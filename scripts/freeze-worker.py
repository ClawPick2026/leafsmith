"""Freeze the onedir worker at the resource-map path in tauri.conf.json.

Run with the packaging venv's Python. The embedded runtime is shipped, not a
launcher for a user-installed Python. Optional engines/models are not included.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate_health(stdout: str) -> dict:
    """Do not accept an exit code or import-only check as a working PDF engine."""
    try:
        response = json.loads(stdout)
        result = response["result"]
        details = result["details"]
        if (response.get("ok") is not True or result.get("outputs") != []
                or details.get("status") != "ok"
                or type(details.get("form_pages")) is not int or details["form_pages"] < 1
                or type(details.get("form_fields")) is not int or details["form_fields"] < 1):
            raise ValueError("Invalid worker health self-test")
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError("Worker health self-test did not generate and independently read back a PDF form") from error
    return result


def build_command(root: Path = ROOT) -> list[str]:
    return [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "leafsmith-worker", "--distpath", str(root / "build/worker"),
        "--workpath", str(root / "build/pyinstaller"), "--specpath", str(root / "build"),
        "--paths", str(root / "worker"), "--hidden-import", "pdf_ops",
        # The worker is a batch JSON protocol, never an interactive Python REPL.
        # Ubuntu's optional readline extension would pull in GPL-only libreadline.
        "--exclude-module", "readline",
        "--hidden-import", "media_ops", "--collect-all", "pypdfium2",
        "--collect-all", "pypdfium2_raw", "--collect-data", "reportlab",
        "--collect-data", "docx",
        # Speaker-note templates use oxml/../templates: oxml must exist on disk,
        # not just inside PYZ, even though the XML templates are already data.
        "--collect-all", "pptx",
        str(root / "worker/main.py"),
    ]


def main() -> None:
    subprocess.run(build_command(), cwd=ROOT, check=True)
    bundle = ROOT / "build/worker/leafsmith-worker"
    worker = bundle / ("leafsmith-worker.exe" if os.name == "nt" else "leafsmith-worker")
    # Not used by Leafsmith; avoid redistributing GPL/test-font payloads at all.
    for pattern in ("DarkGarden*", "hb-test.ttf"):
        for path in (bundle / "_internal/reportlab/fonts").glob(pattern):
            if path.is_file():
                path.unlink()
    logs = ROOT / "build/logs"
    logs.mkdir(parents=True, exist_ok=True)
    # Prove this test cannot discover an external Python or optional engine.
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("PYTHON") and k.upper() != "VIRTUAL_ENV"}
    env["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32") if os.name == "nt" else ""
    completed = subprocess.run([str(worker)], input='{"operation":"health"}\n',
                               text=True, capture_output=True, timeout=120, env=env)
    (logs / "frozen-worker.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (logs / "frozen-worker.stderr.log").write_text(completed.stderr, encoding="utf-8")
    (logs / "frozen-worker.exitcode.txt").write_text(str(completed.returncode), encoding="utf-8")
    completed.check_returncode()
    result = validate_health(completed.stdout)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
