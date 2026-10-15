"""Native TaskProcess producer crash + broker restart, isolated and synthetic.

The real execution/admission/queue/process supervisor runs unchanged. Only the
CLI command points at this harness's synthetic producer, which calls no model.
All processes, state, profiles, credentials and HTTP endpoints belong to QA.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing,contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import traceback
from urllib.parse import urlencode
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from astra_broker_restart import Child,http_json,isolated_directory,say


def body_for(conversation):
    return 'QA_PRODUCER '+conversation+'\n'+('Unicode 🪐 [[wiki]] repeated\n'*12000)


@contextmanager
def reader_pool(broker):
    pool=ThreadPoolExecutor(max_workers=20)
    try:yield pool
    except BaseException:
        # SSE readers keep receiving heartbeats indefinitely. End only this
        # owned broker before waiting for their threads during failed QA.
        broker.kill()
        raise
    finally:pool.shutdown(wait=True,cancel_futures=True)


def synthetic_cli(args):
    from sentra_cli.shell_live_preview import LivePreviewWriter
    from sentra_core.conversations import ConversationStore
    prompt=sys.stdin.read()
    log=args.qa_base/('producer-'+args.resume+'.jsonl')
    with log.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'pid':os.getpid(),'conversation_id':args.resume})+'\n')
        stream.flush();os.fsync(stream.fileno())
    # The real runtime already opened this conversation. The synthetic CLI
    # checkpoints through the real protected store, without a final receipt.
    store=ConversationStore(args.state_dir,principal='astra-producer-qa')
    turn,_=store.begin_turn(args.resume,prompt)
    text=body_for(args.resume)
    store.checkpoint_response(args.resume,turn,text)
    writer=LivePreviewWriter();writer.activity('provider_submitted');writer.send(text)
    # Crash after an acknowledged durable checkpoint but in the middle of the
    # next framing record. No newline: this suffix must never be published.
    partial=json.dumps({'nonce':writer.nonce,'kind':'delta','text':'UNCOMMITTED 🪐 suffix'},ensure_ascii=False).encode()[:-3]
    with open(writer.path,'ab',buffering=0) as stream:
        stream.write(partial);os.fsync(stream.fileno())
    while True:time.sleep(.1)


def broker(base,port):
    from sentra_canvas.service import Canvas
    from sentra_canvas.__main__ import CanvasServer
    root=base/'projects';root.mkdir(exist_ok=True)
    app=Canvas(root,principal='astra-producer-qa',state_dir=base/'state'/'canvas',max_task_workers=10)
    app.model_catalog=lambda:{'models':['sentra/test-one']}
    app._cli_command=lambda arguments:[sys.executable,'-B',str(Path(__file__).resolve()),
        '--native-cli','--qa-base',str(base),*arguments]
    control=app._shell_service();runtime=app._shell_runtime
    server=CanvasServer(app,port)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    say({'ready':True,'port':server.server_port,'secret':server.secret,'pid':os.getpid()})
    try:
        for line in sys.stdin:
            request=json.loads(line)
            try:
                command=request['command']
                if command=='seed':
                    project=app.create_workspace('Native_producer_QA')['id']
                    def call(action,**fields):
                        return app.shell_bridge({'action':action,'project_id':project,
                            'request_key':'producer-qa-'+uuid.uuid4().hex,**fields})['value']
                    space=call('home')['space']['space_id']
                    run=app._runtime().run(project)
                    if run['state']!='RUNNING':control.durable.transition_run(run['run_id'],runtime.owner,'RUNNING')
                    dot=call('dot_create',space_id=space,name='Native producer QA',role='specialist',model='sentra/test-one')
                    scopes=[]
                    for _ in range(10):
                        conversation=call('conversation_create',space_id=space,dot_id=dot['dot_id'])['conversation_id']
                        sent=call('message_send',space_id=space,conversation_id=conversation,content='Synthetic native producer crash QA')
                        scopes.append({'project_id':project,'space_id':space,'conversation_id':conversation,
                            'operation_id':sent['operation_id']})
                    (base/'fixture.json').write_text(json.dumps(scopes),encoding='utf-8')
                    result={'scopes':scopes}
                elif command=='inspect':
                    scopes=json.loads((base/'fixture.json').read_text(encoding='utf-8'))
                    heads=[runtime.stream.head(s['project_id'],s['conversation_id']) for s in scopes]
                    operations=[control.durable.operation_status(s['operation_id'],runtime.owner)['state'] for s in scopes]
                    with runtime.live._lock:
                        pending={cid:len(record['pending']) for cid,record in runtime.live._current.items()}
                    logs=[]
                    for scope in scopes:
                        path=base/('producer-'+scope['conversation_id']+'.jsonl')
                        logs.append([json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else [])
                    drafts=[]
                    for scope in scopes:
                        try:drafts.append(runtime.conversations.response_draft(scope['conversation_id']))
                        except PermissionError:drafts.append(None) # Worker has not opened this queued conversation yet.
                    result={'heads':heads,'operations':operations,'partial_record_bytes':pending,
                        'invocations':logs,'draft_sha256':[hashlib.sha256(d['content'].encode()).hexdigest() if d else None for d in drafts],
                        'active_processes':len(runtime._processes),'stream_error':runtime.stream_error,
                        'workers':[{'name':worker.name,'alive':worker.is_alive(),
                            'stack':[{'function':frame.name,'line':frame.lineno,'file':Path(frame.filename).name}
                                for frame in traceback.extract_stack(sys._current_frames()[worker.ident])[-7:]]}
                            for worker in runtime._threads if worker.ident in sys._current_frames()]}
                elif command=='kill_producers':
                    with runtime._lock:processes=list(runtime._processes.values())
                    assert len(processes)==10,'Ten native producers must be active before inducing failure'
                    for process in processes:process.terminate_tree()
                    deadline=time.monotonic()+10
                    while any(process.poll() is None for process in processes):
                        if time.monotonic()>deadline:raise AssertionError('Owned producer failed to terminate')
                        time.sleep(.01)
                    result={'processes':10,'all_process_exits_verified':True,'exit_codes':[process.returncode for process in processes]}
                else:raise ValueError('Unknown producer QA command')
                say({'request_id':request['request_id'],'ok':True,'value':result})
            except BaseException as exc:
                say({'request_id':request['request_id'],'ok':False,'error':type(exc).__name__+': '+str(exc)[:500]})
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);app.shutdown()


def run():
    from playwright.sync_api import sync_playwright
    from astra_stream_resilience import HTML,sse_frame
    output=ROOT/'.tmp'/'astra-producer-crash';output.mkdir(parents=True,exist_ok=True)
    report={'success':False,'model_inference':False,'provider_accounts_used':False,'production_services_accessed':False,
        'runtime':'unchanged native execution pipeline and TaskProcess Windows Job',
        'injection':'Canvas._cli_command points only to synthetic local CLI','phases':[]}
    children=[]
    try:
        with isolated_directory(children) as temporary:
            base=Path(temporary)
            first=Child('--native-broker',str(base),entry=Path(__file__).resolve());children.append(first)
            scopes=first.call('seed')['scopes']
            deadline=time.monotonic()+20
            while True:
                before=first.call('inspect')
                if (before['operations']==['RUNNING']*10 and before['active_processes']==10
                        and all(before['partial_record_bytes'].get(s['conversation_id'],0)>0 for s in scopes)
                        and all(h and h.get('content_ref',{}).get('sha256')==hashlib.sha256(body_for(s['conversation_id']).encode()).hexdigest()
                            for h,s in zip(before['heads'],scopes))):break
                if time.monotonic()>deadline:
                    report['readiness_diagnostics']={k:before[k] for k in ('operations','active_processes','stream_error','workers')}
                    raise AssertionError('Ten native producers/committed heads/partial framing records did not become ready: '+str(before['operations']))
                time.sleep(.05)
            assert all(len(rows)==1 for rows in before['invocations'])
            expected=[hashlib.sha256(body_for(s['conversation_id']).encode()).hexdigest() for s in scopes]
            assert before['draft_sha256']==expected
            report['phases'].append({'name':'ten_native_children_running','protected_drafts':10,
                'long_references':10,'incomplete_records_ingested':10,'synthetic_cli_invocations':10})
            endpoint=first.ready;root='http://127.0.0.1:'+str(endpoint['port']);ready=queue.Queue();failure_started=[None]
            def observe_failure():
                started=time.monotonic()
                request=urllib.request.Request(root+'/api/shell/stream?project_id='+scopes[0]['project_id'],
                    headers={'Authorization':'Bearer '+endpoint['secret'],'Last-Event-ID':'0'})
                seen={};announced=False
                with urllib.request.urlopen(request,timeout=45) as response:
                    while True:
                        event=sse_frame(response)
                        if event['event']=='snapshot':
                            for scope in scopes:
                                view=http_json(endpoint,'/api/shell/stream/head?'+urlencode({key:scope[key]
                                    for key in ('project_id','space_id','conversation_id')}))
                                seen[scope['conversation_id']]=view
                        elif event['event']=='shell':
                            wire=event['data'];conversation=wire['conversation_id'];prior=seen.get(conversation)
                            if wire['kind']=='delta' and (prior is None or prior['sequence']!=wire['base_sequence']):
                                scope=next(scope for scope in scopes if scope['conversation_id']==conversation)
                                view=http_json(endpoint,'/api/shell/stream/head?'+urlencode({key:scope[key]
                                    for key in ('project_id','space_id','conversation_id')}))
                            else:
                                content=(prior['content'] if wire['kind']=='delta' else '')+wire['text']
                                view={**wire['preview'],'content':content,'sequence':wire['sequence']}
                            seen[conversation]=view
                            assert 'UNCOMMITTED' not in wire['text'] and 'UNCOMMITTED' not in view.get('content','')
                        else:continue
                        if len(seen)==10 and not announced:ready.put(round((time.monotonic()-started)*1000));announced=True
                        if len(seen)==10 and all(view.get('status')=='interrupted' for view in seen.values()):
                            return {'conversations':len(seen),'failure_to_observed_ms':round((time.monotonic()-failure_started[0])*1000)}
            with sync_playwright() as playwright,reader_pool(first) as pool:
                browser=playwright.chromium.launch(headless=True)
                context=browser.new_context()
                context.route('**/qa-producer.html',lambda route:route.fulfill(body=HTML,content_type='text/html'))
                context.route('**/qa-stream-transport.js',lambda route:route.fulfill(
                    body=(ROOT/'sentra_canvas/desktop_ui/src/shell-stream-transport.js').read_text(encoding='utf-8'),content_type='text/javascript'))
                page=context.new_page();page.goto(root+'/qa-producer.html')
                page.wait_for_function('typeof window.startFeed==="function"')
                views=[{k:s[k] for k in ('project_id','space_id','conversation_id')} for s in scopes]
                page.evaluate('args=>window.startFeed(args)',{'scopes':views,'token':endpoint['secret']})
                page.wait_for_function('window.heads.size===10 && window.feed.state==="connected"')
                readers=[pool.submit(observe_failure) for _ in range(20)]
                prepared=0;replay_times=[]
                try:
                    for _ in readers:replay_times.append(ready.get(timeout=45));prepared+=1
                except queue.Empty:
                    report['observer_readiness_diagnostics']={'ready':prepared,
                        'completed_errors':[str(future.exception())[:300] for future in readers if future.done()]}
                    raise
                report['initial_full_replay_ready_ms']=replay_times
                report['initial_full_replay_max_ms']=max(replay_times)
                report['initial_full_replay_within_15_seconds']=max(replay_times)<=15000
                say({'qa_phase':'twenty_http_readers_ready','initial_full_replay_max_ms':max(replay_times)})
                failure_started[0]=time.monotonic()
                failure=first.call('kill_producers');assert failure['all_process_exits_verified']
                report['producer_exits']=failure
                observations=[future.result(timeout=15) for future in readers]
                report['producer_failure_to_all_interruptions_max_ms']=max(item['failure_to_observed_ms'] for item in observations)
                page.wait_for_function('window.heads.size===10 && [...window.heads.values()].every(h=>h.status==="interrupted")')
                after=first.call('inspect')
                assert after['operations']==['UNCERTAIN']*10
                assert after['active_processes']==0 and not after['partial_record_bytes']
                assert after['invocations']==before['invocations']
                assert after['draft_sha256']==expected
                for old,new in zip(before['heads'],after['heads']):
                    assert new['content']==old['content'] and new['content_ref']==old['content_ref']
                report['phases'].append({'name':'abrupt_native_producer_exit','verified_process_exits':10,
                    'operations_uncertain':10,'http_readers_received_all_interruptions':len(observations),
                    'uncommitted_json_suffix_published':False,'persisted_drafts_and_references_retained':True,
                    'synthetic_cli_relaunches':0})
                first.kill()
                second=Child('--native-broker',str(base),'--port',str(endpoint['port']),entry=Path(__file__).resolve());children.append(second)
                restored=second.call('inspect')
                assert restored['operations']==['UNCERTAIN']*10 and restored['active_processes']==0
                assert restored['invocations']==before['invocations'] and restored['draft_sha256']==expected
                for scope,head,digest in zip(views,restored['heads'],expected):
                    reference=head['content_ref'];offset=0;parts=[]
                    while offset is not None:
                        body=http_json(second.ready,'/api/shell/stream/content?'+urlencode({**scope,
                            'reference_id':reference['reference_id'],'offset':offset}))
                        parts.append(body['content']);offset=body['next_offset']
                    assert hashlib.sha256(''.join(parts).encode()).hexdigest()==digest==reference['sha256']
                    assert 'UNCOMMITTED' not in ''.join(parts)
                final=second.call('inspect');assert final['invocations']==before['invocations']
                report['phases'].append({'name':'broker_restart_after_producer_failures','drafts_and_full_references_verified':10,
                    'operations_still_uncertain':10,'synthetic_cli_relaunches':0})
                browser.close()
            report.update(success=True,flows=10,http_readers=20,multiplexed_dom_observers=20,
                input_sha256={str(path.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in [ROOT/'sentra_canvas/shell_runtime.py',ROOT/'sentra_canvas/shell_live.py',
                        ROOT/'sentra_canvas/shell_stream.py',ROOT/'sentra_canvas/owned_process.py',
                        ROOT/'sentra_cli/shell_live_preview.py',ROOT/'sentra_core/conversations.py',
                        ROOT/'tests/qa/astra_broker_restart.py',Path(__file__).resolve()]},
                limits=['Synthetic CLI, no model or provider call','One owner, not twenty team identities',
                    'No installed runtime, OS suspend, gateway or relay combined failure',
                    'Acknowledged checkpoints survive; incomplete producer JSON is intentionally not a committed event',
                    'No automatic producer restart; uncertain operations require reconciliation'])
    except BaseException as exc:
        report.update(error_type=type(exc).__name__,error=str(exc)[:1200]);raise
    finally:
        for child in reversed(children):child.close()
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    say({k:v for k,v in report.items() if k!='input_sha256'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-broker',type=Path);parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--native-cli',action='store_true');parser.add_argument('--qa-base',type=Path)
    parser.add_argument('--workspace');parser.add_argument('--state-dir',type=Path);parser.add_argument('--resume')
    args,unknown=parser.parse_known_args()
    if args.native_broker:broker(args.native_broker,args.port)
    elif args.native_cli:synthetic_cli(args)
    else:
        if unknown:parser.error('Unexpected harness arguments')
        run()
