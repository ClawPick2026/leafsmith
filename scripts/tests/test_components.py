"""Stdlib-only pack contract tests. No network or compiler required."""
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "build_component.py"


def builder():
    if not SCRIPT.exists():
        return None
    spec = importlib.util.spec_from_file_location("build_component", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def elf_fixture(needed, machine=62, *, search=None, search_tag=29, elf_type=3,
                interpreter=None, section_needed=None, section_search=None, flags1=0, soname=None):
    """ELF loader-metadata fixture; not executable machine code.

    PT_LOAD maps the file, PT_DYNAMIC points at DT_STRTAB/DT_STRSZ, and
    optional section decoys let tests distinguish loader data from sections.
    """
    import struct
    data = bytearray(8192)
    data[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHIQQQIHHHHHH", data, 16, elf_type, machine, 1, 0, 64,
                     512, 0, 64, 56, 3 if interpreter is not None else 2, 64, 3, 0)

    def tables(names, paths, strings_offset, dynamic_offset):
        strings = bytearray(b"\0")
        entries = []
        for tag, text in ([(1, n) for n in names] + ([(search_tag, paths)] if paths is not None else [])
                          + ([(14, soname)] if soname is not None else [])):
            entries.append((tag, len(strings)))
            strings.extend(text.encode("ascii") + b"\0")
        if flags1:
            entries.append((0x6ffffffb, flags1))
        entries += [(5, 0x400000 + strings_offset), (10, len(strings)), (0, 0)]
        data[strings_offset:strings_offset + len(strings)] = strings
        for index, entry in enumerate(entries):
            struct.pack_into("<qQ", data, dynamic_offset + index * 16, *entry)
        return len(strings), len(entries) * 16

    string_size, dynamic_size = tables(needed, search, 1024, 2048)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0x400000, 0x400000, len(data), len(data), 4096)
    struct.pack_into("<IIQQQQQQ", data, 120, 2, 6, 2048, 0x400800, 0x400800, dynamic_size, dynamic_size, 8)
    if interpreter is not None:
        encoded = interpreter.encode("ascii") + b"\0"
        data[3072:3072 + len(encoded)] = encoded
        struct.pack_into("<IIQQQQQQ", data, 176, 3, 4, 3072, 0x400c00, 0x400c00, len(encoded), len(encoded), 1)
    strings_offset, dynamic_offset = 1024, 2048
    if section_needed is not None or section_search is not None:
        strings_offset, dynamic_offset = 4096, 5120
        string_size, dynamic_size = tables(section_needed or [], section_search, strings_offset, dynamic_offset)
    struct.pack_into("<IIQQQQIIQQ", data, 576, 0, 3, 2, 0x400000 + strings_offset, strings_offset, string_size, 0, 0, 1, 0)
    struct.pack_into("<IIQQQQIIQQ", data, 640, 0, 6, 3, 0x400000 + dynamic_offset, dynamic_offset, dynamic_size, 1, 0, 8, 16)
    return data


