"""Split a reviewed preview asset; the generated helper only reconstructs bytes.

Usage: python scripts/commander/preview_parts.py split --source Setup.exe
       --output-dir NEW_DIRECTORY [--part-bytes 1073741824]
No upload, installer execution, replacement or release authority is provided.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

DEFAULT_PART_BYTES = 1024 ** 3
MAX_PART_BYTES = 2 * 1024 ** 3 - 1
MAX_PARTS = 64
BUFFER_BYTES = 1024 ** 2
MANIFEST_NAME = "preview-parts.json"
HELPER_NAME = "Reassemble-Preview.ps1"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}


def _safe_name(value: str) -> str:
    if (not _NAME.fullmatch(value) or value.endswith(".")
            or value.split(".", 1)[0].upper() in _DEVICES):
        raise ValueError("unsafe asset basename")
    return value


def _absolute(value: str | Path) -> Path:
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("parent traversal is not accepted")
    return path.absolute()


def _no_links(path: Path) -> None:
    for entry in (*reversed(path.parents), path):
        info = entry.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)):
            raise ValueError("linked paths are not accepted")


def _stat_key(info: os.stat_result) -> tuple[int, ...]:
    # Windows path stat adds executable permission bits for .exe names, and
    # path/CRT fstat can synthesize ctime differently. These are the common
    # identity/content fields; compare full mode/ctime within each API below.
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_size, info.st_mtime_ns)


REASSEMBLY_HELPER = r'''param(
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [string]$ManifestPath = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Assert-SafeName([string]$Name) {
    if ($Name -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$' -or $Name.EndsWith('.') -or
        $Name.Split('.')[0] -imatch '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$') { throw 'Unsafe basename' }
}
function Assert-NoLinks([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        $entry = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Linked paths are forbidden' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
function Assert-Keys($Value, [string[]]$Keys) {
    if ($null -eq $Value -or @($Value.PSObject.Properties).Count -ne $Keys.Count) { throw 'Invalid manifest fields' }
    foreach ($key in $Keys) {
        if (@($Value.PSObject.Properties.Name | Where-Object { $_ -ceq $key }).Count -ne 1) { throw 'Invalid manifest fields' }
    }
}
function Assert-Integer($Value, [long]$Minimum, [long]$Maximum) {
    if (($Value -isnot [int] -and $Value -isnot [long]) -or $Value -lt $Minimum -or $Value -gt $Maximum) {
        throw 'Invalid manifest size or count'
    }
}
function Assert-Hash($Value) {
    if ($Value -isnot [string] -or $Value -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid SHA256' }
}
function Hash-Hex($Value) { return [BitConverter]::ToString($Value).Replace('-','').ToLowerInvariant() }
$temporary = $null
$temporaryOwned = $false
$output = $null
$joined = $null
try {
    if ([string]::IsNullOrEmpty($ManifestPath)) { $ManifestPath = Join-Path $PSScriptRoot 'preview-parts.json' }
    $manifestFile = [IO.Path]::GetFullPath($ManifestPath)
    Assert-NoLinks $manifestFile
    $manifestInfo = Get-Item -LiteralPath $manifestFile -Force
    if ($manifestInfo.PSIsContainer -or $manifestInfo.Length -gt 1048576) { throw 'Manifest is not a bounded file' }
    $manifest = [IO.File]::ReadAllText($manifestFile) | ConvertFrom-Json
    Assert-Keys $manifest @('schema_version','original','part_bytes','parts','reassembly_helper')
    Assert-Integer $manifest.schema_version 1 1
    Assert-Integer $manifest.part_bytes 1 2147483647
    if ($manifest.reassembly_helper -cne 'Reassemble-Preview.ps1') { throw 'Invalid helper identity' }
    Assert-Keys $manifest.original @('name','size_bytes','sha256')
    Assert-SafeName $manifest.original.name
    Assert-Hash $manifest.original.sha256
    Assert-Integer $manifest.original.size_bytes 0 137438953408
    if ($manifest.parts -isnot [array] -or $manifest.parts.Count -lt 1 -or $manifest.parts.Count -gt 64) { throw 'Invalid part count' }
    $expectedCount = [Math]::Max(1, [Math]::Ceiling($manifest.original.size_bytes / [double]$manifest.part_bytes))
    if ($manifest.parts.Count -ne $expectedCount) { throw 'Part count does not match original size' }
    $directory = [IO.Path]::GetDirectoryName($manifestFile)
    $names = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    [long]$total = 0
    for ($i = 0; $i -lt $manifest.parts.Count; $i++) {
        $part = $manifest.parts[$i]
        Assert-Keys $part @('name','size_bytes','sha256')
        Assert-SafeName $part.name
        Assert-Hash $part.sha256
        Assert-Integer $part.size_bytes 0 $manifest.part_bytes
        if (-not $names.Add($part.name)) { throw 'Duplicate part' }
        if ($part.name -cne ($manifest.original.name + ('.part{0:D4}' -f ($i + 1)))) { throw 'Unexpected part path or order' }
        $expectedSize = [Math]::Min([long]$manifest.part_bytes, [long]($manifest.original.size_bytes - $total))
        if ($part.size_bytes -ne $expectedSize) { throw 'Part size does not match original size' }
        $partPath = Join-Path $directory $part.name
        Assert-NoLinks $partPath
        $partInfo = Get-Item -LiteralPath $partPath -Force
        if ($partInfo.PSIsContainer -or $partInfo.Length -ne $part.size_bytes) { throw 'Part size mismatch' }
        $total += $part.size_bytes
    }
    if ($total -ne $manifest.original.size_bytes) { throw 'Original size mismatch' }
    $destination = [IO.Path]::GetFullPath($OutputPath)
    Assert-SafeName ([IO.Path]::GetFileName($destination))
    $parent = [IO.Path]::GetDirectoryName($destination)
    Assert-NoLinks $parent
    if (Test-Path -LiteralPath $destination) { throw 'Output already exists' }
    $temporary = Join-Path $parent ('.sentra-reassemble-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $output = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $temporaryOwned = $true
    $joined = [Security.Cryptography.SHA256]::Create()
    $buffer = New-Object byte[] 1048576
    foreach ($part in $manifest.parts) {
        $partPath = Join-Path $directory $part.name
        Assert-NoLinks $partPath
        $partStream = $null
        $hash = [Security.Cryptography.SHA256]::Create()
        try {
            $partStream = [IO.File]::Open($partPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            Assert-NoLinks $partPath
            if ($partStream.Length -ne $part.size_bytes) { throw 'Part size changed' }
            [long]$copied = 0
            while (($read = $partStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $copied += $read
                if ($copied -gt $part.size_bytes) { throw 'Part grew during read' }
                [void]$hash.TransformBlock($buffer, 0, $read, $buffer, 0)
                [void]$joined.TransformBlock($buffer, 0, $read, $buffer, 0)
                $output.Write($buffer, 0, $read)
            }
            [void]$hash.TransformFinalBlock([byte[]]@(), 0, 0)
            if ($copied -ne $part.size_bytes -or (Hash-Hex $hash.Hash) -cne $part.sha256) { throw 'Part SHA256 mismatch' }
        } finally {
            if ($null -ne $partStream) { $partStream.Dispose() }
            $hash.Dispose()
        }
    }
    [void]$joined.TransformFinalBlock([byte[]]@(), 0, 0)
    if ($output.Length -ne $manifest.original.size_bytes -or (Hash-Hex $joined.Hash) -cne $manifest.original.sha256) {
        throw 'Joined SHA256 or size mismatch'
    }
    $output.Flush($true)
    $output.Dispose()
    $output = $null
    # File.Move has no overwrite overload here, including on Windows PowerShell 5.1.
    [IO.File]::Move($temporary, $destination)
    $temporary = $null
    @{status='reassembled'; path=$destination; size_bytes=$total; sha256=$manifest.original.sha256} | ConvertTo-Json -Compress
} catch {
    [Console]::Error.WriteLine('Reassembly refused: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($null -ne $output) { $output.Dispose() }
    if ($null -ne $joined) { $joined.Dispose() }
    if ($temporaryOwned -and $null -ne $temporary -and [IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
}
'''


def _write_new(path: Path, content: bytes) -> None:
    with path.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def split_asset(source: str | Path, newoutputdir: str | Path,
                part_bytes: int = DEFAULT_PART_BYTES) -> dict:
    """Read a stable regular source into a new directory; never overwrite.

    A failed split leaves its new directory for inspection, without a manifest
    announcing a completed asset. The source and pre-existing files are read-only.
    """
    if type(part_bytes) is not int or not 1 <= part_bytes <= MAX_PART_BYTES:
        raise ValueError("part_bytes must be an integer between 1 and 2147483647")
    original, destination = _absolute(source), _absolute(newoutputdir)
    name = _safe_name(original.name)
    _safe_name(destination.name)
    if name.casefold() in {MANIFEST_NAME.casefold(), HELPER_NAME.casefold()} or len(name) > 150:
        raise ValueError("asset basename conflicts with metadata or part naming")
    _no_links(original)
    _no_links(destination.parent)
    before = original.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("source must be a regular file")
    count = max(1, (before.st_size + part_bytes - 1) // part_bytes)
    if count > MAX_PARTS:
        raise ValueError("asset exceeds the 64-part limit")
    destination.mkdir(exist_ok=False)
    parts = []
    joined = hashlib.sha256()
    with original.open("rb") as incoming:
        _no_links(original)
        opened = os.fstat(incoming.fileno())
        if _stat_key(before) != _stat_key(opened):
            raise RuntimeError("source identity changed before splitting")
        for index in range(count):
            part_name = f"{name}.part{index + 1:04d}"
            size = 0
            digest = hashlib.sha256()
            remaining = min(part_bytes, before.st_size - index * part_bytes)
            with (destination / part_name).open("xb") as outgoing:
                while remaining:
                    block = incoming.read(min(BUFFER_BYTES, remaining))
                    if not block:
                        raise RuntimeError("source shrank during splitting")
                    outgoing.write(block)
                    size += len(block)
                    remaining -= len(block)
                    digest.update(block)
                    joined.update(block)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            parts.append({"name": part_name, "size_bytes": size, "sha256": digest.hexdigest()})
        _no_links(original)
        after = original.stat()
        finished = os.fstat(incoming.fileno())
        if (incoming.read(1) or _stat_key(before) != _stat_key(finished)
                or _stat_key(before) != _stat_key(after) or before.st_mode != after.st_mode
                or before.st_ctime_ns != after.st_ctime_ns or opened.st_ctime_ns != finished.st_ctime_ns
                or opened.st_mode != finished.st_mode):
            raise RuntimeError("source changed during splitting")
    manifest = {"schema_version": 1, "original": {"name": name, "size_bytes": before.st_size,
        "sha256": joined.hexdigest()}, "part_bytes": part_bytes, "parts": parts,
        "reassembly_helper": HELPER_NAME}
    _write_new(destination / HELPER_NAME, REASSEMBLY_HELPER.encode("utf-8"))
    _write_new(destination / MANIFEST_NAME, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    return {"status": "split", "manifest_path": str(destination / MANIFEST_NAME),
            "helper_path": str(destination / HELPER_NAME), **manifest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("split", help="Split into a new directory, with verified reassembly helper")
    command.add_argument("--source", required=True, type=Path)
    command.add_argument("--output-dir", required=True, type=Path)
    command.add_argument("--part-bytes", type=int, default=DEFAULT_PART_BYTES)
    args = parser.parse_args(argv)
    try:
        result = split_asset(args.source, args.output_dir, args.part_bytes)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
