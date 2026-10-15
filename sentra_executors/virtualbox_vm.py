"""Owned VirtualBox VMs, unattended local ISO install and real COM framebuffer.

No host desktop capture, paid extension, dependency installation or OS download.
Every physical action is consumed through the central guarded executor.
"""
from dataclasses import dataclass, field
from contextlib import contextmanager
from pathlib import Path
import base64
import hashlib
import json
import os
import re
import subprocess
import time

from ._base import GuardedExecutor
from .rpa import effect_checkpoint, ExecutorFailure

VM_CAPABILITIES = ('vm:observe', 'vm:manage', 'vm:input', 'vm:guest')
VM_ACTIONS = {'vm:observe': ('status', 'frame', 'diagnostics', 'installation.plan', 'storage.candidate'),
    'vm:manage': ('provision', 'start', 'shutdown', 'pause', 'resume', 'restart', 'installation.boot_disk', 'installation.prepare', 'installation.launch', 'installation.reconcile', 'installation.advance', 'resource.cap', 'storage.enroll'),
    'vm:input': ('input.key', 'input.mouse', 'input.bios_dvd'), 'vm:guest': ('guest.run', 'installation.verify', 'project.import', 'project.import.reconcile')}
# Published on the shell bridge. The desktop button is Lumen's; this contract
# does not draw one and does not claim a physical install or a guest copy.
NEXT_AUTHORIZED_GUEST_STEP = {
    'action': 'installation.verify', 'route': 'dot_vm_execute', 'capability': 'vm:guest',
    'arguments': ['action'], 'screen_button': False, 'emits_credentials': False,
    'credential_source': 'stored VM record',
    'depends_on': [
        'vm:guest grant on the Dot work item',
        'running owned guest',
        'Guest Additions command channel',
        'new central operation distinct from any unfinished imports/*.tar',
    ],
    'must_not': [
        'installation.launch', 'installation.prepare', 'resend launch-intent.json',
        'copy or delete an imports tar that has no succeeded receipt',
        'delete VM, VDI, or Dot',
    ],
    'after_verify': {
        'action': 'project.import',
        'requires': ['explicit host_folder', 'new request_key', 'installed_os_verified from this verify'],
    },
}
BRIDGE_INTERFACE = {
    'installation.advance': {
        'route': 'dot_vm_execute', 'capability': 'vm:manage', 'arguments': ['confirm_launch'],
        'screen_button': False, 'replays_launch_intent': False, 'physical_proof': False,
    },
    'installation.verify': {
        'route': 'dot_vm_execute', 'capability': 'vm:guest', 'arguments': ['action'],
        'screen_button': False, 'emits_credentials': False, 'physical_proof': False,
        'credential_source': 'stored VM record',
    },
    'project.import': {
        'route': 'dot_vm_execute', 'capability': 'vm:guest',
        'arguments': ['relative_path', 'host_folder', 'request_key'],
        'screen_button': False, 'replays_duplicate_operation': False, 'physical_proof': False,
    },
}


def bridge_capability(action):
    """Map a bridge argument to the capability that already admits it."""
    if isinstance(action, str):
        for capability, actions in VM_ACTIONS.items():
            if action in actions:
                return capability
    return None


def executable():
    import shutil
    found = shutil.which('VBoxManage.exe') or shutil.which('VBoxManage')
    candidate = Path(found or r'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe')
    return str(candidate.resolve()) if candidate.is_file() else None


def machine_readable(text):
    result = {}
    for line in text.splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key.startswith('"'):
            try:
                key = json.loads(key)
            except ValueError:
                pass
        try:
            result[key] = json.loads(value)
        except ValueError:
            result[key] = value.strip('"')
    return result


@dataclass(frozen=True)
class VirtualBoxBinding:
    vm_id: str
    marker: str
    configuration: object  # trusted record reader; never renderer-selected VM IDs
    timeout_seconds: float = 3610
    workspace_root: str | None = None
    storage_enrollment: object = field(default=None, repr=False, compare=False)
    storage_approval: object = field(default=None, repr=False, compare=False)


