"""Local computer file and command executor, activated by an owner profile."""
from dataclasses import dataclass
from pathlib import Path
import base64
import hashlib
import os
import subprocess

from ._base import GuardedExecutor
from .rpa import effect_checkpoint

CAPABILITIES = ('computer:file.read', 'computer:file.write', 'computer:file.delete', 'computer:execute')

@dataclass(frozen=True)
class ComputerBinding:
    root: str
    timeout_seconds: float = 3610
    resolve_root: object = None

class LocalComputerExecutor(GuardedExecutor):
    kind = 'computer-local'

    def _validate(self, request, binding):
        args = dict(request.arguments)
        root=binding.resolve_root(request) if binding.resolve_root else Path(binding.root)
        if 'reason' in args and (not isinstance(args['reason'],str) or not 1<=len(args['reason'])<=300):raise ValueError('bounded explanation required')
        if request.capability_id == 'computer:execute':
            if set(args) - {'command', 'cwd', 'timeout_seconds','reason'} or not isinstance(args.get('command'), str) or not 1 <= len(args['command']) <= 100000:
                raise ValueError('command required')
            timeout = args.get('timeout_seconds', 120)
            if type(timeout) not in {int, float} or not 1 <= timeout <= 3600:
                raise ValueError('timeout must be 1..3600 seconds')
            args['timeout_seconds'] = timeout
            cwd=Path(args.get('cwd') or root)
            args['cwd'] = str((Path(root)/cwd).resolve() if not cwd.is_absolute() else cwd.resolve())
            return args
        action = args.get('action')
        allowed = {'computer:file.read': {'read', 'stat', 'list'}, 'computer:file.write': {'write', 'edit'}, 'computer:file.delete': {'delete'}}[request.capability_id]
        if action not in allowed or set(args) - {'action', 'path', 'content', 'base64', 'expected_sha256','reason'} or not isinstance(args.get('path'), str):
            raise ValueError('invalid file operation')
        path = Path(args['path'])
        args['path'] = str((Path(root) / path).resolve() if not path.is_absolute() else path.resolve())
        if action in {'write', 'edit'} and (('content' in args) == ('base64' in args)):
            raise ValueError('provide either text content or base64 bytes')
        return args

    def _execute(self, binding, args):
        effect_checkpoint()
        if 'command' in args:
            argv = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', args['command']] if os.name == 'nt' else ['/bin/sh', '-c', args['command']
            ]
            result = subprocess.run(argv, cwd=args['cwd'], capture_output=True, timeout=args['timeout_seconds'], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return {'exit_code': result.returncode, 'stdout': result.stdout[-262144:].decode('utf-8', errors='replace'), 'stderr': result.stderr[-262144:].decode('utf-8', errors='replace')}
        path, action = Path(args['path']), args['action']
        if action == 'list':
            return {'path': str(path), 'items': [{'name': p.name, 'directory': p.is_dir()} for p in list(path.iterdir())[:1000]]}
        if action == 'stat':
            return {'path': str(path), 'exists': path.exists(), 'bytes': path.stat().st_size if path.is_file() else None}
        if args.get('expected_sha256') and hashlib.sha256(path.read_bytes()).hexdigest() != args['expected_sha256']:
            raise ValueError('file changed since it was read')
        if action == 'read':
            data = path.read_bytes()
            try:
                value = {'content': data.decode('utf-8')}
            except UnicodeDecodeError:
                value = {'base64': base64.b64encode(data).decode()}
            return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), **value}
        if action == 'delete':
            path.unlink()
            return {'path': str(path), 'exists': path.exists()}
        data = args['content'].encode('utf-8') if 'content' in args else base64.b64decode(args['base64'], validate=True)
        effect_checkpoint()
        with path.open('xb' if action == 'write' else 'wb') as output:
            output.write(data)
        return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

def configure_computer(host, *, workspace_id, workspace_root, agent_id):
    from sentra_executors.central_integration import CentralExecutorFactory
    from sentra_executors.discovery import MachineDeclaration
    from sentra_runtime.contracts import Capability, Machine
    from sentra_canvas.shell_access import AccessStore
    root = str(Path(workspace_root).resolve(strict=True))
    mid = host._machine_id(workspace_id, agent_id, 'computer-local')
    if mid in host._inventory:
        return dict(host._inventory[mid])
    factory = CentralExecutorFactory(control=host.control, owner=host.owner, agent_id=agent_id)
    factory.policy = AccessStore(host.control, host.owner).policy(factory.policy, root)
    from sentra_canvas.task_workspace import directory
    resolve_root=lambda request:directory(host.control,host.owner,request,root)
    executor = LocalComputerExecutor(machine_id=mid, owner_principal_id=agent_id, bindings={cap: ComputerBinding(root,resolve_root=resolve_root) for cap in CAPABILITIES}, policy=factory.policy)
    factory.register_execution(MachineDeclaration(Machine(mid, 'computer-local', agent_id, tuple(Capability(cap, cap, 'high') for cap in CAPABILITIES)), executor))
    value = {'machine_id': mid, 'kind': 'computer-local', 'workspace_id': workspace_id, 'agent_id': agent_id, 'capabilities': list(CAPABILITIES), 'actions': {'computer:file.read': ['read', 'stat', 'list'], 'computer:file.write': ['write', 'edit'], 'computer:file.delete': ['delete'], 'computer:execute': ['execute']}, 'registered': True}
    host._factories[mid], host._inventory[mid] = factory, value
    host.configurations.put(mid, {'kind': 'computer-local', 'workspace_id': workspace_id, 'workspace_root': root, 'agent_id': agent_id})
    return dict(value)
