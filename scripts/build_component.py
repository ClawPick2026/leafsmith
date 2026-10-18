#!/usr/bin/env python3
"""Build optional, app-local engine ZIPs; never publishes or edits the registry."""
import hashlib
import json
from pathlib import Path
import stat
import re
import zipfile
import os
import shutil
import subprocess
import email.parser

MAX_DOWNLOAD = 750 * 1024 * 1024
MAX_EXTRACTED = 2 * 1024 * 1024 * 1024
MAX_FILES = 20000
SNAPSHOT = "https://snapshot.ubuntu.com/ubuntu/20261001T000000Z/"
FFMPEG_SOURCES = [
    {"name": "ffmpeg-7.1.5.tar.xz", "url": "https://ffmpeg.org/releases/ffmpeg-7.1.5.tar.xz", "sha256": "de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f"},
    {"name": "libvpx-1.15.2.tar.gz", "url": "https://github.com/webmproject/libvpx/archive/refs/tags/v1.15.2.tar.gz", "sha256": "26fcd3db88045dee380e581862a6ef106f49b74b6396ee95c2993a260b4636aa"},
    {"name": "opus-1.5.2.tar.gz", "url": "https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz", "sha256": "65c1d2f78b9f2fb20082c38cbe47c951ad5839345876e46941612ee87f9a7ce1"},
]


# Downloaded and independently hashed during recipe preparation; no unofficial binaries.
WINDOWS_OCR_SOURCES = [
    {"name": "tesseract-5.5.3.tar.gz", "url": "https://codeload.github.com/tesseract-ocr/tesseract/tar.gz/refs/tags/5.5.3", "sha256": "9218e62793116d42a9f6d14cd9348518b27f382096eea3d0f2d1a24616bb5884"},
    {"name": "leptonica-1.87.0.tar.gz", "url": "https://codeload.github.com/DanBloomberg/leptonica/tar.gz/refs/tags/1.87.0", "sha256": "fa2b40c5caea96d1bb93a97486262aed8731b69ce25a84a6bf5d25323e33f631"},
    {"name": "zlib-1.3.2.tar.xz", "url": "https://zlib.net/zlib-1.3.2.tar.xz", "sha256": "d7a0654783a4da529d1bb793b7ad9c3318020af77667bcae35f95d0e42a792f3"},
    {"name": "libpng-1.6.59.tar.gz", "url": "https://codeload.github.com/pnggroup/libpng/tar.gz/refs/tags/v1.6.59", "sha256": "2540302a1844ad2b2b501977abecfa850f265f97b78f065a712ab4074a89f5b5"},
]
TESSDATA_BASE = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/65727574dfcd264acbb0c3e07860e4e9e9b22185/"
WINDOWS_OCR_DATA = [
    {"name": "eng.traineddata", "url": TESSDATA_BASE + "eng.traineddata", "sha256": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"},
    {"name": "osd.traineddata", "url": TESSDATA_BASE + "osd.traineddata", "sha256": "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff"},
    {"name": "tessdata-LICENSE", "url": TESSDATA_BASE + "LICENSE", "sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"},
]


OFFICE_VERSION = "26.2.7.1"
OFFICE_CANDIDATE = {
    "releaseChannel": "prerelease",
    "displayName": "LibreOffice conversion (26.2.7.1 pre-release candidate)",
    "dependencyBaseline": {"libpng": "1.6.59", "libpngUpgradeCommit": "fd76bd2515f0d4e69ed227834ee355bf6a6d7f88"},
    "upstreamReleasePolicy": "https://www.libreoffice.org/download/pre-releases/",
}
OFFICE_BASE = "https://downloadarchive.documentfoundation.org/libreoffice/old/26.2.7.1/"
WINDOWS_OFFICE_INSTALLER = {"name": "LibreOffice_26.2.7.1_Win_x86-64.msi", "url": OFFICE_BASE + "win/x86_64/LibreOffice_26.2.7.1_Win_x86-64.msi", "sha256": "82edb4c85605bf38420f461596c5e4eb625afbe6557bd6c7bfa2c470b430a8c7"}
LINUX_OFFICE_INSTALLER = {"name": "LibreOffice_26.2.7.1_Linux_x86-64_deb.tar.gz", "url": OFFICE_BASE + "deb/x86_64/LibreOffice_26.2.7.1_Linux_x86-64_deb.tar.gz", "sha256": "7cc840bd089f4779636cb2340f33786e71ce66669fdfbe36fe5c7322edc186ee"}
WINDOWS_OFFICE_SOURCES = [
    {"name": "libreoffice-26.2.7.1.tar.xz", "url": OFFICE_BASE + "src/libreoffice-26.2.7.1.tar.xz", "sha256": "3ce4475c3e8c27450d667d83bf2dd9e99a8070d190363286022cf392d4eaec17"},
    {"name": "libreoffice-dictionaries-26.2.7.1.tar.xz", "url": OFFICE_BASE + "src/libreoffice-dictionaries-26.2.7.1.tar.xz", "sha256": "b8c73d520b1b6f65e1eed838d903334dbc68aa57c729049af74cac47db14cafd"},
    {"name": "libreoffice-help-26.2.7.1.tar.xz", "url": OFFICE_BASE + "src/libreoffice-help-26.2.7.1.tar.xz", "sha256": "cbe017cfb3ebd15bcffec2d3b646b0414a4b62c2a8eedb9c0d2dc7568dfc6843"},
    {"name": "libreoffice-translations-26.2.7.1.tar.xz", "url": OFFICE_BASE + "src/libreoffice-translations-26.2.7.1.tar.xz", "sha256": "781fc87e10424b510ee095480f152c4ed044e6b9a98e2a07020584bfe7691ac8"},
]


WINDOWS_OFFICE_CRT = [
    {"name": "concrt140.dll", "sha256": "34b64fba6f029a630e773a9cc323720e2250f36d049c2a2e3d8b202feece026d"},
    {"name": "msvcp140.dll", "sha256": "157c2531a5bda76bef11d208c4aa704bf6ac6b5d3435b86b2b93dba8f0701600"},
    {"name": "msvcp140_1.dll", "sha256": "13af1868c5c66d17526f3a74f3cbac76c279f36ca73259f896120ff72073e02b"},
    {"name": "msvcp140_2.dll", "sha256": "44107c382321d49e80e3622794390e3ec89eb332a542a83a6d474c6e164c7460"},
    {"name": "msvcp140_atomic_wait.dll", "sha256": "ece7c9fa921a40e7ecb35eb6f6858d03b6c2a0c77911f6e71ae9715cc25dbbdc"},
    {"name": "msvcp140_codecvt_ids.dll", "sha256": "27ff490ee875ce357dcb40686905d7ca94cd5be1cf2fc3fd7b1d3f0840878d6e"},
    {"name": "vcruntime140.dll", "sha256": "10153b02aa10a8ecb8c71b6d53185651b7a94c96e3a2ebec659d62f512fb97a6"},
    {"name": "vcruntime140_1.dll", "sha256": "3784622569df61db345062f2563117038c52f3254325282fcac703ddf026e623"},
]
for _pin in WINDOWS_OFFICE_CRT:
    _pin["member"] = _pin["name"] + "_amd64.DFEFC2FE_EEE6_424C_841B_D4E66F0C84A3"


def build_plan(component, platform):
    if platform not in {"windows-x86_64", "linux-x86_64"}:
        raise ValueError("Only native Windows/Linux x86_64 builders are supported")
    if component == "ffmpeg":
        return {"version": "7.1.5-vpx1.15.2-opus1.5.2", "sources": FFMPEG_SOURCES,
                "configure": ["--disable-gpl", "--disable-nonfree", "--disable-autodetect", "--disable-doc",
                              "--disable-debug", "--disable-shared", "--enable-static", "--enable-libvpx", "--enable-libopus"]}
    if platform == "windows-x86_64" and component == "tesseract":
        return {"builder": "cmake-msvc-static", "version": "5.5.3-lept1.87.0-png1.6.59-zlib1.3.2-data4.1.0",
                "sources": WINDOWS_OCR_SOURCES, "data": WINDOWS_OCR_DATA, "imageCodecs": ["PNG", "PNM", "BMP"],
                "runtimeNotices": [{"name": "MSVC-2022-license.docx", "url": "https://visualstudio.microsoft.com/wp-content/uploads/2021/11/Visual-Studio-2022-Enterprise-Professional-License-EN.docx", "sha256": "9c0cd52b20db9d081854c75bd1b50c75514b8f8cb09c8cad15e89d90b97b5bf3"}]}
    if platform == "windows-x86_64" and component == "libreoffice":
        return {**OFFICE_CANDIDATE, "builder": "official-msi-admin-extract-ci-only", "version": OFFICE_VERSION,
                "installer": WINDOWS_OFFICE_INSTALLER, "sources": WINDOWS_OFFICE_SOURCES,
                "crtMembers": WINDOWS_OFFICE_CRT, "preserveEntireRuntime": True}
    if platform == "linux-x86_64" and component == "libreoffice":
        # Jammy's tracker has NOT confirmed the Oct 2026 backports. Never fall
        # back to its 7.3 engine; only use the distro for this audited ELF closure.
        return {**OFFICE_CANDIDATE, "builder": "official-debs-app-local", "version": OFFICE_VERSION,
                "installer": LINUX_OFFICE_INSTALLER, "sources": WINDOWS_OFFICE_SOURCES,
                "snapshot": SNAPSHOT, "distribution": "jammy",
                "packages": ["fonts-dejavu-core", "libx11-6", "libx11-xcb1", "libxext6", "libxinerama1",
                             "libxrandr2", "libxrender1", "libice6", "libsm6", "libavahi-client3", "libavahi-common3",
                             "libcairo2", "libcups2", "libdbus-1-3", "libfontconfig1", "libfreetype6", "libgcc-s1",
                             "libglib2.0-0", "libgssapi-krb5-2", "libkrb5-3", "libcom-err2", "libnspr4", "libnss3",
                             "libstdc++6", "zlib1g"]}
    if platform == "linux-x86_64" and component == "tesseract":
        return {"snapshot": SNAPSHOT, "distribution": "jammy", "packages": ["tesseract-ocr", "tesseract-ocr-eng", "tesseract-ocr-osd"]}
    raise ValueError(f"No verified builder for {component}/{platform}; use an existing system engine")


def fetch_source(pin, cache):
    import urllib.request
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) or not pin["url"].startswith("https://") or Path(pin["name"]).name != pin["name"]:
        raise ValueError("An HTTPS source with an exact SHA-256 pin is required")
    path = cache / pin["name"]
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".partial")
        try:
            with urllib.request.urlopen(pin["url"], timeout=180) as response, temporary.open("wb") as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
                    if target.tell() > MAX_DOWNLOAD:
                        raise ValueError("Source download exceeds size limit")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != pin["sha256"]:
            raise ValueError(f"Source checksum mismatch: {path}; remove cache only after investigating")
    return path


