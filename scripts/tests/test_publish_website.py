"""Website publish orchestration. Stdlib only; no network, Lakebed or browser."""
import contextlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "publish_website.py"
spec = importlib.util.spec_from_file_location("publish_website", SCRIPT)
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)

OLD = "1" * 64
NEW = "082f67d21764fe2de1579d027c242a1bb76e1f784eb225f3fdd390f63983848b"
BUILD_OUTPUT = f"""Artifact written to /repo/.lakebed/artifacts/web.claimed.json
Target:   claimed
Artifact: sha256:{'d' * 64}
Client:   sha256:{NEW}
"""


def html(digest):
    return f'<script type="module" src="/client.js?v=sha256%3A{digest}"></script>'


class FakeRunner:
    """Records commands; answers git queries and serves scripted live HTML."""
    def __init__(self, root, *, branch="main", behind="0", dirty="", fail=(), live=(OLD, NEW)):
        self.root, self.branch, self.behind, self.dirty, self.fail = root, branch, behind, dirty, set(fail)
        self.live = list(live)
        self.commands, self.fetched, self.slept = [], [], 0

    def run(self, argv, *, env=None):
        self.commands.append((tuple(argv), dict(env or {})))
        joined = " ".join(argv)
        if argv[:2] == ["git", "rev-parse"]:
            return 0, (self.branch if "--abbrev-ref" in argv else "abc123") + "\n"
        if argv[:2] == ["git", "rev-list"]:
            return 0, self.behind + "\n"
        if argv[:2] == ["git", "status"]:
            return 0, self.dirty
        for name in self.fail:
            if name in joined:
                return 1, f"{name} failed\n"
        if "web:build" in joined:
            artifact = self.root / ".lakebed" / "artifacts" / "web.claimed.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}")
            return 0, BUILD_OUTPUT
        if "deploy" in argv:
            return 0, "Deployed dep_yefw3xsfKf5oAixk\nclaimToken tok_SECRETvalue123\nhttps://leafsmith.lakebed.app\n"
        return 0, ""

    def fetch(self, url):
        self.fetched.append(url)
        return html(self.live.pop(0) if len(self.live) > 1 else self.live[0])

    def sleep(self, seconds):
        self.slept += seconds

    @contextlib.contextmanager
    def serve_web(self):
        self.commands.append((("serve-web",), {}))
        yield "http://127.0.0.1:43123"


def repo(deploy_id=publish.DEPLOY_ID):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "web").mkdir()
    (root / "web" / "lakebed.json").write_text(json.dumps({"deployId": deploy_id}))
    return tmp, root


def names(runner):
    return [" ".join(argv) for argv, _ in runner.commands]


class ParsingTests(unittest.TestCase):
    def test_client_hash_from_lakebed_build_output(self):
        self.assertEqual(publish.client_hash_from_build(BUILD_OUTPUT), NEW)
        with self.assertRaisesRegex(publish.PublishError, "client hash"):
            publish.client_hash_from_build("Artifact: sha256:" + "d" * 64)

    def test_client_hash_from_served_html(self):
        self.assertEqual(publish.client_hash_from_html(html(NEW)), NEW)
        self.assertEqual(publish.client_hash_from_html(f'src="/client.js?v=sha256:{NEW}"'), NEW)
        self.assertIsNone(publish.client_hash_from_html("<html></html>"))

    def test_redacts_lakebed_tokens_from_printed_output(self):
        text = publish.redact('claimToken tok_C1QCC7wbFs7Ojz "claimToken": "abc", "token":"xyz"')
        self.assertNotIn("tok_C1QCC7wbFs7Ojz", text)
        self.assertNotIn('"abc"', text)
        self.assertNotIn('"xyz"', text)


class PreflightTests(unittest.TestCase):
    def test_refuses_another_deploy_identity(self):
        tmp, root = repo("dep_other")
        with tmp:
            with self.assertRaisesRegex(publish.PublishError, "dep_yefw3xsfKf5oAixk"):
                publish.check_identity(root)
            (root / "web" / "lakebed.json").unlink()
            with self.assertRaisesRegex(publish.PublishError, "lakebed.json"):
                publish.check_identity(root)

    def test_branch_behind_and_uncommitted_rules(self):
        with self.assertRaisesRegex(publish.PublishError, "main"):
            publish.preflight("feature", 0, [], False)
        with self.assertRaisesRegex(publish.PublishError, "behind origin/main"):
            publish.preflight("main", 2, [], False)
        with self.assertRaisesRegex(publish.PublishError, "web/client/a.tsx.*--allow-uncommitted"):
            publish.preflight("main", 0, ["web/client/a.tsx"], False)
        self.assertEqual(publish.preflight("main", 0, [], False), [])
        warnings = publish.preflight("main", 0, ["web/client/a.tsx"], True)
        self.assertTrue(any("not match any commit" in w for w in warnings), warnings)

    def test_artifact_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "web.claimed.json"
            artifact.write_bytes(b"x" * publish.ARTIFACT_LIMIT)
            self.assertEqual(publish.check_artifact(artifact), publish.ARTIFACT_LIMIT)
            artifact.write_bytes(b"x" * (publish.ARTIFACT_LIMIT + 1))
            with self.assertRaisesRegex(publish.PublishError, "1 MiB"):
                publish.check_artifact(artifact)


