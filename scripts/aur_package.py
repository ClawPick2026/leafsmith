#!/usr/bin/env python3
"""Render, check and publish the leafsmith-bin AUR package.

AUR receives only the recipe (PKGBUILD, .SRCINFO, launcher, desktop entry),
rendered from packaging/aur/ for a published GitHub release; the AppImage
itself is downloaded from that release by makepkg. Commands, in CI order:

  fetch-release  CI host, GitHub token   pin the release AppImage's SHA-256
  plan           Arch container          render files and decide what to publish
  namcap         Arch container          fail on namcap errors not yet reviewed
  smoke          Arch container          run the installed app's headless checks
  publish        CI host, AUR SSH key    push the validated files to AUR master
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging" / "aur"
PKGNAME = "leafsmith-bin"
AUR_READ = f"https://aur.archlinux.org/{PKGNAME}.git"
AUR_PUSH = f"ssh://aur@aur.archlinux.org/{PKGNAME}.git"
# The app's names after the Paperwork -> Leafsmith rename, matching _appname,
# _product and _worker in PKGBUILD.in. Only releases built with them are packaged.
APP = "leafsmith"
PRODUCT = "Leafsmith"
BUNDLE = f"opt/{APP}/"
WORKER_PYTHON = BUNDLE + f"usr/lib/{PRODUCT}/worker/_internal/"
# Notice copies include .py files (packaging's SPDX `licenses` module); text, never run.
WORKER_NOTICES = BUNDLE + f"usr/lib/{PRODUCT}/worker/third-party-licenses/"
INSTALLED_WORKER = Path(f"/{BUNDLE}usr/lib/{PRODUCT}/worker/{APP}-worker")
LOCAL_SOURCES = (f"{APP}.sh", f"{APP}.desktop")
PACKAGE_FILES = ("PKGBUILD", ".SRCINFO", *LOCAL_SOURCES)
MAINTAINER = re.compile(r"\w[\w .'-]* <[\w.+@ -]+>")
REPOSITORY = "ClawPick2026/leafsmith"
SUMS_ASSET = "SHA256SUMS-linux-x86_64.txt"
# Tags published by the Desktop packages workflow: v1.2.3 or v1.2.3-rc.4.
TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?")
# Tauri names the bundle <productName>_<version>_amd64.AppImage.
APPIMAGE = re.compile(rf"{PRODUCT}_([0-9]+\.[0-9]+\.[0-9]+)_amd64\.AppImage")
SHA256 = re.compile(r"[0-9a-f]{64}")


def pkgver_from_tag(tag: str) -> str:
    """pacman orders 1.0rc2 < 1.0rc10 < 1.0 < 1.0.1; pkgver cannot contain '-'."""
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError(f"Unsupported release tag {tag!r}; expected v1.2.3 or v1.2.3-(alpha|beta|rc).N")
    major, minor, patch, label, number = match.groups()
    return f"{major}.{minor}.{patch}" + (f"{label}{number}" if label else "")


def release_artifact(release: dict, sums_text: str) -> dict:
    """Pin the release's AppImage. The SHA256SUMS list was written by the job
    that verified the AppImage; GitHub's recorded asset digest must agree."""
    tag = release.get("tag_name", "")
    pkgver = pkgver_from_tag(tag)
    if release.get("draft") is not False:
        raise ValueError(f"Release {tag} is a draft; only published releases are packaged")
    appimages = [a for a in release.get("assets", []) if a.get("name", "").endswith(".AppImage")]
    if len(appimages) != 1:
        raise ValueError(f"Release {tag} must have exactly one .AppImage asset, found {len(appimages)}")
    asset = appimages[0]
    match = APPIMAGE.fullmatch(asset["name"])
    if not match or match[1] != TAG.fullmatch(tag).expand(r"\1.\2.\3"):
        raise ValueError(f"AppImage {asset['name']!r} does not match release {tag}")
    if asset.get("browser_download_url") != f"https://github.com/{REPOSITORY}/releases/download/{tag}/{asset['name']}":
        raise ValueError(f"Unexpected AppImage download URL for {tag}")
    listed = {}
    for line in sums_text.splitlines():
        checksum, separator, name = line.partition("  ")
        if separator and SHA256.fullmatch(checksum):
            listed[name] = checksum
    sha256 = listed.get(asset["name"])
    if not sha256:
        raise ValueError(f"{asset['name']} is not in the checksum list {SUMS_ASSET} of {tag}")
    if asset.get("digest") not in (None, "sha256:" + sha256):
        raise ValueError(f"GitHub's asset digest for {asset['name']} disagrees with {SUMS_ASSET}")
    if type(asset.get("size")) is not int or asset["size"] <= 0:
        raise ValueError(f"{asset['name']} has no size")
    return {"tag": tag, "pkgver": pkgver, "prerelease": release.get("prerelease") is True,
            "release_url": release.get("html_url", ""), "appimage": asset["name"],
            "sha256": sha256, "size": asset["size"]}