def unpack_source(archive, destination):
    import tarfile
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        entries = source.getmembers()
        for entry in entries:
            name = entry.name.rstrip("/")
            if name.startswith("/") or "\\" in name or ":" in name or ".." in name.split("/") or not (entry.isfile() or entry.isdir()):
                raise ValueError(f"Unsafe source archive entry: {entry.name}")
        source.extractall(destination, members=entries, filter="data")
    return destination


def office_external_sources(archive):
    """Read checksums from the pinned source, without evaluating arbitrary Make code.

    Collect ALL listed externals (a superset of the Windows build), not just core.
    Upstream's patches and Windows build configurations remain in the core archive.
    """
    import tarfile
    with tarfile.open(archive) as source:
        member = source.getmember(f"libreoffice-{OFFICE_VERSION}/download.lst")
        if not member.isfile() or member.size > 1024 * 1024:
            raise ValueError("Invalid LibreOffice download.lst")
        with source.extractfile(member) as stream:
            text = stream.read().decode("utf-8")
    values = dict(re.findall(r"^([A-Z][A-Z0-9_]*)\s*:=\s*([^\n#]+)", text, re.MULTILINE))
    pins = []
    for key, value in values.items():
        match = re.fullmatch(r"(.+)_(TARBALL|TTF|JAR)", key)
        if not match:
            continue
        for _ in range(10):
            updated = re.sub(r"\$\(([A-Z][A-Z0-9_]*)\)", lambda m: values.get(m[1], m[0]).strip(), value)
            if updated == value:
                break
            value = updated
        value = value.strip()
        digest = values.get(match[1] + "_SHA256SUM", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_+.\-]+", value) or value in {".", ".."} or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Unresolved or unsafe LibreOffice source pin: {key}")
        kind = "src" if match[2] == "TARBALL" else "extern"
        pins.append({"name": value, "url": f"https://dev-www.libreoffice.org/{kind}/{value}", "sha256": digest})
    if not pins or len({p["name"] for p in pins}) != len(pins):
        raise ValueError("Empty or conflicting LibreOffice external source manifest")
    return pins


def ocr_cmake_options(project, prefix):
    common = ["-DCMAKE_POLICY_DEFAULT_CMP0091=NEW", "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
              "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF", f"-DCMAKE_INSTALL_PREFIX={prefix}",
              f"-DCMAKE_PREFIX_PATH={prefix}", "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF",
              "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF"]
    options = {
        "zlib": ["-DZLIB_BUILD_SHARED=OFF", "-DZLIB_BUILD_STATIC=ON", "-DZLIB_BUILD_TESTING=OFF", "-DZLIB_INSTALL=ON"],
        "libpng": ["-DPNG_SHARED=OFF", "-DPNG_STATIC=ON", "-DPNG_TESTS=OFF", "-DPNG_TOOLS=OFF"],
        "leptonica": ["-DSW_BUILD=OFF", "-DBUILD_PROG=OFF", "-DSTRICT_CONF=ON", "-DENABLE_ZLIB=ON", "-DENABLE_PNG=ON",
                      *[f"-DENABLE_{codec}=OFF" for codec in ["GIF", "JPEG", "TIFF", "WEBP", "OPENJPEG"]]],
        "tesseract": ["-DWIN32_MT_BUILD=ON", "-DDISABLE_ARCHIVE=ON", "-DDISABLE_CURL=ON",
                      "-DDISABLE_TIFF=ON", "-DOPENMP_BUILD=OFF", "-DENABLE_NATIVE=OFF", "-DGRAPHICS_DISABLED=ON",
                      "-DBUILD_TRAINING_TOOLS=OFF", "-DBUILD_TESTS=OFF", "-DINSTALL_CONFIGS=ON"],
    }
    if project not in options:
        raise ValueError(f"Unknown OCR source project: {project}")
    if project != "zlib":
        common += [f"-DZLIB_LIBRARY={prefix / 'lib/zs.lib'}", f"-DZLIB_INCLUDE_DIR={prefix / 'include'}"]
    if project in {"leptonica", "tesseract"}:
        common += [f"-DPNG_LIBRARY={prefix / 'lib/libpng16_static.lib'}", f"-DPNG_PNG_INCLUDE_DIR={prefix / 'include'}"]
    return common + options[project]


