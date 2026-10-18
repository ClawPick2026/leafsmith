#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod components;
mod worker_process;
use serde::{Deserialize,Serialize};
use serde_json::{json,Value};
use std::{collections::HashMap,fs,path::{Path,PathBuf},sync::{atomic::{AtomicBool,Ordering},Mutex}};
use tauri::{Manager,State};
use uuid::Uuid;

#[derive(Default)]
struct NativeState { inputs:Mutex<HashMap<String,PathBuf>>, outputs:Mutex<HashMap<String,PathBuf>>, running:AtomicBool, cache:Mutex<Option<JobCache>> }

struct JobCache { root:PathBuf, _lease:fs::File }
impl JobCache {
    fn open(cache:&Path)->Result<Self,String>{
        use fs2::FileExt;
        fs::create_dir_all(cache).map_err(|_|"The local job cache could not be created.")?;
        let lease=fs::OpenOptions::new().create(true).truncate(false).read(true).write(true).open(cache.join("job-cache.lock")).map_err(|_|"The job cache lock is unavailable.")?;
        lease.try_lock_exclusive().map_err(|_|"Another Paperwork instance is using the local job cache. Close it before starting this instance.")?;
        let root=cache.join("jobs");
        worker_process::remove_private_directory(&root).map_err(|_|"Previous job files could not be removed. Close any applications using cached outputs and retry.")?;
        private_directory(&root)?;
        Ok(Self{root,_lease:lease})
    }
    fn cleanup(&self){let _=worker_process::remove_private_directory(&self.root);}
}
impl Drop for JobCache {fn drop(&mut self){self.cleanup();}}
fn private_directory(path:&Path)->Result<(),String>{
    let mut builder=fs::DirBuilder::new();
    #[cfg(unix)]
    {use std::os::unix::fs::DirBuilderExt;builder.mode(0o700);}
    builder.create(path).map_err(|_|"A private job directory could not be created.".into())
}
struct JobDirectory {path:PathBuf,keep:bool}
impl JobDirectory {
    fn new(root:&Path)->Result<Self,String>{
        let path=root.join(Uuid::new_v4().to_string());
        private_directory(&path)?;
        let mut directory=Self{path,keep:false};
        directory.path=dunce::canonicalize(&directory.path).map_err(|_|"The job directory could not be resolved.")?;
        Ok(directory)
    }
}
impl Drop for JobDirectory {fn drop(&mut self){if !self.keep{let _=worker_process::remove_private_directory(&self.path);}}}

fn cleanup_application(app:&tauri::AppHandle){
    worker_process::shutdown_workers();
    let state=app.state::<NativeState>();
    let cache=state.cache.lock().unwrap_or_else(|poisoned|poisoned.into_inner());
    if let Some(cache)=cache.as_ref(){cache.cleanup();}
}
fn on_application_event(event:&tauri::RunEvent,cleanup:impl FnOnce()){
    if matches!(event,tauri::RunEvent::Exit){cleanup();}
}
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
struct NativeFile { id:String,name:String,size:u64,path_hint:String }
#[derive(Serialize)]
struct NativeOutput { id:String,name:String,mime:String,size:u64 }
#[derive(Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
struct JobRequest { operation:String,input_ids:Vec<String>,options:Value }
#[derive(Serialize)]
struct JobResult { outputs:Vec<NativeOutput>,details:Value }

#[tauri::command]
async fn select_inputs(state:State<'_,NativeState>) -> Result<Vec<NativeFile>,String> {
    let paths=tauri::async_runtime::spawn_blocking(||rfd::FileDialog::new().set_title("Select documents or media to process").pick_files()).await.map_err(|_|"The file dialog failed.")?.unwrap_or_default();
    if paths.len()>64 {return Err("Select at most 64 files.".into());}
    let mut store=state.inputs.lock().map_err(|_|"File selection state is unavailable.")?;
    let mut files=Vec::new();
    for path in paths {
        let path=dunce::canonicalize(path).map_err(|_|"A selected file is unavailable.")?;
        let metadata=fs::metadata(&path).map_err(|_|"A selected file cannot be read.")?;
        if !metadata.is_file() || metadata.len()>2*1024*1024*1024 {return Err("Select regular files of at most 2 GiB each.".into());}
        let id=Uuid::new_v4().to_string();let name=path.file_name().unwrap_or_default().to_string_lossy().into_owned();
        files.push(NativeFile{id:id.clone(),name:name.clone(),size:metadata.len(),path_hint:name});store.insert(id,path);
    }
    Ok(files)
}

