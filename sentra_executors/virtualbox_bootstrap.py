"""One-shot Debian Live installation into the exclusively owned empty VDI.

The seed is a read-only DVD, never a host share. Preparing a seed is not proof
of installation. A nonempty target is never formatted or automatically retried.
"""
from pathlib import Path
import base64
import hashlib
import json
import os
import time
import uuid

from .rpa import effect_checkpoint, ExecutorFailure
from .virtualbox_installation import owned_storage
from .virtualbox_seed import seed_iso


def _private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    if os.name == 'nt':
        import win32api, win32security, ntsecuritycon
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        acl = win32security.ACL()
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, 3, ntsecuritycon.FILE_ALL_ACCESS, sid)
        win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)


def install_script(vm_id, capacity, password):
    identity = uuid.UUID(vm_id)
    ident = str(identity)
    # VBox SMBIOS can expose the first three UUID fields in either byte
    # order (system-uuid-le). Only the two exact representations of the
    # already host-bound VM UUID are admissible, never a prefix or any UUID.
    legacy_dmi = str(uuid.UUID(bytes_le=identity.bytes))
    if type(capacity) is not int or not 16 * 1024**3 <= capacity <= 256 * 1024**3:
        raise ValueError('bounded owned guest disk required')
    secret = base64.b64encode(('sentra:' + password + '\n').encode()).decode()
    return (r'''#!/bin/bash
set -euo pipefail
exec > >(tee /tmp/sentra-install.log) 2>&1
trap 'echo "SENTRA_INSTALL_FAILED line=$LINENO"; sync' ERR
test "$(id -u)" = 0
test -r /sys/class/dmi/id/product_uuid
dmi_uuid=$(cat /sys/class/dmi/id/product_uuid | tr '[:upper:]' '[:lower:]')
echo "READBACK_DMI_UUID=$dmi_uuid"
case "$dmi_uuid" in '@@ID@@'|'@@LEGACY_DMI@@') ;; *) echo "DMI_UUID_MISMATCH $dmi_uuid"; exit 33 ;; esac
test "$(lsblk -dn -o NAME,TYPE | awk '$2 == "disk" {print $1}')" = sda
test "$(blockdev --getsize64 /dev/sda)" = '@@CAPACITY@@'
test -d /run/live
test "$(findmnt -nr -o FSTYPE /)" = overlay
test -z "$(lsblk -nr -o NAME /dev/sda | tail -n +2)"
test -z "$(wipefs -n --noheadings -o TYPE /dev/sda)"
test ! -e /run/sentra-install-admitted
touch /run/sentra-install-admitted
echo SENTRA_INSTALL_ADMITTED
# Host full VDI map preflight plus guest identity/sole disk/signature guards.
printf 'label: dos\nstart=2048, type=83, bootable\n' | sfdisk /dev/sda
udevadm settle
mkfs.ext4 -F -L sentra-root /dev/sda1
mkdir -p /target
mount /dev/sda1 /target
source=$(findmnt -rn -t squashfs -o TARGET | head -n 1)
test -n "$source" && test -f "$source/etc/debian_version"
cp -a "$source/." /target/
mkdir -p /target/dev /target/proc /target/sys /target/run
for directory in dev proc sys run; do mount --rbind /$directory /target/$directory; mount --make-rslave /target/$directory; done
rm -f /target/etc/resolv.conf
cp -L /etc/resolv.conf /target/etc/resolv.conf
printf 'UUID=%s / ext4 defaults 0 1\n' "$(blkid -s UUID -o value /dev/sda1)" > /target/etc/fstab
printf '%s\n' '@@ID@@' > /target/etc/sentra-dot-vm-id
printf '%s\n' 'sentra-@@SHORT@@' > /target/etc/hostname
printf '127.0.0.1 localhost\n127.0.1.1 sentra-@@SHORT@@\n' > /target/etc/hosts
cat > /target/usr/sbin/policy-rc.d <<'POLICY'
#!/bin/sh
exit 101
POLICY
chmod 755 /target/usr/sbin/policy-rc.d
chroot /target /bin/bash <<'CHROOT'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y grub-pc linux-image-amd64 linux-headers-amd64 build-essential dkms sudo lightdm xfce4
apt-get purge -y live-boot live-boot-initramfs-tools live-config live-config-systemd || exit 41
groupadd -r autologin || true
id sentra >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo,audio,video sentra
usermod -aG autologin,sudo,audio,video sentra || true
printf '%s' '@@SECRET@@' | base64 -d | chpasswd
printf 'sentra ALL=(ALL:ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/sentra
chmod 440 /etc/sudoers.d/sentra
mkdir -p /etc/lightdm/lightdm.conf.d /etc/default/grub.d
printf '%s\n' '[Seat:*]' 'autologin-user=sentra' 'autologin-user-timeout=0' 'user-session=xfce' > /etc/lightdm/lightdm.conf.d/60-sentra-dot.conf
printf '%s\n' 'GRUB_CMDLINE_LINUX_DEFAULT="tsc=unstable clocksource=acpi_pm nohz=off maxcpus=1"' 'GRUB_TIMEOUT=0' > /etc/default/grub.d/60-sentra-dot.cfg
systemctl enable lightdm
systemctl set-default graphical.target
mkdir -p /mnt/additions
additions_dev=""
for sr in /dev/sr2 /dev/sr1 /dev/sr0; do
    if [ -b "$sr" ]; then
        if blkid "$sr" 2>/dev/null | grep -qi 'VBOX'; then additions_dev="$sr"; break; fi
    fi
done
[ -n "$additions_dev" ] || additions_dev="/dev/sr2"
mount -o ro "$additions_dev" /mnt/additions
bash /mnt/additions/VBoxLinuxAdditions.run --nox11 || test -x /usr/sbin/VBoxService
umount /mnt/additions
systemctl enable vboxadd || true
systemctl enable vboxadd-service || true
update-initramfs -u -k all
grub-install --target=i386-pc /dev/sda
update-grub
rm /usr/sbin/policy-rc.d
CHROOT
cp /tmp/sentra-install.log /target/var/log/sentra-install.log
touch /target/etc/sentra-install-complete
sync
echo SENTRA_INSTALL_COMPLETE_POWEROFF
systemctl poweroff
'''.replace('@@ID@@', ident).replace('@@SHORT@@', ident[:8])
        .replace('@@CAPACITY@@', str(capacity)).replace('@@SECRET@@', secret)
        .replace('@@LEGACY_DMI@@', legacy_dmi)).encode()