def latest_appimage_release(releases: list[dict]) -> dict | None:
    """GitHub lists releases newest first; prereleases count, drafts do not.
    None until a release has an AppImage built under the current name."""
    for release in releases:
        if (release.get("draft") is False and TAG.fullmatch(release.get("tag_name", ""))
                and any(APPIMAGE.fullmatch(a.get("name", "")) for a in release.get("assets", []))):
            return release
    return None


def github_json(url: str, token: str | None):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "leafsmith-aur-package"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return json.load(response)


def fetch_release(tag: str | None, token: str | None) -> dict | None:
    api = f"https://api.github.com/repos/{REPOSITORY}/releases"
    if tag:
        pkgver_from_tag(tag)  # also keeps the tag a plain URL path segment
        release = github_json(f"{api}/tags/{tag}", token)
    else:
        release = latest_appimage_release(github_json(f"{api}?per_page=30", token))
        if release is None:
            return None
    url = f"https://github.com/{REPOSITORY}/releases/download/{release['tag_name']}/{SUMS_ASSET}"
    if not any(a.get("name") == SUMS_ASSET and a.get("browser_download_url") == url for a in release.get("assets", [])):
        raise ValueError(f"Release {release['tag_name']} has no {SUMS_ASSET}")
    # A public asset: fetch it without the token, which would follow the redirect to the asset host.
    request = urllib.request.Request(url, headers={"User-Agent": "leafsmith-aur-package"})
    with urllib.request.urlopen(request, timeout=60) as response:
        sums = response.read(65537)
    if len(sums) > 65536:
        raise ValueError(f"{SUMS_ASSET} is unexpectedly large")
    return release_artifact(release, sums.decode("utf-8"))


def makepkg_srcinfo(directory: Path) -> str:
    return subprocess.run(["makepkg", "--printsrcinfo"], cwd=directory, check=True,
                          capture_output=True, text=True, timeout=120).stdout


def render(artifact: dict, maintainer: str, pkgrel: int, srcinfo=makepkg_srcinfo) -> dict[str, bytes]:
    """Every substituted value is validated, so none can inject PKGBUILD code."""
    if not MAINTAINER.fullmatch(maintainer):
        raise ValueError("AUR maintainer must look like 'Name <email>' without shell characters")
    if (artifact["pkgver"] != pkgver_from_tag(artifact["tag"]) or not APPIMAGE.fullmatch(artifact["appimage"])
            or not SHA256.fullmatch(artifact["sha256"]) or type(pkgrel) is not int or pkgrel < 1):
        raise ValueError("Invalid release artifact or pkgrel")
    files = {name: (PACKAGING / name).read_bytes() for name in LOCAL_SOURCES}
    values = {"MAINTAINER": maintainer, "PKGVER": artifact["pkgver"], "PKGREL": str(pkgrel),
              "TAG": artifact["tag"], "APPIMAGE": artifact["appimage"], "APPIMAGE_SHA256": artifact["sha256"],
              "LAUNCHER_SHA256": hashlib.sha256(files[f"{APP}.sh"]).hexdigest(),
              "DESKTOP_SHA256": hashlib.sha256(files[f"{APP}.desktop"]).hexdigest()}
    template = (PACKAGING / "PKGBUILD.in").read_text(encoding="utf-8")
    files["PKGBUILD"] = re.sub(r"@([A-Z0-9_]+)@", lambda m: values[m[1]], template).encode()
    with tempfile.TemporaryDirectory(prefix="leafsmith-aur-") as temporary:
        directory = Path(temporary)
        for name, content in files.items():
            (directory / name).write_bytes(content)
        files[".SRCINFO"] = srcinfo(directory).encode()
    return files


def pacman_vercmp(a: str, b: str) -> int:
    return int(subprocess.run(["vercmp", a, b], check=True, capture_output=True, text=True, timeout=30).stdout)


