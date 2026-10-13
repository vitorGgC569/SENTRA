"""Read-only inspection of the existing SENTRA Canvas broker and Web availability.

Never prints bearer credentials, prompts, conversation content or identity.
Never sends a Web job or starts/restarts a broker.
"""
from __future__ import annotations
import hashlib
import json
import urllib.request
import urllib.error
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from sentra_canvas.broker import read_endpoint
endpoint=read_endpoint((root/'.sentra'/'canvas').resolve())
if endpoint is None:
    print(json.dumps({'canvas_broker':'unavailable'}))
    raise SystemExit(2)

def call(route, body=None):
    headers={'Authorization':'Bearer '+endpoint.secret, 'Content-Type':'application/json'}
    request=urllib.request.Request('http://127.0.0.1:'+str(endpoint.server_port)+route,
        headers=headers, data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=12) as response:
        return json.loads(response.read(1200000))

health=endpoint.request('/api/health')
print(json.dumps({'canvas_broker':'verified','pid':endpoint.pid,'port':endpoint.server_port,
    'runtime_id_verified':health.get('runtime_id')==endpoint.runtime_id}))
from scripts.commander.extension_identity import extension_source_identity
with urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=5) as response:
    relay=json.loads(response.read(65536))
extension=(relay.get('extension') or {})
source_hash=extension_source_identity(root/'edge_extension')['source_hash']
expected_outbox=hashlib.sha256(str((root/'.sentra/browser/relay.sqlite3').resolve()).casefold().encode()).hexdigest()
outbox_matches=relay.get('outbox_identity')==expected_outbox
print(json.dumps({'relay_live':relay.get('ok') is True,
    'relay_outbox_matches_canvas':outbox_matches,
    'relay_web_send_configured': relay.get('web_send_configured') is True,
    'relay_generated_assets_configured': relay.get('generated_assets_configured') is True,
    'relay_queued':relay.get('queued'),'relay_leased':relay.get('leased'),
    'extension_online':extension.get('online'),
    'extension_build_matches_checkout':(extension.get('status') or {}).get('sw_source_hash')==source_hash,
    'online_workers':len(relay.get('workers_online') or []),
    'worker_adoption':'lazy_on_pending_job'}))
projects=call('/api/workspaces')
ready_projects=0
print('project_count',len(projects))
for p in projects[:12]:
    ident=p['id']
    tag=hashlib.sha256(ident.encode()).hexdigest()[:10]
    try:
        result=call('/api/shell/bridge',{'project_id':ident,'action':'home'})
        if not result.get('ok'):
            print(json.dumps({'project_tag':tag,'status':'denied'}))
            continue
        data=result.get('value') or {}
        attach=data.get('attachments') or {}
        from urllib.parse import quote
        evidence=call('/api/center/browser-evidence?ws='+quote(ident,safe=''))
        collector_ready=any(row.get('extension_id')==extension.get('extension_id') and
            row.get('enabled') and row.get('source_sha256')==source_hash for row in evidence.get('collectors',[]))
        if attach.get('model_delivery_available') is True and collector_ready:
            ready_projects+=1
        print(json.dumps({'project_tag':tag,'status':'readable',
            'relay_ready':attach.get('model_delivery_available'),
            'collector_enrolled_for_project':collector_ready,
            'relay_reason':attach.get('model_delivery_reason'),
            'run_state':(data.get('run') or {}).get('state'),
            'dot_count':len(data.get('dots') or []),
            'conversation_count':len(data.get('conversations') or [])}))
    except Exception as exc:
        print(json.dumps({'project_tag':tag,'status':'error',
            'error_class':type(exc).__name__}))
admission_ready=(ready_projects > 0 and relay.get('ok') is True and outbox_matches
    and extension.get('online') is True
    and (extension.get('status') or {}).get('sw_source_hash')==source_hash)
# A production browser worker is adopted lazily, after a real job is queued.
# Zero workers with zero jobs is NOT an admission fault.
print(json.dumps({'production_native_asset_admission_ready':admission_ready,
    'reason':None if admission_ready else 'missing Canvas authenticated Web relay/host attestor composition',
    'real_image_generation_attempted':False,
    'real_generated_asset_receipt_verified':False}))
if not admission_ready:
    raise SystemExit(4)
