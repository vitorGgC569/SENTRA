"""Render a credential-free, network-fenced page in the native Windows backend."""
from __future__ import annotations
import argparse,json,re,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

def check(report: Path, nonce: str) -> int:
    if not re.fullmatch('[a-f0-9]{32}',nonce):raise ValueError('invalid probe nonce')
    result={'schema':1,'nonce':nonce,'backend':'native','frozen':getattr(sys,'frozen',False),
            'renderer_loaded':False,'node_absent':False,'network_blocked':False,'window_destroyed':False}
    requests=[];window=None;closed=threading.Event();loaded=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(True);self.send_response(200);self.end_headers()
        def log_message(self,*_):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        import webview
        html=("<!doctype html><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; "
              "script-src 'unsafe-eval'; connect-src 'none'; base-uri 'none'; form-action 'none'\">"
              "<meta name='sentra-native-probe' content='"+nonce+"'><title>SENTRA native display check</title>")
        window=webview.create_window('SENTRA native display check',html=html,
            hidden=True,width=320,height=200,js_api=None)
        def on_loaded():
            if loaded.is_set():return
            loaded.set()
            try:
                value=window.evaluate_js("({nonce:document.querySelector('meta[name=sentra-native-probe]').content,"
                    "nodeAbsent:typeof process==='undefined'&&typeof require==='undefined'})")
                result['renderer_loaded']=value.get('nonce')==nonce
                result['node_absent']=value.get('nodeAbsent') is True
                window.evaluate_js("window.__sentraProbeBlocked=null;fetch('http://127.0.0.1:"
                    +str(server.server_port)+"/probe').then(()=>window.__sentraProbeBlocked=false)"
                    ".catch(()=>window.__sentraProbeBlocked=true)")
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    observed=window.evaluate_js('window.__sentraProbeBlocked')
                    if observed is not None:
                        result['network_blocked']=observed is True and not requests;break
                    time.sleep(.05)
            except Exception as exc:result['error_type']=type(exc).__name__
            finally:window.destroy()
        window.events.loaded+=on_loaded
        window.events.closed+=closed.set
        webview.start(gui='edgechromium',debug=False,private_mode=True)
        result['window_destroyed']=closed.is_set()
    except Exception as exc:result['error_type']=type(exc).__name__
    finally:
        server.shutdown();server.server_close();thread.join(2)
        result['ok']=all(result[key] is True for key in ('renderer_loaded','node_absent','network_blocked','window_destroyed'))
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return 0 if result['ok'] else 2

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path,required=True);parser.add_argument('--nonce',required=True)
    args=parser.parse_args();raise SystemExit(check(args.report,args.nonce))
