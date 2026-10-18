import { capsule, endpoint, text } from 'lakebed/server';
import { guides, homeTitle } from '../shared/discovery.ts';
import { renderGuide, renderGuideIndex, renderRobots, renderSitemap } from './discovery.ts';

// Public, read-only discovery pages only. No document handlers, tables,
// uploads, secrets or outbound requests. Processing stays in browser memory.
const guideEndpoints = Object.fromEntries(guides.map((guide, index) => [
  `guide${index}`,
  endpoint({ method: 'GET', path: guide.path, readOnly: true }, () =>
    text(renderGuide(guide), { headers: { 'Content-Type': 'text/html; charset=utf-8' } })),
]));

export default capsule({
  name: homeTitle,
  auth: { requireSignIn: false },
  schema: {},
  queries: {},
  mutations: {},
  endpoints: {
    status: endpoint({ method: 'GET', path: '/api/status', readOnly: true }, () => text('Paperwork: browser-only processing; no document storage.')),
    robots: endpoint({ method: 'GET', path: '/robots.txt', readOnly: true }, () => text(renderRobots())),
    sitemap: endpoint({ method: 'GET', path: '/sitemap.xml', readOnly: true }, () =>
      text(renderSitemap(), { headers: { 'Content-Type': 'application/xml; charset=utf-8' } })),
    tools: endpoint({ method: 'GET', path: '/tools', readOnly: true }, () =>
      text(renderGuideIndex(), { headers: { 'Content-Type': 'text/html; charset=utf-8' } })),
    ...guideEndpoints,
  }
});
