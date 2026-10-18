"""Fail-closed Linux shared-library notice and corresponding-source audit.

This is a packaging gate, not legal advice. Debian source download is deliberately
separate from apt configuration: this program never modifies the host's sources.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import ast
import glob
import hashlib
import importlib.metadata as md
import json
import os
import sys
import sysconfig
import tempfile
import zipfile
from email.parser import Parser
import re
import shutil
import subprocess


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_file(root, name):
    root = Path(root).resolve()
    path = root / name
    if Path(name).is_absolute() or ".." in Path(name).parts or not path.resolve().is_relative_to(root):
        raise ValueError("Unsafe inventory path: " + str(name))
    if not path.is_file():
        raise ValueError("Missing inventory file: " + str(name))
    return path


def command(args, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, timeout=300, **kwargs)


def wheel_owners(distributions, records, notices):
    """Use installed RECORD paths, not guessed wheel/package names (.libs too)."""
    records = {canonical(r["name"]): r for r in records}
    index = {}
    for dist in distributions:
        name = dist.metadata.get("Name", "")
        record = records.get(canonical(name))
        for file in dist.files or []:
            if not re.search(r"\.so(?:\.|$)", Path(file).name):
                continue
            if not record or not record.get("notices"):
                raise ValueError("Missing wheel notices: " + name)
            for notice in record["notices"]:
                checked_file(notices, notice)
            original = Path(dist.locate_file(file))
            if not original.is_file():
                raise ValueError("Missing wheel RECORD library: " + str(original))
            owner = {**record, "kind": "wheel", "record": str(file), "original": str(original),
                     "original_sha256": sha256(original)}
            index.setdefault(Path(file).name, []).append(owner)
    return index


def wheel_owner(path, index):
    candidates = index.get(path.name, [])
    if len(candidates) > 1:
        suffix = [r for r in candidates if path.as_posix().endswith("/" + r["record"])]
        candidates = suffix or candidates
    if len(candidates) > 1:
        raise ValueError("Ambiguous wheel RECORD basename: " + path.name)
    return dict(candidates[0]) if candidates else None


def linker_paths():
    result = command(["ldconfig", "-p"])
    result.check_returncode()
    paths = {}
    for line in result.stdout.splitlines():
        match = re.match(r"\s*(\S+)\s+\(.*\)\s+=>\s+(/\S+)", line)
        if match:
            paths.setdefault(match[1], []).append(Path(match[2]))
    return paths


def debian_owner(path, linker):
    """Resolve original installed path through ldconfig, then exact dpkg owner.

    dpkg -S on a PyInstaller copy is meaningless. Also try merged-/usr aliases,
    since dpkg's recorded path can predate the runner's directory symlinks.
    """
    paths = []
    if path.is_absolute():
        paths.extend([path, path.resolve()])
    else:
        paths.extend(linker.get(path.name, []))
    candidates = list(paths)
    for original in paths:
        text = str(original)
        if text.startswith(("/lib/", "/lib64/")):
            candidates.append(Path("/usr" + text))
        elif text.startswith(("/usr/lib/", "/usr/lib64/")):
            candidates.append(Path(text[4:]))
    owners = {}
    for original in dict.fromkeys(candidates):
        found = command(["dpkg-query", "-S", str(original)])
        if found.returncode:
            continue
        for line in found.stdout.splitlines():
            if ": " not in line:
                continue
            package, installed = line.rsplit(": ", 1)
            if installed != str(original):
                continue
            result = command(["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n", package])
            result.check_returncode()
            binary, version, source, source_version = result.stdout.strip().split("\t")
            owners[(binary, version)] = {"kind": "debian", "name": binary, "version": version,
                                        "source_package": source, "source_version": source_version,
                                        "original": str(original)}
    if len(owners) != 1:
        raise ValueError(("Unmapped" if not owners else "Ambiguous") + " system library: " + str(path))
    return next(iter(owners.values()))


def license_policy(text, source_package, basename):
    """Reject GPL-only/AGPL libraries, not LGPL runtime libraries.

    Debian copyright can cover GPL build utilities alongside LGPL libraries.
    Keep that complete text and exact sources; do not reject LGPL because its
    notice incorporates GPL text. Exceptions are restricted to GCC runtime libs.
    This heuristic is a tripwire, not a binary-level legal determination.
    """
    evidence = text
    if re.search(r"(?mi)^Format:.*copyright-format", text):
        # DEP5 distinguishes default code terms from per-file build-tool terms.
        # Preserve every stanza in the notices/sources, but do not mislabel an
        # Apache/LGPL library GPL-only because config.guess is GPL. Source-file
        # exceptions still require human review; this is not linkage analysis.
        for paragraph in re.split(r"\n\s*\n", text):
            control = Parser().parsestr(paragraph)
            if control.get("Files", "").strip() == "*" and control.get("License"):
                evidence = control["License"].splitlines()[0]
                break
    if re.search(r"\bAGPL(?:v?\d|[-\s]|\b)|Affero General Public", evidence, re.I):
        raise ValueError("AGPL library is prohibited: " + basename)
    gpl = re.search(r"\bGPL(?:v?\d|[-\s]|\b)|GNU GENERAL PUBLIC LICENSE", evidence, re.I)
    lgpl = re.search(r"\bLGPL(?:v?\d|[-\s]|\b)|GNU (?:LESSER|LIBRARY) GENERAL PUBLIC LICENSE", evidence, re.I)
    gcc = (re.fullmatch(r"gcc-\d+", source_package or "")
           and re.match(r"lib(?:gcc_s|stdc\+\+)\.so(?:\.|$)", basename)
           and re.search(r"GCC (?:RUNTIME LIBRARY |runtime )?EXCEPTION", text, re.I))
    if gcc:
        return "gcc-runtime-exception-source-required"
    if lgpl:
        return "lgpl-source-required"
    if gpl:
        raise ValueError("GPL-only library requires explicit review; not permitted: " + basename)
    return "notice-and-exact-source-preserved"


def debian_notices(owner, output, filesystem=Path("/")):
    package = owner["name"].split(":", 1)[0]
    source = filesystem / "usr/share/doc" / package / "copyright"
    if not source.is_file():
        raise ValueError("Missing Debian package copyright: " + str(source))
    folder = Path("linux/debian") / (owner["name"].replace(":", "_") + "-" + owner["version"].replace(":", "_"))
    target = output / folder / "copyright"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    notices = [target.relative_to(output).as_posix()]
    # Copyright files often refer to the standard text instead of embedding it.
    # Also preserve every available common license: this resolves indirect and
    # wrapped references (e.g. LGPL referring in turn to the GPL), without links.
    common = filesystem / "usr/share/common-licenses"
    referenced = re.findall(r"/usr/share/common-licenses/([\w.+-]+)", source.read_text(errors="replace"))
    for name in referenced:
        if not (common / name.rstrip(".")).is_file():
            raise ValueError("Missing referenced common license: " + name)
    for license_file in sorted(common.iterdir()) if common.is_dir() else []:
        if license_file.is_file():
            dest = output / "linux/common-licenses" / license_file.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(license_file, dest)
            notices.append(dest.relative_to(output).as_posix())
    return sorted(notices)


def verify_source_directory(directory, package, version):
    dscs = list(directory.glob("*.dsc"))
    if len(dscs) != 1:
        raise ValueError("Expected exactly one source .dsc for " + package + "=" + version)
    dsc = dscs[0]
    text = dsc.read_text(encoding="utf-8")
    # apt validates repository authentication on download. Parse clear-signed
    # control data here; do not pretend this is an independent PGP validation.
    start = re.search(r"(?m)^Format:", text)
    if start:
        text = text[start.start():].split("-----BEGIN PGP SIGNATURE-----", 1)[0]
    control = Parser().parsestr(text)
    if control.get("Source") != package or control.get("Version") != version:
        raise ValueError("Mismatched source identity for " + package + "=" + version)
    files = {dsc.name: sha256(dsc)}
    checksums = control.get("Checksums-Sha256", "").splitlines()
    for line in checksums:
        if not line.strip():
            continue
        digest, size, name = line.split()
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or Path(name).name != name:
            raise ValueError("Unsafe source checksum entry: " + name)
        path = checked_file(directory, name)
        if path.stat().st_size != int(size) or sha256(path) != digest:
            raise ValueError("Mismatched source checksum: " + name)
        files[name] = digest
    if len(files) < 2 or not any(".tar." in name or name.endswith(".tar") for name in files):
        raise ValueError("Missing source archives in .dsc for " + package)
    return files


def fetch_source(package, version, output):
    if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", package) or not re.fullmatch(r"[0-9A-Za-z.+:~_-]+", version):
        raise ValueError("Unsafe source package identity")
    directory = output / (package + "-" + version.replace(":", "_"))
    directory.mkdir(parents=True, exist_ok=False)
    args = ["apt-get", "source", "--download-only", "--only-source", package + "=" + version]
    result = command(args, cwd=directory)
    (directory / "download.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise ValueError("Cannot obtain exact corresponding source " + package + "=" + version
                         + "; enable matching deb-src or an authenticated Ubuntu snapshot/Launchpad archive; "
                         "never substitute a newer version. " + result.stderr[-2000:])
    files = verify_source_directory(directory, package, version)
    return {"source_package": package, "source_version": version, "command": args,
            "files": {(directory.relative_to(output) / name).as_posix(): digest for name, digest in files.items()}}


def shared_libraries(root):
    """Inventory actual *.so / *.so.* payloads, including wheel .libs folders."""
    root = Path(root).resolve()
    paths = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            raise ValueError("Payload symlink escapes audit root: " + str(path))
        if re.search(r"\.so(?:\.|$)", path.name):
            if not path.resolve().is_relative_to(root):
                raise ValueError("Library symlink escapes payload: " + str(path))
            if not path.is_file():
                raise ValueError("Missing shared library target: " + str(path))
            paths.append(path)
    return paths


def linked_libraries(paths):
    """ldd's transitive resolved closure for trusted build outputs only."""
    paths = list(paths)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(dict.fromkeys(str(p.parent.resolve()) for p in paths))
    libraries = set()
    for path in paths:
        result = command(["ldd", str(path.resolve())], env=env)
        output = result.stdout + result.stderr
        if "not found" in output:
            raise ValueError("Unresolved linked library for " + str(path) + ": " + output)
        if result.returncode:
            raise ValueError("Cannot inventory linked dependencies for " + str(path) + ": " + output)
        for line in output.splitlines():
            match = re.search(r"(?:=>\s*)?(/\S+)\s+\(", line)
            if match:
                original = Path(match[1])
                if not original.is_file():
                    raise ValueError("Missing linked library: " + str(original))
                libraries.add(original)
    return sorted(libraries)


