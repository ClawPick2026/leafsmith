#!/usr/bin/env python3
"""Release a new desktop version: bump, tag, wait for CI, then publish download links.

    python3 scripts/release.py rc                # v0.1.0-rc.2 -> v0.1.0-rc.3
    python3 scripts/release.py final             # v0.1.0-rc.3 -> v0.1.0
    python3 scripts/release.py patch             # 0.1.0 -> 0.1.1 (minor, major likewise)
    python3 scripts/release.py minor --rc        # 0.1.0 -> 0.2.0-rc.1
    python3 scripts/release.py --version 0.3.0   # explicit
    python3 scripts/release.py rc --dry-run      # show the plan, change nothing
    python3 scripts/release.py --links-only v0.1.0-rc.3

The app manifests hold X.Y.Z; release candidates are tags vX.Y.Z-rc.N of that
version, which is what the "Desktop packages" workflow's tag check accepts.

Steps: preflight (main, clean, up to date, gh signed in, tag unused) -> confirm ->
npm test and build -> bump package.json, package-lock.json, Cargo.toml and
tauri.conf.json, write docs/releases/<tag>.md if missing -> commit and push main
-> wait for that commit's CI build -> push an annotated tag (CI publishes the
already-verified packages) -> wait for the release -> verify assets against the
GitHub digests and SHA256SUMS -> update README and website download links ->
commit, push and publish the website with scripts/publish_website.py.

Download links change only after the release assets exist and verify, as the
project rules require. Other workflows that react to a published release (for
example AUR packaging) run on their own.
"""
from __future__ import annotations

import argparse
import dataclasses
import functools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
REPO = "ClawPick2026/paperwork-desktop"
RELEASE_URL = f"https://github.com/{REPO}/releases/tag/"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/download/"
ASSETS = {"Windows": "Paperwork_{base}_x64-setup.exe", "Linux": "Paperwork_{base}_amd64.AppImage"}
SUMS = ("SHA256SUMS-windows-x86_64.txt", "SHA256SUMS-linux-x86_64.txt")
LINK_FILES = ("README.md", "web/shared/desktop.ts", "web/tests/desktop_download.py")
_VERSION = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-rc\.([1-9]\d*))?")


class ReleaseError(Exception):
    pass


