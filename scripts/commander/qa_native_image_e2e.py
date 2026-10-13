"""E2E proof script for ChatGPT Web native image generation -> Edge -> Relay -> Canvas.

Defaults to --dry-run: checks broker, relay, extension, quiescence and project readiness
WITHOUT creating WorkItems, submitting jobs or triggering ChatGPT generations.
Live execution (--execute) creates exactly ONE QA WorkItem/Operation, observes the
sentra.generated_asset receipt, fetches bytes via authenticated /api/shell/generated-media,
and verifies byte-for-byte SHA-256 integrity.
In case of uncertainty (UNCERTAIN / timeout / missing ACK): OBSERVE ONLY, NEVER RESEND.
"""
from __future__ import annotations

import argparse
import hashlib
import base64
import json
import time
import uuid
import urllib.parse
import urllib.error
import urllib.request
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentra_canvas.broker import read_endpoint
from scripts.commander.extension_identity import extension_source_identity


def get_broker_endpoint(root: Path):
    state_dir = (root / ".sentra" / "canvas").resolve()
    endpoint = read_endpoint(state_dir)
    return endpoint


def check_relay_health(relay_url: str = "http://127.0.0.1:8765"):
    try:
        with urllib.request.urlopen(f"{relay_url}/health", timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SENTRA ChatGPT Web Native Image E2E Probe")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                        help="Run read-only preflight without submitting any job (default)")
    parser.add_argument("--execute", dest="dry_run", action="store_false",
                        help="Execute single real QA image generation and fetch (Phase 2 only)")
    parser.add_argument("--relay-base", default="http://127.0.0.1:8765",
                        help="Relay base URL (default: http://127.0.0.1:8765)")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    endpoint = get_broker_endpoint(root)
    broker_ok = endpoint is not None
    broker_info = {}
    if broker_ok:
        try:
            health = endpoint.request("/api/health")
            broker_info = {
                "pid": endpoint.pid,
                "port": endpoint.server_port,
                "runtime_id_verified": health.get("runtime_id") == endpoint.runtime_id,
            }
        except Exception as exc:
            broker_ok = False
            broker_info = {"error": str(exc)}

    relay = check_relay_health(args.relay_base)
    relay_live = relay.get("ok") is True
    expected_outbox = hashlib.sha256(str((root / '.sentra/browser/relay.sqlite3').resolve()).casefold().encode()).hexdigest()
    outbox_matches = relay.get('outbox_identity') == expected_outbox
    extension = relay.get("extension") or {}
    extension_online = extension.get("online") is True

    source_hash = ""
    try:
        source_hash = extension_source_identity(root / "edge_extension")["source_hash"]
    except Exception:
        pass
    extension_build_match = (extension.get("status") or {}).get("sw_source_hash") == source_hash

    quiescent = (relay.get("queued", -1) == 0 and relay.get("leased", -1) == 0)
    workers_count = len(relay.get("workers_online") or [])

    ready_projects = []
    if broker_ok:
        try:
            headers = {"Authorization": f"Bearer {endpoint.secret}", "Content-Type": "application/json"}
            req = urllib.request.Request(f"http://127.0.0.1:{endpoint.server_port}/api/workspaces", headers=headers)
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=8) as r:
                workspaces = json.loads(r.read().decode())
            for ws in workspaces[:6]:
                pid = ws.get("id")
                bridge_req = urllib.request.Request(
                    f"http://127.0.0.1:{endpoint.server_port}/api/shell/bridge",
                    headers=headers,
                    data=json.dumps({"project_id": pid, "action": "home"}).encode()
                )
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(bridge_req, timeout=8) as br:
                    bdata = json.loads(br.read().decode())
                attach = (bdata.get("value") or {}).get("attachments") or {}
                collector_request = urllib.request.Request(f'http://127.0.0.1:{endpoint.server_port}/api/center/browser-evidence?ws=' + urllib.parse.quote(pid, safe=''), headers=headers)
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(collector_request, timeout=8) as response:
                    enrolled = json.load(response).get('collectors', [])
                collector_ready = any(row.get('extension_id') == extension.get('extension_id') and
                    row.get('enabled') and row.get('source_sha256') == source_hash for row in enrolled)
                if attach.get("model_delivery_available") is True and collector_ready:
                    ready_projects.append(pid)
        except Exception:
            pass

    if args.dry_run:
        report = {
            "mode": "dry_run",
            "broker_verified": broker_ok,
            "broker_info": broker_info,
            "relay_live": relay_live,
            "relay_outbox_matches_canvas": outbox_matches,
            "relay_web_send_configured": bool(relay.get("web_send_configured", False)),
            "relay_generated_assets_configured": bool(relay.get("generated_assets_configured", False)),
            "extension_online": extension_online,
            "extension_build_matches_checkout": extension_build_match,
            "quiescent": quiescent,
            "workers_online": workers_count,
            "ready_projects_count": len(ready_projects),
            "planned_action": "WOULD_CREATE_ONE_QA_OPERATION_AND_FETCH_GENERATED_MEDIA",
            "uncertainty_policy": "observe_only_no_resend",
            "admission_ready": (broker_ok and relay_live and outbox_matches and extension_online and extension_build_match and len(ready_projects) > 0),
        }
        print(json.dumps(report, indent=2))
        return 0 if report["admission_ready"] else 1

    # --- Phase 2 Live Execution Path ---
    if not (broker_ok and relay_live and outbox_matches and extension_online and extension_build_match and quiescent and len(ready_projects) > 0):
        print(json.dumps({
            "error": "preflight_failed_cannot_execute",
            "broker": broker_ok, "relay": relay_live,
            "outbox_matches": outbox_matches,
            "extension": extension_online, "quiescent": quiescent,
            "ready_projects": len(ready_projects),
        }))
        return 2

    # A fresh QA conversation selects native image generation explicitly.
    # No fabricated input attachment or SENTRA plugin mention is inserted in
    # the ChatGPT composer, and no existing CLI conversation is silently moved.
    from sentra_canvas.broker import _NoRedirect
    project = ready_projects[0]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    headers = {'Authorization': 'Bearer ' + endpoint.secret, 'Content-Type': 'application/json'}
    scope = {'project_id': project}
    def call(action, **fields):
        request = urllib.request.Request(f'http://127.0.0.1:{endpoint.server_port}/api/shell/bridge',
            headers=headers, data=json.dumps({'action':action, **scope,
                'request_key':'image-qa-' + uuid.uuid4().hex, **fields}).encode())
        with opener.open(request, timeout=60) as response:
            envelope = json.load(response)
        if envelope.get('ok') is not True: raise RuntimeError('unconfirmed bridge envelope')
        return envelope['value']
    scope['space_id'] = call('space_create', name='QA Imagem ' + uuid.uuid4().hex[:8])['space_id']
    dot = call('dot_create', name='QA Imagem nativa', role='specialist', model='sentra/chatgpt-web/gpt-6', effort='high')
    cid = call('conversation_create', dot_id=dot['dot_id'], title='QA: imagem nativa e transporte binário')['conversation_id']
    scope['conversation_id'] = cid
    sent = call('message_send', content='Gere uma imagem nativa do ChatGPT: uma fotografia de um cachorro pequeno num jardim. Use a ferramenta de geração de imagens; não desenhe com Python, SVG ou ferramentas de arquivos. Entregue a imagem gerada nesta resposta.', native_generation='image')
    report = {**scope, 'dot_id':dot['dot_id'], 'operation_id':sent['operation_id'],
        'work_item_id':sent['work_item_id'], 'status':'ADMITTED', 'automatic_retry':False,
        'model':dot['model'], 'effort':dot['effort'], 'source':'native_chatgpt_relay'}
    output = root / '.tmp' / ('native-image-e2e-' + uuid.uuid4().hex[:10] + '.json')
    def save(): output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    save(); print(json.dumps({'report':str(output), 'status':'ADMITTED'}), flush=True)
    call('turn_permission_grant', work_item_id=sent['work_item_id'], capabilities=['web:send'], ttl_seconds=600)
    started = time.monotonic()
    while time.monotonic() - started < 320:
        messages = call('message_list')['items']
        answers = [item for item in messages if item['role'] == 'assistant' and item.get('operation_id') == sent['operation_id']]
        if answers:
            answer = answers[-1]; assets = answer.get('generated_assets', [])
            if not assets:
                report.update(status='FINAL_WITHOUT_BINARY', generated_asset_verified=False); save()
                print(json.dumps({'report':str(output),'status':report['status']})); return 3
            verified = []
            for asset in assets:
                query = urllib.parse.urlencode({**scope,'message_id':answer['message_id'],'asset_id':asset['asset_id']})
                request = urllib.request.Request(f'http://127.0.0.1:{endpoint.server_port}/api/shell/generated-media?' + query, headers=headers)
                with opener.open(request, timeout=30) as response:
                    binary = response.read(20*1024*1024 + 1)
                    content_type = response.headers.get('Content-Type')
                if content_type != asset['mime_type'] or len(binary) != asset['byte_length'] or hashlib.sha256(binary).hexdigest() != asset['sha256']:
                    raise RuntimeError('generated binary MIME/size/hash mismatch')
                if content_type not in {'image/png','image/jpeg'}: continue
                from PIL import Image
                import io
                with Image.open(io.BytesIO(binary)) as image: image.verify()
                target = output.with_name(output.stem + '-' + asset['asset_id'] + ('.png' if content_type == 'image/png' else '.jpg'))
                target.write_bytes(binary)
                verified.append({'sha256':asset['sha256'],'byte_length':len(binary),'path':str(target)})
            report.update(status='BINARY_VERIFIED' if verified else 'NO_IMAGE_BINARY', images=verified,
                generated_asset_verified=bool(verified), message_id=answer['message_id']); save()
            print(json.dumps({'report':str(output),'status':report['status']}), flush=True)
            return 0 if verified else 3
        user = next((item for item in messages if item['message_id'] == sent['message_id']), None)
        if user and user['status'] in {'uncertain','unconfirmed','failed','rejected'}:
            report.update(status='UNCERTAIN_NO_RESEND', generated_asset_verified=False); save()
            print(json.dumps({'report':str(output),'status':report['status']}), flush=True); return 4
        time.sleep(2)
    report.update(status='OBSERVATION_TIMEOUT_NO_RESEND', generated_asset_verified=False); save()
    print(json.dumps({'report':str(output),'status':report['status']}), flush=True); return 4


if __name__ == "__main__":
    raise SystemExit(main())
