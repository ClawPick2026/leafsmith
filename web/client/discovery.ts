import { homeTitle, homeDescription, siteUrl } from '../shared/discovery.ts';
import { useEffect } from 'preact/hooks';

export type PageMetadata = { path: string; title: string; description: string; structuredData?: object };

const home: PageMetadata = { path: '/', title: homeTitle, description: homeDescription };

export function HomeMetadata() {
  usePageMetadata(home);
  return null;
}

export function usePageMetadata(page: PageMetadata) {
  useEffect(() => applyMetadata(page), [page.path]);
}

/** Only public product metadata belongs here; never include workspace contents. */
export function applyMetadata({ path, title, description, structuredData }: PageMetadata) {
  document.title = title;
  const meta = (attribute: 'name' | 'property', key: string, content: string) => {
    let element = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${key}"]`);
    if (!element) {
      element = document.createElement('meta');
      element.setAttribute(attribute, key);
      document.head.append(element);
    }
    element.content = content;
  };
  meta('name', 'description', description);
  meta('property', 'og:type', 'website');
  meta('property', 'og:site_name', 'Leafsmith');
  meta('property', 'og:title', title);
  meta('property', 'og:description', description);
  meta('property', 'og:url', siteUrl + path);
  meta('name', 'twitter:card', 'summary');
  meta('name', 'twitter:title', title);
  meta('name', 'twitter:description', description);
  let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement('link');
    canonical.rel = 'canonical';
    document.head.append(canonical);
  }
  canonical.href = siteUrl + path;
  // textContent is never parsed as HTML, so guide text cannot close the script element.
  let graph = document.head.querySelector<HTMLScriptElement>('script[type="application/ld+json"]');
  if (!structuredData) {
    graph?.remove();
    return;
  }
  if (!graph) {
    graph = document.createElement('script');
    graph.type = 'application/ld+json';
    document.head.append(graph);
  }
  graph.textContent = JSON.stringify(structuredData);
}