class SuiteTests(unittest.TestCase):
    def test_browser_suite_targets_url_with_each_script_convention(self):
        steps = {name: (argv, env) for name, argv, env in publish.browser_suite("https://x.test", "/py")}
        self.assertEqual(steps["discovery_http"], (["/py", "web/tests/discovery_http.py"], {"LEAFSMITH_URL": "https://x.test"}))
        self.assertEqual(steps["seo_browser"][0], ["/py", "web/tests/seo_browser.py", "https://x.test", "all"])
        self.assertEqual(steps["e2e"][0], ["/py", "web/tests/e2e.py", "https://x.test"])
        self.assertEqual(steps["review_regressions"][0], ["/py", "web/tests/review_regressions.py", "https://x.test"])
        self.assertEqual(steps["theme_browser"][0], ["/py", "web/tests/theme_browser.py", "https://x.test", "web"])
        self.assertEqual(steps["crop_preview"][0], ["/py", "web/tests/crop_preview.py", "https://x.test"])
        self.assertEqual(steps["ui_polish"][1], {"LEAFSMITH_URL": "https://x.test"})
        self.assertEqual(steps["test_shell"][1], {"LEAFSMITH_URL": "https://x.test"})
        self.assertNotIn("desktop_download", steps)
        with_downloads = [name for name, _, _ in publish.browser_suite("https://x.test", "/py", downloads=True)]
        self.assertIn("desktop_download", with_downloads)


class PublishFlowTests(unittest.TestCase):
    def options(self, **values):
        return {"dry_run": False, "allow_uncommitted": False, "local_browser": True,
                "downloads": False, "python": "/py", "url": publish.PUBLIC_URL, **values}

    def test_full_publish_order_waits_for_new_bundle_then_checks_live_site(self):
        tmp, root = repo()
        with tmp:
            runner = FakeRunner(root)
            record = publish.publish(self.options(), runner, root=root)
            seen = names(runner)
            order = [seen.index(step) for step in ("npm test", "npm run build", "npm run web:build", "serve-web",
                                                    "npx --yes lakebed@0.0.40 deploy web")]
            self.assertEqual(order, sorted(order))
            deploy = seen.index("npx --yes lakebed@0.0.40 deploy web")
            local = [i for i, (argv, env) in enumerate(runner.commands)
                     if "http://127.0.0.1:43123" in argv or env.get("LEAFSMITH_URL") == "http://127.0.0.1:43123"]
            live = [i for i, (argv, env) in enumerate(runner.commands)
                    if publish.PUBLIC_URL in argv or env.get("LEAFSMITH_URL") == publish.PUBLIC_URL]
            self.assertTrue(local and max(local) < deploy)
            self.assertTrue(any(i > deploy for i in live), "live suite must run after deploy")
            self.assertEqual(record["client"], NEW)
            self.assertEqual(record["head"], "abc123")
            self.assertTrue(record["deployed"])
            self.assertGreaterEqual(len(runner.fetched), 2)
            self.assertNotIn("tok_SECRETvalue123", json.dumps(record))

    def test_dry_run_never_deploys(self):
        tmp, root = repo()
        with tmp:
            runner = FakeRunner(root)
            record = publish.publish(self.options(dry_run=True), runner, root=root)
            self.assertFalse(any("deploy" in name for name in names(runner)))
            self.assertFalse(record["deployed"])

    def test_failed_local_check_stops_before_deploy(self):
        for failing in ("npm test", "web/tests/e2e.py"):
            tmp, root = repo()
            with tmp:
                runner = FakeRunner(root, fail={failing})
                with self.assertRaisesRegex(publish.PublishError, "Nothing was deployed"):
                    publish.publish(self.options(), runner, root=root)
                self.assertFalse(any("deploy" in name for name in names(runner)), failing)

    def test_live_site_must_serve_the_built_bundle(self):
        tmp, root = repo()
        with tmp:
            runner = FakeRunner(root, live=(OLD,))
            with self.assertRaisesRegex(publish.PublishError, "still serves"):
                publish.publish(self.options(), runner, root=root)
            self.assertGreater(runner.slept, 0)

    def test_post_deploy_failure_says_the_site_was_updated(self):
        tmp, root = repo()
        with tmp:
            runner = FakeRunner(root)
            original = runner.run
            def run(argv, *, env=None):
                if publish.PUBLIC_URL in argv and "e2e.py" in " ".join(argv) and any("deploy" in n for n in names(runner)):
                    runner.commands.append((tuple(argv), dict(env or {})))
                    return 1, "live e2e failed\n"
                return original(argv, env=env)
            runner.run = run
            with self.assertRaisesRegex(publish.PublishError, "live site is already updated"):
                publish.publish(self.options(), runner, root=root)

    def test_uncommitted_web_changes_need_the_explicit_flag(self):
        tmp, root = repo()
        with tmp:
            runner = FakeRunner(root, dirty=" M web/client/workspace.tsx\n?? web/client/preview.tsx\n")
            with self.assertRaisesRegex(publish.PublishError, "--allow-uncommitted"):
                publish.publish(self.options(), runner, root=root)
            record = publish.publish(self.options(allow_uncommitted=True), FakeRunner(root, dirty=runner.dirty), root=root)
            self.assertEqual(record["uncommitted"], ["web/client/workspace.tsx", "web/client/preview.tsx"])


if __name__ == "__main__":
    unittest.main()
