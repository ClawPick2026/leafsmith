"""Noninteractive package smoke. This is NOT an interactive desktop/OS test.

worker: run a frozen worker with no external runtime on PATH.
nsis: silently install only into a fresh temporary directory, then test the
installed native executable and its installed resource worker. Never invoke an
uninstaller or modify an existing install.
appimage: extract without FUSE and test AppRun/native resource resolution.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
validate_health = runpy.run_path(str(ROOT / "scripts/freeze-worker.py"))["validate_health"]


def clean_environment(no_path=False):
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("PYTHON") and k.upper() != "VIRTUAL_ENV"}
    if no_path:
        env["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32") if os.name == "nt" else ""
    else:
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                      if p and "python" not in p.lower() and ".venv" not in p.lower())
    return env


def run(command, label, logs, report, **kwargs):
    entry = {"label": label, "command": [str(p) for p in command], "returncode": None}
    report["processes"].append(entry)
    try:
        completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace",
                                   capture_output=True, timeout=180, **kwargs)
        stdout, stderr = completed.stdout, completed.stderr
        entry["returncode"] = completed.returncode
    except subprocess.TimeoutExpired as error:
        entry["timed_out"] = True
        stdout, stderr = error.stdout or b"", error.stderr or b""
        raise
    finally:
        for stream, value in (("stdout", locals().get("stdout", "")), ("stderr", locals().get("stderr", ""))):
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            (logs / (label + "." + stream + ".log")).write_text(value, encoding="utf-8")
    completed.check_returncode()
    return completed.stdout


def verify_licenses(worker):
    directory = worker.parent / "third-party-licenses"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if not manifest:
        raise ValueError("Packaged dependency notice manifest is empty")
    for name, expected in manifest.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError("Unsafe or missing packaged notice: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Packaged notice checksum mismatch: " + name)
    records = json.loads((directory / "python-packages.json").read_text(encoding="utf-8"))
    records = {r["name"].lower().replace("_", "-"): r for r in records}
    required = {"pypdfium2": "pdfium.txt", "pillow": "license", "cryptography": "license",
                "reportlab": "bitstream-vera-license.txt", "pyinstaller": "copying.txt"}
    for package, marker in required.items():
        notices = records.get(package, {}).get("notices", [])
        if not any(marker in name.lower() and name in manifest for name in notices):
            raise ValueError("Missing packaged dependency license: " + package)
    bootloader = records["pyinstaller"]["notices"]
    if not any("exception" in (directory / name).read_text(encoding="utf-8", errors="replace").lower()
               for name in bootloader):
        raise ValueError("Missing PyInstaller bootloader exception text")
    if "python-runtime/LICENSE.txt" not in manifest:
        raise ValueError("Missing embedded Python runtime license")
    return {"verified_notice_files": len(manifest)}


def test_worker(worker, logs, report, label="worker"):
    stdout = run([str(worker)], label, logs, report, input='{"operation":"health"}\n',
                 env=clean_environment(no_path=True))
    result = validate_health(stdout)
    report["worker_result"] = result
    report["licenses"] = verify_licenses(worker)


def test_native(app, worker, logs, report, env, prefix=None):
    stdout = run([*(prefix or []), str(app), "--worker-self-test"], "native-self-test", logs, report, env=env)
    # Native execute_worker returns the result, not the JSON-line envelope.
    result = validate_health(json.dumps({"ok": True, "result": json.loads(stdout)}))
    report["native_result"] = result
    test_worker(worker, logs, report, label="packaged-worker")


def smoke(kind, path, logs, report):
    if kind == "worker":
        test_worker(path, logs, report)
        return
    # Install/extract is scoped to this fresh directory, removed on completion.
    with tempfile.TemporaryDirectory(prefix="paperwork-package-", dir=logs) as scratch:
        scratch = Path(scratch)
        if kind == "nsis":
            if os.name != "nt":
                raise ValueError("NSIS smoke requires native Windows")
            destination = scratch / "installed"
            run([str(path), "/S", "/D=" + str(destination)], "nsis-install", logs, report,
                env=clean_environment())
            app = destination / "paperwork-desktop.exe"
            worker = destination / "worker/paperwork-worker.exe"
            if not app.is_file() or not worker.is_file():
                raise ValueError("NSIS payload is missing expected native app or resource worker")
            test_native(app, worker, logs, report, clean_environment())
        else:
            if sys.platform != "linux":
                raise ValueError("AppImage smoke requires native Linux")
            path.chmod(path.stat().st_mode | 0o111)
            run([str(path), "--appimage-extract"], "appimage-extract", logs, report,
                cwd=scratch, env=clean_environment())
            appdir = scratch / "squashfs-root"
            worker = appdir / "usr/lib/paperwork-desktop/worker/paperwork-worker"
            if not worker.is_file():
                found = [str(p.relative_to(appdir)) for p in appdir.rglob("paperwork-worker") if p.is_file()]
                raise ValueError("Unexpected AppImage worker resource layout: " + repr(found))
            env = clean_environment()
            env["APPDIR"] = str(appdir)
            prefix = ["xvfb-run", "-a"] if shutil.which("xvfb-run") and not env.get("DISPLAY") else []
            test_native(appdir / "AppRun", worker, logs, report, env, prefix)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=("worker", "nsis", "appimage"))
    parser.add_argument("--path", required=True, help="Path or glob resolving to exactly one package/worker")
    parser.add_argument("--logs", required=True, type=Path)
    args = parser.parse_args()
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    report = {"kind": args.kind, "success": False, "interactive_desktop_tested": False, "processes": []}
    try:
        matches = glob.glob(args.path)
        if len(matches) != 1 or not Path(matches[0]).is_file():
            raise ValueError("Expected exactly one package/worker, found: " + repr(matches))
        path = Path(matches[0]).resolve()
        report["artifact"] = str(path)
        report["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        smoke(args.kind, path, logs, report)
        report["success"] = True
    except Exception as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        (logs / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
