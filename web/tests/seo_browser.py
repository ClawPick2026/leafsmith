"""Real-browser discovery acceptance; no search-engine submission.
Run with existing test venv: seo_browser.py BASE [metadata|links|deeplink|all].
Evidence lives in ignored tests/artifacts/seo-* files.
"""
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1].rstrip('/')
MODE = sys.argv[2] if len(sys.argv) > 2 else 'all'
settings = json.loads((ROOT / 'tests/browser-env.json').read_text())
env = os.environ.copy()
if settings.get('library_path'):
    env['LD_LIBRARY_PATH'] = settings['library_path']

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, executable_path=settings['executable_path'], env=env,
        args=settings.get('launch_args', ['--no-sandbox']),
    )
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(BASE, wait_until='networkidle')
    if MODE in ('metadata', 'all'):
        expect(page).to_have_title('Paperwork — Free PDF & Image Tools, No Uploads')
        expect(page.locator('meta[name="description"]')).to_have_attribute('content', 'Merge, split, annotate and sign PDFs in your browser. Convert images and generate QR codes. No account required; documents stay on your device.')
        expect(page.locator('link[rel="canonical"]')).to_have_attribute('href', 'https://paperwork.lakebed.app/')
        expect(page.locator('meta[property="og:title"]')).to_have_attribute('content', page.title())
        expect(page.locator('meta[name="twitter:card"]')).to_have_attribute('content', 'summary')
        print('PASS rendered homepage title, description, canonical and sharing metadata')
    if MODE in ('links', 'all'):
        nav = page.get_by_role('navigation', name='PDF guides')
        expect(nav).to_be_visible()
        for path in ['/tools', '/merge-pdf', '/split-pdf', '/images-to-pdf', '/sign-pdf']:
            expect(nav.locator(f'a[href="{path}"]')).to_have_count(1)
        page.locator('a[href="/merge-pdf"]').click()
        expect(page.get_by_role('heading', level=1)).to_contain_text('Merge')
        expect(page.locator('a[href="/?tool=merge"]')).to_be_visible()
        print('PASS crawlable homepage links lead to a server-rendered guide')
    if MODE in ('deeplink', 'all'):
        for slug, tool, heading in [
            ('merge-pdf', 'merge', 'Merge PDFs'),
            ('split-pdf', 'split', 'Split PDF'),
            ('images-to-pdf', 'images-pdf', 'Images to PDF'),
            ('sign-pdf', 'sign', 'Sign PDF'),
        ]:
            page.goto(BASE + '/' + slug, wait_until='networkidle')
            page.locator(f'a[href="/?tool={tool}"]').click()
            expect(page.get_by_role('heading', level=1)).to_have_text(heading)
            expect(page.locator('link[rel="canonical"]')).to_have_attribute('href', 'https://paperwork.lakebed.app/')
        page.goto(BASE + '/?tool=not-a-tool', wait_until='networkidle')
        expect(page.get_by_role('heading', name='Your documents. Your device.')).to_be_visible()
        print('PASS every guide opens its actual tool; invalid tool falls back safely')
    if MODE == 'all':
        for width in [1440, 390]:
            page.set_viewport_size({'width': width, 'height': 1000})
            for path in ['/', '/tools', '/merge-pdf', '/split-pdf', '/images-to-pdf', '/sign-pdf']:
                page.goto(BASE + path, wait_until='networkidle')
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), (path, width)
            page.screenshot(path=str(ROOT / f'tests/artifacts/seo-mobile-{width}.png'), full_page=True)
        assert not errors, errors
        print('PASS desktop/mobile discovery pages fit; no uncaught browser errors')
    browser.close()
