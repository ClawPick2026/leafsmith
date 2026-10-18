# Website search discovery

The browser edition uses `https://leafsmith.lakebed.app` as its canonical public origin. This is intentionally separate from the desktop application's title and metadata.

## Public pages

- `/` remains the existing interactive workspace. Its descriptive title is present in the initial Lakebed HTML; description, canonical and Open Graph/Twitter text metadata are installed when JavaScript runs.
- `/tools` is a directory of the guides.
- `/merge-pdf`, `/split-pdf`, `/images-to-pdf` and `/sign-pdf` are guides with distinct titles, descriptions, instructions, limitations, FAQs, canonical links, JSON-LD breadcrumbs and ordinary navigation links. Their action links open the actual workspace tool via an allowlisted `?tool=` value.
- `/robots.txt` is a plain-text crawler file pointing at `/sitemap.xml`.
- `/sitemap.xml` enumerates the homepage, directory and four guides. Tool query URLs are not separately advertised as indexable pages.

`/tools` and the guides are client routes rendered by `web/client/guides.tsx` inside the Lakebed app shell, not server endpoints. Opening the workspace starts a Lakebed guest session (a 30-day, origin-scoped cookie), and Lakebed rejects endpoint requests that carry that cookie unless the browser marks them same-origin. Server-rendered guide endpoints therefore returned a JSON 403 to returning visitors who opened a guide from a bookmark, the address bar, another application or another `*.lakebed.app` app. Only `robots.txt`, `sitemap.xml` and `/api/status` remain endpoints.

`web/shared/discovery.ts` owns public identity, guide content, the shared privacy/limits text and the JSON-LD graph. `web/client/discovery.ts` installs each page's title, description, canonical, sharing metadata and JSON-LD. `web/server/discovery.ts` generates the sitemap and robots bodies. No undocumented Lakebed HTML-shell replacement, bot-specific content, new hosting service, analytics, document upload or processing backend is introduced.

## Limits and excluded actions

Every page depends on JavaScript. The initial HTML for every path is the Lakebed shell with the homepage title, because the default shell has no documented arbitrary-head injection API. Search engines that render JavaScript see each page's own metadata; clients that do not run JavaScript, such as many link-preview services, see the homepage title and no guide text.

A valid sitemap, structured data and crawlable pages do not guarantee indexing or rankings. No Search Console or Bing account has been registered or verified, no indexing submission has been made, and no directories or third parties have been contacted. These are website-side improvements only.

The application remains a preview with the existing privacy and capability boundaries. Guide copy must not imply OCR, Office conversion, original-text editing, secure redaction, guaranteed compression or certificate-backed signing. Hosting and CDN requests still carry ordinary network metadata.

## Verification

From the repository root, using the existing task-local browser Python environment:

```sh
npm test
npm run build
npm run web:build
npx --yes lakebed@0.0.40 dev web --host 127.0.0.1 --port 3150
LEAFSMITH_URL=http://127.0.0.1:3150 PYTHON web/tests/discovery_http.py
PYTHON web/tests/seo_browser.py http://127.0.0.1:3150 all
PYTHON web/tests/e2e.py http://127.0.0.1:3150
PYTHON web/tests/review_regressions.py http://127.0.0.1:3150
```

Replace `PYTHON` with the existing test venv's interpreter; do not install browser dependencies globally. `npm run web:publish` runs all of the above on a fresh dev server, deploys `web/` to the same Lakebed deploy, waits until the public hostname serves the new client bundle and repeats the browser suites there (`--dry-run` stops before deploying; `--allow-uncommitted` deploys working-tree changes; `--verify-downloads` also downloads both desktop packages). It never creates a desktop release. Repeat HTTP/browser acceptance against the exact public hostname after an authorized deployment. The HTTP suite checks the crawler files and that every discovery URL opens the app for new and returning visitors. The discovery browser suite checks metadata, actual guide-to-tool navigation, invalid tool fallback, responsive widths and uncaught exceptions. Existing browser suites independently inspect real PDF/image downloads and privacy behavior.