@functools.total_ordering
@dataclasses.dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    rc: int | None = None

    @property
    def base(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def tag(self) -> str:
        return "v" + str(self)

    @property
    def label(self) -> str:
        return self.base + (f" RC{self.rc}" if self.rc else "")

    def __str__(self) -> str:
        return self.base + (f"-rc.{self.rc}" if self.rc else "")

    def __lt__(self, other: "Version") -> bool:
        def key(v):
            return (v.major, v.minor, v.patch, v.rc is None, v.rc or 0)
        return key(self) < key(other)


def parse_version(text: str) -> Version:
    match = _VERSION.fullmatch(text)
    if not match:
        raise ReleaseError(f"{text!r} is not a version like 1.2.3 or 1.2.3-rc.4.")
    major, minor, patch, rc = match.groups()
    return Version(int(major), int(minor), int(patch), int(rc) if rc else None)


def latest_tag(tags: list[str]) -> Version | None:
    versions = [parse_version(t) for t in tags if t.startswith("v") and _VERSION.fullmatch(t)]
    return max(versions, default=None)


def next_version(app_base: str, latest: Version | None, bump: str | None, rc: bool = False,
                 explicit: str | None = None) -> tuple[Version, list[str]]:
    app = parse_version(app_base)
    if app.rc:
        raise ReleaseError("tauri.conf.json must hold X.Y.Z; release candidates live only in tags.")
    warnings = []
    unreleased_rc = latest is not None and latest.base == app.base and latest.rc is not None
    if explicit:
        new = parse_version(explicit)
    elif bump == "rc":
        if latest is not None and latest.base == app.base and latest.rc is None:
            raise ReleaseError(f"v{app.base} is already released; use patch, minor or major with --rc.")
        new = dataclasses.replace(app, rc=latest.rc + 1 if unreleased_rc else 1)
    elif bump == "final":
        if not unreleased_rc:
            raise ReleaseError(f"There is no release candidate of {app.base} to finalize.")
        new = app
    elif bump in ("patch", "minor", "major"):
        parts = {"major": (app.major + 1, 0, 0), "minor": (app.major, app.minor + 1, 0),
                 "patch": (app.major, app.minor, app.patch + 1)}[bump]
        new = Version(*parts, 1 if rc else None)
        if unreleased_rc:
            warnings.append(f"v{app.base} was never released as final ({latest.tag} is the newest tag); this skips it.")
    else:
        raise ReleaseError("Choose major, minor, patch, rc or final, or pass --version.")
    if latest is not None and not new > latest:
        raise ReleaseError(f"{new.tag} is not newer than the latest tag {latest.tag}.")
    return new, warnings


def _replace_first(text: str, pattern: str, value: str, where: str) -> str:
    updated, count = re.subn(pattern, lambda m: m.group(1) + value + m.group(3), text, count=1, flags=re.S | re.M)
    if not count:
        raise ReleaseError(f"Cannot find the version in {where}.")
    return updated


def set_app_version(root: Path, base: str) -> list[Path]:
    version = r'([^"]+)'
    edits = {
        "package.json": [r'("version": ")' + version + '(")'],
        "package-lock.json": [r'("version": ")' + version + '(")',
                              r'("packages": \{\s*"": \{[^{}]*?"version": ")' + version + '(")'],
        "src-tauri/Cargo.toml": [r'^(version = ")' + version + '(")'],
        "src-tauri/tauri.conf.json": [r'("version": ")' + version + '(")'],
    }
    changed = []
    for name, patterns in edits.items():
        path = root / name
        text = original = path.read_text()
        for pattern in patterns:
            text = _replace_first(text, pattern, base, name)
        if text != original:
            path.write_text(text)
            changed.append(path)
    lock = json.loads((root / "package-lock.json").read_text())
    found = {json.loads((root / "package.json").read_text())["version"], lock["version"], lock["packages"][""]["version"],
             json.loads((root / "src-tauri/tauri.conf.json").read_text())["version"],
             tomllib.loads((root / "src-tauri/Cargo.toml").read_text())["package"]["version"]}
    if found != {base}:
        raise ReleaseError(f"Version update left inconsistent manifests: {sorted(found)}.")
    return changed


def release_notes(version: Version, previous: str | None, commits: list[str]) -> str:
    rc = version.rc is not None
    base = version.base
    changes = [c for c in commits if not c.startswith("chore(release):")
               and not re.fullmatch(r"docs: publish v\S+ download links", c)]
    lines = [f"# Paperwork {version.label} — Windows and Linux" + (" preview" if rc else ""), ""]
    if rc:
        lines += ["**Release candidate for testing, not the finished release.**", ""]
    lines += [
        "## Downloads", "",
        f"- `Paperwork_{base}_x64-setup.exe`: Windows x86_64 NSIS installer.",
        f"- `Paperwork_{base}_amd64.AppImage`: Linux x86_64. Built on Ubuntu 22.04; it needs glibc 2.35 or later. "
        "Make it executable (`chmod +x`) and run it.",
        "- `Paperwork-linux-corresponding-sources.zip`: the exact Ubuntu source packages for the Linux libraries in the "
        "AppImage's dependency set. Keep it with the AppImage if you redistribute it.",
        "- `Paperwork-windows-x86_64-third-party-notices.zip`, `Paperwork-linux-x86_64-third-party-notices.zip`: "
        "the license notices that also ship inside each package.",
        "- `SHA256SUMS-windows-x86_64.txt`, `SHA256SUMS-linux-x86_64.txt`: verify downloads before running them.", "",
        "**Both packages are unsigned.** Windows SmartScreen may show an unrecognized-publisher warning. "
        "Use copies of non-sensitive documents and review every output.", "",
        "Application code is MIT. Bundled libraries keep their own licenses. Optional engines and models are "
        "separately licensed and require consent before download.", "",
        f"## Changes since {previous}" if previous else "## Changes", "",
        *([f"- {c}" for c in changes] or ["- No code changes recorded."]), "",
        "## What the workflow checked", "",
        "On both platforms the `Desktop packages` workflow ran the frontend tests and production build, the native "
        "security and application crate tests, the Python worker and packaging regression tests, the frozen worker "
        "with no Python on `PATH`, the packaged native host's worker self-test and the packaged document-operation "
        "checks, which independently read the generated files. Windows: silent installation of this installer into a "
        "fresh directory first. Linux: the AppImage extracted without FUSE and run under Xvfb, plus the post-bundle "
        "library license and source audit.", "",
        "## Not tested", "",
        "- Interactive use on either platform: GUI, file pickers, save dialogs, desktop integration and uninstall.",
        "- Linux distributions other than the Ubuntu 22.04 build runner.",
        "- Optional OCR, Office, FFmpeg and AI engine/model packs. They are separate downloads with their own release status.",
        "",
        "Report problems in this repository's Issues. Do not attach private documents, passwords or API keys.", "",
    ]
    return "\n".join(lines)


def verify_assets(version: Version, data: dict, sums_text: str) -> dict:
    tag = version.tag
    if data.get("tag_name") != tag:
        raise ReleaseError(f"GitHub returned release {data.get('tag_name')!r}, not {tag}.")
    if data.get("draft"):
        raise ReleaseError(f"Release {tag} is still a draft.")
    if bool(data.get("prerelease")) != (version.rc is not None):
        raise ReleaseError(f"Release {tag} has the wrong pre-release flag.")
    sums = {}
    for line in sums_text.splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.strip().lstrip("*")] = digest.lower()
    assets = {asset["name"]: asset for asset in data.get("assets", [])}
    info = {}
    for platform, pattern in ASSETS.items():
        name = pattern.format(base=version.base)
        asset = assets.get(name)
        if asset is None:
            raise ReleaseError(f"Release {tag} is missing {name}.")
        url = DOWNLOAD_URL + tag + "/" + name
        if asset.get("browser_download_url") != url:
            raise ReleaseError(f"{name} has an unexpected download URL: {asset.get('browser_download_url')}.")
        digest = str(asset.get("digest", "")).removeprefix("sha256:").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or sums.get(name) != digest:
            raise ReleaseError(f"The GitHub SHA-256 digest of {name} does not match the release's SHA256SUMS.")
        info[platform] = {"name": name, "sha256": digest, "bytes": asset["size"], "url": url}
    return info


