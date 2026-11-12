"""
Request rate limits: a counter per key and time window in the cache (DatabaseCache in production, shared by the
gunicorn workers). Not exact at the edges of a window, which is enough to stop floods and guessing.
"""
import time

from django.core.cache import cache
from rest_framework.throttling import BaseThrottle

API_PER_MINUTE = 600        # REST API, per user (a script or an AI working hard stays well below)
API_ANON_PER_MINUTE = 60    # REST API without a token, per address
MCP_PER_MINUTE = 300        # MCP, per token
TRIAL_POSTS_PER_HOUR = 20   # public demo requests (form and JSON API), per address: captcha guessing


def hit(key, limit, period):
    """Count one more request for key in the current window of `period` seconds; True when it goes over `limit`."""
    bucket = f'rate:{key}:{int(time.time() // period)}'
    count = (cache.get(bucket) or 0) + 1
    cache.set(bucket, count, period)
    return count > limit


class PanelRateThrottle(BaseThrottle):
    """DRF: per user when authenticated (session or token), per address otherwise."""

    def allow_request(self, request, view):
        from .permissions import client_ip
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            return not hit(f'api:user:{user.pk}', API_PER_MINUTE, 60)
        return not hit(f'api:ip:{client_ip(request)}', API_ANON_PER_MINUTE, 60)

    def wait(self):
        return 60
