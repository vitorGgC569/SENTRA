"""Protected, single-use host handoff to the real coordinated update helper."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from sentra_core.conversations import _encode, _decode


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def assert_installation_offline(install_dir):
    """Real process observation; never signals a process or releases a PTY."""
    if os.name != 'nt':
        raise RuntimeError('coordinated Windows updates require Windows process evidence')
    script = "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, text=True, timeout=15, check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    rows = json.loads(result.stdout or '[]')
    rows = rows if isinstance(rows, list) else [rows]
    root = Path(install_dir).resolve(strict=True)
    names = {p.name.casefold() for p in root.glob('*.exe')}
    for row in rows:
        executable = row.get('ExecutablePath')
        if not executable and str(row.get('Name', '')).casefold() in names:
            raise RuntimeError('installed process identity cannot be observed; defer update')
        if executable and Path(executable).resolve().is_relative_to(root):
            raise RuntimeError('installed process still alive; defer update without stopping it')


def load_handoff(path, install_dir):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 131072:
        raise PermissionError('unsafe coordinated update handoff')
    value = _decode(path.read_text(encoding='utf-8'))
    root = Path(install_dir).resolve(strict=True)
    marker = json.loads((root / '.sentra-install.json').read_text(encoding='utf-8'))
    if (value.get('schema') != 1 or value.get('install_dir') != str(root) or
            value.get('installation_id') != marker.get('installation_id') or
            value.get('expires_at', 0) <= time.time() or value.get('admin_quiesced') is not True or
            value.get('conpty_handles') != [] or not value.get('owner') or not value.get('operation_id')):
        raise PermissionError('coordinated update identity/offline handoff invalid')
    for field, digest in [('installer','installer_sha256'), ('backup_manifest','backup_manifest_sha256')]:
        target = Path(value[field])
        if target.is_symlink() or not target.is_file() or _sha(target) != value[digest]:
            raise PermissionError('coordinated update artifact changed')
    from .updater import verify_authenticode
    verify_authenticode(Path(value['installer']), value['signer_thumbprint'])
    assert_installation_offline(root)
    context = helper_effect_context(value)
    context.checkpoint()
    return value


def helper_effect_context(value):
    """Reopen the selected CP and reuse its exact receipt and persisted grant."""
    from sentra_mcp.services.control_plane import ControlPlaneService
    from sentra_runtime.central_authority import CentralDurableIntentAuthority
    from sentra_runtime.contracts import OperationRequest, PolicyDecision
    from sentra_runtime.durable_admission import IntentReceipt
    from sentra_runtime.effect_boundary import CentralEffectContext
    admission = value.get('admission')
    if not isinstance(admission, dict) or not admission.get('grant_id'):
        raise PermissionError('root-composed central effect receipt and grant required')
    control = ControlPlaneService.from_store(Path(value['state_root']), backend='configured')
    if (control.store.backend != value['authority']['backend'] or
        getattr(control.store, 'tenant_id', 'local') != value['tenant_id']):
        raise PermissionError('update authority selection changed after staging')
    request = OperationRequest(**admission['request'])
    receipt = IntentReceipt(**admission['receipt'])
    if request.operation_id != value['operation_id'] or receipt.owner != value['owner']:
        raise PermissionError('update handoff central intent identity mismatch')
    authority = CentralDurableIntentAuthority(control.durable, ttl_s=60, budgets=control.budgets)
    def authorize(candidate):
        query = admission['authorization']
        if not isinstance(query, dict) or set(query) - {'principal_type', 'principal_id', 'capability', 'scope_type', 'scope_id', 'context'}:
            return PolicyDecision(False, 'invalid host authorization query')
        if query.get('principal_id') != candidate.principal_id or query.get('capability') != candidate.capability_id:
            return PolicyDecision(False, 'update authorization differs from immutable central request')
        decision = control.authorization.authorize(value['owner'], **query, local_owner=False)
        return PolicyDecision(decision.get('allowed') is True and decision.get('grant_id') == admission['grant_id'],
                              'existing central update grant rechecked')
    return CentralEffectContext(authority, receipt, request, authorize)


def write_helper_outcome(path, value, *, state, result):
    """Helper receipt is evidence for root reconciliation, not a new authority."""
    path = Path(path)
    record = {'schema':1,'owner':value['owner'],'installation_id':value['installation_id'],
        'operation_id':value['operation_id'],'handoff_sha256':_sha(path),'state':state,
        'helper_pid':os.getpid(),'result':result,'created_at':time.time()}
    target = path.with_suffix('.outcome.protected')
    with target.open('x',encoding='utf-8') as out:
        out.write(_encode(record));out.flush();os.fsync(out.fileno())
    return record


def read_helper_outcome(path, *, owner, operation_id, installation_id):
    path = Path(path)
    target = path.with_suffix('.outcome.protected')
    if target.is_symlink() or not target.is_file():
        return {'state':'UNCERTAIN','operation_id':operation_id}
    value = _decode(target.read_text(encoding='utf-8'))
    if any(value.get(k) != v for k,v in {'owner':owner,'operation_id':operation_id,
        'installation_id':installation_id,'handoff_sha256':_sha(path)}.items()):
        raise PermissionError('update helper evidence binding mismatch')
    return value


def verify_installed_components(root, components):
    root = Path(root).resolve(strict=True)
    from native_bridge.bootstrap import extension_identity
    extension = extension_identity(root / 'edge_extension')
    expected = components.get('extension')
    if not isinstance(expected,dict) or any(extension[k] != expected[k] for k in ('version','build_id','source_hash')):
        raise RuntimeError('installed extension differs from the coordinated release')
    gateway = components.get('gateway') or {}
    if _sha(root / 'web-models' / 'integration-build.json') != gateway.get('sha256'):
        raise RuntimeError('installed WebModels differs from the coordinated release')
    for component in components.get('runtime_components',{}).values():
        for item in component['files']:
            path = root / item['path']
            if path.is_symlink() or not path.resolve().is_relative_to(root) or _sha(path) != item['sha256']:
                raise RuntimeError('installed runtime component digest mismatch')


def schedule_on_exit(*, control, owner, operation_id, installation_id, state_root,
                     install_dir, prepared, conpty_handles, checkpoint):
    """Called inside the already reserved facade effect, never by a renderer."""
    if not isinstance(prepared, dict) or conpty_handles != []:
        raise PermissionError('trusted prepared release and empty ConPTY inventory required')
    root = Path(install_dir).resolve(strict=True)
    package = Path(prepared['package_root']).resolve(strict=True)
    installer = Path(prepared['installer']).resolve(strict=True)
    helper = package / 'sentra-update-helper.exe'
    if package.is_relative_to(root) or not installer.is_relative_to(package) or not helper.is_file():
        raise PermissionError('update helper/package must live outside the installed program tree')
    operation = control.durable.operation_status(operation_id, owner)
    if operation['state'] not in {'RUNNING','STARTING'}:
        raise PermissionError('update handoff is not bound to an active central operation')
    components = prepared.get('components')
    if (not isinstance(components, dict) or not {'extension', 'gateway', 'runtime_components'} <= components.keys()
        or set(components['runtime_components']) != {'quickjs', 'hcs', 'rustdesk'}):
        raise ValueError('complete coordinated release component manifest required')
    admission = prepared.get('admission')
    if not isinstance(admission, dict) or not admission.get('grant_id'):
        raise PermissionError('root-composed handoff of the existing central effect admission required')
    from .updater import _installed_signer_thumbprint, verify_authenticode
    signer = _installed_signer_thumbprint()
    verify_authenticode(installer, signer); verify_authenticode(helper, signer)
    backup = Path(prepared['backup_manifest']).resolve(strict=True)
    if _sha(backup) != prepared['backup_manifest_sha256']:
        raise PermissionError('C09 backup manifest changed')
    # Schema changes require the native authority migration's completed receipt.
    if prepared.get('schema_changed'):
        if prepared.get('schema_backward_compatible') is not True:
            raise PermissionError('app-exit program rollback requires a reviewed backward-compatible schema')
        migration = control.durable.operation_status(prepared['schema_operation_id'], owner)
        if migration['state'] != 'SUCCEEDED':
            raise PermissionError('native authority schema migration receipt required')
    directory = Path(state_root).resolve(strict=True) / 'app-exit-updates'
    checkpoint(); directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256((owner+'\0'+operation_id).encode()).hexdigest() + '.protected')
    if path.exists():
        raise RuntimeError('update handoff already reserved; observe helper outcome, never relaunch')
    record = {'schema':1,'owner':owner,'tenant_id':getattr(control.store,'tenant_id','local'),
        'installation_id':installation_id,'operation_id':operation_id,'install_dir':str(root),
        'state_root':str(Path(state_root).resolve()),'installer':str(installer),'installer_sha256':_sha(installer),
        'backup_manifest':str(backup),'backup_manifest_sha256':prepared['backup_manifest_sha256'],
        'signer_thumbprint':signer,'version':prepared['version'],'expires_at':time.time()+3600,
        'admin_quiesced':True,'conpty_handles':[],'manifest_url':prepared.get('manifest_url',''),
        'components':components, 'admission':admission,
        'authority':{'backend':control.store.backend}}
    helper_effect_context(record).checkpoint()
    checkpoint()
    with path.open('x',encoding='utf-8') as out:
        out.write(_encode(record));out.flush();os.fsync(out.fileno())
    checkpoint()
    process = subprocess.Popen([str(helper),'apply','--installer',str(installer),'--install-dir',str(root),
        '--state-dir',record['state_root'],'--parent-pid',str(os.getpid()),'--version',record['version'],
        '--manifest-url',record['manifest_url'],'--handoff-file',str(path)],
        cwd=package,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return {'phase':'HELPER_WAITING_FOR_APP_EXIT','pid':process.pid,'handoff_sha256':_sha(path),
            'operation_id':operation_id,'apply_on':'app_exit','decision':'scheduled'}
