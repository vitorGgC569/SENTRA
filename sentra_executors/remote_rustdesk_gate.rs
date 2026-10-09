// Native instrumentation for an OWNED RustDesk build; not a RustDesk wire codec.
// Added to the pinned crate by remote_rustdesk_build.py; never applied to clone here.
use std::{env, fs, path::PathBuf, sync::OnceLock, time::{Duration, SystemTime, UNIX_EPOCH}};
use sha2::{Digest, Sha256};
use serde::Deserialize;

#[derive(Clone, Deserialize)]
struct Config {
    peer_id: String, peer_key_sha256: String, rendezvous_key: String,
    rendezvous_server: String, profile: String, receipt: String, lease: String,
    session_id: String, scope_sha256: String,
}
static CONFIG: OnceLock<Option<Config>> = OnceLock::new();
fn config() -> &'static Option<Config> {
    CONFIG.get_or_init(|| env::var("SENTRA_RUSTDESK_CONFIG").ok().map(|p| {
        let bytes=fs::read(p).expect("SENTRA native config unreadable");
        serde_json::from_slice(&bytes).expect("SENTRA native config malformed")
    }))
}
pub fn enabled() -> bool { config().is_some() }
fn lease_active(c: &Config) -> bool {
    let Ok(bytes)=fs::read(&c.lease) else { return false; };
    let Ok(v)=serde_json::from_slice::<serde_json::Value>(&bytes) else { return false; };
    let now=SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64;
    v["session_id"].as_str()==Some(c.session_id.as_str()) &&
    v["scope_sha256"].as_str()==Some(c.scope_sha256.as_str()) &&
    v["expires_unix_ms"].as_u64().map(|end| end>now && end<=now+5000).unwrap_or(false)
}
pub fn bootstrap() {
    let Some(c)=config().clone() else { return; };
    // A service/install child inheriting this environment must not recursively
    // turn itself into another owned GUI connection. This build owns one role.
    let args:Vec<String>=env::args().skip(1).collect();
    if args!=vec!["--connect".to_owned(),c.peer_id.clone()] { std::process::exit(93); }
    if !lease_active(&c) { std::process::exit(91); }
    // This is a native source addition, not a claim that stock CLI supports pinning.
    *hbb_common::config::APP_HOME_DIR.write().unwrap()=c.profile.clone();
    std::thread::spawn(move || loop {
        if !lease_active(&c) { std::process::exit(92); }
        std::thread::sleep(Duration::from_millis(100));
    });
}
pub fn owned_arguments() -> Option<Vec<String>> {
    config().as_ref().map(|c|vec!["--connect".into(),c.peer_id.clone()])
}
pub fn configure_servers() {
    if let Some(c)=config() {
        hbb_common::config::Config::set_option("custom-rendezvous-server".into(),c.rendezvous_server.clone());
        hbb_common::config::Config::set_option("key".into(),c.rendezvous_key.clone());
    }
}
pub fn check_root(peer_id:&str,key:&str) -> anyhow::Result<()> {
    if let Some(c)=config() {
        anyhow::ensure!(lease_active(c),"SENTRA native effect lease expired");
        anyhow::ensure!(peer_id==c.peer_id && key==c.rendezvous_key,"SENTRA configured peer/root mismatch");
    }
    Ok(())
}
pub fn check_identity(peer_id:&str,pk:&[u8]) -> anyhow::Result<()> {
    if let Some(c)=config() {
        anyhow::ensure!(lease_active(c),"SENTRA native effect lease expired");
        anyhow::ensure!(peer_id==c.peer_id && pk.len()==32,"SENTRA peer identity mismatch");
        anyhow::ensure!(hex::encode(Sha256::digest(pk))==c.peer_key_sha256,"SENTRA peer key pin mismatch");
    }
    Ok(())
}
pub fn verified(peer_id:&str,pk:&[u8],secured:bool) -> anyhow::Result<()> {
    check_identity(peer_id,pk)?;
    if let Some(c)=config() {
        anyhow::ensure!(secured,"SENTRA refuses unencrypted native fallback");
        let data=serde_json::json!({"extension":"sentra-peer-gate-v1","session_id":c.session_id,
            "scope_sha256":c.scope_sha256,"peer_id":peer_id,"peer_key_sha256":c.peer_key_sha256,
            "native_pid":std::process::id(),"peer_authenticated":true,
            "state":"PEER_VERIFIED","desktop_login_asserted":false});
        let path=PathBuf::from(&c.receipt);let tmp=path.with_extension("tmp");
        fs::write(&tmp,serde_json::to_vec(&data)?)?;
        // Receipt is first-write only. Duplicate/reconnect verification must not
        // overwrite a different process/session's evidence.
        match fs::hard_link(&tmp,&path) {
            Ok(()) => {},
            Err(error) if error.kind()==std::io::ErrorKind::AlreadyExists => {},
            Err(error) => return Err(error.into()),
        }
        let _=fs::remove_file(tmp);
    }
    Ok(())
}