def _require_hardware_uuid(info, vm_id):
    """Refuse installation if the host SMBIOS UUID source was overridden."""
    if str(info.get('hardwareuuid', '')).lower() != str(uuid.UUID(vm_id)):
        raise ValueError('VirtualBox hardware DMI UUID differs from owned VM')


def prepare(client, binding, cfg):
    info, disk = owned_storage(client, binding, cfg)
    _require_hardware_uuid(info, binding.vm_id)
    if (cfg['os_family'] != 'linux' or not Path(cfg['iso_path']).name.startswith('debian-live-13.')
            or not disk['empty_observed'] or info.get('VMState') not in {'poweroff', 'running'}):
        raise ValueError('exact empty owned Debian Live disk required')
    additions = Path(client.path).parent / 'VBoxGuestAdditions.iso'
    if not additions.is_file():
        raise ValueError('local Oracle Guest Additions ISO required')
    folder = Path(cfg['base_folder']) / cfg['name'] / 'bootstrap'
    if folder.exists():
        raise ValueError('bootstrap already prepared; inspect existing attempt, never replay')
    image = Path(cfg['iso_path']).resolve(strict=True)
    with image.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != cfg['iso_sha256']:
            raise ValueError('configured installation ISO changed')
    current_image = info.get('SATA-1-0')
    restore_image = info.get('VMState') == 'poweroff' and current_image == 'emptydrive'
    if not restore_image and Path(current_image or '').resolve() != image:
        raise ValueError('unexpected installation DVD; cannot replace foreign media')
    if any(info.get('SATA-%s-0' % port, 'none') != 'none' for port in (2, 3)):
        raise ValueError('seed drives already occupied; inspect existing attempt')
    if info.get('VMState') == 'running':
        if Path(info.get('SATA-1-0', '')).resolve() != Path(cfg['iso_path']).resolve():
            raise ValueError('only configured empty Live guest may be stopped for installation')
        client.run('controlvm', binding.vm_id, 'poweroff')
        for _ in range(20):
            if client.status(binding).get('VMState') == 'poweroff':
                break
            effect_checkpoint()
            time.sleep(.5)
        info, disk = owned_storage(client, binding, cfg)
        _require_hardware_uuid(info, binding.vm_id)
        if info.get('VMState') != 'poweroff' or not disk['empty_observed']:
            raise ValueError('poweroff and empty disk must be reconfirmed')
    if restore_image:
        # Prior Live shutdown ejected this configured DVD. Admission above is
        # restricted to the exact powered-off owned empty disk and ISO hash.
        client.run('storageattach', binding.vm_id, '--storagectl', 'SATA', '--port', 1,
            '--device', 0, '--type', 'dvddrive', '--medium', str(image))
    effect_checkpoint()
    _private_directory(folder)
    seed = folder / 'seed.iso'
    seed_iso(seed, {'INSTALL.SH': install_script(binding.vm_id, disk['capacity_bytes'], cfg['password'])})
    (folder / 'admission.json').write_text(json.dumps({'vm_id': binding.vm_id,
        'disk_uuid': disk['disk_uuid'], 'vdi_metadata_sha256': disk['metadata_sha256'],
        'seed_sha256': hashlib.sha256(seed.read_bytes()).hexdigest(), 'prepared_at': time.time()}))
    for port, medium in ((2, seed), (3, additions)):
        client.run('storageattach', binding.vm_id, '--storagectl', 'SATA', '--port', port,
            '--device', 0, '--type', 'dvddrive', '--medium', str(medium))
    return {'status': 'installation_seed_prepared', 'vm_id': binding.vm_id,
        'disk_uuid': disk['disk_uuid'], 'installed_os_verified': False, 'automatic_retry': False}


