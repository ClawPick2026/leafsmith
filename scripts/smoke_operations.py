"""Synthetic artifact acceptance for an actual frozen worker, not source imports.

Host Python dependencies create/parse fixtures only. The child receives no Python,
external engine or library environment. Optional engines are explicitly excluded.
All retained documents and diagnostics contain synthetic data only.
"""
from __future__ import annotations

import csv
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

EXCLUDED = {
    "office_import": "Requires a separately verified, consented LibreOffice engine.",
    "ocr_pdf": "Requires a separately verified Tesseract engine and language data.",
    "ocr_image": "Requires a separately verified Tesseract engine and language data.",
    "summarize": "Requires a separately verified local model/server or explicit cloud consent.",
    "translate_pdf": "Requires a separately verified local model/server or explicit cloud consent.",
    "transcribe": "Requires separately verified FFmpeg, speech engine and model.",
    "compress_video": "Requires a separately verified FFmpeg engine.",
}


def isolated_environment():
    keep = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP", "TMPDIR",
            "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL"}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32") if os.name == "nt" else ""
    return env


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_record(path):
    return {"name": path.name, "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def create_fixtures(directory):
    from PIL import Image
    from reportlab.pdfgen import canvas
    directory.mkdir(mode=0o700)
    pdf = directory / "synthetic-invoice.pdf"
    doc = canvas.Canvas(str(pdf), pagesize=(612, 792), invariant=1)
    doc.setFont("Helvetica", 18)
    doc.drawString(54, 730, "Original invoice")
    doc.drawString(54, 670, "DRAFT")
    doc.acroForm.textfield(name="reference", value="SYNTHETIC-001", x=54, y=540,
                          width=240, height=24, fontName="Helvetica")
    doc.showPage()
    doc.save()
    text = directory / "synthetic.txt"
    text.write_text("Original invoice\nSynthetic text import\n", encoding="utf-8")
    html = directory / "synthetic.html"
    html.write_text("<html><body><p>Original invoice</p><script>FORBIDDEN SCRIPT</script>"
                    "<img src='https://invalid.example/never-fetch.png'></body></html>", encoding="utf-8")
    image = directory / "synthetic.png"
    Image.new("RGB", (64, 32), (80, 100, 120)).save(image)
    return {"pdf": pdf, "txt": text, "html": html, "image": image}


def invoke_worker(worker, operation, inputs, options, root, entry, report):
    """One request/process; never log the request or its password options."""
    job = Path(tempfile.mkdtemp(prefix=entry["name"] + "-", dir=root))
    request = {"operation": operation, "inputs": [str(p) for p in inputs],
               "output_dir": str(job), "options": options, "engines": {}}
    process = {"label": "builtin-" + entry["name"], "returncode": None}
    report.setdefault("processes", []).append(process)
    entry["job"] = job.name
    stdout = stderr = b""
    try:
        completed = subprocess.run([str(worker)], input=(json.dumps(request) + "\n").encode(),
                                   capture_output=True, timeout=180, cwd=job,
                                   env=isolated_environment(), shell=False)
        stdout, stderr = completed.stdout, completed.stderr
        process["returncode"] = entry["returncode"] = completed.returncode
    except subprocess.TimeoutExpired as error:
        process["timed_out"] = entry["timed_out"] = True
        stdout, stderr = error.stdout or b"", error.stderr or b""
        raise ValueError("Frozen worker timed out") from None
    finally:
        for stream, value in (("stdout", stdout), ("stderr", stderr)):
            if isinstance(value, str):
                value = value.encode("utf-8")
            (job / (stream + ".log")).write_bytes(value)
    require(completed.returncode == 0, "Frozen worker exited " + str(completed.returncode))
    try:
        envelope = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise ValueError("Worker stdout is not one JSON response") from None
    require(isinstance(envelope, dict) and envelope.get("ok") is True,
            "Worker returned a protocol error (see synthetic stdout log)")
    result = envelope.get("result")
    require(isinstance(result, dict) and isinstance(result.get("outputs"), list)
            and isinstance(result.get("details"), dict), "Invalid worker result schema")
    paths = []
    for output in result["outputs"]:
        require(isinstance(output, dict) and isinstance(output.get("path"), str), "Invalid output record")
        path = Path(output["path"])
        require(path.is_absolute() and not path.is_symlink() and path.resolve().parent == job.resolve()
                and path.is_file() and path.stat().st_size > 0, "Output escaped job or is missing/empty")
        require(output.get("name") == path.name and isinstance(output.get("mime"), str), "Invalid output metadata")
        paths.append(path)
    require(len(set(paths)) == len(paths), "Duplicate output paths")
    entry["outputs"] = [file_record(path) for path in paths]
    return result, paths


def read_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    require(not reader.is_encrypted and len(reader.pages) == 1, "Expected one readable, unencrypted PDF page")
    return reader


def pdf_text(path):
    return read_pdf(path).pages[0].extract_text() or ""


def single(paths):
    require(len(paths) == 1, "Expected exactly one output")
    return paths[0]


def validate_export(path, format):
    if format in {"png", "jpeg"}:
        from PIL import Image, ImageStat
        with Image.open(path) as image:
            image.load()
            require(image.format == format.upper() and image.size == (612, 792), "Incorrect rendered image format/dimensions")
            require(max(ImageStat.Stat(image.convert("RGB")).var) > 1, "Rendered PDF image is blank")
        return
    if format in {"docx", "xlsx", "pptx"}:
        members = {"docx": ["word/document.xml"], "xlsx": ["xl/worksheets/sheet1.xml"],
                   "pptx": ["ppt/slides/slide1.xml"]}[format]
        with zipfile.ZipFile(path) as archive:
            require(archive.testzip() is None and "[Content_Types].xml" in archive.namelist(), "Invalid Office archive")
            roots = [ET.fromstring(archive.read(name)) for name in members]
            if format == "xlsx" and "xl/sharedStrings.xml" in archive.namelist():
                roots.append(ET.fromstring(archive.read("xl/sharedStrings.xml")))
            text = " ".join(" ".join(root.itertext()) for root in roots)
    elif format == "csv":
        text = " ".join(" ".join(row) for row in csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    elif format == "html":
        class Text(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
            def handle_data(self, data):
                self.parts.append(data)
        parser = Text()
        parser.feed(path.read_text(encoding="utf-8"))
        text = " ".join(parser.parts)
    else:
        text = path.read_text(encoding="utf-8")
    require("Original invoice" in text and "DRAFT" in text, "Export lost synthetic document text")


def exercise_builtin_operations(worker, logs, report):
    """Fail closed but finish independent checks to retain a useful failure matrix."""
    root = Path(tempfile.mkdtemp(prefix="builtin-operations-", dir=logs)).resolve()
    summary = {"success": False, "synthetic_only": True, "root": str(root), "checks": [],
               "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "excluded": [{"name": key, "status": "excluded", "reason": value} for key, value in EXCLUDED.items()],
               "passed": 0, "failed": 0}
    report["builtin_operations"] = summary
    fixtures = create_fixtures(root / "fixtures")
    summary["fixtures"] = [file_record(path) for path in fixtures.values()]
    state = {}

    def check(name, operation, inputs, options, verify):
        entry = {"name": name, "operation": operation, "status": "failed", "outputs": []}
        summary["checks"].append(entry)
        try:
            result, paths = invoke_worker(worker, operation, inputs, options, root, entry, report)
            verify(result, paths)
            entry["status"] = "passed"
        except Exception as error:
            entry["error"] = str(error)
        summary["passed"] = sum(item["status"] == "passed" for item in summary["checks"])
        summary["failed"] = len(summary["checks"]) - summary["passed"]
        (root / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def inspect(result, paths):
        require(not paths, "Inspection unexpectedly emitted files")
        pages = result["details"].get("pages", [])
        require(len(pages) == 1 and pages[0].get("width") == 612, "Inspection lost page geometry")
        objects = pages[0].get("objects", [])
        selected = [obj for obj in objects if obj.get("text") == "Original invoice" and obj.get("editable") is True]
        require(len(selected) == 1 and any(obj.get("text") == "DRAFT" for obj in objects), "PDFium inspection did not identify editable text")
        state["object_index"] = selected[0]["object_index"]

    pdf = fixtures["pdf"]
    check("inspect", "inspect_pdf", [pdf], {}, inspect)

    def edited(result, paths):
        path = single(paths)
        text = pdf_text(path)
        require("Revised invoice" in text and "Original invoice" not in text and "DRAFT" in text,
                "Text replacement did not remove original text and retain other text")
        page = read_pdf(path).pages[0]
        fonts = page["/Resources"]["/Font"].get_object().values()
        require(any(font.get_object().get("/BaseFont") == "/Courier-Bold" for font in fonts), "Selected replacement font missing")
        require(b"Original invoice" not in page.get_contents().get_data(), "Original text object remains in content stream")

    # A failed inspection cannot silently turn editing into a skip/pass.
    check("edit-font", "edit_pdf_text", [pdf], {"page": 1, "object_index": state.get("object_index", -1),
          "text": "Revised invoice", "font": "Courier-Bold", "font_size": 16}, edited)

    def annotated(kind, paths):
        page = read_pdf(single(paths)).pages[0]
        annotations = [ref.get_object() for ref in page.get("/Annots", [])]
        subtype = "/Text" if kind == "comment" else "/Highlight"
        matching = [a for a in annotations if a.get("/Subtype") == subtype and a.get("/Contents") == "Synthetic note"]
        require(len(matching) == 1, "Missing real PDF annotation/comment contents")
        require(list(matching[0]["/Rect"]) == [54, 710, 220, 750], "Annotation rectangle changed")
        if kind == "highlight":
            require(len(matching[0].get("/QuadPoints", [])) == 8, "Highlight has no quadrilateral")
        require("Original invoice" in pdf_text(single(paths)), "Annotation removed document text")

    for kind in ("comment", "highlight"):
        check("annotation-" + kind, "annotate_pdf", [pdf], {"kind": kind, "page": 1,
              "rect": [54, 710, 220, 750], "text": "Synthetic note"},
              lambda result, paths, kind=kind: annotated(kind, paths))

    def form(result, paths):
        from pypdf import PdfReader, PdfWriter
        path = single(paths)
        reader = read_pdf(path)
        fields = reader.get_fields()
        require(set(fields or {}) == {"name", "email", "message"}, "Template form fields missing")
        require(all(field.get("/FT") == "/Tx" for field in fields.values()), "Template fields are not fillable text")
        writer = PdfWriter(clone_from=reader)
        writer.update_page_form_field_values(writer.pages[0], {"name": "Synthetic Person"})
        filled = io.BytesIO()
        writer.write(filled)
        filled.seek(0)
        require(PdfReader(filled).get_fields()["name"].get("/V") == "Synthetic Person", "Form fill/readback failed")

    check("form-template", "form_template", [], {"template_id": "contact"}, form)

    def protected(result, paths):
        from pypdf import PdfReader
        path = single(paths)
        reader = PdfReader(path)
        require(reader.is_encrypted, "Protect produced an unencrypted PDF")
        encryption = reader.trailer["/Encrypt"]
        require(encryption.get("/V") == 5 and encryption.get("/Length") == 256
                and encryption["/CF"]["/StdCF"].get("/CFM") == "/AESV3", "Output is not AES-256")
        require(reader.decrypt("synthetic-password") != 0 and "Original invoice" in reader.pages[0].extract_text(), "Known-password AES readback failed")
        state["protected"] = path

    check("protect-aes", "protect_pdf", [pdf], {"password": "synthetic-password", "owner_password": "synthetic-owner"}, protected)

    def unlocked(result, paths):
        require("Original invoice" in pdf_text(single(paths)), "Unlock lost document text")
        require(result["details"].get("encryption") == "none", "Unlock still reports encryption")

    check("unlock-known-password", "unlock_pdf", [state.get("protected", pdf)], {"password": "synthetic-password"}, unlocked)

    def removed(result, paths):
        text = pdf_text(single(paths))
        require("DRAFT" not in text and "Original invoice" in text, "Exact watermark removal changed wrong text")
        require(result["details"].get("removed_objects") == 1, "Expected exactly one removed object")

    check("remove-exact-watermark", "remove_watermark", [pdf], {"exact_text": "DRAFT"}, removed)

    def compressed(mode, paths):
        reader = read_pdf(single(paths))
        if mode == "lossless":
            require("Original invoice" in reader.pages[0].extract_text() and "reference" in (reader.get_fields() or {}), "Lossless compression lost text/form")
        else:
            require(not reader.pages[0].extract_text().strip() and len(reader.pages[0].images) > 0, "Raster PDF is not flattened to an image")
        require(tuple(reader.pages[0].mediabox)[2:] == (612, 792), "Compression changed page dimensions")

    for mode in ("lossless", "raster"):
        check("compress-" + mode, "compress_pdf", [pdf], {"mode": mode, "dpi": 72, "quality": 80},
              lambda result, paths, mode=mode: compressed(mode, paths))
    for format in ("docx", "xlsx", "pptx", "txt", "csv", "html", "png", "jpeg"):
        check("export-" + format, "convert_from_pdf", [pdf], {"format": format, "dpi": 72},
              lambda result, paths, format=format: validate_export(single(paths), format))

    def imported(kind, paths):
        reader = read_pdf(single(paths))
        if kind == "image":
            require(len(reader.pages[0].images) == 1, "Image import has no embedded image")
        else:
            text = reader.pages[0].extract_text()
            require("Original invoice" in text and "FORBIDDEN SCRIPT" not in text, "Text/HTML import lost text or included scripts")

    for kind in ("txt", "html", "image"):
        check("import-" + kind, "convert_to_pdf", [fixtures[kind]], {},
              lambda result, paths, kind=kind: imported(kind, paths))

    def enhanced(result, paths):
        from PIL import Image
        with Image.open(single(paths)) as image:
            image.load()
            require(image.format == "PNG" and image.size == (32, 16), "Pillow output format/resize incorrect")
            require(image.getpixel((16, 8)) == (120, 150, 180), "Pillow brightness did not alter pixels correctly")
        require(result["details"].get("engine") == "Pillow", "Unexpected image enhancement engine")

    check("enhance-image", "enhance_image", [fixtures["image"]], {"format": "png", "brightness": 1.5,
          "width": 32, "height": 16}, enhanced)
    summary["checks_count"] = len(summary["checks"])
    summary["success"] = summary["failed"] == 0
    (root / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if not summary["success"]:
        raise ValueError(f"builtin operation acceptance: {summary['failed']}/{summary['checks_count']} checks failed; see {root / 'results.json'}")
    return summary
