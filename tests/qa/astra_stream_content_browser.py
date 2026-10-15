"""Production React/API with synthetic immutable pages over a real isolated HTTP server."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
import traceback
from urllib.parse import parse_qs, urlsplit
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'sentra_canvas/desktop_ui'
SCOPE = {'project_id': 'qa-content', 'space_id': 'qa-space', 'conversation_id': 'qa-conversation'}
BODY = 'INÍCIO da prévia\n' + '🦉 ação Unicode ha haha.\n' * 7000 + '\n[[texto legítimo]] <script>window.qaInjected=true</script> FIM da prévia'
NEW_BODY = BODY + '\nNOVO TRECHO preservado'
PAGE_CHARS = 65536
LONG_BODY = ''.join((f'PAGINA-{index:03d}-INICIO\n' + ('Leitura sintetica preservada.\n' * 2400))[:PAGE_CHARS]
                    for index in range(83)) + '\nFINAL-PAGINA-083'
sha = lambda value: hashlib.sha256(value.encode('utf-8')).hexdigest()


@lru_cache(maxsize=3)
def reference(body):
    return {'reference_id': 'stream-' + sha(body), 'sha256': sha(body), 'total_chars': len(body),
        'total_utf8_bytes': len(body.encode()), 'action': 'stream_content', 'page_max_chars': 65536, 'page_max_utf8_bytes': 262144}


def preview(body=BODY, operation='op-qa-one'):
    return {'status': 'generating', 'operation_id': operation, 'sequence': 123, 'content': 'Último trecho preservado na conversa.',
        'truncated': True, 'partial': True, 'authoritative': False, 'content_ref': reference(body)}


class Backend:
    mode = 'normal'
    def __init__(self):
        self.requests = []; self.forbidden_requests = []; self.pending = threading.Event(); self.release = threading.Event()
        self.bodies = {reference(body)['reference_id']: body for body in (BODY, NEW_BODY, LONG_BODY)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def cors(self):
        self.send_header('Access-Control-Allow-Origin', self.server.browser_origin)
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
    def do_OPTIONS(self):
        self.send_response(204); self.cors(); self.end_headers()
    def do_POST(self):
        self.server.backend.forbidden_requests.append({'method': 'POST', 'path': self.path})
        self.send_response(405); self.cors(); self.end_headers()
    def do_GET(self):
        fields = {key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()}
        assert self.headers.get('Authorization') == 'Bearer synthetic-content-qa'
        assert set(fields) == {*SCOPE, 'reference_id', 'offset', 'limit'}
        assert all(fields[key] == value for key, value in SCOPE.items())
        backend = self.server.backend; backend.requests.append(fields)
        body = backend.bodies[fields['reference_id']]
        ref = reference(body); offset, limit = int(fields['offset']), int(fields['limit'])
        content = body[offset:offset + limit]
        status = {'denied': 403, 'expired': 404}.get(backend.mode, 200)
        value = {**SCOPE, **ref, 'reference_id': ref['reference_id'], 'offset': offset, 'content': content,
            'next_offset': offset + len(content) if offset + len(content) < len(body) else None,
            'page_sha256': sha(content), 'persisted': True, 'partial': True, 'authoritative': False,
            'automatic_retry': False, 'closes_trio': False}
        if status != 200: value = {'error': 'synthetic unavailable'}
        if backend.mode == 'tampered': value['page_sha256'] = '0' * 64
        payload = json.dumps(value).encode()
        silent = backend.mode in ('silent_headers', 'silent_body') and offset == PAGE_CHARS
        try:
            if silent and backend.mode == 'silent_headers':
                backend.pending.set(); backend.release.wait(45)
            self.send_response(status); self.cors(); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload))); self.end_headers()
            if silent and backend.mode == 'silent_body':
                self.wfile.write(payload[:32]); self.wfile.flush()
                backend.pending.set(); backend.release.wait(45)
                payload = payload[32:]
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Expected when production AbortController cancels this isolated read.


def main():
    output = ROOT / '.tmp/astra-stream-content-browser'; output.mkdir(parents=True, exist_ok=True)
    (output / 'failure.png').unlink(missing_ok=True)
    with socket.socket() as candidate:
        candidate.bind(('127.0.0.1', 0)); port = candidate.getsockname()[1]
    log = (output / 'vite.log').open('w', encoding='utf-8')
    vite = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=UI,
        stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    endpoint = f'http://127.0.0.1:{port}/desktop-assets/qa/stream-content.html'
    backend = Backend(); server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.backend = backend
    server.browser_origin = f'http://127.0.0.1:{port}'
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    report = {'synthetic_only': True, 'model_inference': False, 'production_component_and_transport': True, 'scenarios': [], 'failures': []}
    try:
        for _ in range(100):
            try: urllib.request.urlopen(endpoint, timeout=1).close(); break
            except OSError:
                if vite.poll() is not None: raise RuntimeError('Vite exited')
                time.sleep(.1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_init_script('sessionStorage.setItem("sentra_native_token","synthetic-content-qa");window.qaInitialPreview=' + json.dumps(preview()) + ';')
            context.add_init_script('window.qaBackendOrigin=' + json.dumps(f'http://127.0.0.1:{server.server_port}') + ';')
            context.add_init_script('''window.qaHoldOffset=null;window.qaHeld=[];window.qaAborts=[];window.qaApiRequests=[];
                const originalFetch=window.fetch.bind(window);window.fetch=async(...args)=>{
                  const url=new URL(args[0],location.href), options=args[1]||{};
                  if(url.pathname.startsWith('/api/')) {
                    window.qaApiRequests.push({method:options.method||'GET',path:url.pathname,query:url.search,time:performance.now()});
                    options.signal?.addEventListener('abort',()=>window.qaAborts.push({offset:Number(url.searchParams.get('offset')),time:performance.now()}),{once:true});
                    args[0]=window.qaBackendOrigin+url.pathname+url.search;
                  }
                  const response=await originalFetch(...args);
                  if(String(args[0]).includes('/api/shell/stream/content?')&&Number(new URL(args[0],location.href).searchParams.get('offset'))===window.qaHoldOffset){
                    await new Promise((resolve,reject)=>{
                      const cancel=()=>reject(new DOMException('Synthetic delayed response cancelled','AbortError'));
                      if(options.signal?.aborted) {cancel();return;}
                      options.signal?.addEventListener('abort',cancel,{once:true});
                      window.qaHeld.push(()=>{options.signal?.removeEventListener('abort',cancel);resolve();});
                    });
                  } return response;
                };window.qaRelease=()=>{window.qaHoldOffset=null;window.qaHeld.splice(0).forEach(resolve=>resolve());};''')
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(endpoint)
                page.get_by_role('button', name='Ver prévia completa', exact=True).click()
                page.locator('.shell-stream-full-pages').wait_for()
                text = ''.join(page.locator('.shell-stream-content-page').all_text_contents())
                assert text == BODY and sha(text) == reference(BODY)['sha256']
                assert page.evaluate('window.qaInjected===true') is False
                assert page.locator('.qa-retained-window').inner_text() == preview()['content']
                assert page.get_by_role('dialog', name='Prévia salva · ainda não confirmada').count() == 1
                assert page.locator('.shell-stream-content-panel[data-authoritative=false]').count() == 1
                assert page.locator('.shell-stream-content-page button, .shell-stream-content-page script').count() == 0
                report['scenarios'].append('complete_unicode_and_literal_markup')
                page.screenshot(path=str(output / 'complete-1440.png'), full_page=True)
                page.keyboard.press('Escape'); page.get_by_role('dialog').wait_for(state='detached')
                page.wait_for_function('Array.from(document.querySelectorAll("button")).find(node=>node.textContent==="Ver prévia completa")===document.activeElement', timeout=2000)
                # Late response is not displayed after an operation change.
                page.evaluate('window.qaHoldOffset=65536')
                page.get_by_role('button', name='Ver prévia completa', exact=True).click()
                page.wait_for_function('window.qaHeld.length===1')
                page.evaluate('value=>window.qaSetPreview(value)', preview(operation='op-qa-two'))
                page.get_by_role('dialog').wait_for(state='detached')
                page.evaluate('window.qaRelease()'); page.wait_for_timeout(100)
                assert page.locator('.shell-stream-full-pages').count() == 0
                report['scenarios'].append('late_operation_page_discarded')
                # Newer head of the same operation does not change the immutable read.
                page.evaluate('window.qaHoldOffset=65536')
                page.get_by_role('button', name='Ver prévia completa', exact=True).click()
                page.wait_for_function('window.qaHeld.length===1')
                page.evaluate('value=>window.qaSetPreview(value)', preview(NEW_BODY, 'op-qa-two'))
                page.get_by_role('button', name='Consultar prévia mais recente', exact=True).wait_for()
                page.evaluate('window.qaRelease()')
                page.locator('.shell-stream-full-pages').wait_for()
                assert ''.join(page.locator('.shell-stream-content-page').all_text_contents()) == BODY
                page.get_by_role('button', name='Consultar prévia mais recente', exact=True).click()
                page.wait_for_function('document.querySelector(".shell-stream-full-pages")?.textContent.includes("NOVO TRECHO preservado")')
                report['scenarios'].append('same_operation_snapshot_then_explicit_refresh')
                page.evaluate("window.dispatchEvent(new Event('sentra:auth-recovery-failed'))")
                page.get_by_role('dialog').wait_for(state='detached')
                assert page.locator('.shell-stream-content-page').count() == 0
                report['scenarios'].append('auth_failure_clears_loaded_body')
                # Page integrity, expiry and denial fail closed without a retry.
                for mode in ('tampered', 'expired', 'denied'):
                    backend.mode = mode; before = len(backend.requests)
                    page.get_by_role('button', name='Ver prévia completa', exact=True).click()
                    page.get_by_role('alert').wait_for()
                    assert page.locator('.shell-stream-content-page').count() == 0
                    assert len(backend.requests) == before + 1
                    if mode == 'denied': assert page.evaluate('window.qaAccessDenied') is True
                    page.keyboard.press('Escape'); page.get_by_role('dialog').wait_for(state='detached')
                    report['scenarios'].append(mode + '_no_retry_no_body')
                backend.mode = 'normal'
                page.evaluate('window.qaHoldOffset=65536')
                page.get_by_role('button', name='Ver prévia completa', exact=True).click()
                page.wait_for_function('window.qaHeld.length===1')
                page.evaluate('value=>window.qaSetScope(value)', {**SCOPE, 'conversation_id': 'other-conversation'})
                page.get_by_role('dialog').wait_for(state='detached')
                page.evaluate('window.qaRelease()'); page.wait_for_timeout(100)
                assert page.locator('.shell-stream-content-page').count() == 0
                report['scenarios'].append('late_scope_page_discarded')
                page.evaluate('value=>window.qaSetScope(value)', SCOPE)
                page.evaluate('value=>window.qaSetPreview(value)', preview(LONG_BODY, 'op-qa-large'))
                before = len(backend.requests); started = time.monotonic()
                page.get_by_role('button', name='Ver prévia completa', exact=True).click()
                page.locator('.shell-message-window[data-windowed=true][data-total="84"]').wait_for(timeout=60000)
                loaded_seconds = time.monotonic()-started
                requests = backend.requests[before:]
                assert [int(value['offset']) for value in requests] == list(range(0, len(LONG_BODY), PAGE_CHARS))
                assert len(requests) == 84
                max_nodes = 0; samples = []
                for position in ('first', 'middle', 'last'):
                    target = {'first':0, 'middle':42, 'last':83}[position]
                    for _ in range(15):
                        page.locator('.shell-stream-full-pages').evaluate('''(node,target)=>{
                          const slots=[...node.querySelectorAll('.shell-message-slot')];
                          const index=slot=>Number(slot.dataset.messageId.split(':').at(-1));
                          const exact=slots.find(slot=>index(slot)===target);
                          const anchor=exact||(target>index(slots.at(-1))?slots.at(-1):slots[0]);
                          const top=node.scrollTop+anchor.getBoundingClientRect().top-node.getBoundingClientRect().top;
                          node.scrollTop=exact?top:target>index(anchor)
                            ?top+anchor.getBoundingClientRect().height+(target-index(anchor)-1)*240
                            :top-(index(anchor)-target)*240;
                        }''', target)
                        page.wait_for_timeout(120)
                        nodes = page.locator('.shell-stream-content-page').evaluate_all('nodes=>nodes.map(node=>({id:node.dataset.page,text:node.textContent}))')
                        if any(node['id'].endswith(':'+str(target)) for node in nodes): break
                    assert 1 <= len(nodes) <= 24, (position, len(nodes))
                    max_nodes = max(max_nodes, len(nodes))
                    for node in nodes:
                        index = int(node['id'].rsplit(':', 1)[1])
                        assert node['text'] == LONG_BODY[index * PAGE_CHARS:(index + 1) * PAGE_CHARS]
                    indices = [int(node['id'].rsplit(':', 1)[1]) for node in nodes]
                    assert target in indices, (position,target,indices)
                    samples.append({'position': position, 'page_indices': indices, 'dom_pages': len(nodes)})
                    page.screenshot(path=str(output / f'virtualized-{position}-1440.png'), full_page=True)
                report['virtualization'] = {'pages': 84, 'chars': len(LONG_BODY), 'load_seconds': round(loaded_seconds, 3),
                    'max_sampled_dom_pages': max_nodes, 'samples': samples, 'source_sha256': sha(LONG_BODY)}
                report['scenarios'].append('84_pages_virtualized_first_middle_last_exact_content')
                page.keyboard.press('Escape'); page.get_by_role('dialog').wait_for(state='detached')

                # Native fetch remains pending over the isolated HTTP connection.
                # Closing must abort that exact read and never start another page/prompt.
                page.evaluate('value=>window.qaSetPreview(value)', preview(operation='op-qa-cancel'))
                for close_kind, mode in (('escape','silent_headers'), ('button','silent_body')):
                    backend.mode=mode; backend.pending.clear(); backend.release.clear()
                    before=len(backend.requests); before_abort=page.evaluate('window.qaAborts.length')
                    page.get_by_role('button', name='Ver prévia completa', exact=True).click()
                    page.wait_for_function('document.querySelector("[role=status]")?.textContent.includes("65.536")')
                    assert backend.pending.wait(2), 'HTTP response did not reach its controlled stall'
                    if close_kind=='escape': page.keyboard.press('Escape')
                    else: page.get_by_role('button', name='Fechar', exact=True).click()
                    page.get_by_role('dialog').wait_for(state='detached')
                    page.wait_for_function('value=>window.qaAborts.length>value', arg=before_abort)
                    backend.release.set(); page.wait_for_timeout(250)
                    assert len(backend.requests)==before+2
                    assert page.locator('.shell-stream-content-page').count()==0
                    assert page.locator('.qa-retained-window').inner_text()==preview()['content']
                    report['scenarios'].append('close_'+close_kind+'_'+mode+'_aborts_http_no_retry')

                # An authentication loss during an actual pending body clears
                # the selection; late bytes may not resurrect its modal.
                backend.mode='silent_body'; backend.pending.clear(); backend.release.clear()
                before=len(backend.requests); before_abort=page.evaluate('window.qaAborts.length')
                page.get_by_role('button', name='Ver prévia completa', exact=True).click()
                page.wait_for_function('document.querySelector("[role=status]")?.textContent.includes("65.536")')
                assert backend.pending.wait(2)
                page.evaluate("window.dispatchEvent(new Event('sentra:auth-recovery-failed'))")
                page.get_by_role('dialog').wait_for(state='detached')
                page.wait_for_function('value=>window.qaAborts.length>value',arg=before_abort)
                backend.release.set();page.wait_for_timeout(250)
                assert len(backend.requests)==before+2
                assert page.locator('.shell-stream-content-page').count()==0
                assert page.get_by_role('dialog').count()==0
                assert page.locator('.qa-retained-window').inner_text()==preview()['content']
                report['scenarios'].append('auth_loss_pending_http_aborts_no_late_body_or_retry')

                # Reopen the same operation with a newer immutable reference
                # before the cancelled old HTTP response has been released.
                backend.mode='silent_body';backend.pending.clear();backend.release.clear()
                page.get_by_role('button',name='Ver prévia completa',exact=True).click()
                page.wait_for_function('document.querySelector("[role=status]")?.textContent.includes("65.536")')
                assert backend.pending.wait(2)
                page.keyboard.press('Escape');page.get_by_role('dialog').wait_for(state='detached')
                backend.mode='normal'
                page.evaluate('value=>window.qaSetPreview(value)',preview(NEW_BODY,'op-qa-cancel'))
                page.get_by_role('button',name='Ver prévia completa',exact=True).click()
                page.locator('.shell-stream-full-pages').wait_for()
                assert ''.join(page.locator('.shell-stream-content-page').all_text_contents())==NEW_BODY
                before_release=len(backend.requests)
                backend.release.set();page.wait_for_timeout(300)
                assert ''.join(page.locator('.shell-stream-content-page').all_text_contents())==NEW_BODY
                assert page.locator('.shell-stream-content-panel').get_attribute('data-reference')==reference(NEW_BODY)['reference_id']
                assert len(backend.requests)==before_release
                assert page.get_by_role('alert').count()==0
                report['scenarios'].append('reopen_new_reference_survives_cancelled_old_http_response')
                page.keyboard.press('Escape');page.get_by_role('dialog').wait_for(state='detached')

                backend.mode='silent_body'; backend.pending.clear(); backend.release.clear()
                before=len(backend.requests); before_abort=page.evaluate('window.qaAborts.length')
                page.get_by_role('button', name='Ver prévia completa', exact=True).click()
                page.wait_for_function('document.querySelector("[role=status]")?.textContent.includes("65.536")')
                assert backend.pending.wait(2)
                silence_started=time.monotonic()
                page.get_by_role('alert').wait_for(timeout=35000)
                elapsed=time.monotonic()-silence_started
                assert 27 <= elapsed <= 35, elapsed
                assert 'nenhuma mensagem foi reenviada' in page.get_by_role('alert').inner_text()
                assert page.evaluate('window.qaAborts.length')>before_abort
                backend.release.set(); page.wait_for_timeout(500)
                assert len(backend.requests)==before+2
                assert page.locator('.shell-stream-content-page').count()==0
                assert page.locator('.qa-retained-window').inner_text()==preview()['content']
                report['silence_timeout']={'seconds':round(elapsed,3),'requests':len(backend.requests)-before,'retried':False,'prompt_sent':False}
                page.screenshot(path=str(output / 'silence-timeout-1440.png'), full_page=True)
                report['scenarios'].append('30s_body_silence_aborts_http_no_retry_no_prompt')
                assert not backend.forbidden_requests,backend.forbidden_requests
                api_requests=page.evaluate('window.qaApiRequests')
                assert all(value['method']=='GET' and value['path']=='/api/shell/stream/content' for value in api_requests)
                report['api_request_methods']=sorted({value['method'] for value in api_requests})
                assert not errors, errors
            except Exception as error:
                report['failures'].append(traceback.format_exc()); page.screenshot(path=str(output / 'failure.png'), full_page=True)
            finally:
                backend.release.set(); page.evaluate('window.qaRelease()'); report['page_errors'] = errors; report['requests'] = backend.requests
                context.close(); browser.close()
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key:value for key,value in report.items() if key!='requests'}, ensure_ascii=True)); return bool(report['failures'])
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)
        vite.terminate()
        try: vite.wait(timeout=10)
        except subprocess.TimeoutExpired: vite.kill(); vite.wait(timeout=5)
        log.close()


if __name__ == '__main__': raise SystemExit(main())
