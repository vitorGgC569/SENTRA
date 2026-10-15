"""Emit a reviewable native RustDesk source patch for a separately owned build.

Does not edit third_party, install software, compile, or claim a native runtime.
Stock executable cannot enforce the peer pin; it is intentionally unsupported.
"""
from pathlib import Path
import difflib
import hashlib
from .rpa import ExecutorFailure

PROFILE_SOURCE = 'libs/hbb_common/src/config.rs'
PROFILE_API = '''// SENTRA-owned session profile, installed before any lazy Config access.
// No environment lookup or mutable directory fallback in storage accessors.
#[derive(Debug, PartialEq)]
struct SentraOwnedProfile { root: PathBuf, ipc_scope: String }
static SENTRA_OWNED_PROFILE: std::sync::OnceLock<SentraOwnedProfile> = std::sync::OnceLock::new();

pub fn set_sentra_owned_profile(root: &Path, ipc_scope: &str) -> Result<()> {
    anyhow::ensure!(root.is_absolute(), "SENTRA profile must be absolute");
    anyhow::ensure!(ipc_scope.len() == 64 && ipc_scope.bytes().all(|ch| ch.is_ascii_hexdigit()),
                    "SENTRA IPC scope must be a session digest");
    let root = root.canonicalize()?;
    anyhow::ensure!(root.is_dir(), "SENTRA profile directory must exist");
    let profile = SentraOwnedProfile {root, ipc_scope: ipc_scope.to_owned()};
    if let Some(current) = SENTRA_OWNED_PROFILE.get() {
        anyhow::ensure!(current == &profile, "SENTRA profile cannot change after initialization");
        return Ok(());
    }
    for name in ["config", "log", "ipc"] {
        let directory = profile.root.join(name);
        fs::create_dir_all(&directory)?;
        anyhow::ensure!(directory.canonicalize()?.starts_with(&profile.root), "SENTRA profile escaped its root");
    }
    SENTRA_OWNED_PROFILE.set(profile).map_err(|_| anyhow!("SENTRA profile initialization raced"))?;
    Ok(())
}

fn sentra_config_path(p: &Path) -> Option<PathBuf> {
    let profile = SENTRA_OWNED_PROFILE.get()?;
    assert!(p.components().all(|part| matches!(part, std::path::Component::Normal(_) | std::path::Component::CurDir)),
            "SENTRA config path must stay relative to its owned profile");
    Some(profile.root.join("config").join(p))
}

#[cfg(test)]
mod sentra_owned_profile_contract {
    use super::*;
    #[test]
    fn native_config_log_and_ipc_are_isolated() {
        let stamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let root = std::env::temp_dir().join(format!("sentra-profile-contract-{}-{stamp}",std::process::id()));
        fs::create_dir(&root).unwrap();
        let default_config = Config::path("");
        let default_ipc = Config::ipc_path("");
        assert!(set_sentra_owned_profile(Path::new("relative-profile"),&"a".repeat(64)).is_err());
        assert!(set_sentra_owned_profile(&root,"bad-scope").is_err());
        set_sentra_owned_profile(&root,&"a".repeat(64)).unwrap();
        let root = root.canonicalize().unwrap();
        assert_eq!(Config::path(""),root.join("config"));
        assert_ne!(Config::path(""),default_config);
        assert_eq!(Config::log_path(),root.join("log"));
        assert_ne!(Config::ipc_path(""),default_ipc);
        assert!(Config::ipc_path("").contains(&"a".repeat(64)));
        assert!(std::panic::catch_unwind(||Config::path("../escape")).is_err());
        Config::set_option("sentra-profile-contract".into(),"isolated".into());
        assert!(root.join("config/RustDesk2.toml").is_file());
        assert!(set_sentra_owned_profile(&root,&"b".repeat(64)).is_err());
        assert_eq!(Config::path(""),root.join("config"));
        fs::remove_dir_all(root).unwrap();
    }
}

'''


