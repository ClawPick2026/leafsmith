"""Verify the real website preview links and the bytes downloaded through them."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('LEAFSMITH_URL', 'https://leafsmith.lakebed.app')
RELEASE = 'https://github.com/ClawPick2026/leafsmith/releases/tag/v0.1.0-rc.3'
PACKAGES = [
    ('Download Windows preview', 'windows', 'Windows', 'Leafsmith_0.1.0_x64-setup.exe', '5a43304e1d16811b64c331254869dd034635e931606cd5671d98ad3db6f30810'),
    ('Download Linux preview', 'linux', 'Linux', 'Leafsmith_0.1.0_amd64.AppImage', '726ff00e552c8e2666c92d82b155d5b4b91211ff8aa1bc841742cbb1a67c6e97'),
]

class DesktopDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = json.loads((ROOT/'tests/browser-env.json').read_text())
        env = dict(os.environ, LD_LIBRARY_PATH=settings['library_path'])
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True, executable_path=settings['executable_path'], args=settings['launch_args'], env=env)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def test_preview_links_download_verified_packages_with_honest_scope(self):
        page = self.browser.new_page(viewport={'width':1440, 'height':1080}, accept_downloads=True)
        try:
            page.goto(BASE, wait_until='networkidle')
            section = page.get_by_role('region', name='Desktop downloads', exact=True)
            expect(section).to_be_visible(timeout=5000)
            expect(section.get_by_role('link', name='Release notes & checksums', exact=True)).to_have_attribute('href', RELEASE)
            text = section.inner_text()
            for phrase in ['0.1.0-rc.3', 'Unsigned', 'Interactive use has not been tested', 'glibc 2.35', 'unrecognized-publisher']:
                self.assertIn(phrase, text)
            self.assertNotIn('rc.1', text)
            for name, icon, label, filename, sha256 in PACKAGES:
                link = section.get_by_role('link', name=name, exact=True)
                expect(link.locator('svg')).to_have_count(1)
                expect(link.locator(f'svg[data-icon="{icon}"]')).to_be_visible()
                expect(link).to_have_text(label)
                expect(link).to_have_attribute('href', f'https://github.com/ClawPick2026/leafsmith/releases/download/v0.1.0-rc.3/{filename}')
                link.hover()
                self.assertEqual(link.evaluate('element=>getComputedStyle(element).cursor'), 'pointer')
                with page.expect_download(timeout=300000) as event:
                    link.click()
                download = event.value
                self.assertEqual(download.suggested_filename, filename)
                self.assertIsNone(download.failure())
                with Path(download.path()).open('rb') as stream:
                    self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(), sha256)
            section.screenshot(path=str(ROOT/'tests/browser-env/desktop-downloads.png'))
        finally:
            page.close()

    def test_mobile_download_section_has_no_horizontal_overflow(self):
        page = self.browser.new_page(viewport={'width':390, 'height':844})
        try:
            page.goto(BASE, wait_until='networkidle')
            section = page.get_by_role('region', name='Desktop downloads', exact=True)
            expect(section).to_be_visible(timeout=5000)
            section.scroll_into_view_if_needed()
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.screenshot(path=str(ROOT/'tests/browser-env/mobile-downloads.png'))
        finally:
            page.close()

if __name__ == '__main__':
    unittest.main()
