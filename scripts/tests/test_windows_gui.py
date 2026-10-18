"""Portable UNIT tests only. These never establish native Windows GUI acceptance.

Run: python -m unittest discover -s scripts/tests -p test_windows_gui.py -v
"""
import importlib.util
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'windows_gui', Path(__file__).parents[1] / 'smoke_windows_gui.py')
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)

HOSTED = {
    'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
    'RUNNER_OS': 'Windows', 'GITHUB_REPOSITORY': 'ClawPick2026/paperwork-desktop',
    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ID': '123',
    'GITHUB_RUN_ATTEMPT': '1', 'RUNNER_TEMP': r'C:\runner\temp', 'ImageOS': 'win22',
}


class RunnerGuardTests(unittest.TestCase):
    def test_rejects_non_windows_and_every_missing_or_wrong_ci_guard(self):
        with self.assertRaises(RuntimeError):
            smoke.require_disposable_runner(HOSTED, 'linux')
        for key in HOSTED:
            for value in (None, '', 'untrusted'):
                env = dict(HOSTED)
                if value is None:
                    del env[key]
                else:
                    env[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                    smoke.require_disposable_runner(env, 'win32')

    def test_real_cli_rejection_has_nonzero_exit_and_no_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, GITHUB_ACTIONS='false', RUNNER_TEMP=temporary,
                       PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, str(Path(smoke.__file__))], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Only manual execution', result.stderr)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_accepts_only_explicit_hosted_manual_windows_context(self):
        smoke.require_disposable_runner(HOSTED, 'win32')


class DownloadTests(unittest.TestCase):
    def test_copy_is_exact_sized_and_hash_verified(self):
        payload = b'unit-only installer bytes'
        digest = hashlib.sha256(payload).hexdigest()
        for data, size, sha, valid in (
            (payload, len(payload), digest, True),
            (payload + b'x', len(payload), digest, False),
            (payload[:-1], len(payload), digest, False),
            (payload, len(payload), '0' * 64, False),
        ):
            with self.subTest(size=len(data), sha=sha):
                output = io.BytesIO()
                if valid:
                    smoke.copy_verified(io.BytesIO(data), output, size, sha)
                    self.assertEqual(output.getvalue(), payload)
                else:
                    with self.assertRaises(RuntimeError):
                        smoke.copy_verified(io.BytesIO(data), output, size, sha)
                    self.assertLessEqual(len(output.getvalue()), size)

    def test_only_fixed_public_release_and_https_asset_redirect_are_allowed(self):
        smoke.validate_download_url(smoke.INSTALLER_URL, initial=True)
        smoke.validate_download_url('https://release-assets.githubusercontent.com/github-production-release-asset/1/fixture?sig=not-secret')
        for url in (
            'http://github.com/ClawPick2026/paperwork-desktop/releases/download/v0.1.0-rc.1/Paperwork_0.1.0_x64-setup.exe',
            'https://github.com/another/repo/releases/download/a/b.exe',
            smoke.INSTALLER_URL + '?x=1',
            'https://github.com@evil.example/file.exe',
            'https://release-assets.githubusercontent.com:444/github-production-release-asset/a',
            'https://release-assets.githubusercontent.com/anything.exe',
            'file:///C:/installer.exe',
        ):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                smoke.validate_download_url(url)
        with self.assertRaises(RuntimeError):
            smoke.validate_download_url('https://release-assets.githubusercontent.com/github-production-release-asset/a', initial=True)