def update_links(root: Path, version: Version, info: dict) -> list[Path]:
    desktop = (root / "web/shared/desktop.ts").read_text()
    match = re.search(r"version: '([^']+)'", desktop)
    if not match:
        raise ReleaseError("Cannot find the published version in web/shared/desktop.ts.")
    old = parse_version(match.group(1))
    if old == version:
        return []
    replacements = [(re.escape(old.tag) + r"(?![\w.])", version.tag),
                    (re.escape(f"'{old}'"), f"'{version}'"),
                    (re.escape(f"[{old.label}]("), f"[{version.label}](")]
    for platform, pattern in ASSETS.items():
        block = re.search(r"platform: '" + platform + r"',.*?sha256: '([0-9a-f]{64})',\s*bytes: (\d+)", desktop, re.S)
        if not block:
            raise ReleaseError(f"Cannot find the {platform} package in web/shared/desktop.ts.")
        new = info[platform]
        replacements += [(re.escape(pattern.format(base=old.base)), new["name"]),
                         (block.group(1), new["sha256"]),
                         (r"(platform: '" + platform + r"',.*?bytes: )" + block.group(2), r"\g<1>" + str(new["bytes"]))]
    changed = []
    for name in LINK_FILES:
        path = root / name
        text = original = path.read_text()
        for pattern, value in replacements:
            text = re.sub(pattern, value, text, flags=re.S)
        if old.tag in text:
            raise ReleaseError(f"{name} still mentions {old.tag} after updating the links.")
        if text != original:
            path.write_text(text)
            changed.append(path)
    return changed


def _check(runner, argv, failure):
    code, output = runner.run(argv)
    if code:
        raise ReleaseError(failure)
    return output


