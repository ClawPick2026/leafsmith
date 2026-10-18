"""Browser acceptance for crop selection, placement boxes and result previews.
Run against either target:
  ../.test-venv/bin/python tests/crop_preview.py URL
where URL is the Lakebed website (dev or deploy) or the desktop Vite preview.
Downloads are parsed independently with pypdf and Pillow. Fixtures, downloads
and screenshots go to the ignored tests/artifacts/crop-preview/.
"""
import json, os, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'tests' / 'artifacts' / 'crop-preview'
ART.mkdir(parents=True, exist_ok=True)
BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3141'
HOME = re.compile(r'^Paperwork (Desktop )?home$')


def fixtures():
    c = canvas.Canvas(str(ART / 'pages.pdf'), pagesize=(600, 800))
    for n, word in enumerate(['Alpha', 'Beta', 'Gamma'], 1):
        c.setFont('Helvetica', 24)
        c.drawString(50, 730, f'Original {word} - Page {n}')
        c.showPage()
    c.save()
    w = PdfWriter()
    w.append(str(ART / 'pages.pdf'))
    w.pages[0].rotate(90)
    w.write(str(ART / 'rotated.pdf'))
    halves = Image.new('RGB', (240, 120), (220, 30, 30))
    halves.paste((30, 30, 220), (120, 0, 240, 120))
    halves.save(ART / 'halves.png')


fixtures()
settings = json.loads((ROOT / 'tests/browser-env.json').read_text()) if (ROOT / 'tests/browser-env.json').exists() else {}
env = os.environ.copy()
if settings.get('library_path'):
    env['LD_LIBRARY_PATH'] = settings['library_path']
results, errors, uploads = [], [], []


def record(name, fn):
    started = time.time()
    fn()
    results.append({'check': name, 'passed': True, 'seconds': round(time.time() - started, 2)})
    print('PASS', name, flush=True)


