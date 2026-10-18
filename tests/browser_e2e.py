"""Real Chromium acceptance; no Tauri bridge injection or mocked job results.

Run with Playwright, pypdf, reportlab and Pillow installed:
  ../paperwork/.test-venv/bin/python tests/browser_e2e.py http://127.0.0.1:1420
Optional PAPERWORK_BROWSER_ENV points to a JSON executable_path/library_path/
launch_args config (defaults to ../paperwork/tests/browser-env.json if present).
Only test-local browser environment is changed. For stable release acceptance,
serve a frozen copy of dist rather than an actively edited Vite/HMR session;
PAPERWORK_SERVED_BUILD records that served directory's asset hashes. Capture
stdout with `set -o pipefail; ... | tee docs/screenshots/browser/run-output.txt`.
All fixtures/downloads/screenshots
are retained under docs/screenshots/browser; report: tests/browser-verification.json.
Native IPC, engine installation and packaged apps require separate native testing.
"""
import hashlib
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

from PIL import Image
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'docs/screenshots/browser'
ART.mkdir(parents=True, exist_ok=True)
BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:1420'
REPORT = ROOT / 'tests/browser-verification.json'
CONFIG = Path(os.environ.get('PAPERWORK_BROWSER_ENV', str(ROOT.parent / 'paperwork/tests/browser-env.json')))
STARTED = datetime.now(timezone.utc).isoformat()
SERVED_BUILD = Path(os.environ['PAPERWORK_SERVED_BUILD']).resolve() if os.environ.get('PAPERWORK_SERVED_BUILD') else None
BUILD_MANIFEST = [
    {'path': str(p.relative_to(SERVED_BUILD)), 'source_uri': p.as_uri(),
     'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    for p in sorted(SERVED_BUILD.rglob('*')) if p.is_file()
] if SERVED_BUILD else []
results, requests, errors, consoles, external_attempts = [], [], [], [], []
artifacts = {}


def fixture_files():
    c = canvas.Canvas(str(ART / 'source.pdf'), pagesize=(600, 800))
    for n, word in enumerate(['Alpha', 'Beta', 'Gamma'], 1):
        c.setFont('Helvetica', 24)
        c.drawString(50, 730, f'Original {word} - Page {n}')
        if n == 1:
            c.acroForm.textfield(name='name', x=50, y=600, width=200, height=25, value='Ada')
            c.acroForm.checkbox(name='approved', x=50, y=550, checked=False)
        c.showPage()
    c.save()
    c = canvas.Canvas(str(ART / 'second.pdf'), pagesize=(600, 800))
    c.drawString(50, 730, 'Delta document')
    c.save()
    Image.new('RGB', (240, 120), (210, 70, 45)).save(ART / 'red.jpg', quality=95)
    Image.new('RGB', (80, 160), (70, 140, 85)).save(ART / 'green.png')
    w = PdfWriter()
    w.append(str(ART / 'source.pdf'))
    w.encrypt('secret')
    w.write(str(ART / 'locked.pdf'))
    (ART / 'invalid.pdf').write_bytes(b'not a pdf file')


def evidence(path, details=None):
    path = Path(path)
    artifacts[path.name] = {
        'path': str(path.relative_to(ROOT)), 'source_uri': path.as_uri(),
        'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        **(details or {}),
    }
    return path


def screenshot(page, name, locator=None, full_page=False):
    path = ART / name
    if locator is None and full_page:
        page.evaluate('window.scrollTo({top:0,behavior:"instant"})')
    (locator or page).screenshot(path=str(path), **({'full_page': full_page} if locator is None else {}))
    return evidence(path, {'viewport': page.viewport_size, 'capture': 'element' if locator is not None else 'full_page' if full_page else 'viewport'})


def pointer_controls(page):
    bad = page.locator('button:enabled, a[href]').evaluate_all("""els => els.filter(e =>
      e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' &&
      getComputedStyle(e).cursor !== 'pointer').map(e => ({name:e.getAttribute('aria-label') || e.innerText,
      cursor:getComputedStyle(e).cursor}))""")
    assert not bad, bad


def no_overflow(page):
    widths = page.evaluate('({scroll:document.documentElement.scrollWidth, viewport:innerWidth})')
    assert widths['scroll'] <= widths['viewport'], widths


def load(page, names, tool):
    page.get_by_test_id('file-input').set_input_files([str(ART / name) for name in names])
    expect(page.get_by_role('button', name='Clear workspace', exact=True)).to_be_enabled(timeout=45000)
    page.get_by_test_id('tool-' + tool).click()
    expect(page.get_by_test_id('run-tool')).to_be_enabled(timeout=45000)


def download(page, name, index=0, run=True, count=1):
    if run:
        page.get_by_test_id('run-tool').click()
        expect(page.get_by_role('region', name='Results', exact=True)).to_be_visible(timeout=60000)
        expect(page.get_by_test_id('download-result')).to_have_count(count, timeout=45000)
    with page.expect_download() as event:
        page.get_by_test_id('download-result').nth(index).click()
    path = ART / name
    event.value.save_as(path)
    assert not event.value.failure()
    evidence(path, {'download_name': event.value.suggested_filename, 'download_url': event.value.url})
    pointer_controls(page)
    return path


def image_objects(reader, page_index=0):
    resources = reader.pages[page_index]['/Resources']
    objects = resources.get('/XObject', {}).get_object() if '/XObject' in resources else {}
    return [o.get_object() for o in objects.values() if o.get_object().get('/Subtype') == '/Image']


def shell(page):
    expect(page.get_by_role('heading', name='Your documents. Your device.')).to_be_visible()
    expect(page.locator('[data-testid^="tool-"]')).to_have_count(12)
    expect(page.locator('[data-testid^="native-"]')).to_have_count(17)
    assert page.locator('header svg').first.get_attribute('stroke-width') == '1.5'
    assert not page.evaluate("'__TAURI_INTERNALS__' in window"), 'This acceptance must remain an unmocked browser preview'
    pointer_controls(page)
    no_overflow(page)
    screenshot(page, 'desktop-home.png')
    page.get_by_role('textbox', name='Search tools', exact=True).fill('Organize')
    expect(page.locator('[data-testid^="tool-"]')).to_have_count(1)
    page.get_by_role('textbox', name='Search tools', exact=True).fill('')
    page.get_by_role('textbox', name='Search native tools', exact=True).fill('OCR')
    expect(page.locator('[data-testid^="native-"]')).to_have_count(2)
    page.get_by_role('textbox', name='Search native tools', exact=True).fill('')


def organize(page):
    load(page, ['source.pdf'], 'organize')
    page.get_by_test_id('page-range').fill('3,1')
    page.get_by_label('Rotate output pages').select_option('90')
    page.get_by_label('Left', exact=True).fill('10')
    page.get_by_label('Top', exact=True).fill('20')
    r = PdfReader(download(page, 'organized.pdf'))
    assert len(r.pages) == 2
    assert 'Gamma' in r.pages[0].extract_text() and 'Alpha' in r.pages[1].extract_text()
    assert all(p.rotation == 90 for p in r.pages)
    for p in r.pages:
        assert abs(float(p.cropbox.width) - 590) < .1
        assert abs(float(p.cropbox.height) - 780) < .1
    expect(page.get_by_label('Preview page 1', exact=True)).to_be_visible(timeout=45000)
    screenshot(page, 'desktop-workspace.png', full_page=True)


def merge(page):
    load(page, ['source.pdf', 'second.pdf'], 'merge')
    page.get_by_role('button', name='Move second.pdf up', exact=True).click()
    r = PdfReader(download(page, 'merged.pdf'))
    assert len(r.pages) == 4
    assert 'Delta' in r.pages[0].extract_text() and 'Gamma' in r.pages[3].extract_text()


def split(page):
    load(page, ['source.pdf'], 'split')
    page.get_by_test_id('page-range').fill('2-3')
    page.get_by_role('combobox', name='Output', exact=True).select_option('individual')
    r1 = PdfReader(download(page, 'split-2.pdf', count=2))
    r2 = PdfReader(download(page, 'split-3.pdf', index=1, run=False))
    assert len(r1.pages) == len(r2.pages) == 1
    assert 'Beta' in r1.pages[0].extract_text() and 'Gamma' in r2.pages[0].extract_text()


def annotation(page):
    load(page, ['source.pdf'], 'annotate')
    page.get_by_label('New text', exact=True).fill('Reviewed by Paperwork')
    r = PdfReader(download(page, 'annotated-text.pdf'))
    assert 'Reviewed by Paperwork' in ' '.join(r.pages[0].extract_text().split())
    assert 'Original Alpha' in r.pages[0].extract_text()
    assert r.get_fields()['name']['/V'] == 'Ada'


def annotation_image(page):
    load(page, ['source.pdf'], 'annotate')
    page.get_by_role('combobox', name='Add', exact=True).select_option('image')
    page.get_by_label('Overlay image', exact=True).set_input_files(str(ART / 'red.jpg'))
    r = PdfReader(download(page, 'annotated-image.pdf'))
    assert any((obj['/Width'], obj['/Height']) == (240, 120) for obj in image_objects(r))
    assert 'Original Alpha' in r.pages[0].extract_text()


def fill(page):
    load(page, ['source.pdf'], 'forms')
    page.get_by_label('name', exact=True).fill('Grace Hopper')
    page.get_by_label('approved', exact=True).check()
    r = PdfReader(download(page, 'filled.pdf'))
    assert r.get_fields()['name']['/V'] == 'Grace Hopper'
    assert r.get_fields()['approved']['/V'] != '/Off'


def flatten(page):
    load(page, ['source.pdf'], 'forms')
    page.get_by_label('name', exact=True).fill('Grace Hopper')
    page.get_by_label('Flatten fields (make them non-interactive)', exact=True).check()
    r = PdfReader(download(page, 'flattened.pdf'))
    assert not r.get_fields()
    assert 'Grace Hopper' in r.pages[0].extract_text()


def images_pdf(page):
    load(page, ['red.jpg', 'green.png'], 'images-pdf')
    r = PdfReader(download(page, 'images.pdf'))
    assert len(r.pages) == 2
    assert (image_objects(r, 0)[0]['/Width'], image_objects(r, 0)[0]['/Height']) == (240, 120)
    assert (image_objects(r, 1)[0]['/Width'], image_objects(r, 1)[0]['/Height']) == (80, 160)


def pdf_images(page):
    load(page, ['source.pdf'], 'pdf-images')
    page.get_by_test_id('page-range').fill('2')
    im = Image.open(download(page, 'page-2.png'))
    assert im.format == 'PNG' and im.size == (900, 1200)
    assert im.convert('RGB').getextrema() != ((255, 255),) * 3


def extract(page):
    load(page, ['source.pdf'], 'text')
    page.get_by_test_id('page-range').fill('3')
    text = download(page, 'extracted.txt').read_text()
    assert 'Gamma' in text and 'Alpha' not in text


def optimize(page):
    load(page, ['source.pdf'], 'optimize')
    path = download(page, 'optimized.pdf')
    assert path.stat().st_size <= (ART / 'source.pdf').stat().st_size
    r = PdfReader(path)
    assert len(r.pages) == 3 and 'Original Alpha' in r.pages[0].extract_text()
    assert r.get_fields()['name']['/V'] == 'Ada'


def image_resize(page):
    load(page, ['red.jpg'], 'image-tools')
    page.get_by_label('Maximum width (px)').fill('120')
    im = Image.open(download(page, 'resized.jpg'))
    assert im.format == 'JPEG' and im.size == (120, 60)


def image_merge(page):
    load(page, ['red.jpg', 'green.png'], 'image-tools')
    page.get_by_role('combobox', name='Task', exact=True).select_option('merge')
    im = Image.open(download(page, 'combined.png'))
    assert im.format == 'PNG' and im.size == (240, 280)
    assert im.convert('RGB').getpixel((5, 5))[0] > 190
    assert im.convert('RGB').getpixel((5, 200)) == (70, 140, 85)


def image_convert(page):
    load(page, ['red.jpg'], 'image-tools')
    page.get_by_role('combobox', name='Format', exact=True).select_option('image/webp')
    im = Image.open(download(page, 'converted.webp'))
    assert im.format == 'WEBP' and im.size == (240, 120)


def qr(page):
    page.get_by_test_id('tool-qr').click()
    page.get_by_label('Link or text').fill('https://example.com/paperwork')
    svg = ElementTree.fromstring(download(page, 'qr.svg').read_text())
    assert svg.tag.endswith('svg')
    assert any(e.tag.endswith(('path', 'rect')) for e in svg.iter())
    expect(page.get_by_role('img', name='Generated QR code')).to_be_visible()
    screenshot(page, 'desktop-qr.png', full_page=True)


def draw(page):
    c = page.get_by_label('Draw signature')
    c.scroll_into_view_if_needed()
    box = c.bounding_box()
    page.mouse.move(box['x'] + 20, box['y'] + 50)
    page.mouse.down()
    for dx, dy in [(40, 30), (60, 70), (90, 25), (130, 55)]:
        page.mouse.move(box['x'] + dx, box['y'] + dy)
    page.mouse.up()
    page.wait_for_timeout(300)


def signature(page):
    load(page, ['source.pdf'], 'sign')
    draw(page)
    r = PdfReader(download(page, 'signed.pdf'))
    assert any((obj['/Width'], obj['/Height']) == (520, 170) for obj in image_objects(r))
    assert 'Original Alpha' in r.pages[0].extract_text()


def stale_signature(page):
    load(page, ['source.pdf'], 'sign')
    draw(page)
    page.get_by_role('button', name='Paperwork Desktop home').click()
    page.get_by_test_id('tool-sign').click()
    page.get_by_test_id('run-tool').click()
    expect(page.get_by_role('alert')).to_contain_text('Draw a signature first')
    expect(page.get_by_test_id('download-result')).to_have_count(0)


def retained(page):
    page.get_by_test_id('tool-qr').click()
    page.get_by_test_id('run-tool').click()
    expect(page.get_by_test_id('download-result')).to_have_count(1, timeout=45000)
    url = page.get_by_test_id('download-result').get_attribute('href')
    page.get_by_label('Link or text').fill('')
    page.get_by_test_id('run-tool').click()
    expect(page.get_by_role('alert')).to_be_visible()
    expect(page.get_by_test_id('download-result')).to_have_count(1)
    assert page.get_by_test_id('download-result').get_attribute('href') == url
    ElementTree.fromstring(download(page, 'retained-qr.svg', run=False).read_text())


def sample(page):
    page.get_by_role('button', name='Try a sample', exact=True).click()
    expect(page.get_by_test_id('run-tool')).to_be_enabled(timeout=45000)
    r = PdfReader(download(page, 'demo-organized.pdf'))
    assert len(r.pages) > 0 and r.pages[0].extract_text().strip()
    page.get_by_role('button', name='Paperwork Desktop home').click()
    expect(page.get_by_role('button', name='Try a sample', exact=True)).to_have_count(0)


def invalid_range(page):
    load(page, ['source.pdf'], 'organize')
    page.get_by_test_id('page-range').fill('99')
    page.get_by_test_id('run-tool').click()
    expect(page.get_by_role('alert')).to_be_visible()
    expect(page.get_by_test_id('download-result')).to_have_count(0)


def invalid_file(page, name, encrypted=False):
    page.get_by_test_id('file-input').set_input_files(str(ART / name))
    expect(page.get_by_role('alert')).to_be_visible(timeout=45000)
    if encrypted:
        expect(page.get_by_role('alert')).to_contain_text('encrypt', ignore_case=True)
    page.get_by_test_id('tool-organize').click()
    expect(page.get_by_role('alert')).to_be_visible()
    expect(page.get_by_test_id('run-tool')).to_be_disabled()
    expect(page.get_by_test_id('download-result')).to_have_count(0)


def scope(page):
    page.get_by_role('button', name='Scope & privacy', exact=True).click()
    expect(page.get_by_role('heading', name='Native processing and limitations')).to_be_visible()
    body = page.locator('main').inner_text()
    for phrase in ['bundled', 'explicit per-job consent', 'Electronic signatures are not certificate signatures', 'attempts to remove cached job files', 'crash or forced termination', 'if cleanup fails', 'not secure erasure']:
        assert phrase in body, phrase
    pointer_controls(page)
    screenshot(page, 'desktop-privacy.png', full_page=True)


def native_preview(page):
    native = page.get_by_role('region', name='Native tools', exact=True)
    expect(native).to_contain_text('Native features require the installed Paperwork Desktop app')
    ids = native.locator('[data-testid^="native-"]').evaluate_all('els=>els.map(e=>e.dataset.testid)')
    assert len(ids) == 17
    native.evaluate('(e)=>window.scrollTo({top:window.scrollY+e.getBoundingClientRect().top-96,behavior:"instant"})')
    screenshot(page, 'desktop-native-cards.png')
    for testid in ids:
        native.get_by_test_id(testid).click()
        expect(native.get_by_role('button', name='Choose native files', exact=True)).to_be_disabled()
        expect(native.get_by_test_id('run-native')).to_be_disabled()
        pointer_controls(page)
        no_overflow(page)
    page.get_by_test_id('native-summarize').click()
    expect(native.get_by_role('combobox', name='Provider', exact=True)).to_have_value('ollama')
    expect(native.get_by_label('Cloud API key (this job only)', exact=True)).to_have_count(0)
    native.get_by_role('combobox', name='Provider', exact=True).select_option('openai-compatible')
    consent = native.get_by_role('checkbox', name='I consent to sending')
    expect(consent).not_to_be_checked()
    expect(native.get_by_label('Cloud API key (this job only)', exact=True)).to_have_attribute('type', 'password')
    expect(native.get_by_test_id('run-native')).to_be_disabled()
    native.get_by_role('button', name='Close', exact=True).click()
    native.get_by_test_id('native-summarize').click()
    expect(native.get_by_role('combobox', name='Provider', exact=True)).to_have_value('ollama')
    page.get_by_test_id('native-edit_pdf_text').click()
    panel = native.locator('section').filter(has=page.get_by_role('button', name='Choose native files', exact=True)).first
    panel.scroll_into_view_if_needed()
    screenshot(page, 'desktop-native-panel.png', locator=panel)
    native.get_by_text('Optional components & models', exact=True).click()
    expect(native.get_by_role('button', name='Refresh component status')).to_be_disabled()
    expect(native).to_contain_text('Component status has not been retrieved. No installation is assumed.')
    expect(native.get_by_role('button', name='Install ', exact=False)).to_have_count(0)
    screenshot(page, 'desktop-native-components.png', locator=native.locator('details').last)


def style(page):
    browser_card = page.get_by_test_id('tool-organize')
    native_card = page.get_by_test_id('native-inspect_pdf')
    styles = [c.evaluate("e=>{let s=getComputedStyle(e); return {background:s.backgroundColor,radius:s.borderRadius,border:s.borderColor,color:s.color,font:s.fontFamily}}") for c in [browser_card, native_card]]
    assert styles[0] == styles[1], styles
    assert styles[0]['background'] == 'rgb(255, 254, 250)'
    assert styles[0]['radius'] == '12px'
    assert page.locator('main h1').evaluate('e=>getComputedStyle(e).fontFamily').startswith('Georgia')
    evidence(ART / 'desktop-home.png', {'browser_card_style': styles[0], 'native_card_style': styles[1]})


def mobile(page):
    page.set_viewport_size({'width': 390, 'height': 844})
    screenshot(page, 'mobile-home.png')
    no_overflow(page)
    expect(page.get_by_role('button', name='Choose files', exact=True)).to_be_visible()
    pointer_controls(page)
    page.get_by_test_id('native-summarize').click()
    native = page.get_by_role('region', name='Native tools', exact=True)
    panel = native.locator('section').filter(has=page.get_by_role('button', name='Choose native files', exact=True)).first
    no_overflow(page)
    expect(native.get_by_test_id('run-native')).to_be_disabled()
    # The 778px panel plus the 80px sticky header exceeds the 844px home
    # viewport. Use a taller phone viewport to retain the entire panel without
    # the sticky header occluding its title in a locator screenshot.
    page.set_viewport_size({'width': 390, 'height': 1000})
    panel.evaluate('(e)=>window.scrollTo({top:window.scrollY+e.getBoundingClientRect().top-96,behavior:"instant"})')
    screenshot(page, 'mobile-native-panel.png', locator=panel)
    no_overflow(page)
    page.set_viewport_size({'width': 390, 'height': 844})
    no_overflow(page)


def offline(page):
    # A browser cannot cold-load its HTTP-served bundle while offline. Initialize
    # the source preview first; then prove this operation makes no network call.
    # Packaged Tauri offline cold-start is explicitly outside this test's scope.
    load(page, ['source.pdf'], 'organize')
    expect(page.get_by_label('Preview page 1', exact=True)).to_be_visible(timeout=45000)
    page.context.set_offline(True)
    try:
        r = PdfReader(download(page, 'offline-organized.pdf'))
        assert len(r.pages) == 3 and 'Alpha' in r.pages[0].extract_text()
    finally:
        page.context.set_offline(False)


def write_report(browser_version):
    payload = {
        'started_at': STARTED, 'finished_at': datetime.now(timezone.utc).isoformat(),
        'base_url': BASE, 'browser': browser_version,
        'scope': 'Real Chromium browser preview; file inputs and independently parsed downloads. No Tauri globals, invoke mocks or fake native outputs.',
        'source_uri': Path(__file__).resolve().as_uri(),
        'test_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'command': [sys.executable, str(Path(__file__).resolve()), BASE],
        'served_build_manifest': BUILD_MANIFEST,
        'actual_output_source_uri': (ART / 'run-output.txt').as_uri() if (ART / 'run-output.txt').exists() else None,
        'report_uri': REPORT.as_uri(), 'browser_environment_config_uri': CONFIG.as_uri() if CONFIG.exists() else None,
        'checks': results, 'passed': sum(r['status'] == 'passed' for r in results),
        'failed': sum(r['status'] == 'failed' for r in results),
        'skipped': [
            {'check': 'Real Tauri IPC and native system file/save pickers', 'reason': 'No installed Tauri host in a normal Chromium preview.'},
            {'check': 'Native engine/component installation and native job execution', 'reason': 'Browser preview intentionally disables these actions; no bridge or installed component state is faked.'},
            {'check': 'Windows NSIS and Linux AppImage interactive launch', 'reason': 'Requires built packages and target desktop OS, not proven by web tests.'},
            {'check': 'Pixel-identical original-site comparison', 'reason': 'No synchronized original-site visual baseline; computed shared design tokens and desktop/mobile screenshots are retained instead.'},
        ],
        'network': {'requests': requests, 'external_attempts': external_attempts, 'request_count': len(requests), 'external_attempt_count': len(external_attempts)},
        'uncaught_browser_errors': errors, 'console_errors': consoles,
        'artifacts': list(artifacts.values()),
    }
    REPORT.write_text(json.dumps(payload, indent=2))
    return payload


fixture_files()
settings = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
env = os.environ.copy()
if settings.get('library_path'):
    env['LD_LIBRARY_PATH'] = settings['library_path']
origin = urlsplit(BASE)
with sync_playwright() as pw:
    launch = {'headless': True, 'args': settings.get('launch_args', ['--no-sandbox']), 'env': env}
    if settings.get('executable_path'):
        launch['executable_path'] = settings['executable_path']
    browser = pw.chromium.launch(**launch)
    version = browser.version
    context = browser.new_context(viewport={'width': 1440, 'height': 1080}, accept_downloads=True, service_workers='block')

    def route_request(route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.scheme in ('http', 'https') and parsed.netloc != origin.netloc:
            external_attempts.append({'url': request.url, 'method': request.method})
            route.abort('blockedbyclient')
        else:
            route.continue_()

    context.route('**/*', route_request)
    context.on('request', lambda r: requests.append({'url': r.url, 'method': r.method, 'resource_type': r.resource_type, 'body_bytes': len(r.post_data_buffer or b'')}))

    def check(name, fn):
        page = context.new_page()
        page.set_default_timeout(12000)
        page.on('pageerror', lambda e: errors.append({'check': name, 'error': str(e)}))
        page.on('console', lambda m: consoles.append({'check': name, 'message': m.text}) if m.type == 'error' else None)
        started = time.monotonic()
        before = set(artifacts)
        try:
            page.goto(BASE, wait_until='networkidle')
            fn(page)
            results.append({'check': name, 'status': 'passed', 'seconds': round(time.monotonic() - started, 2), 'artifact_uris': [artifacts[k]['source_uri'] for k in set(artifacts) - before]})
            print('PASS', name, flush=True)
        except Exception as exc:
            shot = 'failed-' + str(len(results) + 1) + '.png'
            try:
                screenshot(page, shot, full_page=True)
            except Exception:
                pass
            results.append({'check': name, 'status': 'failed', 'seconds': round(time.monotonic() - started, 2), 'error': str(exc), 'traceback': traceback.format_exc(), 'screenshot_uri': (ART / shot).as_uri()})
            print('FAIL', name, str(exc)[:600], flush=True)
        finally:
            page.close()
            write_report(version)

    checks = [
        ('desktop shell, 12 preserved browser tools, 17 native cards and search', shell),
        ('reorder/extract/delete/rotate/crop PDF, parsed pages and cropboxes', organize),
        ('merge PDFs using actual workspace reorder controls', merge),
        ('split selected pages into two independently parsed downloads', split),
        ('text annotation preserves original text and form field', annotation),
        ('file-input image annotation embeds actual JPEG dimensions', annotation_image),
        ('fillable text and checkbox values round-trip', fill),
        ('flattened form has visible value and no interactive fields', flatten),
        ('JPEG and PNG become ordered PDF image pages', images_pdf),
        ('selected PDF page renders to nonblank 900x1200 PNG', pdf_images),
        ('embedded text extraction respects page selection', extract),
        ('lossless optimization never increases size and preserves forms', optimize),
        ('image resize produces parsed 120x60 JPEG', image_resize),
        ('image combination produces parsed pixels and 240x280 PNG', image_merge),
        ('image format conversion produces parsed WebP', image_convert),
        ('QR generates valid SVG download and visible preview', qr),
        ('drawn electronic signature embeds 520x170 image', signature),
        ('blank remounted signature cannot reuse stale drawing', stale_signature),
        ('failed operation retains previous valid downloadable output', retained),
        ('built-in sample is real PDF and cannot overwrite occupied workspace', sample),
        ('invalid page range fails visibly without download', invalid_range),
        ('encrypted PDF reason survives navigation and processing stays disabled', lambda p: invalid_file(p, 'locked.pdf', True)),
        ('malformed PDF fails visibly and processing stays disabled', lambda p: invalid_file(p, 'invalid.pdf')),
        ('scope copy documents actual privacy/native/cache limitations', scope),
        ('all native panels honestly disabled without Tauri, consent UI and no fake installation', native_preview),
        ('browser and native cards retain identical warm-paper design tokens', style),
        ('390px mobile home and native panel without horizontal overflow', mobile),
        ('real PDF organize succeeds offline after source preview initialization', offline),
    ]
    for name, fn in checks:
        check(name, fn)

    def privacy_check(_page):
        assert not external_attempts, external_attempts
        assert not [r for r in requests if r['method'] not in ('GET', 'HEAD') or r['body_bytes']], 'Unexpected upload or request body'
        assert not errors, errors
        assert not consoles, consoles

    check('cold-context network has no CDN/external attempts, uploads or browser errors', privacy_check)
    context.close()
    browser.close()
report = write_report(version)
print(json.dumps({'passed': report['passed'], 'failed': report['failed'], 'skipped': len(report['skipped']), 'report_uri': REPORT.as_uri()}, indent=2))
sys.exit(1 if report['failed'] else 0)