class ArtifactHelperTests(unittest.TestCase):
    def test_serializes_non_iterable_win32_rect_without_losing_negative_origin(self):
        rect = SimpleNamespace(left=-8, top=-8, right=1288, bottom=908)
        self.assertEqual(smoke.rectangle_values(rect), [-8, -8, 1288, 908])

    def test_run_root_and_nsis_destination_are_bounded_and_keep_spaces(self):
        self.assertEqual(str(smoke.run_root(HOSTED)), r'C:\runner\temp\paperwork-windows-gui-123-1')
        command = smoke.nsis_install_command(r'C:\runner\temp\setup.exe', r'C:\runner\temp\installed Paperwork')
        self.assertTrue(command.endswith(r' /D=C:\runner\temp\installed Paperwork'))
        self.assertIn('/S', command)
        for invalid in (r'C:\runner\..\temp', r'\\server\share', 'relative', 'C:\\', r'C:\temp\name:stream'):
            env = dict(HOSTED, RUNNER_TEMP=invalid)
            with self.subTest(path=invalid), self.assertRaises(RuntimeError):
                smoke.require_disposable_runner(env, 'win32')

    def test_inspection_parser_requires_actual_expected_text_object(self):
        data = {'pages': [{'page': 1, 'objects': [
            {'type': 'text', 'text': 'synthetic GUI marker', 'editable': True, 'object_index': 0}]}]}
        text = 'Returned details\n' + json.dumps(data) + '\nextra UI copy'
        self.assertEqual(smoke.parse_inspection(text, 'synthetic GUI marker')['pages'][0]['page'], 1)
        for invalid in ('synthetic GUI marker', json.dumps({'pages': []}),
                        text.replace('synthetic GUI marker', 'incorrect'),
                        text.replace('"editable": true', '"editable": false')):
            with self.subTest(text=invalid), self.assertRaises(RuntimeError):
                smoke.parse_inspection(invalid, 'synthetic GUI marker')

    # Existing helper behavior characterization, not native GUI proof.
    def test_json_evidence_round_trip_is_complete_and_no_staging_file_remains(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'state.json'
            smoke.write_json(path, {'passed': False, 'exit_status': 1})
            smoke.write_json(path, {'passed': True, 'exit_status': 0})
            self.assertEqual(json.loads(path.read_text()), {'passed': True, 'exit_status': 0})
            self.assertEqual([p.name for p in Path(temporary).iterdir()], ['state.json'])

    def test_wait_helper_never_treats_timeout_as_success(self):
        self.assertEqual(smoke.wait_until(lambda: 'observed', 'unit', timeout=1), 'observed')
        with self.assertRaisesRegex(RuntimeError, 'Timed out: absent'):
            smoke.wait_until(lambda: False, 'absent', timeout=0)

    def test_contact_readback_rejects_wrong_pdf_shape(self):
        fields = {name: {'/FT': '/Tx'} for name in ('name', 'email', 'message')}
        smoke.validate_contact(1, 'Contact form\nName\nEmail\nMessage', fields)
        for pages, text, f in ((0, 'Contact form', fields), (2, 'Contact form', fields),
                               (1, 'Not the expected form', fields), (1, 'Contact form', {}),
                               (1, 'Contact form', dict(fields, name={'/FT': '/Btn'}))):
            with self.subTest(pages=pages, text=text, fields=f), self.assertRaises(RuntimeError):
                smoke.validate_contact(pages, text, f)


class NativeTraceTests(unittest.TestCase):
    def test_drive_reads_inspection_from_nonclickable_overflowing_uia_text(self):
        # Simulated UIA provider only: exercise real drive/lookup/parser behavior,
        # not Windows rendering, processing, file dialogs, or GUI acceptance.
        details = {'pages': [{'page': 1, 'objects': [
            {'type': 'text', 'text': smoke.MARKER, 'editable': True, 'object_index': 0}]}]}
        outer = SimpleNamespace(left=0, top=0, right=1000, bottom=800,
                                height=lambda: 800)
        button_rect = SimpleNamespace(left=20, top=100, right=300, bottom=150,
                                      width=lambda: 280, height=lambda: 50)
        text_rect = SimpleNamespace(left=20, top=200, right=1400, bottom=1600,
                                    width=lambda: 1380, height=lambda: 1400)

        def element(text, rect, enabled):
            return SimpleNamespace(window_text=lambda: text, rectangle=lambda: rect,
                                   is_visible=lambda: True, is_enabled=lambda: enabled)

        result = element(json.dumps(details, indent=2), text_rect, False)
        controls = {
            'Text': [result] + [element(text, button_rect, True) for text in (
                'synthetic-input.pdf',
                'Processing finished. Read the returned details below.',
                'Processing finished. Save outputs below.',
                'Output saved to the location you selected.',
            )],
            'Button': [element(text, button_rect, True) for text in (
                'Run Inspect PDF text', 'Run PDF form templates', 'Save output',
            )],
        }
        trace = object.__new__(smoke.NativeTrace)
        trace.window = SimpleNamespace(
            rectangle=lambda: outer,
            descendants=lambda control_type: controls.get(control_type, []))
        scrolls = []
        trace.mouse = SimpleNamespace(scroll=lambda **kwargs: scrolls.append(kwargs))
        trace.focus = lambda target: None
        trace.connect = lambda: None
        clicks = []
        trace.click = lambda name, **kwargs: clicks.append(name)
        trace.file_dialog = lambda *args: None
        trace.capture = lambda *args, **kwargs: None
        trace.step = lambda *args, **kwargs: None
        self.assertFalse(trace.usable(result))  # Reading must not require a click target.

        with tempfile.TemporaryDirectory() as temporary, patch.object(smoke.time, 'sleep'):
            trace.evidence = Path(temporary)
            trace.drive()
            observed = json.loads((trace.evidence / 'inspection-ui-readback.json').read_text())
        self.assertEqual(observed, details)
        self.assertIn('Save output', clicks)  # Inspection did not block the next operation.
        self.assertEqual(scrolls, [])


class WorkflowStaticTests(unittest.TestCase):
    """Static CI configuration checks, explicitly not execution evidence."""
    def test_manual_only_readonly_bounded_hosted_lane_with_pinned_actions(self):
        workflow = Path(__file__).parents[2] / '.github/workflows/windows-gui.yml'
        text = workflow.read_text(encoding='utf-8')
        self.assertRegex(text, r'(?m)^on:\n  workflow_dispatch:\n\npermissions:\n  contents: read\n')
        self.assertNotRegex(text, r'(?m)^  (push|pull_request|pull_request_target|schedule|workflow_call):')
        self.assertIn('runs-on: windows-2022', text)
        self.assertIn('timeout-minutes: 20', text)
        uses = re.findall(r'(?m)^\s+(?:- )?uses: (\S+)', text)
        self.assertEqual(len(uses), 3)
        for action in uses:
            self.assertRegex(action, r'^actions/[a-z-]+@[0-9a-f]{40}$')
        self.assertLess(text.index('Guard disposable hosted Windows'), text.index('actions/setup-python@'))
        self.assertIn('persist-credentials: false', text)
        self.assertIn('if: always()', text)
        self.assertIn('venv', text)


if __name__ == '__main__':
    unittest.main()