def run_git(*args: str) -> str:
    completed = subprocess.run(["git", *args], capture_output=True, text=True, timeout=300)
    if completed.returncode:
        # AUR's server hooks explain rejected pushes on stderr. The SSH key path
        # is only in GIT_SSH_COMMAND, never in these arguments.
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def git(directory: Path, *args: str) -> str:
    return run_git("-C", str(directory), *args)


def clone_aur(remote: str, target: Path) -> str:
    """Clone without running repository hooks; return HEAD, or '' when AUR has
    no package of this name yet (AUR serves an empty repository for it)."""
    run_git("-c", "core.hooksPath=/dev/null", "clone", "--quiet", remote, str(target))
    git(target, "config", "core.hooksPath", "/dev/null")
    if not git(target, "branch", "--list", "--all"):
        git(target, "symbolic-ref", "HEAD", "refs/heads/master")
        return ""
    if git(target, "rev-parse", "--abbrev-ref", "HEAD") != "master":
        raise ValueError("The AUR repository's checked-out branch is not master")
    return git(target, "rev-parse", "HEAD")


def tracked_files(checkout: Path) -> dict[str, bytes]:
    files = {}
    for name in filter(None, git(checkout, "ls-files", "-z").split("\0")):
        path = checkout / name
        if path.is_symlink() or not path.is_file() or "/" in name:
            raise ValueError(f"Unexpected non-file or nested path in the AUR repository: {name}")
        files[name] = path.read_bytes()
    return files


def srcinfo_version(text: str) -> tuple[str, int]:
    fields = {}
    for line in text.splitlines():
        key, separator, value = line.strip().partition(" = ")
        if separator:
            fields.setdefault(key, value)
    if fields.get("pkgbase") != PKGNAME or fields.get("pkgname") != PKGNAME:
        raise ValueError(f"The AUR repository holds {fields.get('pkgbase')!r}, not {PKGNAME}")
    if "epoch" in fields or not fields.get("pkgrel", "").isdigit():
        raise ValueError("AUR has an epoch or non-integer pkgrel; reconcile the manual change first")
    return fields["pkgver"], int(fields["pkgrel"])


