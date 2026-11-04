"""
Build the user manual PDFs (Spanish and English) from content.py and the screenshots.

    python scripts/manual/build_manual.py --shots <dir with es/ and en/ screenshots> \
        --out orchestrator/static/manual

Needs playwright (pip install playwright) and Pillow, and uses the installed Google Chrome.
The screenshots come from screenshots.py (see its docstring).
"""
import argparse
import base64
import datetime
import html
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content import MANUAL, SECURITY  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm; }
* { box-sizing: border-box; }
body { font-family: 'Inter', -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; color: #0f172a; font-size: 10.5pt; line-height: 1.55; margin: 0; }
.cover { height: 255mm; display: flex; flex-direction: column; justify-content: space-between; page-break-after: always; }
.cover .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 13pt; color: #2563eb; }
.cover .logo { width: 34px; height: 34px; border-radius: 9px; background: #2563eb; display: inline-flex; align-items: center; justify-content: center; }
.cover h1 { font-size: 34pt; line-height: 1.1; margin: 0 0 10px; letter-spacing: -0.02em; }
.cover .subtitle { font-size: 14pt; color: #475569; max-width: 140mm; }
.cover .hero { border-radius: 14px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 10px 30px rgba(15, 23, 42, .12); }
.cover .hero img { width: 100%; display: block; max-height: 120mm; object-fit: cover; object-position: top; }
.cover .meta { color: #64748b; font-size: 10pt; }
.toc { page-break-after: always; }
.toc h2 { font-size: 20pt; margin: 0 0 14px; }
.toc ol { padding-left: 0; list-style: none; counter-reset: toc; }
.toc li { counter-increment: toc; display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid #e2e8f0; font-size: 11.5pt; }
.toc li::before { content: counter(toc, decimal-leading-zero); color: #2563eb; font-weight: 700; min-width: 26px; }
.toc a { color: inherit; text-decoration: none; }
section { page-break-before: always; }
section h2 { font-size: 19pt; margin: 0 0 6px; letter-spacing: -0.01em; display: flex; align-items: baseline; gap: 10px; }
section h2 .num { color: #2563eb; font-size: 13pt; font-weight: 700; }
.intro { color: #334155; font-size: 11pt; margin: 0 0 12px; }
ol.steps { list-style: none; padding: 0; margin: 0 0 12px; counter-reset: step; }
ol.steps li { counter-increment: step; position: relative; padding: 4px 0 4px 34px; }
ol.steps li::before { content: counter(step); position: absolute; left: 0; top: 4px; width: 22px; height: 22px; border-radius: 50%;
    background: #2563eb; color: white; font-size: 9pt; font-weight: 700; display: flex; align-items: center; justify-content: center; }
figure { margin: 12px 0 14px; page-break-inside: avoid; }
figure img { max-width: 100%; max-height: 138mm; width: auto; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 10px; display: block; box-shadow: 0 4px 14px rgba(15, 23, 42, .08); }
figcaption { text-align: center; }
figcaption { font-size: 9pt; color: #64748b; margin-top: 5px; }
figcaption b { color: #334155; }
.tip { border-left: 4px solid #2563eb; background: #eff6ff; padding: 8px 12px; border-radius: 6px; font-size: 10pt; margin: 10px 0; page-break-inside: avoid; }
.tip b { color: #1d4ed8; }
.columns { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.box { border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; }
.box h3 { margin: 0 0 8px; font-size: 12pt; }
.box ul { margin: 0; padding-left: 18px; }
.box li { margin: 4px 0; font-size: 9.8pt; }
.box.ok h3 { color: #15803d; }
.box.you h3 { color: #b45309; }
code { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 9pt; background: #f1f5f9; padding: 1px 4px; border-radius: 4px; }
"""


def image_data(path, max_width=1800):
    """The screenshot as an embedded JPEG (retina PNGs would make the PDF huge)."""
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert('RGB')
        if image.width > max_width:
            image = image.resize((max_width, round(image.height * max_width / image.width)), Image.LANCZOS)
        # Very tall full-page captures: keep the top part, which is what the text describes
        if image.height > image.width * 1.5:
            image = image.crop((0, 0, image.width, int(image.width * 1.5)))
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=80, optimize=True, progressive=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode()


def code(text):
    """Escape, and show URLs, paths and settings as code."""
    import re
    escaped = html.escape(text)
    return re.sub(r'(https?://[\w./?=&{}#:-]+[\w/}]|(?<![\w/])/[a-z][\w./?=&{}#:-]*[\w/}]|\b[A-Z_]{6,}=?[\w.]*|fetch\([^)]*\)\.then\([^)]*\)\))', r'<code>\1</code>', escaped)


def build_html(lang, shots_dir, version):
    text = MANUAL[lang]
    figure_number = 0
    parts = [f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8"><title>{html.escape(text["title"])}</title>',
             f'<style>{CSS}</style></head><body>']
    cover_shot = os.path.join(shots_dir, lang, '10-project-test-card.png')
    today = datetime.date.today()
    date = today.strftime('%d/%m/%Y') if lang == 'es' else today.strftime('%B %d, %Y')
    parts.append(f'''<div class="cover">
        <div class="brand"><span class="logo"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg></span> Community SH</div>
        <div><h1>{html.escape(text["title"])}</h1><p class="subtitle">{html.escape(text["subtitle"])}</p></div>
        <div class="hero"><img src="{image_data(cover_shot)}"></div>
        <p class="meta">v{version} · {date} · https://communitysh.xyz</p>
    </div>''')
    parts.append(f'<div class="toc"><h2>{text["toc"]}</h2><ol>')
    for index, section in enumerate(text['sections'], 1):
        parts.append(f'<li><a href="#s{index}">{html.escape(section["title"])}</a></li>')
    parts.append('</ol></div>')
    for index, section in enumerate(text['sections'], 1):
        parts.append(f'<section id="s{index}"><h2><span class="num">{index:02d}</span>{html.escape(section["title"])}</h2>')
        parts.append(f'<p class="intro">{code(section["intro"])}</p>')
        if section['steps']:
            parts.append('<ol class="steps">' + ''.join(f'<li>{code(step)}</li>' for step in section['steps']) + '</ol>')
        if section.get('security'):
            security = SECURITY[lang]
            parts.append('<div class="columns">')
            parts.append(f'<div class="box ok"><h3>✓ {security["built_in_title"]}</h3><ul>'
                         + ''.join(f'<li>{code(item)}</li>' for item in security['built_in']) + '</ul></div>')
            parts.append(f'<div class="box you"><h3>→ {security["yours_title"]}</h3><ul>'
                         + ''.join(f'<li>{code(item)}</li>' for item in security['yours']) + '</ul></div>')
            parts.append('</div>')
        if section.get('tip'):
            parts.append(f'<div class="tip"><b>{text["tip"]}:</b> {code(section["tip"])}</div>')
        for shot, caption in section['shots']:
            path = os.path.join(shots_dir, lang, f'{shot}.png')
            if not os.path.exists(path):
                path = os.path.join(shots_dir, 'es', f'{shot}.png')
            figure_number += 1
            parts.append(f'<figure><img src="{image_data(path)}"><figcaption><b>{text["figure"]} {figure_number}.</b> '
                         f'{html.escape(caption)}</figcaption></figure>')
        parts.append('</section>')
    parts.append('</body></html>')
    return ''.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shots', required=True)
    parser.add_argument('--out', default=os.path.join(ROOT, 'orchestrator', 'static', 'manual'))
    parser.add_argument('--langs', nargs='+', default=['es', 'en'])
    args = parser.parse_args()
    version = {}
    exec(open(os.path.join(ROOT, 'config', 'version.py')).read(), version)
    os.makedirs(args.out, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome')
        page = browser.new_page()
        for lang in args.langs:
            page.set_content(build_html(lang, args.shots, version['VERSION']), wait_until='load')
            footer = MANUAL[lang]['footer']
            target = os.path.join(args.out, f'community-sh-manual-{lang}.pdf')
            page.pdf(path=target, format='A4', print_background=True, display_header_footer=True,
                     header_template='<span></span>',
                     footer_template=f'<div style="width:100%;font:8px Helvetica,Arial,sans-serif;color:#94a3b8;padding:0 16mm;display:flex;justify-content:space-between">'
                                     f'<span>{html.escape(footer)} · v{version["VERSION"]}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
                     margin={'top': '16mm', 'bottom': '18mm', 'left': '16mm', 'right': '16mm'})
            print(f'{target}: {os.path.getsize(target) // 1024} KB')
        browser.close()


if __name__ == '__main__':
    main()
