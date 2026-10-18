"""Verify the deployed HTTP discovery graph without executing JavaScript."""
import json
import os
import unittest
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

BASE = os.environ.get('PAPERWORK_URL', 'http://127.0.0.1:3150').rstrip('/')
PUBLIC = 'https://paperwork.lakebed.app'
GUIDES = {'/merge-pdf': 'merge', '/split-pdf': 'split', '/images-to-pdf': 'images-pdf', '/sign-pdf': 'sign'}

class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
    def handle_data(self, text):
        self.text.append(text)


def fetch(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return response.status, response.headers.get('Content-Type', ''), response.read().decode()

class DiscoveryHTTP(unittest.TestCase):
    def test_homepage_initial_title_describes_tools(self):
        status, mime, body = fetch('/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', mime)
        self.assertIn('<title>Paperwork — Free PDF &amp; Image Tools, No Uploads</title>', body)

    def test_crawlers_can_follow_complete_discovery_graph_without_javascript(self):
        status, mime, robots = fetch('/robots.txt')
        self.assertEqual(status, 200)
        self.assertIn('text/plain', mime)
        self.assertIn('User-agent: *', robots)
        self.assertIn('Sitemap: ' + PUBLIC + '/sitemap.xml', robots)
        status, mime, sitemap = fetch('/sitemap.xml')
        self.assertEqual(status, 200)
        self.assertIn('xml', mime)
        root = ET.fromstring(sitemap)
        urls = [node.text for node in root.findall('{*}url/{*}loc')]
        expected = [PUBLIC + path for path in ['/', '/tools', *GUIDES]]
        self.assertEqual(sorted(urls), sorted(expected))
        self.assertEqual(len(set(urls)), len(urls))
        titles = set()
        for path in ['/tools', *GUIDES]:
            with self.subTest(path=path):
                status, mime, body = fetch(path)
                self.assertEqual(status, 200)
                self.assertIn('text/html', mime)
                page = Page(body)
                self.assertEqual(len([t for t, a in page.tags if t == 'h1']), 1)
                canonical = [a['href'] for t, a in page.tags if t == 'link' and a.get('rel') == 'canonical']
                self.assertEqual(canonical, [PUBLIC + path])
                descriptions = [a.get('content', '') for t, a in page.tags if t == 'meta' and a.get('name') == 'description']
                self.assertTrue(descriptions and len(descriptions[0]) > 30)
                self.assertTrue(any(t == 'meta' and a.get('property') == 'og:title' for t, a in page.tags))
                import re
                title = re.search(r'<title>(.*?)</title>', body).group(1)
                self.assertNotIn(title, titles)
                titles.add(title)
                links = [a.get('href') for t, a in page.tags if t == 'a']
                self.assertIn('/', links)
                for guide in GUIDES:
                    if guide != path:
                        self.assertIn(guide, links)
                if path in GUIDES:
                    self.assertIn('/tools', links)
                    self.assertIn('/?tool=' + GUIDES[path], links)
                    self.assertIn('No account', body)
                    self.assertIn('200', body)
                self.assertNotIn('src="/client.js', body)
                self.assertNotIn('gtag(', body)
                self.assertNotIn('googletagmanager', body)

if __name__ == '__main__':
    unittest.main()