def ascii_batches(text):
    keys = dict(zip('1234567890', range(2, 12)))
    keys.update(dict(zip('qwertyuiop', range(16, 26))))
    keys.update(dict(zip('asdfghjkl', range(30, 39))))
    keys.update(dict(zip('zxcvbnm', range(44, 51))))
    keys.update({' ':57, '\n':28, '-':12, '=':13, '/':53, '.':52, ',':51, ';':39, "'":40})
    shifted = {'_':'-', ':':';', '"':"'", '|':'\\', '>':'.', '&':'7'}
    keys['\\'] = 43
    batch = []
    for char in text:
        shift = char in shifted or char.isupper()
        code = keys[shifted.get(char, char.lower())]
        scans = ([42] if shift else []) + [code, code | 128] + ([170] if shift else [])
        if len(batch) + len(scans) > 32:
            yield batch
            batch = []
        batch += scans
    if batch:
        yield batch


def launch(client, binding, cfg):
    info, disk = owned_storage(client, binding, cfg)
    _require_hardware_uuid(info, binding.vm_id)
    folder = Path(cfg['base_folder']) / cfg['name'] / 'bootstrap'
    seed = folder / 'seed.iso'
    admission = json.loads((folder / 'admission.json').read_text())
    if (info.get('VMState') != 'running' or not disk['empty_observed']
            or admission['vm_id'] != binding.vm_id or admission['disk_uuid'] != disk['disk_uuid']
            or admission['vdi_metadata_sha256'] != disk['metadata_sha256']
            or admission['seed_sha256'] != hashlib.sha256(seed.read_bytes()).hexdigest()
            or Path(info.get('SATA-2-0', '')).resolve() != seed.resolve()):
        raise ValueError('installation admission changed')
    # Exclusive durable intention survives partial delivery and blocks repeats.
    effect_checkpoint()
    with (folder / 'launch-intent.json').open('x') as handle:
        json.dump({'vm_id': binding.vm_id, 'started_at': time.time()}, handle)
    client.input(binding, {'action':'input.key', 'scancodes':[29,56,60,188,184,157]})
    time.sleep(2)
    for line in ('user\n', 'live\n', "sudo mkdir -p /mnt/sentra-seed\n",
                 'sudo mount -o ro /dev/sr1 /mnt/sentra-seed\n',
                 'sudo bash /mnt/sentra-seed/install.sh\n'):
        for scans in ascii_batches(line):
            effect_checkpoint()
            client.input(binding, {'action':'input.key', 'scancodes':scans})
            time.sleep(.05)
        time.sleep(2)
    return {'status':'installation_launch_sent', 'vm_id': binding.vm_id,
        'installed_os_verified':False, 'automatic_retry':False}


