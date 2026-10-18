"""Linux redistribution contracts; synthetic data is never release evidence."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "audit_linux_libraries.py"


def api():
    if not SCRIPT.exists():
        raise AssertionError("Linux shipped-library auditor is missing")
    spec = importlib.util.spec_from_file_location("linux_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InventoryTests(unittest.TestCase):
    def test_real_payload_includes_versioned_and_vendored_shared_libraries(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in ["_internal/libffi.so.8", "_internal/Pillow.libs/libjpeg-abc.so.62", "_internal/pkg/mod.cpython-312-x86_64-linux-gnu.so"]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture native library")
            (root / "not-a-library.txt").write_text("not native")
            found = api().shared_libraries(root)
            self.assertEqual(sorted(p.relative_to(root).as_posix() for p in found), sorted([
                "_internal/libffi.so.8", "_internal/Pillow.libs/libjpeg-abc.so.62", "_internal/pkg/mod.cpython-312-x86_64-linux-gnu.so"]))


class OwnershipTests(unittest.TestCase):
    def test_relocated_cpython_soname_and_dynload_use_runtime_notice(self):
        import tempfile
        from unittest.mock import patch
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "lib/python3.12/lib-dynload").mkdir(parents=True)
            (root / "lib/libpython3.12.so.1.0").write_bytes(b"actual runtime fixture")
            (root / "lib/python3.12/lib-dynload/_ssl.cpython-312-x86_64-linux-gnu.so").write_bytes(b"actual stdlib fixture")
            (root / "notices/python-runtime").mkdir(parents=True)
            (root / "notices/python-runtime/LICENSE.txt").write_text("CPython license fixture")
            config = {"DESTSHARED": "/build/install/lib/python3.12/lib-dynload", "LDLIBRARY": "libpython3.12.so", "INSTSONAME": "libpython3.12.so.1.0", "LIBDIR": "/build/install/lib"}
            with patch.object(module.sysconfig, "get_config_var", config.get), patch.object(module.sysconfig, "get_path", lambda key: str(root / "lib/python3.12")), patch.object(module.sys, "base_prefix", str(root)):
                for name in ["libpython3.12.so.1.0", "_ssl.cpython-312-x86_64-linux-gnu.so"]:
                    owner = module.python_runtime_owner(Path("_internal") / name, root / "notices")
                    self.assertIsNotNone(owner, name)
                    self.assertEqual(owner["kind"], "python-runtime")

    def test_wheel_record_maps_vendored_basename_to_actual_notices(self):
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            notice = root / "python/pillow/LICENSE"
            notice.parent.mkdir(parents=True)
            notice.write_text("Actual wheel notice fixture")
            original = root / "site/Pillow.libs/libjpeg-123.so.62"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"native fixture")
            dist = SimpleNamespace(metadata={"Name": "Pillow"}, version="11.0", files=[Path("Pillow.libs/libjpeg-123.so.62")], locate_file=lambda f: root / "site" / f)
            index = api().wheel_owners([dist], [{"name": "Pillow", "version": "11.0", "license": "MIT", "notices": ["python/pillow/LICENSE"]}], root)
            record = api().wheel_owner(Path("_internal/libjpeg-123.so.62"), index)
            self.assertEqual(record["name"], "Pillow")
            self.assertEqual(record["notices"], ["python/pillow/LICENSE"])
            self.assertEqual(record["original"], str(original))

    def test_ambiguous_record_basenames_fail_instead_of_picking_first(self):
        index = {"native.so": [{"name": "first", "record": "a/native.so"}, {"name": "second", "record": "b/native.so"}]}
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            api().wheel_owner(Path("_internal/native.so"), index)

    def test_notice_paths_cannot_escape_resource_directory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "Unsafe|Missing"):
                api().checked_file(Path(folder), "../../outside")

    def test_system_owner_uses_real_ldconfig_path_and_exact_source_version(self):
        from unittest.mock import patch
        import subprocess
        def run(command, **kwargs):
            if command[:2] == ["ldconfig", "-p"]:
                text = "libffi.so.8 (libc6,x86-64) => /lib/x86_64-linux-gnu/libffi.so.8\n"
            elif command[:2] == ["dpkg-query", "-S"]:
                if command[2] != str(Path("/lib/x86_64-linux-gnu/libffi.so.8")):
                    return subprocess.CompletedProcess(command, 1, "", "not owned")
                text = "libffi8:amd64: " + command[2] + "\n"
            elif command[:2] == ["dpkg-query", "-W"]:
                text = "libffi8:amd64\t3.4.2-4\tlibffi\t3.4.2-4\n"
            else:
                raise AssertionError(command)
            return subprocess.CompletedProcess(command, 0, text, "")
        module = api()
        with patch.object(module.subprocess, "run", run):
            record = module.debian_owner(Path("_internal/libffi.so.8"), module.linker_paths())
        self.assertEqual(record["source_package"], "libffi")
        self.assertEqual(record["source_version"], "3.4.2-4")
        self.assertEqual(record["original"], str(Path("/lib/x86_64-linux-gnu/libffi.so.8")))

    def test_known_freezer_origin_cannot_be_reassigned_to_host_soname(self):
        import tempfile
        import subprocess
        from unittest.mock import patch
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "custom-python/libcrypto.so.3"
            original.parent.mkdir()
            original.write_bytes(b"not owned by Debian")
            def run(command, **kwargs):
                if command[:2] == ["dpkg-query", "-S"] and command[2] == "/lib/host/libcrypto.so.3":
                    return subprocess.CompletedProcess(command, 0, "libssl3:amd64: /lib/host/libcrypto.so.3\n", "")
                if command[:2] == ["dpkg-query", "-W"]:
                    return subprocess.CompletedProcess(command, 0, "libssl3:amd64\t3.0\topenssl\t3.0\n", "")
                return subprocess.CompletedProcess(command, 1, "", "not owned")
            with patch.object(module.subprocess, "run", run):
                with self.assertRaisesRegex(ValueError, "Unmapped"):
                    module.debian_owner(original, {original.name: [Path("/lib/host/libcrypto.so.3")]})

    def test_freezer_toc_captures_original_native_paths(self):
        import tempfile
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            toc = Path(folder) / "COLLECT-00.toc"
            toc.write_text(repr(([('libffi.so.8', '/usr/lib/x86_64-linux-gnu/libffi.so.8.1.0', 'BINARY'), ('pkg/ext.so', '/venv/site/pkg/ext.so', 'EXTENSION'), ('file.txt', '/data/file.txt', 'DATA')],)))
            origins = module.freezer_origins(toc)
            self.assertEqual(origins['libffi.so.8'], Path('/usr/lib/x86_64-linux-gnu/libffi.so.8.1.0'))
            self.assertEqual(origins['pkg/ext.so'], Path('/venv/site/pkg/ext.so'))
            self.assertNotIn('file.txt', origins)

    def test_unknown_system_library_fails_closed(self):
        from unittest.mock import patch
        import subprocess
        module = api()
        with patch.object(module.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 1, "", "not owned")):
            with self.assertRaisesRegex(ValueError, "Unmapped"):
                module.debian_owner(Path("_internal/unowned.so.99"), {})


class SourceTests(unittest.TestCase):
    def source_fixture(self, root, version="1.2-3"):
        import hashlib
        archive = root / "example_1.2.orig.tar.xz"
        archive.write_bytes(b"synthetic source archive fixture")
        patch_archive = root / "example_1.2-3.debian.tar.xz"
        patch_archive.write_bytes(b"synthetic Debian patches/build-recipe fixture")
        entries = "".join(" " + hashlib.sha256(p.read_bytes()).hexdigest() + " " + str(p.stat().st_size) + " " + p.name + "\n" for p in [archive, patch_archive])
        dsc = root / "example_1.2-3.dsc"
        dsc.write_text("Format: 3.0 (quilt)\nSource: example\nVersion: " + version + "\nChecksums-Sha256:\n" + entries)
        return archive, dsc

    def test_source_fetch_pins_version_and_checks_actual_dsc_archives(self):
        import tempfile
        import subprocess
        from unittest.mock import patch
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                self.source_fixture(Path(kwargs["cwd"]))
                return subprocess.CompletedProcess(command, 0, "download fixture", "")
            with patch.object(module.subprocess, "run", run):
                record = module.fetch_source("example", "1.2-3", output)
            self.assertIn("example=1.2-3", calls[0])
            self.assertIn("--download-only", calls[0])
            self.assertEqual(len(record["files"]), 3)
            for file, digest in record["files"].items():
                self.assertEqual(module.sha256(output / file), digest)

    def test_wrong_source_version_is_not_corresponding_source(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            self.source_fixture(root, "1.2-4")
            with self.assertRaisesRegex(ValueError, "source identity"):
                api().verify_source_directory(root, "example", "1.2-3")

    def test_missing_or_modified_source_archive_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, _ = self.source_fixture(root)
            archive.write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "source checksum"):
                api().verify_source_directory(root, "example", "1.2-3")

    def test_missing_debian_patch_archive_fails_even_if_upstream_tarball_exists(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            self.source_fixture(root)
            (root / "example_1.2-3.debian.tar.xz").unlink()
            with self.assertRaisesRegex(ValueError, "Missing.*debian.tar"):
                api().verify_source_directory(root, "example", "1.2-3")

    def test_signed_dsc_and_epoch_version_are_preserved(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            _, dsc = self.source_fixture(root, "1:1.2-3")
            contents = dsc.read_text()
            dsc.write_text("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\n" + contents + "\n-----BEGIN PGP SIGNATURE-----\nfixture NOT a real signature\n-----END PGP SIGNATURE-----\n")
            self.assertEqual(len(api().verify_source_directory(root, "example", "1:1.2-3")), 3)

    def test_missing_exact_mirror_version_fails_with_actionable_error(self):
        import tempfile
        import subprocess
        from unittest.mock import patch
        module = api()
        with tempfile.TemporaryDirectory() as folder, patch.object(module.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 100, "", "Version not found")):
            with self.assertRaisesRegex(ValueError, "exact corresponding source.*example=1.2-3"):
                module.fetch_source("example", "1.2-3", Path(folder))

    def test_gpl_only_is_rejected_but_lgpl_and_narrow_gcc_exception_are_allowed(self):
        module = api()
        with self.assertRaisesRegex(ValueError, "GPL-only"):
            module.license_policy("License: GPL-3+", "unsafe", "libunsafe.so")
        self.assertEqual(module.license_policy("License: LGPL-2.1+\nLicense: GPL-2+", "glib2.0", "libglib-2.0.so.0"), "lgpl-source-required")
        self.assertEqual(module.license_policy("GPL-3 with GCC Runtime Library Exception", "gcc-12", "libstdc++.so.6"), "gcc-runtime-exception-source-required")
        with self.assertRaisesRegex(ValueError, "GPL-only"):
            module.license_policy("GPL-3 with GCC Runtime Library Exception", "unrelated", "libunsafe.so")
        for term in ["GPLv2+", "GNU General Public License version 3"]:
            with self.subTest(term=term), self.assertRaisesRegex(ValueError, "GPL-only"):
                module.license_policy(term, "unsafe", "libunsafe.so")
        for term in ["AGPL-3.0", "AGPLv3"]:
            with self.subTest(term=term), self.assertRaisesRegex(ValueError, "AGPL"):
                module.license_policy(term, "unsafe", "libunsafe.so")

    def test_actual_libffi_copyright_distinguishes_runtime_from_gpl_documentation(self):
        # Unmodified libffi8:amd64 3.4.2-4 copyright from packaging CI
        # 39135464089, artifacts/first-package-linux/build/worker/paperwork-worker/
        # third-party-licenses/linux/debian/libffi8_amd64-3.4.2-4/copyright.
        import hashlib
        fixture = Path(__file__).with_name("fixtures") / "libffi-copyright.txt"
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(),
                         "7258c8acc378030d8dbe1fcdf394e915769fa31dcbaf3d2991d9a79891f3bcdc")
        text = fixture.read_text(encoding="utf-8")
        for basename in ["libffi.so", "libffi.so.8", "libffi.so.8.1.0"]:
            with self.subTest(basename=basename):
                self.assertEqual(api().license_policy(text, "libffi", basename),
                                 "notice-and-exact-source-preserved")

    def test_libffi_exception_is_not_a_source_or_mit_keyword_allowlist(self):
        text = (Path(__file__).with_name("fixtures") / "libffi-copyright.txt").read_text(encoding="utf-8")
        module = api()
        for source, basename in [("unknown", "libffi.so.8"), ("libffi-extra", "libffi.so.8"),
                                 ("libffi", "libother.so.8"), ("libffi", "libffi.so.8-extra"),
                                 ("libffi", "other/libffi.so.8")]:
            with self.subTest(source=source, basename=basename), self.assertRaisesRegex(ValueError, "GPL-only"):
                module.license_policy(text, source, basename)
        before, after = text.split("    Documentation:", 1)
        damaged = [
            ("altered grant", text.replace("without restriction", "with restrictions")),
            ("missing condition", text.replace("in all copies or substantial portions of the Software.", "")),
            ("missing disclaimer", text.replace("THE SOFTWARE IS PROVIDED", "DISCLAIMER REMOVED")),
            ("missing attribution", text.replace("libffi - Copyright", "unattributed - Copyright")),
            ("documentation grant only", "License:\nGPL-3\nDocumentation:\n" + before + after),
            ("additional runtime terms", text.replace("    Documentation:", "GPL-3 runtime restriction\n    Documentation:")),
            ("missing boundary", text.replace("    Documentation:", "")),
            ("bare MIT keyword", "License: MIT"),
            ("empty notice", ""),
        ]
        for label, notice in damaged:
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "review|GPL-only"):
                module.license_policy(notice, "libffi", "libffi.so.8")
        for term in ["AGPL-3.0", "Affero General Public License"]:
            for notice in [term + "\n" + text, text + "\n" + term]:
                with self.subTest(term=term, notice=notice), self.assertRaisesRegex(ValueError, "AGPL"):
                    module.license_policy(notice, "libffi", "libffi.so.8")

    def test_actual_libuuid_copyright_distinguishes_bsd_runtime_from_gpl_utilities(self):
        # Unmodified libuuid1:amd64 2.37.2-4ubuntu3.6 copyright from CI
        # 39143386304, artifacts/linux-without-readline-evidence/build/worker/
        # paperwork-worker/third-party-licenses/linux/debian/
        # libuuid1_amd64-2.37.2-4ubuntu3.6/copyright. Also byte-identical to
        # debian/copyright in the matching Ubuntu source archive.
        import hashlib
        fixture = Path(__file__).with_name("fixtures") / "libuuid-copyright.txt"
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(),
                         "2c447817698777e3b2365a5afe2a58ececb85367dfdf0ea2c0df49add90e93eb")
        self.assertEqual(api().license_policy(fixture.read_text(encoding="utf-8"),
                                             "util-linux", "libuuid.so.1", source_version="2.37.2-4ubuntu3.6"),
                         "notice-and-exact-source-preserved")

    def test_libuuid_unchanged_notice_requires_reviewed_source_version(self):
        text = (Path(__file__).with_name("fixtures") / "libuuid-copyright.txt").read_text(encoding="utf-8")
        module = api()
        with self.assertRaisesRegex(ValueError, "libuuid.*source version.*explicit review"):
            module.license_policy(text, "util-linux", "libuuid.so.1")
        for version in [None, "", "2.37.2-4ubuntu3.5", "2.37.2-4ubuntu3.7", "2.38-1"]:
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "libuuid.*source version.*explicit review"):
                module.license_policy(text, "util-linux", "libuuid.so.1", source_version=version)
        self.assertEqual(module.license_policy(text, "util-linux", "libuuid.so.1", source_version="2.37.2-4ubuntu3.6"),
                         "notice-and-exact-source-preserved")

    def test_libuuid_exception_is_not_a_package_or_bsd_keyword_allowlist(self):
        text = (Path(__file__).with_name("fixtures") / "libuuid-copyright.txt").read_text(encoding="utf-8")
        module = api()
        for source, basename in [("unknown", "libuuid.so.1"), ("util-linux-extra", "libuuid.so.1"),
                                 ("util-linux", "libmount.so.1"), ("util-linux", "libblkid.so.1"),
                                 ("util-linux", "libuuid.so"), ("util-linux", "libuuid.so.1.3.0"),
                                 ("util-linux", "libuuid.so.1-extra"), ("util-linux", "other/libuuid.so.1")]:
            with self.subTest(source=source, basename=basename), self.assertRaisesRegex(ValueError, "GPL-only"):
                module.license_policy(text, source, basename, source_version="2.37.2-4ubuntu3.6")
        for label, notice in [
            ("GPL-only runtime", "License: GPL-2+"),
            ("bare BSD keyword", "License: BSD-3-clause"),
            ("empty notice", ""),
            ("changed runtime license", text.replace("1999 Andreas Dilger (adilger@enel.ucalgary.ca)\nLicense: BSD-3-clause",
                                                     "1999 Andreas Dilger (adilger@enel.ucalgary.ca)\nLicense: GPL-2+")),
            ("changed condition", text.replace("without specific prior written permission.", "with no permission.")),
            ("missing disclaimer", text.replace("THIS SOFTWARE IS PROVIDED", "DISCLAIMER REMOVED")),
            ("missing attribution", text.replace("1999 Andreas Dilger (adilger@enel.ucalgary.ca)", "")),
            ("additional override", text + "\nFiles: libuuid/src/gen_uuid.c\nLicense: GPL-3+\n"),
        ]:
            self.assertNotEqual(notice, text, label)
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "review|GPL-only"):
                module.license_policy(notice, "util-linux", "libuuid.so.1", source_version="2.37.2-4ubuntu3.6")

    def test_libuuid_checks_all_stanzas_for_agpl_before_runtime_classification(self):
        text = (Path(__file__).with_name("fixtures") / "libuuid-copyright.txt").read_text(encoding="utf-8")
        for term in ["AGPL-3.0", "AGPLv3", "Affero General Public License"]:
            for notice in [term + "\n" + text, text + "\nLicense: " + term,
                           text + "\nFiles: libuuid/src/gen_uuid.c\nLicense: " + term + "\n"]:
                with self.subTest(term=term, notice=notice), self.assertRaisesRegex(ValueError, "AGPL library is prohibited"):
                    api().license_policy(notice, "util-linux", "libuuid.so.1", source_version="2.37.2-4ubuntu3.6")

    def test_permissive_runtime_dep5_is_not_rejected_for_gpl_build_tools(self):
        text = ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                "Files: *\nCopyright: fixture only\nLicense: Apache-2.0\n\n"
                "Files: build-aux/config.guess\nCopyright: fixture only\nLicense: GPL-3+\n")
        self.assertEqual(api().license_policy(text, "example", "libexample.so"), "notice-and-exact-source-preserved")

    def test_copyright_and_referenced_common_license_are_copied_not_linked(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            copyright = root / "usr/share/doc/libexample/copyright"
            copyright.parent.mkdir(parents=True)
            copyright.write_text("License: LGPL-2.1+\nSee /usr/share/common-licenses/LGPL-2.1\n")
            common = root / "usr/share/common-licenses/LGPL-2.1"
            common.parent.mkdir(parents=True)
            common.write_text("Real common-license fixture text")
            records = api().debian_notices({"name": "libexample:amd64", "version": "1.0"}, root / "output", root)
            contents = [(root / "output" / f).read_text() for f in records]
            self.assertIn(copyright.read_text(), contents)
            self.assertIn(common.read_text(), contents)
            self.assertTrue(all(not (root / "output" / f).is_symlink() for f in records))


class GateTests(unittest.TestCase):
    def test_transitive_ldd_inventory_requires_no_unresolved_libraries(self):
        import tempfile
        import subprocess
        from unittest.mock import patch
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "app"
            binary.write_bytes(b"\x7fELFfixture")
            missing = subprocess.CompletedProcess(["ldd"], 0, "libmissing.so.1 => not found\n", "")
            with patch.object(module.subprocess, "run", lambda *args, **kwargs: missing):
                with self.assertRaisesRegex(ValueError, "Unresolved"):
                    module.linked_libraries([binary])

    def test_prebundle_inventory_records_staged_hash_and_wheel_notice(self):
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            worker = root / "worker"
            staged = worker / "_internal/pkg/native.so"
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"real staged fixture, not original")
            (worker / "paperwork-worker").write_bytes(b"bootloader fixture")
            native = root / "native"
            native.write_bytes(b"native executable fixture")
            output = worker / "third-party-licenses"
            notice = output / "python/example/LICENSE"
            notice.parent.mkdir(parents=True)
            notice.write_text("MIT license fixture")
            boot = output / "python/pyinstaller/COPYING.txt"
            boot.parent.mkdir(parents=True)
            boot.write_text("PyInstaller bootloader exception fixture")
            original = root / "site/pkg/native.so"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"original fixture")
            dist = SimpleNamespace(metadata={"Name": "example"}, files=[Path("pkg/native.so")], locate_file=lambda f: root / "site" / f)
            records = [{"name": "example", "version": "1.0", "license": "MIT", "notices": ["python/example/LICENSE"]}, {"name": "pyinstaller", "notices": ["python/pyinstaller/COPYING.txt"]}]
            with patch.object(module, "linker_paths", lambda: {}), patch.object(module, "linked_libraries", lambda paths: []):
                inventory = module.collect(worker, native, output, root / "sources", records, [dist])
            self.assertEqual(len(inventory["libraries"]), 1)
            record = inventory["libraries"][0]
            self.assertEqual(record["sha256"], module.sha256(staged))
            self.assertNotEqual(record["sha256"], record["original_sha256"])
            self.assertEqual(record["notices"], ["python/example/LICENSE"])

    def test_libffi_keeps_full_notice_and_still_requires_exact_source(self):
        import tempfile
        import shutil
        from unittest.mock import patch
        module = api()
        fixture = Path(__file__).with_name("fixtures") / "libffi-copyright.txt"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            worker = root / "worker"
            staged = worker / "_internal/libffi.so.8"
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"synthetic runtime library; not release evidence")
            (worker / "paperwork-worker").write_bytes(b"synthetic bootloader")
            native = root / "native"
            native.write_bytes(b"synthetic executable")
            output = worker / "third-party-licenses"
            boot = output / "python/pyinstaller/COPYING.txt"
            boot.parent.mkdir(parents=True)
            boot.write_text("PyInstaller bootloader exception fixture")
            copyright = root / "usr/share/doc/libffi8/copyright"
            copyright.parent.mkdir(parents=True)
            shutil.copyfile(fixture, copyright)
            common = root / "usr/share/common-licenses/GPL"
            common.parent.mkdir(parents=True)
            common.write_text("synthetic common-license fixture; not release evidence")
            owner = {"kind": "debian", "name": "libffi8:amd64", "version": "3.4.2-4",
                     "source_package": "libffi", "source_version": "3.4.2-4", "original": str(staged)}
            records = [{"name": "pyinstaller", "notices": ["python/pyinstaller/COPYING.txt"]}]
            copy_notices = module.debian_notices
            with patch.object(module, "linker_paths", return_value={}), \
                    patch.object(module, "linked_libraries", return_value=[]), \
                    patch.object(module, "python_runtime_owner", return_value=None), \
                    patch.object(module, "debian_owner", return_value=owner), \
                    patch.object(module, "debian_notices", side_effect=lambda owner, out: copy_notices(owner, out, root)), \
                    patch.object(module, "fetch_source", side_effect=ValueError("missing exact corresponding source")) as fetch:
                with self.assertRaisesRegex(ValueError, "exact corresponding source"):
                    module.collect(worker, native, output, root / "sources", records, [])
                fetch.assert_called_once_with("libffi", "3.4.2-4", root / "sources")
                copied = output / "linux/debian/libffi8_amd64-3.4.2-4/copyright"
                self.assertEqual(copied.read_bytes(), fixture.read_bytes())
                self.assertFalse(copied.is_symlink())
                self.assertEqual((output / "linux/common-licenses/GPL").read_bytes(), common.read_bytes())
                # A reviewed policy never substitutes for the actual notice.
                copyright.unlink()
                with self.assertRaisesRegex(ValueError, "Missing Debian package copyright"):
                    module.collect(worker, native, output, root / "sources-2", records, [])
                self.assertEqual(fetch.call_count, 1)

    def test_libuuid_keeps_full_notice_and_still_requires_exact_source(self):
        import tempfile
        import shutil
        from unittest.mock import patch
        module = api()
        fixture = Path(__file__).with_name("fixtures") / "libuuid-copyright.txt"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            worker = root / "worker"
            staged = worker / "_internal/libuuid.so.1"
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"synthetic runtime library; not release evidence")
            (worker / "paperwork-worker").write_bytes(b"synthetic bootloader")
            native = root / "native"
            native.write_bytes(b"synthetic executable")
            output = worker / "third-party-licenses"
            boot = output / "python/pyinstaller/COPYING.txt"
            boot.parent.mkdir(parents=True)
            boot.write_text("PyInstaller bootloader exception fixture")
            copyright = root / "usr/share/doc/libuuid1/copyright"
            copyright.parent.mkdir(parents=True)
            shutil.copyfile(fixture, copyright)
            common = root / "usr/share/common-licenses"
            common.mkdir(parents=True)
            # The real mixed notice references these licenses, including GPL.
            for name in ["GPL-2", "GPL-3", "LGPL", "LGPL-2", "LGPL-2.1", "LGPL-3"]:
                (common / name).write_text("synthetic common-license fixture: " + name)
            owner = {"kind": "debian", "name": "libuuid1:amd64", "version": "2.37.2-4ubuntu3.6",
                     "source_package": "util-linux", "source_version": "2.37.2-4ubuntu3.6", "original": str(staged)}
            records = [{"name": "pyinstaller", "notices": ["python/pyinstaller/COPYING.txt"]}]
            copy_notices = module.debian_notices
            with patch.object(module, "linker_paths", return_value={}), \
                    patch.object(module, "linked_libraries", return_value=[]), \
                    patch.object(module, "python_runtime_owner", return_value=None), \
                    patch.object(module, "debian_owner", return_value=owner), \
                    patch.object(module, "debian_notices", side_effect=lambda owner, out: copy_notices(owner, out, root)), \
                    patch.object(module, "fetch_source", side_effect=ValueError("missing exact corresponding source")) as fetch:
                # The binary version and complete notice stay unchanged: only
                # the source identity may authorize the reviewed exception.
                for version in [None, "", "2.37.2-4ubuntu3.7"]:
                    if version is None:
                        owner.pop("source_version", None)
                    else:
                        owner["source_version"] = version
                    with self.subTest(source_version=version), self.assertRaisesRegex(ValueError, "libuuid.*source version.*explicit review"):
                        module.collect(worker, native, output, root / "sources", records, [])
                    fetch.assert_not_called()
                owner["source_version"] = "2.37.2-4ubuntu3.6"
                with self.assertRaisesRegex(ValueError, "exact corresponding source"):
                    module.collect(worker, native, output, root / "sources", records, [])
                fetch.assert_called_once_with("util-linux", "2.37.2-4ubuntu3.6", root / "sources")
                copied = output / "linux/debian/libuuid1_amd64-2.37.2-4ubuntu3.6/copyright"
                self.assertEqual(copied.read_bytes(), fixture.read_bytes())
                self.assertFalse(copied.is_symlink())
                for license_file in common.iterdir():
                    self.assertEqual((output / "linux/common-licenses" / license_file.name).read_bytes(), license_file.read_bytes())
                # Existing positive path: collection succeeds with a complete,
                # checksum-verified synthetic source record for this version.
                def synthetic_source(package, version, destination):
                    directory = destination / (package + "-" + version)
                    directory.mkdir()
                    _, dsc = SourceTests().source_fixture(directory, version)
                    dsc.write_text(dsc.read_text().replace("Source: example\n", "Source: " + package + "\n"))
                    files = module.verify_source_directory(directory, package, version)
                    return {"source_package": package, "source_version": version,
                            "files": {directory.name + "/" + name: digest for name, digest in files.items()}}
                with patch.object(module, "fetch_source", side_effect=synthetic_source):
                    collected = module.collect(worker, native, output, root / "complete-sources", records, [])
                self.assertEqual(collected["libraries"][0]["source_version"], "2.37.2-4ubuntu3.6")
                self.assertEqual(collected["libraries"][0]["policy"], "notice-and-exact-source-preserved")
                self.assertTrue(module.audit_payload(staged.parent, collected, output, root / "complete-sources")["success"])
                copyright.unlink()
                with self.assertRaisesRegex(ValueError, "Missing Debian package copyright"):
                    module.collect(worker, native, output, root / "sources-2", records, [])
                self.assertEqual(fetch.call_count, 1)
            # Postbundle inspection also requires the source; the runtime policy
            # is not an exemption from the Debian corresponding-source gate.
            inventory = {"libraries": [{**owner, "basename": staged.name,
                         "notices": [copied.relative_to(output).as_posix()],
                         "sha256": module.sha256(staged), "policy": "notice-and-exact-source-preserved"}], "sources": []}
            with self.assertRaisesRegex(ValueError, "Missing exact corresponding source"):
                module.audit_payload(staged.parent, inventory, output, root / "sources")

    def test_libuuid_postbundle_rechecks_reviewed_source_version(self):
        import tempfile
        import shutil
        module = api()
        fixture = Path(__file__).with_name("fixtures") / "libuuid-copyright.txt"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            payload = root / "payload"
            payload.mkdir()
            staged = payload / "libuuid.so.1"
            staged.write_bytes(b"synthetic postbundle runtime; not release evidence")
            notices = root / "notices"
            notice = notices / "libuuid/copyright"
            notice.parent.mkdir(parents=True)
            shutil.copyfile(fixture, notice)
            sources = root / "sources"
            sources.mkdir()
            # A matching .dsc and complete synthetic archives are insufficient
            # when that source version's runtime has not been reviewed.
            for version in ["2.37.2-4ubuntu3.7", "2.37.2-4ubuntu3.6", None, ""]:
                source_version = version or "2.37.2-4ubuntu3.6"
                directory = sources / source_version
                directory.mkdir(exist_ok=True)
                _, dsc = SourceTests().source_fixture(directory, source_version)
                dsc.write_text(dsc.read_text().replace("Source: example\n", "Source: util-linux\n"))
                files = module.verify_source_directory(directory, "util-linux", source_version)
                record = {"kind": "debian", "name": "libuuid1:amd64", "version": "2.37.2-4ubuntu3.6",
                          "source_package": "util-linux", "source_version": version, "basename": staged.name,
                          "notices": ["libuuid/copyright"], "sha256": module.sha256(staged),
                          "policy": "notice-and-exact-source-preserved"}
                if version is None:
                    record.pop("source_version")
                inventory = {"libraries": [record], "sources": [{"source_package": "util-linux",
                             "source_version": source_version,
                             "files": {source_version + "/" + name: digest for name, digest in files.items()}}]}
                if version == "2.37.2-4ubuntu3.6":
                    report = module.audit_payload(payload, inventory, notices, sources)
                    self.assertTrue(report["success"])
                    self.assertEqual(report["shared_library_count"], 1)
                    self.assertEqual(report["source_package_count"], 1)
                else:
                    with self.assertRaisesRegex(ValueError, "libuuid.*source version.*explicit review"):
                        module.audit_payload(payload, inventory, notices, sources)

    def test_postbundle_unknown_library_is_not_allowed_by_other_notices(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "newlib.so.1").write_bytes(b"unknown fixture")
            with self.assertRaisesRegex(ValueError, "Unmapped"):
                api().audit_payload(root, {"libraries": [], "sources": []}, root, root)

    def test_postbundle_rewritten_rpath_records_actual_hash_not_original_hash(self):
        import tempfile
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            staged = root / "libexample.so.1"
            staged.write_bytes(b"rewritten RPATH fixture")
            notice = root / "copyright"
            notice.write_text("actual notice fixture")
            inventory = {"libraries": [{"basename": staged.name, "kind": "wheel", "name": "example", "version": "1", "notices": ["copyright"], "sha256": "0" * 64}], "sources": []}
            report = module.audit_payload(root, inventory, root, root)
            self.assertEqual(report["libraries"][0]["sha256"], module.sha256(staged))
            self.assertEqual(report["libraries"][0]["inventory_sha256"], "0" * 64)

    def test_postbundle_requires_source_artifact_for_debian_library(self):
        import tempfile
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "libexample.so.1").write_bytes(b"fixture")
            (root / "copyright").write_text("LGPL fixture")
            inventory = {"libraries": [{"basename": "libexample.so.1", "kind": "debian", "name": "libexample", "version": "1", "source_package": "example", "source_version": "1", "notices": ["copyright"], "sha256": "0" * 64}], "sources": []}
            with self.assertRaisesRegex(ValueError, "corresponding source"):
                module.audit_payload(root, inventory, root, root)


class WiringTests(unittest.TestCase):
    def test_license_report_linux_mode_collects_before_notice_manifest(self):
        import runpy
        import sys
        import tempfile
        from unittest.mock import patch
        report_script = SCRIPT.with_name("license-report.py")
        module = runpy.run_path(str(report_script))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            output = root / "build/worker/paperwork-worker/third-party-licenses"
            main = module["main"]
            def collect_linux(*args, **kwargs):
                self.assertTrue((output / "python-runtime/LICENSE.txt").is_file())
                return {"schema": 1, "libraries": [], "sources": []}
            main.__globals__["ROOT"] = root
            main.__globals__["collect_python"] = lambda out: []
            main.__globals__["collect_npm"] = lambda root, out: []
            with patch.dict(sys.modules, {"audit_linux_libraries": type("Audit", (), {"collect": staticmethod(collect_linux)})}), patch.object(sys, "platform", "linux"), patch.object(sys, "argv", [str(report_script), "--linux-native", str(root / "native")]):
                main()
            import json
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertIn("linux-libraries.json", manifest)


class ArchiveTests(unittest.TestCase):
    def test_source_zip_contains_exact_checked_archives_and_audit(self):
        import tempfile
        import json
        import zipfile
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source_dir = root / "sources/example-1.2-3"
            source_dir.mkdir(parents=True)
            SourceTests().source_fixture(source_dir)
            files = module.verify_source_directory(source_dir, "example", "1.2-3")
            inventory = {"sources": [{"source_package": "example", "source_version": "1.2-3", "files": {"example-1.2-3/" + name: digest for name, digest in files.items()}}]}
            (root / "sources/appimage-library-audit.json").write_text(json.dumps({"appimage_sha256": "fixture-only"}))
            target = root / "artifacts/sources.zip"
            module.source_archive(root / "sources", inventory, target)
            with zipfile.ZipFile(target) as archive:
                self.assertIn("appimage-library-audit.json", archive.namelist())
                for name, digest in inventory["sources"][0]["files"].items():
                    import hashlib
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)

    def test_library_directory_symlink_cannot_hide_external_payload(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "payload").mkdir()
            (root / "outside").mkdir()
            (root / "outside/native.so").write_bytes(b"external fixture")
            try:
                (root / "payload/hidden-libraries").symlink_to(root / "outside", target_is_directory=True)
            except OSError:
                self.skipTest("Host does not permit symlink fixture")
            with self.assertRaisesRegex(ValueError, "escapes"):
                api().shared_libraries(root / "payload")

    def test_escaping_library_symlink_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "payload").mkdir()
            (root / "outside").write_bytes(b"outside")
            try:
                (root / "payload/escape.so").symlink_to(root / "outside")
            except OSError:
                self.skipTest("Host does not permit symlink fixture")
            with self.assertRaisesRegex(ValueError, "escapes"):
                api().shared_libraries(root / "payload")


class ExtractedPayloadTests(unittest.TestCase):
    def test_extracted_appimage_has_checked_debian_sources_not_just_an_inventory(self):
        import tempfile
        import shutil
        import json
        import subprocess
        from unittest.mock import patch
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            payload = root / "fixture-appdir"
            worker = payload / "usr/lib/paperwork-desktop/worker"
            library = worker / "_internal/libexample.so.1"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"RPATH-rewritten fixture library")
            (worker / "paperwork-worker").write_bytes(b"fixture worker executable")
            notices = worker / "third-party-licenses"
            notices.mkdir()
            (notices / "copyright").write_text("LGPL license fixture")
            sources = root / "sources"
            source_dir = sources / "example-1.2-3"
            source_dir.mkdir(parents=True)
            SourceTests().source_fixture(source_dir)
            files = module.verify_source_directory(source_dir, "example", "1.2-3")
            inventory = {"libraries": [{"basename": "libexample.so.1", "kind": "debian", "name": "libexample", "version": "1.2-3", "source_package": "example", "source_version": "1.2-3", "notices": ["copyright"], "role": "shipped-worker", "path": "_internal/libexample.so.1", "sha256": "0" * 64}], "sources": [{"source_package": "example", "source_version": "1.2-3", "files": {"example-1.2-3/" + name: digest for name, digest in files.items()}}]}
            (notices / "linux-libraries.json").write_text(json.dumps(inventory))
            manifest = {p.name: module.sha256(p) for p in notices.iterdir()}
            (notices / "manifest.json").write_text(json.dumps(manifest))
            reference = root / "prebundle.json"
            shutil.copyfile(notices / "linux-libraries.json", reference)
            appimage = root / "fixture.AppImage"
            appimage.write_bytes(b"extraction is mocked, NOT a real AppImage")
            logs = root / "logs"
            logs.mkdir()
            def extract(command, **kwargs):
                self.assertEqual(command, [str(appimage), "--appimage-extract"])
                shutil.copytree(payload, Path(kwargs["cwd"]) / "squashfs-root")
                return subprocess.CompletedProcess(command, 0, "synthetic extraction fixture", "")
            with patch.object(module, "command", extract):
                report = module.audit_appimage(str(appimage), reference, sources, logs)
                self.assertTrue(report["success"])
                self.assertEqual(report["shared_library_count"], 1)
                self.assertEqual(report["source_package_count"], 1)
                self.assertEqual(report["libraries"][0]["sha256"], module.sha256(library))
                (notices / "copyright").write_text("corrupted notice fixture")
                with self.assertRaisesRegex(ValueError, "notice checksum"):
                    module.audit_appimage(str(appimage), reference, sources, logs)

    def test_cli_source_zip_failure_never_leaves_success_true(self):
        import tempfile
        import json
        from unittest.mock import patch
        module = api()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            inventory = root / "inventory.json"
            inventory.write_text('{"sources": []}')
            sources = root / "sources"
            sources.mkdir()
            import sys
            argv = [str(SCRIPT), "--appimage", "fixture", "--inventory", str(inventory), "--sources", str(sources), "--source-archive", str(root / "source.zip"), "--logs", str(root / "logs")]
            with patch.object(sys, "argv", argv), patch.object(module, "audit_appimage", lambda *args: {"success": True}), patch.object(module, "source_archive", side_effect=ValueError("deliberate ZIP failure")):
                self.assertEqual(module.main(), 1)
            report = json.loads((root / "logs/report.json").read_text())
            self.assertFalse(report["success"])
            self.assertIn("ZIP failure", report["error"])


if __name__ == "__main__":
    unittest.main()
