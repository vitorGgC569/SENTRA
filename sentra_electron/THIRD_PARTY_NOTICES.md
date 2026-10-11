# SENTRA Electron display — provenance

Design and security review references: Chat On Steroids 2.1.31,
https://github.com/totec448-spec/chat-on-steroids, commit 151e7ef,
MIT license. This implementation does **not** bundle or execute the upstream
Electron application or its privileged main process. It renders SENTRA's own
Canvas with no Electron IPC tool/OS authority; Electron is a display only.
The original upstream tree and LICENSE remain in third_party/chat-on-steroids.
Electron itself and transitive dependencies retain their own notices/licenses.
