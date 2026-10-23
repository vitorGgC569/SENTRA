# Downloading a multipart Windows preview

GitHub limits each release asset to less than 2 GiB. A complete SENTRA setup
can exceed that size, so a preview may publish numbered parts instead of one
direct executable. See [GitHub's release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

## On the Windows computer

1. Open the identified preview release and download every part of the chosen
   artifact, `preview-parts.json` and `Reassemble-Preview.ps1` into one new folder.
2. Open PowerShell in that folder and run:

   ```powershell
   powershell.exe -NoProfile -File .\Reassemble-Preview.ps1 -OutputPath .\SENTRA-Setup-1.0.1.exe
   ```

3. The helper verifies every part and the complete reconstructed SHA-256. It
   refuses missing, changed, duplicated or unsafe paths and an existing output
   file. It does not start the installer. Open the resulting setup after the
   helper reports success.

Keep the parts of different artifacts/releases in separate folders. If Windows
blocks a downloaded script under the computer's execution policy, inspect the
script and use the machine's approved script execution procedure; rebuilding
the file does not require Python, Node or another archiver on the client.

The hash verifies downloaded bytes. It is separate from trusted Windows
publisher signing and clean-install qualification. Read the release notes for
the actual signature and acceptance status of that preview.

## Preparing parts from reviewed release outputs

```powershell
python scripts/commander/preview_parts.py split --source .\release\SENTRA-Setup-1.0.1.exe --output-dir .\new-setup-parts
```

The default part size is 1 GiB. The output directory must not exist. The command
emits a structured manifest with sizes and SHA-256 values and generates the
self-contained reassembly helper. It neither uploads nor publishes anything.
The original complete artifact remains the input for release acceptance and
signature checks; splitting does not change its bytes or qualify a release.