def _preflight(runner):
    if _check(runner, ["git", "rev-parse", "--abbrev-ref", "HEAD"], "git failed.").strip() != "main":
        raise ReleaseError("Release from main.")
    dirty = _check(runner, ["git", "status", "--porcelain", "--untracked-files=all"], "git status failed.")
    if dirty.strip():
        files = ", ".join(line[3:] for line in dirty.splitlines() if line.strip())
        raise ReleaseError("Releases are made from committed code; uncommitted changes: " + files)
    _check(runner, ["git", "fetch", "--quiet", "--tags", "origin", "main"], "git fetch failed.")
    behind = int(_check(runner, ["git", "rev-list", "--count", "HEAD..origin/main"], "git rev-list failed.").strip() or 0)
    if behind:
        raise ReleaseError(f"Local main is {behind} commit(s) behind origin/main. Pull first.")
    _check(runner, ["gh", "auth", "status"], "The GitHub CLI is not signed in (run 'gh auth login').")


def _wait_ci(runner, sha: str, ref: str) -> bool:
    for _ in range(60):
        out = _check(runner, ["gh", "run", "list", "--repo", REPO, "--workflow", "build.yml", "--commit", sha,
                              "--branch", ref, "--event", "push", "--json", "databaseId,status,conclusion",
                              "--limit", "1"], "gh run list failed.")
        runs = json.loads(out or "[]")
        if runs:
            break
        runner.sleep(10)
    else:
        raise ReleaseError(f"No Desktop packages run started for {ref} at {sha[:12]} within 10 minutes.")
    code, _ = runner.run(["gh", "run", "watch", str(runs[0]["databaseId"]), "--repo", REPO, "--exit-status", "--interval", "30"])
    return code == 0


def release(options: dict, runner, root: Path = ROOT) -> dict:
    _preflight(runner)
    tags = _check(runner, ["git", "tag", "--list", "v*"], "git tag failed.").split()
    latest = latest_tag(tags)
    app_base = json.loads((root / "src-tauri/tauri.conf.json").read_text())["version"]
    new, warnings = next_version(app_base, latest, options["bump"], options["rc"], options["version"])
    if new.tag in tags or _check(runner, ["git", "ls-remote", "--tags", "origin", f"refs/tags/{new.tag}"], "git ls-remote failed.").strip():
        raise ReleaseError(f"Tag {new.tag} already exists.")

    notes_path = root / "docs" / "releases" / f"{new.tag}.md"
    if options["notes"]:
        notes, source = Path(options["notes"]).read_text(), options["notes"]
    elif notes_path.exists():
        notes, source = notes_path.read_text(), "existing " + str(notes_path.relative_to(root))
    else:
        log = ["git", "log", "--no-merges", "--format=%s"] + ([f"{latest.tag}..HEAD"] if latest else [])
        commits = _check(runner, log, "git log failed.").splitlines()
        notes, source = release_notes(new, latest.tag if latest else None, commits), "generated"
    if not notes.startswith("# "):
        raise ReleaseError("Release notes must start with a '# ' title line.")

    plan = "\n".join([
        f"Release {new.tag} (latest tag: {latest.tag if latest else 'none'})",
        f"App version: {app_base}" + (f" -> {new.base}" if new.base != app_base else " (unchanged)"),
        f"Release notes ({source}): docs/releases/{new.tag}.md",
        *[f"warning: {w}" for w in warnings],
        "Steps: npm test/build, commit, push main, wait for CI, push tag, wait for the release, "
        "verify assets, update download links, push, publish the website.",
        "", notes])
    record = {"version": str(new), "tag": new.tag, "warnings": warnings, "plan": plan}
    if options["dry_run"]:
        return record
    if not options["yes"] and not runner.confirm(plan):
        raise ReleaseError("Release cancelled; nothing was changed.")

    if not options["skip_checks"]:
        _check(runner, ["npm", "test"], "npm test failed; nothing was changed.")
        _check(runner, ["npm", "run", "build"], "npm run build failed; nothing was changed.")
    changed = set_app_version(root, new.base)
    if not notes_path.exists() or options["notes"]:
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text(notes)
        changed.append(notes_path)
    if changed:
        _check(runner, ["git", "add", "--"] + [str(p.relative_to(root)) for p in changed], "git add failed.")
        _check(runner, ["git", "commit", "-m", f"chore(release): {new.tag}"], "git commit failed.")
    sha = _check(runner, ["git", "rev-parse", "HEAD"], "git rev-parse failed.").strip()
    _check(runner, ["git", "push", "origin", "main"], "git push failed; nothing was tagged.")
    if not options["no_wait"] and not _wait_ci(runner, sha, "main"):
        raise ReleaseError(f"The main build for {sha[:12]} failed, so {new.tag} was not tagged. Fix main, "
                           f"then rerun: python3 scripts/release.py --version {new}")
    _check(runner, ["git", "tag", "-a", new.tag, "-m", f"Paperwork {new.label}", sha], "git tag failed.")
    _check(runner, ["git", "push", "origin", new.tag], f"Pushing {new.tag} failed; push it manually.")
    if options["no_wait"]:
        record["stopped"] = f"Tag pushed. When the release exists, run: python3 scripts/release.py --links-only {new.tag}"
        return record
    if not _wait_ci(runner, sha, new.tag):
        raise ReleaseError(f"The release run for {new.tag} failed. See docs/BUILDING.md 'Publish a release' to retry.")
    publish_links(new, runner, root)
    return record


