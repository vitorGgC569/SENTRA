// Native release-library probe, not a mock of RustDesk storage accessors.
// build_rustdesk.py links this against the candidate's actual hbb_common rlib.
extern crate hbb_common;

use hbb_common::config::{set_sentra_owned_profile, Config};
use std::{env, fs, path::PathBuf};

fn main() {
    let root = PathBuf::from(env::args().nth(1).expect("owned test profile required"));
    let scope = env::args().nth(2).expect("owned test session digest required");
    let previous = Config::path("RustDesk2.toml");
    let unchanged = || fs::metadata(&previous).ok().map(|m| (m.len(), m.modified().unwrap()));
    let before = unchanged();

    assert!(set_sentra_owned_profile(&PathBuf::from("relative"), &scope).is_err());
    assert!(set_sentra_owned_profile(&root, "invalid-scope").is_err());
    set_sentra_owned_profile(&root, &scope).unwrap();
    let root = root.canonicalize().unwrap();
    assert_eq!(Config::path(""), root.join("config"));
    assert_eq!(Config::log_path(), root.join("log"));
    assert!(Config::ipc_path("").starts_with(r"\\.\pipe\SENTRA-RustDesk-"));
    assert!(Config::ipc_path("").contains(&scope));

    Config::set_option("sentra-profile-contract".to_owned(), "isolated".to_owned());
    assert!(root.join("config/RustDesk2.toml").is_file());
    assert!(set_sentra_owned_profile(&root, &"c".repeat(64)).is_err());
    assert_eq!(before, unchanged());

    if env::args().nth(3).as_deref() == Some("escape") {
        // Release dependencies use panic=abort. The driver checks the exact
        // guard message and abnormal exit in this separate owned subprocess.
        let escaped = Config::path("../../escaped-profile.txt");
        fs::write(escaped, b"unexpected escape from owned profile").unwrap();
        std::process::exit(99);
    }
    println!("profile-config-log-ipc-isolated");
}
