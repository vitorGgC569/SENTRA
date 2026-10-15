"""Actual MV3 worker termination + isolated browser restart; no provider/account I/O.

The staged extension has two relay URL substitutions plus lifecycle diagnostic
listeners. Its manifest is restamped as a TEST
identity; no production bootstrap, token or browser profile is copied.
"""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError
from scripts.commander.extension_identity import stage_extension_source, stamp_extension_identity
from native_bridge.extension_sources import extension_source_identity

TEST_TOKEN='SENTRA-MV3-QA-NOT-A-PRODUCTION-CREDENTIAL'
ACTIVE_KEY='oma_active_3456789'
RESULT_KEY='oma_result_job_mv3_qa'


class Relay(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self):
        super().__init__(('127.0.0.1',0),Handler)
        self.identity={};self.requests=[];self.results=[];self.result_available=False


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_args):pass
    def respond(self,code,body):
        encoded=json.dumps(body).encode()
        self.send_response(code);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
    def do_GET(self):
        self.server.requests.append(('GET',self.path))
        if self.path=='/extension/version':return self.respond(200,self.server.identity)
        return self.respond(501,{'error':'unexpected synthetic relay GET'})
    def do_POST(self):
        self.server.requests.append(('POST',self.path))
        if self.headers.get('Authorization')!='Bearer '+TEST_TOKEN:return self.respond(401,{'error':'test auth required'})
        length=int(self.headers.get('Content-Length','0'))
        if length>100_000:return self.respond(413,{'error':'test budget exceeded'})
        body=json.loads(self.rfile.read(length) or b'{}')
        if self.path=='/jobs/result':
            if not self.server.result_available:return self.respond(503,{'error':'induced test outage'})
            self.server.results.append(body);return self.respond(200,{'ok':True})
        if self.path=='/extension/heartbeat':return self.respond(200,{'ok':True})
        if self.path=='/browser-evidence/invalidate':return self.respond(200,{'state':'invalidated','grants_created':False})
        if self.path=='/workers/release':return self.respond(200,{'ok':True})
        return self.respond(501,{'error':'no execution supported by this synthetic relay'})


def wait_until(page,predicate,*,timeout=5000):
    deadline=time.monotonic()+timeout/1000
    while time.monotonic()<deadline:
        if predicate():return
        page.wait_for_timeout(50)
    raise AssertionError('Timed out awaiting isolated browser state')


def launch(playwright,profile,extension):
    return playwright.chromium.launch_persistent_context(str(profile),headless=True,channel='chromium',
        ignore_default_args=['--disable-extensions'],
        args=[f'--disable-extensions-except={extension}',f'--load-extension={extension}',
              '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1'])


