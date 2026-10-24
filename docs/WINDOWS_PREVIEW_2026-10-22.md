# Windows installer preview — October 22, 2026

## Source and artifact

- Tag: [`installer-preview-20261022-a8a525d`](https://github.com/vitorGgC569/SENTRA/tree/installer-preview-20261022-a8a525d).
- Source commit: `a8a525d0a2e7667a01ea055b38071c024d2e06ae`.
- Local folder: `C:\Users\vitor\Desktop\SENTRA-installer-preview-20261022-a8a525d`.
- Setup: `SENTRA-Setup.exe`, 3,150,031,357 bytes.
- SHA-256: `41720dd7c8850c712215fb6a932295bb858328fa4e4f8aa56b723163384a62f7`.

The annotated Git tag was pushed to origin. The installer is a local artifact;
no GitHub Release asset upload is claimed. It is an unsigned experimental
preview. Subsequent source changes are not included in this frozen artifact.

## Build

All fourteen application executables were built from source, followed by the
complete setup. The Web Models source/runtime build also completed, with 72
integration checks and nine saved-conversation checks passing. Its Electron
package, the main Desktop Electron runtime, validated native components and the
pinned offline registration prerequisite are included.

The build restored exact pinned terminal assets, normalized generated Desktop
HTML before sealing, and used LF-only upstream build worktrees. Node used the
Windows system CA store for downloads; TLS verification stayed enabled.

Build output and logs are under `.tmp/windows-preview-20261022/`. The final
Desktop folder contains the setup, installer/payload provenance manifests,
SHA256SUMS, setup integrity/GUI reports and `smoke-report.json`.

## Basic packaged validation

The second disposable smoke run passed:

- Embedded installer payload verification with `--check`, without installation.
- Frozen installer hidden GUI creation/destruction with `--gui-check`.
- Help commands for the packaged CLI, launcher and MCP server.
- Packaged Canvas broker startup with a new workspace/state directory.
- Authenticated health and byte hashes of the embedded Desktop JS, CSS and bootstrap.
- Shutdown of that test broker; existing installations and profiles were preserved.

The first smoke run correctly recorded failure because its PID assertion expected
the onefile launcher PID. PyInstaller's same-executable child owns the broker.
The second run checked the child's executable path and parent PID before accepting
its authenticated endpoint. No failed run was presented as a pass.

The reusable script is `tests/qa/windows_preview_smoke.py`. It requires a fresh
output directory and checks only the supplied build. A third run using that
committed script also passed, reproducing the same setup and embedded asset hashes:

```powershell
python tests/qa/windows_preview_smoke.py --dist .tmp/windows-preview-20261022/dist --output .tmp/windows-preview-20261022/smoke-new
```

This is not clean-machine installation, real account login, upgrade/rollback,
mobile-device, Authenticode or stable-release qualification. Those acceptance
criteria remain open in the SENTRA implementation tracker.