def reconcile_failed_attempt(client, binding, cfg, *, evidence=None, detach_storage=False, request_key=None):
    """Safely archive a prior failed installation attempt without data loss.

    Admitted ONLY when the current owned VDI is observed completely empty
    (allocated_blocks=0, no partition table, stable metadata) AND its metadata
    hash strictly matches admission.json of the attempt.
    Never deletes anything: moves the bootstrap directory to
    bootstrap-attempts/<timestamp>-<seed_hash_short>, writes reconciliation.json,
    and plans (or executes if detach_storage=True) detaching seed/GA media.
    Idempotent by request_key; fail-closed on any divergence.
    """
    info, disk = owned_storage(client, binding, cfg)
    _require_hardware_uuid(info, binding.vm_id)

    if evidence is not None:
        if (evidence.get('disk_uuid') != disk['disk_uuid']
                or evidence.get('metadata_sha256') != disk['metadata_sha256']
                or evidence.get('allocated_blocks') != disk['allocated_blocks']):
            raise ValueError('reconciliation refused: provided evidence diverges from current owned disk')

    if (disk.get('allocated_blocks') != 0
            or not disk.get('empty_observed')
            or disk.get('partition_table_observed')
            or not disk.get('metadata_stable')):
        raise ValueError('reconciliation refused: owned disk must be strictly empty and unpartitioned')

    base = Path(cfg['base_folder']).resolve()
    vm_dir = (base / cfg['name']).resolve()
    bootstrap_dir = vm_dir / 'bootstrap'
    attempts_dir = vm_dir / 'bootstrap-attempts'

    # Idempotent return if already reconciled
    if not bootstrap_dir.exists():
        if attempts_dir.is_dir():
            for receipt_file in sorted(attempts_dir.glob('*/reconciliation.json'), reverse=True):
                try:
                    saved = json.loads(receipt_file.read_text())
                    if (saved.get('vm_id') == binding.vm_id
                            and saved.get('disk_uuid') == disk['disk_uuid']
                            and saved.get('vdi_metadata_sha256') == disk['metadata_sha256']):
                        if request_key is None or saved.get('request_key') == request_key:
                            if detach_storage and not saved.get('storage_detached'):
                                if info.get('VMState') == 'running':
                                    if Path(info.get('SATA-1-0', '')).resolve() != Path(cfg['iso_path']).resolve():
                                        raise ValueError('only configured empty Live guest may be stopped for reconciliation')
                                    client.run('controlvm', binding.vm_id, 'poweroff')
                                    for _ in range(20):
                                        if client.status(binding).get('VMState') == 'poweroff':
                                            break
                                        effect_checkpoint()
                                        time.sleep(.5)
                                    info, disk = owned_storage(client, binding, cfg)
                                    _require_hardware_uuid(info, binding.vm_id)
                                    if info.get('VMState') != 'poweroff' or not disk['empty_observed']:
                                        raise ValueError('poweroff and empty disk must be reconfirmed before detaching storage')
                                effect_checkpoint()
                                for port in (2, 3):
                                    if info.get(f'SATA-{port}-0', 'none') != 'none':
                                        client.run('storageattach', binding.vm_id, '--storagectl', 'SATA',
                                                   '--port', port, '--device', 0, '--type', 'dvddrive', '--medium', 'none')
                                status_fn = getattr(client, 'status', None)
                                if status_fn is not None:
                                    after_info = status_fn(binding)
                                    if any(after_info.get(f'SATA-{p}-0', 'none') != 'none' for p in (2, 3)):
                                        raise ValueError('failed to detach seed/additions storage')
                                saved['storage_detached'] = True
                                receipt_file.write_text(json.dumps(saved, indent=2))
                            return saved
                except Exception:
                    continue
        raise ValueError('reconciliation refused: no existing bootstrap attempt found to reconcile')

    admission_file = bootstrap_dir / 'admission.json'
    seed_file = bootstrap_dir / 'seed.iso'
    intent_file = bootstrap_dir / 'launch-intent.json'
    if not (admission_file.is_file() and seed_file.is_file() and intent_file.is_file()):
        raise ValueError('reconciliation refused: incomplete bootstrap attempt files')

    admission = json.loads(admission_file.read_text())
    intent = json.loads(intent_file.read_text())

    seed_sha256 = hashlib.sha256(seed_file.read_bytes()).hexdigest()
    if (admission.get('vm_id') != binding.vm_id
            or admission.get('disk_uuid') != disk['disk_uuid']
            or admission.get('vdi_metadata_sha256') != disk['metadata_sha256']
            or admission.get('seed_sha256') != seed_sha256):
        raise ValueError('reconciliation refused: admission metadata mismatch with current disk/seed')

    storage_detached = False
    actions_planned = ['detach_seed_sata_2', 'detach_guest_additions_sata_3']
    if detach_storage:
        if info.get('VMState') == 'running':
            if Path(info.get('SATA-1-0', '')).resolve() != Path(cfg['iso_path']).resolve():
                raise ValueError('only configured empty Live guest may be stopped for reconciliation')
            client.run('controlvm', binding.vm_id, 'poweroff')
            for _ in range(20):
                if client.status(binding).get('VMState') == 'poweroff':
                    break
                effect_checkpoint()
                time.sleep(.5)
            info, disk = owned_storage(client, binding, cfg)
            _require_hardware_uuid(info, binding.vm_id)
            if info.get('VMState') != 'poweroff' or not disk['empty_observed']:
                raise ValueError('poweroff and empty disk must be reconfirmed before detaching storage')
        effect_checkpoint()
        for port in (2, 3):
            if info.get(f'SATA-{port}-0', 'none') != 'none':
                client.run('storageattach', binding.vm_id, '--storagectl', 'SATA',
                           '--port', port, '--device', 0, '--type', 'dvddrive', '--medium', 'none')
        status_fn = getattr(client, 'status', None)
        if status_fn is not None:
            after_info = status_fn(binding)
            if any(after_info.get(f'SATA-{p}-0', 'none') != 'none' for p in (2, 3)):
                raise ValueError('failed to detach seed/additions storage')
        storage_detached = True

    _private_directory(attempts_dir)
    timestamp = int(intent.get('started_at') or admission.get('prepared_at') or time.time())
    seed_hash_short = admission['seed_sha256'][:8]
    target_dir = attempts_dir / f"{timestamp}-{seed_hash_short}"
    if target_dir.exists():
        target_dir = attempts_dir / f"{timestamp}-{seed_hash_short}-{uuid.uuid4().hex[:6]}"

    effect_checkpoint()
    bootstrap_dir.rename(target_dir)

    receipt = {
        'status': 'reconciled_failed_attempt',
        'reason': 'install_failed_before_partition',
        'vm_id': binding.vm_id,
        'disk_uuid': disk['disk_uuid'],
        'vdi_metadata_sha256': disk['metadata_sha256'],
        'allocated_blocks': disk['allocated_blocks'],
        'empty_observed': disk['empty_observed'],
        'partition_table_observed': disk['partition_table_observed'],
        'archived_attempt': str(target_dir),
        'archived_at': time.time(),
        'request_key': request_key,
        'previous_admission': admission,
        'previous_intent': intent,
        'actions_planned': actions_planned,
        'storage_detached': storage_detached,
    }
    (target_dir / 'reconciliation.json').write_text(json.dumps(receipt, indent=2))
    return receipt


