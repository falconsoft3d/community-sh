"""
Test mode of a project: anyone asks for a demo on its public page (/<slug>/), the worker copies the
chosen instance into the sibling project with a new admin password, and when its days are over the
demo is stopped (and deleted a week later).
"""
import logging
import secrets
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from .. import task_log
from ..models import Instance
from ..permissions import RESOURCE_NAME_RE
from ..trial_models import TrialRequest

logger = logging.getLogger(__name__)

ONE_DEMO_EVERY = timedelta(days=30)  # one demo a month per email
DEMOS_PER_IP = 3                     # and at most 3 a month from the same address
DELETE_AFTER = timedelta(days=7)     # a stopped demo is deleted a week after it expired
MIN_FREE_MEMORY = 700 * 1024 * 1024  # an Odoo with its PostgreSQL needs about this much to start


def server_limits():
    """(demos per day, demos at once) for the whole server, from Settings → Demos."""
    from ..config_models import GitHubConfig
    from ..permissions import get_global_config
    config = get_global_config()
    if config is None:
        return (GitHubConfig._meta.get_field('trial_max_per_day').default,
                GitHubConfig._meta.get_field('trial_max_active_total').default)
    return config.trial_max_per_day, config.trial_max_active_total


def max_demos_on_server():
    return server_limits()[1]


def demos_today():
    """Demos asked for since midnight, on every project (failed ones don't count)."""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return TrialRequest.objects.filter(created_at__gte=start).exclude(status=TrialRequest.Status.FAILED).count()


CAPTCHA_MAX_AGE = 30 * 60  # seconds to answer it
RESERVED_SLUGS = {'static', 'media', 'api', 'www', 'demo', 'admin'}


def trial_slug_problem(slug, project=None):
    """Why /<slug>/ can't be the demo page of this project ('' when it can)."""
    from django.urls import Resolver404, resolve
    from ..project_models import Project
    try:
        taken = resolve(f'/{slug}/').url_name != 'trial-page'
    except Resolver404:
        taken = False
    if taken or slug in RESERVED_SLUGS:
        return f'«{slug}» ya es una página del panel: elige otra URL.'
    others = Project.objects.filter(trial_slug=slug)
    if project is not None and project.pk:
        others = others.exclude(pk=project.pk)
    if others.exists():
        return 'Otro proyecto ya usa esa URL.'
    return ''


def trial_settings_problems(data, owner, project=None):
    """{field: message} for the test mode settings of a project (web form and API)."""
    problems = {}
    if not data.get('trial_enabled'):
        return problems
    if not data.get('trial_slug'):
        problems['trial_slug'] = 'Indica la URL de la página de demos.'
    target = data.get('trial_target_project')
    if target is None:
        problems['trial_target_project'] = 'Elige el proyecto donde se crearán las demos.'
    elif target.owner_id != getattr(owner, 'pk', owner) or (project is not None and target.pk == project.pk):
        problems['trial_target_project'] = 'Debe ser otro proyecto tuyo (un proyecto hermano).'
    return problems


def make_captcha():
    """A sum of two numbers to solve: (question, signed token). The answer travels only inside the signature."""
    import random
    from django.core import signing
    a, b = random.randint(2, 19), random.randint(2, 19)
    token = signing.dumps({'a': a, 'b': b, 'n': secrets.token_hex(8)}, salt='trial-captcha')
    return f'{a} + {b}', token


def check_captcha(token, answer):
    """The answer is right, the question is recent and was never used before (one request per question)."""
    from django.core import signing
    from django.core.cache import cache
    try:
        data = signing.loads(token or '', salt='trial-captcha', max_age=CAPTCHA_MAX_AGE)
        right = int(str(answer).strip()) == data['a'] + data['b']
    except (signing.BadSignature, ValueError, TypeError, KeyError):
        return False
    return right and cache.add(f'trial-captcha:{data["n"]}', 1, CAPTCHA_MAX_AGE * 2)


def demo_instances(project):
    """What the demo page offers: the running instances of the project, newest Odoo first."""
    instances = list(project.instances.filter(status=Instance.Status.RUNNING))
    return sorted(instances, key=lambda i: (-float(i.odoo_version), i.name))


ACTIVE = Q(status=TrialRequest.Status.PENDING) | Q(status=TrialRequest.Status.READY, instance__isnull=False)


def active_demos(project):
    """Demos of the project that use the server now: being built or running."""
    return project.trial_requests.filter(ACTIVE)