fn execute_worker(worker:&Path,request:&Value)->Result<Value,String> {
    worker_process::execute_worker(worker,request)
}
fn worker_path(app:&tauri::AppHandle)->Result<PathBuf,String>{
    let name=if cfg!(windows){"worker/paperwork-worker.exe"}else{"worker/paperwork-worker"};
    app.path().resolve(name,tauri::path::BaseDirectory::Resource).map_err(|_|"The app resource directory is unavailable.".into())
}
struct RunningGuard<'a>(&'a AtomicBool);
impl Drop for RunningGuard<'_>{fn drop(&mut self){self.0.store(false,Ordering::Release);}}

fn requires_cloud_consent(options:&Value)->Result<bool,String>{
    let provider=options.get("provider").and_then(Value::as_str).unwrap_or("local");
    // CLI providers never use endpoint. A stale UI value must not turn a local
    // model operation into a cloud operation (or trigger URL validation).
    if !matches!(provider,"ollama"|"openai-compatible"){return Ok(false);}
    let default_endpoint=if provider=="ollama"{"http://127.0.0.1:11434"}else{""};
    let endpoint=options.get("endpoint").and_then(Value::as_str).unwrap_or(default_endpoint);
    let parsed=reqwest::Url::parse(endpoint).map_err(|_|"The provider endpoint is invalid.")?;
    if endpoint.len()>2048 || !matches!(parsed.scheme(),"http"|"https") || parsed.host_str().is_none()
        || !parsed.username().is_empty() || parsed.password().is_some() || parsed.query().is_some()
        || parsed.fragment().is_some() || parsed.port()==Some(0){
        return Err("Use an HTTP(S) provider URL without credentials, query parameters or fragments.".into());
    }
    let loopback=matches!(parsed.host_str(),Some("localhost"|"127.0.0.1"|"::1"|"[::1]"));
    if !loopback && parsed.scheme()!="https"{return Err("Remote provider endpoints must use HTTPS.".into());}
    if !loopback && provider!="openai-compatible"{return Err("Choose the explicit cloud provider mode for a remote endpoint.".into());}
    let cloud=provider=="openai-compatible";
    if cloud && options.get("cloud_consent").and_then(Value::as_bool)!=Some(true){
        return Err("Cloud processing requires explicit consent for this operation.".into());
    }
    Ok(cloud)
}

