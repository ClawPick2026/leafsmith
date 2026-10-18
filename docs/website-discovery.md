# Website search discovery

The browser edition uses `https://paperwork.lakebed.app` as its canonical public origin. This is intentionally separate from the desktop application's title and metadata.

## Public pages

- `/` remains the existing interactive workspace. Its descriptive title is present in the initial Lakebed HTML; description, canonical and Open Graph/Twitter text metadata are installed when JavaScript runs.
- `/tools` is a server-rendered directory.
- `/merge-pdf`, `/split-pdf`, `/images-to-pdf` and `/sign-pdf` are server-rendered guides with distinct titles, descriptions, instructions, limitations, FAQs, canonical links and ordinary navigation links. They are usable as reading material without JavaScript. Their action links open the actual workspace tool via an allowlisted `?tool=` value.
- `/robots.txt` is a plain-text crawler file pointing at `/sitemap.xml`.
- `/sitemap.xml` enumerates the homepage, directory and four guides. Tool query URLs are not separately advertised as indexable pages.

`web/shared/discovery.ts` owns public identity and guide content. `web/server/discovery.ts` generates escaped HTML and sitemap/robots bodies. `web/server/index.ts` registers read-only GET endpoints using Lakebed's documented response helpers. No undocumented Lakebed HTML-shell replacement, bot-specific content, new hosting service, analytics, document upload or processing backend is introduced.

## Limits and excluded actions

The workspace still depends on JavaScript. The default Lakebed shell does not provide a documented arbitrary-head injection API, so its meta description and canonical are client-rendered; guide-page metadata is in the HTTP response and can be read by non-JavaScript link unfurlers. The standard workspace title is set through `capsule.name`.

A valid sitemap, structured data and crawlable pages do not guarantee indexing or rankings. No Search Console or Bing account has been registered or verified, no indexing submission has been made, and no directories or third parties have been contacted. These are website-side improvements only.

The application remains a preview with the existing privacy and capability boundaries. Guide copy must not imply OCR, Office conversion, original-text editing, secure redaction, guaranteed compression or certificate-backed signing. Hosting and CDN requests still carry ordinary network metadata.

## Verification

From the repository root, using the existing task-local browser Python environment:

```sh
npm test
npm run build
npm run web:build
npx --yes lakebed@0.0.40 dev web --host 127.0.0.1 --port 3150
PAPERWORK_URL=http://127.0.0.1:3150 PYTHON web/tests/discovery_http.py
PYTHON web/tests/seo_browser.py http://127.0.0.1:3150 all
PYTHON web/tests/e2e.py http://127.0.0.1:3150
PYTHON web/tests/review_regressions.py http://127.0.0.1:3150
```

Replace `PYTHON` with the existing test venv's interpreter; do not install browser dependencies globally. Repeat HTTP/browser acceptance against the exact public hostname after an authorized deployment. The HTTP suite checks the no-JavaScript discovery graph. The discovery browser suite checks metadata, actual guide-to-tool navigation, invalid tool fallback, responsive widths and uncaught exceptions. Existing browser suites independently inspect real PDF/image downloads and privacy behavior.