# Windows 10/11 system DLLs only. MSVC/MinGW redistributables are NOT OS DLLs.
WINDOWS_SYSTEM_DLLS = set("""activeds advapi32 avrt bcrypt bcryptprimitives cabinet cfgmgr32 clbcatq comctl32 comdlg32
crypt32 cryptbase cryptnet cryptsp d2d1 d3d9 d3d10 d3d10_1 d3d11 d3d12 d3dcompiler_47 dbghelp dnsapi
 dwrite dwmapi dxgi dxcore gdi32 gdiplus hid imagehlp imm32 iphlpapi kernel32 kernelbase mpr msacm32
msimg32 msvcrt mswsock ncrypt netapi32 normaliz ntdll ole32 oleacc oleaut32 opengl32 powrprof propsys
psapi rasapi32 rpcrt4 secur32 setupapi shell32 shcore shlwapi sspicli ucrtbase urlmon user32 userenv
usp10 uxtheme version winhttp wininet winmm winscard winspool wintrust wldap32 ws2_32 wtsapi32
fontsub msi oledlg wer wsock32 httpapi mfplat mfplay mfreadwrite""".split())
# Exact optional module names audited in this pinned official MSI. Preserve their
# notices/bytes, but do not claim Java, .NET automation or scanner support.
OFFICE_NONCONVERSION_MODULES = {
    "officebean.dll", "twain32shim.exe", "spsupp_x86.dll", "cli_uno.dll",
    *[prefix + name + ".dll" for prefix in ["", "policy.1.0."]
      for name in ["cli_basetypes", "cli_cppuhelper", "cli_oootypes", "cli_ure", "cli_uretypes"]],
}
OFFICE_PACKAGING_LAUNCHERS = {
    "office/program/python-core-3.12.15/lib/" + suffix
    for suffix in [*["setuptools/" + name + ".exe" for name in ["gui-arm64", "gui", "cli-arm64", "cli", "cli-32", "gui-32"]],
                   *["pip/_vendor/distlib/" + name + ".exe" for name in ["t32", "w64-arm", "t64-arm", "w32"]]]
}


def pe_dependencies(path):
    """Parse normal + delay imports of an AMD64 PE; never execute a runner DLL."""
    import struct
    data = Path(path).read_bytes()
    try:
        if data[:2] != b"MZ":
            raise ValueError("missing MZ header")
        offset = struct.unpack_from("<I", data, 0x3c)[0]
        if data[offset:offset + 4] != b"PE\0\0":
            raise ValueError("missing PE signature")
        machine, sections = struct.unpack_from("<HH", data, offset + 4)
        optional_size = struct.unpack_from("<H", data, offset + 20)[0]
        optional = offset + 24
        if machine != 0x8664 or struct.unpack_from("<H", data, optional)[0] != 0x20b:
            raise ValueError("Windows engine must be a native x86_64 PE32+ binary")
        if optional_size < 240 or not 0 < sections < 100:
            raise ValueError("invalid PE section/data-directory table")
        table = optional + optional_size
        ranges = [struct.unpack_from("<IIII", data, table + i * 40 + 8) for i in range(sections)]
        def rva(value):
            for virtual_size, address, raw_size, raw_offset in ranges:
                if address <= value < address + max(virtual_size, raw_size):
                    result = raw_offset + value - address
                    if value - address >= raw_size or result >= len(data):
                        break
                    return result
            raise ValueError("PE import RVA is outside file sections")
        names = set()
        for index, width, name_field in [(1, 20, 12), (13, 32, 4)]:
            address, size = struct.unpack_from("<II", data, optional + 112 + index * 8)
            if not address:
                continue
            start = rva(address)
            if size > 1024 * 1024 or start + size > len(data):
                raise ValueError("unbounded PE import table")
            terminated = False
            for cursor in range(start, start + size, width):
                descriptor = data[cursor:cursor + width]
                if len(descriptor) != width:
                    raise ValueError("truncated PE import descriptor")
                if not any(descriptor):
                    terminated = True
                    break
                if index == 13 and struct.unpack_from("<I", descriptor)[0] != 1:
                    raise ValueError("Unsupported non-RVA delay import descriptor")
                name_start = rva(struct.unpack_from("<I", descriptor, name_field)[0])
                end = data.find(b"\0", name_start, name_start + 256)
                if end < 0:
                    raise ValueError("unterminated PE DLL name")
                name = data[name_start:end].decode("ascii").lower()
                if not re.fullmatch(r"[a-z0-9_.+\-]+\.(?:dll|drv|pyd)", name):
                    raise ValueError("unsafe PE DLL name")
                names.add(name)
            if not terminated:
                raise ValueError("unterminated PE import table")
        return sorted(names)
    except (struct.error, UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"Invalid Windows runtime {path}: {error}") from error


def audit_windows_runtime(payload, component=None):
    files = [p for p in sorted(payload.rglob("*")) if p.is_file() and p.suffix.lower() in {".exe", ".dll", ".com", ".bin", ".pyd"}]
    excluded = {p for p in files if component == "libreoffice" and (
        (p.parent.relative_to(payload).as_posix() == "office/program" and p.name.lower() in OFFICE_NONCONVERSION_MODULES)
        or p.relative_to(payload).as_posix() in OFFICE_PACKAGING_LAUNCHERS)}
    available = {p.name.lower() for p in files if p not in excluded}
    result = {}
    for path in files:
        if path in excluded:
            result[path.relative_to(payload).as_posix()] = {"excludedFromHeadlessConversionAudit": "Optional Java/.NET/scanner integration or cross-architecture Python packaging launcher; not supported headless functionality"}
            continue
        if path.suffix.lower() == ".bin":
            with path.open("rb") as stream:
                if stream.read(2) != b"MZ":
                    continue
        dependencies = pe_dependencies(path)
        for name in dependencies:
            if name not in available and name.rsplit(".", 1)[0] not in WINDOWS_SYSTEM_DLLS and not name.startswith(("api-ms-win-", "ext-ms-win-")):
                raise ValueError(f"Incomplete Windows runtime: {path.name} imports {name}; refusing a pack that borrows runner-installed DLLs. Supply an audited app-local runtime with its notices/sources first.")
        result[path.relative_to(payload).as_posix()] = dependencies
    if not result:
        raise ValueError("No native Windows executables to audit")
    return result


