"""
The second factor: a code of the authenticator app (TOTP) or, when the phone is lost, a single-use recovery code.
"""
import hashlib
import secrets

import pyotp

RECOVERY_CODES = 10
RECOVERY_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'


def _normalize(code):
    return (code or '').strip().lower().replace(' ', '').replace('-', '')


def _hash(code):
    return hashlib.sha256(_normalize(code).encode()).hexdigest()


def new_recovery_codes(profile):
    """Replace the recovery codes with 10 new ones; returns them in plain text (shown once, stored hashed)."""
    codes = [''.join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10)) for _ in range(RECOVERY_CODES)]
    codes = [f'{code[:5]}-{code[5:]}' for code in codes]
    profile.two_factor_recovery_codes = [_hash(code) for code in codes]
    profile.save(update_fields=['two_factor_recovery_codes'])
    return codes


def verify_code(user, code):
    """
    True for a current code of the app (each one works once) or an unused recovery code (then spent).
    """
    from django.core.cache import cache
    profile = getattr(user, 'profile', None)
    code = _normalize(code)
    if not (profile and profile.two_factor_enabled and profile.two_factor_secret and code):
        return False
    if code.isdigit() and len(code) == 6:
        if not pyotp.TOTP(profile.two_factor_secret).verify(code, valid_window=1):
            return False
        # A code seen on the way (shoulder, logs) can't be used again while it is still valid
        return cache.add(f'totp-used:{user.pk}:{code}', 1, 120)
    hashed = _hash(code)
    remaining = list(profile.two_factor_recovery_codes or [])
    if hashed not in remaining:
        return False
    remaining.remove(hashed)
    profile.two_factor_recovery_codes = remaining
    profile.save(update_fields=['two_factor_recovery_codes'])
    return True
