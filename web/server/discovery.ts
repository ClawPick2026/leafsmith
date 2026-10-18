import { guides, siteUrl, homeDescription, type Guide } from '../shared/discovery.ts';

function htmlEscape(value: string): string {
  return value.replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]!));
}

const styles = `
*{box-sizing:border-box}body{margin:0;background:#f8f9f4;color:#283c31;font:1rem/1.7 system-ui,sans-serif}
header,main,footer{max-width:58rem;margin:auto;padding:1.25rem}header{border-bottom:1px solid #dfe4d6}
nav{display:flex;flex-wrap:wrap;gap:1rem}a{color:#2e4c3b;cursor:pointer;text-underline-offset:.2em}a:focus-visible{outline:3px solid #a74d34;outline-offset:4px}
h1{font:2.5rem/1.15 Georgia,serif;letter-spacing:-.025em}h2{font-size:1.35rem;margin-top:2rem}h3{font-size:1.05rem}
section,article{margin:1.5rem 0;padding:1.25rem;background:#fffefa;border:1px solid #dfe4d6;border-radius:.75rem}
li+li{margin-top:.65rem}li,p,a{overflow-wrap:anywhere}.cta{display:inline-block;padding:.7rem 1.1rem;background:#2e4c3b;color:#fffefa;border-radius:.4rem;text-decoration:none}
footer{font-size:.9rem}ol,ul{padding-left:1.5rem}@media(max-width:40rem){h1{font-size:2rem}header,main,footer{padding:1rem}section,article{padding:1rem}}
`;

const scopeHtml = `<section aria-labelledby="privacy"><h2 id="privacy">Privacy and browser edition limits</h2>
<p>Free to use, with no account and no document uploads. Files are processed in tab memory, not on our server. Download your results before closing or reloading the tab; there is no saved workspace.</p>
<p>The host and CDN receive request metadata such as your IP address when you load the app or libraries. Third-party scripts run in the page and must be trusted. You need internet access to load processing libraries; offline operation is not guaranteed.</p>
<p>Limits: 8 files, 25 MiB per file, 50 MiB combined and 200 pages per PDF. Device memory may impose lower practical limits. Password-protected PDFs are rejected.</p>
<p>This browser edition has no OCR, Office conversion or original text editing. Crop changes the visible page box, not underlying content; it is not redaction.</p></section>`;

function jsonLd(guide?: Guide): string {
  const graph: Record<string, unknown>[] = [{
    '@type': 'WebApplication', name: 'Paperwork', url: siteUrl + '/',
    description: homeDescription, applicationCategory: 'UtilitiesApplication',
    operatingSystem: 'Any (web browser)',
    browserRequirements: 'JavaScript required; internet access needed to load processing libraries.',
    isAccessibleForFree: true,
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
  }];
  if (guide) graph.push({
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Paperwork', item: siteUrl + '/' },
      { '@type': 'ListItem', position: 2, name: 'Tool guides', item: siteUrl + '/tools' },
      { '@type': 'ListItem', position: 3, name: guide.heading, item: siteUrl + guide.path },
    ],
  });
  // JSON remains parseable while script-closing text and JS separators cannot break out.
  const json = JSON.stringify({ '@context': 'https://schema.org', '@graph': graph })
    .replace(/[<>&\u2028\u2029]/g, character => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`);
  return `<script type="application/ld+json">${json}</script>`;
}

function documentHtml(path: string, title: string, description: string, body: string, guide?: Guide): string {
  const canonical = siteUrl + path;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${htmlEscape(title)}</title><meta name="description" content="${htmlEscape(description)}"><link rel="canonical" href="${htmlEscape(canonical)}">
<meta property="og:title" content="${htmlEscape(title)}"><meta property="og:description" content="${htmlEscape(description)}"><meta property="og:url" content="${htmlEscape(canonical)}"><meta property="og:type" content="website"><meta property="og:site_name" content="Paperwork">
<meta name="twitter:card" content="summary"><meta name="twitter:title" content="${htmlEscape(title)}"><meta name="twitter:description" content="${htmlEscape(description)}">
<style>${styles}</style>${jsonLd(guide)}</head><body><header><nav aria-label="Main navigation"><a href="/">Paperwork workspace</a><a href="/tools">Tool guides</a></nav></header><main>${body}${scopeHtml}</main><footer><a href="/">Open Paperwork</a> · <a href="/tools">All tool guides</a></footer></body></html>`;
}

function guideLinks(items: Guide[]): string {
  return `<ul>${items.map(guide => `<li><a href="${htmlEscape(guide.path)}">${htmlEscape(guide.heading)}</a></li>`).join('')}</ul>`;
}

export function renderGuide(guide: Guide): string {
  return documentHtml(guide.path, guide.title, guide.description, `
<h1>${htmlEscape(guide.heading)}</h1><p>${htmlEscape(guide.intro)}</p>
<p><a class="cta" href="/?tool=${htmlEscape(encodeURIComponent(guide.toolId))}">Open this tool</a></p>
<section aria-labelledby="steps"><h2 id="steps">How to use it</h2><ol>${guide.steps.map(step => `<li>${htmlEscape(step)}</li>`).join('')}</ol></section>
<section aria-labelledby="limits"><h2 id="limits">Limitations</h2><ul>${guide.limitations.map(limit => `<li>${htmlEscape(limit)}</li>`).join('')}</ul></section>
<section aria-labelledby="questions"><h2 id="questions">Questions and answers</h2>${guide.faq.map(faq => `<h3>${htmlEscape(faq.question)}</h3><p>${htmlEscape(faq.answer)}</p>`).join('')}</section>
<nav aria-label="Other tool guides">${guideLinks(guides.filter(item => item.path !== guide.path))}</nav>`, guide);
}
export function renderGuideIndex(): string {
  return documentHtml('/tools', 'PDF & Image Tool Guides — Paperwork',
    'Instructions for merging and splitting PDFs, converting images to PDF and drawing electronic signatures. Free browser tools with no account or document uploads.',
    `<h1>PDF and image tool guides</h1><p>Choose a guide for steps, input limits and output checks, or <a href="/">open the workspace</a>.</p>
${guides.map(guide => `<article><h2><a href="${htmlEscape(guide.path)}">${htmlEscape(guide.heading)}</a></h2><p>${htmlEscape(guide.description)}</p></article>`).join('')}`);
}
export function renderSitemap(): string {
  const paths = ['/', '/tools', ...guides.map(guide => guide.path)];
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${paths.map(path => `<url><loc>${htmlEscape(siteUrl + path)}</loc></url>`).join('\n')}\n</urlset>\n`;
}
export function renderRobots(): string {
  return `User-agent: *\nAllow: /\nSitemap: ${siteUrl}/sitemap.xml\n`;
}
