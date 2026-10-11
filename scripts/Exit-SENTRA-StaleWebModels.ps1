# Recovery only. Temporarily presents the LAST BUILT integration patch to the
# running SENTRA Desktop so its guarded Exit can restore the Codex route.
# NEVER starts or stops processes. Restores the development patch in finally.
# Do not use while another agent is editing sentra-upstream.patch.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repo 'integrations\codex_chatgpt_web\sentra-upstream.patch'
$payloadRoot = @(
    (Join-Path $repo 'web-models'),
    (Join-Path $repo 'dist\web-models')
) | Where-Object {
    Test-Path -LiteralPath (Join-Path $_ 'win-unpacked\Codex Web GPT.exe') -PathType Leaf
} | Select-Object -First 1
if (-not $payloadRoot) { throw 'No installed/packaged Web Models executable found. No files changed.' }
$packaged = Join-Path $payloadRoot 'licenses\codex-chatgpt-web\sentra-upstream.patch'
$manifest = Join-Path $payloadRoot 'integration-build.json'
foreach ($required in @($source, $packaged, $manifest)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing required file: $required. No files changed."
    }
}
$expected = [string]((Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).patch_sha256)
$packHash = (Get-FileHash -LiteralPath $packaged -Algorithm SHA256).Hash.ToLowerInvariant()
$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not $expected -or $expected.ToLowerInvariant() -ne $packHash) {
    throw 'Packaged patch does not match its build manifest; refusing temporary substitution.'
}
if ($sourceHash -eq $packHash) {
    throw 'Source and packaged patch already match; the refused Exit has a different cause.'
}
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 17842 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) { throw 'Gateway :17842 listener not found. No files changed.' }
$gatewayProcessId = [int]$listener.OwningProcess
$processInfo = Get-Process -Id $gatewayProcessId -ErrorAction Stop
if ($processInfo.ProcessName -notlike 'pythonw*') {
    throw 'Gateway is not owned by expected pythonw process; refusing workaround.'
}
$recoveryDir = Join-Path $repo '.sentra\recovery'
New-Item -ItemType Directory -Path $recoveryDir -Force | Out-Null
$backup = Join-Path $recoveryDir ('sentra-upstream-pre-exit-' + [guid]::NewGuid().ToString('N') + '.patch')
Copy-Item -LiteralPath $source -Destination $backup -ErrorAction Stop
if ((Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHash) {
    throw 'Backup verification failed. No files changed.'
}
$swapped = $false
$gatewayStopped = $false
try {
    $swapped = $true
    Copy-Item -LiteralPath $packaged -Destination $source -Force -ErrorAction Stop
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $packHash) {
        throw 'Temporary patch hash validation failed.'
    }
    Write-Host ''
    Write-Host 'TEMPORARY COMPATIBILITY RESTORED. Click Exit in the SENTRA tray NOW.' -ForegroundColor Yellow
    Write-Host 'Waiting up to 90 seconds for the Gateway to close normally; then the new development patch will be restored.'
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 750
        $stillListening = Get-NetTCPConnection -LocalPort 17842 -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.OwningProcess -eq $gatewayProcessId } |
            Select-Object -First 1
        if (-not $stillListening) {
            $gatewayStopped = $true
            break
        }
    }
} finally {
    if ($swapped) {
        $nowHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($nowHash -eq $packHash) {
            Copy-Item -LiteralPath $backup -Destination $source -Force -ErrorAction Stop
            $restoredHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($restoredHash -ne $sourceHash) {
                throw "FAILED to verify source restoration. Original backup remains at $backup"
            }
            Write-Host 'ORIGINAL DEVELOPMENT PATCH RESTORED and hash verified.' -ForegroundColor Green
        } else {
            Write-Warning "Source patch changed during recovery. Did NOT overwrite it. Original backup: $backup"
        }
    }
}
if ($gatewayStopped) {
    Write-Host 'Gateway :17842 closed. SENTRA Desktop Exit completed (or another controller shut it down).' -ForegroundColor Green
} else {
    Write-Warning 'Gateway still listening after 90s. Temporary patch was reverted. Read the Web Models status and retry only after diagnosis.'
}
Write-Host "Recovery backup kept locally at: $backup"
