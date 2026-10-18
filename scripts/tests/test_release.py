"""Desktop release automation. Stdlib only; no network, git remote, gh or CI."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release.py"
spec = importlib.util.spec_from_file_location("release", SCRIPT)
release = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release  # dataclasses resolve annotations through sys.modules
spec.loader.exec_module(release)

V = release.parse_version
FILES = ["package.json", "package-lock.json", "src-tauri/Cargo.toml", "src-tauri/tauri.conf.json",
         "web/shared/desktop.ts", "web/tests/desktop_download.py", "README.md"]
EXE_SHA, APP_SHA = "a" * 64, "b" * 64
DOWNLOAD = "https://github.com/ClawPick2026/paperwork-desktop/releases/download/"


def copy_repo():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for name in FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, root / name)
    (root / "docs" / "releases").mkdir(parents=True)
    # Flow tests assume app 0.1.0 with tags up to v0.1.0-rc.2, whatever the repository holds later.
    release.set_app_version(root, "0.1.0")
    return tmp, root


def github_release(tag="v0.1.0-rc.3", base="0.1.0", prerelease=True, **override):
    assets = [
        {"name": f"Paperwork_{base}_x64-setup.exe", "size": 34000001, "digest": "sha256:" + EXE_SHA},
        {"name": f"Paperwork_{base}_amd64.AppImage", "size": 139000002, "digest": "sha256:" + APP_SHA},
        {"name": "SHA256SUMS-windows-x86_64.txt", "size": 100, "digest": "sha256:" + "c" * 64},
        {"name": "SHA256SUMS-linux-x86_64.txt", "size": 100, "digest": "sha256:" + "d" * 64},
    ]
    for asset in assets:
        asset["browser_download_url"] = DOWNLOAD + tag + "/" + asset["name"]
    data = {"tag_name": tag, "draft": False, "prerelease": prerelease, "assets": assets}
    data.update(override)
    return data


def sums(base="0.1.0"):
    return f"{EXE_SHA}  Paperwork_{base}_x64-setup.exe\n{APP_SHA}  Paperwork_{base}_amd64.AppImage\n"


class VersionTests(unittest.TestCase):
    def test_parse_format_order_and_latest_tag(self):
        self.assertEqual(str(V("v0.1.0-rc.2")), "0.1.0-rc.2")
        self.assertEqual(V("0.1.0-rc.2").tag, "v0.1.0-rc.2")
        self.assertEqual(V("0.1.0-rc.2").label, "0.1.0 RC2")
        self.assertEqual(V("1.2.3").label, "1.2.3")
        self.assertEqual(V("0.1.0-rc.10").base, "0.1.0")
        self.assertLess(V("0.1.0-rc.2"), V("0.1.0-rc.10"))
        self.assertLess(V("0.1.0-rc.10"), V("0.1.0"))
        self.assertLess(V("0.1.0"), V("0.1.1-rc.1"))
        for bad in ("0.1", "v0.1.0-beta.1", "v0.1.0-rc2", "01.1.0", "components-v0.1.0", "v0.1.0\n"):
            with self.assertRaises(release.ReleaseError, msg=bad):
                V(bad)
        self.assertEqual(release.latest_tag(["components-v0.1.0", "v0.1.0-rc.1", "v0.1.0-rc.2", "junk"]), V("0.1.0-rc.2"))
        self.assertIsNone(release.latest_tag(["components-v0.1.0"]))

    def test_next_version_after_a_release_candidate(self):
        latest = V("0.1.0-rc.2")
        self.assertEqual(release.next_version("0.1.0", latest, "rc")[0], V("0.1.0-rc.3"))
        self.assertEqual(release.next_version("0.1.0", latest, "final")[0], V("0.1.0"))
        self.assertEqual(release.next_version("0.1.0", latest, "minor", rc=True)[0], V("0.2.0-rc.1"))
        self.assertEqual(release.next_version("0.1.0", latest, "major")[0], V("1.0.0"))
        version, warnings = release.next_version("0.1.0", latest, "patch")
        self.assertEqual(version, V("0.1.1"))
        self.assertTrue(any("never released as final" in w for w in warnings), warnings)

    def test_next_version_after_a_final_release_and_without_tags(self):
        latest = V("0.1.0")
        with self.assertRaisesRegex(release.ReleaseError, "already released"):
            release.next_version("0.1.0", latest, "rc")
        with self.assertRaisesRegex(release.ReleaseError, "release candidate"):
            release.next_version("0.1.0", latest, "final")
        self.assertEqual(release.next_version("0.1.0", latest, "patch", rc=True)[0], V("0.1.1-rc.1"))
        self.assertEqual(release.next_version("0.1.0", None, "rc")[0], V("0.1.0-rc.1"))
        with self.assertRaisesRegex(release.ReleaseError, "release candidate"):
            release.next_version("0.1.0", None, "final")

    def test_explicit_version_must_be_newer(self):
        self.assertEqual(release.next_version("0.1.0", V("0.1.0-rc.2"), None, explicit="0.1.0-rc.5")[0], V("0.1.0-rc.5"))
        with self.assertRaisesRegex(release.ReleaseError, "newer"):
            release.next_version("0.1.0", V("0.1.0-rc.2"), None, explicit="0.1.0-rc.2")
        with self.assertRaises(release.ReleaseError):
            release.next_version("0.1.0", None, None, explicit="latest")


class FileTests(unittest.TestCase):
    def test_app_version_changes_only_the_four_manifest_versions(self):
        tmp, root = copy_repo()
        with tmp:
            before = {name: (root / name).read_text() for name in FILES[:4]}
            changed = release.set_app_version(root, "9.2.0")
            self.assertEqual(sorted(str(p.relative_to(root)) for p in changed), sorted(FILES[:4]))
            self.assertEqual(json.loads((root / "package.json").read_text())["version"], "9.2.0")
            lock = json.loads((root / "package-lock.json").read_text())
            self.assertEqual((lock["version"], lock["packages"][""]["version"]), ("9.2.0", "9.2.0"))
            self.assertEqual(json.loads((root / "src-tauri/tauri.conf.json").read_text())["version"], "9.2.0")
            self.assertEqual(tomllib.loads((root / "src-tauri/Cargo.toml").read_text())["package"]["version"], "9.2.0")
            for name, old in before.items():
                diff = [a for a, b in zip(old.splitlines(), (root / name).read_text().splitlines()) if a != b]
                self.assertEqual(len(diff), 2 if name == "package-lock.json" else 1, name)
            self.assertEqual(release.set_app_version(root, "9.2.0"), [])

    def test_release_notes_pass_the_workflow_title_check_and_name_real_assets(self):
        notes = release.release_notes(V("0.2.0-rc.1"), "v0.1.0", ["feat: crop tools", "chore(release): v0.1.0"])
        self.assertTrue(notes.startswith("# Paperwork 0.2.0 RC1"))
        for text in ("Paperwork_0.2.0_x64-setup.exe", "Paperwork_0.2.0_amd64.AppImage", "unsigned",
                     "feat: crop tools", "## Not tested", "Changes since v0.1.0"):
            self.assertIn(text, notes)
        self.assertNotIn("chore(release)", notes)
        final = release.release_notes(V("0.2.0"), "v0.2.0-rc.1", [])
        self.assertTrue(final.startswith("# Paperwork 0.2.0 — Windows and Linux\n"))
        self.assertNotIn("preview", final.splitlines()[0].lower())

    def test_verify_assets_requires_matching_digests_urls_and_flags(self):
        info = release.verify_assets(V("0.1.0-rc.3"), github_release(), sums())
        self.assertEqual(info["Windows"], {"name": "Paperwork_0.1.0_x64-setup.exe", "sha256": EXE_SHA, "bytes": 34000001,
                                           "url": DOWNLOAD + "v0.1.0-rc.3/Paperwork_0.1.0_x64-setup.exe"})
        self.assertEqual(info["Linux"]["sha256"], APP_SHA)
        broken = {
            "missing": (github_release(assets=github_release()["assets"][1:]), sums()),
            "digest": (github_release(), sums().replace(EXE_SHA, "e" * 64)),
            "draft": (github_release(draft=True), sums()),
            "pre-release": (github_release(prerelease=False), sums()),
        }
        moved = github_release()
        moved["assets"][0]["browser_download_url"] = "https://example.com/x.exe"
        broken["URL"] = (moved, sums())
        for reason, (data, text) in broken.items():
            with self.assertRaisesRegex(release.ReleaseError, reason, msg=reason):
                release.verify_assets(V("0.1.0-rc.3"), data, text)

    def test_download_links_move_to_the_new_release_everywhere(self):
        tmp, root = copy_repo()
        with tmp:
            old_tag = "v" + re.search(r"version: '([^']+)'", (root / "web/shared/desktop.ts").read_text()).group(1)
            info = release.verify_assets(V("9.0.0"), github_release("v9.0.0", "9.0.0", prerelease=False), sums("9.0.0"))
            changed = release.update_links(root, V("9.0.0"), info)
            self.assertEqual(sorted(str(p.relative_to(root)) for p in changed),
                             ["README.md", "web/shared/desktop.ts", "web/tests/desktop_download.py"])
            for name in ("README.md", "web/shared/desktop.ts", "web/tests/desktop_download.py"):
                text = (root / name).read_text()
                self.assertNotIn(old_tag, text, name)
                self.assertNotIn("Paperwork_" + V(old_tag).base + "_", text, name)
            desktop = (root / "web/shared/desktop.ts").read_text()
            self.assertIn("version: '9.0.0'", desktop)
            self.assertIn(f"sha256: '{EXE_SHA}'", desktop)
            self.assertIn("bytes: 139000002", desktop)
            self.assertIn(DOWNLOAD + "v9.0.0/Paperwork_9.0.0_amd64.AppImage", desktop)
            test = (root / "web/tests/desktop_download.py").read_text()
            self.assertIn(f"'Paperwork_9.0.0_x64-setup.exe', '{EXE_SHA}'", test)
            self.assertIn("'9.0.0'", test)
            readme = (root / "README.md").read_text()
            self.assertIn("[9.0.0](https://github.com/ClawPick2026/paperwork-desktop/releases/tag/v9.0.0)", readme)


class FakeRunner:
    def __init__(self, root, *, dirty="", branch="main", remote_tag="", main_ci=0, confirm=True):
        self.root, self.dirty, self.branch, self.remote_tag, self.main_ci, self.answer = root, dirty, branch, remote_tag, main_ci, confirm
        self.commands, self.prompts = [], []
        self.tags = ["components-v0.1.0", "v0.1.0-rc.1", "v0.1.0-rc.2"]

    def run(self, argv, *, env=None):
        argv = list(argv)
        self.commands.append(argv)
        if argv[:2] == ["git", "rev-parse"]:
            return 0, (self.branch if "--abbrev-ref" in argv else "f00d" * 10) + "\n"
        if argv[:2] == ["git", "status"]:
            return 0, self.dirty
        if argv[:2] == ["git", "rev-list"]:
            return 0, "0\n"
        if argv[:2] == ["git", "tag"] and "--list" in argv:
            return 0, "\n".join(self.tags) + "\n"
        if argv[:2] == ["git", "ls-remote"]:
            return 0, self.remote_tag
        if argv[:2] == ["git", "log"]:
            return 0, "feat: crop tools\nfix: overlay bounds\n"
        if argv[:3] == ["gh", "run", "list"]:
            ref = argv[argv.index("--branch") + 1]
            return 0, json.dumps([{"databaseId": 11 if ref == "main" else 22}])
        if argv[:3] == ["gh", "run", "watch"]:
            return (self.main_ci if argv[3] == "11" else 0), ""
        if argv[:2] == ["gh", "api"]:
            tag = argv[2].rsplit("/", 1)[-1]
            return 0, json.dumps(github_release(tag, V(tag).base, V(tag).rc is not None))
        if argv[:3] == ["gh", "release", "download"]:
            tag = argv[3]
            base = V(tag).base
            name = argv[argv.index("--pattern") + 1]
            return 0, (sums(base).splitlines()[0] if "windows" in name else sums(base).splitlines()[1]) + "\n"
        return 0, ""

    def confirm(self, text):
        self.prompts.append(text)
        return self.answer

    def sleep(self, seconds):
        pass


def joined(runner):
    return [" ".join(c) for c in runner.commands]


class ReleaseFlowTests(unittest.TestCase):
    def options(self, **values):
        return {"bump": "rc", "rc": False, "version": None, "notes": None, "yes": False,
                "dry_run": False, "skip_checks": False, "no_wait": False, **values}

    def test_dry_run_changes_nothing(self):
        tmp, root = copy_repo()
        with tmp:
            before = {name: (root / name).read_text() for name in FILES}
            runner = FakeRunner(root)
            plan = release.release(self.options(dry_run=True, bump="minor"), runner, root=root)
            self.assertEqual(plan["version"], "0.2.0")
            self.assertEqual({name: (root / name).read_text() for name in FILES}, before)
            self.assertFalse([c for c in joined(runner) if c.startswith(("git commit", "git push", "git tag -a"))])
            self.assertEqual(list((root / "docs/releases").iterdir()), [])

    def test_full_release_order(self):
        tmp, root = copy_repo()
        with tmp:
            runner = FakeRunner(root)
            result = release.release(self.options(bump="minor", rc=True), runner, root=root)
            self.assertEqual(result["version"], "0.2.0-rc.1")
            seen = joined(runner)
            def first(prefix):
                return next(i for i, c in enumerate(seen) if c.startswith(prefix))
            steps = [first("npm test"), first("git commit -m chore(release): v0.2.0-rc.1"), first("git push origin main"),
                     first("gh run watch 11"), first("git tag -a v0.2.0-rc.1"), first("git push origin v0.2.0-rc.1"),
                     first("gh run watch 22"), first("gh api repos/ClawPick2026/paperwork-desktop/releases/tags/v0.2.0-rc.1"),
                     first("git commit -m docs: publish v0.2.0-rc.1 download links"),
                     max(i for i, c in enumerate(seen) if c == "git push origin main"),
                     first("python3 scripts/publish_website.py --verify-downloads")]
            self.assertEqual(steps, sorted(steps))
            self.assertEqual(json.loads((root / "package.json").read_text())["version"], "0.2.0")
            self.assertTrue((root / "docs/releases/v0.2.0-rc.1.md").read_text().startswith("# Paperwork 0.2.0 RC1"))
            self.assertIn("version: '0.2.0-rc.1'", (root / "web/shared/desktop.ts").read_text())
            self.assertEqual(len(runner.prompts), 1)

    def test_refusals_happen_before_any_change(self):
        cases = {
            "uncommitted": dict(dirty=" M README.md\n"),
            "main": dict(branch="feature"),
            "already exists": dict(remote_tag="abc\trefs/tags/v0.1.0-rc.3\n"),
            "cancelled": dict(confirm=False),
        }
        for reason, values in cases.items():
            tmp, root = copy_repo()
            with tmp:
                runner = FakeRunner(root, **values)
                with self.assertRaisesRegex(release.ReleaseError, reason, msg=reason):
                    release.release(self.options(), runner, root=root)
                self.assertFalse([c for c in joined(runner) if c.startswith(("git commit", "git push", "git tag -a"))], reason)
                self.assertEqual(list((root / "docs/releases").iterdir()), [], reason)

    def test_failed_main_build_stops_before_tagging(self):
        tmp, root = copy_repo()
        with tmp:
            runner = FakeRunner(root, main_ci=1)
            with self.assertRaisesRegex(release.ReleaseError, "--version 0.1.0-rc.3"):
                release.release(self.options(yes=True), runner, root=root)
            self.assertFalse([c for c in joined(runner) if c.startswith("git tag -a")])

    def test_no_wait_stops_after_pushing_the_tag(self):
        tmp, root = copy_repo()
        with tmp:
            runner = FakeRunner(root)
            release.release(self.options(yes=True, no_wait=True), runner, root=root)
            seen = joined(runner)
            self.assertIn("git push origin v0.1.0-rc.3", seen)
            self.assertFalse([c for c in seen if c.startswith(("gh run watch", "gh api", "python3 scripts/publish_website.py"))])
            self.assertEqual(runner.prompts, [])

    def test_links_only_publishes_an_existing_release(self):
        tmp, root = copy_repo()
        with tmp:
            runner = FakeRunner(root)
            release.links_only("v0.1.0-rc.3", runner, root=root)
            seen = joined(runner)
            self.assertIn("git commit -m docs: publish v0.1.0-rc.3 download links", seen)
            self.assertIn("python3 scripts/publish_website.py --verify-downloads", seen)
            self.assertIn("v0.1.0-rc.3", (root / "README.md").read_text())


if __name__ == "__main__":
    unittest.main()
