import { guides, guideIndex, siteUrl } from '../shared/discovery.ts';

function xmlEscape(value: string): string {
  return value.replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[character]!));
}

// Guide pages are client routes in the app shell. A GET endpoint at those paths
// would reject direct visits from anyone holding the app's guest-session cookie.
export function renderSitemap(): string {
  const paths = ['/', guideIndex.path, ...guides.map(guide => guide.path)];
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${paths.map(path => `<url><loc>${xmlEscape(siteUrl + path)}</loc></url>`).join('\n')}\n</urlset>\n`;
}
export function renderRobots(): string {
  return `User-agent: *\nAllow: /\nSitemap: ${siteUrl}/sitemap.xml\n`;
}