def native_peer_gate_patch(source_root: str) -> dict:
    root=Path(source_root).resolve(strict=True)
    transformations={
        'src/lib.rs': [('pub mod core_main;','pub mod core_main;\npub mod sentra_peer_gate;')],
        'src/core_main.rs': [
            ('pub fn core_main() -> Option<Vec<String>> {',
             'pub fn core_main() -> Option<Vec<String>> {\n    crate::sentra_peer_gate::bootstrap();'),
            ('    crate::load_custom_client();','    crate::load_custom_client();\n    crate::sentra_peer_gate::configure_servers();'),
            ('    if _is_flutter_invoke_new_connection {',
             '    if let Some(args) = crate::sentra_peer_gate::owned_arguments() { return Some(args); }\n    #[cfg(feature = "flutter")]\n    if _is_flutter_invoke_new_connection {')],
        'flutter/windows/runner/main.cpp': [
            ('  if (hwnd != NULL) {',
             '  // Owned SENTRA native session must never delegate to an unrelated stock GUI.\n  if (hwnd != NULL && GetEnvironmentVariableW(L"SENTRA_RUSTDESK_CONFIG", NULL, 0) == 0) {')],
        'src/client/io_loop.rs': [
            ('                loop {\n                    tokio::select! {',
             '                let mut sentra_timer = crate::rustdesk_interval(time::interval(Duration::from_millis(50)));\n'
             '                loop {\n                    tokio::select! {\n'
             '                        _ = sentra_timer.tick(), if crate::sentra_peer_gate::enabled() => {\n'
             '                            if let Some(input) = crate::sentra_peer_gate::take_input() {\n'
             '                                let mut sent = false;\n'
             '                                if input.action == "login" {\n'
             '                                    self.handler.handle_login_from_ui(String::new(), String::new(), input.password.clone(), false, &mut peer).await;\n'
             '                                    sent = true;\n'
             '                                } else if self.is_connected {\n'
             '                                    let mut message = Message::new();\n'
             '                                    if input.action == "input.mouse" && input.x >= 0 && input.y >= 0 && input.x <= 8192 && input.y <= 8192 && input.mask >= 0 && input.mask <= 255 {\n'
             '                                        message.set_mouse_event(MouseEvent {mask:input.mask,x:input.x,y:input.y,..Default::default()});\n'
             '                                        sent = peer.send(&message).await.is_ok();\n'
             '                                    } else if input.action == "input.key" && input.keycode <= 65535 {\n'
             '                                        let mut key = KeyEvent {down:input.down,press:false,..Default::default()};\n'
             '                                        key.set_chr(input.keycode); message.set_key_event(key);\n'
             '                                        sent = peer.send(&message).await.is_ok();\n'
             '                                    }\n'
             '                                }\n'
             '                                crate::sentra_peer_gate::input_receipt(&input.operation_id,&input.action,sent);\n'
             '                            }\n'
             '                        }'),
            ('    async fn handle_msg_from_ui(&mut self, data: Data, peer: &mut Stream) -> bool {',
             '    async fn handle_msg_from_ui(&mut self, data: Data, peer: &mut Stream) -> bool {\n'
             '        if crate::sentra_peer_gate::enabled() && !matches!(&data, Data::Close) { return true; }'),
            ('                            self.handle_local_clipboard_msg(&mut peer, _msg).await;',
             '                            if !crate::sentra_peer_gate::enabled() { self.handle_local_clipboard_msg(&mut peer, _msg).await; }'),
            ('        if let Ok(msg_in) = Message::parse_from_bytes(&data) {',
             '        if let Ok(msg_in) = Message::parse_from_bytes(&data) {\n'
             '            if crate::sentra_peer_gate::enabled() && matches!(msg_in.union.as_ref(),\n'
             '                Some(message::Union::Clipboard(_)) | Some(message::Union::MultiClipboards(_)) |\n'
             '                Some(message::Union::Cliprdr(_)) | Some(message::Union::FileResponse(_)) |\n'
             '                Some(message::Union::FileAction(_)) | Some(message::Union::AudioFrame(_))) { return true; }'),
            ('                        let peer_version = pi.version.clone();',
             '                        crate::sentra_peer_gate::desktop_login();\n                        let peer_version = pi.version.clone();'),
            ('                        _ = status_timer.tick() => {',
             '                        _ = status_timer.tick() => {\n'
             '                            if self.is_connected { crate::sentra_peer_gate::desktop_login(); }'),
            ('                    handler.on_rgba(display, data);',
             '                    crate::sentra_peer_gate::capture_frame(display, data);\n                    handler.on_rgba(display, data);')],
        'src/client.rs':[
            ('        let rs_pk = get_rs_pk(if key.is_empty() {',
             '        crate::sentra_peer_gate::check_root(peer_id, key)?;\n        let rs_pk = get_rs_pk(if key.is_empty() {'),
            ('        let sign_pk = match sign_pk {',
             '        if crate::sentra_peer_gate::enabled() && sign_pk.is_none() { bail!("SENTRA requires verified rendezvous peer identity"); }\n        let sign_pk = match sign_pk {'),
            ('        match timeout(READ_TIMEOUT, conn.next()).await? {',
             '        crate::sentra_peer_gate::check_identity(peer_id, &sign_pk.0)?;\n        match timeout(READ_TIMEOUT, conn.next()).await? {'),
            ('        Ok(option_pk)\n    }',
             '        if crate::sentra_peer_gate::enabled() {\n            crate::sentra_peer_gate::verified(peer_id, option_pk.as_ref().ok_or_else(|| anyhow!("SENTRA peer key absent"))?, conn.is_secured())?;\n        }\n        Ok(option_pk)\n    }')]
    }
    transformations[PROFILE_SOURCE] = [
        ('pub const LINK_DOCS_HOME:', PROFILE_API+'pub const LINK_DOCS_HOME:'),
        ('    pub fn path<P: AsRef<Path>>(p: P) -> PathBuf {',
         '    pub fn path<P: AsRef<Path>>(p: P) -> PathBuf {\n'
         '        if let Some(path) = sentra_config_path(p.as_ref()) { return path; }'),
        ('    pub fn log_path() -> PathBuf {',
         '    pub fn log_path() -> PathBuf {\n'
         '        if let Some(profile) = SENTRA_OWNED_PROFILE.get() { return profile.root.join("log"); }'),
        ('    pub fn ipc_path(postfix: &str) -> String {',
         '    pub fn ipc_path(postfix: &str) -> String {\n'
         '        if let Some(profile) = SENTRA_OWNED_PROFILE.get() {\n'
         '            #[cfg(windows)]\n'
         '            return format!("\\\\\\\\.\\\\pipe\\\\SENTRA-RustDesk-{}\\\\query{}",profile.ipc_scope,postfix);\n'
         '            #[cfg(not(windows))]\n'
         '            return profile.root.join("ipc").join(format!("ipc{postfix}")).to_string_lossy().into_owned();\n'
         '        }'),
    ]
    patches=[];hashes={}
    for name,replacements in transformations.items():
        try:
            raw=(root/name).read_bytes()
        except FileNotFoundError as exc:
            code='rustdesk_native_patch_submodule_unavailable' if name==PROFILE_SOURCE else 'rustdesk_native_patch_source_unavailable'
            raise ExecutorFailure(code,evidence={'file':name}) from exc
        # Git's Windows checkout can use CRLF while the pinned patch anchors
        # use LF. Normalize only line endings, retaining the exact raw hash.
        old=raw.decode('utf-8').replace('\r\n','\n');new=old
        hashes[name]=hashlib.sha256(raw).hexdigest()
        for before,after in replacements:
            # A drifted/private API must be reviewed; never patch by a guessed line.
            if new.count(before)!=1:raise ExecutorFailure('rustdesk_native_patch_source_drift',evidence={'file':name})
            new=new.replace(before,after,1)
        patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
    module=Path(__file__).with_name('remote_rustdesk_gate.rs').read_text(encoding='utf-8')
    patches.extend(difflib.unified_diff([],module.splitlines(True),fromfile='/dev/null',tofile='b/src/sentra_peer_gate.rs'))
    return {'extension':'sentra-peer-gate-v1','control_extension':'sentra-desktop-control-v1',
            'patch':''.join(patches),'source_sha256':hashes,
            'compiled':False,'operational':False,'requires':'pinned native flutter RustDesk build and RustDesk server'}
