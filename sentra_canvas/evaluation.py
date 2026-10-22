"""Run current source/assets with separate state, without replacing an installation."""
from __future__ import annotations
import argparse
import html as html_text
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]


def prepare_state(path):
    state=Path(path).resolve()
    marker=state/'sentra-evaluation.json'
    if state.exists() and any(state.iterdir()) and not marker.is_file():
        raise ValueError('Evaluation requires a separate empty state directory')
    state.mkdir(parents=True,exist_ok=True)
    if marker.is_file():
        if json.loads(marker.read_text(encoding='utf-8'))!={'product':'SENTRA isolated evaluation','schema':1}:
            raise ValueError('Unknown evaluation state')
    else:marker.write_text(json.dumps({'product':'SENTRA isolated evaluation','schema':1}),encoding='utf-8')
    return state


def seed(app):
    if app.store.workspaces():
        return json.loads((app.state_dir/'evaluation-scope.json').read_text(encoding='utf-8'))
    project=app.create_workspace('SENTRA_Avaliacao')['id']
    runtime=app._runtime();run=runtime.run(project)
    if run['state']!='RUNNING':runtime.durable.transition_run(run['run_id'],runtime.owner,'RUNNING')
    home=app.shell_bridge({'action':'home','project_id':project})['value']
    scope={'project_id':project,'space_id':home['space']['space_id']}
    catalog=app.model_catalog()['models']
    if not catalog:raise RuntimeError('No model catalog available for evaluation Dot')
    model=next((m for m in catalog if m=='sentra/chatgpt-web/gpt-6'),catalog[0])
    if isinstance(model,dict):model=model.get('id') or model.get('model')
    def create(name,**fields):
        return app.shell_bridge({'action':'dot_create',**scope,'name':name,'role':'coordinator',
            'model':model,'request_key':'evaluation-'+uuid.uuid4().hex,**fields})['value']
    dot=create('Oxta Avaliacao',mascot='blue')
    create('Subagente Avaliacao',mascot='mint',canvas_root_dot_id=dot['dot_id'])
    scope['dot_id']=dot['dot_id']
    (app.state_dir/'evaluation-scope.json').write_text(json.dumps(scope),encoding='utf-8')
    return scope


def prepare_assets(state,scope,title='SENTRA · Avaliação ORCA'):
    source=ROOT/'sentra_canvas/static'
    build=ROOT/'sentra_canvas/desktop_ui/.tmp/orca-workspace-build'
    if not (build/'desktop.js').is_file():raise RuntimeError('Run build:orca-validation first')
    target=state/'evaluation-ui';target.mkdir(exist_ok=True)
    for file in source.iterdir():
        if file.name=='desktop-assets':continue
        if file.is_file():shutil.copy2(file,target/file.name)
        elif file.is_dir():shutil.copytree(file,target/file.name,dirs_exist_ok=True)
    assets=target/'desktop-assets';shutil.copytree(build,assets,dirs_exist_ok=True)
    shutil.copy2(source/'desktop-assets/bootstrap.js',assets/'bootstrap.js')
    navigation={'view':'canvas',**scope,'conversation_id':None}
    boot="localStorage.setItem('sentra-orca-workspace-enabled','1');\n"
    boot+="localStorage.setItem('sentra_shell_navigation',"+json.dumps(json.dumps(navigation))+');\n'
    (assets/'evaluation-bootstrap.js').write_text(boot,encoding='utf-8')
    html=(build/'index.html').read_text(encoding='utf-8')
    html=html.replace('<title>SENTRA Desktop</title>','<title>'+html_text.escape(title)+'</title>')
    html=html.replace('<head>','<head><script src="/desktop-assets/evaluation-bootstrap.js"></script>')
    (target/'desktop.html').write_text(html,encoding='utf-8')
    return target


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--electron',type=Path)
    parser.add_argument('--mobile',action='store_true')
    parser.add_argument('--mobile-port',type=int,default=5197)
    parser.add_argument('--title',default='SENTRA · Avaliação ORCA')
    parser.add_argument('--stop',action='store_true')
    args=parser.parse_args()
    if args.stop:
        if not (args.state/'sentra-evaluation.json').is_file():raise ValueError('Not an evaluation state')
        from .broker import read_endpoint
        endpoint=read_endpoint(prepare_state(args.state))
        if endpoint is None:raise RuntimeError('Evaluation broker unavailable')
        endpoint.request('/api/runtime/shutdown',{})
        return
    state=prepare_state(args.state)
    from .service import Canvas
    from . import __main__ as http
    from .broker import publish_endpoint,remove_endpoint
    app=Canvas(state/'workspace',state_dir=state)
    server=None;mobile=None
    try:
        scope=seed(app);http.STATIC=prepare_assets(state,scope,args.title)
        server=http.CanvasServer(app,0);publish_endpoint(server)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        if args.mobile:
            node=shutil.which('node')
            if not node:raise RuntimeError('Node unavailable for LAN evaluation')
            mobile=subprocess.Popen([sys.executable,'-m','sentra_canvas.mobile_host','--state',str(state),
                '--bind','auto','--port',str(args.mobile_port),'--node',node],cwd=ROOT,
                stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if args.electron:
            from . import electron_host
            executable=args.electron.resolve(strict=True)
            display=state/'display';display.mkdir(exist_ok=True)
            (state/'display-profile').mkdir(exist_ok=True)
            entry="const {app}=require('electron');app.setPath('userData',"+json.dumps(str(state/'display-profile'))+");\n"
            entry+='require('+json.dumps(str(ROOT/'sentra_electron/evaluation_diagnostics.cjs'))+').installEvaluationDiagnostics(app,'+json.dumps(str(state))+');\n'
            entry+='require('+json.dumps(str(ROOT/'sentra_electron/main.cjs'))+');\n'
            (display/'main.cjs').write_text(entry,encoding='utf-8')
            electron_host.SURFACE=display;electron_host.electron_binary=lambda:executable
            electron_host.launch_electron(server,wait=False)
        print('SENTRA isolated evaluation ready; no installed state copied.',flush=True)
        while thread.is_alive():time.sleep(.5)
    finally:
        if mobile and mobile.poll() is None:mobile.terminate();mobile.wait(timeout=10)
        if server:server.shutdown();server.server_close();remove_endpoint(server)
        app.shutdown()


if __name__=='__main__':main()
