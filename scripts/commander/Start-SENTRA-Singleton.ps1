param(
    [string]$StateDir = ".sentra",
    [string]$InstallDir = "."
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path $InstallDir).Path
$statePath = if ([IO.Path]::IsPathRooted($StateDir)) {
    [IO.Path]::GetFullPath($StateDir)
} else {
    [IO.Path]::GetFullPath((Join-Path $root $StateDir))
}
$tunnelJson = Join-Path $statePath "tunnel.json"
$legacyKey = Join-Path $statePath "tunnel\runtime-key.dpapi"
$profile = Join-Path $statePath "tunnel\profiles\sentra-local.yaml"
$bstr = [IntPtr]::Zero
$secure = $null

Push-Location $root
try {
    if (-not (Test-Path $tunnelJson)) {
        if (-not (Test-Path $legacyKey)) { throw "Legacy Runtime API key not found: $legacyKey" }
        if (-not (Test-Path $profile)) { throw "Tunnel profile not found: $profile" }
        $line = Select-String -Path $profile -Pattern '^\s*tunnel_id\s*:\s*(\S+)' | Select-Object -First 1
        if (-not $line) { throw "tunnel_id not found in sentra-local.yaml" }
        $tunnelId = $line.Matches[0].Groups[1].Value.Trim('"', "'")
        $encrypted = Get-Content $legacyKey -Raw
        $secure = ConvertTo-SecureString $encrypted
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        & python -B -m sentra_remote.run_cli --state-dir $statePath service configure-tunnel --install-dir $root --tunnel-id $tunnelId
        if ($LASTEXITCODE -ne 0) { throw "SENTRA tunnel configuration migration failed" }
    }

    Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue
    & python -B -m sentra_remote.run_cli --state-dir $statePath service restart-tunnel --install-dir $root
    if ($LASTEXITCODE -ne 0) { throw "SENTRA tunnel singleton restart failed" }
} finally {
    Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    if ($null -ne $secure) { $secure.Dispose() }
    Pop-Location
}