def elf_dependencies(path):
    """Read bounded loader-authoritative ELF64 metadata; never execute ldd.

    Section headers are deliberately irrelevant (and may be absent/decoys).
    Dynamic virtual addresses must map uniquely to file-backed PT_LOAD bytes.
    """
    import struct
    try:
        with Path(path).open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size

            def read(offset, length, limit):
                if offset < 0 or not 0 < length <= limit or offset + length > size:
                    raise ValueError("Unbounded or truncated ELF metadata")
                stream.seek(offset)
                content = stream.read(length)
                if len(content) != length:
                    raise ValueError("Truncated ELF metadata")
                return content

            header = read(0, 64, 64)
            kind, machine, version, _, offset = struct.unpack_from("<HHIQQ", header, 16)
            if header[:7] != b"\x7fELF\x02\x01\x01" or machine != 62 or header[7] not in {0, 3}:
                raise ValueError("Linux engine must be an x86_64 ELF64 little-endian binary")
            ehsize, width, count = struct.unpack_from("<HHH", header, 52)
            if kind not in {2, 3} or version != 1 or ehsize != 64 or width != 56 or not 0 < count <= 1024 or offset < 64:
                raise ValueError("Invalid ELF program header table/type")
            table = read(offset, width * count, 56 * 1024)
            segments = [struct.unpack_from("<IIQQQQQQ", table, i * width) for i in range(count)]
            loads = [s for s in segments if s[0] == 1]
            if not loads:
                raise ValueError("Missing ELF PT_LOAD mapping")
            for segment in segments:
                tag, flags, start, address, _, filesz, memsz, align = segment
                if tag not in {1, 2, 3}:
                    continue
                if filesz > memsz or start + filesz > size or address + memsz > 2**64:
                    raise ValueError("Invalid ELF segment bounds")
                if align not in {0, 1} and (align & (align - 1) or (address - start) % align):
                    raise ValueError("Invalid ELF segment alignment")
            ordered = sorted(loads, key=lambda s: s[3])
            if any(a[3] + a[6] > b[3] for a, b in zip(ordered, ordered[1:])):
                raise ValueError("Overlapping ELF PT_LOAD mappings")

            def mapped(address, length):
                candidates = [s[2] + address - s[3] for s in loads
                              if s[1] & 4 and s[3] <= address and address + length <= s[3] + s[5]]
                if length <= 0 or len(candidates) != 1:
                    raise ValueError("ELF metadata outside unique file-backed PT_LOAD mapping")
                return candidates[0]

            interpreters = [s for s in segments if s[0] == 3]
            if len(interpreters) > 1:
                raise ValueError("Duplicate ELF interpreter")
            interpreter = None
            if interpreters:
                segment = interpreters[0]
                if not 1 < segment[5] <= 256:
                    raise ValueError("Unbounded ELF interpreter")
                text = read(segment[2], segment[5], 256)
                # Ubuntu/glibc x86_64 baseline only; no arbitrary host interpreter.
                if text != b"/lib64/ld-linux-x86-64.so.2\0":
                    raise ValueError("Unsupported or unterminated ELF interpreter")
                interpreter = text[:-1].decode("ascii")

            dynamic = [s for s in segments if s[0] == 2]
            if len(dynamic) != 1:
                raise ValueError("Expected one ELF PT_DYNAMIC segment")
            segment = dynamic[0]
            if segment[5] % 16 or mapped(segment[3], segment[5]) != segment[2]:
                raise ValueError("Inconsistent ELF PT_DYNAMIC mapping")
            content = read(segment[2], segment[5], 1024 * 1024)
            entries = []
            for cursor in range(0, len(content), 16):
                tag, value = struct.unpack_from("<qQ", content, cursor)
                if tag == 0:
                    break
                entries.append((tag, value))
            else:
                raise ValueError("Unterminated ELF dynamic table")

            def single(tag):
                values = [value for key, value in entries if key == tag]
                if len(values) != 1:
                    raise ValueError(f"Missing or duplicate ELF dynamic tag {tag}")
                return values[0]

            string_size = single(10)
            strings = read(mapped(single(5), string_size), string_size, 16 * 1024 * 1024)
            needed, paths = [], {}
            for tag, value in entries:
                if tag not in {1, 15, 29}:
                    continue
                if value >= len(strings):
                    raise ValueError("Invalid ELF dynamic string offset")
                end = strings.find(b"\0", value)
                if end < 0:
                    raise ValueError("Unterminated ELF dynamic string")
                text = strings[value:end].decode("ascii")
                if tag == 1:
                    if not re.fullmatch(r"[A-Za-z0-9_.+\-]+", text) or text in {".", ".."}:
                        raise ValueError("Unsafe ELF dependency name")
                    needed.append(text)
                else:
                    if tag in paths:
                        raise ValueError("Duplicate ELF search-path tag")
                    paths[tag] = text.split(":")
            # DT_RUNPATH suppresses DT_RPATH, including an otherwise unsafe
            # decoy RPATH. Only loader-effective paths participate in resolution.
            runpath = paths.get(29)
            rpath = paths.get(15, []) if runpath is None else []
            flags1 = [value for tag, value in entries if tag == 0x6ffffffb]
            if len(flags1) > 1:
                raise ValueError("Duplicate ELF DT_FLAGS_1")
            return {"needed": sorted(set(needed)), "search": rpath if runpath is None else runpath,
                    "rpath": rpath, "runpath": runpath, "type": kind, "interpreter": interpreter,
                    "pie": bool(flags1 and flags1[0] & 0x08000000)}
    except (struct.error, UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"Invalid Linux runtime {path}: {error}") from error