def refusal(project, email, ip):
    """Why this person can't have a demo now ('' when they can)."""
    since = timezone.now() - ONE_DEMO_EVERY
    recent = project.trial_requests.filter(created_at__gte=since).exclude(status=TrialRequest.Status.FAILED)
    previous = recent.filter(email__iexact=email).order_by('created_at').first()
    if previous:
        available = timezone.localtime(previous.created_at + ONE_DEMO_EVERY).strftime('%d/%m/%Y')
        return f'Ya pediste una demo este mes con {email}. Podrás pedir otra a partir del {available}.'
    if ip and recent.filter(ip=ip).count() >= DEMOS_PER_IP:
        return 'Se han pedido demasiadas demos desde tu conexión este mes.'
    per_day, at_once = server_limits()
    if demos_today() >= per_day:
        return 'Hoy ya no se pueden pedir más demos. Vuelve a intentarlo mañana.'
    if active_demos(project).count() >= project.trial_max_active or TrialRequest.objects.filter(ACTIVE).count() >= at_once:
        return 'Ahora mismo no quedan plazas para demos. Vuelve a intentarlo en unos días.'
    return ''


def demo_name(project, trial):
    """slug-company-xxxx: unique, and a valid resource name (subdomain)."""
    base = slugify(trial.company or trial.name).replace('_', '-')[:20].strip('-')
    while True:
        name = '-'.join(part for part in (project.trial_slug, base, secrets.token_hex(2)) if part)[:63].strip('-')
        if RESOURCE_NAME_RE.match(name) and not Instance.objects.filter(name=name).exists():
            return name


def request_demo(project, source, name, email, company='', phone='', ip=None, job_title='', country='', check_ip=True):
    """
    Store the request and queue its build. Returns (TrialRequest, '') or (None, why not).
    The limits are checked and the request stored in one transaction, with the project locked:
    many requests at once can't all slip past the number of places.
    """
    from django.db import transaction
    from ..project_models import Project
    from ..task_models import Task
    from ..tasks import enqueue
    with transaction.atomic():
        project = Project.objects.select_for_update().get(pk=project.pk)
        error = refusal(project, email, ip if check_ip else None)
        if error:
            return None, error
        trial = TrialRequest.objects.create(project=project, source=source, name=name, email=email.lower(),
                                            company=company, job_title=job_title, phone=phone, country=country,
                                            ip=ip, version=source.odoo_version)
        # Their details stay in Contacts, also after the demo is gone
        from ..contact_models import save_contact
        trial.contact = save_contact(trial)
        trial.task = enqueue(Task.Kind.TRIAL, trial=trial.pk)
        trial.save(update_fields=['task', 'contact'])
    return trial, ''


def build_demo(task):
    """Worker: copy the instance into the sibling project and give its admin a new password."""
    from ..services import DockerService
    from ..task_models import Task
    from ..tasks import destroy_instance
    from ..traefik_service import TraefikService
    trial = TrialRequest.objects.select_related('project__trial_target_project', 'source').get(pk=task.params['trial'])
    project, target = trial.project, trial.project.trial_target_project
    name = ''
    try:
        if trial.source is None:
            raise Exception('La instancia que se iba a copiar ya no existe')
        if target is None:
            raise Exception(f'El proyecto «{project.name}» no tiene proyecto de demos')
        import psutil
        if psutil.virtual_memory().available < MIN_FREE_MEMORY:
            raise Exception('El servidor no tiene memoria libre para otra demo')
        name = demo_name(project, trial)
        task_log.line(f'Demo de {trial.source.name} ({trial.source.odoo_version}) para {trial.email} como {name}')
        service = DockerService()
        instance = service.copy_instance(trial.source, name, project=target, create_branch=False, origin='trial')
        instance.owner = target.owner
        instance.save(update_fields=['owner'])
        Task.objects.filter(pk=task.pk).update(instance=instance)
        task_log.progress(90, 'Preparando tu copia')
        # The copy is the visitor's: no working passwords of other users, mail servers or API keys of the template
        for note in service.sanitize_demo(instance):
            task_log.line(note)
        task_log.progress(93, 'Creando tu usuario administrador')
        password = secrets.token_urlsafe(9)
        login = service.set_admin_password(instance, password)
        instance.admin_login, instance.admin_password = login, password
        instance.admin_database = instance.demo_default_db or instance.database_name or ''
        instance.save(update_fields=['admin_login', 'admin_password', 'admin_database'])
        service.restart_instance(instance)  # Odoo caches the system parameters that changed
        task_log.progress(96, 'Publicando la dirección segura (HTTPS)')
        ok, message = TraefikService.generate_instance_config(instance)
        if not ok:
            task_log.line(f'Traefik: {message}')
        trial.instance, trial.admin_login, trial.admin_password = instance, login, password
        trial.status = TrialRequest.Status.READY
        trial.expires_at = timezone.now() + timedelta(days=project.trial_days)
        # The email first: when the page shows the demo ready it can already say it was sent
        task_log.progress(98, 'Enviando tus datos por email')
        sent, error = send_demo_email(trial)
        if sent:
            trial.emailed_at = timezone.now()
            task_log.line(f'Datos de acceso enviados por email a {trial.email}')
        elif error:
            task_log.line(f'No se pudo enviar el email a {trial.email}: {error}')
        trial.save(update_fields=['instance', 'admin_login', 'admin_password', 'status', 'expires_at', 'emailed_at'])
        return f'Demo lista: {instance.url} (vence el {timezone.localtime(trial.expires_at):%d/%m/%Y})'
    except Exception as e:
        # A half-built copy only takes memory: remove it
        leftover = Instance.objects.filter(name=name).first() if name else None
        if leftover is not None:
            try:
                destroy_instance(leftover)
            except Exception:
                logger.exception('Could not remove the failed demo %s', name)
        trial.status, trial.error = TrialRequest.Status.FAILED, str(e)
        trial.save(update_fields=['status', 'error'])
        raise