#[tauri::command]
async fn run_native_job(app:tauri::AppHandle,state:State<'_,NativeState>,request:JobRequest)->Result<JobResult,String>{
    if !paperwork_security::is_supported_operation(&request.operation){return Err("This operation is not supported.".into());}
    if request.input_ids.len()>64 || !request.options.is_object() || serde_json::to_vec(&request.options).map_err(|_|"Invalid job options.")?.len()>32*1024{return Err("The operation options exceed the request limits.".into());}
    if state.running.swap(true,Ordering::AcqRel){return Err("A native processing job is already running.".into());}
    let _running=RunningGuard(&state.running);
    let inputs={let grants=state.inputs.lock().map_err(|_|"File grants are unavailable.")?;request.input_ids.iter().map(|id|grants.get(id).cloned().ok_or_else(||"Select the input file again; its read permission is no longer available.".to_owned())).collect::<Result<Vec<_>,_>>()?};
    if requires_cloud_consent(&request.options)? {
        let endpoint=request.options.get("endpoint").and_then(Value::as_str).unwrap_or("").to_owned();
        let approved=tauri::async_runtime::spawn_blocking(move||rfd::MessageDialog::new().set_title("Allow cloud processing?").set_description(format!("Selected document or media content will be sent to {endpoint}. Provider charges may apply. Continue with this operation?")).set_buttons(rfd::MessageButtons::OkCancel).show()).await.map_err(|_|"The consent dialog failed.")?;
        if approved!=rfd::MessageDialogResult::Ok{return Err("Cloud processing was cancelled. Nothing was sent.".into());}
    }
    let root=state.cache.lock().map_err(|_|"The local job cache is unavailable.")?.as_ref().ok_or("The local job cache is unavailable.")?.root.clone();
    let mut job_directory=JobDirectory::new(&root)?;
    let job=job_directory.path.clone();
    let mut engine_paths=components::engine_paths(&app)?;
    if let Some(model_id)=request.options.get("model_file_id").and_then(Value::as_str) {
        let model=state.inputs.lock().map_err(|_|"Model grants are unavailable.")?.get(model_id).cloned().ok_or("Select the local model file again.")?;
        let extension=model.extension().and_then(|s|s.to_str()).unwrap_or("").to_ascii_lowercase();
        if !["bin","gguf","ggml"].contains(&extension.as_str()){return Err("Select a local .bin, .gguf or .ggml model file.".into());}
        let key=if request.operation=="transcribe"{"whisper_model"}else{"llama_model"};
        engine_paths.insert(key.into(),model.to_string_lossy().into_owned());
    }
    let payload=json!({"operation":request.operation,"inputs":inputs,"output_dir":job,"options":request.options,"engines":engine_paths});
    let worker=worker_path(&app)?;
    let result=tauri::async_runtime::spawn_blocking(move||execute_worker(&worker,&payload)).await.map_err(|_|"The processing task failed.")??;
    let mut outputs=Vec::new();let mut pending_grants=Vec::new();
    for item in result.get("outputs").and_then(Value::as_array).ok_or("The worker output list is missing.")? {
        let path=dunce::canonicalize(item.get("path").and_then(Value::as_str).ok_or("An output path is missing.")?).map_err(|_|"An output file is unavailable.")?;
        if !path.starts_with(&job)||!path.is_file(){return Err("The worker attempted to expose a file outside the operation's output directory.".into());}
        let size=fs::metadata(&path).map_err(|_|"An output file cannot be read.")?.len();let id=Uuid::new_v4().to_string();
        let name=path.file_name().unwrap_or_default().to_string_lossy().into_owned();let mime=item.get("mime").and_then(Value::as_str).unwrap_or("application/octet-stream").to_owned();
        pending_grants.push((id.clone(),path));outputs.push(NativeOutput{id,name,mime,size});
    }
    state.outputs.lock().map_err(|_|"Output grants are unavailable.")?.extend(pending_grants);
    job_directory.keep=true;
    Ok(JobResult{outputs,details:result.get("details").cloned().unwrap_or(json!({}))})
}

#[tauri::command]
async fn save_output(state:State<'_,NativeState>,output_id:String)->Result<bool,String>{
    let source=state.outputs.lock().map_err(|_|"Output grants are unavailable.")?.get(&output_id).cloned().ok_or("The output is no longer available.")?;
    let name=source.file_name().unwrap_or_default().to_string_lossy().into_owned();
    let selected=tauri::async_runtime::spawn_blocking(move||rfd::FileDialog::new().set_title("Save result").set_file_name(name).save_file()).await.map_err(|_|"The save dialog failed.")?;
    if let Some(destination)=selected {if destination==source{return Ok(true);}fs::copy(source,destination).map_err(|_|"The result could not be saved. Check the destination and available disk space.")?;Ok(true)}else{Ok(false)}
}
#[tauri::command]
fn component_status(app:tauri::AppHandle)->Result<Vec<components::ComponentStatus>,String>{components::status(&app)}
#[tauri::command]
async fn install_component(app:tauri::AppHandle,component_id:String)->Result<components::ComponentStatus,String>{tauri::async_runtime::spawn_blocking(move||components::install(&app,&component_id)).await.map_err(|_|"The component installer failed.")?}

