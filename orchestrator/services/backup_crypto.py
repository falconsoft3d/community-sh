"""
Encryption of the copies sent to S3, with a passphrase chosen in Settings → Respaldos (not the server's keys, so a
copy can be decrypted on another server, or anywhere with Python and `cryptography`):

    python backup_crypto.py decrypt <file.enc> <output>      # asks for the passphrase (or CSH_BACKUP_PASSPHRASE)

Format: b'CSHENC1\\n' + 16-byte salt + 8-byte nonce prefix, then records of a 4-byte big-endian length and an
AES-256-GCM ciphertext of up to 1 MiB of plaintext. The key comes from the passphrase with scrypt; each chunk's
nonce is the prefix and its 4-byte counter, and its associated data says whether it is the last one, so a copy
that was cut short, reordered or altered doesn't decrypt.
"""
import math
import os
import struct

MAGIC = b'CSHENC1\n'
SALT_SIZE = 16
PREFIX_SIZE = 8
CHUNK = 1024 * 1024
TAG_SIZE = 16
HEADER_SIZE = len(MAGIC) + SALT_SIZE + PREFIX_SIZE
SUFFIX = '.enc'


class DecryptionError(Exception):
    pass


def _key(passphrase, salt):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode())


def _nonce(prefix, counter):
    return prefix + struct.pack('>I', counter)


def encrypted_size(plain_size):
    """The size of the encrypted file for a plain file of this size."""
    chunks = max(1, math.ceil(plain_size / CHUNK))
    return HEADER_SIZE + chunks * (4 + TAG_SIZE) + plain_size


def is_encrypted(path):
    with open(path, 'rb') as f:
        return f.read(len(MAGIC)) == MAGIC


def encrypt_file(source, target, passphrase):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not passphrase:
        raise ValueError('Falta la frase de cifrado')
    salt, prefix = os.urandom(SALT_SIZE), os.urandom(PREFIX_SIZE)
    aes = AESGCM(_key(passphrase, salt))
    with open(source, 'rb') as src, open(target, 'wb') as out:
        out.write(MAGIC + salt + prefix)
        counter, chunk = 0, src.read(CHUNK)
        while True:
            following = src.read(CHUNK)
            last = not following
            data = aes.encrypt(_nonce(prefix, counter), chunk, b'last' if last else b'more')
            out.write(struct.pack('>I', len(data)) + data)
            if last:
                break
            counter, chunk = counter + 1, following
    os.chmod(target, 0o600)
    return target


def decrypt_file(source, target, passphrase):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with open(source, 'rb') as src:
        header = src.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE or not header.startswith(MAGIC):
            raise DecryptionError('No es una copia cifrada por Community SH')
        salt, prefix = header[len(MAGIC):len(MAGIC) + SALT_SIZE], header[len(MAGIC) + SALT_SIZE:]
        aes = AESGCM(_key(passphrase or '', salt))
        counter, finished = 0, False
        with open(target, 'wb') as out:
            while True:
                size = src.read(4)
                if not size:
                    break
                if finished or len(size) != 4:
                    raise DecryptionError('La copia está dañada')
                data = src.read(struct.unpack('>I', size)[0])
                for flag in (b'more', b'last'):
                    try:
                        out.write(aes.decrypt(_nonce(prefix, counter), data, flag))
                        finished = flag == b'last'
                        break
                    except InvalidTag:
                        continue
                else:
                    raise DecryptionError('Frase de cifrado incorrecta o copia dañada')
                counter += 1
        if not finished:
            raise DecryptionError('La copia está incompleta')
    return target


if __name__ == '__main__':
    import getpass
    import sys
    if len(sys.argv) != 4 or sys.argv[1] not in ('encrypt', 'decrypt'):
        sys.exit('Uso: python backup_crypto.py decrypt|encrypt <entrada> <salida>')
    phrase = os.environ.get('CSH_BACKUP_PASSPHRASE') or getpass.getpass('Frase de cifrado: ')
    try:
        (decrypt_file if sys.argv[1] == 'decrypt' else encrypt_file)(sys.argv[2], sys.argv[3], phrase)
    except DecryptionError as e:
        sys.exit(str(e))
    print(f'Listo: {sys.argv[3]}')