class PackTests(unittest.TestCase):
    def test_pack_is_deterministic_and_manifest_matches_real_zip(self):
        module = builder()
        self.assertTrue(callable(getattr(module, "create_pack", None)), "pack builder is not implemented")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload"
            (payload / "bin").mkdir(parents=True)
            (payload / "bin/tool").write_text("#!/bin/sh\nprintf 'real fixture\\n'\n")
            metadata = dict(id="tesseract", name="Tesseract OCR", version="5.0.0-test", platform="linux-x86_64",
                            license="Apache-2.0", executable="bin/tool")
            first = module.create_pack(payload, root / "one", metadata)
            second = module.create_pack(payload, root / "two", metadata)
            a = Path(first["archive"])
            b = Path(second["archive"])
            self.assertEqual(a.read_bytes(), b.read_bytes())
            manifest = first["manifest"]
            self.assertEqual(manifest["sha256"], hashlib.sha256(a.read_bytes()).hexdigest())
            self.assertEqual(manifest["downloadBytes"], a.stat().st_size)
            self.assertNotIn("url", manifest, "unpublished artifacts must not invent a download URL")
            with zipfile.ZipFile(a) as archive:
                entry = archive.getinfo("bin/tool")
                self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertTrue(entry.external_attr >> 16 & 0o100)
            self.assertEqual(json.loads(Path(first["manifestPath"]).read_text()), manifest)

    def test_pack_rejects_unsafe_paths_missing_executable_and_unbounded_size(self):
        module = builder()
        assert module is not None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload"
            payload.mkdir()
            (payload / "tool").write_text("tool")
            metadata = dict(id="ffmpeg", name="FFmpeg", version="7.1.3", platform="linux-x86_64",
                            license="LGPL-2.1-or-later", executable="tool")
            for bad in ("../tool", "C:/tool", "bin\\tool", "/tool", "missing"):
                with self.subTest(executable=bad), self.assertRaises(ValueError):
                    module.create_pack(payload, root / "out", dict(metadata, executable=bad))
            (payload / "bad\\name").write_text("unsafe on Windows")
            with self.assertRaises(ValueError):
                module.create_pack(payload, root / "out", metadata)
            (payload / "bad\\name").unlink()
            module.MAX_EXTRACTED = 3
            with self.assertRaises(ValueError):
                module.create_pack(payload, root / "out", metadata)

    @unittest.skipIf(os.name == "nt", "symlink creation requires a Windows privilege")
    def test_internal_symlinks_become_regular_files_but_escaping_links_fail(self):
        module = builder()
        assert module is not None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload"
            payload.mkdir()
            (payload / "actual").write_text("binary content")
            (payload / "tool").symlink_to("actual")
            metadata = dict(id="ffmpeg", name="FFmpeg", version="7.1.3", platform="linux-x86_64",
                            license="LGPL-2.1-or-later", executable="tool")
            result = module.create_pack(payload, root / "out", metadata)
            with zipfile.ZipFile(result["archive"]) as archive:
                self.assertEqual(archive.read("tool"), b"binary content")
                self.assertNotEqual(archive.getinfo("tool").external_attr >> 16 & 0o170000, 0o120000)
            (root / "private").write_text("outside")
            (payload / "escape").symlink_to(root / "private")
            with self.assertRaises(ValueError):
                module.create_pack(payload, root / "out", metadata)

    def test_windows_ocr_uses_current_decoder_and_compression_security_fixes(self):
        module = builder()
        plan = module.build_plan("tesseract", "windows-x86_64")
        self.assertEqual(plan["version"], "5.5.3-lept1.87.0-png1.6.59-zlib1.3.2-data4.1.0")
        pins = {p["name"]: p["sha256"] for p in plan["sources"]}
        self.assertEqual(pins["libpng-1.6.59.tar.gz"], "2540302a1844ad2b2b501977abecfa850f265f97b78f065a712ab4074a89f5b5")
        self.assertEqual(pins["zlib-1.3.2.tar.xz"], "d7a0654783a4da529d1bb793b7ad9c3318020af77667bcae35f95d0e42a792f3")
        flags = module.ocr_cmake_options("zlib", Path("prefix"))
        self.assertIn("-DZLIB_BUILD_SHARED=OFF", flags)
        self.assertIn("-DZLIB_BUILD_TESTING=OFF", flags)
        self.assertIn(f"-DZLIB_LIBRARY={Path('prefix') / 'lib/zs.lib'}", module.ocr_cmake_options("libpng", Path("prefix")))

    def test_windows_ocr_plan_pins_all_native_sources_and_english_osd_data(self):
        module = builder()
        plan = module.build_plan("tesseract", "windows-x86_64")
        self.assertEqual(plan["builder"], "cmake-msvc-static")
        self.assertEqual(plan["version"], "5.5.3-lept1.87.0-png1.6.59-zlib1.3.2-data4.1.0")
        self.assertEqual({s["name"] for s in plan["sources"]}, {
            "tesseract-5.5.3.tar.gz", "leptonica-1.87.0.tar.gz", "libpng-1.6.59.tar.gz", "zlib-1.3.2.tar.xz"})
        self.assertEqual({s["name"] for s in plan["data"]}, {"eng.traineddata", "osd.traineddata", "tessdata-LICENSE"})
        for pin in plan["sources"] + plan["data"]:
            self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(pin["url"].startswith("https://"))
            self.assertNotIn("/main/", pin["url"])
        self.assertEqual(plan["imageCodecs"], ["PNG", "PNM", "BMP"])
        self.assertEqual(plan["runtimeNotices"][0]["sha256"], "9c0cd52b20db9d081854c75bd1b50c75514b8f8cb09c8cad15e89d90b97b5bf3")

    def test_office_plans_explicitly_label_upstream_prerelease_candidate(self):
        module = builder()
        for target in ["windows-x86_64", "linux-x86_64"]:
            with self.subTest(target=target):
                plan = module.build_plan("libreoffice", target)
                self.assertEqual(plan.get("releaseChannel"), "prerelease")
                self.assertEqual(plan.get("displayName"), "LibreOffice conversion (26.2.7.1 pre-release candidate)")
                self.assertEqual(plan.get("dependencyBaseline"), {
                    "libpng": "1.6.59",
                    "libpngUpgradeCommit": "fd76bd2515f0d4e69ed227834ee355bf6a6d7f88"})
                self.assertEqual(plan.get("upstreamReleasePolicy"), "https://www.libreoffice.org/download/pre-releases/")

    def test_windows_office_security_baseline_uses_fixed_dependency_candidate(self):
        module = builder()
        plan = module.build_plan("libreoffice", "windows-x86_64")
        # Sep/Oct 2026 arbitrary-write/LFI/SSRF/RCE and CFF fixes: >=26.2.5.
        self.assertEqual(plan["version"], "26.2.7.1")
        self.assertEqual(plan["installer"]["sha256"], "82edb4c85605bf38420f461596c5e4eb625afbe6557bd6c7bfa2c470b430a8c7")
        self.assertEqual({p["name"]: p["sha256"] for p in plan["sources"]}, {
            "libreoffice-26.2.7.1.tar.xz": "3ce4475c3e8c27450d667d83bf2dd9e99a8070d190363286022cf392d4eaec17",
            "libreoffice-dictionaries-26.2.7.1.tar.xz": "b8c73d520b1b6f65e1eed838d903334dbc68aa57c729049af74cac47db14cafd",
            "libreoffice-help-26.2.7.1.tar.xz": "cbe017cfb3ebd15bcffec2d3b646b0414a4b62c2a8eedb9c0d2dc7568dfc6843",
            "libreoffice-translations-26.2.7.1.tar.xz": "781fc87e10424b510ee095480f152c4ed044e6b9a98e2a07020584bfe7691ac8"})

    def test_linux_office_security_minimum_replaces_unverified_jammy_backports(self):
        module = builder()
        plan = module.build_plan("libreoffice", "linux-x86_64")
        self.assertEqual(plan.get("version"), "26.2.7.1")
        self.assertEqual(plan["builder"], "official-debs-app-local")
        self.assertEqual(plan["installer"]["sha256"], "7cc840bd089f4779636cb2340f33786e71ce66669fdfbe36fe5c7322edc186ee")
        self.assertEqual(plan["sources"], module.build_plan("libreoffice", "windows-x86_64")["sources"])
        self.assertIn("libfontconfig1", plan["packages"])
        self.assertFalse(any(p.startswith("libreoffice") for p in plan["packages"]))

    def test_windows_office_plan_uses_official_msi_and_matching_source_bundles(self):
        module = builder()
        plan = module.build_plan("libreoffice", "windows-x86_64")
        self.assertEqual(plan["builder"], "official-msi-admin-extract-ci-only")
        self.assertEqual(plan["version"], "26.2.7.1")
        self.assertEqual(plan["installer"]["sha256"], "82edb4c85605bf38420f461596c5e4eb625afbe6557bd6c7bfa2c470b430a8c7")
        for pin in [plan["installer"], *plan["sources"]]:
            self.assertTrue(pin["url"].startswith("https://downloadarchive.documentfoundation.org/libreoffice/old/26.2.7.1/"))
            self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(plan["sources"]), 4)
        self.assertTrue(plan["preserveEntireRuntime"])

    def test_office_corresponding_sources_resolve_release_manifest_without_executing_make(self):
        import io
        import tarfile
        module = builder()
        text = "MICRO := 4\nFOO_TARBALL := foo-1.$(MICRO).tar.xz\nFOO_SHA256SUM := " + "a" * 64 + "\nFONT_TTF := font.ttf\nFONT_SHA256SUM := " + "b" * 64 + "\n"
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "core.tar"
            def make_archive(content):
                with tarfile.open(archive, "w") as tar:
                    entry = tarfile.TarInfo("libreoffice-26.2.7.1/download.lst")
                    encoded = content.encode()
                    entry.size = len(encoded)
                    tar.addfile(entry, io.BytesIO(encoded))
            make_archive(text)
            pins = module.office_external_sources(archive)
            self.assertEqual([p["name"] for p in pins], ["foo-1.4.tar.xz", "font.ttf"])
            self.assertEqual(pins[0]["url"], "https://dev-www.libreoffice.org/src/foo-1.4.tar.xz")
            self.assertEqual(pins[1]["url"], "https://dev-www.libreoffice.org/extern/font.ttf")
            for invalid in [text.replace("a" * 64, "missing"), text.replace("$(MICRO)", "$(shell touch PWNED)"), text.replace("foo-1.", "../foo-1.")]:
                make_archive(invalid)
                with self.assertRaises(ValueError):
                    module.office_external_sources(archive)

    def test_windows_ocr_cmake_options_disable_network_and_unpinned_codecs(self):
        module = builder()
        prefix = Path("runtime-prefix")
        flags = module.ocr_cmake_options("tesseract", prefix)
        for required in ["-DBUILD_SHARED_LIBS=OFF", "-DWIN32_MT_BUILD=ON", "-DDISABLE_ARCHIVE=ON", "-DDISABLE_CURL=ON", "-DDISABLE_TIFF=ON", "-DOPENMP_BUILD=OFF", "-DENABLE_NATIVE=OFF", "-DGRAPHICS_DISABLED=ON", "-DBUILD_TRAINING_TOOLS=OFF"]:
            self.assertIn(required, flags)
        flags = module.ocr_cmake_options("leptonica", prefix)
        for codec in ["GIF", "JPEG", "TIFF", "WEBP", "OPENJPEG"]:
            self.assertIn(f"-DENABLE_{codec}=OFF", flags)
        self.assertIn("-DENABLE_PNG=ON", flags)
        self.assertIn("-DSTRICT_CONF=ON", flags)
        self.assertIn("-DSW_BUILD=OFF", flags)
        for project in ["zlib", "libpng", "leptonica", "tesseract"]:
            flags = module.ocr_cmake_options(project, prefix)
            self.assertIn("-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded", flags)
            self.assertIn("-DCMAKE_POLICY_DEFAULT_CMP0091=NEW", flags)
        with self.assertRaises(ValueError):
            module.ocr_cmake_options("unknown", prefix)

    def test_windows_ocr_builder_keeps_data_config_licenses_and_exact_sources(self):
        import io
        import tarfile
        from unittest.mock import patch
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources, payload = root / "sources", root / "payload"
            sources.mkdir()
            payload.mkdir()
            pins = []
            for project, license_file in [("zlib", "README"), ("libpng", "LICENSE"), ("leptonica", "leptonica-license.txt"), ("tesseract", "LICENSE")]:
                path = sources / f"{project}.tar.gz"
                with tarfile.open(path, "w:gz") as archive:
                    content = f"{project} unit-test license text".encode()
                    entry = tarfile.TarInfo(f"{project}-fixture/{license_file}")
                    entry.size = len(content)
                    archive.addfile(entry, io.BytesIO(content))
                    if project == "tesseract":
                        font = tarfile.TarInfo("tesseract-fixture/tessdata/pdf.ttf")
                        font.size = 4
                        archive.addfile(font, io.BytesIO(b"font"))
                pins.append(dict(name=path.name, url="https://example.invalid/" + path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            data = []
            for name in ["eng.traineddata", "osd.traineddata", "tessdata-LICENSE"]:
                path = sources / name
                path.write_text("unit-test data fixture, not a trained model")
                data.append(dict(name=name, url="https://example.invalid/" + name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            commands, environments = [], []
            def tool_fixture(command, **kwargs):
                commands.append(list(map(str, command)))
                environments.append(kwargs.get("env", {}))
                if "--install" in command:
                    prefix = root / "prefix"
                    (prefix / "bin").mkdir(parents=True, exist_ok=True)
                    (prefix / "bin/tesseract.exe").write_bytes(b"unit-test fixture, not a native executable")
                    (prefix / "share/tessdata/configs").mkdir(parents=True, exist_ok=True)
                    (prefix / "share/tessdata/configs/pdf").write_text("tessedit_create_pdf 1")
                    (prefix / "share/tessdata/pdf.ttf").write_bytes(b"unit-test font")
            runtime = sources / "MSVC-2022-license.docx"
            runtime.write_bytes(b"unit-test runtime terms")
            plan = dict(version="fixture", sources=pins, data=data,
                        runtimeNotices=[dict(name=runtime.name, url="https://example.invalid/terms", sha256=hashlib.sha256(runtime.read_bytes()).hexdigest())])
            with patch.object(module, "run", side_effect=tool_fixture), patch.object(module.subprocess, "check_output", return_value="cmake fixture\n"):
                metadata = module.build_windows_ocr(plan, root, payload, sources)
            self.assertEqual(metadata["executable"], "bin/tesseract.exe")
            self.assertTrue((payload / "bin/tessdata/eng.traineddata").is_file())
            self.assertTrue((payload / "bin/tessdata/osd.traineddata").is_file())
            self.assertTrue((payload / "bin/tessdata/configs/pdf").is_file())
            self.assertTrue((payload / "bin/tessdata/pdf.ttf").is_file())
            self.assertEqual(len(list((payload / "licenses").glob("*-*"))), 6)
            self.assertTrue((payload / "licenses/MSVC-2022-license.docx").is_file())
            self.assertTrue((sources / "cmake-commands.json").is_file())
            self.assertEqual(len([c for c in commands if "--install" in c]), 4)
            self.assertTrue(all(e.get("GIT_CEILING_DIRECTORIES") == str(root) for e in environments))
            self.assertFalse(list(payload.rglob("*.dll")), "static build must not silently bundle unaudited DLLs")

    def test_linux_office_stages_official_runtime_and_sources_not_distro_engine(self):
        import io
        import tarfile
        from unittest.mock import patch
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, sources = root / "payload", root / "sources"
            payload.mkdir()
            sources.mkdir()
            plan = module.build_plan("libreoffice", "linux-x86_64")
            installer = root / plan["installer"]["name"]
            with tarfile.open(installer, "w:gz") as archive:
                for package in ["libobasis26.2-core", "libobasis26.2-pyuno"]:
                    content = b"labelled unit-test DEB fixture; dpkg commands are mocked"
                    entry = tarfile.TarInfo(f"release/DEBS/{package}_26.2.7.1-1_amd64.deb")
                    entry.size = len(content)
                    archive.addfile(entry, io.BytesIO(content))
            for pin in plan["sources"]:
                (sources / pin["name"]).write_text("labelled unit-test source fixture")
            commands = []
            def command_fixture(command, cwd=None, **kwargs):
                command = list(map(str, command))
                commands.append(command)
                if "install" in command:
                    (root / "apt/cache/archives/libfontconfig1_fixture_amd64.deb").write_text("unit-test dependency fixture")
                if "--extract" in command:
                    destination = Path(command[-1])
                    if "libobasis" in command[-2]:
                        office = destination / "opt/libreoffice26.2"
                        for name in ["program/soffice", "program/soffice.bin", "program/fundamentalrc", "LICENSE.html", "NOTICE", "share/fonts/truetype/fixture.ttf"]:
                            p = office / name
                            p.parent.mkdir(parents=True, exist_ok=True)
                            p.write_text("labelled unit-test official runtime fixture")
                    else:
                        p = destination / "usr/share/doc/libfontconfig1/copyright"
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text("labelled unit-test dependency notice")
            def output_fixture(command, **kwargs):
                name = "libobasis26.2-core" if "libobasis" in str(command[-1]) else "libfontconfig1"
                version = "26.2.7.1-1" if name.startswith("libobasis") else "2.13-fixture"
                return f"Package: {name}\nVersion: {version}\nArchitecture: amd64\n"
            (root / "common-licenses").mkdir()
            (root / "common-licenses/LGPL-3").write_text("labelled unit-test license fixture")
            def fixture_path(*args):
                return root / "common-licenses" if args == ("/usr/share/common-licenses",) else Path(*args)
            with patch.object(module, "Path", side_effect=fixture_path), patch.object(module, "run", side_effect=command_fixture), patch.object(module.subprocess, "check_output", side_effect=output_fixture), patch.object(module, "fetch_source", side_effect=lambda p,c: installer if p == plan["installer"] else sources / p["name"]), patch.object(module, "office_external_sources", return_value=[]):
                metadata = module.build_debs("libreoffice", plan, root, payload, sources)
            self.assertEqual(metadata["version"], "26.2.7.1")
            self.assertEqual(metadata["name"], plan["displayName"])
            self.assertIn("pre-release candidate", (payload / "SOURCE-OFFER.txt").read_text())
            self.assertTrue((payload / "root/opt/libreoffice26.2/NOTICE").is_file())
            self.assertTrue((payload / "root/opt/libreoffice26.2/share/fonts/truetype/fixture.ttf").is_file())
            self.assertIn("opt/libreoffice26.2/program", (payload / "bin/libreoffice").read_text())
            self.assertTrue((payload / "SOURCE-OFFER.txt").is_file())
            provenance = json.loads((payload / "PROVENANCE.json").read_text())
            self.assertEqual(provenance["office"]["installer"]["sha256"], plan["installer"]["sha256"])
            self.assertEqual(provenance["office"]["releaseChannel"], "prerelease")
            self.assertEqual([p["package"] for p in provenance["office"]["packages"]], ["libobasis26.2-core"])
            self.assertTrue(any("source" in c and "libfontconfig1=2.13-fixture" in c for c in commands))
            self.assertFalse(any("--extract" in c and "pyuno" in c[-2] for c in commands))

    def test_windows_office_candidate_pins_actual_eight_amd64_crt_members(self):
        module = builder()
        pins = module.build_plan("libreoffice", "windows-x86_64")["crtMembers"]
        expected = {
            "concrt140.dll": "34b64fba6f029a630e773a9cc323720e2250f36d049c2a2e3d8b202feece026d",
            "msvcp140.dll": "157c2531a5bda76bef11d208c4aa704bf6ac6b5d3435b86b2b93dba8f0701600",
            "msvcp140_1.dll": "13af1868c5c66d17526f3a74f3cbac76c279f36ca73259f896120ff72073e02b",
            "msvcp140_2.dll": "44107c382321d49e80e3622794390e3ec89eb332a542a83a6d474c6e164c7460",
            "msvcp140_atomic_wait.dll": "ece7c9fa921a40e7ecb35eb6f6858d03b6c2a0c77911f6e71ae9715cc25dbbdc",
            "msvcp140_codecvt_ids.dll": "27ff490ee875ce357dcb40686905d7ca94cd5be1cf2fc3fd7b1d3f0840878d6e",
            "vcruntime140.dll": "10153b02aa10a8ecb8c71b6d53185651b7a94c96e3a2ebec659d62f512fb97a6",
            "vcruntime140_1.dll": "3784622569df61db345062f2563117038c52f3254325282fcac703ddf026e623"}
        self.assertEqual(len(pins), 8)
        self.assertEqual({p["name"]: p["sha256"] for p in pins}, expected)
        self.assertEqual({p["member"] for p in pins}, {
            name + "_amd64.DFEFC2FE_EEE6_424C_841B_D4E66F0C84A3" for name in expected})

    def test_windows_office_crt_selects_pinned_amd64_cab_members(self):
        from unittest.mock import patch
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = root / "office/program"
            program.mkdir(parents=True)
            content = b"labelled unit-test CRT member; PE parser tested separately"
            pin = dict(name="msvcp140.dll", member="msvcp140.dll_amd64.fixture", sha256=hashlib.sha256(content).hexdigest())
            def expand_fixture(command, **kwargs):
                self.assertIn("-F:" + pin["member"], list(map(str, command)))
                (Path(command[-1]) / pin["member"]).write_bytes(content)
            with patch.object(module, "msi_cabinet_stream", return_value=root / "cabinet.cab"), patch.object(module, "run", side_effect=expand_fixture), patch.object(module, "pe_dependencies", return_value=["kernel32.dll"]) as pe:
                records = module.stage_msi_crt(root / "official.msi", [pin], root, program)
                self.assertEqual((program / pin["name"]).read_bytes(), content)
                self.assertEqual(records, [pin])
                pe.assert_called_once()
                with self.assertRaisesRegex(ValueError, "checksum"):
                    module.stage_msi_crt(root / "official.msi", [dict(pin, sha256="0" * 64)], root, program)

    def test_windows_office_refuses_administrative_extraction_outside_disposable_ci(self):
        from unittest.mock import patch
        module = builder()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "disposable.*CI"):
                module.build_windows_office(module.build_plan("libreoffice", "windows-x86_64"), root, root / "payload", root / "sources")
            self.assertFalse(list(root.iterdir()), "must refuse before downloading or starting MSI")

    def test_windows_office_preserves_full_runtime_and_requires_signed_official_installer(self):
        from unittest.mock import patch
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, sources = root / "payload", root / "sources"
            payload.mkdir()
            sources.mkdir()
            msi = root / "installer.msi"
            msi.write_bytes(b"unit-test MSI fixture, not a distributable")
            source = root / "core.tar.xz"
            source.write_bytes(b"unit-test source fixture")
            crt = b"unit-test x64 CRT fixture"
            plan = dict(**module.OFFICE_CANDIDATE, version="26.2.7.1", installer={"name": "installer.msi"}, sources=[{"name": source.name}],
                        crtMembers=[dict(name="msvcp140.dll", member="msvcp140.dll_amd64.fixture", sha256=hashlib.sha256(crt).hexdigest())])
            calls = []
            def extraction_fixture(command, **kwargs):
                calls.append(list(map(str, command)))
                if str(command[0]).endswith("expand.exe"):
                    (Path(command[-1]) / plan["crtMembers"][0]["member"]).write_bytes(crt)
                    return
                installed = root / "msi-admin/LibreOffice"
                for name in ["program/soffice.com", "program/soffice.bin", "program/runtime.dll", "LICENSE.html", "NOTICE", "share/fonts/truetype/font.ttf", "licenses/third-party.txt"]:
                    path = installed / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("unit-test installed-file fixture")
                (root / "msi-admin/System64").mkdir()
                (root / "msi-admin/System64/msvcp140.dll").write_bytes(b"unit-test colliding ARM64 CRT; must not be copied")
                (root / "msi-admin/Fonts").mkdir()
                (root / "msi-admin/Fonts/official-font.ttf").write_bytes(b"unit-test MSI font fixture")
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), patch.object(module, "msi_cabinet_stream", return_value=root / "cabinet.cab"), patch.object(module, "pe_dependencies", return_value=[]), patch.object(module, "fetch_source", side_effect=lambda p,c: msi if p["name"].endswith("msi") else source), patch.object(module, "office_external_sources", return_value=[]), patch.object(module, "run", side_effect=extraction_fixture), patch.object(module.subprocess, "check_output", return_value=json.dumps({"Status": "Valid", "Subject": "O=The Document Foundation, CN=The Document Foundation"})):
                metadata = module.build_windows_office(plan, root, payload, sources)
            self.assertEqual(metadata["executable"], "office/program/soffice.com")
            self.assertEqual(metadata["name"], plan["displayName"])
            self.assertIn("pre-release candidate", (payload / "SOURCE-OFFER.txt").read_text())
            self.assertTrue((payload / "office/licenses/third-party.txt").is_file())
            self.assertTrue((payload / "office/share/fonts/truetype/font.ttf").is_file())
            self.assertTrue((payload / "office/share/fonts/truetype/official-font.ttf").is_file(), "MSI Fonts must be app-local, not globally installed")
            self.assertTrue((payload / "office/program/runtime.dll").is_file())
            self.assertTrue((payload / "office/program/msvcp140.dll").is_file(), "MSI System64 CRT must become app-local, never borrowed from the runner")
            self.assertEqual((payload / "office/program/msvcp140.dll").read_bytes(), crt)
            self.assertTrue((payload / "SOURCE-OFFER.txt").is_file())
            self.assertIn("/a", calls[0])
            self.assertNotIn("/i", calls[0], "must never install the engine globally")
            self.assertEqual(json.loads((payload / "PROVENANCE.json").read_text())["authenticode"]["Status"], "Valid")
            self.assertEqual(json.loads((payload / "PROVENANCE.json").read_text())["releaseChannel"], "prerelease")

    def test_windows_recipes_dispatch_to_native_builders_not_apt(self):
        from unittest.mock import patch
        module = builder()
        with patch.object(module, "build_windows_ocr", return_value={"id": "tesseract"}) as ocr, patch.object(module, "build_windows_office", return_value={"id": "libreoffice"}) as office, patch.object(module, "build_debs", side_effect=AssertionError("APT must never run for Windows")):
            for component in ["tesseract", "libreoffice"]:
                result = module.build_payload(component, "windows-x86_64", {}, Path("work"), Path("payload"), Path("sources"))
                self.assertEqual(result["id"], component)
            ocr.assert_called_once()
            office.assert_called_once()

    def test_smoke_environment_does_not_borrow_runner_engines_libraries_or_ocr_data(self):
        from unittest.mock import patch
        module = builder()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"PATH": "/runner/tools", "TESSDATA_PREFIX": "/runner/data", "LD_LIBRARY_PATH": "/runner/libs", "PYTHONPATH": "/runner/python", "SystemRoot": "C:/Windows"}):
            root = Path(directory)
            environment = module.smoke_environment(root, windows=True)
            for key in ["TESSDATA_PREFIX", "LD_LIBRARY_PATH", "PYTHONPATH"]:
                self.assertNotIn(key, environment)
            self.assertNotIn("runner", environment["PATH"])
            self.assertEqual(environment["USERPROFILE"], str(root))
            self.assertEqual(environment["SystemRoot"], "C:/Windows")
            self.assertEqual(os.environ["TESSDATA_PREFIX"], "/runner/data")
            self.assertEqual(module.smoke_environment(root, windows=False)["PATH"], "/usr/bin:/bin")

    def test_windows_pe_audit_rejects_wrong_architecture_and_missing_runtime_dlls(self):
        import struct
        module = builder()
        def pe_fixture(imports, delayed=None, machine=0x8664):
            data = bytearray(4096)
            data[:2] = b"MZ"
            struct.pack_into("<I", data, 0x3c, 128)
            data[128:132] = b"PE\0\0"
            struct.pack_into("<HHIIIHH", data, 132, machine, 1, 0, 0, 0, 240, 0)
            struct.pack_into("<H", data, 152, 0x20b)
            struct.pack_into("<I", data, 152 + 108, 16)
            struct.pack_into("<II", data, 152 + 112 + 8, 0x1000, 20 * (len(imports) + 1))
            struct.pack_into("<8sIIII", data, 392, b".idata\0\0", 3584, 0x1000, 3584, 512)
            for index, name in enumerate(imports):
                struct.pack_into("<I", data, 512 + index * 20 + 12, 0x1200 + index * 80)
                encoded = name.encode() + b"\0"
                data[1024 + index * 80:1024 + index * 80 + len(encoded)] = encoded
            if delayed:
                struct.pack_into("<II", data, 152 + 112 + 13 * 8, 0x1500, 64)
                struct.pack_into("<II", data, 1792, 1, 0x1600)
                data[2048:2048 + len(delayed) + 1] = delayed.encode() + b"\0"
            return data
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool = root / "tool.exe"
            tool.write_bytes(pe_fixture(["WINSPOOL.DRV", "pyuno.pyd"]))
            self.assertEqual(module.pe_dependencies(tool), ["pyuno.pyd", "winspool.drv"])
            tool.write_bytes(pe_fixture(["KERNEL32.dll", "VCRUNTIME140.dll"], "USER32.dll"))
            self.assertEqual(set(module.pe_dependencies(tool)), {"kernel32.dll", "vcruntime140.dll", "user32.dll"})
            with self.assertRaisesRegex(ValueError, "vcruntime140.dll"):
                module.audit_windows_runtime(root)
            (root / "VCRUNTIME140.dll").write_bytes(pe_fixture(["KERNEL32.dll"]))
            self.assertEqual(set(module.audit_windows_runtime(root)), {"tool.exe", "VCRUNTIME140.dll"})
            optional = root / "office/program/cli_uno.dll"
            optional.parent.mkdir(parents=True)
            optional.write_bytes(b"unit-test optional Java module fixture")
            findings = module.audit_windows_runtime(root, component="libreoffice")
            self.assertIn("excludedFromHeadlessConversionAudit", findings["office/program/cli_uno.dll"])
            with self.assertRaises(ValueError):
                module.audit_windows_runtime(root)
            optional.unlink()
            tool.write_bytes(pe_fixture([], machine=0x14c))
            with self.assertRaisesRegex(ValueError, "x86_64"):
                module.pe_dependencies(tool)
            tool.write_bytes(b"not a PE")
            with self.assertRaises(ValueError):
                module.pe_dependencies(tool)

    def test_office_audit_identifies_exact_upstream_cross_arch_python_packaging_launchers(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            optional = root / "office/program/python-core-3.12.15/lib/pip/_vendor/distlib/t32.exe"
            self.assertIn(optional.relative_to(root).as_posix(), module.OFFICE_PACKAGING_LAUNCHERS)
            self.assertEqual(len(module.OFFICE_PACKAGING_LAUNCHERS), 10)
            self.assertFalse(any("python-core-3.12.14/" in p for p in module.OFFICE_PACKAGING_LAUNCHERS))
            optional.parent.mkdir(parents=True)
            optional.write_bytes(b"labelled unit-test x86 pip packaging stub, not a conversion binary")
            findings = module.audit_windows_runtime(root, component="libreoffice")
            self.assertIn("excludedFromHeadlessConversionAudit", findings[optional.relative_to(root).as_posix()])
            with self.assertRaises(ValueError):
                module.audit_windows_runtime(root)
            (root / "office/program/not-an-approved-launcher.exe").write_bytes(b"wrong architecture fixture")
            with self.assertRaises(ValueError):
                module.audit_windows_runtime(root, component="libreoffice")
            for name in ["httpapi", "mfplat", "mfplay", "mfreadwrite"]:
                self.assertIn(name, module.WINDOWS_SYSTEM_DLLS)

    def test_elf_metadata_reports_loader_soname(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "libgio-2.0.so.0.7200.4"
            library.write_bytes(elf_fixture(["libc.so.6"], soname="libgio-2.0.so.0"))
            self.assertEqual(module.elf_dependencies(library)["soname"], "libgio-2.0.so.0")
            library.write_bytes(elf_fixture(["libc.so.6"]))
            self.assertIsNone(module.elf_dependencies(library)["soname"])

    def test_linux_elf_closure_rejects_missing_libraries_and_wrong_architecture(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = root / "root/opt/libreoffice26.2/program"
            program.mkdir(parents=True)
            binary = program / "soffice.bin"
            binary.write_bytes(elf_fixture(["libc.so.6", "librequired.so.1"]))
            with self.assertRaisesRegex(ValueError, "librequired.so.1"):
                module.audit_linux_office(root)
            (program / "librequired.so.1").write_bytes(elf_fixture(["libm.so.6"]))
            findings = module.audit_linux_office(root)
            self.assertEqual(findings["root/opt/libreoffice26.2/program/soffice.bin"], ["libc.so.6", "librequired.so.1"])
            binary.write_bytes(elf_fixture([], machine=183))
            with self.assertRaisesRegex(ValueError, "x86_64"):
                module.audit_linux_office(root)
            binary.write_bytes(b"\x7fELFtruncated")
            with self.assertRaises(ValueError):
                module.audit_linux_office(root)

    def test_linux_office_rejects_imports_to_exact_excluded_modules(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            program = payload / "root/opt/libreoffice26.2/program"
            program.mkdir(parents=True)
            optional = program / "libofficebean.so"
            optional.write_bytes(elf_fixture(["libmissing-java.so.1"]))
            binary = program / "soffice.bin"
            binary.write_bytes(elf_fixture(["libc.so.6"]))
            findings = module.audit_linux_office(payload)
            self.assertIn("excludedFromHeadlessConversionAudit", findings[optional.relative_to(payload).as_posix()])
            for search in [None, "$ORIGIN"]:
                with self.subTest(search=search):
                    binary.write_bytes(elf_fixture([optional.name], search=search))
                    with self.assertRaisesRegex(ValueError, "libofficebean.so"):
                        module.audit_linux_office(payload)

    def test_linux_elf_uses_loader_dependencies_not_section_decoys(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            program = payload / "root/opt/libreoffice26.2/program"
            program.mkdir(parents=True)
            binary = program / "soffice.bin"
            binary.write_bytes(elf_fixture(["libmissing-loader.so.1"], section_needed=["libc.so.6"]))
            self.assertEqual(module.elf_dependencies(binary)["needed"], ["libmissing-loader.so.1"])
            with self.assertRaisesRegex(ValueError, "libmissing-loader.so.1"):
                module.audit_linux_office(payload)

    def test_linux_elf_rejects_unsupported_or_malformed_interpreters(self):
        import struct
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "soffice.bin"
            for interpreter in ["/tmp/ld-linux-x86-64.so.2", "ld-linux-x86-64.so.2", "/lib/ld-musl-x86_64.so.1", ""]:
                with self.subTest(interpreter=interpreter):
                    binary.write_bytes(elf_fixture(["libc.so.6"], interpreter=interpreter))
                    with self.assertRaisesRegex(ValueError, "interpreter"):
                        module.elf_dependencies(binary)
            valid = elf_fixture(["libc.so.6"], interpreter="/lib64/ld-linux-x86-64.so.2")
            binary.write_bytes(valid)
            self.assertEqual(module.elf_dependencies(binary)["needed"], ["libc.so.6"])
            for label in ["unterminated", "duplicate", "oversized"]:
                data = bytearray(valid)
                if label == "unterminated":
                    data[3072 + len("/lib64/ld-linux-x86-64.so.2")] = 65
                elif label == "duplicate":
                    struct.pack_into("<H", data, 56, 4)
                    data[232:288] = data[176:232]
                else:
                    struct.pack_into("<QQ", data, 176 + 32, 4097, 4097)
                binary.write_bytes(data)
                with self.subTest(label=label), self.assertRaisesRegex(ValueError, "interpreter"):
                    module.elf_dependencies(binary)

    def test_linux_office_requires_a_valid_shared_object_provider(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            program = payload / "root/opt/libreoffice26.2/program"
            program.mkdir(parents=True)
            (program / "soffice.bin").write_bytes(elf_fixture(["librequired.so.1"]))
            provider = program / "librequired.so.1"
            wrong_abi = elf_fixture(["libc.so.6"])
            wrong_abi[7] = 9  # FreeBSD ABI is not a Linux/glibc provider.
            for label, content in [
                ("text", b"not an ELF shared object"),
                ("wrong-ABI", wrong_abi),
                ("ET_EXEC", elf_fixture(["libc.so.6"], elf_type=2, interpreter="/lib64/ld-linux-x86-64.so.2")),
                ("PIE-interpreter", elf_fixture(["libc.so.6"], interpreter="/lib64/ld-linux-x86-64.so.2")),
                ("PIE-flag-without-interpreter", elf_fixture(["libc.so.6"], flags1=0x08000000)),
            ]:
                with self.subTest(label=label):
                    provider.write_bytes(content)
                    with self.assertRaisesRegex(ValueError, "librequired.so.1"):
                        module.audit_linux_office(payload)
            provider.write_bytes(elf_fixture(["libc.so.6"]))
            self.assertIn("root/opt/libreoffice26.2/program/soffice.bin", module.audit_linux_office(payload))

    def test_linux_office_resolves_rpath_before_environment_but_runpath_after(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            program = payload / "root/opt/libreoffice26.2/program"
            private = program / "private"
            private.mkdir(parents=True)
            binary = program / "soffice.bin"
            (program / "librequired.so.1").write_bytes(elf_fixture(["libc.so.6"]))
            (private / "librequired.so.1").write_text("invalid first RPATH hit")
            binary.write_bytes(elf_fixture(["librequired.so.1"], search="$ORIGIN/private", search_tag=29))
            self.assertIn(binary.relative_to(payload).as_posix(), module.audit_linux_office(payload))
            binary.write_bytes(elf_fixture(["librequired.so.1"], search="$ORIGIN/private", search_tag=15))
            with self.assertRaisesRegex(ValueError, "librequired.so.1"):
                module.audit_linux_office(payload)

    def test_linux_office_resolves_inherited_rpath_but_not_inherited_runpath(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            program = payload / "root/opt/libreoffice26.2/program"
            private = program / "private"
            private.mkdir(parents=True)
            binary = program / "soffice.bin"
            (program / "libchild.so.1").write_bytes(elf_fixture(["libleaf.so.1"]))
            (program / "libleaf.so.1").write_bytes(elf_fixture(["libc.so.6"]))
            (private / "libleaf.so.1").write_text("invalid inherited RPATH hit")
            binary.write_bytes(elf_fixture(["libchild.so.1"], search="$ORIGIN/private", search_tag=29))
            self.assertIn(binary.relative_to(payload).as_posix(), module.audit_linux_office(payload))
            binary.write_bytes(elf_fixture(["libchild.so.1"], search="$ORIGIN/private", search_tag=15))
            with self.assertRaisesRegex(ValueError, "libleaf.so.1"):
                module.audit_linux_office(payload)

    def test_linux_elf_loader_bounds_and_sectionless_metadata(self):
        import struct
        module = builder()
        valid = elf_fixture(["libc.so.6"])
        sectionless = bytearray(valid)
        struct.pack_into("<Q", sectionless, 40, 0)
        struct.pack_into("<HHH", sectionless, 58, 0, 0, 0)
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "soffice.bin"
            binary.write_bytes(sectionless)
            self.assertEqual(module.elf_dependencies(binary)["needed"], ["libc.so.6"])
            # Characterization of the bounded parser: each mutation leaves the
            # benign section metadata intact, so it cannot rescue loader data.
            mutations = [
                ("program-offset", "<Q", 32, 2**64 - 1),
                ("program-width", "<H", 54, 55),
                ("program-count", "<H", 56, 65535),
                ("no-PT_LOAD", "<I", 64, 0),
                ("load-file-bounds", "<Q", 64 + 32, len(valid) + 1),
                ("load-memory-bounds", "<Q", 64 + 40, 1),
                ("load-alignment", "<Q", 64 + 48, 3),
                ("dynamic-offset-disagrees", "<Q", 120 + 8, 2064),
                ("dynamic-not-loaded", "<Q", 120 + 16, 0x500000),
                ("dynamic-entry-width", "<Q", 120 + 32, 63),
                ("dynamic-unterminated", "<q", 2096, 21),
                ("strtab-unmapped", "<Q", 2064 + 8, 0x500000),
                ("strtab-size-overflow", "<Q", 2080 + 8, 2**64 - 1),
                ("needed-string-offset", "<Q", 2048 + 8, 1000),
                ("missing-DT_STRTAB", "<q", 2064, 21),
            ]
            for label, fmt, offset, value in mutations:
                data = bytearray(valid)
                struct.pack_into(fmt, data, offset, value)
                binary.write_bytes(data)
                with self.subTest(label=label), self.assertRaises(ValueError):
                    module.elf_dependencies(binary)
            duplicate = bytearray(valid)
            struct.pack_into("<H", duplicate, 56, 3)
            duplicate[176:232] = duplicate[120:176]
            binary.write_bytes(duplicate)
            with self.assertRaisesRegex(ValueError, "PT_DYNAMIC"):
                module.elf_dependencies(binary)
            duplicate[176:232] = duplicate[64:120]
            binary.write_bytes(duplicate)
            with self.assertRaisesRegex(ValueError, "Overlapping"):
                module.elf_dependencies(binary)

    def test_linux_office_uses_loader_search_paths_not_section_decoys(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            program = payload / "root/opt/libreoffice26.2/program"
            program.mkdir(parents=True)
            binary = program / "soffice.bin"
            for search in ["/runner/libraries", "", "$ORIGIN/../../../../../../outside"]:
                with self.subTest(search=search):
                    binary.write_bytes(elf_fixture(["libc.so.6"], search=search, section_search="$ORIGIN"))
                    with self.assertRaisesRegex(ValueError, "ELF search path"):
                        module.audit_linux_office(payload)

    def test_linux_office_rejects_unmodeled_dynamic_search_tokens(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            program = payload / "root/opt/libreoffice26.2/program"
            literal = program / "$LIB"
            literal.mkdir(parents=True)
            (literal / "librequired.so.1").write_bytes(elf_fixture(["libc.so.6"]))
            (program / "soffice.bin").write_bytes(elf_fixture(["librequired.so.1"], search="$ORIGIN/$LIB"))
            with self.assertRaisesRegex(ValueError, "ELF search path"):
                module.audit_linux_office(payload)

    def test_linux_office_refuses_unmodeled_hardware_search_overrides(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            program = payload / "root/opt/libreoffice26.2/program"
            program.mkdir(parents=True)
            (program / "librequired.so.1").write_bytes(elf_fixture(["libc.so.6"]))
            (program / "soffice.bin").write_bytes(elf_fixture(["librequired.so.1"]))
            for suffix in ["glibc-hwcaps/x86-64-v2", "tls", "x86_64"]:
                override = program / suffix / "librequired.so.1"
                override.parent.mkdir(parents=True)
                override.write_text("CPU-dependent first hit, not a native library")
                with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, "hardware.*search"):
                    module.audit_linux_office(payload)
                override.unlink()
                override.parent.rmdir()
                if suffix.startswith("glibc-hwcaps/"):
                    (program / "glibc-hwcaps").rmdir()

    def test_zip_entry_limit_counts_archived_files_not_unarchived_directories(self):
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload"
            (payload / "a/b/c").mkdir(parents=True)
            (payload / "a/b/c/tool").write_text("fixture")
            metadata = dict(id="tesseract", name="OCR", version="fixture", platform="windows-x86_64", license="Apache-2.0", executable="a/b/c/tool")
            module.MAX_FILES = 1
            result = module.create_pack(payload, root / "out", metadata)
            with zipfile.ZipFile(result["archive"]) as archive:
                self.assertEqual(len(archive.infolist()), 1)
            (payload / "second").write_text("fixture")
            with self.assertRaisesRegex(ValueError, "limits"):
                module.create_pack(payload, root / "out", metadata)

    def test_ocr_smoke_selects_a_native_font_without_assuming_linux_on_windows(self):
        from unittest.mock import patch
        module = builder()
        with patch.dict(os.environ, {"WINDIR": "C:/Windows"}):
            self.assertEqual(module.ocr_smoke_font(windows=True).as_posix(), "C:/Windows/Fonts/arial.ttf")
            self.assertEqual(module.ocr_smoke_font(windows=False).as_posix(), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

    def test_windows_signature_check_does_not_inherit_pwsh_module_path(self):
        from unittest.mock import patch
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def signature_fixture(command, **kwargs):
                self.assertFalse(any(k.upper() == "PSMODULEPATH" for k in kwargs["env"]))
                self.assertIn("Import-Module Microsoft.PowerShell.Security", command[-1])
                self.assertIn("$ErrorActionPreference='Stop'", command[-1])
                return json.dumps({"Status": "HashMismatch", "Subject": "O=The Document Foundation"})
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "PSModulePath": "PowerShell7-only-modules"}), patch.object(module, "fetch_source", return_value=root / "official.msi"), patch.object(module.subprocess, "check_output", side_effect=signature_fixture), patch.object(module, "run") as run:
                with self.assertRaisesRegex(ValueError, "Authenticode"):
                    module.build_windows_office(module.build_plan("libreoffice", "windows-x86_64"), root, root / "payload", root / "sources")
                run.assert_not_called()

    def test_windows_office_rejects_invalid_signatures_before_sources_or_msi_execution(self):
        from unittest.mock import patch
        module = builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for signature in [{"Status": "HashMismatch", "Subject": "O=The Document Foundation"}, {"Status": "Valid", "Subject": "O=Unrelated Publisher"}]:
                with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), patch.object(module, "fetch_source", return_value=root / "official.msi") as fetch, patch.object(module, "run") as run, patch.object(module.subprocess, "check_output", return_value=json.dumps(signature)):
                    with self.assertRaisesRegex(ValueError, "Authenticode"):
                        module.build_windows_office(module.build_plan("libreoffice", "windows-x86_64"), root, root / "payload", root / "sources")
                    fetch.assert_called_once()
                    run.assert_not_called()

    def test_ffmpeg_uses_7_1_maintenance_memory_safety_fixes(self):
        module = builder()
        for platform in ("windows-x86_64", "linux-x86_64"):
            plan = module.build_plan("ffmpeg", platform)
            self.assertEqual(plan["version"], "7.1.5-vpx1.15.2-opus1.5.2")
            self.assertEqual(plan["sources"][0]["sha256"], "de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f")

    def test_supported_build_plan_pins_sources_and_does_not_advertise_unbuilt_ai(self):
        module = builder()
        self.assertTrue(callable(getattr(module, "build_plan", None)), "reproducible build plan is missing")
        for platform in ("windows-x86_64", "linux-x86_64"):
            plan = module.build_plan("ffmpeg", platform)
            self.assertEqual(plan["version"], "7.1.5-vpx1.15.2-opus1.5.2")
            self.assertEqual(len(plan["sources"]), 3)
            for source in plan["sources"]:
                self.assertTrue(source["url"].startswith("https://"))
                self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
                self.assertNotIn("latest", source["url"])
            self.assertIn("--disable-gpl", plan["configure"])
            self.assertIn("--disable-nonfree", plan["configure"])
            self.assertIn("--disable-autodetect", plan["configure"])
        for component in ("whisper", "llama"):
            with self.assertRaises(ValueError):
                module.build_plan(component, "windows-x86_64")
        self.assertIn("20261001T000000Z", module.build_plan("tesseract", "linux-x86_64")["snapshot"])

    def test_source_cache_is_verified_before_use_and_unsafe_tar_is_rejected(self):
        import io
        import tarfile
        module = builder()
        self.assertTrue(callable(getattr(module, "fetch_source", None)), "verified source download is missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tar"
            with tarfile.open(source, "w") as archive:
                entry = tarfile.TarInfo("../escape")
                entry.size = 4
                archive.addfile(entry, io.BytesIO(b"evil"))
            pin = {"name": source.name, "url": "https://example.invalid/source.tar",
                   "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
            self.assertEqual(module.fetch_source(pin, root), source)
            with self.assertRaises(ValueError):
                module.unpack_source(source, root / "extracted")
            self.assertFalse((root / "escape").exists())
            source.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                module.fetch_source(pin, root)

    def test_cli_prints_a_real_build_plan_without_downloading_or_claiming_a_release(self):
        import subprocess
        result = subprocess.run([sys.executable, str(SCRIPT), "--component", "ffmpeg", "--platform",
                                 "linux-x86_64", "--plan"], capture_output=True, text=True, check=True)
        self.assertTrue(result.stdout.startswith("{"), "CLI must produce the selected build plan")
        plan = json.loads(result.stdout)
        self.assertEqual(plan["version"], "7.1.5-vpx1.15.2-opus1.5.2")
        self.assertNotIn("url", plan)

    def test_real_build_refuses_a_non_native_target_before_downloading(self):
        import subprocess
        target = "linux-x86_64" if os.name == "nt" else "windows-x86_64"
        result = subprocess.run([sys.executable, str(SCRIPT), "--component", "ffmpeg", "--platform", target],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, "unsupported hosts must fail closed, not crash or create a fake pack")
        self.assertIn("native", result.stderr.lower())

    def test_office_smoke_uses_a_real_docx_package_not_html_renamed_as_office(self):
        module = builder()
        self.assertTrue(callable(getattr(module, "office_fixture", None)), "Office smoke needs a real OOXML fixture")
        with tempfile.TemporaryDirectory() as directory:
            source = module.office_fixture(Path(directory))
            self.assertEqual(source.suffix, ".docx")
            with zipfile.ZipFile(source) as archive:
                self.assertIn("[Content_Types].xml", archive.namelist())
                self.assertIn("word/document.xml", archive.namelist())
                self.assertIn(b"Leafsmith conversion smoke", archive.read("word/document.xml"))


if __name__ == "__main__":
    unittest.main()
