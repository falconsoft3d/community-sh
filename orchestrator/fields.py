"""
Secrets stored encrypted (Fernet: AES-128-CBC + HMAC-SHA256): a copy of the database alone doesn't give away the
SMTP password, the S3 or OpenAI keys, GitHub tokens or the instances' passwords. Encrypted on save and decrypted
on read, so the code that uses them doesn't change. The key is FIELD_ENCRYPTION_KEY of .env (a Fernet key) or,
without it, one derived from DJANGO_SECRET_KEY: keep that key, or the stored secrets can't be read back.
Values written before (plain text, without the prefix) are still read as they are.
"""
import base64
import hashlib
import os

from django.db import models

PREFIX = 'enc:'


def _fernet():
    from cryptography.fernet import Fernet
    from django.conf import settings
    key = os.environ.get('FIELD_ENCRYPTION_KEY', '').strip()
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(f'community-sh-fields:{settings.SECRET_KEY}'.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(value):
    if not value or str(value).startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(str(value).encode()).decode()


def decrypt(value):
    if not value or not str(value).startswith(PREFIX):
        return value
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        # Encrypted with another key (the secret key changed): unreadable, better empty than garbage
        return ''


class EncryptedMixin:
    def from_db_value(self, value, expression, connection):
        return decrypt(value)

    def to_python(self, value):
        return decrypt(super().to_python(value))

    def get_prep_value(self, value):
        return encrypt(super().get_prep_value(value))


class EncryptedCharField(EncryptedMixin, models.CharField):
    """A CharField stored encrypted. max_length is the length of the plain value (validated as usual)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plain_max_length = self.max_length

    def db_type(self, connection):
        # The encrypted value is longer than the plain one: a text column holds it whatever its size
        return models.TextField().db_type(connection)


class EncryptedTextField(EncryptedMixin, models.TextField):
    pass
