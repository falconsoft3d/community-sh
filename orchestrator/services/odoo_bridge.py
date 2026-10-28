"""
Signed calls between the panel and the community_sh_ai module of an instance's Odoo: requests
written as "/ia ..." in a chatter come in; the assistant's answer and model introspection go out.
Both sides sign "<timestamp>.<body>" with the instance's admin_login_secret.
"""
import hashlib
import hmac
import html
import json
import time
import urllib.request

from .docker_service import admin_login_secret

MAX_AGE = 300


def odoo_url(instance):
    return f'http://odoo_{instance.name}:8069'


def _signature(instance, timestamp, body):
    return hmac.new(admin_login_secret(instance).encode(), timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()


def verify(instance, body, timestamp, signature):
    try:
        fresh = abs(time.time() - float(timestamp)) < MAX_AGE
    except (TypeError, ValueError):
        return False
    return fresh and bool(signature) and hmac.compare_digest(_signature(instance, timestamp, body), signature)


def _post(instance, path, data, timeout=30, retries=0):
    """
    Signed POST to the module. Sent as text/plain: up to Odoo 15 an application/json body is
    dispatched as JSON-RPC and never reaches a type='http' route.
    """
    import urllib.error
    body = json.dumps(data).encode()
    for attempt in range(retries + 1):
        timestamp = str(int(time.time()))
        request = urllib.request.Request(odoo_url(instance) + path, body, {
            'Content-Type': 'text/plain; charset=utf-8', 'X-CSH-Timestamp': timestamp,
            'X-CSH-Signature': _signature(instance, timestamp, body),
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.URLError as e:
            # Odoo restarts after installing a module: wait for it to come back
            if attempt == retries or isinstance(e, urllib.error.HTTPError) and e.code < 500:
                raise
            time.sleep(5)


def databases(instance):
    if instance.database_name:
        return [instance.database_name]
    try:
        request = urllib.request.Request(odoo_url(instance) + '/web/database/list', json.dumps(
            {'jsonrpc': '2.0', 'method': 'call', 'params': {}}).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response).get('result') or []
    except Exception:
        return []


def post_reply(instance, db, model, res_id, text):
    """Publish the assistant's answer as a note in the chatter the request came from."""
    markup = '\U0001F916 ' + html.escape(text).replace('\n', '<br/>')
    return _post(instance, '/community_sh/ai/reply', {'db': db, 'model': model, 'res_id': res_id, 'html': markup}, retries=24)


def model_info(instance, model, db=None):
    """Fields and main views of a model in the instance's Odoo, as text for the assistant."""
    db = db or next(iter(databases(instance)), None)
    if not db:
        return 'Error: la instancia no tiene base de datos'
    data = _post(instance, '/community_sh/ai/introspect', {'db': db, 'model': model})
    if data.get('error'):
        return f"Error: {data['error']}"
    views = [f"- {v['type']}: {v['xml_id'] or '(sin xml_id)'} «{v['name']}» prioridad {v['priority']}" for v in data['views']]
    fields = [f"- {f['name']} ({f['type']}{', ' + f['relation'] if f.get('relation') else ''}) «{f['string']}»"
              + (' obligatorio' if f.get('required') else '') for f in data['fields'][:400]]
    return (f'Base de datos {db}, modelo {model}.\nVistas principales (hereda de ellas con inherit_id):\n'
            + '\n'.join(views or ['(ninguna)']) + '\nCampos:\n' + '\n'.join(fields))
