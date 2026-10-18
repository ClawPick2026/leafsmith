"""Linux redistribution contracts; synthetic data is never release evidence."""
import importlib.util
from pathlib import Path
import re
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

    def test_reviewed_util_linux_lgpl_libraries_require_exact_source_and_notice(self):
        # Same exact source package as libuuid. libblkid/COPYING and
        # libmount/COPYING explicitly grant LGPL-2.1-or-later, not GPL-only.
        text = (Path(__file__).with_name('fixtures') / 'libuuid-copyright.txt').read_text(encoding='utf-8')
        module = api()
        for basename in ('libblkid.so.1', 'libmount.so.1'):
            with self.subTest(basename=basename):
                self.assertEqual(module.license_policy(text, 'util-linux', basename,
                                 source_version='2.37.2-4ubuntu3.6'),
                                 'notice-and-exact-source-preserved')
                for version in (None, '', '2.37.2-4ubuntu3.7'):
                    with self.assertRaisesRegex(ValueError, 'explicit review'):
                        module.license_policy(text, 'util-linux', basename, source_version=version)
                with self.assertRaisesRegex(ValueError, 'explicit review'):
                    module.license_policy(text + '\nChanged grant', 'util-linux', basename,
                                          source_version='2.37.2-4ubuntu3.6')
                with self.assertRaisesRegex(ValueError, 'AGPL'):
                    module.license_policy(text + '\nLicense: AGPL-3.0', 'util-linux', basename,
                                          source_version='2.37.2-4ubuntu3.6')

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
                                 ("util-linux", "libfdisk.so.1"), ("util-linux", "libsmartcols.so.1"),
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

    def test_dep5_checks_complete_notice_for_agpl_before_default_runtime_grant(self):
        module = api()
        for default in ["MIT", "LGPL-2.1+"]:
            for term in ["AGPL-3.0", "AGPLv3", "Affero General Public License"]:
                for override in ["Files: src/runtime.c\nLicense: " + term,
                                 "Files: build-aux/config.guess\nLicense: " + term,
                                 "License: " + term,
                                 "Comment: additional runtime terms: " + term]:
                    text = ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                            "Files: *\nCopyright: fixture only\nLicense: " + default + "\n\n" + override + "\n")
                    with self.subTest(default=default, term=term, override=override), \
                            self.assertRaisesRegex(ValueError, "AGPL library is prohibited"):
                        module.license_policy(text, "example", "libexample.so")

    def test_dep5_gpl_only_runtime_overrides_require_explicit_review(self):
        module = api()
        for default in ["MIT", "LGPL-2.1+"]:
            for files in ["src/runtime.c", "lib/*.c", "*.[ch]", "src/config.c",
                          "build-aux/runtime.c", "build-aux/config.guess\n src/runtime.c",
                          "config.guess config.sub src/runtime.c"]:
                for term in ["GPL-3+", "GPLv2+", "GNU General Public License version 3"]:
                    text = ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                            "Files: *\nCopyright: fixture only\nLicense: " + default + "\n\n"
                            "Files: " + files + "\nCopyright: fixture only\nLicense: " + term + "\n")
                    with self.subTest(default=default, files=files, term=term), \
                            self.assertRaisesRegex(ValueError, "GPL-only.*explicit review"):
                        module.license_policy(text, "example", "libexample.so")

    def test_dep5_later_gpl_default_override_requires_explicit_review(self):
        text = ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                "Files: *\nLicense: MIT\n\n"
                "Files: *\nLicense: GPL-3+\n")
        with self.assertRaisesRegex(ValueError, "GPL-only.*explicit review"):
            api().license_policy(text, "example", "libexample.so")

    def test_dep5_lgpl_and_permissive_grants_do_not_inherit_gpl_prose(self):
        # Existing behavior: common-license definitions, documentation comments,
        # and LGPL's incorporation of GPL text are not GPL-only file grants.
        module = api()
        for default, expected in [("MIT", "notice-and-exact-source-preserved"),
                                  ("LGPL-2.1+", "lgpl-source-required")]:
            text = ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                    "Files: *\nLicense: " + default + "\n"
                    " The GNU GENERAL PUBLIC LICENSE is incorporated by the LGPL.\n\n"
                    "Files: src/helper.c\nLicense: LGPL-2.1+\n"
                    " See /usr/share/common-licenses/GPL-2.\n\n"
                    "Files: doc/*\nLicense: MIT\nComment: This documentation discusses GPL-3.\n\n"
                    "License: GPL-2\n GNU GENERAL PUBLIC LICENSE\n")
            with self.subTest(default=default):
                self.assertEqual(module.license_policy(text, "example", "libexample.so"), expected)

    def test_dep5_named_gpl_configure_helpers_remain_build_only(self):
        # Existing build-tool distinction, not a broad directory/package waiver.
        for files in ["config.guess", "config.sub", "build-aux/config.sub",
                      "build-aux/config.guess\n build-aux/config.sub"]:
            text = ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                    "Files: *\nLicense: LGPL-2.1+\n\n"
                    "Files: " + files + "\nLicense: GPL-3+\n")
            with self.subTest(files=files):
                self.assertEqual(api().license_policy(text, "example", "libexample.so"), "lgpl-source-required")

    def test_permissive_runtime_dep5_is_not_rejected_for_gpl_build_tools(self):
        text = ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                "Files: *\nCopyright: fixture only\nLicense: Apache-2.0\n\n"
                "Files: build-aux/config.guess\nCopyright: fixture only\nLicense: GPL-3+\n")
        self.assertEqual(api().license_policy(text, "example", "libexample.so"), "notice-and-exact-source-preserved")

    def dep5(self, default, override_files, override_grant):
        return ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                "Files: *\nCopyright: fixture only\nLicense: " + default + "\n\n"
                "Files: " + override_files + "\nCopyright: fixture only\nLicense: " + override_grant + "\n")

    def test_dep5_gpl_alternatives_and_standard_exceptions_are_not_gpl_only(self):
        # Grants seen in Ubuntu jammy WebKitGTK dependencies (CI 39154597775).
        module = api()
        for grant in ["BSD-3-clause or GPL-2", "AFL-2.1 or GPL-2+", "Artistic or GPL-1+",
                      "GPL-2 or MIT", "GPL-2+ or AFL-2.1, and Tcl-BSDish",
                      "GPL-2+ with Bison exception", "GPL-3+ with Autoconf exception",
                      "GPL-3+ with autoconf exception", "GPL-2 with Linux-syscall-note exception",
                      "GPL-2+ with distribution exception"]:
            with self.subTest(grant=grant):
                self.assertEqual(module.license_policy(self.dep5("LGPL-2.1+", "src/core.c", grant), "example", "libexample.so"),
                                 "lgpl-source-required")

    def test_dep5_gpl_only_overrides_outside_library_sources_are_build_or_tool_files(self):
        module = api()
        for files in ["debian/*", "m4/ax_pthread.m4", "builds/unix/pkg.m4", "build-aux/*", "ltmain.sh", "texinfo.tex",
                      "Doxyfile.in", "lib/Makefile.gnulib lib/Makefile.in", "doc/yat2m.c", "src/util/uthash/doc/userguide.html",
                      "tests/* gdk-pixbuf/test-gdk-pixbuf.c", "./examples/printVersion.c", "programs/lz4io.c",
                      "tools/dbus-monitor.c tools/dbus-print-message.?", "src/scripts/*", "contrib/perl/*",
                      "external/perl/Text-Template-1.56/*", "common/coverage/coverage-report.pl", "libsecret/mock/hkdf.py",
                      "Source/ThirdParty/ANGLE/tools/flex-bison/third_party/skeletons/*",
                      "include/linux/input.h include/drm-uapi/etnaviv_drm.h"]:
            with self.subTest(files=files):
                self.assertEqual(module.license_policy(self.dep5("LGPL-2.1+", files, "GPL-2+"), "example", "libexample.so"),
                                 "lgpl-source-required")

    def test_dep5_gpl_only_runtime_looking_overrides_still_require_review(self):
        # Still a tripwire: the error names every unexcused file.
        module = api()
        for files, grant in [("src/core.c", "GPL-2+"), ("lib/*", "GPL-3+"), ("src/basic/ioprio.h", "GPL-2"),
                             ("libexample/linux.c", "GPL-2"), ("src/core.c", "BSD-3-clause and GPL-2"),
                             ("debian/* src/core.c", "GPL-2+"), ("thumbnailer/*", "GPL-2+"),
                             ("build-aux/snippet/arg-nonnull.h", "GPL-3.0+"), ("m4/inline.h", "GPL-2+")]:
            with self.subTest(files=files, grant=grant):
                with self.assertRaisesRegex(ValueError, "GPL-only file override requires explicit review.*" + re.escape(files.split()[-1])):
                    module.license_policy(self.dep5("LGPL-2.1+", files, grant), "example", "libexample.so")

    def test_reviewed_non_runtime_overrides_apply_only_to_their_source_package(self):
        module = api()
        for source, files in [("xz-utils", "src/scripts/* lib/* extra/scanlzma/scanlzma.c"), ("nettle", "getopt*"),
                              ("systemd", "src/basic/ioprio.h src/udev/ata_id/ata_id.c src/udev/udevadm.c"),
                              ("lcms2", "plugins/fast_float/*"), ("gstreamer1.0", "gst/parse/grammar.tab.h"),
                              ("enchant-2", "./providers/applespell_checker.mm build-aux/snippet/arg-nonnull.h"),
                              ("libunistring", "woe32dll/*"),
                              ("gdk-pixbuf", "thumbnailer/*")]:
            text = self.dep5("LGPL-2.1+", files, "GPL-2+")
            with self.subTest(source=source):
                self.assertEqual(module.license_policy(text, source, "libexample.so"), "lgpl-source-required")
                with self.assertRaisesRegex(ValueError, "GPL-only file override requires explicit review"):
                    module.license_policy(text, "example", "libexample.so")
        with self.assertRaisesRegex(ValueError, "src/core.c"):
            module.license_policy(self.dep5("LGPL-2.1+", "lib/* src/core.c", "GPL-2+"), "xz-utils", "liblzma.so.5")

    def test_dep5_default_grant_with_permissive_alternative_is_not_gpl_only(self):
        # dbus: "Files: * / License: GPL-2+ or AFL-2.1".
        module = api()
        text = ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n"
                "Files: *\nCopyright: fixture only\nLicense: GPL-2+ or AFL-2.1\n")
        self.assertEqual(module.license_policy(text, "dbus", "libdbus-1.so.3"), "notice-and-exact-source-preserved")
        with self.assertRaisesRegex(ValueError, "GPL-only library"):
            module.license_policy(text.replace(" or AFL-2.1", ""), "dbus", "libdbus-1.so.3")

    def test_actual_reviewed_library_notices_are_bound_to_exact_text_and_libraries(self):
        # Unmodified notices from CI 39154597775 (Ubuntu jammy): krb5
        # 1.19.2-2ubuntu0.10 (MIT notice; GPL is only an offered alternative),
        # keyutils 1.6.1-2ubuntu3 (library sources keyutils.* are LGPL-2+) and
        # libidn2 2.3.2-2build1 (library sources are LGPL-3+ or GPL-2+) and
        # libzstd 1.4.8+dfsg-3build1 (BSD-3-clause or GPL-2 at the recipient's option).
        import hashlib
        module = api()
        cases = [("krb5-copyright.txt", "krb5", "4a2d321ab57260e8de4b67bde8cff76c07d28be69c2d8b22dfc2bfa42f5c41b9",
                  ["libgssapi_krb5.so.2", "libk5crypto.so.3", "libkrb5.so.3", "libkrb5support.so.0"],
                  "notice-and-exact-source-preserved"),
                 ("keyutils-copyright.txt", "keyutils", "6ab5c541723d8211cab7ebc1643d53aa51c4863c1c838e4625d797ece9472ee8",
                  ["libkeyutils.so.1"], "lgpl-source-required"),
                 ("libidn2-copyright.txt", "libidn2", "41702469f28e8ff406345e3d1dd0c741f11bdfca319264f67036efd6aaa79e4b",
                  ["libidn2.so.0"], "lgpl-source-required"),
                 ("libzstd-copyright.txt", "libzstd", "8cf66791fbe72801cb1d701c832b7e395dad0000bb9699dc42df94b49d699e91",
                  ["libzstd.so.1"], "notice-and-exact-source-preserved")]
        for fixture, source, digest, basenames, policy in cases:
            path = Path(__file__).with_name("fixtures") / fixture
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            text = path.read_text(encoding="utf-8")
            for basename in basenames:
                with self.subTest(source=source, basename=basename):
                    self.assertEqual(module.license_policy(text, source, basename), policy)
            with self.subTest(source=source, change="notice"), self.assertRaisesRegex(ValueError, "explicit review"):
                module.license_policy(text + "\n", source, basenames[0])
            with self.subTest(source=source, change="library"), self.assertRaisesRegex(ValueError, "explicit review"):
                module.license_policy(text, source, "libother.so.1")
            with self.subTest(source=source, change="package"), self.assertRaisesRegex(ValueError, "GPL"):
                module.license_policy(text, "example", basenames[0])
            for term in ["AGPL-3.0", "Affero General Public License"]:
                with self.subTest(source=source, term=term), self.assertRaisesRegex(ValueError, "AGPL"):
                    module.license_policy(text + "\n" + term, source, basenames[0])

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

    def test_spdx_style_common_license_reference_resolves_to_debian_file(self):
        # Ubuntu jammy libpango-1.0-0 1.50.6+ds-2ubuntu1 refers to GPL-2.0/GPL-3.0,
        # but Debian ships those texts as GPL-2/GPL-3.
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            copyright = root / "usr/share/doc/libpango-1.0-0/copyright"
            copyright.parent.mkdir(parents=True)
            copyright.write_text(
                'version 2 can be found in "/usr/share/common-licenses/GPL-2.0".\n'
                'version 3 can be found in "/usr/share/common-licenses/GPL-3.0".\n'
                'See /usr/share/common-licenses/LGPL-3.0+ and /usr/share/common-licenses/LGPL-2.1.\n')
            common = root / "usr/share/common-licenses"
            common.mkdir(parents=True)
            for name in ("GPL-2", "GPL-3", "LGPL-2.1", "LGPL-3"):
                (common / name).write_text(name + " fixture text")
            records = api().debian_notices({"name": "libpango-1.0-0:amd64", "version": "1.50.6+ds-2ubuntu1"},
                                           root / "output", root)
            for name in ("GPL-2", "GPL-3", "LGPL-2.1", "LGPL-3"):
                self.assertIn("linux/common-licenses/" + name, records)

    def test_unresolvable_common_license_reference_still_fails(self):
        import tempfile
        for reference in ("GPL-9.0", "LGPL-2.0", "Apache-2"):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                copyright = root / "usr/share/doc/libexample/copyright"
                copyright.parent.mkdir(parents=True)
                copyright.write_text("See /usr/share/common-licenses/" + reference + "\n")
                common = root / "usr/share/common-licenses"
                common.mkdir(parents=True)
                (common / "GPL-2").write_text("GPL-2 fixture text")
                (common / "LGPL-2.1").write_text("LGPL-2.1 fixture text")
                with self.assertRaisesRegex(ValueError, "Missing referenced common license: " + reference):
                    api().debian_notices({"name": "libexample:amd64", "version": "1.0"}, root / "output", root)


