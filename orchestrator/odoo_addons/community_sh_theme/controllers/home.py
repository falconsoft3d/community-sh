# Home screen: the user's apps (top-level menus) as a grid of icons, with a search box.
# Rendered on the server, so it works the same whatever the web client of the version.
from markupsafe import escape

from odoo import http, release
from odoo.http import request

PAGE = """<!DOCTYPE html>
<html lang="%(lang)s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(company)s</title>
<style>
  :root { --ink: #1f2937; --muted: #6b7280; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: #fff;
         background: radial-gradient(1200px 600px at 10%% -10%%, #8f6a87 0%%, transparent 60%%),
                     radial-gradient(900px 500px at 110%% 10%%, #3f8f8a 0%%, transparent 55%%),
                     linear-gradient(160deg, #4b3248 0%%, #2f2a3d 55%%, #1f2b33 100%%); }
  header { display: flex; align-items: center; justify-content: space-between; padding: 18px 28px; }
  header .company { font-weight: 600; letter-spacing: .2px; opacity: .95; }
  header .user { display: flex; align-items: center; gap: 10px; font-size: 14px; opacity: .9; }
  header .user img { width: 32px; height: 32px; border-radius: 50%%; border: 2px solid rgba(255,255,255,.4); }
  header a { color: #fff; text-decoration: none; opacity: .8; font-size: 13px; }
  main { max-width: 980px; margin: 0 auto; padding: 24px 24px 64px; }
  .search { display: flex; justify-content: center; margin: 8px 0 40px; }
  .search input { width: min(520px, 100%%); padding: 12px 18px; border-radius: 999px; border: 1px solid rgba(255,255,255,.25);
                  background: rgba(255,255,255,.12); color: #fff; font-size: 15px; outline: none; backdrop-filter: blur(8px); }
  .search input::placeholder { color: rgba(255,255,255,.7); }
  .search input:focus { background: rgba(255,255,255,.2); border-color: rgba(255,255,255,.5); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); gap: 28px 12px; }
  .app { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 10px 6px; border-radius: 16px;
         color: #fff; text-decoration: none; transition: background .15s, transform .15s; }
  .app:hover, .app:focus-visible { background: rgba(255,255,255,.1); transform: translateY(-2px); outline: none; }
  .app img, .app .placeholder { width: 72px; height: 72px; border-radius: 18px; background: #fff;
         box-shadow: 0 10px 24px -8px rgba(0,0,0,.45); object-fit: cover; }
  .app .placeholder { display: flex; align-items: center; justify-content: center; font-size: 28px; font-weight: 700; color: #714b67; }
  .app span { font-size: 13.5px; text-align: center; line-height: 1.25; text-shadow: 0 1px 2px rgba(0,0,0,.35); }
  .empty { text-align: center; opacity: .8; display: none; }
</style></head>
<body>
<header><div class="company">%(company)s</div>
  <div class="user"><img src="/web/image/res.users/%(uid)s/avatar_128" alt=""><span>%(user)s</span><a href="/web/session/logout">Salir</a></div></header>
<main>
  <div class="search"><input id="q" type="search" placeholder="Buscar aplicación…" aria-label="Buscar aplicación" autofocus></div>
  <nav class="grid" id="apps">%(apps)s</nav>
  <p class="empty" id="empty">No hay aplicaciones con ese nombre.</p>
</main>
<script>
  const q = document.getElementById('q'), apps = [...document.querySelectorAll('.app')], empty = document.getElementById('empty');
  q.addEventListener('input', () => {
    const term = q.value.trim().toLowerCase();
    let shown = 0;
    apps.forEach(a => { const hit = a.dataset.name.includes(term); a.style.display = hit ? '' : 'none'; shown += hit; });
    empty.style.display = shown ? 'none' : 'block';
  });
  q.addEventListener('keydown', e => { if (e.key === 'Enter') { const first = apps.find(a => a.style.display !== 'none'); if (first) first.click(); } });
</script>
</body></html>"""


def _icon(menu):
    if menu.web_icon_data:
        data = menu.web_icon_data.decode() if isinstance(menu.web_icon_data, bytes) else menu.web_icon_data
        return '<img src="data:image/png;base64,%s" alt="">' % data
    if menu.web_icon and ',' in menu.web_icon and not menu.web_icon.startswith('fa'):
        module, path = menu.web_icon.split(',', 1)
        return '<img src="/%s/%s" alt="">' % (escape(module), escape(path))
    return '<div class="placeholder">%s</div>' % escape((menu.name or '?')[:1].upper())


def _app_action(menu):
    """The action Odoo opens for an app: its own, or that of its first submenu that has one."""
    if menu.action:
        return menu.action
    for child in menu.child_id:  # ordered by sequence, as in the web client
        action = _app_action(child)
        if action:
            return action
    return None


def _app_url(menu):
    # Without an action the web client opens the home screen (this grid) again
    action = _app_action(menu)
    if not action:
        return '/web#menu_id=%d' % menu.id
    if release.version_info[0] >= 18:
        return '/odoo/action-%d' % action.id
    return '/web#menu_id=%d&action=%d' % (menu.id, action.id)


class CommunityShHome(http.Controller):

    @http.route('/community_sh/home', type='http', auth='user')
    def home(self, **kwargs):
        env = request.env
        own = env.ref('community_sh_theme.menu_home_screen', raise_if_not_found=False)
        # ir.ui.menu only returns the menus the user may see
        menus = env['ir.ui.menu'].search([('parent_id', '=', False)]).filtered(lambda m: m != own)
        apps = ''.join(
            '<a class="app" href="%s" data-name="%s">%s<span>%s</span></a>'
            % (escape(_app_url(menu)), escape(menu.name.lower()), _icon(menu), escape(menu.name)) for menu in menus)
        user = env.user
        html = PAGE % {'lang': escape((user.lang or 'en')[:2]), 'company': escape(user.company_id.name),
                       'uid': user.id, 'user': escape(user.name), 'apps': apps}
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])
