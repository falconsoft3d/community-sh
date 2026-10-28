# -*- coding: utf-8 -*-
# "/ia ..." in a chatter sends the request to the panel's AI assistant for this instance.
import json
import logging
import re
import time

import requests

from .common import MAJOR, config, note_kwargs, sign, to_html

try:
    from odoo import api, models
except ImportError:
    from openerp import api, models

_logger = logging.getLogger(__name__)
COMMAND = re.compile(r'^\s*[/@]ia\b[:,]?\s*', re.I)


def _plain(html):
    text = re.sub(r'<br\s*/?>|</p>|</div>', '\n', html or '', flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    try:
        from html import unescape
    except ImportError:  # Python 2
        from HTMLParser import HTMLParser
        unescape = HTMLParser().unescape
    return unescape(text).strip()


def _note(record, text):
    record.sudo().message_post(**note_kwargs(u'\U0001F916 ' + to_html(text)))


def _request(record, text):
    """Send the request to the panel and leave its answer (received / error) as a note."""
    if not record.env.user.has_group('base.group_system'):
        return _note(record, u'Solo los administradores pueden pedir cambios al asistente de IA.')
    panel, instance = config.get('community_sh_panel_url'), config.get('community_sh_instance')
    if not (panel and instance and text):
        return _note(record, u'Escribe lo que quieres después de /ia, por ejemplo: «/ia añade una columna Código a esta lista».')
    payload = json.dumps({
        'db': record.env.cr.dbname, 'model': record._name, 'res_id': record.id,
        'record': record.display_name, 'login': record.env.user.login, 'text': text,
    }).encode()
    timestamp = str(int(time.time()))
    try:
        response = requests.post(
            '%s/odoo-ai/%s/' % (panel.rstrip('/'), instance), data=payload, timeout=10,
            headers={'Content-Type': 'application/json', 'X-CSH-Timestamp': timestamp,
                     'X-CSH-Signature': sign(timestamp.encode() + b'.' + payload)})
        answer = response.json().get('message') or response.text[:300]
    except Exception as error:
        answer = u'No se pudo contactar con Community SH: %s' % error
    _note(record, answer)


if MAJOR >= 9:  # Odoo 8 messages use the old API
    # Hooked on mail.message rather than mail.thread: in Odoo 9 extending the mixin doesn't reach
    # the models that already inherited it, and every chatter post creates a message anyway
    class MailMessage(models.Model):
        _inherit = 'mail.message'

        def _community_sh_ai_check(self):
            for message in self:
                if message.message_type != 'comment' or not message.model or not message.res_id:
                    continue
                text = _plain(message.body or u'')
                if COMMAND.match(text):
                    record = self.env[message.model].browse(message.res_id)
                    try:
                        _request(record, COMMAND.sub('', text, count=1))
                    except Exception:
                        _logger.exception('Community SH AI request failed')

        if MAJOR >= 12:
            @api.model_create_multi
            def create(self, vals_list):
                messages = super(MailMessage, self).create(vals_list)
                messages._community_sh_ai_check()
                return messages
        else:
            @api.model
            def create(self, values):
                message = super(MailMessage, self).create(values)
                message._community_sh_ai_check()
                return message
