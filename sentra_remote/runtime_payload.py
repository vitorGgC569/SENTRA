"""Installed runtime selection from build-embedded pins, never a workspace scan.

The packaging host embeds this record in each frozen executable. Its publisher
trust is the executable's release/signature chain, not an adjacent editable JSON
file or its checksum. These checks select bytes only; they issue no capability,
Grant, peer authentication or claim of an operationally verified component.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from types import MappingProxyType
from typing import Mapping
from .windows_paths import filesystem_path, resolved_path

PIN_RESOURCE = 'sentra-runtime-pins.json'
COMPONENTS = frozenset({'quickjs', 'hcs', 'rustdesk'})
_DIGEST = re.compile(r'[a-f0-9]{64}\Z')
_ROLES = {'quickjs': {'manifest', 'wasm', 'sbom'}, 'hcs': {'manifest', 'executable'},
          'rustdesk': {'manifest', 'build_manifest', 'executable'}}


class InstalledRuntimeUnavailable(RuntimeError):
    pass


def _relative(value, component):
    if (not isinstance(value, str) or not value or len(value) > 512 or '\\' in value or ':' in value
            or any(ord(char) < 32 for char in value)):
        raise ValueError('invalid installed runtime path')
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or any(part in {'.', '..'} or part[-1:] in {' ', '.'} for part in path.parts)
            or path.parts[:2] != ('runtime', component) or len(path.parts) < 3):
        raise ValueError('installed runtime path outside its component')
    return value


def validate_runtime_pins(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'components'} or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('invalid embedded runtime pin schema')
    components = value['components']
    if not isinstance(components, dict) or set(components) != COMPONENTS:
        raise ValueError('integral embedded runtime pins required')
    for name, component in components.items():
        if not isinstance(component, dict) or set(component) != {'files', 'entrypoints'}:
            raise ValueError('invalid embedded component descriptor')
        files, entries = component['files'], component['entrypoints']
        if not isinstance(files, dict) or not 1 <= len(files) <= 20000 or not isinstance(entries, dict) or set(entries) != _ROLES[name]:
            raise ValueError('bounded files and exact runtime entrypoints required')
        seen = set()
        for relative, digest in files.items():
            _relative(relative, name)
            if relative.casefold() in seen or not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
                raise ValueError('duplicate or unpinned runtime file')
            seen.add(relative.casefold())
        if any(not isinstance(path, str) or path not in files for path in entries.values()):
            raise ValueError('runtime entrypoint absent from embedded pins')
    return value


def _safe_file(root: Path, relative: str, *, maximum: int):
    target = root / relative
    for candidate in (target, *target.parents):
        raw = Path(filesystem_path(candidate, resolve=False))
        if raw.is_symlink() or getattr(raw, 'is_junction', lambda: False)():
            raise PermissionError('linked installed runtime file')
    if not Path(filesystem_path(target)).is_file() or not resolved_path(target, strict=True).is_relative_to(resolved_path(root, strict=True)):
        raise InstalledRuntimeUnavailable('installed runtime file missing')
    if Path(filesystem_path(target)).stat().st_size > maximum:
        raise ValueError('installed runtime file exceeds bound')
    return target


def _hash_file(path, maximum):
    digest = hashlib.sha256(); total = 0
    with Path(filesystem_path(path)).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            total += len(block)
            if total > maximum:
                raise ValueError('installed runtime file grew beyond bound')
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class InstalledComponent:
    root: Path
    files: Mapping[str, str]
    entrypoints: Mapping[str, str]

    def file(self, role: str, *, maximum: int = 512 * 1024 * 1024) -> Path:
        if role not in self.entrypoints or type(maximum) is not int or not 1 <= maximum <= 4 * 1024 ** 3:
            raise ValueError('known bounded runtime entrypoint required')
        relative = self.entrypoints[role]
        path = _safe_file(self.root, relative, maximum=maximum)
        if _hash_file(path, maximum) != self.files[relative]:
            raise PermissionError('installed runtime digest differs from embedded build pin')
        return path


def load_installed_component(name: str) -> InstalledComponent:
    """Frozen executables only. No environment, cwd, marker or sibling-pin fallback."""
    if name not in COMPONENTS:
        raise ValueError('unknown installed runtime component')
    if getattr(sys, 'frozen', False) is not True or not getattr(sys, '_MEIPASS', None):
        raise InstalledRuntimeUnavailable('embedded installed runtime pins unavailable in source mode')
    resource_root = Path(getattr(sys, "_MEIPASS")).absolute()
    resource = _safe_file(resource_root, PIN_RESOURCE, maximum=1024 * 1024)
    raw = resource.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError('embedded runtime pins exceed bound')
    component = validate_runtime_pins(json.loads(raw))['components'][name]
    root = Path(sys.executable).absolute().parent
    # Copy the descriptor so a caller cannot replace an entrypoint or digest.
    return InstalledComponent(root, MappingProxyType(dict(component['files'])),
                              MappingProxyType(dict(component['entrypoints'])))


def installed_hcs_configuration() -> dict:
    component = load_installed_component('hcs')
    component.file('manifest', maximum=1024 * 1024)
    executable = component.file('executable')
    return {'bridge_executable': str(executable),
            'bridge_sha256': component.files[component.entrypoints['executable']]}


def installed_rustdesk_configuration() -> dict:
    component = load_installed_component('rustdesk')
    component.file('manifest', maximum=1024 * 1024)
    executable = component.file('executable')
    manifest_path = component.file('build_manifest', maximum=65536)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    executable_sha256 = component.files[component.entrypoints['executable']]
    if (not isinstance(manifest, dict) or manifest.get('extension') != 'sentra-peer-gate-v1'
            or manifest.get('stock_cli_supported') is not False
            or manifest.get('executable_sha256') != executable_sha256
            or not isinstance(manifest.get('source_revision'), str)
            or not re.fullmatch('[a-f0-9]{40}', manifest['source_revision'])):
        raise ValueError('installed RustDesk instrumented build descriptor invalid')
    # The existing native_bundle path rechecks the complete pinned bundle and
    # copies its runtime bytes into private storage before registration.
    return {'executable': str(executable), 'executable_sha256': executable_sha256,
            'build_manifest': str(manifest_path), 'source_revision': manifest['source_revision']}
