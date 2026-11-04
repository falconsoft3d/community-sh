"""
Screenshots for the manual, taken from a panel running locally with the sample data of
seed_demo_data.py (never against a real server: it signs in and fills forms).

    DATABASE_URL=sqlite:////tmp/manual.sqlite3 DEBUG=True MAIN_DOMAIN=communitysh.xyz LETSENCRYPT_EMAIL=x@y.z \
        python manage.py runserver 127.0.0.1:8799
    python scripts/manual/screenshots.py --lang es --out /tmp/shots --tokens /tmp/manual-tokens.txt

Chrome resolves communitysh.xyz to the local panel, so the pages show the real domain.
"""
import argparse
import json
import os

PORT_DEFAULT = 8799
DOMAIN = 'communitysh.xyz'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lang', default='es')
    parser.add_argument('--out', required=True)
    parser.add_argument('--tokens', required=True, help='File with "<building token> <ready token>"')
    parser.add_argument('--port', type=int, default=PORT_DEFAULT)
    parser.add_argument('--user', default='demo')
    parser.add_argument('--password', default='Manual-2026!')
    args = parser.parse_args()
    building, ready = open(args.tokens).read().split()
    out = os.path.join(args.out, args.lang)
    os.makedirs(out, exist_ok=True)
    base = f'http://{DOMAIN}'

    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', args=[f'--host-resolver-rules=MAP {DOMAIN} 127.0.0.1:{args.port}'])

        def context():
            ctx = browser.new_context(viewport={'width': 1366, 'height': 820}, device_scale_factor=2,
                                      locale=args.lang, color_scheme='light')
            ctx.add_cookies([{'name': 'django_language', 'value': args.lang, 'url': base}])
            return ctx

        page = context().new_page()

        def shot(name, url, full=False, before=None, wait=900):
            page.goto(base + url, wait_until='networkidle')
            page.wait_for_timeout(wait)
            if before:
                before()
                page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(out, f'{name}.png'), full_page=full)
            print('ok', name)

        shot('01-landing', '/')
        shot('02-login', '/accounts/login/')
        page.fill('input[name=username]', args.user)
        page.fill('input[name=password]', args.password)
        page.click('button[type=submit]')
        page.wait_for_load_state('networkidle')
        # From here on as if Traefik served it: links and the API show https://
        page.set_extra_http_headers({'X-Forwarded-Proto': 'https'})
        shot('03b-dashboard', '/dashboard/', full=True, wait=1500)
        shot('03-projects', '/projects/')
        shot('04-project-new', '/project/new/')
        shot('06-instance-new', '/instance/new/?project=1', full=True)
        shot('07-instances', '/instances/')
        shot('08-instance-detail', '/instance/4/')
        shot('08b-demo-instance', '/instance/7/')
        shot('09-project-test-mode', '/project/3/edit/', full=True)
        shot('10-project-test-card', '/project/3/', full=True)
        shot('11-backups', '/backups/')
        shot('12-activity', '/activity/')
        shot('13-settings', '/settings/')
        shot('13b-settings-email', '/settings/#email')
        shot('13c-settings-demos', '/settings/#demos')
        shot('14-metrics', '/metrics/', wait=2500)
        shot('15-todo', '/todo/')

        # The public demo pages, as a visitor (no session)
        page = context().new_page()
        page.set_extra_http_headers({'X-Forwarded-Proto': 'https'})

        def fill_demo_form():
            page.check('input[name=instance][value="5"]')
            page.fill('input[name=name]', 'Pedro Gil')
            page.fill('input[name=email]', 'pedro@gilobras.es')
            page.fill('input[name=company]', 'Gil Obras')
            page.fill('input[name=job_title]', 'Arquitecto')
            page.fill('input[name=phone]', '+34 622 333 444')
            page.fill('input[name=country]', 'España')

        shot('16-demo-page', '/bim/', full=True, before=fill_demo_form)
        shot('17-demo-building', f'/bim/demo/{building}/')
        shot('18-demo-ready', f'/bim/demo/{ready}/')
        page.goto(base + '/api/public/demos/bim/')
        data = json.loads(page.inner_text('pre'))
        page.set_content(
            '<body style="margin:0;background:#0f172a;font:15px/1.55 Menlo,monospace;color:#e2e8f0">'
            f'<div style="padding:18px 28px;background:#1e293b;color:#94a3b8">GET https://{DOMAIN}/api/public/demos/bim/'
            ' &nbsp; <span style="color:#4ade80">200 OK</span> · Access-Control-Allow-Origin: *</div>'
            f'<pre style="margin:0;padding:24px 28px;white-space:pre-wrap">{json.dumps(data, indent=2, ensure_ascii=False)}</pre></body>')
        page.screenshot(path=os.path.join(out, '19-api.png'), full_page=True)
        print('ok 19-api')
        browser.close()


if __name__ == '__main__':
    main()
