//! Optional-engine installation. Only version-pinned, embedded registry entries can be installed.
use serde::{Deserialize,Serialize};
use serde_json::{json,Value};
use sha2::{Digest,Sha256};
use std::{collections::HashMap,fs,io::{Read,Write},path::{Path,PathBuf},time::Duration};
use tauri::Manager;
use uuid::Uuid;

#[derive(Clone,Serialize)]
#[serde(rename_all="camelCase")]
pub struct ComponentStatus {pub id:String,pub name:String,pub installed:bool,pub version:Option<String>,pub description:String,pub download_bytes:Option<u64>,pub error:Option<String>}
#[derive(Clone,Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
struct Entry {id:String,name:String,version:String,platform:String,url:String,sha256:String,download_bytes:u64,license:String,executable:String}
#[derive(Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
struct Registry {schema_version:u32,components:Vec<Entry>}
const TOOLS:[(&str,&str,&str);7]=[("tesseract","Tesseract OCR","tesseract"),("libreoffice","LibreOffice conversion","soffice"),("ffmpeg","FFmpeg media processing","ffmpeg"),("whisper","whisper.cpp transcription","whisper-cli"),("llama","llama.cpp local AI","llama-cli"),("whisper_model","Whisper tiny English model",""),("llama_model","Local text model","")];
fn platform()->String{format!("{}-{}",std::env::consts::OS,std::env::consts::ARCH)}
fn registry()->Result<Vec<Entry>,String>{let data:Registry=serde_json::from_str(include_str!("../../components/registry.json")).map_err(|_|"The embedded component registry is invalid.")?;if data.schema_version!=1{return Err("This component registry version is unsupported.".into());}Ok(data.components.into_iter().filter(|e|e.platform==platform()).collect())}
fn root(app:&tauri::AppHandle)->Result<PathBuf,String>{app.path().app_data_dir().map(|p|p.join("components")).map_err(|_|"The component directory is unavailable.".into())}
fn system_tool(name:&str)->Option<PathBuf>{if name.is_empty(){return None;}let executable=if cfg!(windows){format!("{name}.exe")}else{name.to_owned()};std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()).filter(|p|p.is_absolute()).map(|p|p.join(&executable)).find(|p|p.is_file()).and_then(|p|p.canonicalize().ok())}
fn installed_path(app:&tauri::AppHandle,id:&str)->Option<PathBuf>{let index=root(app).ok()?.join(format!("{id}.json"));let data:Value=serde_json::from_slice(&fs::read(index).ok()?).ok()?;let relative=PathBuf::from(data.get("relativeExecutable")?.as_str()?);if !paperwork_security::safe_relative_path(&relative){return None;}let base=root(app).ok()?;let path=base.join(relative).canonicalize().ok()?;if !path.starts_with(base.canonicalize().ok()?)||!path.is_file(){return None;}Some(path)}
pub fn engine_paths(app:&tauri::AppHandle)->Result<HashMap<String,String>,String>{let mut paths=HashMap::new();for (id,_,binary) in TOOLS{if let Some(path)=installed_path(app,id).or_else(||system_tool(binary)){paths.insert(id.into(),path.to_string_lossy().into_owned());}}Ok(paths)}
pub fn status(app:&tauri::AppHandle)->Result<Vec<ComponentStatus>,String>{let entries=registry()?;let paths=engine_paths(app)?;Ok(TOOLS.into_iter().map(|(id,name,_)|{let entry=entries.iter().find(|e|e.id==id);let present=paths.contains_key(id);ComponentStatus{id:id.into(),name:name.into(),installed:present,version:entry.filter(|_|installed_path(app,id).is_some()).map(|e|e.version.clone()),description:if present{"Available locally. Model weights and OCR language data may be required separately.".into()}else if let Some(entry)=entry{format!("Optional {} download. License: {}. Requires your approval.",entry.version,entry.license)}else{"Not installed. A verified downloadable pack for this platform has not been published; an existing system installation can be detected.".into()},download_bytes:entry.map(|e|e.download_bytes),error:None}}).collect())}

