from . import controllers
from odoo import SUPERUSER_ID, api


def _env(env_or_cr):
    # The hooks get (cr, registry) up to Odoo 16 and env from 17
    return env_or_cr if hasattr(env_or_cr, 'cr') else api.Environment(env_or_cr, SUPERUSER_ID, {})


def set_home_screen(env_or_cr, registry=None):
    """The app grid becomes the home screen of internal users who don't have one of their own."""
    env = _env(env_or_cr)
    action = env.ref('community_sh_theme.action_home_screen')
    env['res.users'].with_context(active_test=False).search([('share', '=', False), ('action_id', '=', False)]).write(
        {'action_id': action.id})


def reset_home_screen(env_or_cr, registry=None):
    env = _env(env_or_cr)
    action = env.ref('community_sh_theme.action_home_screen', raise_if_not_found=False)
    if action:
        env['res.users'].with_context(active_test=False).search([('action_id', '=', action.id)]).write({'action_id': False})
