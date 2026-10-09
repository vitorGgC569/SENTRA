"""Emit a reviewable native RustDesk source patch for a separately owned build.

Does not edit third_party, install software, compile, or claim a native runtime.
Stock executable cannot enforce the peer pin; it is intentionally unsupported.
"""
from pathlib import Path
import difflib
import hashlib
from .rpa import ExecutorFailure


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
    patches=[];hashes={}
    for name,replacements in transformations.items():
        raw=(root/name).read_bytes();old=raw.decode('utf-8');new=old
        hashes[name]=hashlib.sha256(raw).hexdigest()
        for before,after in replacements:
            # A drifted/private API must be reviewed; never patch by a guessed line.
            if new.count(before)!=1:raise ExecutorFailure('rustdesk_native_patch_source_drift',evidence={'file':name})
            new=new.replace(before,after,1)
        patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
    module=Path(__file__).with_name('remote_rustdesk_gate.rs').read_text(encoding='utf-8')
    patches.extend(difflib.unified_diff([],module.splitlines(True),fromfile='/dev/null',tofile='b/src/sentra_peer_gate.rs'))
    return {'extension':'sentra-peer-gate-v1','patch':''.join(patches),'source_sha256':hashes,
            'compiled':False,'operational':False,'requires':'pinned native flutter RustDesk build and RustDesk server'}
