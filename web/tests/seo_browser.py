"""Real-browser discovery acceptance; no search-engine submission.
Run with existing test venv: seo_browser.py BASE [metadata|links|deeplink|all].
Evidence lives in ignored tests/artifacts/seo-* files.
"""
import json
import os
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1].rstrip('/')
MODE = sys.argv[2] if len(sys.argv) > 2 else 'all'
PUBLIC = 'https://leafsmith.lakebed.app'
SHARED = (ROOT / 'shared/discovery.ts').read_text()
HOME_DESCRIPTION = re.search(r"export const homeDescription = '([^']+)';", SHARED).group(1)
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
        expect(page).to_have_title('Leafsmith — Free PDF & Image Tools, No Uploads')
        expect(page.locator('meta[name="description"]')).to_have_attribute('content', HOME_DESCRIPTION)
        expect(page.locator('link[rel="canonical"]')).to_have_attribute('href', PUBLIC + '/')
        expect(page.locator('meta[property="og:title"]')).to_have_attribute('content', page.title())
        expect(page.locator('meta[name="twitter:card"]')).to_have_attribute('content', 'summary')
        expect(page.locator('script[type="application/ld+json"]')).to_have_count(0)
        print('PASS rendered homepage title, description, canonical and sharing metadata')
    if MODE in ('links', 'all'):
        nav = page.get_by_role('navigation', name='PDF guides')
        expect(nav).to_be_visible()
        for path in ['/tools', '/merge-pdf', '/split-pdf', '/images-to-pdf', '/sign-pdf']:
            expect(nav.locator(f'a[href="{path}"]')).to_have_count(1)
        page.locator('a[href="/merge-pdf"]').click()
        expect(page.get_by_role('heading', level=1)).to_contain_text('Merge')
        expect(page.locator('a[href="/?tool=merge"]')).to_be_visible()
        print('PASS homepage links lead to a guide')
    if MODE in ('deeplink', 'all'):
        # The homepage visit above started a guest session, as for a returning visitor.
        page.goto(BASE + '/tools', wait_until='networkidle')
        expect(page.get_by_role('heading', level=1)).to_have_text('PDF and image tool guides')
        expect(page).to_have_title('PDF & Image Tool Guides — Leafsmith')
        expect(page.locator('link[rel="canonical"]')).to_have_attribute('href', PUBLIC + '/tools')
        for path in ['/merge-pdf', '/split-pdf', '/images-to-pdf', '/sign-pdf']:
            expect(page.get_by_role('main').locator(f'a[href="{path}"]')).to_have_count(1)
        for slug, tool, heading in [
            ('merge-pdf', 'merge', 'Merge PDFs'),
            ('split-pdf', 'split', 'Split PDF'),
            ('images-to-pdf', 'images-pdf', 'Images to PDF'),
            ('sign-pdf', 'sign', 'Sign PDF'),
        ]:
            page.goto(BASE + '/' + slug, wait_until='networkidle')
            expect(page.get_by_role('heading', level=1)).to_have_count(1)
            expect(page.locator('link[rel="canonical"]')).to_have_attribute('href', f'{PUBLIC}/{slug}')
            expect(page.locator('meta[property="og:url"]')).to_have_attribute('content', f'{PUBLIC}/{slug}')
            assert page.title().endswith(' — Leafsmith') and page.title() != 'Leafsmith — Free PDF & Image Tools, No Uploads', page.title()
            description = page.locator('meta[name="description"]').get_attribute('content')
            assert description and description != HOME_DESCRIPTION, description
            data = json.loads(page.locator('script[type="application/ld+json"]').text_content())
            crumbs = next(node for node in data['@graph'] if node['@type'] == 'BreadcrumbList')['itemListElement']
            assert crumbs[2]['item'] == f'{PUBLIC}/{slug}', crumbs
            main = page.get_by_role('main')
            assert main.locator('ol > li').count() >= 4
            assert main.locator('h3').count() >= 2
            for text in ['no document uploads', '25 MiB per file', 'not redaction']:
                expect(main).to_contain_text(text)
            page.locator(f'a[href="/?tool={tool}"]').click()
            expect(page.get_by_role('heading', level=1)).to_have_text(heading)
            expect(page.locator('link[rel="canonical"]')).to_have_attribute('href', PUBLIC + '/')
            expect(page.locator('script[type="application/ld+json"]')).to_have_count(0)
        page.goto(BASE + '/?tool=not-a-tool', wait_until='networkidle')
        expect(page.get_by_role('heading', name='Your documents. Your device.')).to_be_visible()
        print('PASS returning visitors open every guide directly; guides open their actual tool; invalid tool falls back safely')
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