class VirtualBoxClient:
    def __init__(self, path=None, runner=None):
        self.path, self.runner = path or executable(), runner or subprocess.run

    def run(self, *args, password=None, timeout=120, physical=True):
        if not self.path:
            raise ExecutorFailure('virtualbox_not_installed')
        if physical:
            effect_checkpoint()
        result = self.runner([self.path, *map(str, args)], capture_output=True,
            input=password + '\n' if password else None, text=True, encoding='utf-8', errors='replace',
            timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ExecutorFailure('virtualbox_' + str(args[0]) + '_failed', uncertain=physical)
        return result.stdout[-524288:]

    def detect(self, iso):
        """Accept VirtualBox 7.2 partial ISO metadata, never claim unattended support on E_NOTIMPL."""
        if not self.path:
            raise ExecutorFailure('virtualbox_not_installed')
        result = self.runner([self.path, 'unattended', 'detect', '--iso', str(iso), '--machine-readable'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        metadata = machine_readable(result.stdout)
        if result.returncode:
            if ('E_NOTIMPL' not in result.stderr or not metadata.get('OSTypeId')
                    or 'IsInstallSupported' not in metadata):
                raise ExecutorFailure('virtualbox_iso_detection_failed')
            metadata['_partial_detection'] = True
        return metadata

    def guest_additions_runlevel(self, vm_id):
        """Read-only. Levels 2 and 3 are the guest-control channel."""
        from sentra_executors.guest_execution import safe_vm_id
        if safe_vm_id(vm_id) is None:
            return "0"
        info = machine_readable(self.run("showvminfo", vm_id, "--machinereadable", physical=False))
        return str(info.get("GuestAdditionsRunLevel", "0"))

    def status(self, binding):
        require_vm_token(binding)
        info = machine_readable(self.run('showvminfo', binding.vm_id, '--machinereadable', physical=False))
        if not same_vm_identity(info.get('UUID'), binding.vm_id) or info.get('description') != binding.marker:
            raise ExecutorFailure('virtualbox_vm_identity_changed')
        return info

    @contextmanager
    def console(self, binding):
        require_vm_token(binding)
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        session = None
        try:
            vbox = win32com.client.Dispatch('VirtualBox.VirtualBox')
            machine = vbox.FindMachine(binding.vm_id)
            if not same_vm_identity(str(machine.Id), binding.vm_id) or machine.Description != binding.marker:
                raise ExecutorFailure('virtualbox_vm_identity_changed')
            session = win32com.client.Dispatch('VirtualBox.Session')
            machine.LockMachine(session, 1)  # LockType_Shared; another VM cannot be substituted.
            yield session.Console
        finally:
            if session is not None:
                try:
                    session.UnlockMachine()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    def frame(self, binding):
        begin = time.monotonic()
        with self.console(binding) as console:
            screen = console.Display.GetScreenResolution(0)
            source_width, source_height = int(screen[0]), int(screen[1])
            if not 1 <= source_width <= 8192 or not 1 <= source_height <= 8192:
                raise ExecutorFailure('virtualbox_framebuffer_unavailable')
            scale = min(1, 1280 / source_width, 800 / source_height)
            width, height = max(1, int(source_width * scale)), max(1, int(source_height * scale))
            image = bytes(console.Display.TakeScreenShotToArray(0, width, height, 0x20474E50))
            if not image.startswith(b'\x89PNG\r\n\x1a\n') or len(image) > 1048576:
                raise ExecutorFailure('virtualbox_frame_limit')
        return {'vm_id': binding.vm_id, 'image_base64': base64.b64encode(image).decode(),
            'mime_type': 'image/png', 'width': width, 'height': height,
            'source_width': source_width, 'source_height': source_height,
            'captured_at': time.time(), 'capture_ms': round((time.monotonic() - begin) * 1000),
            'transport': 'virtualbox-com-framebuffer', 'framebuffer_verified': True,
            'desktop_verified': False, 'installed_os_verified': False}

    def input(self, binding, args):
        with self.console(binding) as console:
            effect_checkpoint()
            if args['action'] == 'input.bios_dvd':
                # One centrally fenced input Operation. Separate HTTP calls
                # cannot reach the brief El Torito "Press any key" window.
                # No guest credentials or Guest Additions are involved.
                console.Keyboard.PutScancodes([
                    0x1D, 0x38, 0xE0, 0x53, 0xE0, 0xD3, 0xB8, 0x9D])
                time.sleep(1.4)
                for _ in range(11):
                    console.Keyboard.PutScancodes([0x39, 0xB9])
                    time.sleep(0.38)
                return {'vm_id': binding.vm_id, 'input_sent': True,
                    'action': 'input.bios_dvd', 'keyboard_events_sent': 12,
                    'windows_setup_verified': False, 'automatic_retry': False}
            if args['action'] == 'input.key':
                console.Keyboard.PutScancodes(args['scancodes'])
            else:
                screen = console.Display.GetScreenResolution(0)
                if args['x'] > int(screen[0]) or args['y'] > int(screen[1]):
                    raise ValueError('pointer outside current framebuffer')
                console.Mouse.PutMouseEventAbsolute(args['x'], args['y'], args.get('wheel', 0), 0, args['buttons'])
        return {'vm_id': binding.vm_id, 'input_sent': True, 'action': args['action']}

    def diagnostics(self, binding, cfg):
        """Bounded read-only host evidence, without guessing guest readiness.

        Only the current log below this exact owned VM directory is read. The
        result exposes classified flags rather than host paths or raw logs.
        """
        info = self.status(binding)
        name = cfg.get('name') if isinstance(cfg, dict) else None
        base = cfg.get('base_folder') if isinstance(cfg, dict) else None
        safe_name = (isinstance(name, str) and '..' not in name
                     and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}', name) is not None)
        safe_base = isinstance(base, str) and '\0' not in base and Path(base).is_absolute()
        text = ''
        folder = None
        configured_folder = None
        if safe_name and safe_base:
            root = Path(base).resolve()
            folder = (root / name).resolve()
            log = (folder / 'Logs' / 'VBox.log').resolve()
            try:
                configured_folder = Path(info.get('CfgFile', '')).parent.resolve()
            except OSError:
                configured_folder = None
            if (folder.is_relative_to(root) and configured_folder == folder
                    and log.is_relative_to(folder) and log.is_file()):
                with log.open('rb') as source:
                    source.seek(0, 2)
                    length = source.tell()
                    source.seek(0)
                    prefix = source.read(min(length, 262144))
                    source.seek(max(0, length - 131072))
                    tail = source.read(131072)
                text = (prefix + tail).decode('utf-8', errors='replace')
        live_iso = Path(cfg.get('iso_path') or '').name.lower().startswith('debian-live-')
        runlevel = info.get('GuestAdditionsRunLevel', 0)
        return {'vm_id':binding.vm_id, 'vm_state':info.get('VMState'),
            'graphics_controller':info.get('graphicscontroller'),
            'accelerate_3d':info.get('accelerate3d'),
            'guest_additions_runlevel':runlevel,
            'guest_command_channel_ready':str(runlevel) in {'2', '3'},
            'execution_backend':'hyperv_nem' if 'WHvCapabilityCodeHypervisorPresent is TRUE' in text else ('native' if 'HM: Using' in text else 'unknown'),
            'hardware_virtualization_fallback':'Attempting fall back to NEM' in text,
            'iso_boot_mode':'live_or_installer' if live_iso else 'installer_or_disk',
            'installed_os_verified':False, 'desktop_ready_verified':False,
            'log_identity_verified': folder is not None and configured_folder == folder,
            'automatic_reboot':False}

    def disk_attachments(self, binding):
        require_vm_token(binding)
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            machine = win32com.client.Dispatch('VirtualBox.VirtualBox').FindMachine(binding.vm_id)
            if not same_vm_identity(str(machine.Id), binding.vm_id) or machine.Description != binding.marker:
                raise ExecutorFailure('virtualbox_vm_identity_changed')
            result = []
            for attachment in machine.MediumAttachments:
                if int(attachment.Type) != 3:  # DeviceType_HardDisk; DVD is 2.
                    continue
                medium = attachment.Medium
                parent = medium.Parent
                result.append({'controller':attachment.Controller, 'port':int(attachment.Port),
                    'device':int(attachment.Device), 'location':str(medium.Location), 'disk_uuid':str(medium.Id).lower(),
                    'parent_uuid':str(parent.Id).lower() if parent is not None else None})
            return result
        finally:
            pythoncom.CoUninitialize()


def require_vm_token(binding):
    """Refuse a path or shell fragment before any hypervisor query."""
    from sentra_executors.guest_execution import safe_vm_id
    if safe_vm_id(getattr(binding, "vm_id", None)) is None:
        raise ExecutorFailure("virtualbox_vm_identity_changed")


def same_vm_identity(observed, expected):
    """True when both ids are the same hypervisor token, ignoring case and braces."""
    from sentra_executors.guest_execution import safe_vm_id

    def norm(value):
        if not isinstance(value, str):
            return None
        return safe_vm_id(value.strip().strip("{}").strip().lower())

    left, right = norm(observed), norm(expected)
    return left is not None and left == right


def vm_is_listed(listing, vm_id):
    """Match the hypervisor UUID in braces, not a name that contains the id."""
    from sentra_executors.guest_execution import safe_vm_id
    token = safe_vm_id(vm_id)
    if token is None or not isinstance(listing, str):
        return False
    needle = "{" + token.lower() + "}"
    return any(needle in line.lower() for line in listing.splitlines())


class VirtualBoxExecutor(GuardedExecutor):
    kind = 'virtualbox_vm'
    # Verified on this host's Debian 13 Live guest under Windows Hyper-V/NEM.
    # These affect only this boot; they neither install nor modify the disk.
    DEBIAN_NEM_PARAMETERS = ' tsc=unstable clocksource=acpi_pm nohz=off maxcpus=1'

    def __init__(self, *, client=None, guest_executor=None, **kwargs):
        super().__init__(**kwargs)
        self.client = client or VirtualBoxClient()
        self.guest_executor = guest_executor

    def _validate(self, request, binding):
        args = dict(request.arguments)
        action = args.get('action')
        if action not in VM_ACTIONS[request.capability_id]:
            raise ValueError('unsupported virtual machine action')
        fields = {'input.key': {'scancodes'}, 'input.mouse': {'x', 'y', 'buttons', 'wheel'},
            'storage.enroll': {'expected_candidate_sha256'},
            'guest.run': {'command', 'timeout_seconds'}, 'project.import': {'relative_path', 'host_folder', 'request_key'},
            'installation.reconcile': {'detach_storage', 'request_key'},
            'installation.advance': {'confirm_launch'},
            'resource.cap': {'cpus', 'memory_mb', 'cpu_execution_cap', 'vm_id', 'controlled_proof', 'workload_inspected', 'host', 'surfaces', 'state_root'}}.get(action, set())
        if set(args) - (fields | {'action'}):
            raise ValueError('virtual machine identity is host-owned')
        if action == 'project.import':
            if 'host_folder' in args and (not isinstance(args['host_folder'], str) or not args['host_folder'].strip() or len(args['host_folder']) > 1024):
                raise ValueError('explicit host folder required')
            if 'relative_path' in args and (not isinstance(args['relative_path'], str) or not args['relative_path'] or len(args['relative_path']) > 1024):
                raise ValueError('project-relative directory required')
            if 'request_key' in args and args['request_key'] is not None and (not isinstance(args['request_key'], str) or len(args['request_key']) > 128):
                raise ValueError('invalid import request key')
        if action == 'installation.advance' and 'confirm_launch' in args and type(args['confirm_launch']) is not bool:
            raise ValueError('launch admission must be explicit')
        if action == 'storage.enroll' and (not isinstance(args.get('expected_candidate_sha256'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', args['expected_candidate_sha256'])):
            raise ValueError('exact reviewed storage candidate hash required')
        if action == 'storage.enroll' and (not callable(binding.storage_enrollment) or not callable(binding.storage_approval)):
            raise ValueError('owner storage enrollment host callbacks are not configured')
        if action == 'resource.cap':
            for key in ('cpus', 'memory_mb', 'cpu_execution_cap'):
                if key in args and type(args[key]) is not int:
                    raise ValueError('resource cap plan must be integers')
            if 'host' in args and not isinstance(args['host'], dict):
                raise ValueError('host sample required')
            if 'surfaces' in args and not isinstance(args['surfaces'], dict):
                raise ValueError('surface sample required')
            if 'state_root' in args and not isinstance(args['state_root'], str):
                raise ValueError('state root required')
            if 'controlled_proof' in args and type(args['controlled_proof']) is not bool:
                raise ValueError('controlled proof must be explicit')
            if 'workload_inspected' in args and type(args['workload_inspected']) is not bool:
                raise ValueError('workload inspection must be explicit')
            if 'vm_id' in args and args['vm_id'] != binding.vm_id:
                raise ValueError('virtual machine identity is host-owned')
        if action == 'input.key' and (not isinstance(args.get('scancodes'), list) or not 1 <= len(args['scancodes']) <= 32 or any(type(n) is not int or not 0 <= n <= 255 for n in args['scancodes'])):
            raise ValueError('bounded keyboard scancodes required')
        if action == 'input.bios_dvd' and set(args) != {'action'}:
            raise ValueError('BIOS DVD input has no user-selectable parameters')
        if action == 'input.mouse' and (any(type(args.get(k)) is not int for k in ('x', 'y', 'buttons')) or not 1 <= args['x'] <= 8192 or not 1 <= args['y'] <= 8192 or not 0 <= args['buttons'] <= 7 or type(args.get('wheel', 0)) is not int or not -16 <= args.get('wheel', 0) <= 16):
            raise ValueError('bounded framebuffer pointer required')
        if action == 'guest.run' and (not isinstance(args.get('command'), str) or not 1 <= len(args['command']) <= 65536 or type(args.get('timeout_seconds', 120)) is not int or not 1 <= args.get('timeout_seconds', 120) <= 3600):
            raise ValueError('bounded guest command required')
        return args

    @staticmethod
    def _debian_live_boot_menu(image_base64):
        """Conservative visual guard for Debian Live's *selected* boot item.

        A read-only framebuffer is not permission to send keys. The caller must
        independently hold a central physical effect fence and target the
        exact configured Debian Live ISO. Failure to recognize is fail-closed.
        """
        import io
        try:
            from PIL import Image
            raw = base64.b64decode(image_base64, validate=True)
            if len(raw) > 1048576 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                return False
            with Image.open(io.BytesIO(raw)) as source:
                if source.format != 'PNG' or not (320 <= source.width <= 1920 and 240 <= source.height <= 1200):
                    return False
                picture = source.convert('RGB')
            width, height = picture.size
            selected_y, above_y = round(height * .53), round(height * .49)
            # Debian Live 13's first entry is a long, blue-highlighted bar.
            for ratio in (.44, .65, .83):
                x = round(width * ratio)
                selected = picture.getpixel((x, selected_y))
                background = picture.getpixel((x, above_y))
                if not (90 < selected[0] < 180 and 115 < selected[1] < 210
                        and 145 < selected[2] < 240
                        and all(selected[i] - background[i] >= 36 for i in range(3))):
                    return False
            for ratio in (.11, .94):
                outside = picture.getpixel((round(width * ratio), selected_y))
                if outside[0] > 85 or outside[1] > 135:
                    return False
            return True
        except (ImportError, ValueError, OSError, TypeError):
            return False

    @staticmethod
    def _debian_live_boot_editor(image_base64):
        """Confirm Syslinux's cyan prompt after Tab from a verified Live menu."""
        import io
        try:
            from PIL import Image
            raw = base64.b64decode(image_base64, validate=True)
            if len(raw) > 1048576 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                return False
            with Image.open(io.BytesIO(raw)) as source:
                if source.format != 'PNG' or not (320 <= source.width <= 1920 and 240 <= source.height <= 1200):
                    return False
                picture = source.convert('RGB')
            width, height = picture.size
            cyan = sum(1 for y in range(round(height * .90), round(height * .96))
                for x in range(round(width * .005), round(width * .04))
                if (lambda c: c[0] < 100 and c[1] > 180 and c[2] > 180)(picture.getpixel((x, y))))
            letters = sum(1 for y in range(round(height * .90), round(height * .98))
                for x in range(round(width * .04), round(width * .9))
                if min(picture.getpixel((x, y))) > 180)
            return cyan >= 12 and letters >= 80
        except (ImportError, ValueError, OSError, TypeError):
            return False

    @classmethod
    def _debian_nem_scancode_batches(cls):
        keys = {'a':30,'b':48,'c':46,'d':32,'e':18,'f':33,'g':34,'h':35,
            'i':23,'j':36,'k':37,'l':38,'m':50,'n':49,'o':24,'p':25,'q':16,
            'r':19,'s':31,'t':20,'u':22,'v':47,'w':17,'x':45,'y':21,'z':44,
            ' ':57,'=':13,'1':2}
        batches, current = [], []
        for char in cls.DEBIAN_NEM_PARAMETERS:
            scans = [42,12,140,170] if char == '_' else [keys[char], keys[char] | 128]
            if len(current) + len(scans) > 32:
                batches.append(current); current = []
            current.extend(scans)
        if current:
            batches.append(current)
        return batches

    def _boot_input_fence(self, cfg, vm_id):
        """Absolute Dot VM folders remember that boot keys were already sent."""
        from sentra_executors.guest_execution import safe_vm_id
        folder = cfg.get('base_folder')
        name = cfg.get('name')
        token = safe_vm_id(vm_id)
        if not isinstance(folder, str) or '\0' in folder or not isinstance(name, str) or token is None:
            return None
        root = Path(folder)
        if not root.is_absolute():
            return None
        safe_name = name.strip()
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}', safe_name) or '..' in safe_name):
            return None
        home = (root / safe_name).resolve()
        fence = (home / ('live-boot-input-' + token + '.fence')).resolve()
        try:
            if not home.is_relative_to(root.resolve()) or not fence.is_relative_to(home):
                return None
        except (OSError, ValueError):
            return None
        return fence

    def _advance_debian_live(self, binding, cfg, *, attempts=10):
        """Select Debian Live once, within the existing centrally fenced VM action.

        Never touch unrelated installations or silently replay an uncertain key.
        This advances the boot selector only; it is NOT a completed OS install.
        """
        image = Path(cfg.get('iso_path') or '').name.lower()
        if (cfg.get('os_family') != 'linux' or not image.startswith('debian-live-')
                or not any(tag in image for tag in ('amd64', 'x86_64'))):
            return {'live_boot': 'not_applicable'}
        for attempt in range(attempts):
            effect_checkpoint()
            try:
                frame = self.client.frame(binding)
            except (ExecutorFailure, OSError, RuntimeError):
                # The console may be unavailable for the first few seconds.
                frame = None
            if frame and self._debian_live_boot_menu(frame.get('image_base64')):
                fence = self._boot_input_fence(cfg, binding.vm_id)
                if fence is not None and fence.is_file():
                    return {'live_boot': 'input_already_sent', 'automatic_retry': False,
                        'desktop_ready_verified': False, 'keys_resent': False}
                def arm_boot_input():
                    if fence is None or fence.is_file():
                        return
                    fence.parent.mkdir(parents=True, exist_ok=True)
                    fence.write_text('sent', encoding='utf-8')
                compatibility = False
                # Keep unrelated Linux images/hosts unchanged. Detection is
                # read-only and tied to this UUID/marker and owned VBox log.
                if image.startswith('debian-live-13.') and cfg.get('base_folder') and cfg.get('name'):
                    diagnostics = self.client.diagnostics(binding, cfg)
                    compatibility = diagnostics.get('execution_backend') == 'hyperv_nem'
                if compatibility:
                    arm_boot_input()
                    self.client.input(binding, {'action':'input.key','scancodes':[15,143]})
                    editor_confirmed = False
                    # Guest repaint is asynchronous. Observe only; Tab is
                    # never resent when delivery or rendering is uncertain.
                    for _ in range(10):
                        effect_checkpoint()
                        editor = self.client.frame(binding)
                        if self._debian_live_boot_editor(editor.get('image_base64')):
                            editor_confirmed = True
                            break
                        time.sleep(.1)
                    if not editor_confirmed:
                        return {'live_boot':'editor_not_confirmed', 'automatic_retry':False,
                            'desktop_ready_verified':False}
                    for scans in self._debian_nem_scancode_batches():
                        effect_checkpoint()
                        self.client.input(binding, {'action':'input.key','scancodes':scans})
                        time.sleep(.05)
                # Never catch-and-retry ambiguous key delivery: the COM call
                # may have delivered an event before reporting a failure.
                arm_boot_input()
                effect_checkpoint()
                self.client.input(binding, {'action':'input.key',
                    'scancodes':[0x1c, 0x9c]})
                return {'live_boot':'selection_sent',
                    'boot_selection':'Debian Live system (amd64)',
                    'boot_compatibility':'debian_hyperv_nem' if compatibility else 'default',
                    'kernel_parameters':self.DEBIAN_NEM_PARAMETERS.strip() if compatibility else None,
                    'desktop_ready_verified':False}
            if attempt + 1 < attempts:
                time.sleep(1)
        return {'live_boot':'menu_not_confirmed',
            'desktop_ready_verified':False, 'automatic_retry':False}

    def _execute(self, binding, args):
        from sentra_executors.guest_execution import safe_vm_id
        if safe_vm_id(getattr(binding, 'vm_id', None)) is None:
            raise ValueError('vm id is not a hypervisor token')
        cfg = binding.configuration()
        action = args['action']
        if action == 'storage.candidate':
            from .virtualbox_storage_enrollment import public_storage_candidate, configured_storage_candidate
            return public_storage_candidate(configured_storage_candidate(self.client, binding, cfg))
        if action == 'storage.enroll':
            if not callable(binding.storage_enrollment):
                raise PermissionError('authenticated owner storage enrollment is not configured')
            return binding.storage_enrollment(self.client, binding, cfg, args['expected_candidate_sha256'])
        if action == 'provision':
            return self._provision(binding, cfg)
        if action == 'resource.cap':
            from sentra_executors.vm_resources import apply_authorized_cap
            from orchestrator.resources import ResourceCeiling
            missing = [key for key in ('cpus', 'memory_mb', 'cpu_execution_cap', 'host', 'surfaces', 'state_root') if key not in args]
            if missing:
                return {'ready': False, 'executed': False, 'applied': False, 'refused': True,
                    'mutated': False, 'authorizes_effects': False, 'reason': 'plan incompleto',
                    'missing_order_fields': missing}
            return apply_authorized_cap(
                self.client, binding,
                {'cpus': int(args['cpus']), 'memory_mb': int(args['memory_mb']), 'cpu_execution_cap': int(args['cpu_execution_cap'])},
                host=args['host'], surfaces=args['surfaces'],
                ceiling=ResourceCeiling(), state_root=args['state_root'],
            )
        info = self.client.status(binding)
        if action == 'status':
            return {'vm_id': binding.vm_id, 'vm_state': info.get('VMState'), 'cpus': info.get('cpus'), 'memory_mb': info.get('memory'), 'os_type': info.get('ostype')}
        if action == 'frame':
            return self.client.frame(binding)
        if action == 'diagnostics':
            return self.client.diagnostics(binding, cfg)
        if action == 'project.import':
            from .virtualbox_project import import_project
            return import_project(self.client, binding, cfg, relative_path=args.get('relative_path', '.'),
                host_folder=args.get('host_folder'), request_key=args.get('request_key'))
        if action == 'project.import.reconcile':
            from .virtualbox_project import reconcile_uncertain_import
            return reconcile_uncertain_import(self.client, binding, cfg)
        if action == 'installation.advance':
            from .virtualbox_bootstrap import advance
            return advance(self.client, binding, cfg, confirm_launch=args.get('confirm_launch', False))
        if action in {'installation.prepare', 'installation.launch', 'installation.reconcile'}:
            from .virtualbox_bootstrap import prepare, launch, reconcile_failed_attempt
            if action == 'installation.reconcile':
                return reconcile_failed_attempt(self.client, binding, cfg,
                    detach_storage=bool(args.get('detach_storage')),
                    request_key=args.get('request_key'))
            return (prepare if action == 'installation.prepare' else launch)(self.client, binding, cfg)
        if action in {'installation.plan', 'installation.verify', 'installation.boot_disk'}:
            from .virtualbox_installation import installation_plan, verify_guest, configure_disk_boot
            handler = {'installation.plan':installation_plan, 'installation.verify':verify_guest,
                'installation.boot_disk':configure_disk_boot}[action]
            return handler(self.client, binding, cfg)
        if action == 'input.bios_dvd':
            # BIOS-only bounded keyboard action, with the same central
            # WorkItem/Grant/fence and human input lease as input.key.
            if cfg.get('os_family') != 'windows':
                raise ValueError('BIOS DVD shortcut is Windows-installation-only')
            info = self.client.status(binding)
            dvd = str(info.get('IDE-0-0') or '')
            if (info.get('VMState') != 'running' or str(info.get('boot1')).lower() != 'dvd'
                    or not dvd.lower().endswith('.iso') or not dvd):
                raise ExecutorFailure('windows_dvd_boot_preconditions_unverified')
            return self.client.input(binding, args)
        if action in {'input.key', 'input.mouse'}:
            return self.client.input(binding, args)
        if action == 'guest.run':
            from sentra_executors.guest_execution import is_proven_guest_executor, resolve_guest_executor
            from .virtualbox_project import _guest_account
            account = _guest_account(cfg)
            # Resolve an owned guestcontrol executor only when the running VM
            # proves a usable Guest Additions channel. Do not convert a
            # missing guest executor into a host subprocess or a model claim.
            guest_executor = self.guest_executor
            if guest_executor is None:
                probe = getattr(self.client, 'guest_additions_runlevel', None)
                if callable(probe) and str(probe(binding.vm_id)) in {'2', '3'}:
                    guest_executor = resolve_guest_executor(
                        vm_id=binding.vm_id, username=account,
                        password=cfg.get('password'), os_family=cfg.get('os_family'),
                        client=self.client)
            windows = cfg['os_family'] == 'windows'
            exe = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' if windows else '/bin/sh'
            command_args = ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', args['command']] if windows else ['-lc', args['command']]
            timeout_seconds = args.get('timeout_seconds', 120)
            argv = ('guestcontrol', binding.vm_id, 'run', '--exe', exe,
                '--username', account, '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr',
                '--timeout', timeout_seconds * 1000, '--', *command_args)
            if not is_proven_guest_executor(guest_executor):
                return {'vm_id': binding.vm_id, 'stdout': '', 'guest_process_confirmed': False,
                    'execution_surface': 'blocked', 'claims_guest_execution': False,
                    'host_subprocess': False, 'blocked': True, 'execution_uncertain': True,
                    'automatic_retry': False,
                    'reason': 'guest.run requires a live proven guest executor; host execution was not substituted'}
            produced = guest_executor.execute({
                'action': 'guest.run', 'argv': list(argv), 'command': args['command'],
                'vm_id': binding.vm_id, 'placement': 'guest',
                'timeout_s': timeout_seconds,
            })
            exit_code = produced.get('exit_code') if isinstance(produced, dict) else None
            proven_result = (
                isinstance(produced, dict)
                and produced.get('execution_surface') == 'guest'
                and produced.get('host_subprocess') is not True
                and produced.get('claims_guest_execution') is True
                and produced.get('execution_uncertain') is not True
                and type(exit_code) is int and exit_code == 0
                and isinstance(produced.get('stdout', ''), str)
            )
            if not proven_result:
                return {'vm_id': binding.vm_id, 'stdout': '',
                    'guest_process_confirmed': False, 'execution_surface': 'blocked',
                    'claims_guest_execution': False, 'host_subprocess': False, 'blocked': True,
                    'execution_uncertain': True, 'automatic_retry': False,
                    'reason': 'guest executor did not prove a guest process'}
            secret = cfg.get('password')
            stdout = produced.get('stdout') or ''
            if isinstance(secret, str) and len(secret) >= 8 and secret in stdout:
                return {'vm_id': binding.vm_id, 'stdout': '',
                    'guest_process_confirmed': False, 'execution_surface': 'blocked',
                    'claims_guest_execution': False, 'host_subprocess': False, 'blocked': True,
                    'execution_uncertain': True, 'automatic_retry': False,
                    'reason': 'guest output included a credential and was discarded'}
            return {'vm_id': binding.vm_id, 'stdout': stdout,
                'guest_process_confirmed': True, 'execution_surface': 'guest',
                'claims_guest_execution': True, 'host_subprocess': False, 'blocked': False,
                'execution_uncertain': False, 'automatic_retry': False}
        if action == 'restart' and info.get('VMState') != 'running':
            raise ValueError('restart requires the existing owned VM to be running')
        command = {'start': ('startvm', binding.vm_id, '--type', 'headless'),
            'shutdown': ('controlvm', binding.vm_id, 'acpipowerbutton'),
            'restart': ('controlvm', binding.vm_id, 'reset'),
            'pause': ('controlvm', binding.vm_id, 'pause'), 'resume': ('controlvm', binding.vm_id, 'resume')}[action]
        self.client.run(*command)
        # Rebinding another conversation can change the projection status to
        # existing_vm. That must not disable the verified Live-menu bootstrap.
        # The helper gates on the local image and actual selected menu itself.
        boot = self._advance_debian_live(binding, cfg) if action == 'start' else {}
        after = self.client.status(binding)
        return {'vm_id': binding.vm_id, 'requested_action': action, 'vm_state': after.get('VMState'),
            'os_ready_verified': False, **boot}

    def _provision(self, binding, cfg):
        from .virtualbox_project import _guest_account
        _guest_account(cfg)
        honesty = {}
        if cfg.get('os_family') == 'windows':
            from .virtualbox_installation import assess_windows_license
            info = assess_windows_license(cfg)
            honesty = {'windows_usable': False, 'license_posture': info['posture'],
                'activation_claimed': False, 'product_key_stored': False}
        image = cfg.get('iso_path')
        if not image:
            return {'status': 'pending_image', 'vm_id': binding.vm_id, 'created': False, 'os_ready_verified': False, **honesty}
        iso = Path(image)
        if not iso.is_file() or iso.suffix.lower() != '.iso':
            raise ValueError('local installation ISO required')
        with iso.open('rb') as source:
            sha = hashlib.file_digest(source, 'sha256').hexdigest()
        if sha != cfg['iso_sha256']:
            raise ValueError('installation ISO changed after configuration')
        detected = self.client.detect(str(iso))
        os_type = detected.get('detectedOSTypeId') or detected.get('OSTypeId', '')
        # VirtualBox 7.2 reports the generic 32-bit Debian family even for
        # the official amd64 live image. Respect explicit ISO architecture.
        if cfg['os_family'] == 'linux' and os_type == 'Debian' and any(
                token in iso.name.lower() for token in ('amd64', 'x86_64', 'x64')):
            os_type = 'Debian_64'
        supported = str(detected.get('isUnattendedInstallSupported',
            detected.get('IsInstallSupported', ''))).lower() in {'true', '1', 'yes', 'on'}
        # VirtualBox 7.2 returns E_NOTIMPL while still reporting Windows install
        # support. That partial read must not fall through to the Debian menu.
        windows_image = str(os_type).startswith('Windows')
        manual_boot = (not supported) or (bool(detected.get('_partial_detection')) and not windows_image)
        if not os_type or (os_type.startswith('Windows') != (cfg['os_family'] == 'windows')):
            return {'status': 'unsupported_image', 'created': False, 'detected_os_type': os_type,
                'unattended_supported': supported and not manual_boot, 'os_ready_verified': False, **honesty}
        if os_type.startswith('Windows11') and (cfg['disk_gb'] < 64 or cfg['cpus'] < 2 or cfg['memory_mb'] < 4096):
            raise ValueError('Windows 11 requires at least 2 vCPUs, 4096 MiB RAM and 64 GiB disk')
        # A previously created/partially created UUID is never recreated by another request.
        existing = self.client.run('list', 'vms', physical=False)
        if vm_is_listed(existing, binding.vm_id):
            return {'status': 'existing_vm', 'vm_id': binding.vm_id, 'vm_state': self.client.status(binding).get('VMState'), 'automatic_retry': False, 'os_ready_verified': False, **honesty}
        name = cfg.get('name')
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}', name)
                or '..' in name):
            raise ValueError('vm name is not a hypervisor token')
        marker = getattr(binding, 'marker', None)
        if (not isinstance(marker, str) or not marker.strip() or len(marker) > 200
                or any(char in marker for char in '\n\r\0')):
            raise ValueError('vm marker is not a hypervisor token')
        base = cfg.get('base_folder')
        if not isinstance(base, str) or '\0' in base or not Path(base).is_absolute():
            raise ValueError('vm folder is not a host path')
        folder = Path(base).resolve()
        disk = (folder / name / 'system.vdi').resolve()
        if not disk.is_relative_to(folder):
            raise ValueError('vm name is not a hypervisor token')
        effect_checkpoint()
        folder.mkdir(parents=True, exist_ok=True)
        self.client.run('createvm', '--name', name, '--uuid', binding.vm_id,
            '--ostype', os_type, '--basefolder', str(folder), '--register')
        self.client.run('modifyvm', binding.vm_id, '--description', binding.marker,
            '--cpus', cfg['cpus'], '--memory', cfg['memory_mb'], '--vram', 128,
            '--graphicscontroller', 'vboxsvga' if cfg['os_family'] == 'windows' else 'vmsvga',
            '--ioapic', 'on', '--mouse', 'usbtablet', '--usb-ohci', 'on',
            '--nic1', 'nat', '--nat-localhostreachable1', 'off', '--clipboard-mode', 'disabled',
            '--drag-and-drop', 'disabled', '--audio-enabled', 'off', '--boot1', 'dvd', '--boot2', 'disk')
        if os_type.startswith('Windows11'):
            self.client.run('modifyvm', binding.vm_id, '--firmware', 'efi', '--tpm-type', '2.0')
            self.client.run('modifynvram', binding.vm_id, 'inituefivarstore')
            self.client.run('modifynvram', binding.vm_id, 'secureboot', '--enable')
        self.client.run('createmedium', 'disk', '--filename', str(disk), '--size', cfg['disk_gb'] * 1024, '--format', 'VDI')
        self.client.run('storagectl', binding.vm_id, '--name', 'SATA', '--add', 'sata', '--controller', 'IntelAhci')
        self.client.run('storageattach', binding.vm_id, '--storagectl', 'SATA', '--port', 0, '--device', 0, '--type', 'hdd', '--medium', str(disk))
        self.client.run('storageattach', binding.vm_id, '--storagectl', 'SATA', '--port', 1, '--device', 0, '--type', 'dvddrive', '--medium', str(iso))
        live_boot = {}
        if manual_boot:
            # VirtualBox 7.2 can identify the Live ISO but cannot install it
            # unattended. Start the actual guest and select its verified Live
            # boot-menu entry within the SAME centrally authorized operation.
            self.client.run('startvm', binding.vm_id, '--type', 'headless')
            live_boot = self._advance_debian_live(binding, cfg)
        else:
            from .virtualbox_project import _guest_account
            self.client.run('unattended', 'install', binding.vm_id, '--iso', str(iso), '--user', _guest_account(cfg),
                '--user-password-file', 'stdin', '--full-user-name', 'SENTRA Dot', '--install-additions',
                '--hostname', 'sentra-' + binding.vm_id[:8] + '.local', '--start-vm', 'headless',
                password=cfg['password'], timeout=900)
        return {'status': 'installation_started' if not manual_boot else 'installer_boot_started',
            'installation_mode': 'manual_iso_boot' if manual_boot else 'unattended',
            'vm_id': binding.vm_id, 'vm_state': self.client.status(binding).get('VMState'),
            'created': True, 'detected_os_type': os_type,
            'unattended_supported': supported and not manual_boot,
            'os_ready_verified': False, **honesty, **live_boot}
