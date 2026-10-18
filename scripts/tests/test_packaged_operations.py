"""Artifact acceptance: real frozen-worker coverage is opt-in, never a model mock."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_health_only_zero_exit_is_not_operation_acceptance(tmp_path, monkeypatch):
    smoke = runpy.run_path(str(ROOT / "scripts/smoke-package.py"))
    test_worker = smoke["test_worker"]
    monkeypatch.setitem(test_worker.__globals__, "validate_health", lambda value: {})
    monkeypatch.setitem(test_worker.__globals__, "verify_licenses", lambda worker: {})
    health = {"ok": True, "result": {"outputs": [], "details": {"status": "ok"}}}
    monkeypatch.setattr(subprocess, "run", lambda command, **kw:
                        subprocess.CompletedProcess(command, 0, json.dumps(health), ""))
    report = {"processes": []}
    with pytest.raises(ValueError, match="builtin operation acceptance"):
        test_worker(Path("/synthetic-worker"), tmp_path, report)
    assert report["builtin_operations"]["success"] is False
    assert report["builtin_operations"]["failed"] > 0


@pytest.mark.parametrize("response", [
    {"ok": False, "error": {"message": "missing bundled module"}},
    {"ok": True, "result": {"outputs": [], "details": {}}},
])
def test_empty_or_error_result_with_zero_exit_fails_artifact_checks(tmp_path, monkeypatch, response):
    harness = runpy.run_path(str(ROOT / "scripts/smoke_operations.py"))
    monkeypatch.setattr(subprocess, "run", lambda command, **kw:
                        subprocess.CompletedProcess(command, 0, json.dumps(response), "diagnostic"))
    report = {"processes": []}
    with pytest.raises(ValueError, match="builtin operation acceptance"):
        harness["exercise_builtin_operations"](Path("/synthetic-worker"), tmp_path, report)
    summary = report["builtin_operations"]
    assert summary["checks_count"] == summary["failed"] == 22
    assert summary["passed"] == 0
    assert all(item["status"] == "excluded" for item in summary["excluded"])
    assert {item["returncode"] for item in report["processes"]} == {0}
    root = Path(summary["root"])
    assert json.loads((root / "results.json").read_text()) == summary
    assert len(list(root.glob("*/stdout.log"))) == 22
    assert len(list(root.glob("*/stderr.log"))) == 22


def test_packaged_worker_environment_excludes_host_runtime_and_library_injection(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/host/python")
    monkeypatch.setenv("VIRTUAL_ENV", "/host/venv")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/host/libraries")
    monkeypatch.setenv("LD_PRELOAD", "/host/injected.so")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/host/libraries")
    monkeypatch.setenv("PATH", "/host/python/bin:/host/office/bin")
    harness = runpy.run_path(str(ROOT / "scripts/smoke_operations.py"))
    env = harness["isolated_environment"]()
    assert not {"PYTHONPATH", "VIRTUAL_ENV", "LD_LIBRARY_PATH", "LD_PRELOAD", "DYLD_LIBRARY_PATH"}.intersection(env)
    assert env["PATH"] == (str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32") if os.name == "nt" else "")


@pytest.mark.parametrize("format", ["docx", "xlsx", "pptx", "png", "jpeg", "txt", "csv", "html"])
def test_nonempty_garbage_is_not_an_export_artifact(tmp_path, format):
    harness = runpy.run_path(str(ROOT / "scripts/smoke_operations.py"))
    path = tmp_path / ("invalid." + format)
    path.write_bytes(b"not a real exported document")
    with pytest.raises((ValueError, OSError, zipfile.BadZipFile)):
        harness["validate_export"](path, format)


def test_output_outside_fresh_job_fails_even_with_zero_exit(tmp_path, monkeypatch):
    harness = runpy.run_path(str(ROOT / "scripts/smoke_operations.py"))
    outside = tmp_path / "outside.txt"
    outside.write_text("Original invoice DRAFT")
    response = {"ok": True, "result": {"outputs": [{"path": str(outside), "name": outside.name,
                                                    "mime": "text/plain"}], "details": {}}}
    monkeypatch.setattr(subprocess, "run", lambda command, **kw:
                        subprocess.CompletedProcess(command, 0, json.dumps(response), ""))
    entry = {"name": "escape"}
    with pytest.raises(ValueError, match="escaped job"):
        harness["invoke_worker"](Path("/synthetic-worker"), "convert_from_pdf", [], {}, tmp_path,
                                 entry, {"processes": []})
    assert outside.read_text() == "Original invoice DRAFT"


def test_actual_frozen_worker_builtin_artifacts(tmp_path):
    """Opt in: PACKAGED_WORKER=/absolute/frozen-worker; no source-worker fallback."""
    value = os.environ.get("PACKAGED_WORKER")
    if not value:
        pytest.skip("Set PACKAGED_WORKER to an actual frozen artifact")
    worker = Path(value).resolve(strict=True)
    harness = runpy.run_path(str(ROOT / "scripts/smoke_operations.py"))
    report = {"processes": []}
    harness["exercise_builtin_operations"](worker, tmp_path, report)
    summary = report["builtin_operations"]
    assert summary["success"] is True
    assert summary["checks_count"] == summary["passed"] == 22
    assert summary["failed"] == 0
    assert len(summary["excluded"]) == 7
