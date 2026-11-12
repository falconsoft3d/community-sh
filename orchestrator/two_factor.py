"""The second factor: a code of the authenticator app (TOTP)."""
import pyotp


def verify_code(user, code):
    profile = getattr(user, 'profile', None)
    code = (code or '').strip().replace(' ', '')
    if not (profile and profile.two_factor_enabled and profile.two_factor_secret and code):
        return False
    return pyotp.TOTP(profile.two_factor_secret).verify(code, valid_window=1)
