"""
Confirm the password (and the 2FA code, when it's on) again before what can't be undone or gives secrets away:
showing passwords, creating tokens, deleting instances, restoring, changing settings or users. A stolen session
or a computer left unlocked isn't enough for those. Signing in counts as a confirmation; it lasts REAUTH_SECONDS.
"""
import time
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

REAUTH_SECONDS = 15 * 60
SESSION_KEY = 'reauth_at'


def mark(request):
    request.session[SESSION_KEY] = int(time.time())


def is_recent(request):
    return time.time() - (request.session.get(SESSION_KEY) or 0) < REAUTH_SECONDS


def safe_next(request, url, default='/'):
    if url and url_has_allowed_host_and_scheme(url, {request.get_host()}, require_https=request.is_secure()):
        return url
    return default


def reauth_url(request):
    # After confirming, back to the page the action came from (a POST can't be replayed: it is clicked again)
    if request.method == 'GET':
        back = request.get_full_path()
    else:
        from urllib.parse import urlsplit
        referer = safe_next(request, request.META.get('HTTP_REFERER', ''))
        parts = urlsplit(referer)
        back = parts.path + (f'?{parts.query}' if parts.query else '')
    return reverse('reauth') + '?' + urlencode({'next': back})


def recent_auth_required(view=None, *, json=False, methods=('POST', 'PUT', 'PATCH', 'DELETE')):
    """Only for a recent confirmation; json=True answers {"reauth": url} (403) for fetch() callers."""
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods or is_recent(request):
                return func(request, *args, **kwargs)
            url = reauth_url(request)
            if json:
                return JsonResponse({'reauth': url, 'error': 'Confirma tu contraseña para continuar'}, status=403)
            messages.info(request, 'Por seguridad, confirma tu contraseña y repite la acción')
            return redirect(url)
        return wrapper
    return decorator(view) if view else decorator