def python_runtime_owner(path, output):
    """Only actual CPython libpython/lib-dynload originals, not arbitrary .so's."""
    candidates = [Path(sysconfig.get_config_var("DESTSHARED") or sysconfig.get_path("stdlib")) / path.name,
                  Path(sysconfig.get_path("stdlib")) / "lib-dynload" / path.name]
    runtimes = {sysconfig.get_config_var(key) for key in ("LDLIBRARY", "INSTSONAME")}
    if path.name in runtimes:
        candidates.extend([Path(sysconfig.get_config_var("LIBDIR") or sys.base_prefix) / path.name,
                           Path(sys.base_prefix) / "lib" / path.name])
    original = next((p for p in candidates if p.is_file()), None)
    if original is None:
        return None
    checked_file(output, "python-runtime/LICENSE.txt")
    return {"kind": "python-runtime", "name": "CPython", "version": sys.version.split()[0],
            "original": str(original), "original_sha256": sha256(original),
            "notices": ["python-runtime/LICENSE.txt"], "policy": "cpython-runtime-notices"}


def freezer_origins(toc):
    """Read PyInstaller's real collection provenance without executing its TOC."""
    data = ast.literal_eval(Path(toc).read_text(encoding="utf-8"))
    queue = [data]
    result = {}
    while queue:
        item = queue.pop()
        if not isinstance(item, (tuple, list)):
            continue
        if len(item) == 3 and all(isinstance(value, str) for value in item):
            destination, original, kind = item
            if kind not in ("BINARY", "EXTENSION"):
                continue
            if Path(destination).is_absolute() or ".." in Path(destination).parts:
                raise ValueError("Unsafe PyInstaller native destination: " + destination)
            if destination in result and result[destination] != Path(original):
                raise ValueError("Ambiguous PyInstaller original: " + destination)
            result[destination] = Path(original)
        else:
            queue.extend(item)
    if not result:
        raise ValueError("Missing PyInstaller native collection provenance")
    return result


