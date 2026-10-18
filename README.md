# Paperwork Desktop

Local-first PDF, document, image and media tools, with the same interface as [Paperwork on the web](https://paperwork.lakebed.app).

**Release status:** the application source is available, but native Windows/Linux builds and optional engine packs are still being validated. No finished installer is published yet. Do not mistake successful frontend tests or a CI recipe for a verified desktop release.

## Main Window

![Paperwork Desktop main interface with PDF tools and file workspace](docs/screenshots/browser/desktop-home.png)

The desktop interface captured during real-browser verification. This image does not establish packaged-app or installer compatibility.

## What you can do

The built-in workspace provides:

- Merge, split, reorder, rotate, crop, extract and delete PDF pages.
- Add text, images, shapes and flattened highlights; draw electronic signatures.
- Fill supported PDF forms and extract embedded text.
- Convert images to PDF and PDF pages to images.
- Resize, combine and compress images, and generate QR codes.

The separate **Native tools** workspace adds existing-text editing and standard-font replacement, genuine PDF comments/highlights, Office export/import, OCR, form templates, password protection and known-password unlocking, selected text-watermark removal, PDF/image/video processing, transcription, summaries and text translation. Some operations require a separately installed processing engine or AI model. Native platform and real-engine validation is still in progress; see the release status above.

## Common feature previews

### Organize PDF pages

![PDF page workspace with ordering, rotation, extraction and crop controls](docs/screenshots/browser/desktop-workspace.png)

Select pages and export a new document without overwriting the input.

### Native document tools

![Native PDF editing panel with selected-object and font controls](docs/screenshots/browser/desktop-native-panel.png)

Native files are selected separately from the built-in workspace. Required engines must be available before a job can run.

## First use

Until verified installers are published, the [browser edition](https://paperwork.lakebed.app) remains available with its explicitly reduced feature set. Downloadable desktop releases will be listed on this repository's [Releases page](https://github.com/ClawPick2026/paperwork-desktop/releases).

For the built-in workspace, choose **Try a sample**, open **Organize PDF**, select an operation and download the resulting document. For your own work, use **Choose files** and retain the originals.

In **Native tools**, choose a task, select native input files, enter its parameters and run it. Use **Save output** to retain each result outside the private job cache. Optional engines and models are managed under **Optional components & models**, with separate download consent. A missing or unpublished component is not assumed installed.

For local AI, use an explicitly selected local model file, an available downloaded model, or a running local Ollama service with an installed model. Cloud processing is optional: supply your own provider settings and API key, then approve that individual job. Keys are not saved in application settings.

## Scope and limitations

- Existing-text editing changes selected text objects; it is not a general layout editor. Complex scripts, nested text, original font embedding and non-Latin text replacement are not supported by the current editor.
- PDF-to-Office export reconstructs content approximately. Fonts, tables, reading order, images and layout can differ.
- OCR adds searchable text and editable text/document exports; it does not turn the original scanned pixels into a fully editable layout.
- Drawn signatures are electronic images, not certificate-backed digital signatures.
- Unlocking requires a password you already know. Watermark removal is targeted, not automatic removal from arbitrary images or page content.
- Lossless PDF optimization may not reduce size. Raster compression is lossy and flattens text, forms, links and annotations.
- AI output can omit, invent or mistranslate information. Translation creates a newly typeset text document, not a layout-preserving copy. Language/font coverage and model quality vary.

## Safety and privacy

- Local processing is the default. No document content is automatically uploaded for cloud AI; cloud jobs require individual approval.
- Optional component/model downloads contact their distribution servers and require consent. Their licenses are displayed separately.
- Native processing writes private temporary files and outputs to the app cache. Successful outputs remain available to save during the session. Normal app exit and the next startup clean job caches; a crash or forced termination may leave files on disk until cleanup succeeds.
- Closing the app clears the in-memory workspace. Save desired outputs first; keep separate backups of original documents.
- Processing untrusted files is not an operating-system sandbox. Review sensitive or adversarial documents accordingly.

## Compatibility

The first release targets **Windows x86_64** and **Linux x86_64**. ARM64 and macOS packages are not currently provided. Linux compatibility depends on the packaged libraries and host desktop requirements; no universal distribution compatibility is claimed. Packages are unsigned unless a release explicitly says otherwise, and Windows may display a SmartScreen warning.

## License and support

Paperwork's application code is [MIT licensed](LICENSE). Libraries, processing engines, fonts and AI models retain their own licenses; the application license does not relicense those components.

Report reproducible problems through [GitHub Issues](https://github.com/ClawPick2026/paperwork-desktop/issues). Do not attach private documents, passwords or API keys.