def audit_linux_office(payload):
    # Only host glibc/loader are baseline dependencies; everything else is app-local.
    baseline = {"ld-linux-x86-64.so.2", "libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0",
                "librt.so.1", "libresolv.so.2", "libutil.so.1"}
    # These retained optional GUI/multimedia/Java integrations are never part of
    # headless conversion (SAL_USE_VCLPLUGIN=svp). No import filters are excluded.
    optional = {"liblibreofficekitgtk.so", "libavmediagtk.so", "libavmediaqt6.so", "libavmediagst.so", "libofficebean.so"}
    root = payload / "root"
    program = root / "opt/libreoffice26.2/program"
    exposed = [program, root / "usr/lib/x86_64-linux-gnu", root / "lib/x86_64-linux-gnu", root / "usr/lib", root / "lib"]
    excluded = {(program / name).resolve() for name in optional}
    native, result = {}, {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(payload.resolve()):
            raise ValueError(f"Escaping Linux runtime file: {path}")
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        metadata = elf_dependencies(path)
        relative = path.relative_to(payload).as_posix()
        if path.resolve() in excluded:
            result[relative] = {"excludedFromHeadlessConversionAudit": "Optional GUI/multimedia/Java integration; bytes/notices retained"}
            continue
        native[path.resolve()] = metadata

    searches = {}
    for path, metadata in native.items():
        search = []
        for entry in metadata["search"]:
            if not (entry == "$ORIGIN" or entry.startswith("$ORIGIN/")) or "$" in entry.removeprefix("$ORIGIN"):
                raise ValueError(f"Non-app-local or unsupported ELF search path: {path}: {entry}")
            directory = (path.parent / entry.removeprefix("$ORIGIN").lstrip("/")).resolve()
            if not directory.is_relative_to(payload.resolve()):
                raise ValueError(f"Escaping ELF search path: {path}: {entry}")
            search.append(directory)
        searches[path] = search
        result[path.relative_to(payload.resolve()).as_posix()] = metadata["needed"]

    # This static audit does not infer the eventual x86 CPU's capabilities.
    # Fail closed if glibc could prepend hardware-specific provider directories.
    for directory in {d for paths in searches.values() for d in paths} | set(exposed):
        if any((directory / name).is_dir() for name in ["glibc-hwcaps", "tls", "x86_64", "haswell", "xeon_phi", "avx512_1"]):
            raise ValueError(f"Unsupported hardware-specific ELF search directory: {directory}")

    # Audit every object as a possible plugin root as well as in each loader
    # ancestry. RPATH is inherited; RUNPATH applies only to direct dependencies.
    pending = [(path, ()) for path in native]
    visited = set()
    while pending:
        path, inherited = pending.pop()
        if (path, inherited) in visited:
            continue
        visited.add((path, inherited))
        if len(visited) > 100000:
            raise ValueError("Linux dependency search graph exceeds audit limit")
        metadata, search = native[path], searches[path]
        ancestry = tuple(dict.fromkeys([*(search if metadata["runpath"] is None else []), *inherited]))
        directories = [*ancestry, *exposed] if metadata["runpath"] is None else [*exposed, *search]
        for name in metadata["needed"]:
            # Do not flatten basenames: an invalid first hit must not be rescued
            # by a valid object later in the launcher's library search path.
            provider = next((d / name for d in directories if (d / name).exists()), None)
            if provider is not None:
                resolved = provider.resolve()
                if resolved in excluded:
                    raise ValueError(f"Incomplete Linux runtime: {path.name} imports excluded provider {name}")
                shared = native.get(resolved)
                if shared is None or shared["type"] != 3 or shared["interpreter"] is not None or shared["pie"]:
                    raise ValueError(f"Invalid Linux shared-object provider: {provider} for {path.name} imports {name}")
                pending.append((resolved, ancestry))
            elif name not in baseline:
                raise ValueError(f"Incomplete Linux runtime: {path.name} imports {name}; no runner-library fallback is allowed")
    if not result:
        raise ValueError("No native Linux executables to audit")
    return result


def create_pack(payload, output, metadata):
    payload, output = Path(payload), Path(output)
    required = {"id", "name", "version", "platform", "license", "executable"}
    if set(metadata) != required or metadata["id"] not in {"ffmpeg", "tesseract", "libreoffice", "whisper", "llama"}:
        raise ValueError("Invalid component metadata")
    if metadata["platform"] not in {"linux-x86_64", "windows-x86_64"} or not re.fullmatch(r"[A-Za-z0-9._-]+", metadata["version"]):
        raise ValueError("Invalid platform or version")
    paths = sorted(payload.rglob("*"))
    for path in paths:
        if path.is_symlink() and (not path.resolve().is_relative_to(payload.resolve()) or not path.resolve().is_file()):
            raise ValueError(f"Escaping, dangling or directory symlink: {path}")
        if not path.is_file() and not path.is_dir():
            raise ValueError(f"Unsupported special file: {path}")
    for relative in [metadata["executable"], *(p.relative_to(payload).as_posix() for p in paths)]:
        if not relative or relative.startswith("/") or "\\" in relative or ":" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
            raise ValueError(f"Unsafe archive path: {relative}")
    if not (payload / metadata["executable"]).is_file():
        raise ValueError("Component executable is missing")
    files = [p for p in paths if p.is_file()]
    if len(files) > MAX_FILES or sum(p.stat().st_size for p in files) > MAX_EXTRACTED:
        raise ValueError("Pack exceeds native installer limits")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{metadata['id']}-{metadata['version']}-{metadata['platform']}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for path in sorted(payload.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(payload).as_posix()
            entry = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            mode = 0o755 if relative == metadata["executable"] or path.stat().st_mode & 0o111 else 0o644
            entry.external_attr = (stat.S_IFREG | mode) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(entry, path.read_bytes())
    if archive.stat().st_size > MAX_DOWNLOAD:
        archive.unlink()
        raise ValueError("Pack download exceeds 750 MiB")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = dict(metadata, sha256=digest, downloadBytes=archive.stat().st_size)
    manifest_path = archive.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"archive": str(archive), "manifest": manifest, "manifestPath": str(manifest_path)}


def build_payload(component, target, plan, work, payload, sources):
    if component == "ffmpeg":
        return build_ffmpeg(plan, target, work, payload, sources)
    if target == "windows-x86_64":
        if component == "tesseract":
            return build_windows_ocr(plan, work, payload, sources)
        if component == "libreoffice":
            return build_windows_office(plan, work, payload, sources)
        raise ValueError(f"Unsupported Windows component: {component}")
    if target == "linux-x86_64" and component in {"tesseract", "libreoffice"}:
        return build_debs(component, plan, work, payload, sources)
    raise ValueError(f"Unsupported component/target: {component}/{target}")


def build(component, target, work, output):
    import platform
    import os
    host = ("windows" if os.name == "nt" else "linux") + "-" + platform.machine().lower().replace("amd64", "x86_64")
    if host != target:
        raise RuntimeError(f"A native {target} runner is required; this host is {host}")
    plan = build_plan(component, target)
    work = Path(work) / f"{component}-{target}"
    if work.exists():
        raise ValueError(f"Use an empty work directory (existing build is preserved): {work}")
    work.mkdir(parents=True)
    payload, sources = work / "payload", work / "sources"
    payload.mkdir()
    sources.mkdir()
    metadata = build_payload(component, target, plan, work, payload, sources)
    if target == "windows-x86_64" and component in {"tesseract", "libreoffice"}:
        dependencies = audit_windows_runtime(payload, component=component)
        for directory in [payload, sources]:
            (directory / "PE-DEPENDENCIES.json").write_text(json.dumps(dependencies, indent=2) + "\n", encoding="utf-8")
    if target == "linux-x86_64" and component == "libreoffice":
        dependencies = audit_linux_office(payload)
        for directory in [payload, sources]:
            (directory / "ELF-DEPENDENCIES.json").write_text(json.dumps(dependencies, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(__file__, sources / "build_component.py")
    (sources / "build-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    checksums = {}
    for path in sorted(sources.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                checksums[path.relative_to(sources).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    (sources / "SOURCE-CHECKSUMS.json").write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf-8")
    result = create_pack(payload, output, metadata)
    # Re-extract like the Rust installer (only the entry point gets executable bits).
    # Test the archive, not a host binary or the unarchived staging tree.
    installed = work / "relocated smoke installation"
    with zipfile.ZipFile(result["archive"]) as archive:
        archive.extractall(installed)
    (installed / metadata["executable"]).chmod(0o700)
    smoke(component, installed / metadata["executable"], work / "smoke")
    source_archive = Path(output) / (Path(result["archive"]).stem + "-sources.zip")
    shutil.make_archive(str(source_archive.with_suffix("")), "zip", sources)
    with source_archive.open("rb") as stream:
        source_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    record = {"artifact": Path(result["archive"]).name, "manifest": result["manifest"],
              "sourceArtifact": source_archive.name, "sourceSha256": source_sha,
              "sourceBytes": source_archive.stat().st_size, "smoke": "passed: relocated extracted ZIP"}
    (Path(output) / (Path(result["archive"]).stem + ".build.json")).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    # A failed build/smoke never reaches the artifact-upload step.
    print(json.dumps(record, indent=2))


def run(command, cwd=None, env=None, timeout=3600):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True, timeout=timeout)


def shell_path(path):
    return subprocess.check_output(["cygpath", "-u", str(path)], text=True).strip() if os.name == "nt" else str(path)


def build_windows_ocr(plan, work, payload, sources):
    prefix = work / "prefix"
    trees, commands = {}, []
    notices = payload / "licenses"
    notices.mkdir()
    for pin in plan["sources"]:
        project = pin["name"].split("-")[0].split(".")[0]
        unpacked = unpack_source(fetch_source(pin, sources), work / (project + "-source"))
        directories = [p for p in unpacked.iterdir() if p.is_dir()]
        if len(directories) != 1:
            raise ValueError("Expected one top-level OCR source directory")
        trees[project] = directories[0]
    # Build in dependency order; no SW/vcpkg/FetchContent or ambient codec lookup.
    for project in ["zlib", "libpng", "leptonica", "tesseract"]:
        build_dir = work / (project + "-build")
        configure = ["cmake", "-S", trees[project], "-B", build_dir, "-G", "Visual Studio 17 2022", "-A", "x64",
                     *ocr_cmake_options(project, prefix)]
        steps = [configure, ["cmake", "--build", build_dir, "--config", "Release", "--parallel", "4"],
                 ["cmake", "--install", build_dir, "--config", "Release"]]
        for command in steps:
            commands.append(list(map(str, command)))
            run(command, env=dict(os.environ, GIT_CEILING_DIRECTORIES=str(work)))
        if (build_dir / "CMakeCache.txt").is_file():
            shutil.copy2(build_dir / "CMakeCache.txt", sources / (project + "-CMakeCache.txt"))
    (payload / "bin").mkdir()
    shutil.copy2(prefix / "bin/tesseract.exe", payload / "bin/tesseract.exe")
    # Upstream Windows code searches <exe-directory>/tessdata without a wrapper.
    data_dir = payload / "bin/tessdata"
    shutil.copytree(prefix / "share/tessdata", data_dir)
    shutil.copy2(trees["tesseract"] / "tessdata/pdf.ttf", data_dir / "pdf.ttf")
    for pin in plan["data"]:
        path = fetch_source(pin, sources)
        shutil.copy2(path, notices / pin["name"] if pin["name"].endswith("LICENSE") else data_dir / pin["name"])
    for pin in plan["runtimeNotices"]:
        shutil.copy2(fetch_source(pin, sources), notices / pin["name"])
    for project, filename in {"zlib": "README", "libpng": "LICENSE", "leptonica": "leptonica-license.txt", "tesseract": "LICENSE"}.items():
        shutil.copy2(trees[project] / filename, notices / f"{project}-{filename}")
    (notices / "README.txt").write_text(
        "Tesseract and tessdata_fast: Apache-2.0. Leptonica: BSD-2-Clause. libpng: libpng-2.0. zlib: Zlib. "
        "Original notices accompany this pack; Windows CRT is statically linked using the Visual Studio license's distributable-code terms. "
        "No separately downloaded or unofficial Windows OCR executables, no bundled VC installer. "
        "Only PNG/PNM/BMP image decoding is built; the app rasterizes PDF inputs to PNG. "
        "Publish the matching exact sources ZIP alongside this binary. The MIT application does not relicense these files.\n", encoding="utf-8")
    (sources / "cmake-commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
    (sources / "toolchain.txt").write_text(subprocess.check_output(["cmake", "--version"], text=True), encoding="utf-8")
    (payload / "PROVENANCE.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return dict(id="tesseract", name="Tesseract OCR", version=plan["version"], platform="windows-x86_64",
                license="Apache-2.0; BSD-2-Clause; libpng-2.0; Zlib; MSVC runtime terms (see notices)", executable="bin/tesseract.exe")


def msi_cabinet_stream(installer, work):
    """Read the pinned MSI's embedded CAB via Windows' read-only MSI API.

    Admin extraction flattens colliding ARM64/AMD64 CRT target names in this
    release. Select the exact AMD64 cabinet members instead of guessing a winner.
    """
    import ctypes
    if os.name != "nt":
        raise RuntimeError("Reading the official MSI cabinet requires native Windows")
    api = ctypes.WinDLL("msi.dll")
    uint, wide = ctypes.c_uint, ctypes.c_wchar_p
    declarations = {
        "MsiOpenDatabaseW": [wide, wide, ctypes.POINTER(uint)],
        "MsiDatabaseOpenViewW": [uint, wide, ctypes.POINTER(uint)],
        "MsiViewExecute": [uint, uint], "MsiViewFetch": [uint, ctypes.POINTER(uint)],
        "MsiRecordReadStream": [uint, uint, ctypes.c_void_p, ctypes.POINTER(uint)],
        "MsiCloseHandle": [uint],
    }
    for name, arguments in declarations.items():
        getattr(api, name).argtypes, getattr(api, name).restype = arguments, uint
    handles = []
    def checked(result):
        if result:
            raise RuntimeError(f"Windows MSI cabinet read failed: {result}")
    destination = work / "official-libreoffice1.cab"
    try:
        database, view, record = uint(), uint(), uint()
        checked(api.MsiOpenDatabaseW(str(installer), None, ctypes.byref(database)))
        handles.append(database)
        checked(api.MsiDatabaseOpenViewW(database, "SELECT `Data` FROM `_Streams` WHERE `Name` = 'libreoffice1.cab'", ctypes.byref(view)))
        handles.append(view)
        checked(api.MsiViewExecute(view, 0))
        checked(api.MsiViewFetch(view, ctypes.byref(record)))
        handles.append(record)
        buffer = ctypes.create_string_buffer(1024 * 1024)
        with destination.open("wb") as target:
            while True:
                size = uint(len(buffer))
                checked(api.MsiRecordReadStream(record, 1, buffer, ctypes.byref(size)))
                if not size.value:
                    break
                target.write(buffer.raw[:size.value])
                if target.tell() > MAX_DOWNLOAD:
                    raise ValueError("Embedded MSI cabinet exceeds size limit")
        with destination.open("rb") as stream:
            if stream.read(4) != b"MSCF":
                raise ValueError("Official MSI cabinet is missing or invalid")
        return destination
    finally:
        for handle in reversed(handles):
            api.MsiCloseHandle(handle)


def stage_msi_crt(installer, pins, work, program):
    cabinet = msi_cabinet_stream(installer, work)
    extracted = work / "amd64-crt"
    extracted.mkdir(exist_ok=True)
    result = []
    if not pins:
        raise ValueError("Missing exact official MSI AMD64 CRT member pins")
    for pin in pins:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", pin["member"]) or not re.fullmatch(r"[a-z0-9_]+\.dll", pin["name"]):
            raise ValueError("Unsafe MSI CRT member")
        run([str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/expand.exe"),
             "-F:" + pin["member"], cabinet, extracted], timeout=120)
        path = extracted / pin["member"]
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != pin["sha256"]:
                raise ValueError(f"Official MSI AMD64 CRT checksum mismatch: {pin['name']}")
        pe_dependencies(path)
        shutil.copy2(path, program / pin["name"])
        result.append(dict(pin))
    return result


def build_windows_office(plan, work, payload, sources):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("LibreOffice MSI administrative extraction is allowed only on a disposable GitHub Actions CI runner")
    installer = fetch_source(plan["installer"], work / "downloads")
    # SHA-256 above is mandatory even if Windows trusts the signing certificate.
    signature_script = "$ErrorActionPreference='Stop'; $env:PSModulePath=Join-Path $PSHOME 'Modules'; Import-Module Microsoft.PowerShell.Security -ErrorAction Stop; $s=Get-AuthenticodeSignature -LiteralPath $env:MSI_AUDIT_FILE; @{Status=[string]$s.Status;Subject=[string]$s.SignerCertificate.Subject;Thumbprint=[string]$s.SignerCertificate.Thumbprint}|ConvertTo-Json -Compress"
    signature_environment = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
    signature_environment["MSI_AUDIT_FILE"] = str(installer)
    signature = json.loads(subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", signature_script], text=True,
        env=signature_environment, timeout=120))
    if signature.get("Status") != "Valid" or not re.search(r"(?:^|,\s*)(?:O|CN)=The Document Foundation(?:,|$)", signature.get("Subject", "")):
        raise ValueError("Official LibreOffice MSI Authenticode audit failed; no extraction performed")
    # Preserve all four release source bundles, all their patches, and every listed external.
    archives = [fetch_source(pin, sources) for pin in plan["sources"]]
    externals = office_external_sources(archives[0])
    for pin in externals:
        fetch_source(pin, sources / "externals")
    admin = work / "msi-admin"
    run(["msiexec.exe", "/a", installer, "/qn", "/norestart", f"TARGETDIR={admin}", "/L*v", work / "msi-admin.log"], timeout=600)
    executables = list(admin.rglob("soffice.com"))
    if len(executables) != 1 or executables[0].parent.name != "program":
        raise ValueError("Official MSI did not yield one complete LibreOffice runtime")
    runtime = executables[0].parent.parent
    for name in ["program/soffice.bin", "LICENSE.html", "NOTICE"]:
        if not (runtime / name).is_file() or not (runtime / name).stat().st_size:
            raise ValueError(f"Official LibreOffice runtime/notice is missing: {name}")
    shutil.copytree(runtime, payload / "office", symlinks=True)
    # The MSI has colliding AMD64/ARM64 System64 CRT filenames. Administrative
    # extraction is not architecture selection: read the exact pinned CAB members.
    redistributables = stage_msi_crt(installer, plan["crtMembers"], work, payload / "office/program")
    if (admin / "Fonts").is_dir():
        shutil.copytree(admin / "Fonts", payload / "office/share/fonts/truetype", dirs_exist_ok=True)
    # No trimming of fonts, locale filters, runtime DLLs, dictionaries or license files.
    # create_pack enforces the installer size/path/link bounds on the entire tree.
    provenance = dict(plan, authenticode=signature, externalSources=externals, appLocalMsvc=redistributables,
                      extraction="msiexec /a /qn; CI only; no end-user installer or registration",
                      sourcePolicy="All release source bundles plus ALL download.lst externals; patches/configurations in core source")
    (payload / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(payload / "PROVENANCE.json", sources / "PROVENANCE.json")
    shutil.copy2(work / "msi-admin.log", sources / "msi-admin.log") if (work / "msi-admin.log").is_file() else None
    (payload / "SOURCE-OFFER.txt").write_text(
        f"LibreOffice {plan['version']} pre-release candidate; upstream does not recommend production use. "
        "MPL-2.0/LGPL-3.0-or-later and third-party terms in office/LICENSE.html, office/NOTICE and the preserved runtime notices. "
        f"The matching libreoffice-{plan['version']}-windows-x86_64-sources.zip MUST be published beside this engine ZIP at the same immutable version. "
        "It contains the exact official release source bundles, external sources/data/fonts and upstream patches/build configurations, this builder and checksums. "
        "The MIT application does not relicense this engine. No administrator access is needed to unpack/run the app-local runtime.\n", encoding="utf-8")
    return dict(id="libreoffice", name=plan["displayName"], version=plan["version"], platform="windows-x86_64",
                license="MPL-2.0/LGPL-3.0-or-later plus preserved third-party notices", executable="office/program/soffice.com")


def build_ffmpeg(plan, target, work, payload, sources):
    prefix = work / "prefix"
    prefix.mkdir()
    environment = dict(os.environ, PKG_CONFIG_PATH=shell_path(prefix / "lib/pkgconfig"))
    trees = {}
    for pin in plan["sources"]:
        archive = fetch_source(pin, sources)
        extracted = unpack_source(archive, work / pin["name"].split(".")[0])
        directories = [p for p in extracted.iterdir() if p.is_dir()]
        if len(directories) != 1:
            raise ValueError("Expected one top-level source directory")
        trees[pin["name"].split("-")[0]] = directories[0]
    jobs = str(min(os.cpu_count() or 2, 4))
    pre = "--prefix=" + shell_path(prefix)
    vpx = ["sh", "./configure", pre, "--disable-examples", "--disable-tools", "--disable-unit-tests",
           "--disable-docs", "--disable-shared", "--enable-static", "--enable-pic"]
    if target.startswith("windows"):
        vpx += ["--target=x86_64-win64-gcc"]
    run(vpx, trees["libvpx"], environment)
    run(["make", "-j" + jobs], trees["libvpx"], environment)
    run(["make", "install"], trees["libvpx"], environment)
    run(["sh", "./configure", pre, "--disable-shared", "--enable-static", "--disable-doc", "--disable-extra-programs"], trees["opus"], environment)
    run(["make", "-j" + jobs], trees["opus"], environment)
    run(["make", "install"], trees["opus"], environment)
    flags = list(plan["configure"]) + [pre, "--pkg-config-flags=--static"]
    if target.startswith("windows"):
        flags += ["--target-os=mingw32", "--arch=x86_64", "--extra-ldflags=-static"]
    run(["sh", "./configure", *flags], trees["ffmpeg"], environment)
    run(["make", "-j" + jobs, "ffmpeg.exe" if target.startswith("windows") else "ffmpeg"], trees["ffmpeg"], environment)
    (payload / "bin").mkdir()
    executable = "bin/ffmpeg.exe" if target.startswith("windows") else "bin/ffmpeg"
    shutil.copy2(trees["ffmpeg"] / Path(executable).name, payload / executable)
    notices = payload / "licenses"
    notices.mkdir()
    if target.startswith("windows"):
        # -static also redistributes GCC/MinGW runtime code. Keep its exception/license texts.
        gcc = shutil.which("gcc")
        runtime_notices = Path(gcc).parent.parent / "share/licenses" if gcc else Path("missing")
        if not runtime_notices.is_dir():
            raise RuntimeError("MinGW runtime license directory is missing; refusing redistribution")
        shutil.copytree(runtime_notices, notices / "mingw-runtime-notices", symlinks=False)
    (sources / "toolchain.txt").write_text("\n".join(subprocess.check_output([tool, "--version"], text=True).splitlines()[0] for tool in ["gcc", "make", "pkg-config"]) + "\n", encoding="utf-8")
    for project, names in {"ffmpeg": ["COPYING.LGPLv2.1", "COPYING.LGPLv3"], "libvpx": ["LICENSE", "PATENTS"], "opus": ["COPYING"]}.items():
        for name in names:
            shutil.copy2(trees[project] / name, notices / f"{project}-{name}")
    for name in ["config.h", "ffbuild/config.mak", "ffbuild/config.log"]:
        if (trees["ffmpeg"] / name).exists():
            shutil.copy2(trees["ffmpeg"] / name, sources / Path(name).name)
    (payload / "PROVENANCE.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    (notices / "README.txt").write_text(
        "FFmpeg: LGPL-2.1-or-later, no GPL/nonfree/autodetected libraries. libvpx: BSD-3-Clause plus patent grant. "
        "Opus: BSD-3-Clause plus upstream patent terms in COPYING. No x264/x265; VP9+Opus encode is tested. "
        "Corresponding upstream source archives and this exact builder MUST accompany the binary release. "
        "The MIT application does not relicense these engines. See https://ffmpeg.org/legal.html\n", encoding="utf-8")
    return dict(id="ffmpeg", name="FFmpeg media processing", version=plan["version"], platform=target,
                license="LGPL-2.1-or-later; BSD-3-Clause dependencies (see notices)", executable=executable)


def materialize_deb_links(root):
    # dpkg packages contain absolute links rooted at /; rewrite them into this app-local tree.
    for path in root.rglob("*"):
        if path.is_symlink() and os.readlink(path).startswith("/"):
            target = root / os.readlink(path).lstrip("/")
            path.unlink()
            path.symlink_to(os.path.relpath(target, path.parent))
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError(f"Debian package link escapes root: {path}")
            path.unlink()
            if target.is_file():
                shutil.copy2(target, path)
            elif target.is_dir():
                shutil.copytree(target, path, symlinks=False)
            # Dangling alternatives/manpage links are omitted; executable smoke is mandatory.


def build_debs(component, plan, work, payload, sources):
    office = None
    if component == "libreoffice":
        if plan.get("builder") != "official-debs-app-local" or plan.get("version") != OFFICE_VERSION:
            raise ValueError("Unverified LibreOffice distribution; obsolete distro fallback is forbidden")
        installer = fetch_source(plan["installer"], work / "downloads")
        unpacked = unpack_source(installer, work / "official-debs")
        archives = [fetch_source(pin, sources) for pin in plan["sources"]]
        externals = office_external_sources(archives[0])
        for pin in externals:
            fetch_source(pin, sources / "externals")
        # Optional desktop integration and Python/LibreLogo scripting only.
        # Keep all fonts, filters, dictionaries, module data and original notices.
        omitted = {"libobasis26.2-gnome-integration", "libobasis26.2-kde-integration",
                   "libreoffice26.2-debian-menus", "libobasis26.2-pyuno",
                   "libobasis26.2-librelogo", "libobasis26.2-python-script-provider"}
        office_packages = []
        for deb in sorted(unpacked.rglob("*.deb")):
            if deb.name.split("_")[0] in omitted:
                continue
            fields = email.parser.Parser().parsestr(subprocess.check_output(["dpkg-deb", "--field", str(deb)], text=True))
            if fields["Architecture"] != "amd64" or fields["Version"] != OFFICE_VERSION + "-1":
                raise ValueError("Unexpected official LibreOffice package architecture/version")
            with deb.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            office_packages.append({"package": fields["Package"], "version": fields["Version"], "sha256": digest})
            run(["dpkg-deb", "--extract", deb, payload / "root"])
        runtime = payload / "root/opt/libreoffice26.2"
        for name in ["program/soffice", "program/soffice.bin", "program/fundamentalrc", "LICENSE.html", "NOTICE"]:
            if not (runtime / name).is_file() or not (runtime / name).stat().st_size:
                raise ValueError(f"Official LibreOffice runtime/notice is missing: {name}")
        office = dict(plan, externalSources=externals, packages=office_packages, omittedPackages=sorted(omitted),
                      extraction="dpkg-deb --extract only; no maintainer scripts or global registration")
        (payload / "SOURCE-OFFER.txt").write_text(
            f"LibreOffice {OFFICE_VERSION} pre-release candidate; upstream does not recommend production use. "
            "Original MPL-2.0/LGPL-3.0-or-later and third-party notices in root/opt/libreoffice26.2. "
            f"Publish libreoffice-{OFFICE_VERSION}-linux-x86_64-sources.zip beside this engine. "
            "It preserves all four official release source archives, ALL checksum-pinned download.lst externals, upstream patches/configuration, "
            "exact corresponding Ubuntu dependency sources and this builder. Dependency notices: root/usr/share/doc/*/copyright. "
            "The MIT application does not relicense this engine.\n", encoding="utf-8")
    apt = work / "apt"
    for directory in ["lists/partial", "cache/archives/partial", "state", "log"]:
        (apt / directory).mkdir(parents=True)
    source_list = apt / "sources.list"
    source_list.write_text("".join(
        f"{kind} [arch=amd64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] {plan['snapshot']} {suite} main universe\n"
        for suite in ["jammy", "jammy-updates", "jammy-security"] for kind in ["deb", "deb-src"]), encoding="utf-8")
    config = apt / "apt.conf"
    config.write_text(f'''APT::Architecture "amd64";
Dir::Etc::sourcelist "{source_list}";
Dir::Etc::sourceparts "-";
Dir::State::lists "{apt / 'lists'}";
Dir::State::status "/dev/null";
Dir::Cache "{apt / 'cache'}";
Dir::Log "{apt / 'log'}";
Acquire::Check-Valid-Until "false";
APT::Install-Recommends "false";
APT::Install-Suggests "false";
''', encoding="utf-8")
    # Only a disposable CI runner may use sudo. This never runs on an end-user machine.
    command = ["sudo", "apt-get", "-c", str(config)]
    run(command + ["update"])
    run(command + ["--yes", "--download-only", "install", *plan["packages"]])
    root = payload / "root"
    root.mkdir(exist_ok=True)
    packages, source_versions = [], set()
    for deb in sorted((apt / "cache/archives").glob("*.deb")):
        fields = email.parser.Parser().parsestr(subprocess.check_output(["dpkg-deb", "--field", str(deb)], text=True))
        name, version = fields["Package"], fields["Version"]
        if component == "libreoffice" and name.startswith(("libreoffice", "libobasis")):
            raise ValueError("APT attempted to replace the current official Office engine")
        if name.startswith(("ghostscript", "libgs9", "libgs10", "mupdf", "libmupdf")):
            raise ValueError(f"Forbidden AGPL engine in dependency closure: {name}")
        # Use the baseline host's dynamic loader/glibc, never mix bundled glibc with its loader.
        if name in {"libc6", "libc-bin", "libc-l10n", "locales"}:
            continue
        with deb.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        source = fields.get("Source", name)
        match = re.fullmatch(r"([^ ]+)(?: \(([^)]+)\))?", source)
        if not match:
            raise ValueError("Unexpected source package metadata")
        source_versions.add((match[1], match[2] or version))
        packages.append({"package": name, "version": version, "sha256": digest, "source": match[1], "sourceVersion": match[2] or version})
        run(["dpkg-deb", "--extract", deb, root])
    if not packages:
        raise RuntimeError("APT did not produce any packages")
    # Download the exact corresponding source, including distro patches and .dsc checksums.
    # Failure is fatal: do not publish a binary without its redistribution materials.
    for name, version in sorted(source_versions):
        run(command + ["--download-only", "source", f"{name}={version}"], cwd=sources)
    common_licenses = Path("/usr/share/common-licenses")
    if not common_licenses.is_dir():
        raise RuntimeError("The Ubuntu common license texts are missing")
    shutil.copytree(common_licenses, root / "usr/share/common-licenses", dirs_exist_ok=True)
    materialize_deb_links(root)
    version_package = "tesseract-ocr" if component == "tesseract" else "libreoffice-core"
    version = OFFICE_VERSION if office else next(p["version"] for p in packages if p["package"] == version_package)
    version = version.replace(":", "_").replace("+", "_").replace("~", "_")
    (payload / "bin").mkdir()
    executable = f"bin/{component}"
    body = '''#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ROOT="$HERE/root"
export LD_LIBRARY_PATH="$ROOT/opt/libreoffice26.2/program:$ROOT/usr/lib/x86_64-linux-gnu:$ROOT/lib/x86_64-linux-gnu:$ROOT/usr/lib:$ROOT/lib"
'''
    if component == "tesseract":
        body += '''for data in "$ROOT"/usr/share/tesseract-ocr/*/tessdata; do
  if [ -d "$data" ]; then export TESSDATA_PREFIX="$data"; break; fi
done
chmod u+x "$ROOT/usr/bin/tesseract"
exec "$ROOT/usr/bin/tesseract" "$@"
'''
    else:
        body += '''export SAL_USE_VCLPLUGIN=svp
export FONTCONFIG_FILE="$HERE/fonts.conf"
export URE_BOOTSTRAP="vnd.sun.star.pathname:$ROOT/opt/libreoffice26.2/program/fundamentalrc"
for name in oosplash soffice.bin uno.bin xpdfimport; do
  if [ -f "$ROOT/opt/libreoffice26.2/program/$name" ]; then chmod u+x "$ROOT/opt/libreoffice26.2/program/$name"; fi
done
exec /bin/sh "$ROOT/opt/libreoffice26.2/program/soffice" "$@"
'''
        (payload / "fonts.conf").write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir prefix="relative">root/usr/share/fonts</dir><dir prefix="relative">root/opt/libreoffice26.2/share/fonts/truetype</dir><cachedir prefix="xdg">fontconfig</cachedir></fontconfig>\n', encoding="utf-8")
    (payload / executable).write_text(body, encoding="utf-8")
    (payload / executable).chmod(0o755)
    provenance = {"snapshot": plan["snapshot"], "baseline": "Ubuntu 22.04 / glibc >= 2.35, x86_64", "packages": packages,
                  "licenses": "Exact package copyright/license texts: root/usr/share/doc/*/copyright; corresponding sources accompany the pack"}
    if office:
        provenance["office"] = office
    (payload / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(payload / "PROVENANCE.json", sources / "PROVENANCE.json")
    return dict(id=component, name="Tesseract OCR" if component == "tesseract" else plan["displayName"], version=version,
                platform="linux-x86_64", license="Apache-2.0 plus dependency notices" if component == "tesseract" else "MPL-2.0/LGPL-3.0-or-later plus dependency notices", executable=executable)


def office_fixture(directory):
    source = directory / "conversion.docx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Paperwork conversion smoke</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
    return source


def smoke_environment(directory, windows=False):
    environment = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL"}}
    environment.update(HOME=str(directory), USERPROFILE=str(directory), APPDATA=str(directory / "appdata"),
                       LOCALAPPDATA=str(directory / "localappdata"), TEMP=str(directory), TMP=str(directory),
                       XDG_CACHE_HOME=str(directory / "cache"))
    environment["PATH"] = str(Path(environment.get("SystemRoot", "C:/Windows")) / "System32") if windows else "/usr/bin:/bin"
    return environment


def ocr_smoke_font(windows=False):
    return Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf" if windows else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def smoke(component, executable, directory):
    directory.mkdir()
    environment = smoke_environment(directory, windows=os.name == "nt")
    if component == "ffmpeg":
        config = subprocess.check_output([str(executable), "-buildconf"], stderr=subprocess.STDOUT, text=True, env=environment)
        if "--enable-gpl" in config or "--enable-nonfree" in config or "--disable-autodetect" not in config:
            raise ValueError("FFmpeg redistribution configuration audit failed")
        (directory / "buildconf.txt").write_text(config, encoding="utf-8")
        video = directory / "vp9-opus.webm"
        run([executable, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=128x96:r=5", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "libvpx-vp9", "-c:a", "libopus", video], env=environment, timeout=120)
        run([executable, "-nostdin", "-v", "error", "-i", video, "-f", "null", "-"], env=environment, timeout=120)
        if video.stat().st_size < 1000:
            raise ValueError("FFmpeg produced an empty media file")
    elif component == "tesseract":
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", (1000, 180), "white")
        font = ImageFont.truetype(str(ocr_smoke_font(windows=os.name == "nt")), 76)
        ImageDraw.Draw(image).text((25, 35), "PAPERWORK TEST", fill="black", font=font)
        source = directory / "ocr.png"
        image.save(source)
        text = subprocess.check_output([str(executable), str(source), "stdout", "-l", "eng", "--psm", "7"], env=environment, text=True, timeout=120)
        if "PAPERWORK TEST" not in text.upper():
            raise ValueError(f"Real OCR smoke did not recognize the fixture: {text!r}")
    else:
        source = office_fixture(directory)
        run([executable, "-env:UserInstallation=" + (directory / "profile").as_uri(), "--headless", "--convert-to", "pdf", "--outdir", directory, source], env=environment, timeout=180)
        pdf = directory / "conversion.pdf"
        if not pdf.is_file() or pdf.stat().st_size < 500 or not pdf.read_bytes().startswith(b"%PDF-"):
            raise ValueError("LibreOffice did not produce a real PDF")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", required=True, choices=["ffmpeg", "tesseract", "libreoffice", "whisper", "llama"])
    parser.add_argument("--platform", required=True, choices=["linux-x86_64", "windows-x86_64"])
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist/components"))
    parser.add_argument("--work", type=Path, default=Path("build/components"))
    args = parser.parse_args()
    try:
        plan = build_plan(args.component, args.platform)
        if args.plan:
            print(json.dumps(plan, indent=2))
            return
        build(args.component, args.platform, args.work.resolve(), args.output.resolve())
    except (ValueError, RuntimeError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
