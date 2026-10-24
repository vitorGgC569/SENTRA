"""Frozen broker crash during a synthetic terminal job; no UI or model calls.

The response to one input is deliberately discarded. The broker is killed
while that command waits on a private fixture gate. Recovery observes the
original receipt and process without sending the command again.
"""
from pathlib import Path
import argparse
import hashlib
import http.client
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sentra_canvas.broker import read_endpoint
from sentra_canvas.pty_client import PtyDaemonClient, DaemonPTY


def run(binary, proof_path, output):
    binary = binary.resolve(strict=True)
    output = output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'.tmp'):
        raise ValueError('Choose a new QA directory inside repository .tmp')
    output.mkdir(parents=True)
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    with binary.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert proof['executables'][binary.name]['sha256'] == digest
    state = output/'state/canvas'
    root = output/'project'
    root.mkdir()
    report = {'status': 'running', 'executable_sha256': digest,
              'source_snapshot_sha256': proof['source_snapshot_sha256'],
              'model_inference': False, 'ui_used': False, 'user_state_used': False,
              'fixture': 'PowerShell job; private filesystem completion gate',
              'input_submissions': 0, 'automatic_replay': False}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    process = endpoint = client = daemon_process = None
    owned = []
    gate = None

    def save():
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')

    def wait_for(check, timeout=30):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            value = check()
            if value:
                return value
            time.sleep(.1)
        raise TimeoutError('Owned fixture did not reach the expected checkpoint')

    def request(path, body=None):
        req = urllib.request.Request('http://127.0.0.1:'+str(endpoint.server_port)+path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': 'Bearer '+endpoint.secret, 'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'QA API {path} returned HTTP {exc.code}: '
                               + exc.read(2048).decode('utf-8', errors='replace')) from exc

    def boot():
        nonlocal process, endpoint
        # Keep the fixture owner alive across the crash. A kill-on-close QA Job
        # would intentionally kill descendants and would not model broker loss.
        process = subprocess.Popen([str(binary), '--broker', '--no-open', '--port', '0',
            '--root', str(root), '--state-dir', str(state)], cwd=binary.parent,
            env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1', 'SENTRA_PTY_DAEMON': '1'},
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        owned.append(process)
        def ready():
            if process.poll() is not None:
                raise RuntimeError('Owned frozen broker exited during startup')
            return read_endpoint(state)
        endpoint = wait_for(ready, 60)

    save()
    try:
        boot()
        ws = request('/api/workspaces', {'name': 'Frozen_crash_fixture'})['id']
        request('/api/run/control', {'ws': ws, 'action': 'resume'})
        workspace = Path(request('/api/workspace?ws='+ws)['workspace']['path']).resolve()
        assert workspace.is_relative_to(output)
        terminal = request('/api/terminals', {'ws': ws, 'name': 'Frozen_crash_fixture', 'shell': 'powershell'})
        ident = terminal['id']
        client = PtyDaemonClient(state/'pty-host')
        daemon_process = psutil.Process(client.call('health')['pid'])
        frame = request('/api/terminal/output?'+urllib.parse.urlencode({'ws': ws, 'id': ident}))
        row = next(r for r in client.call('inventory') if r['terminal_id'] == ident)
        original_pid, daemon_id = row['pid'], client.runtime_id
        nonce = uuid.uuid4().hex
        gate = workspace/'continue.flag'
        started, result = workspace/'started.txt', workspace/'result.json'
        command = ("Add-Content -LiteralPath 'started.txt' -Value '"+nonce+"'; "
            "while(-not (Test-Path -LiteralPath 'continue.flag')) { Start-Sleep -Milliseconds 100 }; "
            "$s=0; 1..200 | ForEach-Object { $s += $_ }; "
            "@{total=$s;count=200;token='"+nonce+"'} | ConvertTo-Json -Compress | "
            "Set-Content -LiteralPath 'result.json' -Encoding UTF8; Write-Output QA_JOB_DONE\r")
        key = 'headless-crash-'+nonce
        payload = {'terminal_id': ident, 'data': command, 'input_target': frame['input_target']}
        fingerprint = hashlib.sha256(json.dumps(['terminal_input', payload],
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        connection = http.client.HTTPConnection('127.0.0.1', endpoint.server_port, timeout=15)
        try:
            connection.request('POST', '/api/terminal/input',
                body=json.dumps({'ws': ws, 'id': ident, 'data': command,
                    'request_key': key, 'input_target': frame['input_target']}),
                headers={'Authorization': 'Bearer '+endpoint.secret, 'Content-Type': 'application/json'})
            report['input_submissions'] += 1
            # Do not read or use the response as an acknowledgement.
        finally:
            connection.close()
        wait_for(started.is_file)
        assert started.read_text(encoding='utf-8-sig').splitlines() == [nonce]
        assert not gate.exists() and not result.exists()
        runtime = psutil.Process(endpoint.pid)
        assert os.path.samefile(runtime.exe(), binary)
        assert runtime.pid == process.pid or process.pid in [p.pid for p in runtime.parents()]
        old_runtime = endpoint.runtime_id
        runtime.kill()
        runtime.wait(15)
        process.wait(20)
        endpoint = None
        assert client.runtime_id == daemon_id
        row = next(r for r in client.call('inventory') if r['terminal_id'] == ident)
        assert row['pid'] == original_pid and row['exit_code'] is None
        report.update(broker_killed_during_work=True, daemon_survived=True, same_worker_pid=True)
        save()
        boot()
        assert endpoint.runtime_id != old_runtime
        frame2 = request('/api/terminal/output?'+urllib.parse.urlencode({'ws': ws, 'id': ident}))
        assert frame2['input_target'] != frame['input_target'] and frame2['status'] == 'running'
        selector = {'ws': ws, 'id': ident, 'request_key': key, 'fingerprint': fingerprint}
        receipt = request('/api/terminal/input-status?'+urllib.parse.urlencode(selector))
        assert receipt['resolved'] is True and receipt['task_completion_verified'] is False
        assert not result.exists()
        ack = request('/api/terminal/input-ack', selector)
        assert ack['acknowledged'] is True
        gate.write_text('QA fixture release', encoding='utf-8')
        wait_for(result.is_file)
        observed = json.loads(result.read_text(encoding='utf-8-sig'))
        assert observed == {'count': 200, 'total': 20100, 'token': nonce}
        assert started.read_text(encoding='utf-8-sig').splitlines() == [nonce]
        report.update(status='passed', receipt_reconciled_without_resend=True,
                      receipt_did_not_claim_task_completion=True,
                      worker_completed_after_broker_reopen=True,
                      physical_command_count=1, independently_verified_total=20100,
                      result_sha256=hashlib.sha256(result.read_bytes()).hexdigest())
        request('/api/terminal/close', {'ws': ws, 'id': ident, 'confirm': True})
    except BaseException as exc:
        report.update(status='failed', error=type(exc).__name__+': '+str(exc), traceback=traceback.format_exc())
    finally:
        if gate is not None:
            gate.write_text('QA cleanup release', encoding='utf-8')
        if client is not None:
            try:
                for row in client.call('inventory'):
                    if row['exit_code'] is None:
                        DaemonPTY(client, row['workspace_id'], row['terminal_id'],
                            pid=row['pid'], runtime_id=row['runtime_id']).close()
                client.call('drain')
                client.call('stop_when_idle')
                report['owned_pty_shutdown_requested'] = True
            except Exception as exc:
                report['cleanup_error'] = type(exc).__name__
        if endpoint is not None:
            try:
                request('/api/runtime/shutdown', {'confirm': True})
            except OSError:
                pass
        for child in owned:
            try:
                child.wait(20)
            except subprocess.TimeoutExpired:
                from scripts.commander.build_windows import _terminate_process_tree
                _terminate_process_tree(child)
        report['owned_brokers_closed'] = all(p.poll() is not None for p in owned)
        if daemon_process is not None:
            deadline = time.monotonic()+12
            while time.monotonic()<deadline and daemon_process.is_running():
                time.sleep(.1)
            report['owned_daemon_closed'] = not daemon_process.is_running()
            if not report['owned_daemon_closed']:
                report.update(status='failed', error='Owned daemon cleanup was not verified')
        save()
    return 0 if report['status'] == 'passed' else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--proof', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.executable, args.proof, args.output))