fn self_test(app:&tauri::AppHandle)->Result<Value,String>{
    // Exercise exactly the resource resolver used for GUI jobs, not a list of
    // plausible install paths that could conceal a broken Tauri bundle.
    execute_worker(&worker_path(app)?,&json!({"operation":"health"}))
}
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_final_exit_triggers_application_cleanup() {
        let mut called=false;
        on_application_event(&tauri::RunEvent::Ready,||called=true);
        assert!(!called);
        on_application_event(&tauri::RunEvent::Exit,||called=true);
        assert!(called);
    }

    #[test]
    fn job_cache_removes_stale_outputs_and_locks_against_other_instances() {
        let base=std::env::temp_dir().join(format!("paperwork-cache-test-{}",Uuid::new_v4()));
        fs::create_dir_all(base.join("jobs/stale")).unwrap();
        fs::write(base.join("jobs/stale/decrypted.txt"),b"test-only-private-output").unwrap();
        let cache=JobCache::open(&base).unwrap();
        assert!(!cache.root.join("stale").exists());
        assert!(JobCache::open(&base).is_err());
        let job=JobDirectory::new(&cache.root).unwrap();
        fs::write(job.path.join("output.txt"),b"test-only-output").unwrap();
        let path=job.path.clone();
        drop(job);
        assert!(!path.exists(),"failed jobs must be removed");
        let mut saved=JobDirectory::new(&cache.root).unwrap();
        saved.keep=true;
        let path=saved.path.clone();
        drop(saved);
        assert!(path.exists(),"successful outputs remain available for Save");
        cache.cleanup();
        assert!(!path.exists(),"normal app close removes successful job outputs");
        drop(cache);
        fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn cli_providers_ignore_unused_http_endpoint() {
        for provider in ["local", "llama.cpp", "whisper.cpp"] {
            for endpoint in ["https://remote.example/v1", "not a URL", "http://remote.example"] {
                assert!(!requires_cloud_consent(&json!({"provider":provider,"endpoint":endpoint})).unwrap());
            }
        }
    }

    #[test]
    fn network_providers_require_explicit_mode_and_operation_consent() {
        assert!(requires_cloud_consent(&json!({"provider":"ollama","endpoint":"https://remote.example"})).is_err());
        assert!(requires_cloud_consent(&json!({"provider":"openai-compatible","endpoint":"https://remote.example"})).is_err());
        assert!(requires_cloud_consent(&json!({"provider":"openai-compatible","endpoint":"https://remote.example","cloud_consent":true})).unwrap());
        assert!(requires_cloud_consent(&json!({"provider":"openai-compatible","endpoint":"http://remote.example","cloud_consent":true})).is_err());
        assert!(!requires_cloud_consent(&json!({"provider":"ollama"})).unwrap());
        assert!(!requires_cloud_consent(&json!({"provider":"ollama","endpoint":"http://[::1]:11434"})).unwrap());
    }

    #[test]
    fn network_provider_urls_cannot_expose_credentials_in_consent_dialog() {
        for endpoint in ["file:///private/file", "https://user:secret@remote.example", "https://remote.example/?key=secret", "https://remote.example/#secret", "http://localhost:0"] {
            assert!(requires_cloud_consent(&json!({"provider":"openai-compatible","endpoint":endpoint,"cloud_consent":true})).is_err());
        }
    }
}

fn main(){
    let self_testing=std::env::args().any(|a|a=="--worker-self-test");
    let app=tauri::Builder::default()
        .manage(NativeState::default())
        .setup(|app|{
            let cache=app.path().app_cache_dir()?;
            let cache=JobCache::open(&cache).map_err(std::io::Error::other)?;
            *app.state::<NativeState>().cache.lock().map_err(|_|std::io::Error::other("Job cache state is unavailable."))?=Some(cache);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![select_inputs,run_native_job,save_output,component_status,install_component])
        .build(tauri::generate_context!()).expect("Unable to start Paperwork Desktop");
    if self_testing {
        let result=self_test(app.handle());
        cleanup_application(app.handle());
        match result {Ok(value)=>println!("{value}"),Err(error)=>{eprintln!("{error}");std::process::exit(1);}}
        return;
    }
    app.run(|app,event|on_application_event(&event,||cleanup_application(app)));
}