def plan(artifact: dict, maintainer: str, remote: str, out: Path,
         vercmp=pacman_vercmp, srcinfo=makepkg_srcinfo) -> dict:
    """Decide what to publish relative to AUR's current master and write it to
    out/package with out/plan.json. GitHub's template is the source of truth:
    a different recipe for the same pkgver becomes the next pkgrel."""
    out = Path(out)
    with tempfile.TemporaryDirectory(prefix="leafsmith-aur-clone-") as temporary:
        checkout = Path(temporary) / "aur"
        head = clone_aur(remote, checkout)
        published = tracked_files(checkout) if head else {}
    current = srcinfo_version(published[".SRCINFO"].decode()) if ".SRCINFO" in published else None
    if head and current is None:
        raise ValueError("The AUR repository has commits but no .SRCINFO")
    pkgver, pkgrel, action, files = artifact["pkgver"], 1, "publish", None
    order = vercmp(pkgver, current[0]) if current else 1
    if order < 0:
        action = "older"
    elif order == 0:
        pkgrel = current[1]
        files = render(artifact, maintainer, pkgrel, srcinfo)
        if files == published:
            action = "unchanged"
        else:
            pkgrel, files = pkgrel + 1, None
    if files is None:
        # An older release is still rendered so CI builds and checks the recipe.
        files = render(artifact, maintainer, pkgrel, srcinfo)
    result = {"action": action, "pkgname": PKGNAME, "tag": artifact["tag"], "release_url": artifact["release_url"],
              "pkgver": pkgver, "pkgrel": pkgrel,
              "aur_head": head, "aur_version": f"{current[0]}-{current[1]}" if current else None,
              "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}}
    if out.exists():
        shutil.rmtree(out)
    write_files(out / "package", files)
    (out / "plan.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def write_files(directory: Path, files: dict[str, bytes]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (directory / name).write_bytes(content)
        (directory / name).chmod(0o755 if name.endswith(".sh") else 0o644)


# namcap -m errors accepted after review. Keep each narrow and give the reason.
REVIEWED_NAMCAP_ERRORS = (
    # Arch's guidelines place large self-contained software in /opt; every ELF
    # file there makes namcap report the directory once.
    re.compile(rf"{PKGNAME} E: elffile-in-questionable-dirs opt/"),
    # The frozen worker's CPython runtime and stdlib extension modules keep the
    # hosted runner's build RUNPATH ahead of $ORIGIN. The directory does not
    # exist on user systems and only root can create it under /opt. The fix
    # belongs in scripts/freeze-worker.py, not in a patched AUR binary.
    re.compile(rf"{PKGNAME} E: insecure-runpath /opt/hostedtoolcache/Python/[0-9.]+/x64/lib "
               rf"{re.escape(WORKER_PYTHON)}"
               r"(?:libpython3\.[0-9]+\.so\.1\.0|python3\.[0-9]+/lib-dynload/[\w.-]+\.so)"),
)
DEPENDENCY_REASON = re.compile(r"([a-z-]+) (\[[^]]*\]) (\[[^]]*\])")


def bundled_dependency(line: str, bundled: set[str]) -> bool:
    """namcap resolves libraries the bundle ships without an $ORIGIN RUNPATH,
    and the frozen worker's Python sources and notice copies, against host packages. Such a
    report is bundle-internal only if every needing file is inside the bundle
    and every library is one the package ships; anything else is a real host
    dependency for depends=()."""
    match = re.fullmatch(rf"{PKGNAME} E: dependency-detected-not-included \S+ \((.+)\)", line)
    reasons = list(DEPENDENCY_REASON.finditer(match[1])) if match else []
    if not reasons or ", ".join(r[0] for r in reasons) != match[1]:
        return False
    for reason in reasons:
        try:
            needed, files = ast.literal_eval(reason[2]), ast.literal_eval(reason[3])
        except (ValueError, SyntaxError):
            return False
        if not files or any(".." in f.split("/") for f in files):
            return False
        if reason[1] == "libraries-needed":
            inside = all(f.startswith(BUNDLE) for f in files) and all(Path(lib).name in bundled for lib in needed)
        elif reason[1] == "python-modules-needed":
            inside = all(f.startswith((WORKER_PYTHON, WORKER_NOTICES)) for f in files)
        else:
            inside = False
        if not inside:
            return False
    return True


def namcap_errors(output: str, bundled: set[str] = frozenset()) -> tuple[list[str], list[str]]:
    """Split `namcap -m` error lines into (unreviewed, reviewed); warnings are
    informational. `bundled` holds the file names shipped under /opt/leafsmith."""
    unreviewed, reviewed = [], []
    for line in output.splitlines():
        if re.match(r"(?:\S+|PKGBUILD \(\S+\)) E: |Error: ", line):
            accepted = any(p.fullmatch(line) for p in REVIEWED_NAMCAP_ERRORS) or bundled_dependency(line, bundled)
            (reviewed if accepted else unreviewed).append(line)
    return unreviewed, reviewed


def publish(out: Path, remote: str, maintainer: str) -> bool:
    """Push the validated plan to AUR master. Never force-pushes: if AUR moved
    after validation, stop so the next run plans against the new state."""
    out = Path(out)
    planned = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    if planned["action"] != "publish":
        print(f"Nothing to publish: {planned['action']} (AUR has {planned['aur_version']})")
        return False
    if planned.get("pkgname") != PKGNAME or sorted(planned["files"]) != sorted(PACKAGE_FILES):
        raise ValueError("plan.json does not describe this package's files")
    files = {name: (out / "package" / name).read_bytes() for name in PACKAGE_FILES}
    for name, content in files.items():
        if hashlib.sha256(content).hexdigest() != planned["files"][name]:
            raise ValueError(f"{name} does not match the validated plan")
    if not MAINTAINER.fullmatch(maintainer):
        raise ValueError("AUR maintainer must look like 'Name <email>' without shell characters")
    name, email = maintainer[:-1].split(" <", 1)
    version = f"{planned['pkgver']}-{planned['pkgrel']}"
    with tempfile.TemporaryDirectory(prefix="leafsmith-aur-publish-") as temporary:
        checkout = Path(temporary) / "aur"
        head = clone_aur(remote, checkout)
        published = tracked_files(checkout) if head else {}
        if head != planned["aur_head"]:
            if published == files:
                print(f"AUR already has these files for {version}")
                return False
            raise ValueError("AUR changed after validation; re-run the workflow to plan against it")
        for tracked in published:
            (checkout / tracked).unlink()
        write_files(checkout, files)
        git(checkout, "add", "--all")
        if not git(checkout, "diff", "--cached", "--name-only"):
            print(f"AUR already has these files for {version}")
            return False
        subject = f"Update to {version}" if head else f"Initial upload: {version}"
        git(checkout, "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "--quiet",
            "-m", subject, "-m", f"Release {planned['tag']}: {planned['release_url']}")
        git(checkout, "push", "--quiet", "origin", "HEAD:master")
    print(f"Published {PKGNAME} {version} to AUR")
    return True


def namcap_gate(paths: list[str]) -> int:
    """Run after `pacman -U`: namcap's dependency checks read the local
    package database, and the gate reads the installed file list."""
    output = "".join(subprocess.run(["namcap", "-m", path], check=True, capture_output=True,
                                    text=True, timeout=1800).stdout for path in paths)
    print(output, end="")
    listing = subprocess.run(["pacman", "-Qlq", PKGNAME], check=True, capture_output=True,
                             text=True, timeout=120).stdout.splitlines()
    bundled = {Path(path).name for path in listing if path.startswith("/" + BUNDLE) and not path.endswith("/")}
    unreviewed, reviewed = namcap_errors(output, bundled)
    if reviewed:
        print(f"Accepted {len(reviewed)} reviewed or bundle-internal namcap errors (see namcap_errors in scripts/aur_package.py)")
    for line in unreviewed:
        print(f"::error::Unreviewed namcap error: {line}")
    return 1 if unreviewed else 0


def smoke(logs: Path) -> None:
    """The release workflow's native self-test and packaged-operation checks,
    run against the installed /usr/bin launcher instead of an extracted AppImage."""
    logs = logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    helpers = runpy.run_path(str(ROOT / "scripts" / "smoke-package.py"))
    report = {"kind": "aur-installed", "success": False, "interactive_desktop_tested": False, "processes": []}
    env = helpers["clean_environment"]()
    try:
        helpers["test_native"](Path(f"/usr/bin/{APP}"), INSTALLED_WORKER, logs, report, env,
                               helpers["headless_display_prefix"](env, logs))
        report["success"] = True
    finally:
        (logs / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch-release", help="pin a published release's AppImage (GH_TOKEN optional)")
    fetch.add_argument("--tag", help="release tag; default: the newest published release with a matching AppImage")
    fetch.add_argument("--out", type=Path, required=True)
    planner = commands.add_parser("plan", help="render the package and compare it with AUR")
    planner.add_argument("--release", type=Path, required=True, help="fetch-release output")
    planner.add_argument("--maintainer", required=True, help="'Name <email>' for the PKGBUILD")
    planner.add_argument("--remote", default=AUR_READ)
    planner.add_argument("--out", type=Path, required=True)
    gate = commands.add_parser("namcap", help="run namcap -m and fail on unreviewed errors")
    gate.add_argument("paths", nargs="+", help="PKGBUILD and built package")
    smoker = commands.add_parser("smoke", help="headless checks of the installed package")
    smoker.add_argument("--logs", type=Path, required=True)
    publisher = commands.add_parser("publish", help="push a validated plan to AUR")
    publisher.add_argument("--out", type=Path, required=True, help="plan output directory")
    publisher.add_argument("--maintainer", required=True, help="'Name <email>' for the AUR commit")
    publisher.add_argument("--remote", default=AUR_PUSH)
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch-release":
            artifact = fetch_release(args.tag, os.environ.get("GH_TOKEN"))
            if artifact is None:
                print(f"::notice::No published release has a {PRODUCT}_<version>_amd64.AppImage yet; nothing to package")
                return 0
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
            print(f"{artifact['tag']}: {artifact['appimage']} sha256={artifact['sha256']}")
        elif args.command == "plan":
            artifact = json.loads(args.release.read_text(encoding="utf-8"))
            result = plan(artifact, args.maintainer, args.remote, args.out)
            print(f"{result['action']}: {PKGNAME} {result['pkgver']}-{result['pkgrel']} "
                  f"(AUR has {result['aur_version'] or 'no package yet'})")
        elif args.command == "namcap":
            return namcap_gate(args.paths)
        elif args.command == "smoke":
            smoke(args.logs)
        else:
            publish(args.out, args.remote, args.maintainer)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError, urllib.error.URLError) as error:
        print(f"::error::{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
