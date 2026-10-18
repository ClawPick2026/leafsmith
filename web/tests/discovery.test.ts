import test from 'node:test';
import assert from 'node:assert/strict';
import { siteUrl, homeTitle, homeDescription, guides } from '../shared/discovery.ts';
import { renderGuide, renderGuideIndex, renderSitemap, renderRobots } from '../server/discovery.ts';

const escape = (value: string) => value.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));

function checkDocument(html: string, path: string, title: string, description: string) {
  assert.match(html, /^<!doctype html>/i);
  assert.match(html, /<html lang="en">/);
  assert.match(html, /<meta charset="utf-8">/);
  assert.match(html, /<meta name="viewport" content="width=device-width, initial-scale=1">/);
  assert.ok(html.includes(`<title>${escape(title)}</title>`));
  assert.ok(html.includes(`<meta name="description" content="${escape(description)}">`));
  assert.ok(html.includes(`<link rel="canonical" href="${siteUrl}${path}">`));
  for (const [name, value] of [['og:title', title], ['og:description', description], ['og:url', siteUrl + path], ['og:type', 'website'], ['og:site_name', 'Paperwork']]) {
    assert.ok(html.includes(`<meta property="${name}" content="${escape(value)}">`), name);
  }
  for (const [name, value] of [['twitter:card', 'summary'], ['twitter:title', title], ['twitter:description', description]]) {
    assert.ok(html.includes(`<meta name="${name}" content="${escape(value)}">`), name);
  }
  assert.equal([...html.matchAll(/<h1[ >]/g)].length, 1);
  assert.match(html, /<style>[\s\S]*@media[\s\S]*<\/style>/);
  assert.match(html, /cursor:\s*pointer/);
  assert.doesNotMatch(html, /<script(?! type="application\/ld\+json")|<link[^>]+(?:stylesheet|preload)|@import|https?:\/\/[^"'\s<>]+\.(?:js|css|woff)/i);
  assert.match(html, /<\/body><\/html>$/);
}

test('guide HTML is complete, crawlable and specific to each task', () => {
  for (const guide of guides) {
    const html = renderGuide(guide);
    checkDocument(html, guide.path, guide.title, guide.description);
    assert.ok(html.includes(`<h1>${escape(guide.heading)}</h1>`));
    for (const text of [guide.intro, ...guide.steps, ...guide.limitations, ...guide.faq.flatMap(f => [f.question, f.answer])]) {
      assert.ok(html.includes(escape(text)), text);
    }
    assert.match(html, /<ol>[\s\S]*<li>/);
    assert.ok(html.includes(`href="/?tool=${guide.toolId}"`));
    for (const path of ['/', '/tools', ...guides.filter(g => g !== guide).map(g => g.path)]) {
      assert.ok(html.includes(`href="${path}"`), path);
    }
  }
});

test('directory HTML links every supported guide without duplicating guide metadata', () => {
  const html = renderGuideIndex();
  const title = 'PDF & Image Tool Guides — Paperwork';
  const description = 'Instructions for merging and splitting PDFs, converting images to PDF and drawing electronic signatures. Free browser tools with no account or document uploads.';
  checkDocument(html, '/tools', title, description);
  assert.ok(!guides.some(g => g.title === title || g.description === description));
  assert.match(html, /href="\/"/);
  assert.match(html, /<h1>PDF and image tool guides<\/h1>/);
  for (const guide of guides) {
    assert.ok(html.includes(`href="${guide.path}"`));
    assert.ok(html.includes(escape(guide.description)));
  }
});

test('every discovery page discloses real privacy, loading and scope limits', () => {
  for (const html of [renderGuideIndex(), ...guides.map(renderGuide)]) {
    for (const fact of [
      /Free.*no account/i, /no document uploads/i, /files.*tab memory/i,
      /host.*CDN.*(?:IP|metadata)/i, /third-party scripts.*run.*page/i,
      /internet.*load.*libraries/i, /offline.*not guaranteed/i,
      /8 files/, /25 MiB per file/, /50 MiB combined/, /200 pages per PDF/,
      /password-protected PDFs are rejected/i, /crop.*not redaction/i,
      /no OCR, Office conversion or original text editing/i,
      /Download.*(?:closing|reloading).*tab/i,
    ]) assert.match(html, fact);
    assert.doesNotMatch(html, /100% private|completely private|guaranteed offline|legally binding/i);
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
  for (const guide of guides) assert.ok(renderGuide(guide).includes(`rel="canonical" href="${siteUrl + guide.path}"`));
  assert.doesNotMatch(xml, /lastmod|priority|changefreq|\?tool/);
});

test('robots allows every crawler and points at the canonical sitemap', () => {
  assert.equal(renderRobots(), 'User-agent: *\nAllow: /\nSitemap: https://paperwork.lakebed.app/sitemap.xml\n');
  assert.doesNotMatch(renderRobots(), /Disallow|<[^>]*>/);
});

function structuredData(html: string) {
  const scripts = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1, 'one JSON-LD graph per page');
  assert.doesNotMatch(scripts[0][1], /[<>\u2028\u2029]/);
  return JSON.parse(scripts[0][1]);
}

test('JSON-LD describes the free browser app and each guide breadcrumb without invented endorsements', () => {
  for (const [path, html] of [['/tools', renderGuideIndex()], ...guides.map(g => [g.path, renderGuide(g)])]) {
    const data = structuredData(html);
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
    if (path !== '/tools') {
      const guide = guides.find(g => g.path === path)!;
      const breadcrumb = data['@graph'].find((node: Record<string, unknown>) => node['@type'] === 'BreadcrumbList');
      assert.deepEqual(breadcrumb.itemListElement, [
        { '@type': 'ListItem', position: 1, name: 'Paperwork', item: siteUrl + '/' },
        { '@type': 'ListItem', position: 2, name: 'Tool guides', item: siteUrl + '/tools' },
        { '@type': 'ListItem', position: 3, name: guide.heading, item: siteUrl + path },
      ]);
    }
  }
  const maliciousHeading = '</script><script>alert("&")</script>\u2028\u2029';
  const html = renderGuide({ ...guides[0], heading: maliciousHeading });
  const data = structuredData(html);
  assert.equal(data['@graph'].find((node: Record<string, unknown>) => node['@type'] === 'BreadcrumbList').itemListElement[2].name, maliciousHeading);
  assert.doesNotMatch(html, /<script>alert/);
});

test('guide values stay escaped text and the CTA preserves a single encoded tool value', () => {
  const payload = '<img src=x onerror="alert(1)"> & \'quoted\' </title></script>';
  const toolId = 'merge&other="<bad>\'';
  const guide = {
    ...guides[0], path: '/probe?x="<&\'', toolId,
    title: payload, description: payload, heading: payload, intro: payload,
    steps: [payload], limitations: [payload], faq: [{ question: payload, answer: payload }],
  };
  const html = renderGuide(guide);
  assert.ok(html.includes(`href="/?tool=${escape(encodeURIComponent(toolId))}"`));
  assert.ok(html.includes(`<title>${escape(payload)}</title>`));
  assert.ok(html.includes(`<meta name="description" content="${escape(payload)}">`));
  assert.ok(html.includes(`<h1>${escape(payload)}</h1>`));
  assert.ok(html.includes(`<p>${escape(payload)}</p>`));
  assert.ok(html.includes(`<li>${escape(payload)}</li>`));
  assert.ok(html.includes(`<h3>${escape(payload)}</h3>`));
  assert.ok(html.includes(`rel="canonical" href="${escape(siteUrl + guide.path)}"`));
  assert.doesNotMatch(html, /<img|<bad>|<script(?! type="application\/ld\+json")/);
  assert.equal([...html.matchAll(/<title>/g)].length, 1);
  assert.equal([...html.matchAll(/<\/script>/g)].length, 1);
  const breadcrumb = structuredData(html)['@graph'].find((node: Record<string, unknown>) => node['@type'] === 'BreadcrumbList');
  assert.equal(breadcrumb.itemListElement[2].name, payload);
  assert.equal(breadcrumb.itemListElement[2].item, siteUrl + guide.path);
});

test('image guide distinguishes A4 bounds from fixed A4 sheets', () => {
  const guide = guides.find(g => g.toolId === 'images-pdf')!;
  const html = renderGuide(guide);
  assert.match(html, /page size follows (?:the )?image/i);
  assert.match(html, /A4 bounds/);
  assert.doesNotMatch(html, /per A4 page|own A4 page|within A4 pages/);
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
