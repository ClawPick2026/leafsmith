import { capsule, endpoint, text } from 'lakebed/server';
import { homeTitle } from '../shared/discovery.ts';
import { renderRobots, renderSitemap } from './discovery.ts';

// Public, read-only crawler files only. No document handlers, tables,
// uploads, secrets or outbound requests. Processing stays in browser memory.
// Discovery pages are client routes; see client/guides.tsx.

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
  }
});
