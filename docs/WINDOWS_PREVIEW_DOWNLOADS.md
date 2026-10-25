# Downloading a multipart Windows preview

GitHub limits each release asset to less than 2 GiB. A complete SENTRA setup
can exceed that size, so a preview may publish numbered parts instead of one
direct executable. See [GitHub's release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

## On the Windows computer

1. Open the identified preview release and download every part of the chosen
   artifact, `preview-parts.json` and `Reassemble-Preview.ps1` into one new folder.
2. Open PowerShell in that folder and run:

   ```powershell
   powershell.exe -NoProfile -File .\Reassemble-Preview.ps1 -OutputPath .\SENTRA-Setup-1.0.5.exe
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

## If PowerShell scripts are restricted

Do not change the machine's execution policy for this preview. The same three
parts can be joined with Windows' built-in binary copy command. In a new folder
containing the 1.0.5 parts, first ensure the output does not already exist, then
run these commands interactively:

```powershell
if (Test-Path .\SENTRA-Setup-1.0.5.exe) { throw 'Output already exists' }
cmd.exe /d /c 'copy /b SENTRA-Setup-1.0.5.exe.part0001+SENTRA-Setup-1.0.5.exe.part0002+SENTRA-Setup-1.0.5.exe.part0003 SENTRA-Setup-1.0.5.exe'
Get-FileHash -Algorithm SHA256 .\SENTRA-Setup-1.0.5.exe
```

The complete SHA-256 must be
`7767c72b7f2ed157b650ad586e580a5e114665397f59207650fc27f31d6a54da`.
Stop if the copy reports an error or the hash differs. Do not open an unverified
or incomplete file. This alternative does not execute the downloaded helper.

## Recovering an earlier failed installation

After choosing the destination, select **Clean installation** on the
**Installation and recovery** page. Setup detects previous program components
and moves them to a sibling backup before replacing them. Projects,
conversations, accounts and unrelated files are preserved. The completion page
shows the backup location. Close active SENTRA sessions before continuing.

For damaged local settings alone, select **Recover damaged local settings**.
The invalid file is retained and recovered in Safe/workspace mode; valid
settings are preserved. Clean installation also enables this recovery when
needed. Both options are unchecked by default.

These recovery checks passed against private residue fixtures. Acceptance on
the previously failed PC and on a clean Windows OS still requires testing.

## Native main-window option

If the Electron window cannot open, the supported native main window can be
launched after installation in the default directory (use your chosen path for
a custom installation):

```powershell
& "$env:LOCALAPPDATA\SENTRA\Commander\sentra-canvas.exe" --ui native
```

Native mode does not enable or qualify the external activity bar. The preview
is unsigned and does not request disabling Windows protections.

## Preparing parts from reviewed release outputs

```powershell
python scripts/commander/preview_parts.py split --source .\release\SENTRA-Setup-1.0.5.exe --output-dir .\new-setup-parts
```

The default part size is 1 GiB. The output directory must not exist. The command
emits a structured manifest with sizes and SHA-256 values and generates the
self-contained reassembly helper. It neither uploads nor publishes anything.
The original complete artifact remains the input for release acceptance and
signature checks; splitting does not change its bytes or qualify a release.
