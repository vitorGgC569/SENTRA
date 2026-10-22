# Native workspace fixture

The fixture uses the current renderer with synthetic local state. It does not
load an installed account or send a model request. Keep its browser sandbox,
isolation settings and assertions enabled.

From `sentra_canvas/desktop_ui`, start an owned development server in one
terminal (choose an unused port; `--strictPort` refuses a collision):

```powershell
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5317 --strictPort --base /
```

In a second terminal at the same directory, run the repository Electron binary:

```powershell
$qaOutput = Join-Path $env:TEMP ('sentra-workspace-qa-' + [guid]::NewGuid().ToString('N'))
& '..\..\sentra_electron\node_modules\electron\dist\electron.exe' '.\test\workspace-ux.cjs' '--fixture-target=http://127.0.0.1:5317/test/workspace-ux.html' "--fixture-output=$qaOutput" "--user-data-dir=$qaOutput\chromium-bootstrap"
```

The two required options are `--fixture-target=...` and `--fixture-output=...`.
Do not pass a URL as a positional native argument: on the tested Windows
Electron44 runtime that exited with0xFFFFFFFF before application JavaScript.
Named options passed the real renderer assertions without changing the
application's URL parser or sandbox. File targets retain their existing offline
behavior. Missing, duplicate or empty fixture options are rejected.

Success creates `result.json` and screenshots in the new output directory and
exits0. Failures create `error.txt` when application JavaScript was reached.
Stop only the development server started for this fixture. Retain evidence
until review; do not reuse the QA profile for installed-product acceptance.

If the host process context modifies loopback traffic, use the same normal-user
Windows test runner approved for the repository's physical QA; preserve the
test arguments and assertions. A new frozen installer still requires its own
install/runtime/rollback and independent release evidence.
