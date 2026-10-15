"""Real Canvas HTTP/SSE + native preview adapter + Chromium, synthetic producer.

This never calls a model or a provider and does not certify twenty team users.
Twenty authenticated HTTP readers and twenty multiplexed DOM observers share
one local owner. Source transport is served directly; no installed bundle claim.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import argparse
import json
import hashlib
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas
from sentra_cli.shell_live_preview import LivePreviewWriter


HTML = r"""<!doctype html><meta charset=utf-8><title>SENTRA streaming resilience QA</title>
<main></main><script type=module>
import {ProjectFeed} from '/qa-stream-transport.js';
window.startFeed=async ({scopes,token})=>{
  const heads=new Map(),seen=new Set(),observed=new Map();window.painted=[];window.feedStates=[];
  const headers={Authorization:'Bearer '+token};
  const feed=new ProjectFeed({
    open:async(after,signal)=>{
      const response=await fetch('/api/shell/stream?project_id='+scopes[0].project_id,
        {headers:{...headers,...(after==null?{}:{'Last-Event-ID':String(after)})},signal});
      if(!response.ok)throw Object.assign(new Error('HTTP '+response.status),{status:response.status});
      return response;
    },
    readHead:async(scope,{signal})=>{
      const response=await fetch('/api/shell/stream/head?'+new URLSearchParams(scope),{headers,signal});
      if(!response.ok)throw new Error('snapshot unavailable');return response.json();
    }
  });
  window.feed=feed;window.heads=heads;
  for(let reader=0;reader<20;reader++){
    const scope=scopes[reader%scopes.length],el=document.createElement('pre');
    el.dataset.reader=reader;document.querySelector('main').appendChild(el);
    feed.subscribe(scope,{onState:state=>window.feedStates.push(state),onPreview:view=>{
      heads.set(scope.conversation_id,view);el.textContent=view.content||'';
      for(const match of el.textContent.matchAll(/QA_SAMPLE_(\d+)_(\d+)/g)){
        const key=reader+':'+match[0];if(!observed.has(key))observed.set(key,Date.now());
      }
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        for(const match of el.textContent.matchAll(/QA_SAMPLE_(\d+)_(\d+)/g)){
          const key=reader+':'+match[0];if(seen.has(key))continue;seen.add(key);
          window.painted.push({reader,flow:Number(match[1]),round:Number(match[2]),at_ms:Date.now(),observed_ms:observed.get(key)});
        }
      }));
    }});
  }
};
</script>"""


def sse_frame(response):
    lines = []
    while True:
        line = response.readline()
        if not line:
            raise EOFError('incomplete SSE frame')
        if line.strip():
            lines.append(line.decode().rstrip())
        elif lines:
            fields = dict(line.split(': ', 1) for line in lines)
            fields['data'] = json.loads(fields['data'])
            return fields


def percentile(values, fraction):
    import math
    return sorted(values)[max(0, math.ceil(len(values)*fraction)-1)]


def native_compiler_sample():
    """Observation only; absence at two instants is not proof of an idle host."""
    if os.name != 'nt':return {'observed':False,'reason':'Windows process observation unavailable'}
    result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',
        "Get-CimInstance Win32_Process -Filter \"Name='cargo.exe' OR Name='rustc.exe'\" | Select-Object ProcessId,Name | ConvertTo-Json -Compress"],
        capture_output=True,text=True,timeout=10)
    if result.returncode:return {'observed':False,'reason':'process query failed'}
    return {'observed':True,'at_unix_ms':round(time.time()*1000),'processes':json.loads(result.stdout) if result.stdout.strip() else []}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',default='latest')
    args=parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',args.label):parser.error('bounded filesystem-safe label required')
    compiler_start=native_compiler_sample()
    output = ROOT / '.tmp' / 'astra-stream-resilience'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sentra-stream-load-', ignore_cleanup_errors=True) as temporary:
        base = Path(temporary)
        project_root = base/'project';project_root.mkdir()
        app = Canvas(project_root, principal='astra-stream-load', state_dir=base/'state'/'canvas')
        app.model_catalog = lambda: {'models':['sentra/test-one']}
        server=CanvasServer(app,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        records=[]
        original={key:os.environ.get(key) for key in ('SENTRA_SHELL_PREVIEW_PATH','SENTRA_SHELL_PREVIEW_NONCE')}
        try:
            project=app.create_workspace('ASTRA_STREAM_LOAD')['id']
            def call(action, **fields):
                return app.shell_bridge({'action':action,'project_id':project,'request_key':'load-'+uuid.uuid4().hex,**fields})['value']
            space=call('home')['space']['space_id']
            dot=call('dot_create',space_id=space,name='Stream QA',role='specialist',model='sentra/test-one')
            executions=[]
            runtime=app._shell_runtime
            def synthetic_execute(operation):
                # Move only the isolated execution queue out of queued, as a
                # producer would. Do not fabricate central grants or receipts.
                with closing(runtime.control.store.connect('shell')) as db,db:
                    changed=db.execute("UPDATE canvas_shell_queue SET state='running' WHERE operation_id=? AND state='queued'",(operation,)).rowcount
                if changed:executions.append(operation)
            runtime._execute=synthetic_execute
            persisted={}; ingested={}; write_durations=[]; read_durations=[]
            diagnostic={};measuring=False
            def timed(name,callback):
                def instrumented(*args,**kwargs):
                    if not measuring:return callback(*args,**kwargs)
                    began=time.perf_counter()
                    try:return callback(*args,**kwargs)
                    finally:
                        key=name+':'+threading.current_thread().name
                        diagnostic.setdefault(key,[]).append((time.perf_counter()-began)*1000)
                return instrumented
            import sentra_canvas.shell_stream as stream_module
            stream_module._encode=timed('journal_encode',stream_module._encode)
            stream_module._decode=timed('journal_decode',stream_module._decode)
            runtime.control.store.connect=timed('control_connect',runtime.control.store.connect)
            runtime.control.store.assert_active=timed('authority_check',runtime.control.store.assert_active)
            original_update=runtime.live.update
            def observed_update(record):
                result=original_update(record)
                if measuring:
                    at=time.time()*1000
                    for flow,round_id in re.findall(r'QA_SAMPLE_(\d+)_(\d+)',record['text']):ingested.setdefault(f'{flow}:{round_id}',at)
                return result
            runtime.live.update=timed('live_update',observed_update)
            runtime.live.pump=timed('live_pump',runtime.live.pump)
            class ObservedPath:
                def __init__(self,path):self.path=path
                def __str__(self):return str(self.path)
                def __fspath__(self):return str(self.path)
                def __getattr__(self,name):
                    value=getattr(self.path,name)
                    return timed('preview_file_'+name,value) if callable(value) else value
            callback=runtime.live._on_change
            def observed(record, view):
                began=time.perf_counter();result=callback(record,view)
                write_durations.append((time.perf_counter()-began)*1000)
                if result:
                    at=time.time()*1000
                    for flow,round_id in re.findall(r'QA_SAMPLE_(\d+)_(\d+)',view['content']):persisted.setdefault(f'{flow}:{round_id}',at)
                return result
            runtime.live._on_change=observed
            batch_callback=runtime.live._on_batch
            def observed_batch(observations):
                began=time.perf_counter();results=batch_callback(observations)
                write_durations.append((time.perf_counter()-began)*1000)
                at=time.time()*1000
                for (_,view),accepted in zip(observations,results):
                    if accepted:
                        for flow,round_id in re.findall(r'QA_SAMPLE_(\d+)_(\d+)',view['content']):persisted.setdefault(f'{flow}:{round_id}',at)
                return results
            runtime.live._on_batch=observed_batch
            original_read=runtime.stream.read
            def measured_read(*args,**kwargs):
                began=time.perf_counter()
                try:return original_read(*args,**kwargs)
                finally:read_durations.append((time.perf_counter()-began)*1000)
            runtime.stream.read=measured_read
            scopes=[];writers=[]
            for flow in range(10):
                conversation=call('conversation_create',space_id=space,dot_id=dot['dot_id'])['conversation_id']
                operation=call('message_send',space_id=space,conversation_id=conversation,content='Synthetic streaming QA')['operation_id']
                record=runtime.live.begin(project_id=project,space_id=space,conversation_id=conversation,operation_id=operation)
                record['path']=ObservedPath(record['path'])
                os.environ.update(runtime.live.environment(record));writers.append(LivePreviewWriter());records.append(record)
                scopes.append({'project_id':project,'space_id':space,'conversation_id':conversation})
            root=f'http://127.0.0.1:{server.server_port}'
            ready=queue.Queue()
            def consume():
                req=urllib.request.Request(root+'/api/shell/stream?project_id='+project,headers={'Authorization':'Bearer '+server.secret})
                final=set();fragments=set();count=0
                with urllib.request.urlopen(req,timeout=12) as response:
                    assert sse_frame(response)['event']=='snapshot';ready.put(True)
                    while len(final)<10:
                        event=sse_frame(response)
                        if event['event']!='shell':continue
                        count+=1
                        final.update(int(m) for m in re.findall(r'QA_SAMPLE_(\d+)_5',event['data'].get('text','')))
                        fragments.update(re.findall(r'QA_SAMPLE_(\d+)_(\d+)',event['data'].get('text','')))
                assert len(fragments)==60, 'reader missed one or more synthetic native fragments'
                return count
            with sync_playwright() as playwright, ThreadPoolExecutor(max_workers=20) as pool:
                browser=playwright.chromium.launch(headless=True)
                context=browser.new_context(viewport={'width':1200,'height':900})
                context.route('**/qa-stream.html',lambda route:route.fulfill(body=HTML,content_type='text/html'))
                source=(ROOT/'sentra_canvas/desktop_ui/src/shell-stream-transport.js').read_text(encoding='utf-8')
                context.route('**/qa-stream-transport.js',lambda route:route.fulfill(body=source,content_type='text/javascript'))
                page=context.new_page();page.goto(root+'/qa-stream.html')
                page.wait_for_function('typeof window.startFeed === "function"')
                page.evaluate('args=>window.startFeed(args)',{'scopes':scopes,'token':server.secret})
                page.wait_for_function('window.feed.state === "connected"')
                futures=[pool.submit(consume) for _ in range(20)]
                for _ in futures:ready.get(timeout=20)
                measuring=True
                emitted={}
                for round_id in range(6):
                    for flow,writer in enumerate(writers):
                        emitted[f'{flow}:{round_id}']=time.time()*1000
                        writer.send(f' QA_SAMPLE_{flow}_{round_id} Unicode 🪐 haha.\n')
                    page.wait_for_timeout(160)
                page.wait_for_function('window.painted.length >= 120',timeout=20000)
                counts=[future.result(timeout=20) for future in futures]
                samples=page.evaluate('window.painted')
                latencies=[item['at_ms']-emitted[f"{item['flow']}:{item['round']}"] for item in samples]
                # Temporarily disconnect only the observing browser, while the
                # native adapters keep writing and the protected journal ingests.
                initial_executions=list(executions)
                assert len(initial_executions)==10 and len(set(initial_executions))==10
                context.set_offline(True)
                # Chromium's offline emulation may leave an established
                # loopback socket alive. Explicitly sever that observing read.
                page.evaluate('window.feed.controller.abort()')
                page.wait_for_function('window.feed.state==="reconnecting"')
                for flow,writer in enumerate(writers):writer.send(f' OFFLINE_PERSISTED_{flow}\n')
                page.wait_for_timeout(350)
                for flow,scope in enumerate(scopes):
                    assert f'OFFLINE_PERSISTED_{flow}' in runtime.stream.head(project,scope['conversation_id'])['content']
                assert page.evaluate('[...window.heads.values()].every(h=>!h.content?.includes("OFFLINE_PERSISTED_"))')
                recovered_at=time.monotonic();context.set_offline(False)
                page.evaluate('window.feed.resume()')
                page.wait_for_function('window.feed.state==="connected" && [...window.heads.values()].filter(h=>h.content?.includes("OFFLINE_PERSISTED_")).length===10',timeout=16000)
                recovery_ms=(time.monotonic()-recovered_at)*1000
                page.close()
                for record in records:runtime.live.close(record)
                page=context.new_page();page.goto(root+'/qa-stream.html');page.wait_for_function('typeof window.startFeed==="function"')
                page.evaluate('args=>window.startFeed(args)',{'scopes':scopes,'token':server.secret})
                page.wait_for_function('[...window.heads.values()].filter(h=>h.status==="interrupted" && h.content?.includes("OFFLINE_PERSISTED_")).length===10',timeout=20000)
                assert all(runtime.stream.head(project,scope['conversation_id'])['automatic_retry'] is False for scope in scopes)
                assert executions==initial_executions, 'Observing reconnect re-dispatched an operation'
                report={
                    'measurement_label':args.label,
                    'producer':'synthetic native LivePreviewWriter, no inference','model_inference':False,
                    'server':'production CanvasServer, isolated temporary state','transport':'current source ProjectFeed, not installed bundle',
                    'shared_host_load':'Shared development host; compiler process samples do not certify an isolated release benchmark',
                    'native_compiler_process_samples':{'start':compiler_start,'end':native_compiler_sample()},
                    'flows':10,'http_readers':20,'multiplexed_dom_observers':20,'team_users_certified':False,
                    'distinct_emitted_fragments':60,'all_http_readers_observed_all_sixty_fragments':True,
                    'paint_samples':len(samples),'native_adapter_emit_to_double_raf_ms':{
                        'p50':round(percentile(latencies,.5),2),'p95':round(percentile(latencies,.95),2),'max':round(max(latencies),2)},
                    'native_emit_to_persist_p95_ms':round(percentile([persisted[key]-at for key,at in emitted.items()],.95),2),
                    'native_emit_to_ingest_p95_ms':round(percentile([ingested[key]-at for key,at in emitted.items()],.95),2),
                    'ingest_to_persist_p95_ms':round(percentile([persisted[key]-ingested[key] for key in emitted],.95),2),
                    'persist_to_onpreview_p95_ms':round(percentile([item['observed_ms']-persisted[f"{item['flow']}:{item['round']}"] for item in samples],.95),2),
                    'onpreview_to_double_raf_p95_ms':round(percentile([item['at_ms']-item['observed_ms'] for item in samples],.95),2),
                    'persist_to_paint_p95_ms':round(percentile([item['at_ms']-persisted[f"{item['flow']}:{item['round']}"] for item in samples],.95),2),
                    'journal_write_p95_ms':round(percentile(write_durations,.95),2),'journal_read_p95_ms':round(percentile(read_durations,.95),2),
                    'http_events_per_reader':counts,'browser_offline_preserved_all_ten_heads':True,
                    'observation_socket_explicitly_aborted':True,
                    'read_recovery_after_online_ms':round(recovery_ms,2),'new_window_recovers_interrupted_content':True,
                    'automatic_prompt_replays':0,'prompt_submission_stubbed':True,
                    'diagnostic_durations_ms':{key:{'count':len(values),'total':round(sum(values),2),
                        'p50':round(percentile(values,.5),2),'p95':round(percentile(values,.95),2),'max':round(max(values),2)}
                        for key,values in sorted(diagnostic.items())},
                    'paired_samples':[{'key':f"{item['flow']}:{item['round']}",'reader':item['reader'],
                        'emitted':emitted[f"{item['flow']}:{item['round']}"],
                        'ingested':ingested[f"{item['flow']}:{item['round']}"],
                        'persisted':persisted[f"{item['flow']}:{item['round']}"],
                        'onpreview':item['observed_ms'],'painted':item['at_ms']} for item in samples],
                    'input_sha256':{str(path.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest() for path in [
                        ROOT/'sentra_canvas/shell_stream.py',ROOT/'sentra_canvas/shell_live.py',ROOT/'sentra_canvas/shell_runtime.py',
                        ROOT/'sentra_canvas/service.py',ROOT/'sentra_canvas/shell_web_preview.py',ROOT/'sentra_canvas/__main__.py',
                        ROOT/'sentra_core/model_prose.py',
                        ROOT/'sentra_canvas/desktop_ui/src/shell-stream-transport.js',ROOT/'sentra_cli/shell_live_preview.py',Path(__file__).resolve()]},
                    'limits':['No real inference or provider latency','One owner; not twenty team identities','DOM harness; not full installed application','No OS suspend or physical network outage'],
                }
                (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
                (output/f'report-{args.label}.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
                browser.close();print(json.dumps({key:value for key,value in report.items() if key not in {'paired_samples','diagnostic_durations_ms'}},ensure_ascii=True))
        finally:
            for key,value in original.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value
            for record in records:
                if not record['done']:app._shell_runtime.live.close(record)
            server.shutdown();server.server_close();thread.join(timeout=5);app.shutdown()


if __name__=='__main__':main()
