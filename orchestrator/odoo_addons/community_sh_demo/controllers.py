import werkzeug.exceptions
import werkzeug.utils

from odoo import http
from odoo.http import request

try:  # Odoo 20
    from odoo.http.router import db_list
    from odoo.http.session import logout
except ImportError:
    from odoo.http import db_list

    def logout(session):
        session.logout(keep_db=False)


class CommunityShDemo(http.Controller):

    @http.route('/community_sh/demo', type='http', auth='none', csrf=False, sitemap=False)
    def open_demo(self, db='', **kwargs):
        if db not in db_list(force=True):
            raise werkzeug.exceptions.NotFound()
        if request.session.db != db:
            logout(request.session)
            request.session.db = db
        return werkzeug.utils.redirect('/')
