# Loaded as a server-wide module by Community SH (no install needed).
# The panel signs db:exp:nonce with community_sh_secret (from odoo.conf); a valid,
# unexpired, unused link logs the browser in as the database administrator.
# Kept compatible with Python 2.7 (Odoo 8-10) and 3.5 (Odoo 11/12): no f-strings.
import hashlib
import hmac
import time

import werkzeug.exceptions
import werkzeug.utils

try:
    import odoo
    from odoo import SUPERUSER_ID, api, http
    from odoo.http import request
    from odoo.tools import config
except ImportError:  # Odoo 8-9 are still called openerp
    import openerp as odoo
    from openerp import SUPERUSER_ID, api, http
    from openerp.http import request
    from openerp.tools import config

_used_nonces = {}
PANEL_ADMIN_LOGIN = 'community_sh_admin'


def _registry(db):
    try:
        from odoo.modules.registry import Registry
        return Registry(db)
    except ImportError:
        return odoo.registry(db)


def _panel_admin_password(secret):
    return hmac.new(secret.encode(), b'community-sh-panel-admin', hashlib.sha256).hexdigest()


def _ensure_panel_admin(env, password):
    """
    Odoo 10/11 check the password again on every request, so a session can't simply be
    opened for the admin. Keep a panel-owned administrator instead, with the admin's
    groups and a password derived from the secret; the real admin's password is untouched.
    """
    admin = env['res.users'].browse(SUPERUSER_ID)
    users = env['res.users'].with_context(active_test=False, no_reset_password=True)
    user = users.search([('login', '=', PANEL_ADMIN_LOGIN)], limit=1)
    values = {
        'active': True,
        'groups_id': [(6, 0, admin.groups_id.ids)],
        'company_ids': [(6, 0, admin.company_ids.ids)],
        'company_id': admin.company_id.id,
    }
    if user:
        user.write(values)
    else:
        values.update(name='Administrador (Community SH)', login=PANEL_ADMIN_LOGIN)
        user = users.create(values)
    user.write({'password': password})


def _login_session(session, env, uid, login, db):
    major = odoo.release.version_info[0]
    if major >= 20:
        from odoo.http import session as session_module
        session['pre_login'] = login
        session['pre_uid'] = uid
        session_module.finalize(session, env)
    elif major >= 16:
        session['pre_login'] = login
        session['pre_uid'] = uid
        session.finalize(env)
    else:
        user = env['res.users'].browse(uid)
        session.rotate = True
        session.db = db
        session.uid = uid
        session.login = login
        session.session_token = user._compute_session_token(session.sid)
        session.context = dict(user.context_get())


class CommunityShLogin(http.Controller):

    @http.route('/community_sh/login', type='http', auth='none', csrf=False)
    def login(self, db='', exp='0', nonce='', sig='', **kwargs):
        secret = config.get('community_sh_secret')
        if not secret or not db or not nonce:
            raise werkzeug.exceptions.Forbidden()
        payload = '%s:%s:%s' % (db, exp, nonce)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        now = time.time()
        for used, expiry in list(_used_nonces.items()):
            if expiry < now:
                del _used_nonces[used]
        try:
            expired = float(exp) < now
        except ValueError:
            expired = True
        # Same type on both sides: Python 2 won't compare str with unicode
        if expired or nonce in _used_nonces or not hmac.compare_digest(expected.encode(), sig.encode('ascii', 'replace')):
            raise werkzeug.exceptions.Forbidden('Enlace de acceso no valido o caducado')

        # Odoo 20 can only save a rotated session within a database request: bind the
        # session to the database first and come back through the same link
        if odoo.release.version_info[0] >= 20 and getattr(request, 'db', None) != db:
            request.session.db = db
            return werkzeug.utils.redirect(request.httprequest.full_path)
        _used_nonces[nonce] = float(exp)

        if odoo.release.version_info[0] <= 11:
            # Only (re)create the user when its login fails: rewriting the password on
            # every link would invalidate the sessions already open with it
            password = _panel_admin_password(secret)
            if not request.session.authenticate(db, PANEL_ADMIN_LOGIN, password):
                with _registry(db).cursor() as cr:
                    _ensure_panel_admin(api.Environment(cr, SUPERUSER_ID, {}), password)
                request.session.authenticate(db, PANEL_ADMIN_LOGIN, password)
            return werkzeug.utils.redirect('/web')

        with _registry(db).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            admin = env.ref('base.user_admin', raise_if_not_found=False) or env['res.users'].browse(SUPERUSER_ID)
            _login_session(request.session, env, admin.id, admin.login, db)
        return werkzeug.utils.redirect('/web')
