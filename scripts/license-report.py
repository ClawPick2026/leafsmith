"""Copy real dependency notices; never replace dependency terms with app MIT.

Inventory covers the packaging environment (including build/test tools), not a
claim that each installed distribution is shipped. --require-rust is used by CI.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"pypdfium2", "pillow", "cryptography", "reportlab", "pyinstaller"}
EXCLUDED = {"pymupdf", "mupdf", "ghostscript", "pyqt5", "pyqt6"}


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def notice_path(path):
    # PDFium's third-party notices have ordinary basenames under BUILD_LICENSES.
    return any(any(word in part.upper() for word in ("LICENSE", "COPYING", "NOTICE", "COPYRIGHT"))
               for part in Path(path).parts)


def safe_path(path):
    return Path(*[p.replace(":", "_") for p in Path(str(path)).parts if p not in ("..", "/", "\\")])


def copy_file(source, target):
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return True
    return False


def collect_python(output):
    packages = []
    for dist in md.distributions():
        name = dist.metadata.get("Name", "unknown")
        if canonical(name) in EXCLUDED:
            raise ValueError("Excluded dependency: " + name)
        notices = []
        for file in dist.files or []:
            if notice_path(file):
                target = output / "python" / canonical(name) / safe_path(file)
                if copy_file(Path(dist.locate_file(file)), target):
                    notices.append(target.relative_to(output).as_posix())
        packages.append({"name": name, "version": dist.version,
                         "license": dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See distribution notices",
                         "notices": sorted(notices)})
    missing = REQUIRED - {canonical(p["name"]) for p in packages if p["notices"]}
    if missing:
        raise ValueError("Missing required dependency notices: " + ", ".join(sorted(missing)))
    return sorted(packages, key=lambda p: p["name"].lower())


def collect_npm(root, output):
    packages = []
    for manifest in (root / "node_modules").rglob("package.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            continue
        if not data.get("name") or not data.get("version"):
            continue
        notices = []
        folder = data["name"].replace("/", "_") + "-" + data["version"]
        for source in manifest.parent.rglob("*"):
            relative = source.relative_to(manifest.parent)
            # Nested node_modules packages are inventoried independently.
            if "node_modules" not in relative.parts and source.is_file() and notice_path(relative):
                target = output / "npm" / folder / relative
                copy_file(source, target)
                notices.append(target.relative_to(output).as_posix())
        packages.append({"name": data["name"], "version": data["version"], "license": data.get("license"), "notices": sorted(notices)})
    return sorted(packages, key=lambda p: (p["name"], p["version"]))


def collect_rust(root, output):
    completed = subprocess.run(["cargo", "metadata", "--format-version", "1", "--manifest-path", str(root / "src-tauri/Cargo.toml")],
                               text=True, encoding='utf-8', capture_output=True, check=True, timeout=300)
    packages = []
    for package in json.loads(completed.stdout)["packages"]:
        notices = []
        folder = Path(package["manifest_path"]).parent
        # Registry crates may vendor native libraries with separate nested terms.
        # Never recurse into the workspace app's multi-GB target build directory.
        sources = ([p for p in folder.rglob("*") if p.is_file() and notice_path(p.relative_to(folder))]
                   if package.get("source") else [])
        if package.get("license_file"):
            sources.append(folder / package["license_file"])
        # Preserve README license statements when a crate omits a license file.
        if not sources:
            sources.extend(p for p in folder.glob("README*") if p.is_file())
        for source in set(sources):
            target = output / "rust" / (package["name"] + "-" + package["version"]) / safe_path(source.relative_to(folder))
            if copy_file(source, target):
                notices.append(target.relative_to(output).as_posix())
        packages.append({"name": package["name"], "version": package["version"],
                         "license": package.get("license"), "notices": sorted(notices)})
    return sorted(packages, key=lambda p: (p["name"], p["version"]))


def collect_python_runtime(output):
    candidates = [Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"]
    source = next((p for p in candidates if p.is_file()), None)
    if source is None:
        raise ValueError("Python runtime LICENSE.txt was not found; do not ship without it")
    copy_file(source, output / "python-runtime/LICENSE.txt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-rust", action="store_true")
    parser.add_argument("--linux-native", type=Path,
                        help="Built Linux executable: audit native/worker libraries and download exact Debian sources")
    parser.add_argument("--linux-extra-library", action="append", default=[],
                        help="Additional installed loader-module path/glob (repeatable, Linux only)")
    args = parser.parse_args()
    if args.linux_native and sys.platform != "linux":
        parser.error("--linux-native requires native Linux")
    if args.linux_extra_library and not args.linux_native:
        parser.error("--linux-extra-library requires --linux-native")
    output = ROOT / "build/worker/paperwork-worker/third-party-licenses"
    # No stale notices from a previous build may satisfy the gate.
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    python = collect_python(output)
    npm = collect_npm(ROOT, output)
    rust = collect_rust(ROOT, output) if args.require_rust else []
    collect_python_runtime(output)
    if args.linux_native:
        import glob
        from audit_linux_libraries import collect
        extras = []
        for pattern in args.linux_extra_library:
            matches = glob.glob(pattern, recursive=True)
            if not matches:
                raise ValueError("No installed libraries match requested extra root: " + pattern)
            extras.extend(Path(p) for p in matches)
        source_output = ROOT / "build/linux-corresponding-sources"
        if source_output.exists():
            shutil.rmtree(source_output)
        linux = collect(output.parent, args.linux_native, output, source_output, python,
                        extra_libraries=extras,
                        freezer_toc=ROOT / "build/pyinstaller/paperwork-worker/COLLECT-00.toc")
        (output / "linux-libraries.json").write_text(json.dumps(linux, indent=2), encoding="utf-8")
    for label, records in (("python", python), ("npm", npm), ("rust", rust)):
        (output / (label + "-packages.json")).write_text(json.dumps(records, indent=2), encoding="utf-8")
    if (ROOT / "LICENSE").is_file():
        copy_file(ROOT / "LICENSE", output / "application-MIT.txt")
    (output / "README.txt").write_text(
        "Paperwork application code is MIT; this does NOT relicense dependencies.\n"
        "Actual dependency notices are copied here. Python/npm/Rust inventories include build/test dependencies, "
        "not just runtime dependencies. Package metadata is not a substitute for license texts.\n"
        "PyInstaller's actual COPYING.txt includes the bootloader exception. Python's runtime license is included.\n"
        "PDFium and its third-party build notices, Pillow, cryptography, ReportLab and Bitstream Vera notices are preserved.\n"
        "Unused ReportLab DarkGarden/hb-test fonts are removed from the frozen runtime; source-distribution notices remain for audit.\n"
        "Linux release builds additionally include linux-libraries.json: actual worker libraries plus a prebundle dependency superset.\n"
        "System-library copyrights/common licenses are preserved under linux/. The matching published corresponding-source ZIP\n"
        "contains exact Debian source archives/.dsc/patches and the actual postbundle AppImage library audit, not a source offer.\n"
        "Optional engines and models are not included in the core package and have separate terms.\n",
        encoding="utf-8")
    manifest = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"python_distributions": len(python), "npm_records": len(npm),
                      "rust_records": len(rust), "notice_resource_files": len(manifest), "directory": str(output)}, indent=2))


if __name__ == "__main__":
    main()
