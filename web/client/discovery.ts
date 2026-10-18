import { homeTitle, homeDescription, siteUrl } from '../shared/discovery.ts';
import { useEffect } from 'preact/hooks';

export function HomeMetadata() {
  useEffect(applyHomeMetadata, []);
  return null;
}

/** Only public product metadata belongs here; never include workspace contents. */
export function applyHomeMetadata() {
  document.title = homeTitle;
  const meta = (attribute: 'name' | 'property', key: string, content: string) => {
    let element = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${key}"]`);
    if (!element) {
      element = document.createElement('meta');
      element.setAttribute(attribute, key);
      document.head.append(element);
    }
    element.content = content;
  };
  meta('name', 'description', homeDescription);
  meta('property', 'og:type', 'website');
  meta('property', 'og:site_name', 'Paperwork');
  meta('property', 'og:title', homeTitle);
  meta('property', 'og:description', homeDescription);
  meta('property', 'og:url', siteUrl + '/');
  meta('name', 'twitter:card', 'summary');
  meta('name', 'twitter:title', homeTitle);
  meta('name', 'twitter:description', homeDescription);
  let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement('link');
    canonical.rel = 'canonical';
    document.head.append(canonical);
  }
  canonical.href = siteUrl + '/';
}
