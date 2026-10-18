# Native PDF worker options

`pdf_ops.run({operation,inputs,output_dir,options,engines})` returns
`{outputs:[{path,name,mime}],details:{...}}`. Inputs and output_dir are absolute paths.
One input per job except `form_template`, which needs none. Paths/programs come from
Rust grants/engine registry, never frontend options. Outputs have unique generated
names in the job directory, are never written over originals, and are removed on
failure. Unknown operations/options fail. `inspect_pdf` returns no file.
`PdfOperationError` is a safe ValueError; raw parser/subprocess errors are not exposed.

## Exact options

| Operation | Options and defaults | Behavior/limits |
|---|---|---|
| `inspect_pdf` | `page`: optional 1-based integer, default all | `details.pages[]`: page,width,height,objects[]. Object fields: object_index (0-based top-level index),type,bounds; text objects add text,font,font_size,render_mode,editable,unsupported_reason. Nested form XObjects are not expanded. |
| `edit_pdf_text` | `page=1`, required `object_index`, required `text`, optional `font`, optional `font_size` (default original, 1–500 points) | PDFium mutates original text object using FPDFText_SetText/SetFontSize. A font change removes the actual original object and inserts a replacement with original transform/colors/render mode, not a white overlay. Supported font names: Helvetica, Helvetica-Bold, Helvetica-Oblique, Times-Roman, Times-Bold, Times-Italic, Courier, Courier-Bold, Courier-Oblique. Replacement is conservatively Latin-1 only (with or without font substitution); other scripts explicitly fail. Max 10000 characters, no NUL. No reflow; clipping/invisible text and nontext/nested objects explicitly rejected. Subset fonts/complex scripts can be unsupported. Substitution does not preserve clipping/blending/kerning or drawing order. |
| `annotate_pdf` | `page=1`, `kind=comment` (`comment` or `highlight`), `text=""`, required `rect=[x1,y1,x2,y2]` | Real /Text or /Highlight annotations, not flattened overlays. Finite, positive-area PDF user-space coordinates. Highlight includes /QuadPoints. UI must map rotation/crop coordinates. Text max 10000 characters. |
| `convert_to_pdf` | `timeout=120` seconds (1–600, Office only) | DOCX/XLSX/PPTX/ODT/ODS/ODP require `engines.libreoffice`. PNG/JPEG/TIFF/BMP/WebP use Pillow/ReportLab; multiframe images become pages. TXT uses UTF-8 and standard Courier. HTML/HTM is **text-only**: no browser, asset loading, scripts, styles or embedded content. Standard-font Unicode coverage is limited. |
| `convert_from_pdf` | `format=docx` (`docx,xlsx,pptx,png,jpeg,txt,csv,html`), `dpi=150` (72–300, images), `quality=85` (20–95, JPEG) | One image per page in output-array order. Other formats are editable best-effort reconstruction. DOCX preserves line order/page breaks plus detected tables (table text may repeat). XLSX/CSV use detected tables, fallback text lines; formula-leading cell values are escaped. PPTX uses approximately positioned editable lines and full extracted text in notes, not raster slides. No original images/typography reconstruction. Exported HTML is escaped text with restrictive CSP. Scans need OCR. |
| `form_template` | `template_id=contact` (`contact,approval,invoice`) | Real standard-Helvetica AcroForm fields. Contact: name,email,message. Approval: requester,description,approved checkbox. Invoice: invoice_number,customer,amount. General-purpose samples, **not legal/accounting templates**. |
| `protect_pdf` | required nonempty `password`, required distinct nonempty `owner_password` | pypdf + cryptography AES-256. Owner permission flags are advisory, not security guarantees. |
| `unlock_pdf` | required known nonempty `password` | Wrong password fails. Only writes unencrypted copy after successful authentication. No password recovery. |
| `remove_watermark` | optional nonempty `exact_text`, optional `annotation_subtype` (`Watermark,Stamp,FreeText,Text,Highlight`), optional 1-based `page` (default all) | At least one selector required. Removes entire top-level PDFium text objects only on exact equality; no substring guessing. Selected annotation subtype removes **all** annotations of that subtype on selected pages. No match fails. Images/nested form watermarks not automatically removed. Not secure redaction. |
| `compress_pdf` | `mode=lossless` (`lossless,raster`), `dpi=150` (72–300), `quality=75` (20–95) | Default structural compression/dedup retains text/forms/annotations; size can grow. Raster is explicitly lossy JPEG and flattens text/forms/annotations/links into pixels. No guaranteed size reduction. |
| `ocr_pdf`, `ocr_image` | `language=eng`, `dpi=300` (72–300), `timeout=120` per page (1–600), `include_editable_text=true` | Require `engines.tesseract` and installed language data. Languages are code names such as eng or eng+deu. Both produce searchable **raster** PDF plus separately editable UTF-8 `.txt`. `include_editable_text=false` is rejected, to keep the editable companion mandatory. OCR errors need review. Scan layout is not semantically editable; existing forms/annotations flatten. Image physical dimensions may change. |