def public_url(path):
    """https://<platform domain><path> for links in emails (relative when there is no domain)."""
    from .domains import acme_enabled, main_domain
    domain = main_domain()
    return f"{'https' if acme_enabled() else 'http'}://{domain}{path}" if domain else path


def send_demo_email(trial):
    """The credentials of a ready demo to whoever asked for it, when Settings → Email is on. Returns (sent, error)."""
    import html
    from django.urls import reverse
    from . import mail
    if mail.smtp_config() is None or trial.instance is None:
        return False, ''
    project = trial.project
    expires = timezone.localtime(trial.expires_at).strftime('%d/%m/%Y')
    status_link = public_url(reverse('trial-status', args=[project.trial_slug, trial.token]))
    lines = [
        f'Hola {trial.name}:', '',
        f'Tu demo de {project.name} (Odoo {trial.version}) ya está lista.', '',
        f'Dirección:   {trial.instance.url}',
        f'Usuario:     {trial.admin_login}',
        f'Contraseña:  {trial.admin_password}', '',
        f'Puedes usarla hasta el {expires}. Después se detiene y, una semana más tarde, se elimina.',
        f'Estos datos también están en: {status_link}', '',
        'Si no pediste esta demo, ignora este correo.',
    ]
    rows = ''.join(f'<tr><td style="padding:4px 12px 4px 0;color:#64748b">{label}</td>'
                   f'<td style="padding:4px 0;font-family:Menlo,monospace">{html.escape(value)}</td></tr>'
                   for label, value in (('Dirección', trial.instance.url), ('Usuario', trial.admin_login),
                                        ('Contraseña', trial.admin_password)))
    body_html = (
        '<div style="font-family:Helvetica,Arial,sans-serif;color:#0f172a;max-width:560px">'
        f'<h2 style="margin:0 0 12px">Tu demo de {html.escape(project.name)} está lista</h2>'
        f'<p>Hola {html.escape(trial.name)}, ya puedes probar Odoo {html.escape(trial.version)}:</p>'
        f'<table style="border-collapse:collapse;margin:12px 0">{rows}</table>'
        f'<p><a href="{html.escape(trial.instance.url)}" style="display:inline-block;background:#2563eb;color:#fff;'
        'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600">Abrir mi demo</a></p>'
        f'<p style="color:#64748b;font-size:13px">Disponible hasta el {expires}; después se detiene y una semana más tarde se elimina. '
        f'Los datos también están en <a href="{html.escape(status_link)}">esta página</a>. Si no pediste esta demo, ignora este correo.</p></div>')
    return mail.send(f'Tu demo de {project.name} está lista', '\n'.join(lines), trial.email, html=body_html)


def expire_demos(now=None):
    """Scheduled (worker): stop the demos whose days are over and delete those stopped a week ago."""
    from ..services import DockerService
    from ..tasks import destroy_instance
    now = now or timezone.now()
    done = []
    for trial in TrialRequest.objects.filter(status=TrialRequest.Status.READY, expires_at__lte=now).select_related('instance'):
        if trial.instance is not None:
            try:
                DockerService().stop_instance(trial.instance)
            except Exception:
                logger.exception('Could not stop the demo %s', trial.instance.name)
                continue
        trial.status, trial.stopped_at = TrialRequest.Status.EXPIRED, now
        trial.save(update_fields=['status', 'stopped_at'])
        done.append(f'Demo vencida y detenida: {trial.instance.name if trial.instance else trial.email}')
    for trial in TrialRequest.objects.filter(status=TrialRequest.Status.EXPIRED, stopped_at__lte=now - DELETE_AFTER,
                                             instance__isnull=False).select_related('instance'):
        name = trial.instance.name
        try:
            destroy_instance(trial.instance)
            done.append(f'Demo eliminada: {name}')
        except Exception:
            logger.exception('Could not delete the demo %s', name)
    return done


def public_catalog(project, request=None):
    """What the public API and the demo page show of a project in test mode."""
    from django.urls import reverse
    page = reverse('trial-page', args=[project.trial_slug])
    return {
        'name': project.name,
        'slug': project.trial_slug,
        'url': request.build_absolute_uri(page) if request else page,
        'message': project.trial_message,
        'days': project.trial_days,
        'available': active_demos(project).count() < project.trial_max_active,
        'instances': [{
            'id': instance.pk,
            'name': instance.name,
            'version': instance.odoo_version,
            'description': instance.description,
        } for instance in demo_instances(project)],
        'fields': ['name', 'email', 'company', 'job_title', 'phone', 'country', 'instance'],
    }
