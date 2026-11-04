"""Environment variables of an instance: passed to its Odoo container on every deploy.

Written as a .env file, one `NAME=value` per line (blank lines and # comments are ignored,
"export " and surrounding quotes are accepted). The database connection of the official
Odoo image (HOST, USER, PASSWORD, PORT) is set by the platform and can't be overridden.
"""
import re

from django.core.exceptions import ValidationError

RESERVED = ('HOST', 'USER', 'PASSWORD', 'PORT')
MAX_VARIABLES = 50
MAX_VALUE = 4096
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,127}')


def parse_env(text):
    """{name: value} from the text, or ValueError with every wrong line."""
    variables, errors = {}, []
    for number, raw in enumerate((text or '').splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        name, equals, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if not equals:
            errors.append(f'línea {number}: falta «=» (NOMBRE=valor)')
            continue
        if not _NAME.fullmatch(name):
            errors.append(f'línea {number}: «{name[:40]}» no es un nombre válido (letras, números y _, sin empezar por número)')
            continue
        if name.upper() in RESERVED:
            errors.append(f'línea {number}: {name} la pone la plataforma (conexión a la base de datos)')
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if len(value) > MAX_VALUE:
            errors.append(f'línea {number}: el valor de {name} pasa de {MAX_VALUE} caracteres')
            continue
        variables[name] = value
    if len(variables) > MAX_VARIABLES:
        errors.append(f'como mucho {MAX_VARIABLES} variables')
    if errors:
        raise ValueError('; '.join(errors))
    return variables


def validate_env_vars(text):
    try:
        parse_env(text)
    except ValueError as error:
        raise ValidationError(str(error))


def instance_environment(instance):
    """The variables of the instance for its container ({} if the text is somehow wrong)."""
    try:
        return parse_env(instance.env_vars)
    except ValueError:
        return {}
