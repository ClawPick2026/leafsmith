//! The worker and its engines are one lifetime: a Unix process group or a
//! Windows kill-on-close job. Never send request data before containment exists.
use serde_json::Value;
use std::{
    io::{Read, Write},
    path::Path,
    process::{Child, Command, Stdio},
    sync::{mpsc, Arc, Mutex, OnceLock, Weak},
    thread,
    time::{Duration, Instant},
};

const REPORT_LIMIT: usize = 8 * 1024 * 1024;
const WORKER_TIMEOUT: Duration = Duration::from_secs(1800);
static WORKERS: OnceLock<WorkerRegistry> = OnceLock::new();

#[derive(Default)]
struct RegistryState {
    closing: bool,
    active: Vec<Weak<ProcessTree>>,
}
#[derive(Default)]
struct WorkerRegistry(Mutex<RegistryState>);

impl WorkerRegistry {
    fn spawn(&self, command: &mut Command) -> Result<WorkerGuard, String> {
        // Serialize registration with shutdown, including spawn/containment.
        let mut registry = self.0.lock().map_err(|_| "Worker tracking is unavailable.")?;
        if registry.closing {
            return Err("The application is closing; processing was cancelled.".into());
        }
        command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
        platform::configure(command);
        let child = command.spawn().map_err(|_| "The processing worker could not start.")?;
        let mut worker = WorkerGuard { child, tree: None };
        let tree = Arc::new(ProcessTree(Mutex::new(Some(platform::Tree::attach(&worker.child)?))));
        worker.tree = Some(tree.clone());
        registry.active.retain(|tree| tree.strong_count() != 0);
        registry.active.push(Arc::downgrade(&tree));
        Ok(worker)
    }

    fn shutdown(&self) {
        let mut registry = self.0.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        registry.closing = true;
        for tree in registry.active.drain(..).filter_map(|tree| tree.upgrade()) {
            tree.terminate();
        }
    }
}

