# -*- coding: utf-8 -*-
# Shared by the model and the controllers. Compatible with Python 2.7 (Odoo 8-10) and 3.5+.
import hashlib
import hmac
import time

try:
    import odoo
    from odoo.tools import config
except ImportError:  # Odoo 8-9 are still called openerp
    import openerp as odoo
    from openerp.tools import config

MAJOR = odoo.release.version_info[0]
MAX_AGE = 300  # seconds a signed request stays valid


def secret():
    return config.get('community_sh_secret') or ''


def sign(body):
    """HMAC of a request body (bytes) with the instance secret shared with the panel."""
    return hmac.new(secret().encode(), body, hashlib.sha256).hexdigest()


def verify(body, signature, timestamp):
    if not secret() or not signature:
        return False
    try:
        fresh = abs(time.time() - float(timestamp)) < MAX_AGE
    except (TypeError, ValueError):
        return False
    return fresh and hmac.compare_digest(sign(body).encode(), signature.encode('ascii', 'replace'))


def note_kwargs(html):
    """message_post arguments for an internal note, across versions."""
    kwargs = {'body': html}
    if MAJOR >= 17:
        kwargs['body_is_html'] = True
    if MAJOR >= 14:
        kwargs['subtype_xmlid'] = 'mail.mt_note'
    else:
        kwargs['subtype'] = 'mail.mt_note'
    kwargs['message_type' if MAJOR >= 9 else 'type'] = 'comment'
    return kwargs


def to_html(text):
    try:
        from html import escape
    except ImportError:  # Python 2
        from cgi import escape
    return escape(text).replace('\n', '<br/>')