def collect(worker, native, output, source_output, python_records, distributions=None, extra_libraries=(), freezer_toc=None):
    worker, native, output, source_output = map(lambda p: Path(p).resolve(), (worker, native, output, source_output))
    if not native.is_file() or not (worker / "paperwork-worker").is_file():
        raise ValueError("Build native executable and freeze worker before Linux license collection")
    shipped = shared_libraries(worker)
    if not shipped:
        raise ValueError("Frozen Linux worker contains no shared libraries")
    wheel_index = wheel_owners(md.distributions() if distributions is None else distributions, python_records, output)
    origins = freezer_origins(freezer_toc) if freezer_toc is not None else {}
    linker = linker_paths()
    bootloader = next((r for r in python_records if canonical(r["name"]) == "pyinstaller"), {})
    bootloader_notices = bootloader.get("notices", [])
    if not any("bootloader" in checked_file(output, p).read_text(errors="replace").lower()
               and "exception" in checked_file(output, p).read_text(errors="replace").lower() for p in bootloader_notices):
        raise ValueError("Missing actual PyInstaller bootloader exception notice")
    extras = [Path(p).resolve() for p in extra_libraries]
    # Native binary plus every worker extension: ldd includes transitive deps.
    # GTK/GIO loader modules are explicit extra roots, not assumed shipped.
    dependencies = linked_libraries([native, worker / "paperwork-worker", *shipped, *extras])
    staged_set = {p.resolve() for p in shipped}
    superset = sorted(set(dependencies + extras) - staged_set)
    libraries = []
    debian_cache = {}
    sources_needed = set()
    for path, role in [(p, "shipped-worker") for p in shipped] + [(p, "dependency-superset") for p in superset]:
        collected_original = None
        if role == "shipped-worker":
            relative = path.resolve().relative_to(worker).as_posix().removeprefix("_internal/")
            collected_original = origins.get(relative)
        owner = wheel_owner(path, wheel_index) or python_runtime_owner(path, output)
        if owner and collected_original is not None and Path(owner["original"]).resolve() != collected_original.resolve():
            raise ValueError("Freezer provenance disagrees with current runtime/wheel environment: " + str(path))
        if owner and owner["kind"] == "wheel":
            # Wheel declarations identify primary terms; full nested vendored
            # notices are preserved separately, not reinterpreted as app MIT.
            policy = license_policy(owner.get("license") or "", owner["name"], path.name)
            if policy == "lgpl-source-required":
                raise ValueError("Copyleft wheel requires a reviewed exact-source collector: " + owner["name"])
            owner["policy"] = policy
        if owner is None:
            if role == "shipped-worker":
                if freezer_toc is not None and collected_original is None:
                    raise ValueError("Missing original system-library path in PyInstaller TOC: " + str(path))
                system_path = collected_original or Path(path.name)
            else:
                system_path = path
            owner = debian_owner(system_path, linker)
            key = (owner["name"], owner["version"])
            if key not in debian_cache:
                debian_cache[key] = debian_notices(owner, output)
            owner["notices"] = debian_cache[key]
            copyright_path = next(p for p in owner["notices"] if p.endswith("/copyright"))
            copyright_text = checked_file(output, copyright_path).read_text(errors="replace")
            owner["policy"] = license_policy(copyright_text, owner["source_package"], path.name)
            owner["original_sha256"] = sha256(Path(owner["original"]))
            sources_needed.add((owner["source_package"], owner["source_version"]))
        libraries.append({**owner, "path": path.relative_to(worker).as_posix() if role == "shipped-worker" else str(path),
                          "basename": path.name, "role": role, "sha256": sha256(path)})
    if source_output.exists() and any(source_output.iterdir()):
        raise ValueError("Corresponding source destination must be fresh; refusing stale sources: " + str(source_output))
    source_output.mkdir(parents=True, exist_ok=True)
    sources = []
    for package, version in sorted(sources_needed):
        print("Downloading exact corresponding source " + package + "=" + version, flush=True)
        sources.append(fetch_source(package, version, source_output))
    inventory = {"schema": 1, "platform": sys.platform, "libraries": libraries, "sources": sources,
                 "scope": "Actual frozen-worker libraries plus native/worker ldd closure and explicit loader modules; superset is not a claim that all dependencies ship.",
                 "binaries": [{"name": "paperwork-worker", "sha256": sha256(worker / "paperwork-worker"),
                               "notices": bootloader_notices, "policy": "pyinstaller-bootloader-exception"},
                              {"name": native.name, "sha256": sha256(native), "policy": "application-and-rust-notices"}]}
    (source_output / "source-inventory.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    (source_output / "README.txt").write_text(
        "Exact Debian/Ubuntu source packages for the recorded binary/source package versions.\n"
        "Includes .dsc, upstream archives, and Debian patches/archives listed by each .dsc.\n"
        "Keep this archive available alongside the matching AppImage, including when mirroring it.\n"
        "This is delivery of source files, not a three-year source offer or an upstream URL substitute.\n"
        "Sources cover a dependency superset; consult the postbundle audit for actual shipped libraries.\n", encoding="utf-8")
    return inventory


