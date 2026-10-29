"""GitHub helpers."""
import shutil
import subprocess
import tempfile


def authed_url(repo_url, token):
    """
    HTTPS URL with the token as the password: fine-grained tokens (github_pat_...) are rejected
    as the user name, with a misleading "Write access to repository not granted" (403).
    """
    if not token or not repo_url.startswith('https://'):
        return repo_url
    return repo_url.replace('https://', f'https://x-access-token:{token}@', 1)


def create_branch(repo_url, base_branch, new_branch, token):
    """Create new_branch from base_branch on the remote. Returns (ok, message)."""
    clone_url = authed_url(repo_url, token)
    temp_git_dir = tempfile.mkdtemp()
    try:
        subprocess.run(
            ['git', 'clone', '--branch', base_branch, '--single-branch', clone_url, temp_git_dir],
            check=True, capture_output=True, text=True
        )
        subprocess.run(
            ['git', 'checkout', '-b', new_branch],
            check=True, capture_output=True, text=True, cwd=temp_git_dir
        )
        subprocess.run(
            ['git', 'push', 'origin', new_branch],
            check=True, capture_output=True, text=True, cwd=temp_git_dir
        )
        return True, f'Rama de GitHub "{new_branch}" creada'
    except subprocess.CalledProcessError as e:
        # git may echo the remote URL, which contains the token
        error = (e.stderr or str(e)).replace(token, '***')
        return False, f'No se pudo crear la rama "{new_branch}" en GitHub: {error.strip()}'
    finally:
        shutil.rmtree(temp_git_dir, ignore_errors=True)
