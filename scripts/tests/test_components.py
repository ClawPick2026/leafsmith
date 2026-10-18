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

    def test_windows_ocr_plan_pins_all_native_sources_and_english_osd_data(self):
        module = builder()
        plan = module.build_plan("tesseract", "windows-x86_64")
        self.assertEqual(plan["builder"], "cmake-msvc-static")
        self.assertEqual(plan["version"], "5.5.1-lept1.85.0-png1.6.50-zlib1.3.1-data4.1.0")
        self.assertEqual({s["name"] for s in plan["sources"]}, {
            "tesseract-5.5.1.tar.gz", "leptonica-1.85.0.tar.gz", "libpng-1.6.50.tar.gz", "zlib-1.3.1.tar.gz"})
        self.assertEqual({s["name"] for s in plan["data"]}, {"eng.traineddata", "osd.traineddata", "tessdata-LICENSE"})
        for pin in plan["sources"] + plan["data"]:
            self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(pin["url"].startswith("https://"))
            self.assertNotIn("/main/", pin["url"])
        self.assertEqual(plan["imageCodecs"], ["PNG", "PNM", "BMP"])
        self.assertEqual(plan["runtimeNotices"][0]["sha256"], "9c0cd52b20db9d081854c75bd1b50c75514b8f8cb09c8cad15e89d90b97b5bf3")

    def test_windows_office_plan_uses_official_msi_and_matching_source_bundles(self):
        module = builder()
        plan = module.build_plan("libreoffice", "windows-x86_64")
        self.assertEqual(plan["builder"], "official-msi-admin-extract-ci-only")
        self.assertEqual(plan["version"], "25.2.7.2")
        self.assertEqual(plan["installer"]["sha256"], "9fdd22f8ea7a92a67de5beaa08588ef6da58c1930ac86fd57c46b0c6d7ca9d34")
        for pin in [plan["installer"], *plan["sources"]]:
            self.assertTrue(pin["url"].startswith("https://downloadarchive.documentfoundation.org/libreoffice/old/25.2.7.2/"))
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
                    entry = tarfile.TarInfo("libreoffice-25.2.7.2/download.lst")
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
        for required in ["-DSW_BUILD=OFF", "-DBUILD_SHARED_LIBS=OFF", "-DWIN32_MT_BUILD=ON", "-DDISABLE_ARCHIVE=ON", "-DDISABLE_CURL=ON", "-DDISABLE_TIFF=ON", "-DOPENMP_BUILD=OFF", "-DENABLE_NATIVE=OFF", "-DGRAPHICS_DISABLED=ON", "-DBUILD_TRAINING_TOOLS=OFF"]:
            self.assertIn(required, flags)
        flags = module.ocr_cmake_options("leptonica", prefix)
        for codec in ["GIF", "JPEG", "TIFF", "WEBP", "OPENJPEG"]:
            self.assertIn(f"-DENABLE_{codec}=OFF", flags)
        self.assertIn("-DENABLE_PNG=ON", flags)
        self.assertIn("-DSTRICT_CONF=ON", flags)
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
            plan = dict(version="25.2.7.2", installer={"name": "installer.msi"}, sources=[{"name": source.name}])
            calls = []
            def extraction_fixture(command, **kwargs):
                calls.append(list(map(str, command)))
                installed = root / "msi-admin/LibreOffice"
                for name in ["program/soffice.com", "program/soffice.bin", "program/runtime.dll", "LICENSE.html", "NOTICE", "share/fonts/truetype/font.ttf", "licenses/third-party.txt"]:
                    path = installed / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("unit-test installed-file fixture")
                (root / "msi-admin/System64").mkdir()
                (root / "msi-admin/System64/msvcp140.dll").write_bytes(b"unit-test x64 CRT fixture")
                (root / "msi-admin/Fonts").mkdir()
                (root / "msi-admin/Fonts/official-font.ttf").write_bytes(b"unit-test MSI font fixture")
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), patch.object(module, "pe_dependencies", return_value=[]), patch.object(module, "fetch_source", side_effect=lambda p,c: msi if p["name"].endswith("msi") else source), patch.object(module, "office_external_sources", return_value=[]), patch.object(module, "run", side_effect=extraction_fixture), patch.object(module.subprocess, "check_output", return_value=json.dumps({"Status": "Valid", "Subject": "O=The Document Foundation, CN=The Document Foundation"})):
                metadata = module.build_windows_office(plan, root, payload, sources)
            self.assertEqual(metadata["executable"], "office/program/soffice.com")
            self.assertTrue((payload / "office/licenses/third-party.txt").is_file())
            self.assertTrue((payload / "office/share/fonts/truetype/font.ttf").is_file())
            self.assertTrue((payload / "office/share/fonts/truetype/official-font.ttf").is_file(), "MSI Fonts must be app-local, not globally installed")
            self.assertTrue((payload / "office/program/runtime.dll").is_file())
            self.assertTrue((payload / "office/program/msvcp140.dll").is_file(), "MSI System64 CRT must become app-local, never borrowed from the runner")
            self.assertTrue((payload / "SOURCE-OFFER.txt").is_file())
            self.assertIn("/a", calls[0])
            self.assertNotIn("/i", calls[0], "must never install the engine globally")
            self.assertEqual(json.loads((payload / "PROVENANCE.json").read_text())["authenticode"]["Status"], "Valid")

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

    def test_supported_build_plan_pins_sources_and_does_not_advertise_unbuilt_ai(self):
        module = builder()
        self.assertTrue(callable(getattr(module, "build_plan", None)), "reproducible build plan is missing")
        for platform in ("windows-x86_64", "linux-x86_64"):
            plan = module.build_plan("ffmpeg", platform)
            self.assertEqual(plan["version"], "7.1.3-vpx1.15.2-opus1.5.2")
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
        self.assertEqual(plan["version"], "7.1.3-vpx1.15.2-opus1.5.2")
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
                self.assertIn(b"Paperwork conversion smoke", archive.read("word/document.xml"))


if __name__ == "__main__":
    unittest.main()
