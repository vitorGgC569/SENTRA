"""Real temporary Canvas broker crash/restart; synthetic producers, no accounts.

All spawned processes and Chromium profiles belong to this harness. The
production broker, its endpoint, installed runtime and provider accounts are
never read, stopped or reconfigured. Tokens/nonces stay in private child pipes.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing,contextmanager
import http.client
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def say(value):
    print(json.dumps(value,ensure_ascii=True),flush=True)


def broker(base,port):
    from sentra_canvas.service import Canvas
    from sentra_canvas.__main__ import CanvasServer
    project_root=base/'projects';project_root.mkdir(exist_ok=True)
    app=Canvas(project_root,principal='astra-broker-qa',state_dir=base/'state'/'canvas')
    app.model_catalog=lambda:{'models':['sentra/test-one']}
    control=app._shell_service();runtime=app._shell_runtime
    with closing(control.store.connect('shell')) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS qa_broker_dispatches(id INTEGER PRIMARY KEY AUTOINCREMENT,operation_id TEXT NOT NULL,kind TEXT NOT NULL)')
    def synthetic_execute(operation):
        # This log measures synthetic dispatches, never provider submissions.
        with closing(control.store.connect('shell')) as db,db:
            db.execute('INSERT INTO qa_broker_dispatches(operation_id,kind) VALUES(?,?)',(operation,'attempt'))
            changed=db.execute("UPDATE canvas_shell_queue SET state='running' WHERE operation_id=? AND state='queued'",(operation,)).rowcount
            if changed:db.execute('INSERT INTO qa_broker_dispatches(operation_id,kind) VALUES(?,?)',(operation,'synthetic_submission'))
        if changed:
            control.durable.update_operation(operation,runtime.owner,state='STARTING')
            control.durable.update_operation(operation,runtime.owner,state='RUNNING')
    runtime._execute=synthetic_execute
    server=CanvasServer(app,port)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    say({'ready':True,'port':server.server_port,'secret':server.secret,'pid':os.getpid()})
    try:
        for line in sys.stdin:
            request=json.loads(line);command=request['command']
            try:
                if command=='seed':
                    project=app.create_workspace('Broker_restart_QA')['id']
                    def call(action,**fields):
                        return app.shell_bridge({'action':action,'project_id':project,'request_key':'broker-qa-'+uuid.uuid4().hex,**fields})['value']
                    space=call('home')['space']['space_id']
                    dot=call('dot_create',space_id=space,name='Broker QA',role='specialist',model='sentra/test-one')
                    scopes=[];environments=[]
                    for flow in range(10):
                        conversation=call('conversation_create',space_id=space,dot_id=dot['dot_id'])['conversation_id']
                        sent=call('message_send',space_id=space,conversation_id=conversation,content='Synthetic broker recovery test')
                        operation=sent['operation_id']
                        deadline=time.monotonic()+5
                        while control.durable.operation_status(operation,runtime.owner)['state']!='RUNNING':
                            if time.monotonic()>deadline:raise AssertionError('Synthetic submission did not enter RUNNING')
                            time.sleep(.01)
                        record=runtime.live.begin(project_id=project,space_id=space,conversation_id=conversation,operation_id=operation)
                        scopes.append({'project_id':project,'space_id':space,'conversation_id':conversation,'operation_id':operation})
                        environments.append(runtime.live.environment(record))
                    (base/'fixture.json').write_text(json.dumps(scopes),encoding='utf-8')
                    result={'scopes':scopes,'environments':environments}
                elif command=='inspect':
                    scopes=json.loads((base/'fixture.json').read_text(encoding='utf-8'))
                    heads=[runtime.stream.head(scope['project_id'],scope['conversation_id']) for scope in scopes]
                    operations=[control.durable.operation_status(scope['operation_id'],runtime.owner)['state'] for scope in scopes]
                    with closing(control.store.connect('shell')) as db:
                        submissions=[dict(row) for row in db.execute("SELECT operation_id,kind FROM qa_broker_dispatches ORDER BY id")]
                    result={'heads':heads,'operations':operations,'dispatches':submissions,'stream_error':runtime.stream_error}
                else:raise ValueError('Unsupported synthetic broker QA command')
                say({'request_id':request['request_id'],'ok':True,'value':result})
            except BaseException as exc:
                say({'request_id':request['request_id'],'ok':False,'error':type(exc).__name__+': '+str(exc)[:500]})
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);app.shutdown()


def producer():
    from sentra_cli.shell_live_preview import LivePreviewWriter
    say({'ready':True,'pid':os.getpid()})
    writers=[]
    for line in sys.stdin:
        request=json.loads(line)
        try:
            if request['command']=='init':
                for environment in request['environments']:
                    os.environ.update(environment);writers.append(LivePreviewWriter())
                value={'writers':len(writers)}
            elif request['command']=='emit':
                for writer,text in zip(writers,request['texts']):writer.send(text)
                value={'emitted':len(writers)}
            else:raise ValueError('Unsupported synthetic producer QA command')
            say({'request_id':request['request_id'],'ok':True,'value':value})
        except BaseException as exc:say({'request_id':request['request_id'],'ok':False,'error':type(exc).__name__})


class Child:
    def __init__(self,*args,entry=None):
        self.process=subprocess.Popen([sys.executable,'-B',str(entry or Path(__file__).resolve()),*args],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',cwd=ROOT)
        self.lines=queue.Queue();self.errors=[]
        def drain():
            for line in self.process.stdout:self.lines.put(line)
            self.lines.put(None)
        def errors():
            for line in self.process.stderr:
                if len(self.errors)<20:self.errors.append(line[:500])
        self.drainers=[threading.Thread(target=drain,daemon=True),threading.Thread(target=errors,daemon=True)]
        for thread in self.drainers:thread.start()
        try:
            self.ready=self.receive()
            assert self.ready.get('ready')
        except BaseException:
            self.kill();self.close();raise
    def receive(self):
        line=self.lines.get(timeout=25)
        if line is None:raise RuntimeError(f'Isolated child exited {self.process.poll()}: '+''.join(self.errors)[:800])
        return json.loads(line)
    def call(self,command,**fields):
        identity=uuid.uuid4().hex
        self.process.stdin.write(json.dumps({'request_id':identity,'command':command,**fields},ensure_ascii=True)+'\n');self.process.stdin.flush()
        response=self.receive()
        assert response.get('request_id')==identity
        if not response.get('ok'):raise RuntimeError(response.get('error','isolated child failure'))
        return response['value']
    def kill(self):
        if self.process.poll() is None:self.process.kill()
        self.process.wait(timeout=10)
    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.kill()
        for thread in self.drainers:thread.join(timeout=1)
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
            if stream is not None and not stream.closed:stream.close()


def http_json(endpoint,path,*,token=None):
    request=urllib.request.Request('http://127.0.0.1:'+str(endpoint['port'])+path,
        headers={'Authorization':'Bearer '+(endpoint['secret'] if token is None else token)})
    with urllib.request.urlopen(request,timeout=10) as response:return json.loads(response.read())


@contextmanager
def isolated_directory(children):
    with tempfile.TemporaryDirectory(prefix='sentra-broker-qa-',ignore_cleanup_errors=True) as temporary:
        try:yield temporary
        finally:
            for child in reversed(children):child.close()


def run():
    from playwright.sync_api import sync_playwright
    from astra_stream_resilience import HTML,sse_frame
    output=ROOT/'.tmp'/'astra-broker-restart';output.mkdir(parents=True,exist_ok=True)
    report={'success':False,'model_inference':False,'provider_accounts_used':False,'production_services_accessed':False,
        'broker':'production CanvasServer in its own temporary Python process','producer':'separate synthetic LivePreviewWriter process',
        'phases':[]}
    children=[]
    try:
        with isolated_directory(children) as temporary:
            base=Path(temporary)
            first=Child('--broker',str(base),'--port','0');children.append(first)
            fixture=first.call('seed');scopes=fixture['scopes']
            source=Child('--producer');children.append(source);source.call('init',environments=fixture['environments'])
            texts=['QA_BROKER_FLOW_0 '+('Unicode 🪐 [[wiki]] repeated\n'*12000)]+[f'QA_BROKER_FLOW_{flow} persisted' for flow in range(1,10)]
            source.call('emit',texts=texts)
            deadline=time.monotonic()+15
            while True:
                before=first.call('inspect')
                if all(head and (head.get('content_ref',{}).get('total_chars')==len(texts[flow]) if flow==0 else head.get('content')==texts[flow]) for flow,head in enumerate(before['heads'])):break
                if time.monotonic()>deadline:raise AssertionError('Initial protected heads did not catch up')
                time.sleep(.05)
            assert before['operations']==['RUNNING']*10
            assert sum(row['kind']=='synthetic_submission' for row in before['dispatches'])==10
            report['phases'].append({'name':'ten_original_synthetic_submissions','persisted_heads':10,'long_body_chars':len(texts[0])})
            endpoint=first.ready;root='http://127.0.0.1:'+str(endpoint['port'])
            ready=queue.Queue()
            def observe_until_crash():
                request=urllib.request.Request(root+'/api/shell/stream?project_id='+scopes[0]['project_id'],
                    headers={'Authorization':'Bearer '+endpoint['secret'],'Last-Event-ID':'0'})
                conversations=set();cursor=0;announced=False
                with urllib.request.urlopen(request,timeout=10) as response:
                    try:
                        while True:
                            event=sse_frame(response)
                            if event['event']=='shell':
                                conversations.add(event['data']['conversation_id']);cursor=max(cursor,int(event['id']))
                            if len(conversations)==10 and not announced:ready.put(True);announced=True
                    except (EOFError,OSError,http.client.IncompleteRead):pass
                assert announced
                return {'conversations':len(conversations),'cursor':cursor,'connection_ended':True}
            with sync_playwright() as playwright,ThreadPoolExecutor(max_workers=20) as pool:
                browser=playwright.chromium.launch(headless=True)
                context=browser.new_context()
                html=HTML.replace('({scopes,token})','({scopes,token,cursor})').replace('window.feed=feed;',
                    'if(cursor!=null)feed.cursor=cursor;window.feed=feed;')
                html=html.replace("throw new Error('snapshot unavailable')",
                    "throw Object.assign(new Error('snapshot unavailable'),{status:response.status})")
                context.route('**/qa-broker.html',lambda route:route.fulfill(body=html,content_type='text/html'))
                context.route('**/qa-stream-transport.js',lambda route:route.fulfill(
                    body=(ROOT/'sentra_canvas/desktop_ui/src/shell-stream-transport.js').read_text(encoding='utf-8'),content_type='text/javascript'))
                page=context.new_page();page.goto(root+'/qa-broker.html')
                page.wait_for_function('typeof window.startFeed==="function"')
                view_scopes=[{key:scope[key] for key in ('project_id','space_id','conversation_id')} for scope in scopes]
                page.evaluate('args=>window.startFeed(args)',{'scopes':view_scopes,'token':endpoint['secret']})
                page.wait_for_function('window.heads.size===10 && window.feed.state==="connected"')
                old_cursor=page.evaluate('window.feed.cursor')
                readers=[pool.submit(observe_until_crash) for _ in range(20)]
                for _ in readers:ready.get(timeout=15)
                first.kill();assert first.process.poll() is not None
                assert source.process.poll() is None
                page.wait_for_function('window.feed.state==="reconnecting"',timeout=10000)
                assert page.evaluate('window.heads.size')==10
                observations=[future.result(timeout=12) for future in readers]
                report['phases'].append({'name':'abrupt_broker_exit','http_readers_disconnected':len(observations),
                    'old_window_preserved_heads':10,'old_cursor':old_cursor,'separate_producer_survived':True})
                second=Child('--broker',str(base),'--port',str(endpoint['port']));children.append(second)
                assert second.ready['secret']!=endpoint['secret']
                deadline=time.monotonic()+12
                while True:
                    after=second.call('inspect')
                    if all(head and head['status']=='interrupted' for head in after['heads']):break
                    if time.monotonic()>deadline:raise AssertionError('Interrupted operations not projected after restart')
                    time.sleep(.05)
                assert after['operations']==['UNCERTAIN']*10
                assert after['dispatches']==before['dispatches'],'Broker restart re-dispatched the synthetic producer'
                assert after['heads'][0].get('content_ref')==before['heads'][0]['content_ref'],'Broker restart lost the immutable long content reference'
                page.wait_for_function('window.feed.state==="reauth_required"',timeout=12000)
                try:http_json(second.ready,'/api/health',token=endpoint['secret']);raise AssertionError('Old broker session remained authorized')
                except urllib.error.HTTPError as expired:assert expired.code==401
                page.evaluate('window.feed.close();document.querySelector("main").replaceChildren()')
                # The private native/test control pipe supplies the NEW session;
                # observing reconnection never creates a request key or POST.
                page.evaluate('args=>window.startFeed(args)',{'scopes':view_scopes,'token':second.ready['secret'],'cursor':old_cursor})
                page.wait_for_function('window.heads.size===10 && window.feed.state==="connected" && [...window.heads.values()].every(h=>h.status==="interrupted")',timeout=12000)
                assert page.evaluate('window.feed.cursor')>=old_cursor
                reference=after['heads'][0]['content_ref'];scope=view_scopes[0]
                from urllib.parse import urlencode
                offset=0;parts=[]
                while offset is not None:
                    body=http_json(second.ready,'/api/shell/stream/content?'+urlencode({**scope,'reference_id':reference['reference_id'],'offset':offset}))
                    parts.append(body['content']);offset=body['next_offset']
                assert ''.join(parts)==texts[0] and hashlib.sha256(''.join(parts).encode()).hexdigest()==reference['sha256']
                final=second.call('inspect');assert final['dispatches']==before['dispatches']
                report['phases'].append({'name':'trusted_new_session_resume','same_port':True,'old_session_refused':True,
                    'operations_uncertain':10,'long_reference_reconstructed':True,'synthetic_redispatches':0})
                report.update(success=True,flows=10,http_readers=20,multiplexed_dom_observers=20,
                    input_sha256={str(path.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in [ROOT/'sentra_canvas/shell_stream.py',ROOT/'sentra_canvas/shell_runtime.py',ROOT/'sentra_canvas/service.py',
                            ROOT/'sentra_canvas/shell_live.py',ROOT/'sentra_canvas/__main__.py',ROOT/'sentra_core/model_prose.py',
                            ROOT/'sentra_cli/shell_live_preview.py',Path(__file__).resolve()]},
                    limits=['No real inference, provider submission or team users','Synthetic submission executor; real protected state and HTTP',
                        'New session supplied by private test control pipe, not installed native refresh UX',
                        'Producer bytes not committed during broker downtime are not claimed recovered','No installed release or OS suspend proof'])
                browser.close()
    except BaseException as exc:
        report.update(error_type=type(exc).__name__,error=str(exc)[:1000]);raise
    finally:
        for child in reversed(children):child.close()
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    say({key:value for key,value in report.items() if key!='input_sha256'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--broker',type=Path);parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--producer',action='store_true')
    args=parser.parse_args()
    if args.broker:broker(args.broker,args.port)
    elif args.producer:producer()
    else:run()
