import test from 'node:test';
import assert from 'node:assert/strict';
import { siteUrl, homeTitle, homeDescription, guides, guideIndex, scopeHeading, scopeParagraphs, structuredData } from '../shared/discovery.ts';
import { renderSitemap, renderRobots } from '../server/discovery.ts';

test('directory metadata is distinct from every guide', () => {
  assert.equal(guideIndex.path, '/tools');
  assert.equal(guideIndex.title, 'PDF & Image Tool Guides — Paperwork');
  assert.equal(guideIndex.heading, 'PDF and image tool guides');
  assert.ok(guideIndex.description.length > 30);
  assert.ok(!guides.some(g => g.title === guideIndex.title || g.description === guideIndex.description || g.path === guideIndex.path));
});

test('every discovery page discloses real privacy, loading and scope limits', () => {
  assert.equal(scopeHeading, 'Privacy and browser edition limits');
  const scope = scopeParagraphs.join(' ');
  for (const fact of [
    /Free.*no account/i, /no document uploads/i, /files.*tab memory/i,
    /host.*CDN.*(?:IP|metadata)/i, /third-party scripts.*run.*page/i,
    /internet.*load.*libraries/i, /offline.*not guaranteed/i,
    /8 files/, /25 MiB per file/, /50 MiB combined/, /200 pages per PDF/,
    /password-protected PDFs are rejected/i, /crop.*not redaction/i,
    /no OCR, Office conversion or original text editing/i,
    /Download.*(?:closing|reloading).*tab/i,
  ]) assert.match(scope, fact);
  for (const text of [scope, JSON.stringify(guides), JSON.stringify(guideIndex)]) {
    assert.doesNotMatch(text, /100% private|completely private|guaranteed offline|legally binding/i);
  }
});

test('sitemap XML lists only the six canonical discovery URLs', () => {
  const xml = renderSitemap();
  assert.match(xml, /^<\?xml version="1.0" encoding="UTF-8"\?>\n<urlset xmlns="http:\/\/www.sitemaps.org\/schemas\/sitemap\/0.9">/);
  assert.match(xml, /<\/urlset>\n$/);
  const urls = [...xml.matchAll(/<url><loc>([^<]+)<\/loc><\/url>/g)].map(match => match[1]);
  const expected = ['/', '/tools', ...guides.map(g => g.path)].map(path => siteUrl + path);
  assert.deepEqual(urls, expected);
  assert.equal(new Set(urls).size, 6);
  assert.equal(xml, `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${expected.map(url => `<url><loc>${url}</loc></url>`).join('\n')}\n</urlset>\n`);
  assert.doesNotMatch(xml, /lastmod|priority|changefreq|\?tool/);
});

test('robots allows every crawler and points at the canonical sitemap', () => {
  assert.equal(renderRobots(), 'User-agent: *\nAllow: /\nSitemap: https://paperwork.lakebed.app/sitemap.xml\n');
  assert.doesNotMatch(renderRobots(), /Disallow|<[^>]*>/);
});

test('JSON-LD describes the free browser app and each guide breadcrumb without invented endorsements', () => {
  for (const guide of [undefined, ...guides]) {
    const data = JSON.parse(JSON.stringify(structuredData(guide)));
    assert.equal(data['@context'], 'https://schema.org');
    const app = data['@graph'].find((node: Record<string, unknown>) => node['@type'] === 'WebApplication');
    assert.equal(app.name, 'Paperwork');
    assert.equal(app.url, siteUrl + '/');
    assert.equal(app.description, homeDescription);
    assert.equal(app.applicationCategory, 'UtilitiesApplication');
    assert.equal(app.operatingSystem, 'Any (web browser)');
    assert.match(app.browserRequirements, /JavaScript.*internet.*libraries/i);
    assert.equal(app.isAccessibleForFree, true);
    assert.deepEqual(app.offers, { '@type': 'Offer', price: '0', priceCurrency: 'USD' });
    assert.doesNotMatch(JSON.stringify(data), /aggregateRating|review|FAQPage|HowTo|legal|certified/i);
    const breadcrumb = data['@graph'].find((node: Record<string, unknown>) => node['@type'] === 'BreadcrumbList');
    if (!guide) {
      assert.equal(breadcrumb, undefined);
      continue;
    }
    assert.deepEqual(breadcrumb.itemListElement, [
      { '@type': 'ListItem', position: 1, name: 'Paperwork', item: siteUrl + '/' },
      { '@type': 'ListItem', position: 2, name: 'Tool guides', item: siteUrl + '/tools' },
      { '@type': 'ListItem', position: 3, name: guide.heading, item: siteUrl + guide.path },
    ]);
  }
});

test('image guide distinguishes A4 bounds from fixed A4 sheets', () => {
  const guide = JSON.stringify(guides.find(g => g.toolId === 'images-pdf'));
  assert.match(guide, /page size follows (?:the )?image/i);
  assert.match(guide, /A4 bounds/);
  assert.doesNotMatch(guide, /per A4 page|own A4 page|within A4 pages/);
});

test('discovery catalog describes exactly four actionable browser-only guides', () => {
  assert.equal(siteUrl, 'https://paperwork.lakebed.app');
  assert.equal(homeTitle, 'Paperwork — Free PDF & Image Tools, No Uploads');
  assert.match(homeDescription, /free/i);
  assert.match(homeDescription, /no (?:account|uploads)/i);
  assert.deepEqual(guides.map(g => [g.path, g.toolId]), [
    ['/merge-pdf', 'merge'], ['/split-pdf', 'split'],
    ['/images-to-pdf', 'images-pdf'], ['/sign-pdf', 'sign'],
  ]);
  for (const field of ['title', 'description', 'heading', 'intro'] as const) {
    assert.equal(new Set(guides.map(g => g[field])).size, 4, `${field} must be unique`);
    for (const guide of guides) assert.ok(guide[field].length > 25);
  }
  for (const guide of guides) {
    assert.ok(guide.steps.length >= 4);
    assert.ok(guide.limitations.length >= 2);
    assert.ok(guide.faq.length >= 2);
    assert.match(guide.steps.join(' '), /Download/);
    for (const faq of guide.faq) {
      assert.ok(faq.question.endsWith('?'));
      assert.ok(faq.answer.length > 30);
    }
  }
  const content = (id: string) => JSON.stringify(guides.find(g => g.toolId === id));
  assert.match(content('merge'), /↑.*↓/);
  assert.match(content('merge'), /200.*(?:merged|output)|(?:merged|output).*200/);
  assert.match(content('merge'), /forms.*bookmarks/);
  assert.match(content('split'), /1,3-5/);
  assert.match(content('split'), /30/);
  assert.match(content('split'), /multiple downloads/);
  assert.match(content('images-pdf'), /PNG.*JPEG/);
  assert.match(content('images-pdf'), /A4/);
  assert.match(content('images-pdf'), /OCR/);
  assert.match(content('sign'), /from (?:the )?bottom/);
  assert.match(content('sign'), /not certificate-backed/);
  assert.match(content('sign'), /not identity verified/);
  assert.match(content('sign'), /invalidate existing certificate signatures/);
});
