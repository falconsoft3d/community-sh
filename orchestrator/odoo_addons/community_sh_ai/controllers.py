# -*- coding: utf-8 -*-
# Signed endpoints the panel calls: model fields and views for the assistant, and its answer
# posted back in the chatter where the request was written.
import json

import werkzeug.exceptions
import werkzeug.wrappers

from .common import note_kwargs, verify

try:
    import odoo
    from odoo import SUPERUSER_ID, api, http
    from odoo.http import request
except ImportError:  # Odoo 8-9
    import openerp as odoo
    from openerp import SUPERUSER_ID, api, http
    from openerp.http import request


def _registry(db):
    try:
        from odoo.modules.registry import Registry
        return Registry(db)
    except ImportError:
        return odoo.registry(db)


def _payload():
    body = request.httprequest.get_data()
    headers = request.httprequest.headers
    timestamp = headers.get('X-CSH-Timestamp', '')
    if not verify(timestamp.encode() + b'.' + body, headers.get('X-CSH-Signature'), timestamp):
        raise werkzeug.exceptions.Forbidden()
    return json.loads(body.decode('utf-8'))


def _json(data):
    return werkzeug.wrappers.Response(json.dumps(data), mimetype='application/json')


class CommunityShAI(http.Controller):

    @http.route('/community_sh/ai/introspect', type='http', auth='none', methods=['POST'], csrf=False)
    def introspect(self, **kwargs):
        data = _payload()
        with _registry(data['db']).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            if data['model'] not in env:
                return _json({'error': 'Model %s does not exist' % data['model']})
            fields = env[data['model']].fields_get(attributes=['string', 'type', 'relation', 'required'])
            views = env['ir.ui.view'].search([('model', '=', data['model']), ('inherit_id', '=', False)])
            xml_ids = views.get_external_id()
            return _json({
                'fields': [dict(name=name, **info) for name, info in sorted(fields.items())],
                'views': [{'xml_id': xml_ids.get(view.id) or '', 'type': view.type, 'name': view.name,
                           'priority': view.priority} for view in views],
            })

    @http.route('/community_sh/ai/reply', type='http', auth='none', methods=['POST'], csrf=False)
    def reply(self, **kwargs):
        data = _payload()
        with _registry(data['db']).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            record = env[data['model']].browse(int(data['res_id'])).exists()
            if not record:
                return _json({'error': 'Record not found'})
            author = env.ref('base.partner_root', raise_if_not_found=False)
            kwargs = note_kwargs(data['html'])
            if author:
                kwargs['author_id'] = author.id
            record.message_post(**kwargs)
        return _json({'ok': True})
