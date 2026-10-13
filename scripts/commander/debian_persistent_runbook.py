#!/usr/bin/env python3
"""SENTRA — Sequenciador auditável de instalação Debian persistente em VM Dot.

Garante a sequência:
  reconcile -> prepare -> launch -> observe (poweroff) -> configure_disk_boot -> boot -> verify_guest

Princípios rígidos:
- Modo padrão --dry-run (somente leitura, emite recibo de planejamento sem mutações).
- Flag explícita --execute necessária para qualquer mutação física.
- Sem retry automático em caso de incerteza (perda de observação = UNCERTAIN).
- Recibo JSON gravado em disco a cada passo da execução.
- Nunca imprime senhas ou segredos.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time
import uuid
repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from sentra_executors.virtualbox_vm import VirtualBoxClient, VirtualBoxBinding
from sentra_executors.virtualbox_bootstrap import prepare, launch, reconcile_failed_attempt
from sentra_executors.virtualbox_installation import owned_storage, configure_disk_boot, verify_guest


DEFAULT_VM_ID = 'fcd974cf-ccdc-5636-b7af-2f96024d5dde'
DEFAULT_VM_NAME = 'SENTRA-Dot-fcd974cfccdc5636'
DEFAULT_MARKER = 'SENTRA-DOT:fcd974cf-ccdc-5636-b7af-2f96024d5dde'
DEFAULT_ISO = 'Isos/debian-live-13.7.0-amd64-xfce.iso'
DEFAULT_BASE_FOLDER = '.sentra/durable/dot-vms'


def file_sha256(path: Path) -> str:
    path = Path(path).resolve()
    if not path.is_file():
        return ''
    if hasattr(hashlib, 'file_digest'):
        with path.open('rb') as f:
            return hashlib.file_digest(f, 'sha256').hexdigest()
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def load_dot_vm_config(vm_id: str, *, durable_root: Path | str = None) -> dict:
    """Load the protected Dot VM configuration from the Canvas store by VM UUID.

    Unseals the DPAPI-protected record to obtain the real secret credentials
    without exposing them. Fail-closed if record or password is not found.
    """
    import sqlite3
    from sentra_core.conversations import _decode
    if durable_root is None:
        db_path = Path('.sentra/durable/shell.sqlite3').resolve()
    else:
        db_path = Path(durable_root).resolve() / 'shell.sqlite3'
    if not db_path.is_file():
        raise FileNotFoundError(f"Canvas shell database not found: {db_path}")

    with sqlite3.connect(str(db_path)) as db:
        rows = db.execute("SELECT owner, project, root, body FROM shell_dot_vms").fetchall()
        for owner, project, root, body in rows:
            try:
                record = _decode(body)
                if record.get('vm_id') == str(vm_id):
                    if not record.get('password'):
                        raise ValueError(f"Dot VM record {vm_id} has no configured password")
                    return record
            except Exception as exc:
                if 'unprotected conversation data' in str(exc):
                    continue
                raise
    raise KeyError(f"Dot VM record for VM ID {vm_id} not found in Canvas store")


def _write_receipt(receipts_dir: Path, filename: str, data: dict) -> Path:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    target = receipts_dir / filename
    target.write_text(json.dumps(data, indent=2, sort_keys=True))
    return target


def _step_7_verify_and_summary(client, binding, cfg, summary, receipts_dir, execute, verify_timeout):
    # -------------------------------------------------------------
    # PASSO 7: VERIFY GUEST
    # -------------------------------------------------------------
    print("--- [Passo 7/7] Verify Guest ---")
    step_7 = {'name': 'verify_guest', 'mode': summary['mode'], 'started_at': time.time()}
    try:
        if not execute:
            step_7['status'] = 'dry_run_verify_guest_planned'
            step_7['planned_probes'] = [
                'wait_for_guestcontrol_authenticated_channel',
                'verify_installed_root_ext4_sda1',
                'verify_not_live_overlay',
                'verify_sentra_dot_vm_id',
                'verify_lightdm_active',
                'verify_xfce4_session_running',
            ]
            receipt_path = _write_receipt(receipts_dir, '07-verify-guest-dryrun.json', step_7)
        else:
            deadline = time.time() + verify_timeout
            verified = None
            while time.time() < deadline:
                try:
                    res = verify_guest(client, binding, cfg)
                    if res.get('installed_os_verified') and res.get('desktop_ready_verified'):
                        verified = res
                        break
                except Exception:
                    pass
                time.sleep(5)

            if verified:
                step_7.update(verified)
                receipt_path = _write_receipt(receipts_dir, '07-verify-guest.json', step_7)
            else:
                step_7['status'] = 'verification_unconfirmed'
                step_7['installed_os_verified'] = False
                step_7['desktop_ready_verified'] = False
                receipt_path = _write_receipt(receipts_dir, '07-verify-guest-unconfirmed.json', step_7)

        step_7['completed_at'] = time.time()
        step_7['receipt_file'] = str(receipt_path)
        summary['steps']['verify_guest'] = step_7
        print(f"Passo 7 concluído: {step_7['status']} (recibo: {receipt_path.name})\n")
    except Exception as exc:
        step_7['status'] = 'failed'
        step_7['error'] = str(exc)
        step_7['completed_at'] = time.time()
        summary['steps']['verify_guest'] = step_7
        summary['status'] = 'failed'
        _write_receipt(receipts_dir, '07-verify-guest-error.json', step_7)
        _write_receipt(receipts_dir, 'runbook-summary.json', summary)
        print(f"ERRO no Passo 7: {exc}")
        return summary

    # -------------------------------------------------------------
    # RESUMO FINAL
    # -------------------------------------------------------------
    summary['completed_at'] = time.time()
    summary['duration_seconds'] = round(summary['completed_at'] - summary['started_at'], 2)
    if execute:
        v = summary['steps'].get('verify_guest', {})
        if v.get('installed_os_verified') and v.get('desktop_ready_verified'):
            summary['status'] = 'SUCCEEDED'
        else:
            summary['status'] = 'COMPLETED_VERIFICATION_PENDING'
    else:
        summary['status'] = 'DRY_RUN_PLAN_COMPLETE'

    summary_file = _write_receipt(receipts_dir, 'runbook-summary.json', summary)
    print(f"=== Sequência finalizada com status: {summary['status']} ===")
    print(f"Resumo gravado em: {summary_file}\n")
    return summary


def run_sequence(client, binding, cfg, *, execute=False, receipts_dir=None,
                 observe_timeout=1800, poll_interval=5, verify_timeout=180,
                 readiness_timeout=300, settling_delay=35,
                 request_key=None, verify_only=False):
    """Executa ou planeja (dry-run) a sequência completa de instalação persistente."""
    run_id = f"runbook-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    if request_key is None:
        request_key = run_id

    base = Path(cfg.get('base_folder', DEFAULT_BASE_FOLDER)).resolve()
    vm_dir = (base / cfg.get('name', DEFAULT_VM_NAME)).resolve()
    if receipts_dir is None:
        receipts_dir = vm_dir / 'runbook-receipts'
    else:
        receipts_dir = Path(receipts_dir).resolve()

    summary = {
        'run_id': run_id,
        'request_key': request_key,
        'mode': 'verify-only' if verify_only else ('execute' if execute else 'dry-run'),
        'started_at': time.time(),
        'vm_id': binding.vm_id,
        'steps': {},
        'status': 'in_progress',
    }

    print(f"=== SENTRA Debian Persistent Runbook [{summary['mode'].upper()}] ===")
    print(f"Run ID: {run_id}")
    print(f"VM ID: {binding.vm_id}")
    print(f"Receipts Directory: {receipts_dir}\n")

    if verify_only:
        print("--- [Passos 1 a 6] Preservados / Carregados de Recibos ---")
        for step_idx, step_name, receipt_fname in [
            (1, 'reconcile', '01-reconcile.json'),
            (2, 'prepare', '02-prepare.json'),
            (3, 'launch', '03-launch.json'),
            (4, 'observe_installation', '04-observe.json'),
            (5, 'configure_disk_boot', '05-configure-disk-boot.json'),
            (6, 'boot', '06-boot.json'),
        ]:
            rf = receipts_dir / receipt_fname
            if rf.is_file():
                summary['steps'][step_name] = json.loads(rf.read_text())
                print(f"Passo {step_idx} carregado: {summary['steps'][step_name].get('status')} ({receipt_fname})")
        print()
        return _step_7_verify_and_summary(client, binding, cfg, summary, receipts_dir, True, verify_timeout)

    # -------------------------------------------------------------
    # PASSO 1: RECONCILE
    # -------------------------------------------------------------
    print("--- [Passo 1/7] Reconcile ---")
    step_1 = {'name': 'reconcile', 'mode': summary['mode'], 'started_at': time.time()}
    try:
        if not execute:
            # Em modo dry-run: inspeção estritamente somente leitura
            info, disk = owned_storage(client, binding, cfg)
            bootstrap_dir = vm_dir / 'bootstrap'
            step_1['preflight'] = {
                'vm_state': info.get('VMState'),
                'hardwareuuid_matches': info.get('hardwareuuid', '').lower() == binding.vm_id.lower(),
                'disk_empty': disk.get('empty_observed'),
                'allocated_blocks': disk.get('allocated_blocks'),
                'partition_table_observed': disk.get('partition_table_observed'),
                'bootstrap_exists': bootstrap_dir.exists(),
            }
            if bootstrap_dir.exists():
                adm = json.loads((bootstrap_dir / 'admission.json').read_text())
                step_1['preflight']['admission_disk_uuid_matches'] = (adm.get('disk_uuid') == disk.get('disk_uuid'))
                step_1['preflight']['admission_vdi_sha256_matches'] = (adm.get('vdi_metadata_sha256') == disk.get('metadata_sha256'))
            step_1['status'] = 'dry_run_reconcile_planned'
            step_1['planned_actions'] = ['archive_bootstrap_directory', 'detach_sata_2_seed', 'detach_sata_3_additions']
            receipt_path = _write_receipt(receipts_dir, '01-reconcile-dryrun.json', step_1)
        else:
            # Em modo execute: reconciliação real
            receipt = reconcile_failed_attempt(client, binding, cfg, detach_storage=True, request_key=request_key)
            step_1.update(receipt)
            receipt_path = _write_receipt(receipts_dir, '01-reconcile.json', step_1)

        step_1['completed_at'] = time.time()
        step_1['receipt_file'] = str(receipt_path)
        summary['steps']['reconcile'] = step_1
        print(f"Passo 1 concluído: {step_1['status']} (recibo: {receipt_path.name})\n")
    except Exception as exc:
        step_1['status'] = 'failed'
        step_1['error'] = str(exc)
        step_1['completed_at'] = time.time()
        summary['steps']['reconcile'] = step_1
        summary['status'] = 'failed'
        _write_receipt(receipts_dir, '01-reconcile-error.json', step_1)
        _write_receipt(receipts_dir, 'runbook-summary.json', summary)
        print(f"ERRO no Passo 1: {exc}")
        return summary

    # -------------------------------------------------------------
    # PASSO 2: PREPARE
    # -------------------------------------------------------------
    print("--- [Passo 2/7] Prepare ---")
    step_2 = {'name': 'prepare', 'mode': summary['mode'], 'started_at': time.time()}
    try:
        iso_file = Path(cfg['iso_path']).resolve()
        if not iso_file.is_file():
            raise FileNotFoundError(f"ISO não encontrada: {iso_file}")
        additions_iso = Path(client.path).parent / 'VBoxGuestAdditions.iso'
        if not additions_iso.is_file():
            raise FileNotFoundError(f"VBoxGuestAdditions.iso não encontrada: {additions_iso}")

        if not execute:
            step_2['status'] = 'dry_run_prepare_planned'
            step_2['iso_path'] = str(iso_file)
            step_2['additions_iso'] = str(additions_iso)
            step_2['planned_actions'] = ['build_seed_iso_with_dmi_readback_and_autologin', 'attach_sata_2_seed', 'attach_sata_3_additions']
            receipt_path = _write_receipt(receipts_dir, '02-prepare-dryrun.json', step_2)
        else:
            res = prepare(client, binding, cfg)
            step_2.update(res)
            receipt_path = _write_receipt(receipts_dir, '02-prepare.json', step_2)

        step_2['completed_at'] = time.time()
        step_2['receipt_file'] = str(receipt_path)
        summary['steps']['prepare'] = step_2
        print(f"Passo 2 concluído: {step_2['status']} (recibo: {receipt_path.name})\n")
    except Exception as exc:
        step_2['status'] = 'failed'
        step_2['error'] = str(exc)
        step_2['completed_at'] = time.time()
        summary['steps']['prepare'] = step_2
        summary['status'] = 'failed'
        _write_receipt(receipts_dir, '02-prepare-error.json', step_2)
        _write_receipt(receipts_dir, 'runbook-summary.json', summary)
        print(f"ERRO no Passo 2: {exc}")
        return summary

    # -------------------------------------------------------------
    # PASSO 3: LAUNCH
    # -------------------------------------------------------------
    print("--- [Passo 3/7] Launch ---")
    step_3 = {'name': 'launch', 'mode': summary['mode'], 'started_at': time.time()}
    try:
        if not execute:
            step_3['status'] = 'dry_run_launch_planned'
            step_3['planned_actions'] = [
                'ensure_vm_running_live',
                'wait_guest_additions_runlevel_at_least_1',
                'settling_delay_before_key_injection',
                'record_launch_intent',
                'send_terminal_mount_and_execute_seed_scancodes',
            ]
            receipt_path = _write_receipt(receipts_dir, '03-launch-dryrun.json', step_3)
        else:
            info = client.status(binding)
            if info.get('VMState') != 'running':
                client.run('startvm', binding.vm_id, '--type', 'headless')
                for _ in range(30):
                    time.sleep(1)
                    info = client.status(binding)
                    if info.get('VMState') == 'running':
                        break
                if info.get('VMState') != 'running':
                    raise RuntimeError("VM failed to reach running state for launch")

            # Espera de prontidão observável ANTES de launch(): GuestAdditionsRunLevel >= 1
            print(f"Aguardando prontidão observável do Debian Live (GuestAdditionsRunLevel >= 1, timeout={readiness_timeout}s)...")
            deadline = time.time() + readiness_timeout
            live_ready = False
            while time.time() < deadline:
                info = client.status(binding)
                runlevel = int(info.get('GuestAdditionsRunLevel', 0))
                if runlevel >= 1:
                    live_ready = True
                    break
                time.sleep(2)

            if not live_ready:
                step_3['status'] = 'failed_not_started'
                step_3['error'] = f'Debian Live não atingiu prontidão observável (GuestAdditionsRunLevel >= 1) em {readiness_timeout}s'
                receipt_path = _write_receipt(receipts_dir, '03-launch-not-started.json', step_3)
                summary['steps']['launch'] = step_3
                summary['status'] = 'failed'
                _write_receipt(receipts_dir, 'runbook-summary.json', summary)
                print(f"ERRO no Passo 3: {step_3['error']} (sem gravação de launch-intent)")
                return summary

            # Atraso de assentamento para garantia de login/console prontos
            if settling_delay > 0:
                print(f"Aguardando assentamento do console Live ({settling_delay}s)...")
                time.sleep(settling_delay)

            res = launch(client, binding, cfg)
            step_3.update(res)
            receipt_path = _write_receipt(receipts_dir, '03-launch.json', step_3)

        step_3['completed_at'] = time.time()
        step_3['receipt_file'] = str(receipt_path)
        summary['steps']['launch'] = step_3
        print(f"Passo 3 concluído: {step_3['status']} (recibo: {receipt_path.name})\n")
    except Exception as exc:
        step_3['status'] = 'failed'
        step_3['error'] = str(exc)
        step_3['completed_at'] = time.time()
        summary['steps']['launch'] = step_3
        summary['status'] = 'failed'
        _write_receipt(receipts_dir, '03-launch-error.json', step_3)
        _write_receipt(receipts_dir, 'runbook-summary.json', summary)
        print(f"ERRO no Passo 3: {exc}")
        return summary

    # -------------------------------------------------------------
    # PASSO 4: OBSERVE INSTALLATION (POWEROFF CONFIRMATION)
    # -------------------------------------------------------------
    print("--- [Passo 4/7] Observe Installation ---")
    step_4 = {'name': 'observe_installation', 'mode': summary['mode'], 'started_at': time.time()}
    try:
        if not execute:
            step_4['status'] = 'dry_run_observe_planned'
            step_4['timeout_seconds'] = observe_timeout
            step_4['poll_interval_seconds'] = poll_interval
            step_4['target_state'] = 'poweroff'
            step_4['note'] = 'observation will monitor VM until confirmed shutdown, failing to UNCERTAIN on timeout with automatic_retry=False'
            receipt_path = _write_receipt(receipts_dir, '04-observe-dryrun.json', step_4)
        else:
            deadline = time.time() + observe_timeout
            poweroff_observed = False
            last_state = None
            while time.time() < deadline:
                try:
                    info = client.status(binding)
                    last_state = info.get('VMState')
                    if last_state == 'poweroff':
                        poweroff_observed = True
                        break
                except Exception as poll_exc:
                    last_state = f"poll_error: {poll_exc}"
                time.sleep(poll_interval)

            if poweroff_observed:
                step_4['status'] = 'poweroff_confirmed'
                step_4['vm_state'] = 'poweroff'
                receipt_path = _write_receipt(receipts_dir, '04-observe.json', step_4)
            else:
                step_4['status'] = 'uncertain_loss_of_observation'
                step_4['last_state'] = last_state
                step_4['timeout_seconds'] = observe_timeout
                step_4['automatic_retry'] = False
                receipt_path = _write_receipt(receipts_dir, '04-observe.json', step_4)
                summary['steps']['observe_installation'] = step_4
                summary['status'] = 'UNCERTAIN'
                _write_receipt(receipts_dir, 'runbook-summary.json', summary)
                print(f"UNCERTAIN: tempo limite atingido sem confirmação de poweroff. Sem retry automático.")
                return summary

        step_4['completed_at'] = time.time()
        step_4['receipt_file'] = str(receipt_path)
        summary['steps']['observe_installation'] = step_4
        print(f"Passo 4 concluído: {step_4['status']} (recibo: {receipt_path.name})\n")
    except Exception as exc:
        step_4['status'] = 'UNCERTAIN'
        step_4['error'] = str(exc)
        step_4['automatic_retry'] = False
        step_4['completed_at'] = time.time()
        summary['steps']['observe_installation'] = step_4
        summary['status'] = 'UNCERTAIN'
        _write_receipt(receipts_dir, '04-observe-error.json', step_4)
        _write_receipt(receipts_dir, 'runbook-summary.json', summary)
        print(f"ERRO / UNCERTAIN no Passo 4: {exc}")
        return summary

    # -------------------------------------------------------------
    # PASSO 5: CONFIGURE DISK BOOT
    # -------------------------------------------------------------
    print("--- [Passo 5/7] Configure Disk Boot ---")
    step_5 = {'name': 'configure_disk_boot', 'mode': summary['mode'], 'started_at': time.time()}
    try:
        if not execute:
            step_5['status'] = 'dry_run_configure_disk_boot_planned'
            step_5['planned_actions'] = [
                'modifyvm_boot1_disk_boot2_none',
                'detach_sata_1_live_iso',
                'detach_sata_2_seed',
                'detach_sata_3_additions',
            ]
            receipt_path = _write_receipt(receipts_dir, '05-configure-disk-boot-dryrun.json', step_5)
        else:
            res = configure_disk_boot(client, binding, cfg)
            step_5.update(res)
            receipt_path = _write_receipt(receipts_dir, '05-configure-disk-boot.json', step_5)

        step_5['completed_at'] = time.time()
        step_5['receipt_file'] = str(receipt_path)
        summary['steps']['configure_disk_boot'] = step_5
        print(f"Passo 5 concluído: {step_5['status']} (recibo: {receipt_path.name})\n")
    except Exception as exc:
        step_5['status'] = 'failed'
        step_5['error'] = str(exc)
        step_5['completed_at'] = time.time()
        summary['steps']['configure_disk_boot'] = step_5
        summary['status'] = 'failed'
        _write_receipt(receipts_dir, '05-configure-disk-boot-error.json', step_5)
        _write_receipt(receipts_dir, 'runbook-summary.json', summary)
        print(f"ERRO no Passo 5: {exc}")
        return summary

    # -------------------------------------------------------------
    # PASSO 6: BOOT
    # -------------------------------------------------------------
    print("--- [Passo 6/7] Boot ---")
    step_6 = {'name': 'boot', 'mode': summary['mode'], 'started_at': time.time()}
    try:
        if not execute:
            step_6['status'] = 'dry_run_boot_planned'
            step_6['planned_actions'] = ['startvm_headless_from_installed_disk', 'confirm_vm_running']
            receipt_path = _write_receipt(receipts_dir, '06-boot-dryrun.json', step_6)
        else:
            client.run('startvm', binding.vm_id, '--type', 'headless')
            running_confirmed = False
            for _ in range(30):
                info = client.status(binding)
                if info.get('VMState') == 'running':
                    running_confirmed = True
                    break
                time.sleep(1)
            if not running_confirmed:
                raise RuntimeError("VM failed to reach running state after disk boot")
            step_6['status'] = 'boot_running_confirmed'
            step_6['vm_state'] = 'running'
            receipt_path = _write_receipt(receipts_dir, '06-boot.json', step_6)

        step_6['completed_at'] = time.time()
        step_6['receipt_file'] = str(receipt_path)
        summary['steps']['boot'] = step_6
        print(f"Passo 6 concluído: {step_6['status']} (recibo: {receipt_path.name})\n")
    except Exception as exc:
        step_6['status'] = 'failed'
        step_6['error'] = str(exc)
        step_6['completed_at'] = time.time()
        summary['steps']['boot'] = step_6
        summary['status'] = 'failed'
        _write_receipt(receipts_dir, '06-boot-error.json', step_6)
        _write_receipt(receipts_dir, 'runbook-summary.json', summary)
        print(f"ERRO no Passo 6: {exc}")
        return summary

    return _step_7_verify_and_summary(client, binding, cfg, summary, receipts_dir, execute, verify_timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description="SENTRA Debian Persistent Runbook")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--dry-run', action='store_true', default=True, help="Planejamento e validação somente leitura (padrão)")
    group.add_argument('--execute', action='store_true', default=False, help="Execução física dos passos autorizados")
    group.add_argument('--verify-only', action='store_true', default=False, help="Execução de verificação pós-boot no guest instalado")

    parser.add_argument('--vm-id', default=DEFAULT_VM_ID, help="UUID da VM Dot")
    parser.add_argument('--vm-name', default=DEFAULT_VM_NAME, help="Nome da VM")
    parser.add_argument('--marker', default=DEFAULT_MARKER, help="Marker de auditoria")
    parser.add_argument('--iso-path', default=DEFAULT_ISO, help="Caminho da ISO Live")
    parser.add_argument('--base-folder', default=DEFAULT_BASE_FOLDER, help="Pasta base das VMs")
    parser.add_argument('--receipts-dir', default=None, help="Diretório de recibos JSON")
    parser.add_argument('--observe-timeout', type=int, default=1800, help="Tempo limite de observação da instalação (s)")
    parser.add_argument('--verify-timeout', type=int, default=180, help="Tempo limite de verificação pós-boot (s)")
    parser.add_argument('--readiness-timeout', type=int, default=300, help="Tempo limite para prontidão observável da Live (s)")
    parser.add_argument('--settling-delay', type=int, default=35, help="Atraso de assentamento antes de scancodes (s)")

    args = parser.parse_args(argv)
    verify_only_mode = bool(args.verify_only)
    execute_mode = bool(args.execute) or verify_only_mode

    iso_path = Path(args.iso_path).resolve()
    iso_sha256 = file_sha256(iso_path)

    # Carrega a configuração real unsealed do Dot no Canvas store
    durable_dir = Path(args.base_folder).resolve().parent
    record = load_dot_vm_config(args.vm_id, durable_root=durable_dir)

    cfg = {
        'base_folder': str(Path(record.get('base_folder') or args.base_folder).resolve()),
        'name': record.get('name') or args.vm_name,
        'disk_gb': int(record.get('disk_gb') or 64),
        'os_family': record.get('os_family') or 'linux',
        'iso_path': str(Path(record.get('iso_path') or iso_path).resolve()),
        'iso_sha256': record.get('iso_sha256') or iso_sha256,
        'password': record['password'],
    }

    client = VirtualBoxClient()
    binding = VirtualBoxBinding(args.vm_id, record.get('marker') or args.marker, lambda: cfg)

    result = run_sequence(
        client, binding, cfg,
        execute=execute_mode,
        receipts_dir=args.receipts_dir,
        observe_timeout=args.observe_timeout,
        verify_timeout=args.verify_timeout,
        readiness_timeout=args.readiness_timeout,
        settling_delay=args.settling_delay,
        verify_only=verify_only_mode,
    )
    return 0 if result.get('status') in {'DRY_RUN_PLAN_COMPLETE', 'SUCCEEDED'} else 1


if __name__ == '__main__':
    sys.exit(main())