def _reservation(cfg):
    family = cfg.get('os_family')
    cpus, memory, disk = cfg.get('cpus'), cfg.get('memory_mb'), cfg.get('disk_gb')
    minimum_cpu = 2 if family == 'windows' else 1
    minimum_memory = 4096 if family == 'windows' else 1024
    minimum_disk = 64 if family == 'windows' else 16
    if (family not in {'linux', 'windows'} or type(cpus) is not int or type(memory) is not int
            or type(disk) is not int or cpus < minimum_cpu or memory < minimum_memory
            or not minimum_disk <= disk <= 256):
        return {'reserved': False}
    return {'reserved': True, 'cpus': cpus, 'memory_mb': memory, 'disk_gb': disk}


def _observed(status, **extra):
    extra.pop('status', None)
    extra.pop('interface_action', None)
    result = {'physical_effects_performed': False, 'automatic_retry': False,
        'installed_os_verified': False, 'desktop_ready_verified': False, 'windows_usable': False,
        'activation_claimed': False, 'product_key_stored': False, 'created': False, **extra}
    result['status'] = status
    result['interface_action'] = 'installation.advance'
    return result


def advance(client, binding, cfg, *, confirm_launch=False):
    """One interface step toward a desktop. Never replays a recorded attempt.

    Creating the VM stays on provision. This admits the Debian user and desktop
    seed, or reports a Windows license, without a separate QA script.
    """
    from .virtualbox_installation import assess_windows_license, installation_plan, observational_install, verify_guest
    reservation = _reservation(cfg)
    if not reservation['reserved']:
        return _observed('resource_reservation_required', vm_id=binding.vm_id)
    if cfg.get('os_family') == 'windows':
        license_info = assess_windows_license(cfg)
        if not license_info['install_admitted']:
            return _observed('windows_license_not_admitted', vm_id=binding.vm_id, **license_info)
    if 'base_folder' not in cfg or 'name' not in cfg:
        raise ValueError('owned VM configuration required')
    bootstrap_dir = Path(cfg['base_folder']) / cfg['name'] / 'bootstrap'
    if (bootstrap_dir / 'launch-intent.json').is_file():
        observed = observational_install(cfg, binding.vm_id)
        if observed:
            return _observed('installed_guest_observed', **observed)
        return _observed('prior_attempt_not_replayed', vm_id=binding.vm_id)
    plan = installation_plan(client, binding, cfg)
    partitioned = bool((plan.get('disk') or {}).get('partition_table_observed'))
    if partitioned and plan.get('vm_state') == 'running':
        verified = verify_guest(client, binding, cfg)
        if cfg.get('os_family') == 'linux' and verified.get('desktop_ready_verified'):
            result = _observed('desktop_already_verified', **verified, resource_reservation=reservation)
            result['windows_usable'] = False
            return result
        if cfg.get('os_family') == 'windows':
            result = _observed(verified.get('status') or 'windows_guest_observed', **verified,
                resource_reservation=reservation)
            result['activation_claimed'] = False
            return result
    if (cfg.get('os_family') == 'linux' and (plan.get('disk') or {}).get('empty_observed')
            and plan.get('vm_state') == 'poweroff' and not bootstrap_dir.exists()):
        prepared = prepare(client, binding, cfg)
        return {**prepared, 'user_and_desktop_scripted': True, 'interface_action': 'installation.advance',
            'physical_effects_performed': True, 'automatic_retry': False, 'resource_reservation': reservation,
            'windows_usable': False, 'activation_claimed': False}
    if (bootstrap_dir / 'admission.json').is_file():
        if not confirm_launch:
            return _observed('launch_requires_distinct_admission', vm_id=binding.vm_id,
                resource_reservation=reservation)
        if plan.get('vm_state') == 'running' and (plan.get('disk') or {}).get('empty_observed'):
            launched = launch(client, binding, cfg)
            result = _observed(launched.get('status') or 'installation_launch_sent', **launched,
                resource_reservation=reservation)
            result['physical_effects_performed'] = True
            result['windows_usable'] = False
            return result
        return _observed('launch_preconditions_absent', vm_id=binding.vm_id, resource_reservation=reservation)
    if cfg.get('os_family') == 'windows':
        return _observed('windows_provision_required', vm_id=binding.vm_id, resource_reservation=reservation,
            license_posture=assess_windows_license(cfg)['posture'])
    return _observed('no_safe_interface_step', vm_id=binding.vm_id, plan_status=plan.get('status'),
        resource_reservation=reservation)

