"""Verify the real website preview link and the bytes downloaded through it."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('PAPERWORK_URL', 'https://paperwork.lakebed.app')
INSTALLER = 'https://github.com/ClawPick2026/paperwork-desktop/releases/download/v0.1.0-rc.1/Paperwork_0.1.0_x64-setup.exe'
RELEASE = 'https://github.com/ClawPick2026/paperwork-desktop/releases/tag/v0.1.0-rc.1'
SHA256 = '8d823fccb3cd29232a34146815b1ed0c6b809d63089c2b9056715ed75990b112'

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

    def test_preview_link_downloads_verified_installer_with_honest_scope(self):
        page = self.browser.new_page(viewport={'width':1440, 'height':1080}, accept_downloads=True)
        try:
            page.goto(BASE, wait_until='networkidle')
            section = page.get_by_role('region', name='Desktop downloads', exact=True)
            expect(section).to_be_visible(timeout=5000)
            link = section.get_by_role('link', name='Download Windows preview', exact=True)
            expect(link).to_have_attribute('href', INSTALLER)
            expect(section.get_by_role('link', name='Release notes & checksums', exact=True)).to_have_attribute('href', RELEASE)
            for phrase in ['Unsigned', 'Linux', 'not ready', 'Interactive Windows GUI testing is pending']:
                self.assertIn(phrase, section.inner_text())
            link.hover()
            self.assertEqual(link.evaluate('element=>getComputedStyle(element).cursor'), 'pointer')
            with page.expect_download(timeout=90000) as event:
                link.click()
            download = event.value
            self.assertEqual(download.suggested_filename, 'Paperwork_0.1.0_x64-setup.exe')
            self.assertIsNone(download.failure())
            with Path(download.path()).open('rb') as stream:
                self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(), SHA256)
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
