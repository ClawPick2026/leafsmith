"""AI pack contract tests; inference belongs to native opt-in CI, not mocks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "build_ai_components.py"


def builder():
    if not SCRIPT.exists():
        raise AssertionError("AI pack builder is not implemented")
    spec = importlib.util.spec_from_file_location("ai_components", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackTests(unittest.TestCase):
    def test_model_zip_is_separate_deterministic_regular_files_with_actual_digest(self):
        api = builder()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload"
            (payload / "models").mkdir(parents=True)
            (payload / "models/tiny.bin").write_bytes(b"unit fixture, not weights")
            (payload / "LICENSE").write_text("unit license fixture")
            metadata = {"id": "whisper_model", "name": "Tiny English", "version": "test1",
                        "platform": "linux-x86_64", "license": "MIT", "executable": "models/tiny.bin"}
            first = api.create_pack(payload, root / "one", metadata)
            second = api.create_pack(payload, root / "two", metadata)
            archive = Path(first["archive"])
            self.assertEqual(archive.read_bytes(), Path(second["archive"]).read_bytes())
            self.assertEqual(first["manifest"]["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertEqual(first["manifest"]["downloadBytes"], archive.stat().st_size)
            self.assertEqual(set(first["manifest"]), set(metadata) | {"sha256", "downloadBytes"})
            self.assertEqual(json.loads(Path(first["manifestPath"]).read_text()), first["manifest"])
            with zipfile.ZipFile(archive) as packed:
                self.assertEqual(packed.read("models/tiny.bin"), b"unit fixture, not weights")
                self.assertTrue(all(stat.S_ISREG(x.external_attr >> 16) for x in packed.infolist()))
                self.assertFalse(packed.getinfo("models/tiny.bin").external_attr >> 16 & 0o111)

    def test_case_colliding_zip_paths_are_rejected_before_manifest(self):
        api = builder()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload"
            payload.mkdir()
            (payload / "llama-cli").write_bytes(b"native fixture")
            (payload / "Notice").write_text("a")
            (payload / "notice").write_text("b")
            if len(list(payload.iterdir())) != 3:
                self.skipTest("Host filesystem is case insensitive")
            metadata = {"id": "llama", "name": "llama", "version": "test", "platform": "linux-x86_64",
                        "license": "MIT", "executable": "llama-cli"}
            with self.assertRaisesRegex(ValueError, "[Cc]ollid|[Dd]uplicate"):
                api.create_pack(payload, root / "out", metadata)
            self.assertFalse((root / "out").exists())

    def test_pack_safety_limits_and_engine_permissions(self):
        api = builder()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload"
            payload.mkdir()
            (payload / "whisper-cli").write_bytes(b"native unit fixture")
            metadata = {"id": "whisper", "name": "whisper", "version": "test", "platform": "linux-x86_64",
                        "license": "MIT", "executable": "whisper-cli"}
            packed = api.create_pack(payload, root / "ok", metadata)
            with zipfile.ZipFile(packed["archive"]) as archive:
                self.assertTrue(archive.getinfo("whisper-cli").external_attr >> 16 & 0o111)
            for constant in ["MAX_FILES", "MAX_EXTRACTED", "MAX_DOWNLOAD"]:
                previous = getattr(api, constant)
                setattr(api, constant, 0)
                try:
                    with self.subTest(constant=constant), self.assertRaises(ValueError):
                        api.create_pack(payload, root / constant, metadata)
                finally:
                    setattr(api, constant, previous)
            if __import__("os").name != "nt":
                (payload / "linked").symlink_to(payload / "whisper-cli")
                with self.assertRaises(ValueError):
                    api.create_pack(payload, root / "bad-link", metadata)


class SourceTests(unittest.TestCase):
    def test_cached_download_is_checked_for_both_digest_and_exact_length(self):
        api = builder()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "source.tar.gz"
            path.write_bytes(b"actual source fixture")
            pin = {"name": path.name, "url": "https://invalid.example/pinned",
                   "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            self.assertEqual(api.fetch(pin, root), path)
            for field, value in [("bytes", 1), ("sha256", "0" * 64), ("name", "../escape")]:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    api.fetch(dict(pin, **{field: value}), root)
    def test_source_tar_rejects_links_traversal_and_limits_before_extracting(self):
        import io
        import tarfile
        api = builder()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, kind in [("repo/a.txt", tarfile.REGTYPE), ("../escape", tarfile.REGTYPE),
                               ("repo/link", tarfile.SYMTYPE), ("repo/device", tarfile.CHRTYPE)]:
                archive = root / "source.tar"
                with tarfile.open(archive, "w") as out:
                    item = tarfile.TarInfo(name)
                    item.type = kind
                    item.size = 2 if kind == tarfile.REGTYPE else 0
                    item.linkname = "../../escape" if kind == tarfile.SYMTYPE else ""
                    out.addfile(item, io.BytesIO(b"ok") if item.size else None)
                destination = root / ("good" if name == "repo/a.txt" else "bad")
                if name == "repo/a.txt":
                    api.unpack_source(archive, destination)
                    self.assertEqual((destination / name).read_bytes(), b"ok")
                else:
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        api.unpack_source(archive, destination)
                    self.assertFalse(destination.exists())

    def test_installer_like_zip_extraction_checks_paths_and_only_chmods_entry(self):
        api = builder()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packed = root / "pack.zip"
            with zipfile.ZipFile(packed, "w") as out:
                out.writestr("bin/whisper-cli", b"native fixture")
                out.writestr("licenses/MIT", b"notice")
            installed = api.extract_pack(packed, root / "installed with spaces", "bin/whisper-cli", True)
            self.assertEqual((installed / "bin/whisper-cli").read_bytes(), b"native fixture")
            if __import__("os").name != "nt":
                self.assertTrue((installed / "bin/whisper-cli").stat().st_mode & 0o100)
                self.assertFalse((installed / "licenses/MIT").stat().st_mode & 0o111)
            for name in ["../escape", "C:/escape", "bad\\name", "bin/CON", "bin/trailing."]:
                with zipfile.ZipFile(packed, "w") as out:
                    out.writestr(name, b"bad")
                with self.subTest(name=name), self.assertRaises(ValueError):
                    api.extract_pack(packed, root / "bad", name, False)


class SmokeGateTests(unittest.TestCase):
    def test_native_dependency_audit_rejects_non_system_runtime(self):
        api = builder()
        linux = ' 0x0000000000000001 (NEEDED) Shared library: [libstdc++.so.6]\n 0x0000000000000001 (NEEDED) Shared library: [libc.so.6]'
        self.assertEqual(api.audit_links("linux-x86_64", linux), ["libc.so.6", "libstdc++.so.6"])
        windows = 'Image has the following dependencies:\n    KERNEL32.dll\n    ADVAPI32.dll\n'
        self.assertEqual(api.audit_links("windows-x86_64", windows), ["advapi32.dll", "kernel32.dll"])
        for target, text in [("linux-x86_64", linux + '\n(NEEDED) Shared library: [libggml.so]'),
                             ("linux-x86_64", linux + '\n(RUNPATH) Library runpath: [/builder]'),
                             ("windows-x86_64", windows + '\n    VCRUNTIME140.dll\n'),
                             ("windows-x86_64", "unrecognized output")]:
            with self.subTest(target=target, text=text), self.assertRaises(ValueError):
                api.audit_links(target, text)

    def test_quality_gates_accept_known_content_and_reject_nonempty_garbage(self):
        api = builder()
        text = "And so my fellow Americans ask not what your country can do for you ask what you can do for your country"
        passed = api.assess_speech(text, "1\n00:00:00,000 --> 00:00:11,000\n" + text)
        self.assertEqual(passed["wordErrorRate"], 0)
        self.assertEqual(passed["maxWordErrorRate"], 0.35)
        for speech, srt in [("arbitrary nonempty hallucination", "1\n00:00:00,000 --> 00:00:11,000"),
                            (text, "invalid timestamps")]:
            with self.assertRaises(ValueError):
                api.assess_speech(speech, srt)
        quality = api.assess_text("Alice approved a $5 budget; the team meets Friday.",
                                  "Bonjour, je m'appelle Alice. La réunion est vendredi.")
        self.assertEqual(quality["summaryFactHits"], 3)
        self.assertEqual(quality["translationTokenHits"], 3)
        with self.assertRaises(ValueError):
            api.assess_text("generic unrelated output", "not a translation")

    def test_text_gate_requires_each_fact_and_french_marker_including_observed_wrong_weekday(self):
        # Characterization, not new inference: preserve the existing gate without changing it.
        api = builder()
        summary = "Alice approved a five dollar budget. The team will meet on Friday."
        french = "Bonjour, mon nom est Alice. Le rendez-vous est vendredi."
        for missing, replacement in (("Alice", "Someone"), ("five", "six"), ("Friday", "Tuesday")):
            with self.subTest(summaryMissing=missing), self.assertRaisesRegex(ValueError, "quality gate"):
                api.assess_text(summary.replace(missing, replacement), french)
        for missing, replacement in (("Bonjour", "Hello"), ("Alice", "Bob"), ("vendredi", "mardi")):
            with self.subTest(translationMissing=missing), self.assertRaisesRegex(ValueError, "quality gate"):
                api.assess_text(summary, french.replace(missing, replacement))
        # Actual 0.5B native diagnostic translation from both Windows and Linux.
        with self.assertRaisesRegex(ValueError, "quality gate"):
            api.assess_text(summary, "Bonjour, mon nom est Alice. Le rendez-vous est mardi. [end of text]")
        for short_or_long in ("Alice 5", summary + "x" * 4001):
            with self.subTest(summaryLength=len(short_or_long)), self.assertRaises(ValueError):
                api.assess_text(short_or_long, french)
        for short_or_long in ("Bonjour", french + "x" * 4001):
            with self.subTest(translationLength=len(short_or_long)), self.assertRaises(ValueError):
                api.assess_text(summary, short_or_long)


class RecipeTests(unittest.TestCase):
    def test_llama_candidate_is_official_15b_q2k_with_measured_immutable_pins(self):
        api = builder()
        revision = "91cad51170dc346986eccefdc2dd33a9da36ead9"
        base = f"https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/{revision}/"
        for target in ("linux-x86_64", "windows-x86_64"):
            with self.subTest(target=target):
                plan = api.build_plan("llama", target)
                self.assertEqual(plan["model"], {
                    "name": "qwen2.5-1.5b-instruct-q2_k.gguf",
                    "version": "qwen2.5-1.5b-q2k-91cad511-r1",
                    "license": "Apache-2.0", "revision": revision, "bytes": 752880160,
                    "url": base + "qwen2.5-1.5b-instruct-q2_k.gguf",
                    "sha256": "5ede348e91ce1e7a330926ec5b202c27b864d065149dc463257fde1f98865b3a",
                })
                self.assertEqual(plan["notices"], [
                    {"name": "Qwen-LICENSE", "bytes": 11343, "url": base + "LICENSE",
                     "sha256": "832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e"},
                    {"name": "Qwen-model-card.md", "bytes": 4856, "url": base + "README.md",
                     "sha256": "57c72d4010fb11a98fc8e62dc8ef112b23a7a7525b71e571ca978d35cb3b2eec"},
                ])
        self.assertEqual(api.MAX_DOWNLOAD, 750 * 1024 * 1024)
        self.assertEqual(api.MAX_EXTRACTED, 2 * 1024 * 1024 * 1024)
        self.assertLess(752880160 + sum(p["bytes"] for p in plan["notices"]), api.MAX_DOWNLOAD)
        # Copy coverage only: real pack metadata and NOTICE must describe the new candidate.
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('else "Qwen2.5 1.5B Instruct Q2_K"', source)
        self.assertIn("1.5B Q2_K quantized text models have limited accuracy", source)
        self.assertNotIn("0.5b", source.lower())

    def test_plan_pins_source_models_and_disables_network_accelerators(self):
        api = builder()
        for component in ("whisper", "llama"):
            for target in ("linux-x86_64", "windows-x86_64"):
                plan = api.build_plan(component, target)
                self.assertRegex(plan["source"]["commit"], r"^[0-9a-f]{40}$")
                for pin in [plan["source"], plan["model"], *plan["notices"]]:
                    self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
                    self.assertGreater(pin["bytes"], 0)
                    self.assertLessEqual(pin["bytes"], api.MAX_DOWNLOAD)
                    self.assertTrue(pin["url"].startswith("https://"))
                flags = plan["cmake"]
                self.assertIn("-DBUILD_SHARED_LIBS=OFF", flags)
                self.assertIn("-DGGML_NATIVE=OFF", flags)
                self.assertIn("-DGGML_CUDA=OFF", flags)
                self.assertIn("-DGGML_OPENMP=OFF", flags)
                self.assertIn(f"-D{component.upper()}_CURL=OFF", flags)
                if target.startswith("windows"):
                    self.assertIn("-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded", flags)
                    self.assertIn("-DCMAKE_C_COMPILER=cl", flags)
                    self.assertIn("-DCMAKE_CXX_COMPILER=cl", flags)
                    self.assertEqual({p["name"] for p in plan["runtimeNotices"]},
                                     {"Microsoft-STL-LICENSE.txt", "Microsoft-STL-NOTICE.txt"})
        with self.assertRaises(ValueError):
            api.build_plan("llama_model", "linux-x86_64")
    def test_command_runner_preserves_explicit_environment_and_propagates_failure(self):
        import os
        import subprocess
        import sys
        api = builder()
        with tempfile.TemporaryDirectory() as temporary:
            result = Path(temporary) / "environment.txt"
            api.run([sys.executable, "-c", "import os,pathlib,sys;pathlib.Path(sys.argv[1]).write_text(os.environ['GIT_CEILING_DIRECTORIES'])", str(result)],
                    env=dict(os.environ, GIT_CEILING_DIRECTORIES=temporary))
            self.assertEqual(result.read_text(), temporary)
            with self.assertRaises(subprocess.CalledProcessError):
                api.run([sys.executable, "-c", "raise SystemExit(7)"])

    def test_cli_plan_is_json_without_network_or_output_writes(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, str(SCRIPT), "--component", "llama", "--platform",
                                     "windows-x86_64", "--work", temporary, "--plan"],
                                    capture_output=True, text=True, check=True)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["component"], "llama")
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_build_requires_consent_and_native_host_before_creating_files(self):
        api = builder()
        import os
        other = "linux-x86_64" if os.name == "nt" else "windows-x86_64"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, "allow-model-downloads"):
                api.build("whisper", other, root / "work", root / "out", False)
            with self.assertRaisesRegex(RuntimeError, "native"):
                api.build("whisper", other, root / "work", root / "out", True)
            self.assertEqual(list(root.iterdir()), [])

    def test_notices_preserve_inline_vendored_licenses(self):
        api = builder()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "examples").mkdir(parents=True)
            (source / "LICENSE").write_text("MIT upstream license")
            (source / "examples/miniaudio.h").write_text("inline miniaudio license")
            (source / "examples/stb_vorbis.c").write_text("inline vorbis license")
            payload = root / "payload"
            api.copy_notices("whisper", source, payload)
            self.assertEqual((payload / "licenses/upstream/LICENSE").read_text(), "MIT upstream license")
            self.assertEqual((payload / "licenses/upstream/examples/miniaudio.h").read_text(), "inline miniaudio license")


if __name__ == "__main__":

    unittest.main()
