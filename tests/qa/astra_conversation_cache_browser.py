"""Real React and HTTP reads against synthetic history; no real account or effect."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
from pathlib import Path
import socket
import subprocess
import threading
import time
import traceback
import urllib.request
from urllib.parse import parse_qs,urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'sentra_canvas/desktop_ui'
SCOPE = {'project_id': 'qa-cache', 'space_id': 'qa-space', 'conversation_id': 'qa-conversation'}


class Backend:
    def __init__(self):
        self.requests = []
        self.messages = []
        self.revoked = False
        self.live = {'status': 'idle', 'content': ''}
        self.live_requests = []
        self.originals = {}
        self.lock = threading.RLock()
        self.append(123)

    def append(self, count):
        with self.lock:
            for _ in range(count):
                index = len(self.messages)
                self.messages.append({**SCOPE, 'message_id': f'message-{index:04}', 'role': 'assistant',
                    'content': f'Mensagem {index:04} — conteúdo Unicode 🦉\nSegunda linha.',
                    'created_at': f'2026-01-01T00:{index // 60:02}:{index % 60:02}Z', 'status': 'succeeded',
                    'request_key': f'original-request-{index}'})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        assert self.headers.get('Authorization') == 'Bearer synthetic-cache-qa'
        assert self.path.startswith('/api/shell/live?')
        assert {key:values[0] for key,values in parse_qs(urlsplit(self.path).query).items()}==SCOPE
        with self.server.backend.lock:
            self.server.backend.live_requests.append(self.path)
            payload=json.dumps(self.server.backend.live).encode()
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        backend = self.server.backend
        assert self.headers.get('Authorization') == 'Bearer synthetic-cache-qa'
        with backend.lock:
            backend.requests.append(body)
            assert body['action'] in {'message_list', 'message_content', 'access_status'}, f'Unexpected effect or action: {body["action"]}'
            assert all(body.get(key) == value for key, value in SCOPE.items())
            if body['action'] == 'access_status':
                status, value = 200, {'ok': True, 'value': {'mode': 'ask', 'requests': []}}
            elif backend.revoked:
                status, value = 403, {'ok': False, 'error': 'Synthetic access revoked'}
            elif body['action']=='message_content':
                original=backend.originals[body['message_id']]
                offset=body.get('offset',0); limit=body.get('limit',65536)
                text=original['content'][offset:offset+limit]
                status,value=200,{'ok':True,'value':{'revision':original['revision'],'sha256':original['sha256'],
                    'total_chars':len(original['content']),'offset':offset,'content':text,
                    'next_offset':offset+len(text) if offset+len(text)<len(original['content']) else None}}
            else:
                total = len(backend.messages)
                limit = body.get('limit', 50)
                offset = max(0, total - limit) if body.get('tail') else body.get('offset', 0)
                rows = backend.messages[offset:offset + limit]
                status, value = 200, {'ok': True, 'value': {'items': rows, 'page': {'tail': body.get('tail', False),
                    'total': total, 'offset': offset, 'limit': limit, 'next_offset': offset + len(rows) if offset + len(rows) < total else None}}}
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    output = ROOT / '.tmp/astra-conversation-cache-qa'
    output.mkdir(parents=True, exist_ok=True)
    (output/'failure.png').unlink(missing_ok=True)
    with socket.socket() as candidate:
        candidate.bind(('127.0.0.1', 0)); port = candidate.getsockname()[1]
    log = (output / 'vite.log').open('w', encoding='utf-8')
    vite = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=UI, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    endpoint = f'http://127.0.0.1:{port}/desktop-assets/qa/conversation-cache.html'
    backend = Backend()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.backend = backend
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    source=UI/'src/shell-conversation.jsx'
    report = {'synthetic_only': True, 'production_component_and_transport': True, 'model_inference': False, 'failures': [],
              'conversation_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(endpoint, timeout=1).close(); break
            except OSError:
                if vite.poll() is not None: raise RuntimeError('Vite exited')
                time.sleep(.1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1100})
            context.add_init_script('''sessionStorage.setItem('sentra_native_token','synthetic-cache-qa');
                window.qaHoldReads=false;window.qaHeld=[];
                window.qaResponseKinds=[];window.qaHeldResponses=[];window.qaReceivedResponses=[];
                const originalFetch=window.fetch.bind(window);
                window.fetch=async(...args)=>{
                  let body;try{body=JSON.parse(args[1]?.body||'{}')}catch{}
                  if(window.qaHoldReads&&body?.action==='message_list') await new Promise(resolve=>window.qaHeld.push(resolve));
                  const response=await originalFetch(...args);
                  const kind=body?.action||(String(args[0]).includes('/api/shell/live?')?'live':null);
                  if(window.qaResponseKinds.includes(kind)) {
                    const value=await response.clone().json();
                    window.qaReceivedResponses.push({kind,status:response.status,value});
                    await new Promise(resolve=>window.qaHeldResponses.push({kind,resolve}));
                  }
                  return response;
                };
                window.qaReleaseReads=()=>{window.qaHoldReads=false;window.qaHeld.splice(0).forEach(resolve=>resolve());};
                window.qaReleaseResponses=kind=>{
                  window.qaResponseKinds=window.qaResponseKinds.filter(value=>value!==kind);
                  const release=window.qaHeldResponses.filter(value=>value.kind===kind);
                  window.qaHeldResponses=window.qaHeldResponses.filter(value=>value.kind!==kind);
                  release.forEach(value=>value.resolve());
                };
            ''')
            def route_api(route):
                if route.request.url.split('?')[0].endswith('/api/shell/bridge'):
                    route.fulfill(response=route.fetch(url=f'http://127.0.0.1:{server.server_port}/api/shell/bridge'))
                elif '/api/shell/live?' in route.request.url:
                    route.fulfill(response=route.fetch(url=f'http://127.0.0.1:{server.server_port}/api/shell/live?' + route.request.url.split('?',1)[1]))
                else:
                    route.fulfill(status=404 if '/api/shell/stream' in route.request.url else 200,
                        content_type='application/json', body=json.dumps({'status': 'idle', 'content': '', 'items': []}))
            context.route('**/api/**', route_api)
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(endpoint)
                page.get_by_text('Mensagem 0122', exact=False).wait_for()
                reads = [row for row in backend.requests if row['action'] == 'message_list']
                assert len(reads) == 1, reads
                assert reads[0].get('tail') is True
                report['initial_tail_reads'] = len(reads)
                # Reverse pagination covers every message; no middle range is hidden.
                older = page.get_by_role('button', name='Carregar mais mensagens', exact=True)
                older.click(); page.wait_for_function('document.querySelectorAll(".shell-message").length>0')
                page.get_by_role('button', name='Exibir todo o histórico carregado').click()
                page.wait_for_function('document.querySelectorAll(".shell-message").length===100')
                older.click(); page.wait_for_function('document.querySelectorAll(".shell-message").length===123')
                assert older.count() == 0
                report['complete_history_count'] = page.locator('.shell-message').count()
                # Reader keeps old range when a disjoint new tail arrives.
                page.locator('.shell-transcript').evaluate('(node)=>{node.scrollTop=0;node.dispatchEvent(new Event("scroll",{bubbles:true}));}')
                backend.append(100)
                page.evaluate('document.dispatchEvent(new Event("visibilitychange"))')
                page.get_by_role('button', name='Há novas mensagens · Ir para o mais recente', exact=True).wait_for()
                assert page.locator('.shell-message').count() == 123
                assert page.get_by_text('Mensagem 0222', exact=False).count() == 0
                page.get_by_role('button', name='Há novas mensagens · Ir para o mais recente', exact=True).click()
                page.get_by_text('Mensagem 0222', exact=False).wait_for()
                assert page.locator('.shell-message').count() == 50
                report['disjoint_tail_requires_explicit_adoption'] = True
                # RAM preview paints before a deliberately stalled read, without receipts or exports.
                page.get_by_role('button', name='Fechar QA', exact=True).click()
                page.evaluate('window.qaHoldReads=true')
                start = time.perf_counter()
                page.get_by_role('button', name='Abrir QA', exact=True).click()
                page.locator('.shell-cache-note').wait_for()
                page.get_by_text('Mensagem 0222', exact=False).wait_for()
                report['warm_preview_ms'] = round((time.perf_counter() - start) * 1000, 2)
                assert page.locator('.shell-cached-message').count() == 50
                assert page.locator('.shell-cached-message button, .shell-cached-message a, .shell-cached-message .shell-receipt').count() == 0
                assert page.locator('.shell-chat-intro').count() == 0
                assert page.evaluate('window.qaHeld.length') == 1
                page.screenshot(path=str(output / 'warm-cache-1440.png'), full_page=True)
                page.evaluate('window.qaReleaseReads()')
                page.locator('.shell-cache-note').wait_for(state='detached')
                assert page.locator('.shell-cached-message').count() == 0
                report['warm_preview_replaced_only_after_read'] = True
                # Freeze a complete HTTP 200 payload after it has reached fetch,
                # not before sending its request. Authentication loss invalidates
                # this old read even though its network response was successful.
                page.evaluate("window.qaResponseKinds=['message_list']")
                before=len([row for row in backend.requests if row['action']=='message_list'])
                page.evaluate('document.dispatchEvent(new Event("visibilitychange"))')
                page.wait_for_function("window.qaHeldResponses.some(row=>row.kind==='message_list')")
                received=page.evaluate("window.qaReceivedResponses.filter(row=>row.kind==='message_list').at(-1)")
                assert received['status']==200
                assert received['value']['value']['items'][-1]['message_id']=='message-0222'
                assert len([row for row in backend.requests if row['action']=='message_list'])==before+1
                page.evaluate("window.qaHoldReads=true;window.dispatchEvent(new Event('sentra:auth-recovery-failed'))")
                page.wait_for_function('document.querySelectorAll(".shell-message").length===0&&window.qaCacheStats().entries===0')
                page.evaluate("window.qaReleaseResponses('message_list')")
                page.wait_for_timeout(300)
                assert page.locator('.shell-message').count()==0,'Old successful history response resurrected text'
                assert page.locator('.shell-receipt').count()==0,'Old successful history response resurrected receipts'
                assert page.evaluate('window.qaCacheStats().entries')==0,'Old successful history response repopulated cache'
                assert page.locator('.shell-chat-intro').count()==0,'Denied history was presented as a new empty conversation'
                assert page.locator('.shell-chat-stream-status').get_attribute('data-state')=='access_unavailable'
                assert 'texto preservado' not in page.locator('.shell-chat-stream-status').inner_text()
                report['auth_epoch_discards_received_history_response_without_cache_or_receipt']=True
                report['denied_history_has_explicit_access_state_without_empty_intro']=True
                page.screenshot(path=str(output/'auth-late-history-discarded-1440.png'),full_page=True)
                page.evaluate('window.qaReleaseReads();document.dispatchEvent(new Event("visibilitychange"))')
                page.get_by_text('Mensagem 0222',exact=False).wait_for()
                page.wait_for_function('window.qaCacheStats().entries===1')
                assert len([row for row in backend.requests if row['action']=='message_list'])>=before+2
                report['only_post_invalidation_history_read_recovers']=True

                # The same race also applies to the compatibility live read.
                backend.live={'status':'generating','activity':'Recebendo resposta','operation_id':'op-synthetic-auth-race',
                    'sequence':501,'content':'PREVIA ANTIGA RECEBIDA ANTES DA PERDA DE AUTORIZACAO',
                    'partial':True,'authoritative':False}
                page.evaluate("window.qaResponseKinds=['live'];document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_function("window.qaHeldResponses.some(row=>row.kind==='live')")
                received=page.evaluate("window.qaReceivedResponses.filter(row=>row.kind==='live').at(-1)")
                assert received['status']==200 and received['value']['sequence']==501
                page.evaluate("window.qaHoldReads=true;window.dispatchEvent(new Event('sentra:auth-recovery-failed'))")
                page.wait_for_function('window.qaCacheStats().entries===0')
                page.evaluate("window.qaReleaseResponses('live')")
                page.wait_for_timeout(300)
                assert page.locator('.shell-live-preview').count()==0,'Old successful live response resurrected text'
                assert page.locator('.shell-receipt').count()==0
                assert page.evaluate('window.qaCacheStats().entries')==0
                report['auth_epoch_discards_received_live_response']=True
                backend.live={'status':'idle','content':''}
                page.evaluate('window.qaReleaseReads();document.dispatchEvent(new Event("visibilitychange"))')
                page.get_by_text('Mensagem 0222',exact=False).wait_for()
                page.wait_for_function('window.qaCacheStats().entries===1')
                # A previously received full-body read may not survive access
                # invalidation in the component's private full-content cache.
                original='ORIGINAL SINTETICO COMPLETO — leitura protegida 🦉\n'*200
                original_sha=hashlib.sha256(original.encode()).hexdigest()
                with backend.lock:
                    backend.originals['message-0222']={'content':original,'revision':1,'sha256':original_sha}
                    backend.messages[-1].update(content_truncated=True,content_ref={
                        'action':'message_content','message_id':'message-0222','revision':1,
                        'sha256':original_sha,'total_chars':len(original)})
                page.evaluate('document.dispatchEvent(new Event("visibilitychange"))')
                page.get_by_role('button',name='Ler original completo',exact=True).wait_for()
                page.evaluate("window.qaResponseKinds=['message_content']")
                before_content=len([row for row in backend.requests if row['action']=='message_content'])
                page.get_by_role('button',name='Ler original completo',exact=True).click()
                page.wait_for_function("window.qaHeldResponses.some(row=>row.kind==='message_content')")
                received=page.evaluate("window.qaReceivedResponses.filter(row=>row.kind==='message_content').at(-1)")
                assert received['status']==200 and received['value']['value']['content']==original
                page.evaluate("window.qaHoldReads=true;window.dispatchEvent(new Event('sentra:auth-recovery-failed'))")
                page.wait_for_function('window.qaCacheStats().entries===0')
                page.evaluate("window.qaReleaseResponses('message_content')")
                page.wait_for_timeout(300)
                assert page.locator('.shell-message-original').count()==0
                assert page.locator('.shell-receipt').count()==0
                assert page.evaluate('window.qaCacheStats().entries')==0
                assert len([row for row in backend.requests if row['action']=='message_content'])==before_content+1
                page.evaluate('window.qaReleaseReads();document.dispatchEvent(new Event("visibilitychange"))')
                page.get_by_role('button',name='Ler original completo',exact=True).wait_for()
                assert page.locator('.shell-message-original').count()==0,'Invalidated original survived in private full-content cache'
                page.get_by_role('button',name='Ler original completo',exact=True).click()
                page.locator('.shell-message-original').wait_for()
                assert page.locator('.shell-message-original').text_content()==original
                assert len([row for row in backend.requests if row['action']=='message_content'])==before_content+2
                report['auth_epoch_discards_received_full_content_and_requires_new_read']=True
                with backend.lock:
                    backend.messages[-1].pop('content_truncated');backend.messages[-1].pop('content_ref')
                page.evaluate('document.dispatchEvent(new Event("visibilitychange"))')
                # Even matching cached text cannot reconcile a restored uncertain send.
                page.get_by_role('button', name='Fechar QA', exact=True).click()
                page.evaluate('''() => {
                    window.qaHoldReads=true;
                    sessionStorage.setItem('sentra_shell_draft:qa-cache:qa-conversation', JSON.stringify({content:'', pending:{
                      action:'message_send',project_id:'qa-cache',space_id:'qa-space',conversation_id:'qa-conversation',
                      request_key:'original-request-222',content:'Mensagem 0222 — conteúdo Unicode 🦉\\nSegunda linha.'}}));
                }''')
                page.get_by_role('button', name='Abrir QA', exact=True).click()
                page.locator('.shell-cache-note').wait_for()
                assert page.get_by_role('textbox', name='Mensagem', exact=True).is_disabled()
                assert page.evaluate("JSON.parse(sessionStorage.getItem('sentra_shell_draft:qa-cache:qa-conversation')).pending.request_key") == 'original-request-222'
                assert not any(row['action'] in {'message_send', 'message_request_status'} for row in backend.requests)
                report['cache_cannot_confirm_matching_pending_send'] = True
                page.evaluate("window.dispatchEvent(new Event('sentra:auth-recovery-failed'))")
                page.locator('.shell-cache-note').wait_for(state='detached')
                assert page.locator('.shell-cached-message').count() == 0
                assert page.get_by_role('textbox', name='Mensagem', exact=True).is_disabled()
                assert page.evaluate('window.qaCacheStats().entries') == 0
                report['auth_failure_clears_already_rendered_cache_without_unlocking_pending'] = True
                page.get_by_role('button', name='Fechar QA', exact=True).click()
                page.evaluate("sessionStorage.removeItem('sentra_shell_draft:qa-cache:qa-conversation');window.qaReleaseReads()")
                # Obtain a fresh canonical projection before testing a separate 403.
                page.get_by_role('button', name='Abrir QA', exact=True).click()
                page.get_by_text('Mensagem 0222', exact=False).wait_for()
                page.wait_for_function('window.qaCacheStats().entries===1')
                page.get_by_role('button', name='Fechar QA', exact=True).click()
                # Denial clears both rendered preview and retained RAM text.
                page.evaluate('window.qaHoldReads=true')
                page.get_by_role('button', name='Abrir QA', exact=True).click()
                page.locator('.shell-cache-note').wait_for()
                backend.revoked = True
                page.evaluate('window.qaReleaseReads()')
                page.locator('.shell-error').wait_for()
                page.wait_for_function('document.querySelectorAll(".shell-message").length===0')
                assert page.evaluate('window.qaCacheStats().entries') == 0
                report['revocation_clears_preview_and_cache'] = True
                assert not errors, errors
            except Exception as error:
                report['failures'].append(traceback.format_exc())
                page.screenshot(path=str(output / 'failure.png'), full_page=True)
            finally:
                report['received_response_evidence']=page.evaluate('''window.qaReceivedResponses.map(row=>({
                  kind:row.kind,http_status:row.status,received_before_release:true,
                  message_count:row.value.value?.items?.length,
                  content_chars:(row.value.value?.content??row.value.content??'').length
                }))''')
                page.evaluate("window.qaReleaseResponses('message_list');window.qaReleaseResponses('live');window.qaReleaseResponses('message_content')")
                page.evaluate('window.qaReleaseReads()')
                report['page_errors'] = errors
                report['requests'] = backend.requests
                context.close(); browser.close()
        report['conversation_source_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==report['conversation_source_sha256']
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=True))
        return bool(report['failures'])
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)
        vite.terminate()
        try: vite.wait(timeout=10)
        except subprocess.TimeoutExpired: vite.kill(); vite.wait(timeout=5)
        log.close()


if __name__ == '__main__':
    raise SystemExit(main())
