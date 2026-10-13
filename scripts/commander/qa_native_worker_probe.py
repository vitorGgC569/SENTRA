"""Single-shot authenticated, read-only browser worker adoption probe.

Never sends to ChatGPT, changes navigation, reads chat text or prints secrets.
Cancels only its own pending diagnostic job if no eligible inactive tab appears.
"""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler
from native_bridge.settings import relay_settings

root=Path(__file__).resolve().parents[2]
token,_,_=relay_settings(root)
base="http://127.0.0.1:8765"
opener=build_opener(ProxyHandler({}))

def request(path, payload=None):
    headers={"Authorization":"Bearer "+token}
    data=None
    if payload is not None:
        headers["Content-Type"]="application/json"
        data=json.dumps(payload,separators=(",",":")).encode()
    from urllib.error import HTTPError
    try:
        with opener.open(Request(base+path, data=data, headers=headers), timeout=7) as response:
            return json.loads(response.read(65536))
    except HTTPError as exc:
        issue=json.loads(exc.read(4096))
        print(json.dumps({"http_status":exc.code,"reason":str(issue.get("error") or "denied")[:160]}))
        raise

health=request("/health")
if health.get("queued") != 0 or health.get("leased") != 0 or health.get("extension",{}).get("online") is not True:
    print(json.dumps({"status":"ABORTED","reason":"relay_busy_or_extension_offline"}))
    raise SystemExit(3)

task_id="qa-native-readonly-"+uuid.uuid4().hex
job_id=None
try:
    submitted=request("/jobs/submit",{
        "kind":"BROWSER_ACTION","task_id":task_id,"provider":"chatgpt",
        "browser_action":"extract","browser_args":{"selector":"html","max_chars":1},
        "new_chat":False,"timeout_s":35})
    job_id=submitted["job_id"]
    print(json.dumps({"status":"READONLY_SUBMITTED","job_ref":job_id[:12]}),flush=True)
    outcome=None
    for _ in range(5):
        answer=request("/jobs/wait?job_id="+quote(job_id,safe="")+"&timeout_s=4")
        if not answer.get("pending"):
            outcome=answer
            break
    if outcome:
        print(json.dumps({"status":"OBSERVED",
            "job_status":outcome.get("status"),
            "browser_worker_seen":str(outcome.get("worker") or "").startswith("BROWSER_WORKER_"),
            "result_present":bool(outcome.get("result"))}),flush=True)
    else:
        print(json.dumps({"status":"NO_WORKER_IN_WINDOW",
            "cause":"no eligible inactive browser tab or worker did not claim",
            "automatic_resend":False}),flush=True)
finally:
    if job_id and (outcome is None):
        cancelled=request("/jobs/cancel",{"job_id":job_id})
        print(json.dumps({"own_diagnostic_cancel_requested":cancelled.get("ok") is True}),flush=True)
