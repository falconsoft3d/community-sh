import re

try:
    from odoo.http.router import Application  # Odoo 20
except ImportError:
    from odoo.http import Application

from odoo.tools import config

from . import controllers  # noqa: F401

DEMO_QUERY = re.compile(r'^[a-z0-9][a-z0-9_-]*$')


def _wrap_application():
    """ /?shop goes to the route that opens the database shop (Odoo only reads the database from the session). """
    original = Application.__call__

    def __call__(self, environ, start_response):
        query = environ.get('QUERY_STRING', '')
        path = environ.get('PATH_INFO')
        default = config.get('community_sh_demo_default')
        if path == '/' and DEMO_QUERY.match(query):
            environ['PATH_INFO'] = '/community_sh/demo'
            environ['QUERY_STRING'] = 'db=%s' % query
        elif path == '/web/database/selector' and default:
            # A browser without a database: the demo by default, never the list of databases
            environ['PATH_INFO'] = '/community_sh/demo'
            environ['QUERY_STRING'] = 'db=%s' % default
        return original(self, environ, start_response)

    Application.__call__ = __call__


_wrap_application()
