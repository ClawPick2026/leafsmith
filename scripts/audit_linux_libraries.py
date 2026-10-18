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


# Reviewed non-DEP5 libffi8 3.4.2-4 runtime grant. Match the complete License
# section before Documentation, not an MIT keyword elsewhere in a GPL notice.
# Keep the original copyright (including GPL documentation/packaging) unchanged.
LIBFFI_RUNTIME_GRANT = """
libffi - Copyright (c) 1996-2010  Red Hat, Inc and others.
See source files for details.

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
``Software''), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED ``AS IS'', WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""


# Reviewed libuuid1:amd64 2.37.2-4ubuntu3.6, not all util-linux libraries.
# Ubuntu pool/main/u/util-linux/util-linux_2.37.2-4ubuntu3.6.dsc SHA256:
# e2b458d2005c328b0187ded5acac81c530cca8bf164f7c20b8370d02c4ffaebc.
# Its debian/copyright exactly matches the retained CI fixture. The upstream
# libuuid/COPYING and libuuid/src/* grants are BSD-3-Clause. The runtime source
# list in libuuid/src/Makemodule.am also includes lib/randutils.c (explicit
# BSD-3-Clause header, despite Debian's stale LGPL stanza), lib/md5.c and
# lib/sha1.c (public domain). No distro patch changes those runtime sources.
# Require the COMPLETE reviewed notice, not a BSD keyword or a selected stanza:
# any new override, changed grant, unknown layout, or source version needs
# another review even if the notice stays unchanged.
LIBUUID_COPYRIGHT_SHA256 = "2c447817698777e3b2365a5afe2a58ececb85367dfdf0ea2c0df49add90e93eb"
LIBUUID_SOURCE_VERSION = "2.37.2-4ubuntu3.6"
# The matching source's libblkid/COPYING and libmount/COPYING explicitly grant
# LGPL-2.1-or-later. Both share this exact package/version/complete notice.
# Do not classify either library by the GPL utilities' default DEP5 stanza.
UTIL_LINUX_REVIEWED_RUNTIMES = frozenset({"libuuid.so.1", "libblkid.so.1", "libmount.so.1"})


GPL_TERMS = re.compile(r"\bGPL(?:v?\d|[-\s]|\b)|GNU GENERAL PUBLIC LICENSE", re.I)
LGPL_TERMS = re.compile(r"\bLGPL(?:v?\d|[-\s]|\b)|GNU (?:LESSER|LIBRARY) GENERAL PUBLIC LICENSE", re.I)
# Standard exceptions that permit use of the covered file outside GPL works.
GPL_EXCEPTIONS = re.compile(r"\bwith\s+(?:bison|autoconf|distribution|libtool|linux-syscall-note)\s+exception\b", re.I)

# DEP5 override paths that are packaging, build system, documentation, tests,
# examples, programs or scripts rather than shared-library code. A tripwire
# heuristic: anything else with a GPL-only grant still needs review.
NONRUNTIME_DIRS = frozenset({"debian", "doc", "docs", "man", "po", "test", "tests", "testsuite",
                             "examples", "example", "contrib", "programs", "tools", "scripts", "perl", "coverage"})
# Build-system directories can hold compiled snippets: exempt only non-source
# files there (a "build-aux/runtime.c" still needs review).
BUILD_SYSTEM_DIRS = frozenset({"build-aux", "m4"})
SOURCE_SUFFIXES = (".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".m", ".mm", ".s", ".S", ".asm", ".inc")
NONRUNTIME_NAMES = frozenset({"aclocal.m4", "ar-lib", "autogen.sh", "compile", "config.guess", "config.sub",
                              "configure", "depcomp", "GNUmakefile", "install-sh", "ltmain.sh", "maint.mk",
                              "mdate-sh", "missing", "test-driver", "texinfo.tex", "ylwrap"})
NONRUNTIME_SUFFIXES = (".m4", ".pl", ".pm", ".py", ".sh", ".xsl", ".html", ".texi")
NONRUNTIME_PREFIXES = ("Makefile", "Doxyfile", "test-", "test_")
# Copies of Linux kernel UAPI headers: userspace use is the kernel's
# syscall-note boundary, whether or not Debian repeats the note.
UAPI_HEADER_DIRS = frozenset({"linux", "drm-uapi"})

# Reviewed GPL-only overrides that are not built into the shipped libraries,
# by Debian source package. A trailing "/" covers that directory. Any other
# GPL-only override in these sources still requires review.
REVIEWED_NONRUNTIME_OVERRIDES = {
    "xz-utils": {"lib/*": "getopt_long replacement for the xz command-line tools; liblzma is src/liblzma (public domain)",
                 "extra/scanlzma/scanlzma.c": "standalone scanlzma utility"},
    "nettle": {"getopt*": "getopt replacement for the nettle command-line tools, not libnettle/libhogweed"},
    "systemd": {"src/udev/": "udevd, udevadm and udev helper programs; libudev and libsystemd are src/libudev and src/libsystemd",
                "src/basic/ioprio.h": "Linux I/O-priority syscall ABI definitions (constants, macros and inline syscall "
                                      "wrappers copied from the kernel header); reviewed as an interface definition"},
    "lcms2": {"plugins/fast_float/*": "separately built fast-float plugin, not part of liblcms2"},
    "gstreamer1.0": {"gst/parse/grammar.tab.h": "Bison-generated parser header covered by Bison's skeleton exception"},
    "enchant-2": {"providers/applespell_checker.mm": "macOS AppleSpell provider, not built for Linux",
                  "build-aux/snippet/": "gnulib snippet headers (macro definitions only); gnulib's module metadata "
                                        "licenses them LGPLv2+ for library use"},
    "libunistring": {"woe32dll/*": "Windows DLL support, not built for Linux"},
    "gdk-pixbuf": {"thumbnailer/*": "gdk-pixbuf-thumbnailer program, not the library or its loaders"},
}

# Reviewed whole-notice classifications (Ubuntu jammy, CI 39154597775), bound
# to the exact notice SHA-256 and library basenames. Changed text, another
# library or a missing source needs another review.
REVIEWED_LIBRARY_NOTICES = {
    # Non-DEP5 MIT Kerberos notice; its GPL text is an alternative a recipient
    # may choose ("either the BSD or the GPL"), not a requirement.
    "krb5": ("4a2d321ab57260e8de4b67bde8cff76c07d28be69c2d8b22dfc2bfa42f5c41b9",
             frozenset({"libgssapi_krb5.so.2", "libk5crypto.so.3", "libkrb5.so.3", "libkrb5support.so.0"}),
             "notice-and-exact-source-preserved"),
    # The GPL-2+ default covers the keyctl tools; libkeyutils is built from
    # keyutils.c/keyutils.h, which the "keyutils.*" stanza grants LGPL-2+.
    "keyutils": ("6ab5c541723d8211cab7ebc1643d53aa51c4863c1c838e4625d797ece9472ee8",
                 frozenset({"libkeyutils.so.1"}), "lgpl-source-required"),
    # Library sources (*.c *.h) are "LGPL-3+ or GPL-2+". The GPL-3+ stanzas
    # cover the idn2 tool, docs and FSF build/gnulib files of an older layout.
    "libidn2": ("41702469f28e8ff406345e3d1dd0c741f11bdfca319264f67036efd6aaa79e4b",
                frozenset({"libidn2.so.0"}), "lgpl-source-required"),
    # Debian writes "BSD-3-clause and GPL-2"; the upstream source headers say
    # "You may select, at your option, one of the above-listed licenses."
    "libzstd": ("8cf66791fbe72801cb1d701c832b7e395dad0000bb9699dc42df94b49d699e91",
                frozenset({"libzstd.so.1"}), "notice-and-exact-source-preserved"),
}


def requires_gpl(grant):
    """True when every choice in a DEP5 license expression needs plain GPL.

    DEP5 precedence: ", and" / ", or" bind loosest, then "or", then "and".
    """
    for separator, combine in ((r",\s*and\s+", any), (r",\s*or\s+", all), (r"\s+or\s+", all), (r"\s+and\s+", any)):
        parts = re.split(separator, grant.strip(), flags=re.I)
        if len(parts) > 1:
            return combine(requires_gpl(part) for part in parts)
    return bool(GPL_TERMS.search(grant) and not LGPL_TERMS.search(grant) and not GPL_EXCEPTIONS.search(grant))


def nonruntime_file(pattern, reviewed=()):
    pattern = pattern.removeprefix("./")
    if pattern in reviewed or any(entry.endswith("/") and pattern.startswith(entry) for entry in reviewed):
        return True
    *dirs, name = pattern.split("/")
    return (any(part in NONRUNTIME_DIRS for part in dirs) or name in NONRUNTIME_NAMES
            or (any(part in BUILD_SYSTEM_DIRS for part in dirs) and not name.endswith(SOURCE_SUFFIXES))
            or name.endswith(NONRUNTIME_SUFFIXES) or name.startswith(NONRUNTIME_PREFIXES)
            or (name.endswith(".h") and bool(dirs) and dirs[-1] in UAPI_HEADER_DIRS))


def license_policy(text, source_package, basename, *, source_version=None):
    """Reject GPL-only/AGPL libraries, not LGPL runtime libraries.

    Debian copyright can cover GPL build utilities alongside LGPL libraries.
    Keep that complete text and exact sources; do not reject LGPL because its
    notice incorporates GPL text. Reviewed exceptions cover GCC runtime libs,
    libffi's non-DEP5 MIT grant, and exact-version/hash-bound util-linux runtimes,
    never arbitrary mixed-license sources.
    This heuristic is a tripwire, not a binary-level legal determination.
    """
    # Never let a selected DEP5 default grant hide prohibited later stanzas.
    if re.search(r"\bAGPL(?:v?\d|[-\s]|\b)|Affero General Public", text, re.I):
        raise ValueError("AGPL library is prohibited: " + basename)
    evidence = text
    file_stanzas = []
    default_stanza = None
    if re.search(r"(?mi)^Format:.*copyright-format", text):
        # Read every Files stanza: the default grant cannot settle later
        # source-file overrides. License-definition prose is not a file grant.
        file_stanzas = [control for paragraph in re.split(r"\n\s*\n", text)
                        if (control := Parser().parsestr(paragraph)).get("Files")]
        for control in file_stanzas:
            if control.get("Files", "").strip() == "*" and control.get("License"):
                evidence = control["License"].splitlines()[0]
                default_stanza = control
                break
    if source_package in REVIEWED_LIBRARY_NOTICES:
        digest, basenames, policy = REVIEWED_LIBRARY_NOTICES[source_package]
        if basename not in basenames or hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise ValueError("Unrecognized " + basename + " notice for reviewed " + source_package + "; explicit review required")
        return policy
    if source_package == "util-linux" and basename in UTIL_LINUX_REVIEWED_RUNTIMES:
        if source_version != LIBUUID_SOURCE_VERSION:
            raise ValueError("Unrecognized " + basename + " runtime source version; explicit review required")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != LIBUUID_COPYRIGHT_SHA256:
            raise ValueError("Unrecognized " + basename + " runtime copyright; explicit review required")
        return "notice-and-exact-source-preserved"
    if source_package == "libffi" and re.fullmatch(r"libffi\.so(?:\.[0-9]+)*", basename):
        # Only this reviewed legacy layout is recognized. Require the entire
        # attributed runtime grant before Documentation; absent/changed terms
        # require review even if the damaged notice no longer mentions GPL.
        sections = re.split(r"(?m)^\s*Documentation:\s*$", text, maxsplit=1)
        runtime = re.split(r"(?m)^License:\s*$", sections[0], maxsplit=1)
        if (evidence != text or len(sections) != 2 or len(runtime) != 2
                or runtime[1].split() != LIBFFI_RUNTIME_GRANT.split()):
            raise ValueError("Unrecognized libffi runtime copyright; explicit review required: " + basename)
        return "notice-and-exact-source-preserved"
    reviewed = REVIEWED_NONRUNTIME_OVERRIDES.get(source_package, {})
    for control in file_stanzas:
        if control is default_stanza:
            continue  # The default grant is classified below (including GCC).
        grant = control.get("License", "").splitlines()[0] if control.get("License") else ""
        # A non-GPL alternative or standard exception is not GPL-only. Otherwise
        # only build/tool/doc/test files or reviewed paths are permitted.
        if GPL_TERMS.search(grant) and not LGPL_TERMS.search(grant) and requires_gpl(grant):
            unexcused = [name for name in control["Files"].split() if not nonruntime_file(name, reviewed)]
            if unexcused:
                raise ValueError("GPL-only file override requires explicit review; not permitted: "
                                 + basename + " (" + ", ".join(unexcused) + ")")
    gpl = GPL_TERMS.search(evidence)
    lgpl = LGPL_TERMS.search(evidence)
    gcc = (re.fullmatch(r"gcc-\d+", source_package or "")
           and re.match(r"lib(?:gcc_s|stdc\+\+)\.so(?:\.|$)", basename)
           and re.search(r"GCC (?:RUNTIME LIBRARY |runtime )?EXCEPTION", text, re.I))
    if gcc:
        return "gcc-runtime-exception-source-required"
    if lgpl:
        return "lgpl-source-required"
    # Expression parsing applies only to a DEP5 grant line, never to prose.
    if gpl and (default_stanza is None or requires_gpl(evidence)):
        raise ValueError("GPL-only library requires explicit review; not permitted: " + basename)
    return "notice-and-exact-source-preserved"


def common_license_file(common, name):
    """Resolve a referenced common-license name to an existing Debian file.

    Some copyrights use SPDX-style names (pango's "GPL-2.0") where Debian
    ships "GPL-2". Only drop "+"/"-only"/"-or-later" and a GNU family ".0";
    never map to another version (LGPL-2.0 is not LGPL-2.1).
    """
    name = name.rstrip(".")
    candidates = [name]
    base = re.sub(r"(?:\+|-only|-or-later)$", "", name)
    candidates.append(base)
    if re.fullmatch(r"(?:L?GPL|GFDL)-\d+\.0", base):
        candidates.append(base[:-2])
    return next((common / c for c in candidates if (common / c).is_file()), None)


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
    referenced = re.findall(r"/usr/share/common-licenses/([\w.+-]+)", source.read_text(encoding="utf-8", errors="replace"))
    for name in referenced:
        if common_license_file(common, name) is None:
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
    if not any("bootloader" in checked_file(output, p).read_text(encoding="utf-8", errors="replace").lower()
               and "exception" in checked_file(output, p).read_text(encoding="utf-8", errors="replace").lower() for p in bootloader_notices):
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
    policy_issues = []

    def classify(owner, text, basename):
        try:
            policy = license_policy(text, owner.get("source_package", owner["name"]), basename,
                                    source_version=owner.get("source_version"))
            if owner["kind"] == "wheel" and policy == "lgpl-source-required":
                raise ValueError("Copyleft wheel requires a reviewed exact-source collector: " + owner["name"])
            return policy
        except ValueError as error:
            policy_issues.append({"basename": basename, "package": owner["name"],
                                  "source_version": owner.get("source_version"), "error": str(error)})
            return "unapproved"

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
            owner["policy"] = classify(owner, owner.get("license") or "", path.name)
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
                try:
                    debian_cache[key] = debian_notices(owner, output)
                except ValueError as error:
                    # Record with policy failures; never approve without notices.
                    debian_cache[key] = error
            if isinstance(debian_cache[key], ValueError):
                policy_issues.append({"basename": path.name, "package": owner["name"],
                                      "source_version": owner.get("source_version"), "error": str(debian_cache[key])})
                owner["notices"] = []
                owner["policy"] = "unapproved"
            else:
                owner["notices"] = debian_cache[key]
                copyright_path = next(p for p in owner["notices"] if p.endswith("/copyright"))
                copyright_text = checked_file(output, copyright_path).read_text(encoding="utf-8", errors="replace")
                owner["policy"] = classify(owner, copyright_text, path.name)
            owner["original_sha256"] = sha256(Path(owner["original"]))
            if owner["policy"] != "unapproved":
                sources_needed.add((owner["source_package"], owner["source_version"]))
        libraries.append({**owner, "path": path.relative_to(worker).as_posix() if role == "shipped-worker" else str(path),
                          "basename": path.name, "role": role, "sha256": sha256(path)})
    if policy_issues:
        # Finish the classification pass, but NEVER return an approved inventory
        # or fetch sources/package binaries while any dependency is unresolved.
        report = output / "linux/prebundle-license-review.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"approved": False, "issues": policy_issues,
                                      "libraries": libraries}, indent=2), encoding="utf-8")
        raise ValueError("Dependency license review failed: " + "; ".join(item["error"] for item in policy_issues))
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
        if record["kind"] == "debian" and record.get("source_package") == "util-linux" and path.name in UTIL_LINUX_REVIEWED_RUNTIMES:
            # Recheck this version-bound exception; a stored policy decision
            # does not establish that the packaged runtime was reviewed.
            copyright_path = next((p for p in record["notices"] if p.endswith("/copyright")), None)
            if copyright_path is None:
                raise ValueError("Missing reviewed util-linux runtime copyright; explicit review required: " + path.name)
            license_policy(checked_file(notices, copyright_path).read_text(encoding="utf-8", errors="replace"),
                           record["source_package"], path.name, source_version=record.get("source_version"))
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
