$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $root 'SETUP-SHA256.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Baixe SETUP-SHA256.json e todas as partes.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.source_commit -ne '42870dcd50a2476b2f3b52b3c36bd27d86f9496c') { throw 'Manifesto de outra versao.' }
if ([IO.Path]::GetFileName([string]$manifest.filename) -ne [string]$manifest.filename) { throw 'Nome invalido no manifesto.' }
$out = Join-Path $root ([string]$manifest.filename)
if (Test-Path -LiteralPath $out) { throw 'O Setup ja existe. Nao vou sobrescrever.' }
if (-not $manifest.parts -or $manifest.parts.Count -lt 1) { throw 'Nenhuma parte declarada.' }
foreach ($part in $manifest.parts) {
    if ([IO.Path]::GetFileName([string]$part.name) -ne [string]$part.name) { throw 'Nome de parte invalido.' }
    $source = Join-Path $root ([string]$part.name)
    if (-not (Test-Path -LiteralPath $source)) { throw "Arquivo faltando: $($part.name)" }
    if ((Get-Item -LiteralPath $source).Length -ne [long]$part.bytes) { throw "Tamanho invalido: $($part.name)" }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne ([string]$part.sha256).ToLowerInvariant()) { throw "Hash invalido: $($part.name)" }
}
$dst = [IO.File]::Create($out)
try {
    foreach ($part in $manifest.parts) {
        $src = [IO.File]::OpenRead((Join-Path $root ([string]$part.name)))
        try { $src.CopyTo($dst) } finally { $src.Dispose() }
    }
} finally { $dst.Dispose() }
if ((Get-Item -LiteralPath $out).Length -ne [long]$manifest.bytes -or
    (Get-FileHash -LiteralPath $out -Algorithm SHA256).Hash.ToLowerInvariant() -ne ([string]$manifest.sha256).ToLowerInvariant()) {
    Remove-Item -LiteralPath $out -Force
    throw 'O instalador reconstituido nao corresponde ao SHA-256 aprovado.'
}
Write-Host "OK: Setup reconstituido e verificado: $out" -ForegroundColor Green
Write-Host 'Antes de executar, valide o ambiente Windows de teste e leia as notas da release.'