## Input and engine safety

512 MiB per input; 40 megapixels per rendered/input image; 5 MiB text/HTML.
Office ZIP preflight: max 10000 entries, 200 MiB expanded total, 30 MiB per
entry, ratio ≤500; reject traversal, symlinks, encrypted entries, XML entities,
macros, embedded executable/OLE entries, DDE/active fields and external relationships.
This is conservative (external hyperlinks also rejected), not a substitute for an OS
sandbox. Native PDF parsers likewise are not an OS sandbox; Rust should enforce job
resource/time budgets and component integrity.

Office receives a unique disposable user profile, highest MacroSecurityLevel=3,
DisableMacrosExecution=true, and actual schema settings Writer Content/Update/Link=2
(Never), Calc Content/Update/Link=1 (Never). **UpdateDocMode is a UNO load property,
not a Common/Load registry key**: upstream headless conversion loads with
UpdateDocMode=ACCORDING_TO_CONFIG, so these settings disable link updates. Sources:
LibreOffice core `desktop/source/app/dispatchwatcher.cxx` and `officecfg/registry/schema/org/openoffice/Office/{Writer,Calc,Common}.xcs`.
Arguments include `-env:UserInstallation=file://... --headless --nologo --nodefault
--nolockcheck --norestore`. External resource inputs are rejected before engine launch.
All subprocesses use argument arrays, `shell=False`, stdin/stdout/stderr discarded,
timeouts, explicit executable paths and temporary job directories. Missing optional
engines give an installation-with-consent error; never download during processing.

## Verification and licensing

Run from project root:

```
env PYTHONPATH= PYTHONHOME= .venv-worker/bin/python -m pytest worker/tests/test_pdf_ops.py -q -rs
```

Generated fixtures use ReportLab/Pillow and are independently read with pypdf,
PDFium, Pillow, python-docx, openpyxl and python-pptx. RED/GREEN source/test hashes,
commands and exit statuses are retained in `pdf-evidence.log`. Engine failure probes
are orchestration coverage, **not successful Office/OCR conversion evidence**.
Optional actual engine tests require PAPERWORK_TESSERACT and PAPERWORK_LIBREOFFICE
absolute executable paths. This host has neither engine: successful OCR and Office
imports remain unverified, not silently passed.

Installed metadata checked: pdfplumber, pdfminer.six, python-docx, openpyxl,
python-pptx, charset-normalizer: MIT; pypdf and core XML dependencies: BSD;
ReportLab: BSD; Pillow: MIT-CMU; cryptography: Apache-2.0 OR BSD-3-Clause;
cffi: MIT-0. No PyMuPDF/MuPDF/Ghostscript/GPL Python packages used.
pypdfium2 wrapper: BSD-3-Clause/Apache-2.0; PDFium and bundled dependencies retain
additional permissive notices. **Packaging must preserve the complete wheel LICENSES
and BUILD_LICENSES directories (including PDFium/FreeType/ICU/JPEG notices), not just
this application's MIT license.** Optional LibreOffice/Tesseract engine distributions
need their own component license/notices review and explicit consent; they are not
bundled or relicensed by this module.