struct ProcessTree(Mutex<Option<platform::Tree>>);
impl ProcessTree {
    fn terminate(&self) {
        // Take once: repeated cleanup must never signal a recycled Unix PGID.
        if let Some(mut tree) = self.0.lock().unwrap_or_else(|poisoned| poisoned.into_inner()).take() {
            tree.terminate();
        }
    }
}
impl Drop for ProcessTree {
    fn drop(&mut self) { self.terminate(); }
}
struct WorkerGuard {
    child: Child,
    tree: Option<Arc<ProcessTree>>,
}
impl WorkerGuard {
    fn terminate_tree(&self) {
        if let Some(tree) = &self.tree { tree.terminate(); }
    }
}
impl Drop for WorkerGuard {
    fn drop(&mut self) {
        self.terminate_tree();
        // Also covers containment setup failures (a suspended Windows child).
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Called by Tauri's Exit event, before its process exits. spawn_blocking tasks
/// can outlive NativeState, so state Drop alone is not a shutdown mechanism.
pub(crate) fn shutdown_workers() {
    WORKERS.get_or_init(WorkerRegistry::default).shutdown();
}

pub(crate) fn execute_worker(worker: &Path, request: &Value) -> Result<Value, String> {
    if !worker.is_file() {
        return Err("The packaged processing worker is missing. Reinstall Leafsmith from a verified release.".into());
    }
    let temporary = PrivateTemp::new(request)?;
    let mut command = Command::new(worker);
    configure_environment(&mut command, &temporary.0);
    execute_command(&mut command, request,
        WORKERS.get_or_init(WorkerRegistry::default), WORKER_TIMEOUT, REPORT_LIMIT)
}

fn configure_environment(command: &mut Command, temporary: &Path) {
    command.env_clear();
    for key in ["PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
        "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "LC_CTYPE"] {
        if let Some(value) = std::env::var_os(key) { command.env(key, value); }
    }
    // API keys are provided explicitly in this operation's private stdin, never
    // inherited wholesale alongside CI/cloud credentials or Python injection.
    for key in ["TMPDIR", "TMP", "TEMP"] { command.env(key, temporary); }
}

struct PrivateTemp(std::path::PathBuf);
impl PrivateTemp {
    fn new(request: &Value) -> Result<Self, String> {
        let base = request.get("output_dir").and_then(Value::as_str)
            .map(std::path::PathBuf::from).unwrap_or_else(std::env::temp_dir);
        let path = base.join(format!(".worker-tmp-{}", uuid::Uuid::new_v4()));
        let mut builder = std::fs::DirBuilder::new();
        #[cfg(unix)]
        { use std::os::unix::fs::DirBuilderExt; builder.mode(0o700); }
        builder.create(&path).map_err(|_| "The private worker temporary directory could not be created.")?;
        Ok(Self(path))
    }
}
impl Drop for PrivateTemp {
    fn drop(&mut self) { let _ = remove_private_directory(&self.0); }
}

pub(crate) fn remove_private_directory(path: &Path) -> std::io::Result<()> {
    // Windows may release a terminated engine's open file handles shortly after
    // the worker exits. Bound retries; startup cleanup retries after any crash.
    for attempt in 0..20 {
        match std::fs::remove_dir_all(path) {
            Ok(()) => return Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(error) if attempt == 19 => return Err(error),
            Err(_) => thread::sleep(Duration::from_millis(50)),
        }
    }
    unreachable!()
}

fn execute_command(command: &mut Command, request: &Value, registry: &WorkerRegistry,
    timeout: Duration, report_limit: usize) -> Result<Value, String> {
    let mut payload = serde_json::to_vec(request).map_err(|_| "Invalid worker request.")?;
    payload.push(b'\n');
    let mut worker = registry.spawn(command)?;
    let mut stdin = worker.child.stdin.take().ok_or("Worker input is unavailable.")?;
    let stdout = worker.child.stdout.take().ok_or("Worker output is unavailable.")?;
    // Both pipe operations must be under the deadline. A child may never read
    // stdin, flood stdout, or exit with an engine still holding stdout open.
    let (input_tx, input_rx) = mpsc::sync_channel(1);
    let writer = thread::spawn(move || { let _ = input_tx.send(stdin.write_all(&payload)); });
    let (output_tx, output_rx) = mpsc::sync_channel(1);
    let reader = thread::spawn(move || {
        let mut data = Vec::new();
        let result = stdout.take(report_limit as u64 + 1).read_to_end(&mut data).map(|_| data);
        let _ = output_tx.send(result);
    });
    let result = (|| {
        let started = Instant::now();
        let mut input_done = false;
        let mut output = None;
        let mut exited = false;
        loop {
            if started.elapsed() >= timeout {
                return Err("Processing timed out after 30 minutes. Source files were not changed.".into());
            }
            if !input_done {
                match input_rx.try_recv() {
                    Ok(Ok(())) => input_done = true,
                    Ok(Err(_)) | Err(mpsc::TryRecvError::Disconnected) =>
                        return Err("The processing worker closed unexpectedly.".into()),
                    Err(mpsc::TryRecvError::Empty) => {},
                }
            }
            if output.is_none() {
                match output_rx.try_recv() {
                    Ok(Ok(data)) => {
                        if data.len() > report_limit {
                            return Err("The processing report exceeds the size limit.".into());
                        }
                        output = Some(data);
                    },
                    Ok(Err(_)) | Err(mpsc::TryRecvError::Disconnected) =>
                        return Err("The worker output could not be read.".into()),
                    Err(mpsc::TryRecvError::Empty) => {},
                }
            }
            if !exited && worker.child.try_wait().map_err(|_| "Worker status is unavailable.")?.is_some() {
                exited = true;
                // Descendants must not keep stdout alive after the worker exits.
                worker.terminate_tree();
            }
            if exited && input_done {
                if let Some(data) = output.take() {
                    let response: Value = serde_json::from_slice(&data)
                        .map_err(|_| "The processing worker returned invalid JSON.")?;
                    if response.get("ok").and_then(Value::as_bool) != Some(true) {
                        return Err(response.pointer("/error/message").and_then(Value::as_str)
                            .unwrap_or("The operation failed.").to_owned());
                    }
                    return response.get("result").cloned().ok_or_else(|| "The worker returned no result.".into());
                }
            }
            thread::sleep(Duration::from_millis(10));
        }
    })();
    // Kill before joining either pipe thread, on every result/error path.
    drop(worker);
    let _ = writer.join();
    let _ = reader.join();
    result
}

#[cfg(unix)]
mod platform {
    use super::*;
    use std::os::unix::process::CommandExt;

    pub(super) fn configure(command: &mut Command) { command.process_group(0); }
    pub(super) struct Tree(libc::pid_t);
    impl Tree {
        pub(super) fn attach(child: &Child) -> Result<Self, String> { Ok(Self(child.id() as libc::pid_t)) }
        pub(super) fn terminate(&mut self) {
            // The child became its own group leader before exec, so engines
            // inherit this group, not the desktop application's process group.
            unsafe { libc::kill(-self.0, libc::SIGKILL); }
        }
    }
}

#[cfg(windows)]
mod platform {
    use super::*;
    use std::os::windows::{io::{AsRawHandle, FromRawHandle, OwnedHandle}, process::CommandExt};
    use windows_sys::Win32::{
        Foundation::INVALID_HANDLE_VALUE,
        System::{
            Diagnostics::ToolHelp::{CreateToolhelp32Snapshot, Thread32First, Thread32Next, THREADENTRY32, TH32CS_SNAPTHREAD},
            JobObjects::{AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject, TerminateJobObject,
                JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE},
            Threading::{OpenThread, ResumeThread, CREATE_NO_WINDOW, CREATE_SUSPENDED, THREAD_SUSPEND_RESUME},
        },
    };

    pub(super) fn configure(command: &mut Command) {
        // The PyInstaller bootloader itself may spawn before it reads stdin.
        // Suspend even its first instruction until it belongs to our job.
        command.creation_flags(CREATE_NO_WINDOW | CREATE_SUSPENDED);
    }
    pub(super) struct Tree(OwnedHandle);
    impl Tree {
        pub(super) fn attach(child: &Child) -> Result<Self, String> {
            unsafe {
                let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if job.is_null() { return Err("Worker process isolation could not be created.".into()); }
                let tree = Self(OwnedHandle::from_raw_handle(job));
                let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                if SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                    &limits as *const _ as *const _, std::mem::size_of_val(&limits) as u32) == 0
                    || AssignProcessToJobObject(job, child.as_raw_handle()) == 0 {
                    return Err("The processing worker could not be isolated.".into());
                }
                // std::process::Child exposes the process handle but not its
                // suspended primary thread. Locate that thread without a shell.
                let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
                if snapshot == INVALID_HANDLE_VALUE {
                    return Err("The isolated processing worker could not start.".into());
                }
                let _snapshot = OwnedHandle::from_raw_handle(snapshot);
                let mut entry: THREADENTRY32 = std::mem::zeroed();
                entry.dwSize = std::mem::size_of_val(&entry) as u32;
                let mut found = Thread32First(snapshot, &mut entry);
                while found != 0 {
                    if entry.th32OwnerProcessID == child.id() {
                        let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                        if thread.is_null() { break; }
                        let _thread = OwnedHandle::from_raw_handle(thread);
                        if ResumeThread(thread) != u32::MAX { return Ok(tree); }
                        break;
                    }
                    found = Thread32Next(snapshot, &mut entry);
                }
                Err("The isolated processing worker could not start.".into())
            }
        }
        pub(super) fn terminate(&mut self) {
            unsafe { TerminateJobObject(self.0.as_raw_handle(), 1); }
            // OwnedHandle closes immediately after this call; kill-on-close is
            // also enforced by Windows if the desktop process crashes/exits.
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "leafsmith-worker-test-{}-{}",
                std::process::id(), NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed)
            ));
            crate::private_directory(&path).unwrap();
            Self(path)
        }
        fn command(&self, mode: &str) -> Command {
            let mut command = Command::new(std::env::current_exe().unwrap());
            command.args(["--ignored", "--exact", "worker_process::tests::dummy_worker", "--nocapture"])
                .env("LEAFSMITH_TEST_WORKER", mode)
                .env("LEAFSMITH_TEST_FIXTURE", &self.0);
            command
        }
        fn descendant(&self) -> u32 {
            fs::read_to_string(self.0.join("descendant.pid")).expect("dummy descendant started")
                .parse().unwrap()
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
    }

    // This is an actual native child, launched only by the tests below. It never
    // returns to libtest (whose protocol is deliberately not the worker JSON).
    #[test]
    #[ignore = "subprocess fixture; launched by lifecycle regression tests"]
    fn dummy_worker() {
        let mode = std::env::var("LEAFSMITH_TEST_WORKER").expect("fixture-only entry point");
        if mode == "leaf" || mode == "no-read" {
            thread::sleep(Duration::from_secs(15));
            std::process::exit(0);
        }
        let fixture = Fixture(PathBuf::from(std::env::var_os("LEAFSMITH_TEST_FIXTURE").unwrap()));
        let mut request = String::new();
        std::io::stdin().read_to_string(&mut request).unwrap();
        if mode == "environment" {
            let environment: std::collections::HashMap<String, String> = std::env::vars()
                .filter(|(key, _)| matches!(key.as_str(), "TMPDIR" | "TEMP" | "GITHUB_TOKEN" | "LEAFSMITH_API_KEY" | "PYTHONPATH"))
                .collect();
            fs::write(fixture.0.join("environment.json"), serde_json::to_vec(&environment).unwrap()).unwrap();
            std::process::exit(0);
        }
        let mut leaf = fixture.command("leaf");
        // Inherit stdout: killing only the parent used to leave this pipe open.
        leaf.stdin(Stdio::null()).stdout(Stdio::inherit()).stderr(Stdio::null());
        let child = leaf.spawn().unwrap();
        fs::write(fixture.0.join("descendant.tmp"), child.id().to_string()).unwrap();
        fs::rename(fixture.0.join("descendant.tmp"), fixture.0.join("descendant.pid")).unwrap();
        if mode == "exit" { std::process::exit(0); }
        if mode == "overflow" {
            std::io::stdout().write_all(&vec![b'x'; 16 * 1024]).unwrap();
            std::io::stdout().flush().unwrap();
        }
        thread::sleep(Duration::from_secs(15));
        std::process::exit(0);
    }

    #[cfg(unix)]
    fn process_running(pid: u32) -> bool {
        // A killed orphan may briefly remain a zombie on a CI host whose PID 1
        // reaps slowly. A zombie is not a surviving processing engine.
        #[cfg(target_os = "linux")]
        if let Ok(stat) = fs::read_to_string(format!("/proc/{pid}/stat")) {
            if stat.rsplit_once(") ").map(|(_, tail)| tail.starts_with('Z')).unwrap_or(false) {
                return false;
            }
        }
        unsafe { libc::kill(pid as libc::pid_t, 0) == 0 }
    }
    #[cfg(windows)]
    fn process_running(pid: u32) -> bool {
        use windows_sys::Win32::{Foundation::{CloseHandle, WAIT_TIMEOUT}, System::Threading::{OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE}};
        unsafe {
            let process = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
            if process.is_null() { return false; }
            let running = WaitForSingleObject(process, 0) == WAIT_TIMEOUT;
            CloseHandle(process);
            running
        }
    }
    fn assert_stopped(pid: u32) {
        let start = Instant::now();
        while process_running(pid) && start.elapsed() < Duration::from_secs(3) {
            thread::sleep(Duration::from_millis(10));
        }
        assert!(!process_running(pid), "worker descendant {pid} survived tree cleanup");
    }

    #[test]
    fn worker_exit_does_not_wait_for_descendant_stdout() {
        let fixture = Fixture::new();
        let start = Instant::now();
        let result = execute_command(&mut fixture.command("exit"), &json!({}), &WorkerRegistry::default(),
            Duration::from_secs(6), REPORT_LIMIT);
        assert!(result.unwrap_err().contains("invalid JSON"));
        assert!(start.elapsed() < Duration::from_secs(5));
        assert_stopped(fixture.descendant());
    }

    #[test]
    fn output_overflow_kills_worker_descendants() {
        let fixture = Fixture::new();
        let result = execute_command(&mut fixture.command("overflow"), &json!({}), &WorkerRegistry::default(),
            Duration::from_secs(6), 4096);
        assert!(result.unwrap_err().contains("size limit"));
        assert_stopped(fixture.descendant());
    }

    #[test]
    fn tauri_exit_event_kills_active_tree_and_prevents_new_workers() {
        let fixture = Fixture::new();
        let registry = Arc::new(WorkerRegistry::default());
        let running_registry = registry.clone();
        let mut command = fixture.command("hang");
        let execution = thread::spawn(move || execute_command(&mut command, &json!({}), &running_registry,
            Duration::from_secs(8), REPORT_LIMIT));
        let started = Instant::now();
        while !fixture.0.join("descendant.pid").is_file() && started.elapsed() < Duration::from_secs(5) {
            thread::sleep(Duration::from_millis(10));
        }
        let pid = fixture.descendant();
        crate::on_application_event(&tauri::RunEvent::Exit, || registry.shutdown());
        assert_stopped(pid);
        assert!(execution.join().unwrap().is_err());
        assert!(registry.spawn(&mut fixture.command("hang")).err().unwrap().contains("closing"));
    }

    #[test]
    fn blocked_request_pipe_is_covered_by_timeout() {
        let fixture = Fixture::new();
        let start = Instant::now();
        let result = execute_command(&mut fixture.command("no-read"), &json!({"data":"x".repeat(1024 * 1024)}),
            &WorkerRegistry::default(), Duration::from_secs(2), REPORT_LIMIT);
        assert!(result.unwrap_err().contains("timed out"));
        assert!(start.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn private_worker_temporary_files_are_removed_on_drop() {
        let fixture = Fixture::new();
        let temporary = PrivateTemp::new(&json!({"output_dir":fixture.0})).unwrap();
        assert!(temporary.0.starts_with(&fixture.0));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(fs::metadata(&temporary.0).unwrap().permissions().mode() & 0o777, 0o700);
        }
        fs::write(temporary.0.join("decrypted.tmp"), b"test-only-private-data").unwrap();
        let path = temporary.0.clone();
        drop(temporary);
        assert!(!path.exists());
    }

    #[test]
    fn worker_environment_drops_ambient_secrets_and_uses_private_temp() {
        let fixture = Fixture::new();
        let mut command = fixture.command("environment");
        command.env("GITHUB_TOKEN", "test-only-ambient-secret")
            .env("LEAFSMITH_API_KEY", "test-only-ambient-key").env("PYTHONPATH", "test-only-injection");
        configure_environment(&mut command, &fixture.0);
        // Fixture control is not part of the production environment allowlist.
        command.env("LEAFSMITH_TEST_WORKER", "environment").env("LEAFSMITH_TEST_FIXTURE", &fixture.0);

        let result = execute_command(&mut command, &json!({}), &WorkerRegistry::default(),
            Duration::from_secs(6), REPORT_LIMIT);
        // libtest emits its header, but the child writes its environment to a
        // private fixture file, not stdout or any production application log.
        assert!(result.unwrap_err().contains("invalid JSON"));
        let env: Value = serde_json::from_slice(&fs::read(fixture.0.join("environment.json")).unwrap()).unwrap();
        assert_eq!(env["TMPDIR"], fixture.0.to_string_lossy().as_ref());
        assert_eq!(env["TEMP"], fixture.0.to_string_lossy().as_ref());
        assert!(env.get("GITHUB_TOKEN").is_none());
        assert!(env.get("LEAFSMITH_API_KEY").is_none());
        assert!(env.get("PYTHONPATH").is_none());
    }

    #[test]
    fn timeout_kills_worker_descendants() {
        let fixture = Fixture::new();
        let registry = WorkerRegistry::default();
        let start = Instant::now();
        let result = execute_command(&mut fixture.command("hang"), &json!({}), &registry,
            Duration::from_secs(3), 8 * 1024 * 1024);
        assert!(result.unwrap_err().contains("timed out"));
        assert!(start.elapsed() < Duration::from_secs(6));
        assert_stopped(fixture.descendant());
    }
}
