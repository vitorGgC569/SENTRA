"""Browser contracts plus explicitly opt-in REAL Chromium acceptance.

SENTRA_PLAYWRIGHT_ACCEPTANCE=1 makes missing Playwright/binaries a failure.
The default skip is reported as unavailable runtime proof, never success.
"""
import asyncio
import importlib.util
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sentra_executors.playwright_browser import (
    NetworkProfile, PlaywrightBrowserBinding, PlaywrightBrowserBackend,
    declare_playwright_browser_machine, origin, redacted_url,
)
from sentra_executors.rpa import AuthorizedPaths
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.executor import ExecutorRegistry


class NetworkContracts(unittest.TestCase):
    def test_profiles_are_exact_origins_and_methods(self):
        p = NetworkProfile('site', 'allowlist', ('https://example.test',), max_redirects=0)
        self.assertTrue(p.permits('https://example.test/path?secret=hidden'))
        self.assertFalse(p.permits('https://example.test.evil.test/path'))
        self.assertFalse(p.permits('http://example.test/path'))
        self.assertFalse(p.permits('https://example.test/path', 'POST'))
        self.assertFalse(p.permits('https://example.test/path', redirects=1))

    def test_offline_loopback_and_bounded_redirect_controls(self):
        self.assertFalse(NetworkProfile('offline').permits('https://example.test/'))
        for kwargs in (
            dict(name='host', mode='loopback', allowed_origins=('http://localhost:8000',)),
            dict(name='remote', mode='loopback', allowed_origins=('http://8.8.8.8',)),
            dict(name='path', mode='allowlist', allowed_origins=('https://example.test/private',)),
            dict(name='redirect', mode='allowlist', allowed_origins=('https://example.test',), max_redirects=21),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                NetworkProfile(**kwargs)

    def test_evidence_urls_remove_queries_credentials_and_fragments(self):
        self.assertEqual(redacted_url('https://example.test/path?token=secret#secret'),
                         'https://example.test:443/path')
        self.assertEqual(redacted_url('https://user:password@example.test/'), 'non_http_url')
        with self.assertRaises(ValueError):
            origin('file:///C:/secret.txt')

    def test_missing_provider_has_explicit_failed_diagnosis(self):
        if importlib.util.find_spec('playwright'):
            self.skipTest('Playwright installed; this case covers real absence only')
        backend = PlaywrightBrowserBackend()
        self.addCleanup(backend.shutdown)
        b = PlaywrightBrowserBinding('browser', (NetworkProfile('offline'),))
        d = declare_playwright_browser_machine(machine_id='browser-absence', owner_principal_id='p',
            bindings=(b,), policy=lambda r: PolicyDecision(True, 'absence diagnosis'), backend=backend)
        result = asyncio.run(d.adapter.start(OperationRequest('absent', 'p', 'browser-absence',
            'browser', 'w', 'absent-key', {'action': 'open', 'profile': 'offline'})))
        self.assertEqual((result.state, result.error), ('FAILED', 'dependency_missing_playwright'))
        self.assertEqual(result.evidence['required'], 'playwright')

    def test_unknown_fields_and_unapproved_policy_do_not_launch(self):
        b = PlaywrightBrowserBinding('browser', (NetworkProfile('offline'),))
        d = declare_playwright_browser_machine(machine_id='browser-policy', owner_principal_id='p',
            bindings=(b,), policy=None)
        self.addCleanup(d.adapter.backend.shutdown)
        denied = asyncio.run(d.adapter.start(OperationRequest('denied', 'p', 'browser-policy',
            'browser', 'w', 'deny-key', {'action': 'open', 'profile': 'offline'})))
        self.assertEqual(denied.error, 'policy_denied')
        invalid = asyncio.run(d.adapter.start(OperationRequest('invalid', 'p', 'browser-policy',
            'browser', 'w', 'invalid-key', {'action': 'open', 'profile': 'offline', 'storage_state': 'user.json'})))
        self.assertEqual(invalid.error, 'invalid_scope_or_capability')
        self.assertIsNone(d.adapter.backend._browser)

    def test_unit_actor_preserves_effect_context(self):
        # Scheduling contract only: no claim of browser or durable lease proof.
        from sentra_runtime.effect_boundary import current_effect_context
        class ActorContextProbe(PlaywrightBrowserBackend):
            def _dispatch(self, binding, arguments, deadline):
                return current_effect_context.get()
        marker = object()
        backend = ActorContextProbe()
        self.addCleanup(backend.shutdown)
        binding = PlaywrightBrowserBinding('probe', (NetworkProfile('offline'),))
        token = current_effect_context.set(marker)
        try:
            self.assertIs(backend.run(binding, {'action':'unit-context-probe'}), marker)
        finally:
            current_effect_context.reset(token)


@unittest.skipUnless(os.environ.get('SENTRA_PLAYWRIGHT_ACCEPTANCE') == '1',
    'REAL browser acceptance disabled; set SENTRA_PLAYWRIGHT_ACCEPTANCE=1 with Playwright/Chromium installed')
class RealPlaywrightAcceptance(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='sentra-real-playwright-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.hits = []
        hits = self.hits
        class Handler(BaseHTTPRequestHandler):
            forbidden_origin = ''
            cross_origin = ''
            def do_GET(handler):
                hits.append((handler.server.server_port, handler.path))
                if handler.path == '/redirect':
                    handler.send_response(302)
                    handler.send_header('Location', Handler.forbidden_origin + '/should-not-arrive')
                    handler.end_headers()
                    return
                redirects={'/allowed-redirect/one':'/allowed-redirect/two',
                           '/allowed-redirect/two':'/nested/final', '/loop/a':'/loop/b','/loop/b':'/loop/a'}
                if handler.path in redirects:
                    handler.send_response(302); handler.send_header('Location',redirects[handler.path]); handler.end_headers(); return
                if handler.path=='/nested/final':
                    body=b'<html><body>Final URL<script src="helper.js"></script></body></html>'
                elif handler.path=='/nested/helper.js':
                    body=b"document.body.append(' relative script reached');"
                elif handler.path=='/frames':
                    body=b'''<html><body><iframe src="/frame"></iframe><div id="host"></div>
                    <script>const r=document.getElementById('host').attachShadow({mode:'open'});
                    r.innerHTML='<label for="s">Shadow name</label><input id="s"><button id="sb">Shadow save</button><p id="so"></p>';
                    r.getElementById('sb').onclick=()=>r.getElementById('so').textContent=r.getElementById('s').value;</script></body></html>'''
                elif handler.path=='/frame':
                    body=b'''<html><body><label for="f">Frame name</label><input id="f"><button onclick="document.getElementById('fo').textContent=document.getElementById('f').value">Frame save</button><p id="fo"></p></body></html>'''
                elif handler.path=='/cross-frames':
                    body=('<html><body><iframe src="'+Handler.cross_origin+'/frame"></iframe></body></html>').encode()
                elif handler.path=='/body.json':
                    body=b'{"actual":"captured response"}'
                elif handler.path=='/capture':
                    body=b'<html><body><script>fetch("/body.json").then(r=>r.json()).then(j=>document.body.append(j.actual));</script></body></html>'
                else:
                    body = ('''<!doctype html><html><body>
                    <label for="name">Name</label><input id="name">
                    <button onclick="document.getElementById('out').textContent=document.getElementById('name').value;
                        localStorage.setItem('saved',document.getElementById('name').value)">Save</button>
                    <p id="out">empty</p>
                    <script>document.getElementById('out').textContent=localStorage.getItem('saved') || 'empty';
                    console.log('real-browser-acceptance');
                    fetch('__BLOCKED_ORIGIN__/blocked?token=secret').catch(() => {});
                    </script></body></html>''').replace('__BLOCKED_ORIGIN__', Handler.forbidden_origin).encode()
                handler.send_response(200)
                handler.send_header('Content-Type', 'application/javascript' if handler.path.endswith('.js')
                    else 'application/json' if handler.path.endswith('.json') else 'text/html')
                handler.send_header('Content-Length', str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)
            def log_message(self, *_):
                pass
        self.allowed_server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.blocked_server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.cross_server = ThreadingHTTPServer(('127.0.0.2', 0), Handler)
        for server in (self.allowed_server, self.blocked_server,self.cross_server):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{self.allowed_server.server_port}'
        Handler.forbidden_origin = f'http://127.0.0.1:{self.blocked_server.server_port}'
        Handler.cross_origin = f'http://127.0.0.2:{self.cross_server.server_port}'
        binding = PlaywrightBrowserBinding('browser.real', (
            NetworkProfile('loopback', 'loopback', (self.url,)),
            NetworkProfile('two-origins','loopback',(self.url,Handler.cross_origin)),NetworkProfile('offline')),
            artifact_paths=AuthorizedPaths((str(self.root),), (str(self.root),)))
        self.backend = PlaywrightBrowserBackend()
        self.addCleanup(self.backend.shutdown)
        policy = lambda r: PolicyDecision(True, 'explicit real loopback acceptance')
        self.declaration = declare_playwright_browser_machine(machine_id='real-browser',
            owner_principal_id='acceptance', bindings=(binding,), policy=policy, backend=self.backend)
        self.registry = ExecutorRegistry(authorize=policy)
        self.declaration.register(self.registry)
        self.counter = 0

    async def invoke(self, **arguments):
        self.counter += 1
        return await self.registry.submit(OperationRequest(f'browser-{self.counter}',
            'acceptance', 'real-browser', 'browser.real', 'browser-work', f'browser-key-{self.counter}', arguments))

    def assert_success(self, result):
        self.assertEqual(result.state, 'SUCCEEDED', (result.error, result.evidence))
        return result.evidence

    async def open_page(self):
        opened = self.assert_success(await self.invoke(action='open', profile='loopback'))
        sid = opened['session_id']
        self.assert_success(await self.invoke(action='navigate', session_id=sid, url=self.url + '/form'))
        return sid

    @staticmethod
    def reference(observation, role, name=None):
        element = next(e for e in observation['elements'] if e['role'] == role and (name is None or e['name'] == name))
        return {k: observation[k] for k in ('page_id', 'revision', 'observation_id')} | {
            'element_ref': element['element_ref'], 'role': element['role'], 'name': element['name']}

    def test_real_form_stale_references_png_and_console_network_evidence(self):
        async def scenario():
            sid = await self.open_page()
            observed = self.assert_success(await self.invoke(action='observe', session_id=sid))
            self.assert_success(await self.invoke(action='fill', session_id=sid,
                text='SENTRA actual browser', **self.reference(observed, 'textbox', 'Name')))
            stale = await self.invoke(action='click', session_id=sid, **self.reference(observed, 'button', 'Save'))
            self.assertEqual((stale.state, stale.error), ('FAILED', 'stale_browser_observation'))
            observed = self.assert_success(await self.invoke(action='observe', session_id=sid))
            self.assert_success(await self.invoke(action='click', session_id=sid, **self.reference(observed, 'button', 'Save')))
            observed = self.assert_success(await self.invoke(action='observe', session_id=sid))
            text = self.assert_success(await self.invoke(action='read', session_id=sid, **self.reference(observed, 'document')))
            self.assertIn('SENTRA actual browser', text['text'])
            output = self.root / 'page.png'
            screenshot = self.assert_success(await self.invoke(action='screenshot', session_id=sid, output=str(output)))
            self.assertTrue(output.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertTrue(screenshot['artifact']['verified_before_publish'])
            events = self.assert_success(await self.invoke(action='evidence', session_id=sid))['events']
            self.assertTrue(any(e['kind'] == 'console' for e in events))
            self.assertTrue(any(e['kind'] == 'request' and not e['allowed'] for e in events))
            self.assertFalse(any('token=secret' in str(e) for e in events))
            self.assertFalse(any(port == self.blocked_server.server_port for port, _ in self.hits))
            self.assert_success(await self.invoke(action='close', session_id=sid))
        asyncio.run(scenario())

    def test_context_storage_isolation_and_foreign_page_references(self):
        async def scenario():
            first = await self.open_page()
            observed = self.assert_success(await self.invoke(action='observe', session_id=first))
            self.assert_success(await self.invoke(action='fill', session_id=first, text='private session',
                                              **self.reference(observed, 'textbox', 'Name')))
            observed = self.assert_success(await self.invoke(action='observe', session_id=first))
            self.assert_success(await self.invoke(action='click', session_id=first, **self.reference(observed, 'button', 'Save')))
            observed = self.assert_success(await self.invoke(action='observe', session_id=first))
            second = await self.open_page()
            second_observation = self.assert_success(await self.invoke(action='observe', session_id=second))
            foreign = await self.invoke(action='click', session_id=second, **self.reference(observed, 'button', 'Save'))
            self.assertEqual(foreign.error, 'stale_browser_observation')
            text = self.assert_success(await self.invoke(action='read', session_id=second,
                **self.reference(second_observation, 'document')))['text']
            self.assertIn('empty', text)
            self.assertNotIn('private session', text)
            self.assert_success(await self.invoke(action='network', session_id=second, profile='offline'))
            denied = await self.invoke(action='navigate', session_id=second, url=self.url + '/form')
            self.assertEqual(denied.error, 'browser_navigation_network_denied')
        asyncio.run(scenario())

    def test_redirect_never_reaches_unapproved_origin(self):
        async def scenario():
            sid = await self.open_page()
            result = await self.invoke(action='navigate', session_id=sid, url=self.url + '/redirect')
            self.assertNotEqual(result.state, 'SUCCEEDED')
            events = self.assert_success(await self.invoke(action='evidence', session_id=sid))['events']
            self.assertTrue(any(e['kind'] == 'redirect_blocked' for e in events))
            self.assertFalse(any(port == self.blocked_server.server_port for port, _ in self.hits))
        asyncio.run(scenario())

    def test_allowed_redirects_preserve_final_url_and_relative_resources(self):
        async def scenario():
            sid=await self.open_page()
            result=self.assert_success(await self.invoke(action='navigate',session_id=sid,url=self.url+'/allowed-redirect/one'))
            self.assertTrue(result['url'].endswith('/nested/final'))
            observed=self.assert_success(await self.invoke(action='observe',session_id=sid))
            read=self.assert_success(await self.invoke(action='read',session_id=sid,**self.reference(observed,'document')))
            self.assertIn('relative script reached',read['text'])
            events=self.assert_success(await self.invoke(action='evidence',session_id=sid))['events']
            self.assertTrue(any(e.get('redirect_depth')==2 and e.get('allowed') for e in events))
        asyncio.run(scenario())

    def test_redirect_loop_is_bounded(self):
        async def scenario():
            sid=await self.open_page()
            result=await self.invoke(action='navigate',session_id=sid,url=self.url+'/loop/a')
            self.assertNotEqual(result.state,'SUCCEEDED')
            events=self.assert_success(await self.invoke(action='evidence',session_id=sid))['events']
            self.assertTrue(any(e['kind']=='redirect_blocked' for e in events))
            self.assertLessEqual(len([p for _,p in self.hits if p.startswith('/loop/')]),9)
        asyncio.run(scenario())

    def test_frame_and_shadow_actions_are_revision_bound(self):
        async def scenario():
            sid=await self.open_page()
            self.assert_success(await self.invoke(action='navigate',session_id=sid,url=self.url+'/frames'))
            o=self.assert_success(await self.invoke(action='observe',session_id=sid))
            self.assertEqual(len(o['frames']),2)
            shadow=self.reference(o,'textbox','Shadow name')
            frame=self.reference(o,'textbox','Frame name')
            self.assert_success(await self.invoke(action='fill',session_id=sid,text='shadow value',**shadow))
            stale=await self.invoke(action='fill',session_id=sid,text='not allowed',**frame)
            self.assertEqual(stale.error,'stale_browser_observation')
            o=self.assert_success(await self.invoke(action='observe',session_id=sid))
            self.assertTrue(any(e['shadow_path'] for e in o['elements']))
            self.assert_success(await self.invoke(action='fill',session_id=sid,text='frame value',**self.reference(o,'textbox','Frame name')))
            o=self.assert_success(await self.invoke(action='observe',session_id=sid))
            self.assert_success(await self.invoke(action='click',session_id=sid,**self.reference(o,'button','Frame save')))
            o=self.assert_success(await self.invoke(action='observe',session_id=sid))
            frame_body=next(e for e in o['elements'] if e['role']=='document' and e['frame_id']!=o['frames'][0]['frame_id'])
            reference={k:o[k] for k in ('page_id','revision','observation_id')}|{'element_ref':frame_body['element_ref'],'frame_id':frame_body['frame_id']}
            text=self.assert_success(await self.invoke(action='read',session_id=sid,**reference))['text']
            self.assertIn('frame value',text)
        asyncio.run(scenario())

    def test_capture_exports_real_body_and_session_diagnostics(self):
        import json,base64
        async def scenario():
            sid=await self.open_page()
            self.assert_success(await self.invoke(action='capture.start',session_id=sid))
            self.assert_success(await self.invoke(action='navigate',session_id=sid,url=self.url+'/capture'))
            self.assert_success(await self.invoke(action='observe',session_id=sid))
            report=self.assert_success(await self.invoke(action='diagnostics',session_id=sid))
            self.assertEqual(report['sessions'][0]['capture_state'],'recording')
            output=self.root/'capture.json'
            self.assert_success(await self.invoke(action='capture.stop',session_id=sid,output=str(output)))
            records=json.loads(output.read_text(encoding='utf-8'))['records']
            self.assertTrue(any(base64.b64decode(r['body_base64'])==b'{"actual":"captured response"}' for r in records))
            self.assert_success(await self.invoke(action='close',session_id=sid))
            report=self.assert_success(await self.invoke(action='diagnostics',session_id=sid))
            self.assertEqual(report['sessions'][0]['state'],'closed')
        asyncio.run(scenario())

    def test_different_work_item_cannot_use_browser_session(self):
        async def scenario():
            sid=await self.open_page()
            result=await self.registry.submit(OperationRequest('foreign-work','acceptance','real-browser',
                'browser.real','another-work','foreign-work-key',{'action':'observe','session_id':sid}))
            self.assertEqual(result.error,'browser_session_scope_mismatch')
        asyncio.run(scenario())

    def test_cross_site_frame_is_guarded_and_actionable(self):
        async def scenario():
            sid=await self.open_page()
            self.assert_success(await self.invoke(action='network',session_id=sid,profile='two-origins'))
            self.assert_success(await self.invoke(action='navigate',session_id=sid,url=self.url+'/cross-frames'))
            o=self.assert_success(await self.invoke(action='observe',session_id=sid))
            self.assert_success(await self.invoke(action='fill',session_id=sid,text='cross site value',
                **self.reference(o,'textbox','Frame name')))
            events=self.assert_success(await self.invoke(action='evidence',session_id=sid))['events']
            self.assertTrue(any(e['kind']=='target_guarded' and e['target_type']=='iframe' for e in events))
        asyncio.run(scenario())

    def test_capture_byte_limit_is_explicit_and_does_not_save_a_truncated_success(self):
        from dataclasses import replace
        import json
        original=self.declaration.adapter.bindings['browser.real']
        binding=replace(original,max_capture_bytes=16)
        declaration=declare_playwright_browser_machine(machine_id='small-capture',owner_principal_id='acceptance',
            bindings=(binding,),policy=lambda r:PolicyDecision(True,'bounded capture acceptance'),backend=self.backend)
        declaration.register(self.registry)
        async def invoke(**arguments):
            self.counter+=1
            return await self.registry.submit(OperationRequest('small-'+str(self.counter),'acceptance','small-capture',
                'browser.real','browser-work','small-key-'+str(self.counter),arguments))
        async def scenario():
            sid=self.assert_success(await invoke(action='open',profile='loopback'))['session_id']
            self.assert_success(await invoke(action='capture.start',session_id=sid))
            self.assert_success(await invoke(action='navigate',session_id=sid,url=self.url+'/capture'))
            self.assert_success(await invoke(action='observe',session_id=sid))
            output=self.root/'limited.json'
            self.assert_success(await invoke(action='capture.stop',session_id=sid,output=str(output)))
            actual=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(actual['prior_state'],'failed')
            self.assertLessEqual(actual['bytes'],16)
            self.assertFalse(actual['completeness_asserted'])
        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
