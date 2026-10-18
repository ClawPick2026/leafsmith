# QR code formats plan (work item QR1)

Status: planning document, written 2026-10-19. Nothing here is implemented yet.
Update the **State** line when you start or finish a step. Line numbers drift;
function and file names should not.

State: not started.

## Goal

Make the QR code generator useful without asking people to know QR syntax, and
keep everything on the device. The user chose this on 2026-10-18 over placing
QR codes on PDFs or reading QR codes, because it needs no new runtime library
and never touches a document.

In scope:

1. Remove the prefilled `https://lakebed.dev` / `https://example.com` value.
2. Ready-made content types: Link, Text, Wi-Fi network, Contact, Email, Phone
   call, Text message.
3. An "Encoded content" panel showing exactly what a scanner will read, with the
   Wi-Fi password masked by default.
4. Optional removal of tracking parameters from links, on by default.
5. Error-correction level choice (already planned in
   `docs/feature-improvement-plan.md` § P2).
6. PNG download in addition to SVG (also § P2).
7. A live preview of the code while typing.

Out of scope for QR1 (see [Later](#later)): colours, calendar events, map
locations, bank-transfer (EPC) codes, placing codes on PDFs or images, reading
QR codes, logos, batch generation, and dynamic/trackable codes or URL
shorteners (never).

## Privacy rules for this feature

These come on top of the repository rules in `AGENTS.md` and `web/AGENTS.md`.

- **No new network traffic.** Payloads are built by pure TypeScript in
  `web/shared/`. The website keeps loading only the version-pinned
  `qrcode-generator@1.4.4` from jsDelivr, which it already does. The desktop
  app keeps using the bundled `qrcode-generator@2.0.4`. No link is fetched,
  resolved, unshortened or checked online.
- **No storage.** QR fields are React state only. Nothing goes to
  `localStorage`, `sessionStorage`, IndexedDB, the URL, `document.title`,
  history or the console. (Today only the theme choice is stored, in
  `web/client/theme.ts`.)
- **No secrets in messages or file names.** Validation errors never repeat
  field values. A test asserts that a rejected Wi-Fi password does not appear
  in the error. Download names are fixed (`qr-code.svg`, `qr-code.png`) and
  never derived from the network name, contact name or link.
- **Masking.** The Wi-Fi password field is `type="password"` by default, and
  the Encoded content panel shows `P:••••••••` (always eight dots, so the
  length isn't revealed) until **Show password** is checked.
- **Browser features that send text off the device.** Some browsers offer
  cloud spell checking (Chrome Enhanced Spell Check, Microsoft Editor in Edge).
  Set `spellcheck={false}` on the link, network name, password, email, phone and
  website fields. Free-text fields (Text, Subject, Message) keep the browser
  default. Set `autocomplete="off"` on the password field. Browsers may ignore
  it, so don't claim it prevents password-manager prompts.
- **Clear.** A **Clear fields** button resets every QR field, including the
  password. The existing **Clear workspace** button only exists when files are
  loaded, so it isn't enough on its own.
- **Honest copy.** A fixed note under the panel: "Anyone who scans this code
  can read the encoded content, including a Wi-Fi password." Phone
  compatibility is claimed only for combinations recorded in the manual scan
  matrix (step 9).

## Today

- `web/client/engine-core.ts` → `qrSvg(text)`. It validates a non-empty payload
  of at most 1000 UTF-8 bytes before loading the library, forces UTF-8 byte
  mode, uses fixed level `'M'` and returns `createSvgTag({cellSize: 4, margin:
  16, scalable: true})`.
- `web/client/engine.ts` and `src/engine.ts` destructure the engine's exports in
  explicit lists. A new engine function must be added to **both** lists.
- `web/client/workspace.tsx`
  - `WorkspacePlatform.initialQrText` seeds the `qrText` state.
  - `execute()` pushes `output('qr-code.svg', …, 'image/svg+xml')`.
  - The form is one `<textarea>` labelled "Link or text".
  - The right-hand aside shows a placeholder for the QR tool.
  - `canRun` is always true for the QR tool, so invalid input surfaces as an
    alert on run.
- `web/client/preview.tsx` sets the alt text "Generated QR code" only when
  `result.name === 'qr-code.svg'`.
- `web/client/index.tsx` (`https://lakebed.dev`) and `src/App.tsx`
  (`https://example.com`) set `initialQrText`.
- `web/shared/catalog.ts`, tool `qr`: description "Generate a QR code from a link
  or text." and note "Generates an SVG locally. No tracking or URL shortening.
  Limit 1000 UTF-8 bytes."
- `web/README.md` (tool list and limits) and `README.md` (feature list) mention
  QR codes.

Both library versions expose `getModuleCount()`, `isDark(row, col)` and
`createSvgTag(opts)`. This was checked on 2026-10-19 in
`node_modules/qrcode-generator/dist/qrcode.js` (2.0.4) and in the jsDelivr copy
of 1.4.4.

### Tests that rely on the prefill

These run the QR tool without typing anything, so they must fill a link first.
This is an intended behaviour change, not a weakened test. Note it in the
evidence log.

- `tests/frontend-sharing.test.ts`: asserts both `initialQrText` values. Change
  it to assert that neither platform has the field.
- `web/tests/review_regressions.py` → `retained`.
- `web/tests/ui_polish.py`: two tests click `tool-qr` then `run-tool` directly.
- `tests/browser_e2e.py` → `retained`.
- `web/tests/e2e.py` → `qr` and `tests/browser_e2e.py` → `qr` fill the label
  "Link or text". Rename it to the new "Link" label.
- `web/tests/catalog.test.ts`: the expected `qr` description.

Unchanged and must stay green: `web/tests/engine.test.ts` (QR output is safe SVG
…), `tests/frontend-sharing.test.ts` (QR stays lazy, restores
`stringToBytes`, rejects invalid payloads before loading) and
`tests/frontend-browser.test.ts` (bundled UTF-8 QR without a CDN).

## Design

### 1. Payload builder: `web/shared/qr-payload.ts` (new, pure TypeScript)

```ts
export type QrContent =
  | { kind: 'link'; url: string; stripTracking: boolean }
  | { kind: 'text'; text: string }
  | { kind: 'wifi'; ssid: string; security: 'WPA' | 'WEP' | 'nopass'; password: string; hidden: boolean }
  | { kind: 'contact'; firstName: string; lastName: string; organization: string; title: string; phone: string; email: string; website: string }
  | { kind: 'email'; to: string; subject: string; body: string }
  | { kind: 'phone'; number: string }
  | { kind: 'sms'; number: string; message: string };

export type QrBuild =
  | { ok: true; payload: string; display: string; bytes: number; notes: string[] }
  | { ok: false; error: string };

export const QR_MAX_BYTES = 1000;
export function buildQrPayload(content: QrContent): QrBuild;
```

- The function returns a result instead of throwing, because the UI calls it on
  every render.
- `display` equals `payload` except for the masked Wi-Fi password.
- `bytes` is the UTF-8 length of `payload`. Every type fails with "Encoded
  content is N bytes; the limit is 1000." when `bytes > 1000`, which matches the
  engine's own check.
- Leading and trailing whitespace is trimmed from single-line fields. Free text
  (Text, Subject, Message) is kept as typed. Text-type content must contain a
  non-whitespace character.

| Type | Payload | Validation (error text) |
|---|---|---|
| Link | The URL as typed. `https://` is added when no scheme is present (note "Added https://"). Tracking parameters are removed when enabled (see below). | Must parse with `new URL`, protocol `http:` or `https:`, non-empty host ("Enter a web link, such as https://example.com."). No whitespace ("Links can't contain spaces."). Other schemes: "Use the Text type for content that isn't a web link." `http:` adds the note "This link uses http://, which isn't encrypted." |
| Text | As typed. | Non-empty ("Enter text for the QR code."). |
| Wi-Fi | `WIFI:T:WPA;S:<ssid>;P:<password>;;`; `H:true;` before the final `;` when hidden; open networks give `WIFI:T:nopass;S:<ssid>;;`. Escape `\ ; , : "` in SSID and password with a backslash. | SSID 1–32 UTF-8 bytes, counted before escaping ("Network names are 1–32 bytes; this one is N."). WPA: 8–63 printable ASCII characters or exactly 64 hex digits ("WPA passwords are 8–63 characters."). WEP: 5 or 13 ASCII characters, or 10 or 26 hex digits. Never echo the password. |
| Contact | vCard 3.0 (RFC 2426), CRLF line endings: `BEGIN:VCARD`, `VERSION:3.0`, `N:<last>;<first>;;;`, `FN:<first last, or organization>`, then optional `ORG:`, `TITLE:`, `TEL;TYPE=VOICE:`, `EMAIL;TYPE=INTERNET:`, `URL:`, then `END:VCARD`. Omit empty optional lines. Escape `\` `,` `;` and newline (`\n`) in values. No line folding. | A name or an organization ("Enter a name or an organization."). Phone, email and website use the Phone, Email and Link rules (without the https:// prefix or tracking removal). |
| Email | `mailto:<address>` plus `?subject=…&body=…` for non-empty values. Values use `encodeURIComponent`; newlines become CRLF first (`%0D%0A`, RFC 6068). The address is `encodeURIComponent`-encoded on each side of `@`. | One address matching `^[^\s@]+@[^\s@]+\.[^\s@]+$` ("Enter one email address, such as name@example.com."). |
| Phone call | `tel:<number>` (RFC 3966), with spaces, `-`, `.`, `(` and `)` removed. | Optional leading `+`, then 3–15 digits ("Enter a phone number using digits, with an optional leading +."). |
| Text message | `SMSTO:<number>:<message>`, with the number normalized as for Phone. | Phone rule. The message may be empty. |

Tracking-parameter removal works on the raw query string, not
`URLSearchParams`, so other parameters keep their exact bytes:

- Take the part between `?` and `#` and split it on `&`.
- Decode each key (with `+` read as a space; keep the pair if decoding fails).
- Drop the pair when the key matches `/^utm_/i` or is in this exact set:
  `fbclid gclid gclsrc dclid gbraid wbraid msclkid twclid ttclid li_fat_id igshid
  igsh yclid mc_cid mc_eid _hsenc _hsmi mkt_tok`.
- Rejoin, drop an empty `?`, keep the fragment, and add the note "Removed
  tracking parameters: utm_source, fbclid".
- When nothing matches, the payload is the exact string typed (plus the
  `https://` prefix if one was added). Never re-serialize the URL through
  `URL.toString()`: it rewrites hosts, paths and encodings.

Examples to use as tests:

```text
https://shop.example/item?id=7&utm_source=news&fbclid=abc#reviews
→ https://shop.example/item?id=7#reviews

example.com/menu                → https://example.com/menu
SSID Café;Guest, WPA, pa:ss,wo\rd → WIFI:T:WPA;S:Café\;Guest;P:pa\:ss\,wo\\rd;;
Open network "Lobby", hidden    → WIFI:T:nopass;S:Lobby;H:true;;
+1 (555) 123-4567               → tel:+15551234567
SMS to +15551234567 "Late"      → SMSTO:+15551234567:Late
jane@example.com, "Invoice 42", "Hi,\nsee attached"
→ mailto:jane@example.com?subject=Invoice%2042&body=Hi%2C%0D%0Asee%20attached
Jane Doe, Acme, Inc.            → BEGIN:VCARD␍␊VERSION:3.0␍␊N:Doe;Jane;;;␍␊FN:Jane Doe␍␊ORG:Acme\, Inc.␍␊END:VCARD
```

### 2. Engine: `web/client/engine-core.ts`

```ts
type QrLevel = 'L' | 'M' | 'Q' | 'H';
qrSvg(text: string, options?: { level?: QrLevel }): Promise<string>;           // default 'M'
qrPng(text: string, options: { level?: QrLevel; size: 512 | 1024 | 2048 }): Promise<{ bytes: Uint8Array; width: number; height: number }>;
```

- Validate the level and size before loading the library, like the existing
  payload checks. The error is "Choose error correction L, M, Q or H."
- Share the existing UTF-8 / `stringToBytes` save-and-restore code between both
  functions instead of copying it.
- **PNG layout.** With `n = getModuleCount()`:
  - `scale = floor(size / (n + 8))`. Fail with "Choose a larger PNG size for
    this much content." if it is below 1.
  - `offset = floor((size - scale * n) / 2)`.
  - Fill the canvas white, then draw one black `fillRect` per dark module, and
    export with `toBlob('image/png')`.
  - The output is exactly `size × size`, modules are whole pixels and the quiet
    zone is at least 4 modules.
  - Use `document.createElement('canvas')`, as `processImage` does. Release the
    canvas (`width = height = 0`) afterwards.
- Add `qrPng` to the export lists in `web/client/engine.ts` and `src/engine.ts`.

### 3. UI: `web/client/workspace.tsx` (shared by the website and desktop)

Left column, in this order:

1. **Content type** `<select>`: Link · Text · Wi-Fi network · Contact · Email ·
   Phone call · Text message. Default Link.
2. Fields for the selected type:

   | Type | Fields |
   |---|---|
   | Link | **Link** (placeholder `https://example.com`), **Remove tracking parameters (utm_*, fbclid, gclid and similar)** checkbox, checked by default |
   | Text | **Text** textarea |
   | Wi-Fi network | **Network name (SSID)**, **Security** (WPA/WPA2/WPA3 · WEP · None (open network)), **Password** (hidden for None), **Show password**, **Hidden network** |
   | Contact | **First name**, **Last name**, **Organization**, **Job title**, **Phone**, **Email**, **Website** |
   | Email | **To**, **Subject**, **Message** |
   | Phone call | **Phone number** |
   | Text message | **Phone number**, **Message** |

3. **Error correction**: Low (7%) · Medium (15%), the default · Quartile (25%) ·
   High (30%). Hint: "Higher levels still scan when part of the code is damaged
   or covered, and make the code denser."
4. **File format**: SVG (scalable) · PNG. When PNG is chosen, **PNG size** shows
   512 × 512, 1024 × 1024 (default) and 2048 × 2048 px.
5. **Clear fields** (text button) and the existing **Generate QR code** primary
   button.

Right aside (header "QR code"):

- **Live preview.** About 250 ms after typing stops, call
  `engine.qrSvg(payload, {level})` and show the result as an `<img alt="QR code
  preview">` from a data URL. Use the same `alive` guard as the other preview
  effects so stale results never replace newer ones. While the build is
  invalid, show its error text instead (styled as a hint, not an alert).
- **Encoded content.** Monospace and `whitespace-pre-wrap`. It shows `display`
  (or `payload` when Show password is on), a counter "312 of 1000 bytes", any
  `notes`, and the fixed privacy note.
- Above 600 bytes, add: "Long content makes a dense code. Print it larger or
  shorten the content."

State:

- `qrKind`, plus drafts per type (`Record<kind, fields>`), so switching types
  keeps what was typed. Also `qrLevel`, `qrFormat`, `qrSize` and
  `showPassword`.
- Delete `qrText` and `WorkspacePlatform.initialQrText`, and remove it from
  `web/client/index.tsx` and `src/App.tsx`.

`execute()` for `qr`:

- Build the payload. If it is invalid, `throw Error(build.error)`; the existing
  catch shows an alert and keeps earlier results, which the `retained` tests
  check.
- Otherwise push `qr-code.svg` or `qr-code.png`.
- For PNG, set the notice "Exported 1024 × 1024 pixels."

`web/client/preview.tsx`: use the alt text "Generated QR code" for any result
named `qr-code.*`.

All colours use theme tokens (`web/shared/theme.ts`); `web/tests/theme.test.ts`
rejects hex colour classes. The QR image itself stays black on white in both
themes, as it is today, because inverted codes scan poorly.

### 4. Copy

- `web/shared/catalog.ts`, tool `qr`:
  - Description: "Generate a QR code for a link, text, Wi-Fi network, contact,
    email, phone call or text message."
  - Note: "Generates SVG or PNG locally. Static codes only: no tracking,
    redirects or URL shortening. Limit 1000 UTF-8 bytes of encoded content."
- `web/README.md`:
  - Tool list: "**Generate QR codes:** links, text, Wi-Fi networks, contacts,
    email, phone calls and text messages, as SVG or PNG, generated in the
    browser."
  - Limits: keep the 1000-byte line. Add "Wi-Fi codes support WPA/WPA2/WPA3
    Personal, WEP and open networks; enterprise (802.1X) networks are not
    supported."
- `README.md`: "generate QR codes for links, text, Wi-Fi, contacts, email,
  phone calls and text messages."

## Implementation order

Strict TDD: one behavioural test, watch it fail for the expected reason,
implement the minimum, rerun. Record RED/GREEN output in
`web/tests/evidence-qr.log` (shared and website parts) and
`tests/evidence-qr.log` (desktop adapter parts).

0. **Coordinate.**
   - Run `t3_thread_list` (running threads) and `ListAgents`, and message any
     peer working in `web/client/workspace.tsx`, `web/shared/catalog.ts` or the
     tests listed above.
   - Edit only with exact string replacements on freshly read content.
   - List the files you changed in the final report.
1. **Payload builder** (`web/tests/qr-payload.test.ts`, offline). One test at a
   time, in this order:
   1. Text: passthrough and empty rejection.
   2. Link: scheme rules, the `https://` prefix, the whitespace rejection and
      the http note.
   3. Tracking removal: exact preservation of other parameters, fragment kept,
      option off, nothing to remove.
   4. Wi-Fi: format, escaping, hidden, open network.
   5. Wi-Fi validation: SSID bytes, WPA and WEP lengths, and the password never
      appearing in the error.
   6. Wi-Fi masking: `display` versus `payload`.
   7. Contact: CRLF, escaping, organization only, empty lines omitted.
   8. Email: encoding and CRLF in the body.
   9. Phone: normalization and rejection.
   10. Text message.
   11. The 1000-byte limit for every type.
2. **Error-correction level.**
   - `web/tests/engine.test.ts` (real 1.4.4): `H` produces a larger module
     count than `L` for the same 200-byte payload, and an invalid level is
     rejected before the loader runs.
   - The same assertions in the desktop suite with the bundled 2.0.4.
3. **PNG.** Use a fake canvas that records `fillRect` calls, like the PDF.js
   render tests in `web/tests/engine.test.ts`. Check:
   - the exact output size;
   - the white background is drawn first;
   - the top-left finder module is at `(offset, offset)`;
   - the quiet zone is at least 4 × scale;
   - the "larger PNG size" error;
   - the canvas is released.

   Add `qrPng` to both export lists, with the desktop test proving it works
   without a CDN (`tests/frontend-browser.test.ts`).
4. **Cross-version check** (`tests/frontend-qr.test.ts`). For fixed payloads at
   every level, the module matrices from bundled 2.0.4 and downloaded 1.4.4 are
   identical. This keeps the "one implementation" rule honest across the two
   library versions.
5. **Remove the prefill.**
   - Change the `tests/frontend-sharing.test.ts` assertion first (RED), then
     remove the field.
   - Update the prefill-dependent browser tests listed above in the same step.
6. **Catalog copy.** Change the `web/tests/catalog.test.ts` expectation first,
   then `web/shared/catalog.ts`.
7. **UI.** Browser tests drive this. Install `zxing-cpp` 3.1.1 (Apache-2.0)
   into `.test-venv` only, as a test-only decoder. A manylinux aarch64 wheel
   exists; checked with `pip install --dry-run` on 2026-10-19. Mention it in
   `web/README.md` under verification. Add to `web/tests/e2e.py`, one case at a
   time:
   1. Wi-Fi with escaped characters: Encoded content shows `P:••••••••`;
      after Show password it shows the real value; download PNG; decode it
      with zxing-cpp; the text equals the expected payload.
   2. Link with tracking parameters: the note lists the removed names and the
      decoded PNG has them removed.
   3. Contact: decode the live preview (element screenshot) and compare it
      with the vCard text.
   4. SVG download still parses as XML. The result preview has the alt text
      "Generated QR code".
   5. Invalid input: an alert appears, earlier results are kept, and the error
      text does not contain the typed password.
   6. Clear fields empties every field, including the password.
   7. Privacy:
      - Record every request while filling and generating, and assert that no
        URL or body contains the payload or password.
      - Assert that `localStorage` and `sessionStorage` contain neither.
      - Assert that `document.title` and `location.href` don't change.

   Then add one Wi-Fi PNG round trip to `tests/browser_e2e.py` (desktop
   preview, bundled library, no CDN requests).
8. **Docs.** Update `web/README.md` and `README.md` as in § 4. Set the QR bullet
   in `docs/feature-improvement-plan.md` § P2 to done for PNG and the level.
9. **Manual scan matrix.** The development host can't do this; ask the user.
   - Scan each type with the iPhone Camera app and the Android camera or
     Google Lens, on screen and printed about 3 cm wide.
   - Include: Wi-Fi WPA, Wi-Fi open, Wi-Fi hidden, Wi-Fi with escaped
     characters, and Wi-Fi with a hex-looking network name such as `CAFE`.
   - Record the device, OS version and result in
     `web/tests/evidence-qr-phones.log`.
   - Copy that claims compatibility may only state what this log shows.

## Done when

- `npm test`, `npm run build` and `npm run web:build` pass.
- `web/tests/e2e.py`, `review_regressions.py`, `ui_polish.py` and
  `theme_browser.py` pass against freshly built and served website output, in
  light and dark mode.
- `tests/browser_e2e.py` passes against a fresh desktop preview build.
- RED/GREEN evidence is in the two `evidence-qr.log` files.
- The phone matrix is recorded, and every risk below is either resolved or
  stated as a limitation in the catalog note and README.
- `web/client/workspace.tsx` contains no QR-specific hex colours, and all
  enabled buttons have the pointer cursor (`ui_polish.py`).
- Nothing is committed, pushed or deployed unless the user asks. Deploying the
  website is `npm run web:publish` (coordinator only).

## Risks and unknowns

1. **Hex-looking Wi-Fi names and passwords.** ZXing's de facto format suggests
   double quotes around ASCII values that could be read as hex, but phone
   parsers differ. QR1 does not quote. If the `CAFE` row in the matrix fails,
   add quoting for that case.
2. **WPA3-only (SAE) networks.** `T:WPA` is expected to cover
   WPA/WPA2/WPA3-Personal on current phones, but WPA3-only networks are
   untested. Don't claim them until the matrix shows it. Enterprise (802.1X)
   is unsupported and stated.
3. **`SMSTO:` on iOS.** It is widely used, but must be confirmed in the matrix.
   If iOS ignores it, switch to `sms:<number>?body=<encoded>` and retest
   Android.
4. **vCard line folding.** RFC 2426 asks for folding at 75 octets; QR1 doesn't
   fold, to keep codes small. Long organization names or URLs are part of the
   matrix.
5. **Dense codes.** 1000 bytes at level H needs about 141 × 141 modules, which
   is hard to scan when printed small. The UI states this above 600 bytes
   rather than blocking it.
6. **Live preview on the website** loads the QR library when the tool first
   has valid content, instead of on the first Generate click. It is the same
   pinned request with no payload, and is already covered by the website's
   privacy text about jsDelivr.

## Ownership if delegated

- **Shared (coordinator or a single shared-UI owner):**
  - `web/shared/qr-payload.ts`, `web/shared/catalog.ts`
  - `web/client/engine-core.ts`, `web/client/engine.ts`,
    `web/client/workspace.tsx`, `web/client/preview.tsx`,
    `web/client/index.tsx`
  - `web/tests/*`, `web/README.md`, `README.md`
- **Frontend worker:** `src/engine.ts`, `src/App.tsx`, `tests/*.test.ts`,
  `tests/browser_e2e.py`.
- No Rust, worker, IPC, component or packaging changes are needed.

## Later

- **QR2 Colours.** Foreground and background pickers with a contrast check
  that rejects low-contrast and light-on-dark combinations.
- **QR3 More types.**
  - Calendar event (iCalendar `VEVENT`).
  - Map location (`geo:lat,lon`).
  - EPC/SEPA bank transfer (EPC069-12: level M required, at most 331 bytes,
    IBAN mod-97 check).
- **QR4 Place a QR code on a PDF page or image.** Reuse the Annotate/Sign
  placement box (`RegionSelector`). Draw modules as vector rectangles with
  pdf-lib so print stays sharp.
- **QR5 Read QR codes from an image or PDF page.** This needs a new pinned
  library (jsQR or ZXing-js, Apache-2.0) and a third-party notice. Show
  results as text only, never opened automatically.
