"""Real-browser dark mode acceptance for the website and desktop preview.
Run with the test venv: theme_browser.py BASE [web|desktop]. The desktop preview has no guide pages.
Screenshots go to the ignored tests/artifacts/theme/ directory.
"""
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1].rstrip('/')
TARGET = sys.argv[2] if len(sys.argv) > 2 else 'web'
ARTIFACTS = ROOT.parent / 'tests/artifacts/theme'
ARTIFACTS.mkdir(parents=True, exist_ok=True)
LIGHT_PAGE, DARK_PAGE = 'rgb(248, 249, 244)', 'rgb(19, 24, 20)'
settings = json.loads((ROOT / 'tests/browser-env.json').read_text())
env = os.environ.copy()
if settings.get('library_path'):
    env['LD_LIBRARY_PATH'] = settings['library_path']


def page_background(page):
    return page.evaluate("getComputedStyle(document.querySelector('.min-h-screen')).backgroundColor")


def assert_theme(page, theme):
    toggle = page.get_by_role('button', name='Dark mode')
    expect(toggle).to_have_attribute('aria-pressed', 'true' if theme == 'dark' else 'false')
    assert page.evaluate('document.documentElement.style.colorScheme') == theme
    expected = DARK_PAGE if theme == 'dark' else LIGHT_PAGE
    assert page_background(page) == expected, f'{theme} page background is {page_background(page)}'
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") in (expected, 'rgba(0, 0, 0, 0)')


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, executable_path=settings['executable_path'], env=env,
        args=settings.get('launch_args', ['--no-sandbox']),
    )
    errors = []

    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, color_scheme='light')
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(BASE, wait_until='networkidle')
    assert_theme(page, 'light')
    toggle = page.get_by_role('button', name='Dark mode')
    assert toggle.evaluate('e => getComputedStyle(e).cursor') == 'pointer'
    expect(toggle).to_have_attribute('title', 'Switch to dark mode')
    page.screenshot(path=str(ARTIFACTS / f'{TARGET}-light.png'))
    toggle.click()
    assert_theme(page, 'dark')
    expect(toggle).to_have_attribute('title', 'Switch to light mode')
    assert page.evaluate("localStorage.getItem('leafsmith-theme')") == 'dark'
    page.screenshot(path=str(ARTIFACTS / f'{TARGET}-dark.png'))
    print('PASS toggle switches a light-system page to dark and stores only the choice')

    page.reload(wait_until='networkidle')
    assert_theme(page, 'dark')
    print('PASS saved dark choice survives reload')

    page.get_by_role('button', name='Try a sample', exact=True).click()
    expect(page.get_by_test_id('run-tool')).to_be_enabled(timeout=45000)
    expect(page.get_by_label('Preview page 1')).to_be_visible(timeout=45000)
    assert page.evaluate("getComputedStyle(document.querySelector('[aria-label=\"Preview page 1\"]').parentElement).backgroundColor") == 'rgb(255, 255, 255)'
    page.screenshot(path=str(ARTIFACTS / f'{TARGET}-dark-tool.png'), full_page=True)
    print('PASS document preview stays on a white page in dark mode')

    if TARGET == 'web':
        page.goto(BASE + '/tools', wait_until='networkidle')
        assert_theme(page, 'dark')
        page.get_by_role('button', name='Dark mode').click()
        assert_theme(page, 'light')
        page.goto(BASE, wait_until='networkidle')
        assert_theme(page, 'light')
        print('PASS guide pages share the toggle and saved choice')
    else:
        page.get_by_role('button', name='Dark mode').click()
        assert_theme(page, 'light')
    context.close()

    context = browser.new_context(viewport={'width': 390, 'height': 844}, color_scheme='dark')
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(BASE, wait_until='networkidle')
    assert_theme(page, 'dark')
    assert page.evaluate("localStorage.getItem('leafsmith-theme')") is None
    overflow = page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 0, f'header overflows a 390 px viewport by {overflow}px'
    page.screenshot(path=str(ARTIFACTS / f'{TARGET}-dark-mobile.png'))
    for width in (390, 640, 1024):
        page.set_viewport_size({'width': width, 'height': 844})
        layout = page.evaluate("""() => { const header = document.querySelector('header');
          const box = e => e.getBoundingClientRect();
          return { gap: box(header.querySelector('[aria-label="Dark mode"]')).left - box(header.firstElementChild).right,
                   scopeHeight: box([...header.querySelectorAll('button')].find(b => b.innerText.includes('Scope'))).height } }""")
        assert layout['gap'] >= 8, f'{width}px: toggle is {layout["gap"]}px from the brand'
        if width >= 640:
            assert layout['scopeHeight'] <= 44, f'{width}px: Scope & privacy wraps ({layout["scopeHeight"]}px tall)'
    print('PASS dark system preference applies without a saved choice; header controls keep their spacing')
    context.close()

    assert not errors, errors
    browser.close()
