# Home screen: the user's apps (top-level menus) as a grid of icons, with a search box.
# Rendered on the server, so it works the same whatever the web client of the version.
from markupsafe import escape

from odoo import http, release
from odoo.http import request

PAGE = """<!DOCTYPE html>
<html lang="%(lang)s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(company)s</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
         color: #374151; background-color: #dcd8ea;
         background-image:
           linear-gradient(135deg, transparent 0%%, transparent 38%%, rgba(255,255,255,.28) 38%%, rgba(255,255,255,.28) 52%%, transparent 52%%),
           linear-gradient(135deg, transparent 0%%, transparent 58%%, rgba(255,255,255,.18) 58%%, rgba(255,255,255,.18) 70%%, transparent 70%%),
           linear-gradient(160deg, #cfcae4 0%%, #e3e0ef 45%%, #d6d1e8 100%%);
         background-attachment: fixed; }
  header { display: flex; align-items: center; justify-content: flex-end; gap: 14px; padding: 12px 22px; font-size: 14px; }
  header .company { color: #1f2937; }
  header img { width: 30px; height: 30px; border-radius: 4px; object-fit: cover; }
  header a { color: #6b7280; text-decoration: none; display: flex; }
  header a:hover { color: #1f2937; }
  main { max-width: 880px; margin: 0 auto; padding: 40px 24px 64px; }
  .search { display: flex; justify-content: center; height: 0; overflow: hidden; transition: height .15s, margin .15s; }
  .search.open { height: 46px; margin-bottom: 36px; }
  .search input { width: min(560px, 100%%); padding: 11px 16px; border-radius: 6px; border: 1px solid #c9c3dc;
                  background: rgba(255,255,255,.85); color: #1f2937; font-size: 15px; outline: none; }
  .search input:focus { border-color: #714b67; box-shadow: 0 0 0 3px rgba(113,75,103,.15); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(128px, 1fr)); gap: 30px 8px; }
  .app { display: flex; flex-direction: column; align-items: center; gap: 9px; padding: 6px 4px; border-radius: 6px;
         color: #374151; text-decoration: none; outline: none; }
  .app .tile { display: flex; align-items: center; justify-content: center; width: 68px; height: 68px; border-radius: 4px;
         background: #fff; box-shadow: 0 1px 2px rgba(31,41,55,.12), 0 3px 8px rgba(31,41,55,.07); transition: transform .12s, box-shadow .12s; }
  .app .tile img { width: 48px; height: 48px; object-fit: contain; }
  .app:hover .tile, .app:focus-visible .tile { transform: translateY(-2px); box-shadow: 0 2px 4px rgba(31,41,55,.14), 0 8px 18px rgba(31,41,55,.14); }
  .app .placeholder { font-size: 24px; font-weight: 700; color: #714b67; }
  .app span { max-width: 124px; font-size: 14px; text-align: center; line-height: 1.25; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .empty { text-align: center; color: #6b7280; display: none; }
  .version { position: fixed; left: 16px; bottom: 12px; font-size: 12px; color: #6b7280; }
</style></head>
<body>
<header>
  <span class="company">%(company)s</span>
  <img src="/web/image/res.users/%(uid)s/avatar_128" alt="%(user)s" title="%(user)s">
  <a href="/web/session/logout" title="Cerrar sesión" aria-label="Cerrar sesión">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
  </a>
</header>
<main>
  <div class="search" id="search"><input id="q" type="search" placeholder="Buscar aplicación…" aria-label="Buscar aplicación"></div>
  <nav class="grid" id="apps">%(apps)s</nav>
  <p class="empty" id="empty">No hay aplicaciones con ese nombre.</p>
</main>
<footer class="version">Odoo %(version)s (Edición %(edition)s)</footer>
<script>
  // As in Odoo: start typing anywhere to search the apps; Enter opens the first match, Esc closes
  const box = document.getElementById('search'), q = document.getElementById('q'), empty = document.getElementById('empty');
  const apps = [...document.querySelectorAll('.app')];
  function filter() {
    const term = q.value.trim().toLowerCase();
    let shown = 0;
    apps.forEach(a => { const hit = a.dataset.name.includes(term); a.style.display = hit ? '' : 'none'; shown += hit; });
    empty.style.display = shown ? 'none' : 'block';
    if (!term) box.classList.remove('open');
  }
  q.addEventListener('input', filter);
  document.addEventListener('keydown', e => {
    if (e.target === q) {
      if (e.key === 'Enter') { const first = apps.find(a => a.style.display !== 'none'); if (first) first.click(); }
      if (e.key === 'Escape') { q.value = ''; filter(); q.blur(); }
      return;
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { box.classList.add('open'); q.focus(); }
  });
</script>
</body></html>"""


def _icon(menu):
    if menu.web_icon_data:
        # Served by /web/image: Odoo 20 reads binary fields as attachment objects, not base64
        return '<span class="tile"><img src="/web/image/ir.ui.menu/%d/web_icon_data" alt=""></span>' % menu.id
    if menu.web_icon and ',' in menu.web_icon and not menu.web_icon.startswith('fa'):
        module, path = menu.web_icon.split(',', 1)
        return '<span class="tile"><img src="/%s/%s" alt=""></span>' % (escape(module), escape(path))
    return '<span class="tile placeholder">%s</span>' % escape((menu.name or '?')[:1].upper())


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
        enterprise = env['ir.module.module'].sudo().search_count([('name', '=', 'web_enterprise'), ('state', '=', 'installed')])
        html = PAGE % {'lang': escape((user.lang or 'en')[:2]), 'company': escape(user.company_id.name),
                       'uid': user.id, 'user': escape(user.name), 'apps': apps,
                       'version': escape(release.version), 'edition': 'Enterprise' if enterprise else 'Community'}
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])