def verify_sources(inventory, source_output):
    sources = {}
    for source in inventory.get("sources", []):
        key = (source["source_package"], source["source_version"])
        if key in sources or not source.get("files"):
            raise ValueError("Duplicate or empty corresponding source record")
        for name, expected in source["files"].items():
            if sha256(checked_file(source_output, name)) != expected:
                raise ValueError("Corresponding source artifact checksum mismatch: " + name)
        dscs = [checked_file(source_output, name) for name in source["files"] if name.endswith(".dsc")]
        if len(dscs) != 1:
            raise ValueError("Missing corresponding source .dsc")
        files = verify_source_directory(dscs[0].parent, *key)
        listed = {Path(name).name: digest for name, digest in source["files"].items()}
        if listed != files:
            raise ValueError("Incomplete corresponding source inventory")
        sources[key] = source
    return sources


def audit_payload(root, inventory, notices, source_output):
    """Verify actual libraries against prebundle ownership/source inventory.

    RPATH/strip transformations can change binaries: retain BOTH prebundle and
    actual payload hashes, rather than requiring original Debian byte hashes.
    """
    sources = verify_sources(inventory, source_output)
    index = {}
    for record in inventory["libraries"]:
        index.setdefault(record["basename"], []).append(record)
    actual = []
    for path in shared_libraries(root):
        candidates = index.get(path.name, [])
        identities = {(r["kind"], r["name"], r.get("version"), r.get("source_package"), r.get("source_version")) for r in candidates}
        if len(identities) != 1:
            raise ValueError(("Unmapped" if not identities else "Ambiguous") + " postbundle library: " + str(path))
        record = candidates[0]
        if not record.get("notices"):
            raise ValueError("Missing dependency notices for " + path.name)
        for notice in record["notices"]:
            checked_file(notices, notice)
        if record["kind"] == "debian" and (record["source_package"], record["source_version"]) not in sources:
            raise ValueError("Missing exact corresponding source for " + path.name)
        actual.append({**record, "path": path.relative_to(root).as_posix(),
                       "inventory_sha256": record["sha256"], "sha256": sha256(path)})
    return {"success": True, "shared_library_count": len(actual), "libraries": actual,
            "source_package_count": len(sources), "interactive_desktop_tested": False}