with sync_playwright() as p:
    launch = {'headless': True, 'args': settings.get('launch_args', ['--no-sandbox']), 'env': env}
    if settings.get('executable_path'):
        launch['executable_path'] = settings['executable_path']
    browser = p.chromium.launch(**launch)
    context = browser.new_context(viewport={'width': 1440, 'height': 1080}, accept_downloads=True)
    page = context.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: uploads.append(r.url) if r.method != 'GET' and '/storage/' in r.url else None)
    page.set_default_timeout(30000)
    page.goto(BASE, wait_until='networkidle')

    def load(names, tool):
        page.get_by_role('button', name=HOME).click()
        clear = page.get_by_role('button', name='Clear workspace', exact=True)
        if clear.count():
            clear.click()
        page.get_by_test_id('file-input').set_input_files([str(ART / name) for name in names])
        expect(page.get_by_role('button', name='Clear workspace', exact=True)).to_be_enabled(timeout=45000)
        page.get_by_test_id('tool-' + tool).click()
        expect(page.get_by_test_id('run-tool')).to_be_enabled(timeout=45000)
        # Opening a tool smooth-scrolls to the top; measure positions only after it settles.
        page.wait_for_function('window.scrollY === 0')

    def run(name, index=0):
        page.get_by_test_id('run-tool').click()
        expect(page.get_by_role('region', name='Results', exact=True)).to_be_visible(timeout=60000)
        with page.expect_download() as event:
            page.get_by_test_id('download-result').nth(index).click()
        path = ART / name
        event.value.save_as(path)
        return path

    def drag(test_id, start, end):
        target = page.get_by_test_id(test_id)
        target.scroll_into_view_if_needed()
        box = target.bounding_box()
        page.mouse.move(box['x'] + box['width'] * start[0], box['y'] + box['height'] * start[1])
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] * end[0], box['y'] + box['height'] * end[1], steps=8)
        page.mouse.up()

    def values(labels):
        return {label: float(page.get_by_label(label, exact=True).input_value()) for label in labels}

    def close(actual, expected, tolerance, label):
        assert abs(actual - expected) <= tolerance, f'{label}: {actual} is not within {tolerance} of {expected}'

    def organize_drag():
        load(['pages.pdf'], 'organize')
        expect(page.get_by_label('Preview page 1', exact=True)).to_be_visible(timeout=45000)
        drag('crop-selector', (0.1, 0.1), (0.6, 0.5))
        m = values(['Left', 'Bottom', 'Right', 'Top'])
        for label, expected in {'Left': 60, 'Top': 80, 'Right': 240, 'Bottom': 400}.items():
            close(m[label], expected, 4, label)
        # Arrow keys move the selection by 1% of the displayed page.
        page.get_by_test_id('selection-box').focus()
        page.keyboard.press('ArrowRight')
        moved = values(['Left', 'Right'])
        close(moved['Left'] - m['Left'], 6, 1, 'keyboard move left')
        close(m['Right'] - moved['Right'], 6, 1, 'keyboard move right')
        m = values(['Left', 'Bottom', 'Right', 'Top'])
        page.screenshot(path=str(ART / 'organize-crop-selection.png'), full_page=True)
        result = PdfReader(run('organized-drag.pdf'))
        assert len(result.pages) == 3
        for p in result.pages:
            close(float(p.cropbox.left), m['Left'], 0.01, 'cropbox left')
            close(float(p.cropbox.bottom), m['Bottom'], 0.01, 'cropbox bottom')
            close(float(p.cropbox.width), 600 - m['Left'] - m['Right'], 0.01, 'cropbox width')
            close(float(p.cropbox.height), 800 - m['Top'] - m['Bottom'], 0.01, 'cropbox height')
        preview = page.get_by_role('img', name='Result preview page 1', exact=True)
        expect(preview).to_be_visible(timeout=45000)
        ratio = preview.evaluate('c => c.width / c.height')
        close(ratio, (600 - m['Left'] - m['Right']) / (800 - m['Top'] - m['Bottom']), 0.02, 'result preview aspect ratio')
        page.get_by_role('button', name='Next result page', exact=True).click()
        expect(page.get_by_role('img', name='Result preview page 2', exact=True)).to_be_visible(timeout=45000)
        page.screenshot(path=str(ART / 'organize-result-preview.png'), full_page=True)
        page.get_by_role('button', name='Use result', exact=True).click()
        expect(page.get_by_label('Left', exact=True)).to_have_value('0', timeout=45000)
    record('drag a crop area on the preview, adjust it by keyboard, and preview the cropped result', organize_drag)

    def rotated_crop():
        load(['rotated.pdf'], 'organize')
        source = page.get_by_label('Preview page 1', exact=True)
        expect(source).to_be_visible(timeout=45000)
        assert source.evaluate('c => c.width > c.height'), 'A /Rotate 90 page is displayed in landscape'
        page.get_by_test_id('page-range').fill('1')
        page.get_by_label('Left', exact=True).fill('400')
        selector = page.get_by_test_id('crop-selector').bounding_box()
        selection = page.get_by_test_id('selection-box').bounding_box()
        close((selection['x'] - selector['x']) / selector['width'], 0.5, 0.01, 'displayed crop starts halfway across')
        r = PdfReader(run('rotated-crop.pdf')).pages[0]
        assert r.rotation == 90
        # The displayed left half of a page rotated 90 degrees is its PDF bottom half.
        assert [round(float(v), 2) for v in (r.cropbox.left, r.cropbox.bottom, r.cropbox.width, r.cropbox.height)] == [0, 400, 600, 400]
        result = page.get_by_role('img', name='Result preview page 1', exact=True)
        expect(result).to_be_visible(timeout=45000)
        close(result.evaluate('c => c.width / c.height'), 400 / 600, 0.02, 'rotated result preview aspect ratio')
    record('crop margins follow a rotated page as displayed', rotated_crop)

    def pdf_image_crop():
        load(['pages.pdf'], 'pdf-images')
        page.get_by_test_id('page-range').fill('2')
        expect(page.get_by_test_id('crop-selector')).to_be_visible(timeout=45000)
        for label, value in {'Left': '40', 'Top': '50', 'Right': '300', 'Bottom': '650'}.items():
            page.get_by_label(label, exact=True).fill(value)
        image = Image.open(run('page-2-cropped.png'))
        assert image.format == 'PNG' and image.size == (390, 150), image.size
        assert image.convert('L').getextrema()[0] < 100, 'The cropped area contains the page heading'
        expect(page.get_by_role('img', name='Preview of page-2.png', exact=True)).to_be_visible()
    record('export a cropped area of a PDF page as PNG and preview it', pdf_image_crop)

    def image_crop():
        load(['halves.png'], 'image-tools')
        expect(page.get_by_role('img', name='Source image halves.png', exact=True)).to_be_visible(timeout=45000)
        page.get_by_role('combobox', name='Format', exact=True).select_option('image/png')
        drag('crop-selector', (0.55, 0.05), (0.95, 0.95))
        m = values(['Left', 'Bottom', 'Right', 'Top'])
        close(m['Left'], 132, 3, 'image crop left')
        close(m['Right'], 12, 3, 'image crop right')
        image = Image.open(run('halves-cropped.png')).convert('RGB')
        assert image.size == (240 - m['Left'] - m['Right'], 120 - m['Top'] - m['Bottom']), image.size
        colors = image.getcolors()
        assert colors and all(b > 180 and r < 80 for _, (r, g, b) in colors), 'Only the blue half remains'
        expect(page.get_by_role('img', name='Preview of image.png', exact=True)).to_be_visible()
        page.get_by_role('button', name='Reset crop', exact=True).click()
        assert values(['Left', 'Right'])['Left'] == 0
    record('crop image pixels by dragging on the source image', image_crop)

    def placement():
        load(['pages.pdf'], 'annotate')
        page.get_by_label('Page', exact=True).fill('2')
        expect(page.get_by_label('Preview page 2', exact=True)).to_be_visible(timeout=45000)
        page.get_by_label('New text', exact=True).fill('Placed here')
        drag('placement-selector', (0.5, 0.5), (0.9, 0.6))
        r = values(['X · from left (pt)', 'Y · from bottom (pt)', 'Width (pt)', 'Height (pt)'])
        for label, expected in {'X · from left (pt)': 300, 'Y · from bottom (pt)': 320, 'Width (pt)': 240, 'Height (pt)': 80}.items():
            close(r[label], expected, 4, label)
        result = PdfReader(run('placed.pdf'))
        found = []
        result.pages[1].extract_text(visitor_text=lambda text, cm, tm, *_: found.append(tm) if 'Placed here' in text else None)
        assert found, 'Annotation text is on page 2'
        close(found[0][4], r['X · from left (pt)'], 0.01, 'text x')
        # The first baseline is one Helvetica ascent (718/1000 em at the default 18 pt) below the box top.
        close(found[0][5], r['Y · from bottom (pt)'] + r['Height (pt)'] - 18 * 0.718, 0.05, 'text baseline y')
        expect(page.get_by_role('img', name='Result preview page 2', exact=True)).to_be_visible(timeout=45000)
    record('draw an annotation box on the preview and preview the annotated page', placement)

    def text_preview():
        load(['pages.pdf'], 'text')
        page.get_by_test_id('page-range').fill('3')
        assert 'Gamma' in run('text.txt').read_text()
        expect(page.get_by_test_id('text-preview')).to_contain_text('Original Gamma')
    record('preview extracted text', text_preview)

    def controls():
        bad = page.locator('button:enabled, a[href]').evaluate_all("""els => els.filter(e => e.getClientRects().length &&
          getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).cursor !== 'pointer').map(e => e.getAttribute('aria-label') || e.innerText)""")
        assert not bad, bad
        assert not uploads, uploads
        assert not errors, errors
    record('pointer cursors, no uploads and no uncaught page errors', controls)
    browser.close()

(ART / 'crop-preview.json').write_text(json.dumps({'base_url': BASE, 'checks': results, 'browser_errors': errors}, indent=2))
print(json.dumps({'passed': len(results), 'base_url': BASE}, indent=2))