def publish_links(version: Version, runner, root: Path = ROOT) -> list[Path]:
    tag = version.tag
    data = json.loads(_check(runner, ["gh", "api", f"repos/{REPO}/releases/tags/{tag}"], f"Release {tag} not found."))
    sums_text = "".join(_check(runner, ["gh", "release", "download", tag, "--repo", REPO, "--pattern", name, "--output", "-"],
                               f"Cannot download {name}.") for name in SUMS)
    info = verify_assets(version, data, sums_text)
    changed = update_links(root, version, info)
    if changed:
        _check(runner, ["npm", "test"], "npm test failed after updating the download links; nothing was committed.")
        _check(runner, ["git", "add", "--"] + [str(p.relative_to(root)) for p in changed], "git add failed.")
        _check(runner, ["git", "commit", "-m", f"docs: publish {tag} download links"], "git commit failed.")
        _check(runner, ["git", "push", "origin", "main"], "git push failed.")
    _check(runner, ["python3", "scripts/publish_website.py", "--verify-downloads"],
           "The download links are pushed, but publishing the website failed. Rerun: "
           "python3 scripts/publish_website.py --verify-downloads")
    return changed


def links_only(tag: str, runner, root: Path = ROOT) -> list[Path]:
    version = parse_version(tag)
    _preflight(runner)
    return publish_links(version, runner, root)


class Runner:
    def run(self, argv, *, env=None):
        print("$ " + " ".join(argv), flush=True)
        process = subprocess.Popen(argv, cwd=ROOT, env={**os.environ, **(env or {})}, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        lines = []
        for line in process.stdout:
            lines.append(line)
            sys.stdout.write(line)
        return process.wait(), "".join(lines)

    def confirm(self, text):
        print(text)
        try:
            return input("Proceed with this release? [y/N] ").strip().lower() == "y"
        except EOFError:
            return False

    def sleep(self, seconds):
        time.sleep(seconds)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Release a new Paperwork desktop version.")
    parser.add_argument("bump", nargs="?", choices=["major", "minor", "patch", "rc", "final"])
    parser.add_argument("--rc", action="store_true", help="start a release candidate of the bumped version")
    parser.add_argument("--version", help="explicit version, e.g. 0.2.0 or 0.2.0-rc.1")
    parser.add_argument("--notes", help="release notes file to use instead of generated notes")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and change nothing")
    parser.add_argument("--skip-checks", action="store_true", help="skip local npm test/build (CI still runs everything)")
    parser.add_argument("--no-wait", action="store_true", help="stop after pushing the tag")
    parser.add_argument("--links-only", metavar="TAG", help="verify an existing release and publish its download links")
    args = parser.parse_args(argv)
    try:
        if args.links_only:
            links_only(args.links_only, Runner())
            print(f"Download links for {args.links_only} are published.")
            return 0
        if not args.bump and not args.version:
            parser.error("choose major, minor, patch, rc or final, or pass --version")
        if args.rc and args.bump in ("rc", "final"):
            parser.error("--rc applies to major, minor and patch")
        record = release({"bump": args.bump, "rc": args.rc, "version": args.version, "notes": args.notes,
                          "yes": args.yes, "dry_run": args.dry_run, "skip_checks": args.skip_checks,
                          "no_wait": args.no_wait}, Runner())
    except ReleaseError as error:
        print(f"\nRelease stopped: {error}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(record["plan"])
        print("\nDry run: nothing was changed.")
    else:
        print(record.get("stopped") or f"Released {record['tag']}; download links and website are updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
