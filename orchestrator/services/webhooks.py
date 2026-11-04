"""
GitHub push webhooks: a push to one of an instance's repositories (the main one or an addons one, on the
branch the instance uses) queues a pull, and with "update" also `-u all`, when the instance has auto update on.
"""
import hashlib
import hmac
import re

import requests

GITHUB_API = 'https://api.github.com'


def signature_ok(instance, body, header):
    """X-Hub-Signature-256: sha256=HMAC(webhook secret, body)."""
    if not header or not header.startswith('sha256='):
        return False
    expected = hmac.new(instance.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len('sha256='):])


def _normalize(url):
    url = (url or '').strip().lower().rstrip('/')
    url = re.sub(r'^git@github\.com:', 'https://github.com/', url)
    url = re.sub(r'^https?://[^@/]*@', 'https://', url)  # no credentials
    return url.removesuffix('.git')


def repositories(instance):
    """(url, branch) of every repository of the instance."""
    repos = [(instance.github_repo, instance.github_branch or 'main')] if instance.github_repo else []
    repos += [(repository.url, repository.branch) for repository in instance.repositories.all()]
    return repos


def matching_repository(instance, payload):
    """The (url, branch) of the instance this push is for, or None."""
    repository = payload.get('repository') or {}
    urls = {_normalize(repository.get(key)) for key in ('clone_url', 'html_url', 'ssh_url', 'git_url') if repository.get(key)}
    ref = payload.get('ref') or ''
    if not ref.startswith('refs/heads/') or payload.get('deleted'):
        return None
    branch = ref[len('refs/heads/'):]
    for url, repo_branch in repositories(instance):
        if _normalize(url) in urls and repo_branch == branch:
            return url, branch
    return None


def handle_push(instance, payload):
    """Queue the update for a push. Returns (http status, message)."""
    from ..task_models import Task
    from ..tasks import enqueue
    if not instance.auto_update:
        return 202, 'La actualización automática está desactivada en esta instancia'
    match = matching_repository(instance, payload)
    if match is None:
        return 202, 'El push no es de un repositorio y rama de esta instancia: ignorado'
    waiting = instance.tasks.filter(kind=Task.Kind.PULL_REPOS, status=Task.Status.PENDING).first()
    commit = (payload.get('after') or '')[:7]
    label = f"{match[0].rstrip('/').removesuffix('.git').split('/')[-1]}@{match[1]} {commit}".strip()
    if waiting is not None:
        # One queued update covers several pushes in a row (it pulls whatever is there when it runs)
        if instance.auto_update == instance.AutoUpdate.UPDATE_ALL and not waiting.params.get('update_all'):
            waiting.params['update_all'] = True
            waiting.save(update_fields=['params'])
        return 202, f'Ya hay una actualización en cola (tarea {waiting.pk})'
    task = enqueue(Task.Kind.PULL_REPOS, instance, instance.owner, update_all=instance.auto_update == instance.AutoUpdate.UPDATE_ALL,
                   push=label, source='webhook')
    return 202, f'Actualización en cola (tarea {task.pk})'


def _owner_repo(url):
    match = re.match(r'^https://github\.com/([^/]+)/([^/]+?)(\.git)?/?$', (url or '').strip())
    return (match.group(1), match.group(2)) if match else None


def create_github_hooks(instance, hook_url):
    """
    Create (or bring up to date) the push webhook on every GitHub repository of the instance, with the
    owner's token. Returns [(repository, ok, message)]. The token needs admin:repo_hook (classic) or
    Webhooks: read and write (fine-grained) on those repositories.
    """
    from ..config_models import GitHubConfig
    config = GitHubConfig.objects.filter(user=instance.owner).first() if instance.owner_id else None
    token = config.personal_access_token if config else ''
    results = []
    for url, _branch in repositories(instance):
        owner_repo = _owner_repo(url)
        name = url.rstrip('/').removesuffix('.git').split('/')[-1]
        if owner_repo is None:
            results.append((name, False, 'No es un repositorio de GitHub'))
            continue
        if not token:
            results.append((name, False, 'Sin token de GitHub (Configuración → GitHub)'))
            continue
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'}
        hook = {'name': 'web', 'active': True, 'events': ['push'],
                'config': {'url': hook_url, 'content_type': 'json', 'secret': instance.webhook_secret, 'insecure_ssl': '0'}}
        base = f'{GITHUB_API}/repos/{owner_repo[0]}/{owner_repo[1]}/hooks'
        try:
            listing = requests.get(base, headers=headers, timeout=15)
            if listing.status_code in (403, 404):
                results.append((name, False, 'El token no puede gestionar los webhooks de este repositorio '
                                             '(permiso admin:repo_hook, o «Webhooks» en un token fine-grained)'))
                continue
            listing.raise_for_status()
            existing = next((h for h in listing.json() if (h.get('config') or {}).get('url') == hook_url), None)
            if existing:
                response = requests.patch(f"{base}/{existing['id']}", json=hook, headers=headers, timeout=15)
            else:
                response = requests.post(base, json=hook, headers=headers, timeout=15)
            if response.status_code >= 400:
                results.append((name, False, f'GitHub respondió {response.status_code}: {response.text[:200]}'))
            else:
                results.append((name, True, 'Webhook actualizado' if existing else 'Webhook creado'))
        except requests.RequestException as e:
            results.append((name, False, f'No se pudo contactar con GitHub: {e}'))
    return results