def verify_notice_manifest(notices):
    manifest = json.loads(checked_file(notices, "manifest.json").read_text(encoding="utf-8"))
    if not manifest:
        raise ValueError("Empty packaged notice manifest")
    for name, expected in manifest.items():
        if sha256(checked_file(notices, name)) != expected:
            raise ValueError("Packaged notice checksum mismatch: " + name)


def audit_appimage(pattern, inventory_path, source_output, logs):
    matches = glob.glob(pattern)
    if len(matches) != 1:
        raise ValueError("Expected exactly one AppImage: " + repr(matches))
    appimage = Path(matches[0]).resolve()
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    appimage.chmod(appimage.stat().st_mode | 0o111)
    with tempfile.TemporaryDirectory(prefix="linux-license-audit-", dir=logs) as folder:
        result = command([str(appimage), "--appimage-extract"], cwd=folder)
        (logs / "extract.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        result.check_returncode()
        root = Path(folder) / "squashfs-root"
        worker = root / "usr/lib/paperwork-desktop/worker"
        if not (worker / "paperwork-worker").is_file():
            raise ValueError("Unexpected AppImage worker resource layout")
        notices = worker / "third-party-licenses"
        verify_notice_manifest(notices)
        if sha256(checked_file(notices, "linux-libraries.json")) != sha256(inventory_path):
            raise ValueError("AppImage has stale or modified prebundle Linux inventory")
        for record in inventory["libraries"]:
            if record["role"] == "shipped-worker":
                checked_file(worker, record["path"])
        report = audit_payload(root, inventory, notices, source_output)
        if not report["libraries"]:
            raise ValueError("AppImage has no auditable shared libraries")
        report["appimage_sha256"] = sha256(appimage)
        return report


def source_archive(directory, inventory, target):
    verify_sources(inventory, directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Source ZIP must be outside its input directory")
    # Source tarballs are already compressed; storing avoids expensive double
    # compression of large GCC/WebKit archives. Verify bytes from the final ZIP.
    hashes = {}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                name = path.relative_to(directory).as_posix()
                checked_file(directory, name)
                archive.write(path, name)
                hashes[name] = sha256(path)
    with zipfile.ZipFile(target) as archive:
        if set(archive.namelist()) != set(hashes):
            raise ValueError("Source ZIP inventory mismatch")
        for name, expected in hashes.items():
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError("Source ZIP checksum mismatch: " + name)
    return sha256(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appimage", required=True, help="Exactly one AppImage path/glob")
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--logs", required=True, type=Path)
    parser.add_argument("--source-archive", required=True, type=Path, help="Verified corresponding-source ZIP to publish beside AppImage")
    args = parser.parse_args()
    args.logs.mkdir(parents=True, exist_ok=True)
    report = {"success": False}
    try:
        report = audit_appimage(args.appimage, args.inventory.resolve(), args.sources.resolve(), args.logs.resolve())
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        (args.sources / "appimage-library-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        shutil.copyfile(args.inventory, args.sources / "linux-libraries.json")
        report["source_archive_sha256"] = source_archive(args.sources.resolve(), inventory, args.source_archive.resolve())
        report["source_archive"] = str(args.source_archive)
    except Exception as error:
        report["success"] = False
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    (args.logs / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "libraries"}, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
