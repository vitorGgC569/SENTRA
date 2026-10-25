"""Basic Windows packaged checks without installation or existing profile changes.

Run from the source checkout with an unused output directory:
python tests/qa/windows_preview_smoke.py --dist <built-dist> --output <new-report-dir>
This is not clean-machine installation, login, upgrade or signing qualification.
"""
import argparse,hashlib,json,os,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from sentra_canvas.broker import read_endpoint

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dist',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--payload-only',action='store_true',help='Check frozen components before the native Setup is available')
    args=parser.parse_args()
    dist=args.dist.resolve();output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    report={'scope':'packaged smoke only; no installation, account login or clean-machine qualification',
        'status':'running','installed_profiles_changed':False,'authenticode_claimed':False}
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    process=None;endpoint=None
    def run(name,arguments,timeout=180):
        with (output/(name+'.log')).open('wb') as stream:
            result=subprocess.run(arguments,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout,creationflags=flags)
        if result.returncode:raise RuntimeError(name+' exited '+str(result.returncode))
    try:
        from sentra_remote.installer_engine import original_filename
        setup = dist/'SENTRA-Setup.exe'
        native_setup = not args.payload_only and original_filename(setup) == 'SENTRA-Inno-Setup.exe'
        # Inno does not implement the Python worker's diagnostic switches.
        # Passing those switches to it could start installation instead.
        setup_probed = not args.payload_only and not native_setup
        if setup_probed:
            run('setup-check',[str(setup),'--check','--report-file',str(output/'setup-check.json'),
                '--install-dir',str(output/'unused-install-target')])
            check=json.loads((output/'setup-check.json').read_text(encoding='utf-8'))
            assert check['payload_ok'] and check['payload_verified'] and check['exit_code']==0
            run('setup-gui',[str(setup),'--gui-check','--gui-check-report',str(output/'setup-gui.json')])
            gui=json.loads((output/'setup-gui.json').read_text(encoding='utf-8'))
            assert gui['ok'] and gui['frozen'] and gui['window_destroyed']
        for name in ('sentra-cli','sentra','sentra-mcp'):
            run(name+'-help',[str(dist/(name+'.exe')),'--help'])
        state=output/'canvas-state';root=output/'workspace';root.mkdir()
        log=(output/'canvas.log').open('wb')
        process=subprocess.Popen([str(dist/'sentra-canvas.exe'),'--root',str(root),'--state-dir',str(state),
            '--broker','--port','0','--no-open'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        def owned_pid(pid):
            if pid==process.pid:return True
            if os.name!='nt':return False
            # PyInstaller onefile starts a second, same-executable process.
            raw=subprocess.check_output(['powershell','-NoProfile','-Command',
                'Get-CimInstance Win32_Process -Filter "ProcessId = '+str(int(pid))+'" | '
                'Select-Object ParentProcessId,ExecutablePath | ConvertTo-Json -Compress'],
                creationflags=flags,timeout=15)
            item=json.loads(raw.decode('utf-8-sig'))
            return (item['ParentProcessId']==process.pid and
                Path(item['ExecutablePath']).resolve()==(dist/'sentra-canvas.exe').resolve())
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('packaged Canvas exited before health')
            candidate=read_endpoint(state)
            if candidate and owned_pid(candidate.pid):
                endpoint=candidate;break
            time.sleep(.2)
        else:raise TimeoutError('packaged Canvas health not observed')
        health=endpoint.request('/api/health');assert health['ok'] and health['pid']==endpoint.pid
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def fetch(path):
            request=urllib.request.Request('http://127.0.0.1:'+str(endpoint.server_port)+path,
                headers={'Authorization':'Bearer '+endpoint.secret})
            with opener.open(request,timeout=30) as response:return response.read(32*1024*1024)
        assert b'desktop-assets/bootstrap.js' in fetch('/desktop.html')
        manifest=json.loads(fetch('/desktop-assets/manifest.json'))
        checked={}
        for name in ('desktop.js','desktop.css','bootstrap.js'):
            data=fetch('/desktop-assets/'+name);assert hashlib.sha256(data).hexdigest()==manifest['files'][name]
            checked[name]=len(data)
        setup_digest=None
        if not args.payload_only:
            with setup.open('rb') as setup_stream:
                setup_digest=hashlib.file_digest(setup_stream,'sha256').hexdigest()
        report.update(status='passed',setup_check=setup_probed,setup_hidden_gui=setup_probed,cli_help=True,
            native_setup_qualification_pending=native_setup, payload_only=args.payload_only,
            packaged_canvas_health=True,packaged_asset_hashes=checked,
            setup_sha256=setup_digest,
            setup_bytes=None if args.payload_only else setup.stat().st_size)
    except Exception as error:report.update(status='failed',error_type=type(error).__name__,error=str(error)[:700])
    finally:
        if endpoint:
            try:endpoint.request('/api/runtime/shutdown',{})
            except (OSError,ValueError):pass
        if process:
            try:process.wait(timeout=20)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
        report['own_canvas_closed']=process is None or process.poll() is not None
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report),flush=True)
    return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
