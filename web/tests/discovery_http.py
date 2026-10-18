"""Verify crawler files and that every discovery URL serves the app for new and returning visitors."""
import os
import unittest
import urllib.request
import xml.etree.ElementTree as ET

BASE = os.environ.get('LEAFSMITH_URL', 'http://127.0.0.1:3150').rstrip('/')
PUBLIC = 'https://leafsmith.lakebed.app'
GUIDES = {'/merge-pdf': 'merge', '/split-pdf': 'split', '/images-to-pdf': 'images-pdf', '/sign-pdf': 'sign'}
# Headers a browser sends when a URL is typed, bookmarked or opened from another application.
DIRECT_NAVIGATION = {'Accept': 'text/html', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document', 'Sec-Fetch-Site': 'none'}


def fetch(path, headers=None):
    request = urllib.request.Request(BASE + path, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.headers, response.read().decode()

class DiscoveryHTTP(unittest.TestCase):
    def test_homepage_initial_title_describes_tools(self):
        status, headers, body = fetch('/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers.get('Content-Type', ''))
        self.assertIn('<title>Leafsmith — Free PDF &amp; Image Tools, No Uploads</title>', body)

    def test_crawler_files_list_every_canonical_discovery_url(self):
        status, headers, robots = fetch('/robots.txt')
        self.assertEqual(status, 200)
        self.assertIn('text/plain', headers.get('Content-Type', ''))
        self.assertIn('User-agent: *', robots)
        self.assertIn('Sitemap: ' + PUBLIC + '/sitemap.xml', robots)
        status, headers, sitemap = fetch('/sitemap.xml')
        self.assertEqual(status, 200)
        self.assertIn('xml', headers.get('Content-Type', ''))
        root = ET.fromstring(sitemap)
        urls = [node.text for node in root.findall('{*}url/{*}loc')]
        expected = [PUBLIC + path for path in ['/', '/tools', *GUIDES]]
        self.assertEqual(sorted(urls), sorted(expected))
        self.assertEqual(len(set(urls)), len(urls))

    def test_discovery_urls_open_the_app_for_new_and_returning_visitors(self):
        status, headers, _ = fetch('/', DIRECT_NAVIGATION)
        self.assertEqual(status, 200)
        cookies = [value.split(';', 1)[0] for value in headers.get_all('Set-Cookie') or [] if 'lakebed_guest' in value]
        self.assertEqual(len(cookies), 1, 'Opening the workspace must start the guest session a returning visitor carries')
        for visitor, extra in [('new', {}), ('returning', {'Cookie': cookies[0]})]:
            for path in ['/tools', *GUIDES]:
                with self.subTest(visitor=visitor, path=path):
                    status, headers, body = fetch(path, {**DIRECT_NAVIGATION, **extra})
                    self.assertEqual(status, 200)
                    self.assertIn('text/html', headers.get('Content-Type', ''))
                    self.assertIn('src="/client.js', body)
                    self.assertNotIn('gtag(', body)
                    self.assertNotIn('googletagmanager', body)

if __name__ == '__main__':
    unittest.main()