class GateTests(unittest.TestCase):
    def test_collect_reports_entire_dependency_license_failure_set_before_sources(self):
        # Synthetic distribution, not release evidence: both failures must be
        # reported in one audit, with no approved inventory or source fetching.
        import json
        from unittest.mock import patch
        import tempfile
        module = api()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worker = root / 'worker'
            internal = worker / '_internal'
            internal.mkdir(parents=True)
            for name in ('libbadgpl.so.1', 'libbadagpl.so.1'):
                (internal / name).write_bytes(b'synthetic native dependency')
            (worker / 'paperwork-worker').write_bytes(b'synthetic bootloader')
            native = root / 'native'
            native.write_bytes(b'synthetic host')
            output = worker / 'third-party-licenses'
            boot = output / 'python/pyinstaller/COPYING.txt'
            boot.parent.mkdir(parents=True)
            boot.write_text('PyInstaller bootloader exception fixture')
            def owner(path, linker):
                return {'kind': 'debian', 'name': path.name, 'version': '1',
                        'source_package': path.name, 'source_version': '1',
                        'original': str(internal / path.name)}
            def notices(record, destination):
                path = destination / record['name'] / 'copyright'
                path.parent.mkdir(parents=True, exist_ok=True)
                grant = 'AGPL-3.0' if 'agpl' in record['name'] else 'GPL-3.0'
                path.write_text('License: ' + grant, encoding='utf-8')
                return [path.relative_to(destination).as_posix()]
            with patch.object(module, 'linker_paths', return_value={}), \
                    patch.object(module, 'linked_libraries', return_value=[]), \
                    patch.object(module, 'python_runtime_owner', return_value=None), \
                    patch.object(module, 'debian_owner', side_effect=owner), \
                    patch.object(module, 'debian_notices', side_effect=notices), \
                    patch.object(module, 'fetch_source') as fetch:
                with self.assertRaises(ValueError):
                    module.collect(worker, native, output, root/'sources',
                                   [{'name': 'pyinstaller', 'notices': ['python/pyinstaller/COPYING.txt']}], [])
                fetch.assert_not_called()
            report = json.loads((output/'linux/prebundle-license-review.json').read_text(encoding='utf-8'))
            self.assertFalse(report['approved'])
            self.assertEqual({item['basename'] for item in report['issues']},
                             {'libbadgpl.so.1', 'libbadagpl.so.1'})
            self.assertEqual(len(report['libraries']), 2)
            self.assertFalse((root/'sources/source-inventory.json').exists())

    def test_collect_reports_notice_failures_with_policy_failures(self):
        # An unresolvable notice must not hide later dependency issues behind a
        # traceback: every failure is reported once, and nothing is approved.
        import json
        from unittest.mock import patch
        import tempfile
        module = api()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worker = root / 'worker'
            internal = worker / '_internal'
            internal.mkdir(parents=True)
            for name in ('libnonotice.so.1', 'libbadgpl.so.1'):
                (internal / name).write_bytes(b'synthetic native dependency')
            (worker / 'paperwork-worker').write_bytes(b'synthetic bootloader')
            native = root / 'native'
            native.write_bytes(b'synthetic host')
            output = worker / 'third-party-licenses'
            boot = output / 'python/pyinstaller/COPYING.txt'
            boot.parent.mkdir(parents=True)
            boot.write_text('PyInstaller bootloader exception fixture')
            def owner(path, linker):
                return {'kind': 'debian', 'name': path.name, 'version': '1',
                        'source_package': path.name, 'source_version': '1',
                        'original': str(internal / path.name)}
            def notices(record, destination):
                if 'nonotice' in record['name']:
                    raise ValueError('Missing referenced common license: GPL-9.0')
                path = destination / record['name'] / 'copyright'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('License: GPL-3.0', encoding='utf-8')
                return [path.relative_to(destination).as_posix()]
            with patch.object(module, 'linker_paths', return_value={}), \
                    patch.object(module, 'linked_libraries', return_value=[]), \
                    patch.object(module, 'python_runtime_owner', return_value=None), \
                    patch.object(module, 'debian_owner', side_effect=owner), \
                    patch.object(module, 'debian_notices', side_effect=notices), \
                    patch.object(module, 'fetch_source') as fetch:
                with self.assertRaisesRegex(ValueError, 'GPL-9.0.*GPL-only|GPL-only.*GPL-9.0'):
                    module.collect(worker, native, output, root/'sources',
                                   [{'name': 'pyinstaller', 'notices': ['python/pyinstaller/COPYING.txt']}], [])
                fetch.assert_not_called()
            report = json.loads((output/'linux/prebundle-license-review.json').read_text(encoding='utf-8'))
            self.assertFalse(report['approved'])
            self.assertEqual({item['basename'] for item in report['issues']},
                             {'libnonotice.so.1', 'libbadgpl.so.1'})
            self.assertEqual({item['policy'] for item in report['libraries']}, {'unapproved'})

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

    def test_libuuid_utf8_notices_survive_cp1252_default_through_collection_and_postbundle(self):
        # Portable locale simulation, NOT native Windows packaging evidence.
        # Only omitted encodings use cp1252; all reads still consume real bytes.
        import hashlib
        import shutil
        import tempfile
        from unittest.mock import patch
        module = api()
        fixture = Path(__file__).with_name("fixtures") / "libuuid-copyright.txt"
        expected_text = fixture.read_text(encoding="utf-8")
        expected_hash = "2c447817698777e3b2365a5afe2a58ececb85367dfdf0ea2c0df49add90e93eb"
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), expected_hash)
        real_read_text = Path.read_text

        def cp1252_read_text(path, encoding=None, errors=None, **kwargs):
            return real_read_text(path, encoding=encoding or "cp1252", errors=errors, **kwargs)

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
            boot.write_text("PyInstaller bootloader exception fixture", encoding="utf-8")
            copyright = root / "usr/share/doc/libuuid1/copyright"
            copyright.parent.mkdir(parents=True)
            shutil.copyfile(fixture, copyright)
            common = root / "usr/share/common-licenses"
            common.mkdir(parents=True)
            names = ["GPL-2", "GPL-3", "LGPL", "LGPL-2", "LGPL-2.1", "LGPL-3"]
            for name in names:
                (common / name).write_text("synthetic common-license fixture: " + name, encoding="utf-8")
            version = "2.37.2-4ubuntu3.6"
            owner = {"kind": "debian", "name": "libuuid1:amd64", "version": version,
                     "source_package": "util-linux", "source_version": version, "original": str(staged)}
            records = [{"name": "pyinstaller", "notices": ["python/pyinstaller/COPYING.txt"]}]
            copy_notices = module.debian_notices

            def synthetic_source(package, version, destination):
                directory = destination / (package + "-" + version)
                directory.mkdir()
                _, dsc = SourceTests().source_fixture(directory, version)
                dsc.write_text(dsc.read_text(encoding="utf-8").replace("Source: example\n", "Source: " + package + "\n"),
                               encoding="utf-8")
                files = module.verify_source_directory(directory, package, version)
                return {"source_package": package, "source_version": version,
                        "files": {directory.name + "/" + name: digest for name, digest in files.items()}}

            with patch.object(Path, "read_text", cp1252_read_text), \
                    patch.object(module, "linker_paths", return_value={}), \
                    patch.object(module, "linked_libraries", return_value=[]), \
                    patch.object(module, "python_runtime_owner", return_value=None), \
                    patch.object(module, "debian_owner", return_value=owner), \
                    patch.object(module, "debian_notices", side_effect=lambda owner, out: copy_notices(owner, out, root)), \
                    patch.object(module, "fetch_source", side_effect=synthetic_source) as fetch, \
                    patch.object(module, "license_policy", wraps=module.license_policy) as policy:
                collected = module.collect(worker, native, output, root / "sources", records, [])
                report = module.audit_payload(staged.parent, collected, output, root / "sources")
            fetch.assert_called_once_with("util-linux", version, root / "sources")
            self.assertTrue(report["success"])
            self.assertEqual(report["shared_library_count"], 1)
            self.assertEqual(report["source_package_count"], 1)
            self.assertEqual(policy.call_count, 2)  # Collection and postbundle each re-read the notice.
            for call in policy.call_args_list:
                self.assertEqual(call.args, (expected_text, "util-linux", "libuuid.so.1"))
                self.assertEqual(call.kwargs, {"source_version": version})
                self.assertEqual(hashlib.sha256(call.args[0].encode("utf-8")).hexdigest(), expected_hash)
            copied = output / "linux/debian/libuuid1_amd64-2.37.2-4ubuntu3.6/copyright"
            self.assertEqual(copied.read_bytes(), fixture.read_bytes())
            for name in names:
                self.assertEqual((output / "linux/common-licenses" / name).read_bytes(), (common / name).read_bytes())

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
