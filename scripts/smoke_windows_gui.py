"""Manual, disposable-CI native GUI acceptance; NOT a worker smoke test.

python scripts/smoke_windows_gui.py

Only the fixed public RC is accepted. Requires an already interactive Windows
2022 GitHub-hosted desktop; never unlocks/logs in, installs global tools, modifies
the app, enables debugging, injects IPC/grants, or invokes its worker directly.
Silent NSIS setup/uninstall are recorded separately from real UIA/mouse GUI
interaction. The GUI subprocess has a hard timeout so a hung UIA provider cannot
turn a partial trace into a pass. All documents and evidence are synthetic.
"""


import argparse
import ctypes
import hashlib
import os
import sys
import traceback
import urllib.request
import json
import subprocess
import re
import time
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

INSTALLER_URL = 'https://github.com/ClawPick2026/paperwork-desktop/releases/download/v0.1.0-rc.1/Paperwork_0.1.0_x64-setup.exe'
INSTALLER_SHA256 = '8d823fccb3cd29232a34146815b1ed0c6b809d63089c2b9056715ed75990b112'
INSTALLER_SIZE = 34070948
SOURCE_COMMIT = '5d14d6223241868b9f269b06aec22c50e96b1d35'


def copy_verified(source, target, size, sha256):
    digest = hashlib.sha256()
    count = 0
    deadline = time.monotonic() + 180
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError('Installer download exceeded its time budget.')
        block = source.read(min(65536, size - count + 1))
        if not block:
            break
        count += len(block)
        if count > size:
            raise RuntimeError('Installer exceeds the exact byte cap.')
        digest.update(block)
        target.write(block)
    if count != size or digest.hexdigest() != sha256:
        raise RuntimeError('Installer exact size or SHA-256 mismatch.')


def validate_download_url(url, initial=False):
    parts = urlsplit(url)
    asset = (parts.scheme == 'https' and parts.netloc == 'release-assets.githubusercontent.com'
             and parts.path.startswith('/github-production-release-asset/')
             and not parts.fragment)
    if url != INSTALLER_URL and (initial or not asset):
        raise RuntimeError('Installer download URL/redirect is not allowlisted.')


def run_root(env):
    return PureWindowsPath(env['RUNNER_TEMP']) / ('paperwork-windows-gui-' + env['GITHUB_RUN_ID'] + '-' + env['GITHUB_RUN_ATTEMPT'])


def nsis_install_command(installer, destination):
    # NSIS requires /D last, WITHOUT quotes, including destinations with spaces.
    # This is a CreateProcess command line, never a shell command.
    return subprocess.list2cmdline([str(installer), '/S']) + ' /D=' + str(destination)


