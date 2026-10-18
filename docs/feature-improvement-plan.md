# Feature improvement plan

Status: planning document, written 2026-10-18 against `main` at `37d7c62` (v0.1.0-rc.2).
Nothing in this file is implemented yet unless a work item says so. Update the
"State" line of a work item when you start or finish it.

This plan turns every **Limited**, **Requires engine** and **Requires model/provider**
row of the PDF Guru comparison into concrete work items, and lists smaller
improvements for rows that are already **Yes**. Each work item is self-contained:
read its section, the files it names, and the ground rules below, then work it
with the repository's normal TDD process.

## How to use this plan

1. Pick a work item whose dependencies are done (see [Order of work](#order-of-work)).
2. Re-read the files listed under **Today**; line numbers drift, function names
   should not.
3. If the item changes an operation, option, IPC method, component id or worker
   contract, it needs the coordinator. Follow the
   [contract change checklist](#x3-contract-change-checklist).
4. Work strictly RED → GREEN, one behavioural test at a time, and retain the
   evidence (`worker/pdf-evidence.log`, `worker/media-evidence.log`,
   `web/tests/evidence-*.log`).
5. Finish with the item's **Done when** list, including the user-facing limitation
   text. A row in the comparison table only moves to **Yes** when the packaged app
   has been checked on Windows and Linux, not just the unit suite.

## Ground rules that constrain every item

These come from `AGENTS.md`, `worker/PDF-OPTIONS.md`, `worker/MEDIA-OPTIONS.md` and
`components/README.md`. They are repeated here because most of the "obvious"
upgrade paths break one of them.

- **Licences.** No AGPL and no GPL-only runtime components, no unredistributable
  FFmpeg. This rules out PyMuPDF/MuPDF, Ghostscript, `pdf2docx` (built on PyMuPDF),
  Marker and Surya (GPL code, restricted weights), x264/x265, fdk-aac. Every model
  licence must be read at the pinned revision; model families mix licences by size
  (for example Qwen2.5-1.5B is Apache-2.0 while Qwen2.5-3B is not).
- **Ownership.** Frontend worker: `src/**` and frontend tests. PDF worker:
  `worker/pdf_ops.py`, `worker/tests/test_pdf_ops.py`, `worker/test-requirements.txt`.
  Media/AI worker: `worker/media_ops.py`, `worker/tests/test_media_ops.py`,
  `worker/media-requirements.txt`. Coordinator: Rust, packaging, manifests,
  `components/registry.json`, `worker/main.py`, `worker/runtime-requirements.txt`,
  shared contracts. Work items that cross these lines are split into per-owner
  tasks below.
- **One implementation.** Shared UI and algorithms live in `web/client/` and
  `web/shared/`; `web/shared/` stays pure TypeScript. Only `src/` may import
  bundled npm packages and Tauri. Anything added to the built-in workspace also
  ships on the website, so it must stay local-only there (no uploads, no native
  imports) and load libraries through the injected loaders in `web/client/engine.ts`.
- **Consent and privacy.** Local by default. Cloud processing, timestamp servers,
  OCSP/CRL fetches and component downloads each need explicit, per-operation consent.
  Passwords, private-key passphrases and API keys are entered per job and never
  stored or logged (`media_ops._cloud_config` is the pattern to copy).
- **Honest output.** Never fabricate results, never mark a missing component as
  installed, and state every remaining limitation in `details.limitations`, the
  native catalog note (`src/native-catalog.ts`) and the README.
- **Fixed operation names.** The eleven native PDF operations and five media/AI
  operations keep their names. New capability is either a new option on an existing
  operation or a new, additional operation string.
- **Two library versions.** The website loads pdf-lib 1.17.1, PDF.js 3.11.174 and
  qrcode-generator 1.4.4 from jsDelivr; the desktop bundles pdf-lib 1.17.1,
  PDF.js 6.4.299 and qrcode-generator 2.0.4. Any shared feature that relies on a
  PDF.js or QR API must be tested against both.

## Summary

| Feature | Today | Main cause of the limitation | Target | Work items |
|---|---|---|---|---|
| Edit existing PDF text | Limited | Latin-1 check in `pdf_ops._edit`; only standard-14 fonts; replacement object is appended (drawing order lost); UI always substitutes Helvetica; one object at a time | Unicode replacement with embedded fonts, original font reused where possible, line-level editing; paragraph reflow later | Q1, Q3, T1, T2, T3 |
| PDF → Word/Excel/PowerPoint | Limited | `pdf_ops._export` writes plain lines from `pdfplumber`; no styles, images, columns or paragraph merging; table text duplicated in DOCX | Layout model with reading order, paragraphs, styled runs, images and de-duplicated tables, measured against a fidelity corpus | C1 |
| Word/Excel/PowerPoint → PDF | Requires engine | No LibreOffice pack in `components/registry.json`; recipe is a pre-release candidate | Installable, verified LibreOffice pack | E3 |
| OCR / image to text | Requires engine | No Tesseract pack published; English + OSD only; output replaces pages with rasters | Installable pack, per-language data, overlay mode that keeps original pages, layout-aware DOCX | E2, O1, O2 |
| Remove watermarks | Limited | `pdf_ops._remove_watermark` matches exact top-level text only; UI exposes neither annotation subtypes nor all pages | Candidate detection (repeated text, watermark artifacts, repeated images, nested forms) with user review | Q2, W1 |
| AI summaries | Requires model/provider | Local text model pack failed its quality gate; the UI's summary language field is ignored by `_summary`; no page references | Published local model pack, working language option, page-cited summaries, OCR chaining for scans | E4, Q8, A1 |
| Translate PDFs | Requires model/provider | `media_ops._translation` re-typesets extracted text into a new document; Rust never supplies `engines.pdf_font`, so the Bitstream Vera fallback makes every non-Latin target language fail | Fonts for non-Latin targets, then a layout-preserving mode on top of T1/C1; optional dedicated offline MT engine | E4, Q8, L1, L2 |
| Audio/video transcription | Requires engines/model | FFmpeg pack unpublished but always required; only `tiny.en` model published | FFmpeg-free audio path, published FFmpeg pack, multilingual models | E1, E5, Q5 |
| Compress PDFs | Yes, with caveats | Only two extremes: stream recompression or full rasterisation | Image-only recompression mode that keeps text, forms and links; never return a larger file | Q4 |
| Video compression | Conditional | FFmpeg pack unpublished; VP9/WebM only | Published pack; trim, audio extraction, target-size mode | E1, V1 |
| Image enhancement | Yes (basic) | Pillow brightness/contrast/sharpness only | Auto-level, denoise, document clean-up presets; optional ML upscaling evaluated later | Q6, I1 |
| Draw electronic signatures | Yes (no certificates) | Signature is an image overlay | Optional certificate-backed PAdES signing and signature verification | S1, S2 |
| Fill PDF forms | Yes | Three hard-coded templates in `pdf_ops`; no way to add fields to an existing PDF; radio groups and signature fields reported as unsupported; field appearances are WinAnsi-only | Field designer for any PDF, radio-group filling, Unicode values | F1, T4 |
| Add text, images, shapes, highlights (built-in) | Yes (flattened) | `overlayPdf` in `web/client/engine-core.ts` draws highlights as 30 % opacity rectangles; text is standard-font WinAnsi only; position is typed in points, one overlay per run, checked against the MediaBox | Real `/Highlight` annotations, Unicode text, drag-to-place on the rendered page | Q3, Q7, T4 |
| Comments and annotations (native) | Yes | Rectangle typed as PDF coordinates | Visual placement; more annotation types | Q3, P1 |
| Merge, split, rotate, crop, PDF → images, QR | Yes | Pages are copied with `copyPages`, which can drop forms and bookmarks; browser page export is PNG-only up to 144 DPI; QR is SVG-only with fixed error correction | Small fixes listed in P2 | P2 |

## Order of work

```
Phase 0  Unblock engines      E0 component manager  E1 FFmpeg  E2 Tesseract  E3 LibreOffice  E4 text model  E5 Whisper models
Phase 1  Quick wins           Q1 Q2 Q3 Q4 Q5 Q6 Q7 Q8   (independent of each other)
Phase 2  Core quality         T1 → T2   T4   C1   O1 → O2 (needs C1 writers)   W1   A1   F1   S1   V1   P1   P2
Phase 3  Large features       T3 (needs T1, T2)   L1 (needs T1, C1)   L2   S2 (needs S1)   I1
Always   Cross-cutting        X1 progress/cancel  X2 fidelity corpus  X3 contract checklist  X4 native acceptance  X5 multi-input jobs
```

Phase 0 changes the most rows of the table for the least code: four of the
"Requires" rows are blocked on publishing packs whose build recipes already exist.
Phase 1 items are each a few days of work and need no new dependencies.

---

## Phase 0 — make the required engines installable

All Phase 0 items are coordinator-owned and follow the promotion steps in
`components/README.md` ("Promote only after security, native and publication
verification") and `components/AI.md`. Today `components/registry.json` lists only
`whisper` and `whisper_model`; every other engine works only if the user already has
it on `PATH` (`components.rs: system_tool`).

### E0. Component manager prerequisites

- **Why first:** E1–E5 multiply the number of installable packs, and the manager has
  gaps that become user-visible once there is more than one version of anything.
- **Today (`src-tauri/src/components.rs`):** install verifies exact size and SHA-256
  from the compiled-in registry, which is sound. But there is no uninstall or update,
  old `{id}-{version}-{uuid}` directories are never removed, `ComponentStatus.error` is
  always `None`, a version is shown only for registry installs (not `PATH` tools), and
  installed executables are not re-checked before use. `Cargo.lock` is not committed.
- **Steps:** add update (install new version, switch the index atomically, delete the
  old directory) and uninstall; report real errors (corrupt index, missing executable)
  in `error`; label `PATH` tools as "system installation, version unknown" rather than
  leaving the version blank; commit `Cargo.lock`. Uninstall/update are new IPC methods,
  so they need approval (see Open decisions).
- **Done when:** a user can update and remove a pack from the component panel, and a
  deleted executable shows as an error instead of as installed.

### E1. Publish the FFmpeg pack

- **Unblocks:** video compression, all transcription (until Q5 lands), V1.
- **Today:** LGPL-only recipe for FFmpeg 7.1.5 + libvpx + Opus in
  `scripts/build_component.py`; manual `components.yml` workflow; smoke encodes and
  decodes VP9/Opus.
- **Steps:** run `components.yml` for `ffmpeg` on both platforms → review build
  config (no `--enable-gpl`, no nonfree, no autodetect) and notices → publish engine
  ZIP and sources ZIP to an immutable release → independent download and hash check
  → add registry entries → rebuild the app → native consent/install/run test.
- **Done when:** the component panel shows FFmpeg with version, size and licence;
  `compress_video` and `transcribe` succeed in the packaged app on both platforms
  using the installed pack, not a `PATH` binary.

### E2. Publish the Tesseract pack, then language data packs

- **Today:** Tesseract 5.5.3 recipe with English + OSD from the pinned
  `tessdata_fast` commit. The native catalog asks for a free-text language code but
  only `eng` can be present.
- **Steps:** publish the engine pack as in E1. Then add per-language data packs
  (Apache-2.0, `tessdata_fast`, same pinned commit). Decide the registry shape first
  (see [Open decisions](#open-decisions)): one component per language, or one
  "OCR languages" component with selectable members. Extend `component_status` so
  the UI can list installed languages and the OCR language field becomes a
  multi-select of installed languages rather than free text.
- **Done when:** a user can install German data, select `eng+deu` from a list, and
  OCR succeeds; an uninstalled language is never offered as available.

### E3. Publish the LibreOffice pack

- **Today:** 26.2.7.1 recipe explicitly marked a pre-release candidate; Windows MSI
  Authenticode check and Linux ELF closure still need a native run.
- **Steps:** wait for (or switch the pin to) a stable LibreOffice line that contains
  the security fixes listed in `components/README.md`; run native CI; review the
  roughly 500 MB pack size against the 750 MiB download cap; publish with the
  matching sources ZIP.
- **Done when:** DOCX, XLSX and PPTX samples with tables, images and non-Latin text
  convert in the packaged app on both platforms, and the release notes state the
  LibreOffice version.

### E4. Publish a local text model that passes the quality gate

- **Today:** 0.5B model failed the translation factuality gate (`components/AI.md`,
  "Text candidate decision"). Qwen2.5-1.5B-Instruct Q2_K is pinned but untested.
  Q4_K_M of the same model exceeds the 750 MiB raw download cap.
- **Steps:** run the unchanged native gate on the Q2_K candidate. If it fails, try
  candidates in this order, each only after reading the licence at the pinned
  revision: a larger quantisation of the same model (requires raising the cap for
  model components, see Open decisions), another permissively licensed small
  instruct model. Never weaken the gate fixture.
- **Done when:** `llama` and `llama_model` appear in the registry and both
  `summarize` and `translate_pdf` pass the native gate with the published files.

### E5. Multilingual Whisper models

- **Today:** only `ggml-tiny.en.bin` (English-only) is published; the UI exposes a
  `language` field that has no effect with that model.
- **Steps:** add multilingual whisper.cpp models (MIT) as additional consented
  downloads, starting with `base` (about 150 MB) and `small` (about 490 MB); a
  quantised `large-v3-turbo` fits under the cap and is worth evaluating. Requires
  the registry to support several models for one component (Open decisions). Add a
  native transcription smoke per model with a non-English fixture. Disable or hide
  the language field when the selected model is English-only.
- **Done when:** a German recording transcribes with a multilingual model in the
  packaged app; the UI never implies language support the installed model lacks.

---

## Phase 1 — quick wins

### Q1. Edit-text UI: keep the original font by default

- **State:** font and size part done 2026-10-18 ("Keep original font" default, all nine
  fonts, blank size keeps the original). Not done: prefilling the inspected size.
- **Owner:** frontend.
- **Today:** `src/native-catalog.ts` gives `edit_pdf_text` a `font` select with only
  `Helvetica`, `Times-Roman`, `Courier`, defaulting to `Helvetica`, and
  `NativeTools.tsx: initial()` sends it. So every UI edit replaces the original font
  object, even though `pdf_ops._edit` keeps the original font when `font` is omitted.
  The worker also accepts six bold/oblique variants the UI does not offer.
- **Change:** add a first choice "Keep original font" that omits `font`; list all
  nine supported standard fonts; default `font_size` to the inspected size rather
  than 14.
- **Tests:** frontend test that the default request has no `font` key and uses the
  inspected size; test that choosing a bold font sends the exact worker name.
- **Done when:** editing a word in a PDF with an embedded font keeps that font when
  the glyphs exist (the worker already reports when they do not).

### Q2. Expose existing worker options in the native UI

- **State:** watermark part done 2026-10-18 (blank page means all pages, annotation
  type select). OCR, export, image and video options still hidden.
- **Owner:** frontend.
- **Today:** the worker supports options the UI hides:
  `remove_watermark.annotation_subtype` and all-pages mode (the UI always sends
  `page`), `ocr_*.dpi`, `convert_from_pdf.dpi`/`quality`, `enhance_image` format,
  quality and size bounds, `compress_video.max_duration`.
- **Change:** add these fields with the documented ranges, and an "All pages" choice
  that omits `page`. Use a select for annotation subtype.
- **Done when:** every option in `PDF-OPTIONS.md` and `MEDIA-OPTIONS.md` that a user
  could reasonably need is reachable from the UI, and frontend tests assert the
  exact option payloads.

### Q3. Drag-to-place on the rendered page (built-in and native)

- **Owner:** frontend (shared coordinate maths in `web/shared/`).
- **Today:** the built-in Annotate and Sign tools take X/Y/width/height in points
  (`workspace.tsx: positionInputs`), add one overlay per run, and check bounds against
  the MediaBox, ignoring CropBox and `/Rotate`. Native `annotate_pdf` takes a typed
  rectangle, and `edit_pdf_text` objects are picked from a text list although
  `inspect_pdf` returns `bounds` per object. Uncommitted work at the time of writing
  already adds the pieces: `RegionSelector` in `web/client/preview.tsx` and
  `selectionToPdfRect` / `pdfRectToSelection` / `viewMarginsToPdf` in
  `web/shared/crop.ts`, so far used only by tests.
- **Change:** land the crop/preview work first, then wire `RegionSelector` into
  Annotate, Sign and Crop in the built-in workspace, and into native `annotate_pdf`
  and `edit_pdf_text` (render with the bundled PDF.js, overlay inspected object bounds
  as clickable boxes). Allow several overlays before export instead of one per run.
  Extend the `crop.ts` tests to 0/90/180/270° rotation with offset CropBoxes.
- **Done when:** a user can click a word to edit it and drag to place a comment or
  signature on a rotated, cropped page, and the result lands where it was drawn
  (verified by reading `/Rect` or the drawn image position back in a test).

### Q4. Image-only PDF compression and a no-larger guarantee

- **Owner:** PDF worker; frontend for the new choice.
- **Today:** `compress_pdf` is either lossless stream compression (may grow) or full
  rasterisation (flattens everything).
- **Change:** add `mode=images`: iterate `page.images` with pypdf and recompress or
  downsample embedded raster images above a target DPI (`ImageFile.replace`, already
  present in the pinned pypdf), keeping text, vectors, forms, links and annotations.
  Skip images where recompression does not help, images with soft masks the encoder
  cannot carry, and JBIG2/CCITT bilevel images. For every mode, if the output is not
  smaller than the input, say so in `details` and let the UI offer to keep the
  original instead of presenting a larger "compressed" file.
- **Tests:** fixture with a large embedded photo plus text, a form field and a link;
  assert smaller output, text still extractable, field and `/Link` still present,
  image pixel dimensions reduced to the requested DPI.
- **Done when:** the README caveat changes from "raster compression flattens…" to a
  three-way choice with each mode's effects stated.

### Q5. Transcribe audio files without FFmpeg

- **Owner:** media worker; coordinator for engine requirements in the catalog.
- **Today:** `media_ops._transcribe` always converts with FFmpeg first, so local
  transcription is impossible until E1 ships, even for WAV files. The whisper pack is
  built with its examples and vendored `miniaudio`/`stb_vorbis`, which upstream uses
  to decode WAV, MP3, FLAC and OGG without FFmpeg.
- **Change:** for local `whisper.cpp` jobs on those audio types, pass the file to
  `whisper-cli` directly, with whisper's own duration limit option in place of
  FFmpeg's `-t`. Keep FFmpeg for video, other containers and cloud uploads. Confirm
  the exact supported formats and flags against the pinned whisper.cpp source before
  coding, and add a native smoke with an MP3 fixture.
- **Done when:** with only `whisper` and `whisper_model` installed, an MP3 transcribes
  in the packaged app; video input still asks for FFmpeg with an actionable message.

### Q6. Image enhancement presets

- **Owner:** media worker; frontend for fields.
- **Today:** `media_ops._image` applies three Pillow multipliers.
- **Change:** add optional, still non-generative steps with Pillow only:
  `auto_contrast` (`ImageOps.autocontrast` with cutoff), `denoise` (median filter
  size), `grayscale`, and a `document` preset (grayscale, auto-contrast, unsharp
  mask, optional threshold) for photographed pages. Deskew can follow once OSD is
  available from E2.
- **Done when:** each option has a pixel-level test, and the UI note still says it
  cannot recover detail absent from the source.

### Q7. Real highlight annotations in the built-in workspace

- **Owner:** frontend (shared engine in `web/client/engine-core.ts`).
- **Today:** `overlayPdf` draws `highlight` overlays with
  `page.drawRectangle({ …, opacity: 0.3 })`, which flattens them into page content.
- **Change:** create a `/Highlight` annotation with `/QuadPoints`, colour, `/CA`
  and an appearance stream through pdf-lib's low-level object API (pdf-lib 1.17.1
  has no high-level annotation helper). Keep a "flatten" option for users who want
  the old behaviour. This ships on the website too; it needs no new library.
- **Tests:** in `web/tests/engine.test.ts`, re-open the output and assert one
  `/Annots` entry with `/Subtype /Highlight` and correct QuadPoints, and that page
  content streams are unchanged.
- **Done when:** the "flattened highlights" wording can be removed from the README
  and the comparison table.

### Q8. Fix the AI language options and non-Latin translation fonts

- **State:** done 2026-10-18 with the user-selected font option ("Select font file",
  `font_file_id` → `engines.pdf_font`). The Rust change still needs `cargo test` in CI;
  the development host has no Rust toolchain. Bundled fonts remain an open decision.
- **Owner:** media worker (summary language), coordinator (font supply), frontend.
- **Today:** two defects. (1) The summarize form shows "Target / summary language",
  but `media_ops._summary` never reads `language`, so the setting does nothing.
  (2) `translate_pdf` needs `engines.pdf_font` for scripts outside Bitstream Vera's
  Latin coverage, but `main.rs` passes only `components::engine_paths` and the model,
  so translating into Russian, Greek, Chinese and similar languages always fails with
  a missing-glyph error.
- **Change:** honour `language` in `_summary` (prompt instruction plus a test that it
  reaches the model request), or remove the field from the summarize form. For fonts,
  supply `pdf_font` from the same source T1 uses: a user-selected font file granted
  through `select_inputs`, or a bundled/optional OFL font set (Open decisions). The UI
  should say which scripts the selected font covers before the job runs.
- **Done when:** a summary requested in German comes back in German, and a Russian
  translation produces a PDF with embedded Cyrillic glyphs in the packaged app.

---

## Phase 2 — core quality

### T1. Unicode replacement text with embedded fonts

- **Owner:** PDF worker; frontend for font choice; coordinator if fonts are bundled.
- **Today:** `pdf_ops._edit` rejects any character above U+00FF, substitutes only
  standard-14 fonts, and inserts the replacement with `FPDFPage_InsertObject`, which
  appends it and changes drawing order.
- **Approach (APIs verified present in pypdfium2 5.14.0 / PDFium 156):**
  1. Try the original font first. Read it with `FPDFTextObj_GetFont` and
     `FPDFFont_GetFontData`; if it is embedded and its cmap covers every new
     character, keep the object and call `FPDFText_SetText` (subset fonts usually
     fail this check, which is why step 2 exists).
  2. Otherwise build a replacement font: subset a TrueType-outline font to the needed
     glyphs (fontTools, MIT; new dependency for the coordinator to add), load it with
     `FPDFText_LoadFont(..., FPDF_FONT_TRUETYPE, cid=True)` so it is embedded as a CID
     font with Unicode mapping, and create the new text object from it.
  3. Insert the replacement at the original object's index with
     `FPDFPage_InsertObjectAtIndex`, preserving drawing order; keep matrix, colours and
     render mode as today.
  4. Font sources, in order: a user-selected font file (granted through
     `select_inputs`, so it is consented), a bundled OFL font set, then standard-14.
     The choice of bundled fonts is an open decision because CJK coverage is large.
- **Not in scope:** complex-script shaping (Arabic joining, Indic reordering). Shaped
  output needs a shaping engine such as HarfBuzz and is listed under T3; until then the
  worker must reject scripts that need shaping rather than emit unshaped glyphs.
- **Tests:** Cyrillic and Greek replacement in a PDF with a subset Latin font; read
  back with PDFium and pdfplumber; assert the original object is gone, the new one
  sits at the same index, the font is embedded, and extracted text equals the input.
  A test that Arabic input fails with an actionable message.
- **Done when:** the README no longer says "replacement currently limited to Latin-1"
  and instead names the supported scripts.

### T2. Line-level editing

- **Owner:** PDF worker; frontend.
- **Today:** a visual line is often several text objects (one per word, run or kerning
  break), so users must edit object by object.
- **Approach:** in `inspect_pdf`, add `details.pages[].lines[]` grouping top-level text
  objects that share a baseline, direction and font size within tolerance, each with
  `object_indexes`, `bounds` and joined text. Add an `edit_pdf_text` option
  `object_indexes` (list) that replaces all of them with one new object positioned at
  the first object's origin, using T1's font logic. Reject groups that span different
  matrices (rotation/skew) or clip paths.
- **Done when:** a user can select a whole line in the Q3 picker and replace it in one
  job, and the old objects are removed rather than covered.

### T4. Unicode text in the built-in workspace

- **Owner:** frontend; coordinator for the new dependency and font decision.
- **Today:** built-in text overlays and form field appearances use pdf-lib standard
  fonts, so anything outside WinAnsi fails (`overlayPdf`, `fillPdf` in
  `web/client/engine-core.ts`).
- **Approach:** add `@pdf-lib/fontkit` (MIT) through the injected loaders (bundled in
  `src/engine.ts`, CDN-pinned in `web/client/engine.ts`), embed a subset of the chosen
  font with `embedFont(bytes, { subset: true })`, and use it for overlays and for
  `updateFieldAppearances`. Font source follows the same Open decision as T1; on the
  website the font must load from a pinned URL or a user-chosen local file, never by
  uploading the document.
- **Done when:** Cyrillic text can be added and Cyrillic values filled into a form on
  both website and desktop, with the font embedded in the output.

### C1. PDF → Office reconstruction v2

- **Owner:** PDF worker (new internal layout module inside its files); frontend for
  options.
- **Today:** `pdf_ops._export` writes each `extract_text` line as a DOCX paragraph,
  appends detected tables after the text (so table text appears twice), places PPTX
  words as boxes with size guessed from bounding height, and never exports images or
  styles.
- **Approach:** build an intermediate layout model, then write each format from it.
  1. *Extraction:* `pdfplumber` chars with `fontname`, `size` and colour; table
     bounding boxes; image bounding boxes from page objects, with pixels extracted via
     pypdfium2.
  2. *Layout:* remove words inside table bounding boxes before building text;
     group words into lines and lines into paragraphs (indent, leading, font change);
     detect columns and reading order with a recursive XY-cut; mark repeated
     top/bottom lines across pages as header/footer; derive heading levels from
     relative font size.
  3. *Writers:* DOCX paragraphs with styled runs (bold/italic from font flags or
     names, size, colour), headings, tables in reading order, inline images, page
     size and margins; XLSX one sheet per table with numbers and dates typed but
     formula escaping kept (`_spreadsheet_value`); PPTX positioned text boxes with
     runs plus images, and an optional page-image background for vector art,
     explicitly marked as non-editable.
  4. Keep the current simple export as `layout=text` for users who want plain text
     flow.
- **Measure, don't guess:** add a fidelity corpus and metrics (X2): character recall,
  reading-order edit distance, table cell accuracy, image count. Gate changes on the
  metrics not regressing.
- **Considered and rejected:** `pdf2docx` (PyMuPDF/AGPL). LibreOffice's PDF import
  produces positioned Draw frames, not flowing text; evaluate only as an alternative
  "visual" mode once E3 ships. ML layout models (for example Docling) are a possible
  optional component later; they bring a large PyTorch runtime and need a licence
  review of the weights.
- **Done when:** on the corpus, DOCX output has no duplicated table text, keeps
  images, and passes the agreed metric thresholds; the README limitation lists what is
  still approximate (complex tables, floating text boxes, vector graphics).

### O1. OCR that keeps the original pages

- **Owner:** PDF worker; frontend for options.
- **Today:** `pdf_ops._ocr` renders each page to PNG, has Tesseract produce a new PDF
  per page, and concatenates them, so vectors, fonts, forms, links and annotations of
  the original are lost.
- **Approach:**
  1. `output=overlay` (new default for `ocr_pdf`): run Tesseract with
     `-c textonly_pdf=1` to get a text-only page, scale it from render pixels to the
     original page's user space, and merge it into the original page with pypdf
     (`merge_transformed_page`). Annotations and form fields stay because `/Annots`
     and the AcroForm are untouched. Account for rotation and CropBox offset.
  2. `skip_text=true`: skip pages that already have extractable text, so mixed
     documents are not double-layered. Report which pages were skipped.
  3. `auto_rotate=true`: use OSD (already in the pack) to detect page orientation
     before recognition and rotate the render accordingly.
  4. Keep the current raster output as `output=raster` for scans that need cleanup.
- **Done when:** OCR on a PDF with one scanned page and one digital page with a form
  field keeps the field and the digital text unchanged, and makes the scanned page
  searchable at the correct positions (verified by word coordinates).

### O2. OCR to editable documents with layout

- **Depends on:** C1 writers, E2.
- **Approach:** request Tesseract's hOCR (or TSV) output to get words with boxes and
  confidence, feed them into C1's layout model in place of pdfplumber words, and
  reuse the DOCX/XLSX writers. Mark low-confidence words in `details` so the UI can
  warn.
- **Done when:** `ocr_pdf` can produce a DOCX that keeps paragraphs and tables of a
  scanned page, with the limitation that recognition errors still need review.

### W1. Watermark candidate detection and broader removal

- **Owner:** PDF worker; frontend for the review step.
- **Today:** `_remove_watermark` removes top-level text objects whose text equals
  `exact_text`, or all annotations of a chosen subtype. Image, vector and nested
  watermarks are not handled.
- **Approach:** two steps, so nothing is removed without the user seeing it.
  1. *Detect* (`inspect_pdf` option `watermarks=true`, or a new additional operation
     if the coordinator prefers): list candidates with an id, page list, bounds and a
     reason:
     - marked content `/Artifact` with `/Subtype /Watermark`
       (`FPDFPageObj_CountMarks`, `FPDFPageObj_GetMark`, `FPDFPageObjMark_GetName`);
     - optional-content groups named as watermarks by common producers;
     - text objects with the same text and similar matrix on most pages, rotated or
       semi-transparent text;
     - image objects whose raw data hash (`FPDFImageObj_GetImageDataRaw`) repeats
       at the same position across pages;
     - form XObjects repeated across pages, inspected one level down
       (`FPDFFormObj_CountObjects`).
  2. *Remove* (`remove_watermark` option `candidate_ids`): remove exactly the chosen
     objects, including objects inside form XObjects via `FPDFFormObj_RemoveObject`.
     Keep `exact_text` and `annotation_subtype` working as now.
- **Out of scope:** pixel inpainting of watermarks burned into scanned images. Say so.
  Removal is still not redaction; hidden text under a removed object remains.
- **Copy:** state that users should only remove watermarks from documents they have
  the right to modify.
- **Done when:** fixtures with an Acrobat-style artifact watermark, a repeated
  diagonal text watermark, a repeated logo image and a nested form watermark are each
  detected and removed, and unrelated content is byte-identical after `gen_content`.

### A1. Better summaries

- **Owner:** media worker; frontend.
- **Today:** `media_ops._summary` chunks the text without page boundaries and
  map-reduces it to one Markdown summary.
- **Approach:**
  - chunk on page boundaries and label chunks with page numbers; ask for page
    references; verify that each cited page number exists and drop or flag invalid
    citations instead of passing them through;
  - optional structured sections (key points, decisions, dates, open questions) as a
    `style` option;
  - when no text is extractable and Tesseract is installed, offer "Run OCR first" in
    the UI as a separate, visible job rather than chaining silently.
- **Done when:** summaries carry page references that are checked against the input,
  and scanned input leads to an OCR offer instead of a bare error.

### F1. Add form fields to any PDF

- **Owner:** frontend (shared workspace).
- **Today:** fields can be filled (`fillPdf`) and flattened; `pdfInfo` marks radio
  groups, signature fields and buttons as `unsupported`; native `form_template`
  creates three fixed ReportLab templates (contact, approval, invoice).
- **Approach:** a field designer in the built-in workspace using pdf-lib's form API
  (`createTextField`, `createCheckBox`, `createRadioGroup`, `createDropdown`,
  `addToPage`): place, resize, name and set required/multiline/max length. Placement
  reuses Q3. Support filling radio groups (pdf-lib's `PDFRadioGroup.select`), and add
  JSON import/export of field values. Works offline on both website and desktop.
- **Out of scope:** XFA forms and form JavaScript (calculations, validation). Detect XFA
  and say it is unsupported rather than silently dropping it.
- **Done when:** a user can turn a plain PDF into a fillable form and fill it, and the
  output's fields read back with pdf-lib and pypdf.

### S1. Certificate-backed digital signatures (PAdES)

- **Owner:** coordinator (contract, dependency, multi-input), PDF worker
  (operations), frontend (UI).
- **Today:** only drawn image signatures. The README and UI correctly say these are
  not certificate signatures.
- **Approach:**
  - New additional operations `sign_pdf_certificate` and `verify_pdf_signatures`.
  - Library: pyHanko (MIT) with its certificate validator. Audit transitive licences
    before adding it to `worker/runtime-requirements.txt`.
  - Inputs: the PDF plus a PKCS#12 (`.p12`/`.pfx`) file chosen through
    `select_inputs`; this needs multi-input jobs (X5). The passphrase is entered per
    job and handled like `api_key`: never stored, logged or echoed.
  - Signature level: PAdES B-B offline by default. B-T (timestamp) and B-LT
    (revocation data) contact external servers, so they require a user-entered TSA URL
    and explicit per-job network consent, enforced in Rust as cloud jobs are today.
  - Visible appearance can reuse a drawn signature image; invisible signatures are
    allowed. Always sign as an incremental update so earlier signatures stay valid.
  - Verification reports integrity, signer certificate, signing time, coverage and
    whether the chain reaches a trust root the user supplied; it does not claim legal
    validity or qualified (eIDAS QES) status.
- **Tests:** generate a throwaway CA and PKCS#12 in the test; sign; verify with
  pyHanko and check the byte range and that a one-byte modification breaks
  verification; double signing keeps the first signature valid.
- **Done when:** the comparison row reads "Electronic signatures and certificate
  (PKCS#12) signatures" and the limitation text names what is not supported
  (hardware tokens, OS certificate stores, qualified signatures).

### V1. More video tools

- **Owner:** media worker; coordinator if the FFmpeg build changes.
- **Approach, within the existing VP9/Opus LGPL build:** trim (`start`, `end`),
  extract audio to Opus/OGG or FLAC, a `target_mb` mode using two-pass bitrate
  control, and resolution presets. Evaluate AV1 (SVT-AV1 or libaom, BSD-style with
  patent grants) as an optional codec; H.264/H.265/AAC remain excluded for licensing
  reasons, and the UI should say so plainly.
- **Done when:** each option has a real-FFmpeg test in the media suite and the output
  is probed for codec, duration and size.

### P1. Annotation polish (native and built-in)

- Add underline, strike-out, free text, ink and rectangle annotations (pypdf
  `annotations` already provides `FreeText`, `Rectangle`, `PolyLine`; markup types need
  low-level dictionaries); list and delete existing annotations; export a comment
  summary as text. Uses Q3 placement.

### P2. Polish for rows that are already "Yes"

Small, independent fixes in the shared workspace (`web/client/engine-core.ts`,
`web/client/workspace.tsx`):

- **Merge/split/reorder:** `transformPdf` and `mergePdfs` copy pages with
  `copyPages`, which can drop the AcroForm and outline. Carry over bookmarks whose
  targets survive, and form fields of kept pages; say what is dropped when it cannot
  be kept.
- **Rotate:** allow per-page rotation instead of one rotation for every selected page.
- **PDF → images (browser):** add JPEG and WebP and a higher DPI option within the
  existing 16-megapixel canvas limit; expose native `dpi`/`quality` (Q2).
- **QR codes:** PNG export as well as SVG, and a choice of error-correction level
  (currently fixed at `M`). Covered by work item QR1 in `docs/qr-code-plan.md`.
- **Signatures:** trim transparent margins of drawn signatures; typed signature in a
  chosen font (after T4).

---

---

## Phase 3 — large features

### T3. Paragraph reflow editing

- **Depends on:** T1, T2.
- **Approach:** detect paragraph blocks (lines with consistent left edge, leading
  and font); let the user edit the block's text; re-wrap with measured glyph widths
  from the replacement font into the block's width; replace all of the block's
  objects. Fail, not overflow, when new text needs more lines than fit, unless the
  user allows shrinking or extending into blank space below. Shaping for complex
  scripts (HarfBuzz via a permissively licensed binding, after licence review) belongs
  here.
- **Out of scope:** reflow across columns or pages, moving surrounding content.

### L1. Layout-preserving translation

- **Depends on:** T1 (embedded fonts), C1 (blocks and reading order). Coordinator must
  decide where shared PDF layout code lives, because `translate_pdf` is owned by the
  media worker and PDFium code by the PDF worker (see Open decisions).
- **Approach:** new `translate_pdf` option `layout=preserve` (default stays
  `document`): translate per text block in reading order, write the translation into
  the block's box with the T1 font logic and shrink-to-fit down to a minimum size,
  remove the original block objects, leave images, vectors and annotations untouched.
  List overflowing blocks in `details`. Offer a bilingual output (original and
  translation on facing pages) as a cheaper alternative.
- **Done when:** a two-column PDF with figures translates with figures in place, and
  every overflow is reported rather than clipped silently.

### L2. Dedicated offline translation engine

- **Why:** small general LLMs mistranslate facts (see the E4 gate failure); dedicated
  translation models are smaller and more faithful per language pair.
- **Approach:** evaluate CTranslate2 (MIT) with OPUS-MT/Marian or Argos Translate
  models (licences vary per model, many CC-BY with attribution) as an optional
  component, one download per language pair, behind a `provider=offline-mt` option.
- **Done when:** the same factuality gate used in E4 passes for the published pairs.

### S2. Hardware tokens, OS certificate stores and long-term validation

- **Depends on:** S1.
- PKCS#11 tokens and smart cards (pyHanko supports PKCS#11; needs the vendor driver
  module, chosen by the user), Windows certificate store, and B-LT/B-LTA with
  revocation data. Needs native interactive testing on real tokens.

### I1. Optional ML image tools (evaluate first)

- Upscaling and background removal through ONNX Runtime (MIT) with permissively
  licensed weights, as an optional consented component. Evaluate CPU speed, pack size
  and weight licences before committing; it must stay clearly labelled as generative
  when it invents detail.

---

## Cross-cutting work

### X1. Progress reporting and cancellation

- **Today:** a native job is one blocking worker call with a 30-minute timeout
  (`worker_process.rs: WORKER_TIMEOUT`) and no progress or user cancellation. OCR of a
  long PDF, transcription and model jobs are exactly the slow cases this plan adds
  more of.
- **Approach (coordinator):** let the worker emit progress lines on a separate
  channel (stdout stays reserved for the single result line), surface them as Tauri
  events, and add a cancel IPC method that kills the job's process tree with the
  existing containment. Adding an IPC method changes the fixed IPC list in `AGENTS.md`
  and needs the user's approval.

### X2. Fidelity corpus and metrics

- Keep a small committed corpus of generated fixtures (ReportLab/Pillow, as the PDF
  suite does now) plus an ignored local corpus of real documents under
  `tests/artifacts/`. Add a script that runs C1, O1, O2, T1 and L1 over the corpus and
  prints metrics (character recall, reading-order distance, table cell accuracy,
  overflow count). Record before/after numbers in the evidence log for every change to
  those items.

### X3. Contract change checklist

When a work item adds an operation, option, component or IPC method, update all of:

1. `worker/main.py` (`PDF_OPERATIONS` / `MEDIA_OPERATIONS`) — coordinator.
2. `OPERATIONS` and `OPTION_KEYS` in the owning worker module, with tests.
3. The operation allowlist in `crates/native-security/src/lib.rs`, job handling in
   `src-tauri/src/main.rs`, component handling in `src-tauri/src/components.rs` and
   `components/registry.json`.
4. `src/native-model.ts` (`nativeOperations`) and `src/native-catalog.ts` (fields,
   `components`, note text).
5. `worker/PDF-OPTIONS.md` or `worker/MEDIA-OPTIONS.md`.
6. `README.md` "Scope and limitations", the comparison table, and website copy under
   `web/` if the browser edition is affected.
7. `scripts/smoke_operations.py` / `scripts/tests/test_packaged_operations.py` so the
   packaged-app check covers the new behaviour.
8. Dependencies: `worker/runtime-requirements.txt` (frozen worker),
   `scripts/license-report.py` output and third-party notices.

### X4. Native acceptance

- Extend the packaged operation checks (currently 22) with one check per new
  behaviour, run on both platforms in `build.yml`. Engine-dependent checks run only
  against published packs. Interactive behaviour (Q3 picker, F1 designer, consent
  dialogs) needs the Windows GUI smoke (`scripts/smoke_windows_gui.py`) or a manual
  test record; browser-preview tests do not count as native evidence.
- The Playwright browser suites (`tests/browser_e2e.py`, `web/tests/e2e.py` and
  others) are not run by any workflow today. Items that change the shared workspace
  (Q3, Q7, T4, F1, P2) should add browser coverage and run it against fresh builds of
  both targets, as `AGENTS.md` requires.
- `web/tests/engine.test.ts` downloads pdf-lib and qrcode-generator from jsDelivr on
  first run. Keep that in mind when adding fontkit (T4): the test needs the same
  pinned version the website loads.

### X5. Multi-input native jobs

- **Today:** `pdf_ops._run` and `media_ops.run` accept one input; Rust already allows
  up to 64 `inputIds`.
- **Needed by:** S1 (PDF + certificate), T1 (PDF + font file), and a future native
  merge. Define the per-operation input roles in the contract (for example
  `inputs[0]` is the document, `inputs[1]` the credential) rather than inferring them
  from file extensions.

---

## Open decisions

These need a decision from the project owner before the dependent items start.

1. **Bundled fonts (T1, T4, Q8, L1).** Bundle a Noto subset (OFL) in the app, ship
   fonts as an optional font pack component, or rely on user-selected font files only.
   CJK coverage adds tens of megabytes.
2. **Download cap for models (E4, E5).** Keep 750 MiB for all components or allow a
   larger, clearly displayed cap for model files.
3. **Several versions per component id (E2, E5).** Extend the registry and
   `ComponentStatus` so one id (for example `whisper_model`, OCR languages) can have
   several installable members, or add new component ids.
4. **Shared PDF layout code (L1, O2).** Allow a shared worker module (owned by the PDF
   worker, imported by the media worker), or move layout-preserving translation into
   `pdf_ops` under a new operation.
5. **Signing scope (S1).** PKCS#12 only for the first version, and whether
   timestamping is offered at all in v1.
6. **New IPC methods (X1, E0).** Approve adding progress/cancel and component
   update/uninstall methods beyond the fixed list in `AGENTS.md`.
7. **Watermark detection (W1).** Confirm the candidate-detection approach and wording
   is acceptable for the product.

## Non-goals

- Password recovery or cracking (unlocking stays known-password only).
- Silent cloud fallback, automatic downloads, or any network use during local jobs.
- Pixel-level removal of watermarks from scanned images.
- XFA forms and PDF JavaScript execution.
- Claims of legal validity for signatures, or of exact Office round-trips.
