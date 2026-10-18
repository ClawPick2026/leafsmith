"""Packaging regressions; real freeze/native smoke remains a CI integration test."""
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def execute_with_root(script, root, monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(ROOT / "scripts" / script)])
    namespace = {"__file__": str(root / "scripts" / script), "__name__": "__main__"}
    exec(compile((ROOT / "scripts" / script).read_text(), script, "exec"), namespace)
    return namespace


def test_license_collection_preserves_nested_pdfium_notice_text(tmp_path, monkeypatch):
    import importlib.metadata as md
    names = {"pypdfium2": "data/BUILD_LICENSES/pdfium.txt", "pillow": "LICENSE",
             "cryptography": "LICENSE.APACHE", "reportlab": "fonts/bitstream-vera-license.txt",
             "pyinstaller": "COPYING.txt"}
    distributions = []
    for name, notice in names.items():
        relative = Path(name) / "licenses" / notice
        target = tmp_path / "site" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Actual notice fixture for " + name + " bootloader exception")
        class Distribution:
            version = "1.0"
            def __init__(self, name, relative):
                self.metadata = {"Name": name, "License": "See license files"}
                self.files = [relative]
            def locate_file(self, file):
                return tmp_path / "site" / file
        distributions.append(Distribution(name, relative))
    monkeypatch.setattr(md, "distributions", lambda: distributions)
    execute_with_root("license-report.py", tmp_path, monkeypatch)
    output = tmp_path / "build/worker/paperwork-worker/third-party-licenses"
    found = list(output.rglob("pdfium.txt"))
    assert found and found[0].read_text() == "Actual notice fixture for pypdfium2 bootloader exception"


def test_freeze_removes_unused_restrictive_font_payload(tmp_path, monkeypatch):
    fonts = tmp_path / "build/worker/paperwork-worker/_internal/reportlab/fonts"
    fonts.mkdir(parents=True)
    (fonts / "DarkGardenMK.pfb").write_bytes(b"unused font fixture")
    (fonts / "hb-test.ttf").write_bytes(b"unused test font fixture")
    (fonts / "Vera.ttf").write_bytes(b"retained font fixture")
    health = json.dumps({"ok": True, "result": {"outputs": [], "details": {
        "status": "ok", "form_pages": 1, "form_fields": 3}}})
    monkeypatch.setattr(subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 0, health, ""))
    execute_with_root("freeze-worker.py", tmp_path, monkeypatch)
    assert not (fonts / "DarkGardenMK.pfb").exists()
    assert not (fonts / "hb-test.ttf").exists()
    assert (fonts / "Vera.ttf").exists()


def test_npm_notices_include_nested_font_licenses(tmp_path):
    package = tmp_path / "node_modules/example"
    (package / "standard_fonts").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "example", "version": "1.0", "license": "Apache-2.0"}))
    notice = package / "standard_fonts/LICENSE_LIBERATION"
    notice.write_text("Font-specific actual license fixture")
    collector = runpy.run_path(str(ROOT / "scripts/license-report.py"))["collect_npm"]
    output = tmp_path / "notices"
    records = collector(tmp_path, output)
    paths = [output / p for p in records[0]["notices"]]
    assert any(p.read_text() == notice.read_text() for p in paths)


def test_rust_notices_include_nested_vendored_library_terms(tmp_path, monkeypatch):
    crate = tmp_path / "registry/example"
    (crate / "third_party/library").mkdir(parents=True)
    (crate / "third_party/library/LICENSE").write_text("Vendored library actual notice fixture")
    package = {"name": "example", "version": "1.0", "manifest_path": str(crate / "Cargo.toml"),
               "source": "registry+test-fixture", "license": "MIT"}
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, json.dumps({"packages": [package]}), ""))
    collector = runpy.run_path(str(ROOT / "scripts/license-report.py"))["collect_rust"]
    output = tmp_path / "notices"
    records = collector(tmp_path, output)
    assert any((output / p).read_text() == "Vendored library actual notice fixture" for p in records[0]["notices"])


def test_cargo_metadata_decodes_explicit_utf8_not_windows_ansi(tmp_path, monkeypatch):
    def metadata(command, **kwargs):
        assert kwargs.get('encoding') == 'utf-8', 'Cargo JSON is UTF-8, including non-ASCII crate metadata on Windows'
        return subprocess.CompletedProcess(command,0,json.dumps({'packages':[], 'description':'日本語 ⚙'},ensure_ascii=False),'')
    monkeypatch.setattr(subprocess,'run',metadata)
    collector=runpy.run_path(str(ROOT/'scripts/license-report.py'))['collect_rust']
    assert collector(tmp_path,tmp_path/'notices') == []


def test_smoke_retains_failure_evidence_for_zero_exit_non_worker(tmp_path):
    # A real process that exits zero but emits no worker protocol must fail.
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/smoke-package.py"),
                                "--kind", "worker", "--path", sys.executable,
                                "--logs", str(tmp_path)], text=True, capture_output=True)
    assert completed.returncode != 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["success"] is False
    assert report["processes"][0]["returncode"] == 0
    assert (tmp_path / "worker.stdout.log").exists()
    assert (tmp_path / "worker.stderr.log").exists()


@pytest.mark.parametrize("details", [
    {"status": "ok"},
    {"status": "ok", "form_pages": 0, "form_fields": 3},
    {"status": "ok", "form_pages": 1, "form_fields": 0},
    {"status": "ok", "form_pages": True, "form_fields": 3},
    {"status": "unavailable", "form_pages": 1, "form_fields": 3},
])
def test_import_only_or_empty_health_is_not_a_roundtrip(details):
    validate = runpy.run_path(str(ROOT / "scripts/freeze-worker.py"))["validate_health"]
    with pytest.raises(ValueError, match="health self-test"):
        validate(json.dumps({"ok": True, "result": {"outputs": [], "details": details}}))


def test_process_failure_preserves_stderr_and_exact_exit_code(tmp_path):
    runner = runpy.run_path(str(ROOT / "scripts/smoke-package.py"))["run"]
    report = {"processes": []}
    with pytest.raises(subprocess.CalledProcessError) as failure:
        runner([sys.executable, "-c", "import sys;sys.stderr.write('deliberate failure');sys.exit(23)"],
               "failure", tmp_path, report)
    assert failure.value.returncode == report["processes"][0]["returncode"] == 23
    assert (tmp_path / "failure.stderr.log").read_text() == "deliberate failure"


def test_resource_map_and_freezer_destination_agree():
    namespace = runpy.run_path(str(ROOT / "scripts/freeze-worker.py"))
    command = namespace["build_command"](ROOT)
    config = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text())
    assert config["bundle"]["resources"]["../build/worker/paperwork-worker/"] == "worker/"
    assert command[command.index("--distpath") + 1] == str(ROOT / "build/worker")
    assert command[command.index("--name") + 1] == "paperwork-worker"
    assert "--onedir" in command


def test_freeze_rejects_worker_protocol_failure_even_with_zero_exit(monkeypatch):
    """A successful process exit is not a successful worker health check."""
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
            "ok": False, "error": {"message": "PDF engine unavailable"}
        }), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", [str(ROOT / "scripts/freeze-worker.py")])
    with pytest.raises(ValueError, match="health|self-test"):
        runpy.run_path(str(ROOT / "scripts/freeze-worker.py"), run_name="__main__")