def parse_inspection(text, marker):
    if len(text) > 1_000_000:
        raise RuntimeError('UI inspection text exceeds the evidence bound.')
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{', text):
        try:
            data, _ = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        pages = data.get('pages')
        if not isinstance(pages, list) or len(pages) != 1 or not isinstance(pages[0], dict):
            continue
        objects = pages[0].get('objects', [])
        if pages[0].get('page') == 1 and any(
            isinstance(obj, dict) and obj.get('type') == 'text'
            and str(obj.get('text', '')).strip() == marker and obj.get('editable') is True
            and isinstance(obj.get('object_index'), int) for obj in objects
        ):
            return data
    raise RuntimeError('Real UI returned no expected editable synthetic text object.')


def validate_contact(page_count, text, fields):
    if (page_count != 1 or 'Contact form' not in text
            or set(fields) != {'name', 'email', 'message'}
            or any(field.get('/FT') != '/Tx' for field in fields.values())):
        raise RuntimeError('Saved PDF is not the expected one-page contact AcroForm.')


def require_disposable_runner(env, platform):
    expected = {
        'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
        'RUNNER_OS': 'Windows', 'GITHUB_REPOSITORY': 'ClawPick2026/paperwork-desktop',
        'GITHUB_EVENT_NAME': 'workflow_dispatch', 'ImageOS': 'win22',
    }
    if platform != 'win32' or any(env.get(k) != v for k, v in expected.items()):
        raise RuntimeError('Only manual execution on disposable GitHub-hosted Windows is allowed.')
    if any(not re.fullmatch(r'[1-9][0-9]*', env.get(k, ''))
           for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')):
        raise RuntimeError('Missing or invalid GitHub run identity.')
    temp = PureWindowsPath(env.get('RUNNER_TEMP', ''))
    if (not temp.is_absolute() or not re.fullmatch(r'[A-Za-z]:', temp.drive)
            or len(temp.parts) < 2 or '..' in temp.parts
            or any(re.search(r'[<>:"|?*\x00-\x1f]', p) or p.endswith((' ', '.')) for p in temp.parts[1:])):
        raise RuntimeError('RUNNER_TEMP must be a local absolute Windows path.')


WINDOW_TITLE = 'Paperwork Desktop'
APP_IDENTIFIER = 'io.github.clawpick2026.paperwork'
MARKER = 'Paperwork native GUI synthetic acceptance 2026'
APP_EXE = 'paperwork-desktop.exe'  # src-tauri/Cargo.toml package/binary name


def write_json(path, data):
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def wait_until(predicate, description, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.4)
    raise RuntimeError('Timed out: ' + description)


def interactive_desktop():
    """Fail closed in Session 0, locked/disconnected or non-default desktops."""
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user.GetThreadDesktop.restype = wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD
    session = wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)) or session.value == 0:
        raise RuntimeError('No interactive desktop: process is in Session 0 or session lookup failed.')
    active = kernel.WTSGetActiveConsoleSessionId()
    if session.value != active:
        raise RuntimeError('Runner is not in the active console session; no login/unlock workaround is allowed.')
    handle = user.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS only
    if not handle:
        raise RuntimeError('OpenInputDesktop failed; real GUI acceptance is unavailable.')

    def desktop_name(value):
        buf = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if not user.GetUserObjectInformationW(value, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)):
            raise RuntimeError('Unable to inspect desktop identity.')
        return buf.value

    try:
        input_name = desktop_name(handle)
        thread_name = desktop_name(user.GetThreadDesktop(kernel.GetCurrentThreadId()))
        if input_name.casefold() != 'default' or thread_name != input_name:
            raise RuntimeError('Locked, secure, or mismatched desktop; refusing GUI automation.')
    finally:
        user.CloseDesktop(handle)
    width, height = user.GetSystemMetrics(0), user.GetSystemMetrics(1)
    if width < 800 or height < 600:
        raise RuntimeError('Interactive screen is absent or too small.')
    return dict(session_id=session.value, active_console_session=active,
                input_desktop=input_name, thread_desktop=thread_name, screen=[width, height])


class ReleaseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_installer(destination):
    validate_download_url(INSTALLER_URL, initial=True)
    opener = urllib.request.build_opener(ReleaseRedirects())
    request = urllib.request.Request(INSTALLER_URL, headers={'User-Agent': 'Paperwork-native-GUI-acceptance'})
    try:
        with opener.open(request, timeout=30) as response, destination.open('xb') as target:
            validate_download_url(response.geturl())
            declared = response.headers.get('Content-Length')
            if declared is not None and declared != str(INSTALLER_SIZE):
                raise RuntimeError('Installer Content-Length does not match the pinned size.')
            copy_verified(response, target, INSTALLER_SIZE, INSTALLER_SHA256)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def create_synthetic_pdf(path):
    """Independent synthetic input, not an application fixture/grant API."""
    from pypdf import PdfWriter, PdfReader
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
        NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(('BT /F1 15 Tf 54 700 Td (' + MARKER + ') Tj ET').encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)
    reader = PdfReader(path, strict=True)
    if len(reader.pages) != 1 or reader.pages[0].extract_text().strip() != MARKER:
        raise RuntimeError('Synthetic fixture failed its independent input validation.')


