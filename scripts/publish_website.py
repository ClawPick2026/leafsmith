#!/usr/bin/env python3
"""Publish web/ to the existing Lakebed deploy behind https://paperwork.lakebed.app.

This updates the browser edition only. It never creates a desktop release, tag
or GitHub release, and it never commits or pushes.

Order: git preflight -> unit tests and both builds -> browser acceptance against
a fresh local Lakebed dev server -> baseline checks of the live site -> deploy ->
wait until the live site serves the bundle that was just built -> browser
acceptance against the live site. A local failure stops before deploying.

    python3 scripts/publish_website.py --dry-run
    python3 scripts/publish_website.py
    python3 scripts/publish_website.py --allow-uncommitted   # deploy working-tree changes

POSIX only (process groups). Browser suites use the task-local .test-venv and
web/tests/browser-env.json; nothing is installed globally.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_ID = "dep_yefw3xsfKf5oAixk"
PUBLIC_URL = "https://paperwork.lakebed.app"
LAKEBED = ["npx", "--yes", "lakebed@0.0.40"]
ARTIFACT_LIMIT = 1024 * 1024  # Lakebed's artifact size limit
WAIT_SECONDS, WAIT_INTERVAL = 300, 5
STEP_TIMEOUT = 1800

_SHA = r"([0-9a-f]{64})"


class PublishError(Exception):
    pass


def client_hash_from_build(output: str) -> str:
    match = re.search(r"^Client:\s+sha256:" + _SHA, output, re.M)
    if not match:
        raise PublishError("Lakebed build output did not include a client hash.")
    return match.group(1)


def client_hash_from_html(html: str) -> str | None:
    match = re.search(r"client\.js\?v=sha256(?:%3A|:)" + _SHA, html, re.I)
    return match.group(1) if match else None


def redact(text: str) -> str:
    text = re.sub(r"tok_[A-Za-z0-9]+", "tok_[redacted]", text)
    return re.sub(r'("(?:claimToken|token)"\s*:\s*)"[^"]*"', r'\1"[redacted]"', text)


def check_identity(root: Path) -> None:
    path = root / "web" / "lakebed.json"
    try:
        deploy_id = json.loads(path.read_text()).get("deployId")
    except (OSError, ValueError):
        raise PublishError(f"Cannot read {path}; it pins the live deploy {DEPLOY_ID}.") from None
    if deploy_id != DEPLOY_ID:
        raise PublishError(f"web/lakebed.json names {deploy_id!r}, not the live deploy {DEPLOY_ID}. "
                           "Publishing would not update paperwork.lakebed.app.")


def preflight(branch: str, behind: int, dirty: list[str], allow_uncommitted: bool) -> list[str]:
    if branch != "main":
        raise PublishError(f"Publish from main, not {branch!r}.")
    if behind:
        raise PublishError(f"Local main is {behind} commit(s) behind origin/main. Pull first.")
    if dirty and not allow_uncommitted:
        raise PublishError("Uncommitted changes under web/: " + ", ".join(dirty)
                           + ". Commit them, or pass --allow-uncommitted to deploy the working tree.")
    if dirty:
        return ["Deploying uncommitted web/ changes; the live site will not match any commit: " + ", ".join(dirty)]
    return []


def check_artifact(path: Path) -> int:
    size = path.stat().st_size
    if size > ARTIFACT_LIMIT:
        raise PublishError(f"{path.name} is {size} bytes, over Lakebed's 1 MiB artifact limit.")
    return size


def browser_suite(url: str, python: str, downloads: bool = False) -> list[tuple[str, list[str], dict]]:
    """Each web/tests script takes its target URL either as an argument or as PAPERWORK_URL."""
    env = {"PAPERWORK_URL": url}
    steps = [
        ("discovery_http", [python, "web/tests/discovery_http.py"], env),
        ("test_shell", [python, "web/tests/test_shell.py"], env),
        ("seo_browser", [python, "web/tests/seo_browser.py", url, "all"], {}),
        ("e2e", [python, "web/tests/e2e.py", url], {}),
        ("review_regressions", [python, "web/tests/review_regressions.py", url], {}),
        ("ui_polish", [python, "web/tests/ui_polish.py"], env),
        ("theme_browser", [python, "web/tests/theme_browser.py", url, "web"], {}),
        ("crop_preview", [python, "web/tests/crop_preview.py", url], {}),
    ]
    if downloads:
        # Downloads both desktop packages (~170 MB) through the live buttons and checks their hashes.
        steps.append(("desktop_download", [python, "web/tests/desktop_download.py"], env))
    return steps


def _dirty(porcelain: str) -> list[str]:
    paths = []
    for line in porcelain.splitlines():
        if len(line) > 3:
            paths.append(line[3:].split(" -> ")[-1].strip('"'))
    return paths


def publish(options: dict, runner, root: Path = ROOT) -> dict:
    record = {"started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
              "url": options["url"], "deployed": False, "steps": [], "warnings": []}
    deployed = False

    def step(name, argv, env=None, target="local", required=True):
        code, output = runner.run(list(argv), env=env)
        record["steps"].append({"name": name, "target": target, "code": code})
        if code and required:
            if deployed:
                raise PublishError(f"{name} failed against {target} after deploying. The live site is already updated; "
                                   "fix the problem and publish again, or redeploy a known-good version.")
            raise PublishError(f"{name} failed ({target}). Nothing was deployed.")
        return code, output

    check_identity(root)
    branch = step("git branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"])[1].strip()
    step("git fetch", ["git", "fetch", "--quiet", "origin", "main"])
    behind = int(step("git behind", ["git", "rev-list", "--count", "HEAD..origin/main"])[1].strip() or 0)
    dirty = _dirty(step("git status", ["git", "status", "--porcelain", "--untracked-files=all", "--", "web"])[1])
    record["warnings"] += preflight(branch, behind, dirty, options["allow_uncommitted"])
    record["head"] = step("git head", ["git", "rev-parse", "HEAD"])[1].strip()
    record["uncommitted"] = dirty

    step("npm test", ["npm", "test"])
    step("npm run build", ["npm", "run", "build"])
    client = client_hash_from_build(step("npm run web:build", ["npm", "run", "web:build"])[1])
    record["client"] = client
    record["artifact_bytes"] = check_artifact(root / ".lakebed" / "artifacts" / "web.claimed.json")

    if options["local_browser"]:
        with runner.serve_web() as local:
            for name, argv, env in browser_suite(local, options["python"]):
                step(name, argv, env, target=local)

    if options["dry_run"]:
        return _save(record, root)

    url = options["url"]
    for name, argv, env in browser_suite(url, options["python"])[:3]:
        code, _ = step(name, argv, env, target=url + " (before deploy)", required=False)
        if code:
            record["warnings"].append(f"{name} already failed against the live site before deploying.")

    code, output = runner.run(LAKEBED + ["deploy", "web"])
    record["steps"].append({"name": "lakebed deploy", "target": url, "code": code})
    if code:
        raise PublishError("lakebed deploy failed; check its output above. The live site may be unchanged.")
    deployed = True
    record["deployed"] = True
    check_identity(root)

    for attempt in range(WAIT_SECONDS // WAIT_INTERVAL + 1):
        served = client_hash_from_html(runner.fetch(f"{url}/?publish-check={attempt}"))
        if served == client:
            break
        runner.sleep(WAIT_INTERVAL)
    else:
        raise PublishError(f"Deployed, but {url} still serves client {served} instead of {client} "
                           f"after {WAIT_SECONDS} s. Check the deploy with 'npx --yes lakebed@0.0.40 inspect {DEPLOY_ID}'.")

    for name, argv, env in browser_suite(url, options["python"], downloads=options["downloads"]):
        step(name, argv, env, target=url)
    return _save(record, root)


def _save(record: dict, root: Path) -> dict:
    folder = root / "tests" / "artifacts" / "publish"  # ignored by git
    folder.mkdir(parents=True, exist_ok=True)
    stamp = record["started"].replace(":", "").replace("+0000", "Z")
    (folder / f"{stamp}.json").write_text(redact(json.dumps(record, indent=2)) + "\n")
    return record


class Runner:
    def __init__(self, root: Path = ROOT):
        self.root = root

    def run(self, argv, *, env=None):
        print("$ " + " ".join(argv), flush=True)
        process = subprocess.Popen(argv, cwd=self.root, env={**os.environ, **(env or {})}, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        timer = threading.Timer(STEP_TIMEOUT, lambda: _kill(process))
        timer.start()
        lines = []
        try:
            for line in process.stdout:
                lines.append(line)
                sys.stdout.write(redact(line))
            return process.wait(), "".join(lines)
        finally:
            timer.cancel()

    def fetch(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": "paperwork-publish-check", "Cache-Control": "no-cache"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read(2 * 1024 * 1024).decode("utf-8", "replace")
        except OSError:
            return ""

    def sleep(self, seconds):
        time.sleep(seconds)

    @contextlib.contextmanager
    def serve_web(self):
        """A fresh dev server on a copy of web/, so no stale bundle or repo .lakebed state is involved."""
        with tempfile.TemporaryDirectory(prefix="paperwork-publish-") as tmp:
            copy = Path(tmp) / "web"
            shutil.copytree(self.root / "web", copy, ignore=shutil.ignore_patterns(".lakebed", "tests", "docs"))
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            url = f"http://127.0.0.1:{port}"
            log = open(Path(tmp) / "dev.log", "w")
            print(f"$ {' '.join(LAKEBED)} dev <copy of web> --host 127.0.0.1 --port {port}", flush=True)
            process = subprocess.Popen(LAKEBED + ["dev", str(copy), "--host", "127.0.0.1", "--port", str(port)],
                                       cwd=self.root, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 240
                while client_hash_from_html(self.fetch(url + "/")) is None:
                    if process.poll() is not None or time.monotonic() > deadline:
                        log.flush()
                        tail = (Path(tmp) / "dev.log").read_text(errors="replace")[-2000:]
                        raise PublishError("The local Lakebed dev server did not start. Nothing was deployed.\n" + redact(tail))
                    time.sleep(2)
                yield url
            finally:
                _kill(process)
                log.close()


def _kill(process):
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Publish web/ to paperwork.lakebed.app (website only, no desktop release).")
    parser.add_argument("--dry-run", action="store_true", help="run every check but do not deploy")
    parser.add_argument("--allow-uncommitted", action="store_true", help="deploy uncommitted web/ changes")
    parser.add_argument("--skip-local-browser", action="store_true", help="skip browser acceptance on a local dev server")
    parser.add_argument("--verify-downloads", action="store_true", help="also download both desktop packages through the live site")
    parser.add_argument("--python", default=str(ROOT / ".test-venv" / "bin" / "python"), help="interpreter with Playwright")
    parser.add_argument("--url", default=PUBLIC_URL)
    args = parser.parse_args(argv)
    if not Path(args.python).exists():
        print(f"error: {args.python} not found; it needs Playwright for the browser suites.", file=sys.stderr)
        return 2
    options = {"dry_run": args.dry_run, "allow_uncommitted": args.allow_uncommitted,
               "local_browser": not args.skip_local_browser, "downloads": args.verify_downloads,
               "python": args.python, "url": args.url.rstrip("/")}
    try:
        record = publish(options, Runner())
    except PublishError as error:
        print(f"\nPublish stopped: {error}", file=sys.stderr)
        return 1
    for warning in record["warnings"]:
        print(f"warning: {warning}")
    print(f"\n{'Dry run complete' if options['dry_run'] else 'Published'}: client sha256:{record['client']} "
          f"from {record['head'][:12]}{' plus uncommitted changes' if record['uncommitted'] else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