pub fn install(app:&tauri::AppHandle,id:&str)->Result<ComponentStatus,String>{
    if !TOOLS.iter().any(|x|x.0==id){return Err("Unknown optional component.".into());}
    let entry=registry()?.into_iter().find(|e|e.id==id).ok_or("No verified component pack is published for this platform. Existing system engines can be used; no unverified executable will be downloaded.")?;
    let relative=Path::new(&entry.executable);
    if !paperwork_security::safe_relative_path(relative)||entry.sha256.len()!=64||!entry.sha256.bytes().all(|b|b.is_ascii_hexdigit())||entry.version.is_empty()||!entry.version.bytes().all(|b|b.is_ascii_alphanumeric()||b".-_".contains(&b)) {return Err("The component manifest failed validation.".into());}
    let url=reqwest::Url::parse(&entry.url).map_err(|_|"The component URL is invalid.")?;
    if url.scheme()!="https"||url.host_str()!=Some("github.com")||!url.path().starts_with("/ClawPick2026/paperwork-desktop/releases/download/"){return Err("This component source is not allowlisted.".into());}
    let approved=rfd::MessageDialog::new().set_title("Download optional processing engine?").set_description(format!("{} {}\nDownload: {} bytes\nLicense: {}\nSource: {}\nThe verified component will be stored in Paperwork's user data directory. No administrator access is requested.",entry.name,entry.version,entry.download_bytes,entry.license,entry.url)).set_buttons(rfd::MessageButtons::OkCancel).show();
    if approved!=rfd::MessageDialogResult::Ok{return Err("The component download was cancelled.".into());}
    let base=root(app)?;fs::create_dir_all(&base).map_err(|_|"The component cache could not be created.")?;
    let staging=base.join(format!(".install-{}",Uuid::new_v4()));fs::create_dir(&staging).map_err(|_|"The download staging directory could not be created.")?;
    let result=(||{
        let client=reqwest::blocking::Client::builder().timeout(Duration::from_secs(900)).redirect(reqwest::redirect::Policy::limited(5)).build().map_err(|_|"The download client could not start.")?;
        let mut response=client.get(&entry.url).send().map_err(|_|"The component download failed.")?.error_for_status().map_err(|_|"The component server rejected the download.")?;
        let archive=staging.join("download.zip");let mut file=fs::File::create(&archive).map_err(|_|"The component archive could not be created.")?;let mut hash=Sha256::new();let mut count=0u64;let mut buffer=[0u8;65536];
        loop{let size=response.read(&mut buffer).map_err(|_|"The download was interrupted.")?;if size==0{break;}count+=size as u64;if count>750*1024*1024||count>entry.download_bytes{return Err("The component exceeds its expected download size.".into());}hash.update(&buffer[..size]);file.write_all(&buffer[..size]).map_err(|_|"The component could not be saved.")?;}
        drop(file);if count!=entry.download_bytes||format!("{:x}",hash.finalize())!=entry.sha256.to_lowercase(){return Err("Component verification failed. The size or SHA-256 checksum does not match.".into());}
        let mut zip=zip::ZipArchive::new(fs::File::open(&archive).map_err(|_|"The archive could not be opened.")?).map_err(|_|"The component is not a valid ZIP archive.")?;
        if zip.len()>20000{return Err("The archive contains too many entries.".into());}let extracted=staging.join("files");fs::create_dir(&extracted).map_err(|_|"The extraction directory could not be created.")?;let mut bytes=0u64;
        for index in 0..zip.len(){let mut item=zip.by_index(index).map_err(|_|"An archive entry could not be read.")?;let path=Path::new(item.name());if !paperwork_security::safe_relative_path(path)||item.unix_mode().map(|m|m&0o170000==0o120000).unwrap_or(false){return Err("The archive contains an unsafe path or symbolic link.".into());}bytes=bytes.checked_add(item.size()).ok_or("The archive size overflowed.")?;if bytes>2*1024*1024*1024{return Err("The extracted component exceeds 2 GiB.".into());}let target=extracted.join(path);if item.is_dir(){fs::create_dir_all(&target).map_err(|_|"An archive directory could not be created.")?;}else{if let Some(parent)=target.parent(){fs::create_dir_all(parent).map_err(|_|"An archive directory could not be created.")?;}let mut output=fs::OpenOptions::new().create_new(true).write(true).open(&target).map_err(|_|"An archive output is duplicated or unavailable.")?;std::io::copy(&mut item,&mut output).map_err(|_|"Component extraction failed.")?;}}
        let executable=extracted.join(&entry.executable);if !executable.is_file(){return Err("The verified component executable is missing from its archive.".into());}
        #[cfg(unix)] {use std::os::unix::fs::PermissionsExt;fs::set_permissions(&executable,fs::Permissions::from_mode(0o700)).map_err(|_|"The component executable permissions could not be set.")?;}
        let folder=format!("{}-{}-{}",entry.id,entry.version,Uuid::new_v4());fs::rename(&extracted,base.join(&folder)).map_err(|_|"The component installation could not be finalized.")?;
        let relative=PathBuf::from(folder).join(&entry.executable);let index=base.join(format!("{}.json",entry.id));let temporary=base.join(format!(".{}.json",Uuid::new_v4()));fs::write(&temporary,json!({"version":entry.version,"relativeExecutable":relative}).to_string()).map_err(|_|"The component record could not be saved.")?;
        if cfg!(windows)&&index.exists(){fs::remove_file(&index).map_err(|_|"The previous component record could not be replaced.")?;}fs::rename(temporary,index).map_err(|_|"The component record could not be finalized.")?;
        status(app)?.into_iter().find(|s|s.id==id).ok_or_else(||"The installed component could not be found.".into())
    })();let _=fs::remove_dir_all(staging);result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn registry_supports_separately_consented_model_data_without_path_search() {
        for id in ["whisper_model","llama_model"] {
            let entry=TOOLS.iter().find(|entry|entry.0==id).expect("optional model must be available in component status and installer");
            assert!(entry.2.is_empty(),"model weights are not PATH executables");
        }
    }
}