def read_saved_pdf(path):
    from pypdf import PdfReader
    if not path.is_file() or not 100 < path.stat().st_size < 4_000_000:
        raise RuntimeError('Saved PDF is absent, empty or exceeds the synthetic output bound.')
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise RuntimeError('Unexpected encryption in saved contact form.')
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    fields = reader.get_fields() or {}
    validate_contact(len(reader.pages), text, fields)
    return dict(reader='pypdf independent disk readback (not the application worker)',
                pages=len(reader.pages), title='Contact form',
                fields={name: str(value.get('/FT')) for name, value in fields.items()},
                bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def rectangle_values(rectangle):
    return [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom]


def screenshot_metrics(image):
    from PIL import ImageStat
    # Exclude the OS titlebar: a decorated but empty WebView must not pass.
    body = image.convert('RGB').crop((8, 48, image.width - 8, image.height - 8))
    small = body.resize((160, 120))
    return dict(size=[image.width, image.height],
                body_stddev=max(ImageStat.Stat(body).stddev),
                body_colors=len(small.getcolors(19200) or []))


class NativeTrace:
    """Real UIA + mouse/keyboard only; no browser/CDP/JS/IPC access."""
    def __init__(self, root, pid):
        from pywinauto import Desktop, mouse
        self.desktop = Desktop(backend='uia')
        self.mouse = mouse
        self.pid = pid
        self.root = root
        self.evidence = root / 'evidence'
        self.window = None
        self.state = dict(kind='native-windows-GUI', passed=False, exit_status=None,
                          pid=pid, steps=[], close_requested=False)
        self.persist()

    def persist(self):
        write_json(self.evidence / 'gui-state.json', self.state)

    def step(self, name, **details):
        self.state['steps'].append(dict(name=name, monotonic=time.monotonic(), **details))
        self.persist()

    def focus(self, target):
        from ctypes import wintypes
        target.set_focus()
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetForegroundWindow.restype = wintypes.HWND
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        if user.GetForegroundWindow() != target.handle:
            user.SetForegroundWindow(target.handle)  # Ordinary foreground request; no unlock/bypass.
        if user.GetForegroundWindow() != target.handle:
            raise RuntimeError('Real target window could not receive foreground input.')

    def connect(self):
        def find():
            windows = self.desktop.windows(title=WINDOW_TITLE, process=self.pid)
            return windows[0] if len(windows) == 1 else None
        self.window = wait_until(find, 'installed app window', 60)
        self.window.maximize()
        self.focus(self.window)
        if self.window.element_info.process_id != self.pid or self.window.window_text() != WINDOW_TITLE:
            raise RuntimeError('Real app window identity mismatch.')
        self.step('real-window-detected', title=WINDOW_TITLE, hwnd=self.window.handle,
                  process_id=self.pid, backend='Windows UI Automation')
        self.capture('00-native-window-before-render-check')
        wait_until(lambda: self.has_text('Your documents.'), 'rendered home content', 45)
        self.capture('01-home', require_nonblank=True)
        self.step('home-rendered')

    def elements(self, role=None, scope=None):
        target = scope if scope is not None else self.window
        return target.descendants(**({'control_type': role} if role else {}))

    def has_text(self, text):
        return any(text in e.window_text() for e in self.elements('Text'))

    def named(self, name, role='Button', scope=None, contains=False):
        def matches(element):
            value = element.window_text().replace('&', '').strip()
            return (name in value and not value.startswith('Run ')) if contains else value == name
        return [e for e in self.elements(role, scope) if matches(e)]

    def usable(self, element, scope=None):
        outer = (scope if scope is not None else self.window).rectangle()
        rect = element.rectangle()
        return (element.is_visible() and element.is_enabled() and rect.width() > 0 and rect.height() > 0
                and rect.left >= outer.left and rect.right <= outer.right
                and rect.top >= outer.top + 85 and rect.bottom < outer.bottom)

    def seek(self, name, role='Button', contains=False):
        self.focus(self.window)
        found = self.named(name, role, contains=contains)
        if len(found) == 1 and self.usable(found[0]):
            return found[0]
        # Ordinary bounded scrolling of the real app, never injected DOM navigation.
        box = self.window.rectangle()
        # Right-hand document padding avoids scrolling a nested result <pre>.
        point = (box.right - 24, box.top + int(box.height() * .65))
        self.mouse.scroll(coords=point, wheel_dist=80)
        time.sleep(.3)
        for _ in range(26):
            found = self.named(name, role, contains=contains)
            if len(found) == 1 and self.usable(found[0]):
                return found[0]
            if len(found) > 1:
                raise RuntimeError('Ambiguous real UIA control: ' + name)
            self.mouse.scroll(coords=point, wheel_dist=-4)
            time.sleep(.2)
        raise RuntimeError('No usable real UIA control after bounded scrolling: ' + name)

    def click(self, name, contains=False):
        self.seek(name, contains=contains).click_input()
        self.step('clicked', control=name)

    def capture(self, label, target=None, require_nonblank=False):
        target = target if target is not None else self.window
        if target is None:
            return
        image = target.capture_as_image()
        image.save(self.evidence / (label + '.png'))
        metrics = screenshot_metrics(image)
        count = [0]

        def tree(element, depth=0):
            if count[0] >= 2000 or depth >= 32:
                return {'truncated': True}
            count[0] += 1
            info = element.element_info
            node = dict(name=info.name[:12000], role=info.control_type,
                        automation_id=info.automation_id, class_name=info.class_name,
                        process_id=info.process_id, rectangle=rectangle_values(element.rectangle()),
                        visible=element.is_visible(), children=[])
            for child in element.children():
                if count[0] >= 2000:
                    node['truncated'] = True
                    break
                node['children'].append(tree(child, depth + 1))
            return node
        write_json(self.evidence / (label + '-uia.json'),
                   dict(source='live Windows UIA hierarchy', tree=tree(target), screenshot=metrics))
        if require_nonblank and (image.width < 720 or image.height < 600
                                 or metrics['body_stddev'] < 5 or metrics['body_colors'] < 12):
            raise RuntimeError('App screenshot is blank, undersized, or unrendered.')

    def file_dialog(self, title, path, action, label):
        def find():
            dialogs = self.desktop.windows(title=title, process=self.pid, class_name='#32770')
            return dialogs[0] if len(dialogs) == 1 else None
        dialog = wait_until(find, 'real system file dialog: ' + title)
        self.focus(dialog)
        self.capture(label + '-before', dialog)
        edits = [e for e in self.elements('Edit', dialog)
                 if e.window_text().replace('&', '').strip().rstrip(':') == 'File name']
        if not edits:
            combos = [e for e in self.elements('ComboBox', dialog)
                      if e.window_text().replace('&', '').strip().rstrip(':') == 'File name']
            if len(combos) == 1:
                edits = combos[0].descendants(control_type='Edit')
        if len(edits) != 1:
            raise RuntimeError('System file dialog has no unique labelled File name edit; refusing blind input.')
        edits[0].set_edit_text(str(path))
        if edits[0].get_value() != str(path):
            raise RuntimeError('Native file name field did not retain the exact synthetic path.')
        self.capture(label + '-path', dialog)
        buttons = self.named(action, scope=dialog)
        if len(buttons) != 1 or not buttons[0].is_enabled():
            raise RuntimeError('No unique enabled native dialog action: ' + action)
        buttons[0].click_input()
        wait_until(lambda: not find(), 'native system dialog dismissal')
        self.step('system-file-dialog-completed', title=title, action=action, synthetic_path=str(path))

    def drive(self):
        self.connect()
        self.click('Inspect PDF text', contains=True)
        self.click('Choose native files')
        self.file_dialog('Select documents or media to process', self.evidence / 'synthetic-input.pdf',
                         'Open', '02-native-open')
        wait_until(lambda: self.has_text('synthetic-input.pdf'), 'picker-selected file rendered')
        self.seek('Run Inspect PDF text')
        self.capture('03-native-selection', require_nonblank=True)
        self.click('Run Inspect PDF text')
        wait_until(lambda: self.has_text('Processing finished. Read the returned details below.'),
                   'inspection UI completion', 75)
        # The inspected marker is not in any UI input/path: it must come from
        # the installed local operation, through the actual native results UI.
        # Read-only UIA Text can overflow the viewport; it is not a click target.
        wait_until(lambda: self.has_text(MARKER), 'inspection marker in UIA Text')
        text = '\n'.join(e.window_text() for e in self.elements('Text'))
        details = parse_inspection(text, MARKER)
        write_json(self.evidence / 'inspection-ui-readback.json', details)
        self.capture('04-inspection-result', require_nonblank=True)
        self.step('inspection-UI-readback', expected_text=MARKER)
        self.click('PDF form templates', contains=True)
        self.seek('Run PDF form templates')
        # The catalog's default is contact. Readback independently verifies it.
        self.capture('05-contact-template', require_nonblank=True)
        self.click('Run PDF form templates')
        wait_until(lambda: self.has_text('Processing finished. Save outputs below.'),
                   'contact form UI completion', 75)
        self.click('Save output')
        saved = self.evidence / 'saved-contact.pdf'
        if saved.exists():
            raise RuntimeError('Save destination unexpectedly exists; refusing overwrite.')
        self.file_dialog('Save result', saved, 'Save', '06-native-save')
        wait_until(lambda: self.has_text('Output saved to the location you selected.'),
                   'actual UI save confirmation')
        self.seek('Save output')
        self.capture('07-saved-result', require_nonblank=True)
        self.step('save-UI-confirmed')

    def run(self):
        try:
            self.drive()
            self.state['passed'] = True
            self.state['exit_status'] = 0
        except Exception as exc:
            self.state['error'] = str(exc)
            self.state['exit_status'] = 1
            self.persist()
            try:
                self.capture('failure-app')
                for index, dialog in enumerate(self.desktop.windows(process=self.pid)):
                    if dialog.window_text() in ('Select documents or media to process', 'Save result'):
                        self.capture('failure-dialog-' + str(index), dialog)
            except Exception as capture_error:
                self.state['capture_error'] = str(capture_error)
            traceback.print_exc()
        finally:
            if self.window is not None:
                try:
                    self.window.close()  # Normal native WM_CLOSE/Window.Close, not process termination.
                    self.state['close_requested'] = True
                except Exception as close_error:
                    self.state['close_error'] = str(close_error)
                    self.state['passed'] = False
                    self.state['exit_status'] = 1
            self.persist()
        return self.state['exit_status']


def orchestrate(root):
    root.mkdir(exist_ok=False)  # Never reuse a cache/install or erase another run.
    evidence = root / 'evidence'
    evidence.mkdir()
    state_path = evidence / 'acceptance.json'
    state = dict(schema=1, kind='published-RC-native-Windows-GUI-and-uninstall',
                 passed=False, exit_status=1, installer_url=INSTALLER_URL,
                 installer_sha256=INSTALLER_SHA256, installer_bytes=INSTALLER_SIZE,
                 installer_source_commit=SOURCE_COMMIT, app_identifier=APP_IDENTIFIER,
                 automation_checkout=os.environ.get('GITHUB_SHA'),
                 automation_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 native_gui_passed=False, normal_close_passed=False, uninstall_passed=False,
                 install_mode='silent NSIS currentUser', uninstall_mode='silent NSIS actual uninstaller',
                 direct_worker_invocations=0, browser_preview_used=False, synthetic_data_only=True,
                 steps=[])
    app = None
    installed = root / 'installed Paperwork'
    executable = installed / APP_EXE
    uninstaller = installed / 'uninstall.exe'

    def step(name, **details):
        state['steps'].append(dict(name=name, monotonic=time.monotonic(), **details))
        write_json(state_path, state)

    def command(name, args, timeout):
        with (evidence / (name + '.log')).open('w', encoding='utf-8') as log:
            try:
                result = subprocess.run(args, timeout=timeout, stdout=log, stderr=subprocess.STDOUT,
                                        shell=False, check=False)
            except subprocess.TimeoutExpired:
                step(name, exit_status=124, timed_out=True)
                raise
        step(name, exit_status=result.returncode)
        if result.returncode != 0:
            raise RuntimeError(name + ' exited with ' + str(result.returncode))

    write_json(state_path, state)
    try:
        state['desktop'] = interactive_desktop()
        step('interactive-desktop-preflight')
        # Imports only on an authorized disposable runner. End users need no Python.
        import pywinauto
        import PIL
        import pypdf
        state['automation_dependencies'] = dict(pywinauto=pywinauto.__version__,
                                                Pillow=PIL.__version__, pypdf=pypdf.__version__)
        create_synthetic_pdf(evidence / 'synthetic-input.pdf')
        step('synthetic-input-created', sha256=hashlib.sha256((evidence / 'synthetic-input.pdf').read_bytes()).hexdigest())
        installer = root / 'Paperwork_0.1.0_x64-setup.exe'
        download_installer(installer)
        step('installer-exact-hash-and-size-verified')
        command('silent-install', nsis_install_command(installer, installed), 180)
        if not executable.is_file() or not uninstaller.is_file():
            raise RuntimeError('Installed application or actual NSIS uninstaller is absent.')
        step('installed-binaries-present', app=str(executable), uninstaller=str(uninstaller),
             app_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
        env = dict(os.environ)
        # Do not inherit debug/backdoor options from a caller.
        for name in ('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', 'WEBVIEW2_BROWSER_EXECUTABLE_FOLDER',
                     'WEBVIEW2_USER_DATA_FOLDER'):
            env.pop(name, None)
        with (evidence / 'app.log').open('w', encoding='utf-8') as log:
            app = subprocess.Popen([str(executable)], stdout=log, stderr=subprocess.STDOUT,
                                   cwd=installed, env=env, shell=False)
            step('actual-installed-app-launched', pid=app.pid, arguments=[])
            command('native-gui-driver', [sys.executable, str(Path(__file__).resolve()),
                                         '--drive-window', str(app.pid)], 420)
            gui = json.loads((evidence / 'gui-state.json').read_text(encoding='utf-8'))
            if not gui.get('passed') or gui.get('exit_status') != 0 or not gui.get('close_requested'):
                raise RuntimeError('Real GUI trace did not finish and request normal close.')
            state['native_gui_passed'] = True
            exit_code = app.wait(timeout=30)
            if exit_code != 0:
                raise RuntimeError('App did not exit cleanly after normal native close.')
            state['normal_close_passed'] = True
            step('normal-close-process-exit', exit_status=exit_code)
        state['saved_pdf'] = read_saved_pdf(evidence / 'saved-contact.pdf')
        step('independent-saved-PDF-readback')
    except Exception as exc:
        state['error'] = str(exc)
        traceback.print_exc()
        step('acceptance-failed', error=str(exc))
    finally:
        if app is not None and app.poll() is None:
            # Failure-only cleanup, NEVER counted as normal close or GUI success.
            state['forced_app_cleanup'] = True
            try:
                command('failure-only-taskkill', ['taskkill.exe', '/PID', str(app.pid), '/T', '/F'], 20)
                app.wait(timeout=10)
            except Exception as exc:
                state['cleanup_error'] = str(exc)
        if uninstaller.is_file() and (app is None or app.poll() is not None):
            try:
                command('actual-silent-uninstall', [str(uninstaller), '/S'], 90)
                wait_until(lambda: not executable.exists() and not uninstaller.exists(),
                           'actual uninstall removes app and uninstaller binaries', 60)
                state['uninstall_passed'] = True
                step('uninstall-removal-verified', application_binary_removed=True,
                     uninstaller_binary_removed=True)
            except Exception as exc:
                state['uninstall_error'] = str(exc)
                step('uninstall-failed', error=str(exc))
        state['passed'] = (not state.get('error') and state['native_gui_passed']
                           and state['normal_close_passed'] and state['uninstall_passed']
                           and bool(state.get('saved_pdf')) and not state.get('forced_app_cleanup'))
        state['exit_status'] = 0 if state['passed'] else 1
        write_json(state_path, state)
        print(json.dumps(state, indent=2))
    return state['exit_status']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drive-window', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    # MUST precede all imports with side effects, mkdir, downloads, install/cache writes.
    require_disposable_runner(os.environ, sys.platform)
    root = Path(run_root(os.environ))
    if args.drive_window is not None:
        if args.drive_window <= 0 or not (root / 'evidence' / 'acceptance.json').is_file():
            raise RuntimeError('GUI driver is only valid inside its parent acceptance run.')
        interactive_desktop()
        return NativeTrace(root, args.drive_window).run()
    return orchestrate(root)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