def crash_owned_browser(context):
    """Terminate only the browser reached through this owned context's CDP pipe.

    Pin its Windows process handle before the crash and verify actual process
    exit; losing the debugging connection alone is not sufficient evidence.
    """
    if sys.platform!='win32':raise RuntimeError('Crash verification requires Windows process handles')
    import ctypes
    from ctypes import wintypes
    browser=context.browser
    cdp=browser.new_browser_cdp_session()
    processes=cdp.send('SystemInfo.getProcessInfo')['processInfo']
    pid=int(next(item['id'] for item in processes if item['type']=='browser'))
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype=wintypes.BOOL
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    kernel.TerminateProcess.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x00100000|0x1000|0x0001,False,pid)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        # Browser.crash destroys Chromium but can leave its CDP response
        # unresolved in the driver. A pinned process handle avoids awaiting a
        # command whose recipient must die before responding, and avoids PID
        # reuse or matching/killing any other browser process.
        if not kernel.TerminateProcess(handle,0xDEAD):raise ctypes.WinError(ctypes.get_last_error())
        assert kernel.WaitForSingleObject(handle,10000)==0,'Owned browser did not terminate'
        code=wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
        assert code.value!=259,'Owned browser remains active'
        assert code.value!=0,'Requested crash unexpectedly exited successfully'
        return {'browser_process_id':pid,'process_exit_verified':True,'exit_code':code.value,
                'method':'TerminateProcess on pinned handle; PID obtained from owned browser CDP session'}
    finally:kernel.CloseHandle(handle)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser-restart',choices=('graceful','crash'),default='graceful')
    args=parser.parse_args()
    output=ROOT/'.tmp'/'astra-mv3-lifecycle';output.mkdir(parents=True,exist_ok=True)
    relay=Relay();thread=threading.Thread(target=relay.serve_forever,daemon=True);thread.start()
    report={'model_inference':False,'provider_accounts_used':False,'production_services_accessed':False,
        'test_relay':'synthetic ephemeral loopback','browser_restart_mode':args.browser_restart,'phases':[],
        'qa_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        with tempfile.TemporaryDirectory(prefix='sentra-mv3-qa-',ignore_cleanup_errors=True) as temporary:
            base=Path(temporary);extension=base/'extension';profile=base/'profile'
            source_identity=extension_source_identity(ROOT/'edge_extension')
            stage_extension_source(ROOT/'edge_extension',extension)
            assert not (extension/'sentra-bootstrap.json').exists()
            replacement=f'http://127.0.0.1:{relay.server_port}'
            for name in ('service-worker.js','options.js'):
                path=extension/name;text=path.read_text(encoding='utf-8')
                assert text.count('http://127.0.0.1:8765')==1
                path.write_text(text.replace('http://127.0.0.1:8765',replacement),encoding='utf-8')
            worker_path=extension/'service-worker.js'
            worker_path.write_text(worker_path.read_text(encoding='utf-8')+"\n"+
                "chrome.runtime.onStartup.addListener(()=>chrome.storage.local.set({qa_startup_seen:Date.now()}));\n"+
                "chrome.runtime.onInstalled.addListener(details=>chrome.storage.local.set({qa_install_seen:{at:Date.now(),reason:details.reason}}));\n",encoding='utf-8')
            staged=stamp_extension_identity(extension)
            relay.identity={'version':staged['version'],'build_id':staged['build_id'],'source_hash':staged['source_hash']}
            (extension/'qa.html').write_text('<!doctype html><meta charset=utf-8><title>Isolated MV3 QA</title>',encoding='utf-8')
            (extension/'sentra-distribution.json').write_text(json.dumps({'qa_only':True,
                'production_source_hash':source_identity['source_hash'],'test_source_hash':staged['source_hash'],
                'modifications':['service-worker.js relay URL and diagnostic listeners','options.js relay URL','qa.html test driver'],
                'production_bootstrap_copied':False},indent=2),encoding='utf-8')
            report.update(production_source_hash=source_identity['source_hash'],test_source_hash=staged['source_hash'])
            with sync_playwright() as playwright:
                context=launch(playwright,profile,extension)
                try:
                    worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker',timeout=10000)
                    extension_id=worker.url.split('/')[2]
                    page=context.new_page();page.goto(f'chrome-extension://{extension_id}/qa.html')
                    active={'job_id':'websend_mv3_qa','worker':'TAB-3456789','lease_token':'synthetic-original-lease',
                        'kind':'CHAT_TASK','send_reserved':True,'observe_only':True,
                        'assistant_revision':13,'assistant_message_id':'qa-assistant-id','assistant_signature':'a'*64}
                    result={'job_id':'job_mv3_qa','task_id':'task_mv3_qa','worker':'TAB-QA','lease_token':'synthetic-result-lease',
                        'status':'COMPLETED','result':'Synthetic MV3 result; no model called'}
                    initial={'oma_enabled':False,'oma_user_disabled':True,'oma_relay_token':TEST_TOKEN,
                        'oma_pool_instance_id':'POOL-12345678-MV3-QA','sentra_id_profile_epoch':'profile-mv3-qa-12345678',
                        ACTIVE_KEY:active,RESULT_KEY:result}
                    wait_until(page,lambda:page.evaluate("()=>chrome.storage.local.get('qa_install_seen').then(v=>!!v.qa_install_seen)"))
                    report['initial_lifecycle_events']=page.evaluate("()=>chrome.storage.local.get(['qa_startup_seen','qa_install_seen'])")
                    page.evaluate('values=>chrome.storage.local.set(values)',initial)
                    worker.evaluate('omaFlushOutbox()')
                    before=page.evaluate('keys=>chrome.storage.local.get(keys)',list(initial))
                    assert before[RESULT_KEY]==result and before[ACTIVE_KEY]==active
                    report['phases'].append({'name':'transient_503','outbox_retained':True})

                    # Playwright can retain the extension Worker wrapper across
                    # runtime restarts; prove JS-global loss plus CDP stopped /
                    # running transitions instead of assuming wrapper.close.
                    worker.evaluate("globalThis.__sentraQaLifetime='before-forced-stop'")
                    cdp=context.new_cdp_session(page);versions={}
                    def version_update(event):
                        for item in event.get('versions',[]):versions[item['versionId']]=item
                    cdp.on('ServiceWorker.workerVersionUpdated',version_update);cdp.send('ServiceWorker.enable')
                    wait_until(page,lambda:any(item.get('scriptURL')==worker.url and item.get('runningStatus')=='running' for item in versions.values()))
                    version=next(item for item in versions.values() if item.get('scriptURL')==worker.url and item.get('runningStatus')=='running')
                    cdp.send('ServiceWorker.stopWorker',{'versionId':version['versionId']})
                    wait_until(page,lambda:versions.get(version['versionId'],{}).get('runningStatus')=='stopped')
                    page.evaluate("()=>chrome.runtime.sendMessage({operation:'OMA_IDLE_WAKE'})")
                    wait_until(page,lambda:versions.get(version['versionId'],{}).get('runningStatus')=='running')
                    assert worker.evaluate("typeof globalThis.__sentraQaLifetime==='undefined'"),'Stopped worker retained its previous JS globals'
                    after=page.evaluate('keys=>chrome.storage.local.get(keys)',list(initial))
                    for key in (ACTIVE_KEY,RESULT_KEY,'oma_pool_instance_id','sentra_id_profile_epoch'):assert after[key]==before[key]
                    assert worker.evaluate('omaPoolInstanceId()')==initial['oma_pool_instance_id']
                    assert worker.evaluate('omaIdProfileEpoch()')==initial['sentra_id_profile_epoch']
                    report['phases'].append({'name':'forced_worker_stop_and_wake','cdp_stopped_then_running':True,
                        'previous_js_context_destroyed':True,'outbox_identity_and_cursor_retained':True})
                    worker.evaluate('omaSaveActive(3456789,{observe_only:false})')
                    pre_restart=page.evaluate('key=>chrome.storage.local.get(key).then(v=>v[key])',ACTIVE_KEY)
                    assert pre_restart['observe_only'] is False
                    prior_updated=pre_restart['updated']
                    report['pre_restart_active']=pre_restart
                    if args.browser_restart=='crash':
                        report['browser_crash']=crash_owned_browser(context)
                finally:
                    if context.browser.is_connected():
                        try:context.close()
                        except PlaywrightError:
                            if not report.get('browser_crash',{}).get('process_exit_verified'):raise

                context=launch(playwright,profile,extension)
                try:
                    page=context.new_page();page.goto(f'chrome-extension://{extension_id}/qa.html')
                    if not context.service_workers:
                        with context.expect_event('serviceworker',timeout=10000) as started:
                            page.evaluate("()=>chrome.runtime.sendMessage({operation:'OMA_IDLE_WAKE'})")
                        worker=started.value
                    else:worker=context.service_workers[0]
                    try:
                        wait_until(page,lambda:page.evaluate('key=>chrome.storage.local.get(key).then(v=>v[key]?.observe_only===true)',ACTIVE_KEY),timeout=10000)
                    finally:
                        report['restart_lifecycle_events']=page.evaluate("()=>chrome.storage.local.get(['qa_startup_seen','qa_install_seen'])")
                    restored=page.evaluate('keys=>chrome.storage.local.get(keys)',list(initial))
                    preserved=restored[ACTIVE_KEY]
                    report['post_restart_active']=preserved
                    assert preserved['updated']>prior_updated,'Browser startup did not refresh observation-only metadata'
                    assert all(preserved[key]==active[key] for key in active if key!='observe_only')
                    assert restored[RESULT_KEY]==result
                    assert restored['oma_pool_instance_id']==initial['oma_pool_instance_id']
                    assert restored['sentra_id_profile_epoch']==initial['sentra_id_profile_epoch']
                    report['phases'].append({'name':'whole_browser_restart','mode':args.browser_restart,'profile_reused':True,
                        'identity_cursor_and_outbox_retained':True,'web_recovery_observation_only':True,
                        'cleanup_event':'onInstalled' if report['restart_lifecycle_events'].get('qa_install_seen',{}).get('at',0)>
                            report['initial_lifecycle_events'].get('qa_install_seen',{}).get('at',0) else 'onStartup'})
                    relay.result_available=True;worker.evaluate('omaFlushOutbox()')
                    assert page.evaluate('key=>chrome.storage.local.get(key).then(v=>!(key in v))',RESULT_KEY)
                    assert relay.results==[result]
                    report['phases'].append({'name':'relay_available','stored_result_delivered_once':True,'outbox_acknowledged':True})
                    report['browser_version']=context.browser.version
                finally:context.close()
            paths=relay.requests
            forbidden=[path for method,path in paths if any(term in path for term in ('/jobs/submit','/jobs/poll','/jobs/progress','/jobs/receipt','/auth/bootstrap'))]
            assert not forbidden,forbidden
            assert extension_source_identity(ROOT/'edge_extension')==source_identity,'Production source changed during QA'
            report.update(success=True,prompt_submission_calls=0,relay_requests=[{'method':method,'path':path} for method,path in paths],
                source_unchanged=True,source_files_sha256=source_identity['files'],
                limits=['Synthetic relay, no attested provider delivery','No real accounts, inference or OS suspend',
                        'Browser crash verified by pinned process handle' if args.browser_restart=='crash' else
                            'Graceful full browser restart; worker stop was forced',
                        'Staged relay URL substitutions and lifecycle diagnostics; not installed release proof',
                        'Unpacked relaunch delivered onInstalled, not onStartup; both callbacks covered by unit tests'])
    except BaseException as exc:
        report.update(success=False,error_type=type(exc).__name__,error=str(exc)[:1200]);raise
    finally:
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (output/f'report-{args.browser_restart}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        relay.shutdown();relay.server_close();thread.join(timeout=5)
    print(json.dumps({key:value for key,value in report.items() if key not in {'source_files_sha256','relay_requests'}},ensure_ascii=True))


if __name__=='__main__':main()
