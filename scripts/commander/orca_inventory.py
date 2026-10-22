"""Reproducible provenance/license inventory for the experimental integration."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
PIN='70b2197c97b164b16c618736a107967295e5af92'
ADAPTED={
 'src/renderer/src/components/tab-bar/SortableTab.tsx':'sentra_canvas/desktop_ui/src/workspace/OrcaTabStrip.jsx',
 'src/renderer/src/components/tab-bar/tab-bar-surface.tsx':'sentra_canvas/desktop_ui/src/workspace/OrcaTabStrip.jsx',
 'src/renderer/src/components/tab-bar/tab-width-rules.ts':'sentra_canvas/desktop_ui/src/workspace/OrcaTabStrip.jsx',
 'src/renderer/src/components/right-sidebar/FileExplorerRow.tsx':'sentra_canvas/desktop_ui/src/workspace/WorkspaceExplorer.jsx',
 'src/renderer/src/assets/main.css':'sentra_canvas/desktop_ui/src/workspace/workspace.css',
 'src/renderer/src/components/tab-group/TabGroupSplitNodeTree.tsx':'sentra_canvas/desktop_ui/src/workspace/OrcaSplit.jsx',
 'src/shared/tab-types.ts':'sentra_canvas/desktop_ui/src/workspace/layout.js',
 'src/main/runtime/orchestration/coordinator-dag-convergence.ts':'sentra_runtime/orchestration_observation.py',
 'src/main/acp/acp-dialects/opencode-dialect.ts':'sentra_interop/acp_dialects.py',
 'mobile/src/transport/pairing-keychain.ts':'integrations/orca-mobile/app/App.tsx',
 'mobile/src/session/MobileNativeChatCardHeaderAction.tsx':'integrations/orca-mobile/app/components/CardHeaderAction.tsx',
 'src/main/daemon/daemon-stream-backpressure.ts':'integrations/orca-terminal/src/consumer-flow.mjs',
}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    source=parser.parse_args().source.resolve(strict=True)
    subprocess.check_call(['git','-C',str(source),'cat-file','-e',PIN+'^{commit}'])
    def original(path):
        return subprocess.check_output(['git','-C',str(source),'show',PIN+':'+path])
    destination=ROOT/'vendor'/'orca'
    transport=ROOT/'integrations'/'orca-mobile'/'transport'/'src'/'vendor'
    copied={}
    for target in sorted(transport.glob('*.ts')):
        path='src/shared/'+target.name;origin=original(path)
        if origin!=target.read_bytes():raise ValueError('copied ORCA transport has drifted: '+target.name)
        copied[path]=hashlib.sha256(origin).hexdigest()
    terminal=ROOT/'integrations/orca-terminal'
    terminal_provenance=json.loads((terminal/'provenance.json').read_text(encoding='utf-8'))
    if terminal_provenance['commit']!=PIN:raise ValueError('terminal ORCA pin differs from inventory')
    terminal_files=terminal_provenance['copied_files']
    for path,digest in terminal_files.items():
        origin=original(path)
        if hashlib.sha256(origin).hexdigest()!=digest or (terminal/'vendor/orca'/path).read_bytes()!=origin:
            raise ValueError('copied ORCA terminal has drifted: '+path)
    (destination/'LICENSE').write_bytes(original('LICENSE'))
    adapted=[{'source':s,'target':t,'source_sha256':hashlib.sha256(original(s)).hexdigest()} for s,t in ADAPTED.items()]
    provenance={'repository':'https://github.com/stablyai/orca','commit':PIN,'license':'MIT',
        'source_hash_mode':'git-blob-sha256','transport_files':copied,'terminal_files':terminal_files,'adapted':adapted,'assets_imported':[],
        'excluded':['branding','cloud accounts','telemetry','updater','global store','grant authority']}
    (destination/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8')
    projects=['sentra_canvas/desktop_ui','integrations/orca-mobile/transport','integrations/orca-mobile/app','integrations/opencode','integrations/orca-terminal']
    packages=[]
    for project in projects:
        folder=ROOT/project;lock=json.loads((folder/'package-lock.json').read_text(encoding='utf-8'))
        for path,record in sorted(lock['packages'].items()):
            if not path or record.get('link'):continue
            packages.append({'project':project,'path':path,'version':record.get('version'),
                'license':record.get('license','UNDECLARED'), 'integrity':record.get('integrity'),
                'resolved':record.get('resolved'),'development':bool(record.get('dev')),
                'optional':bool(record.get('optional'))})
    (destination/'dependencies.json').write_text(json.dumps({'schema':1,'scope':'lockfile packages, including development and optional platforms',
        'packages':packages},indent=2)+'\n',encoding='utf-8')
    for folder in ('integrations/orca-mobile/app','integrations/orca-mobile/transport'):
        notices=ROOT/folder/'THIRD_PARTY_LICENSES';notices.mkdir(exist_ok=True)
        (notices/'ORCA.txt').write_bytes(original('LICENSE'))
        (notices/'orca-license.json').write_text(json.dumps({'text':original('LICENSE').decode('utf-8')},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Verified {len(copied)} transport modules, {len(terminal_files)} terminal files, {len(adapted)} adaptations and {len(packages)} dependency records.')


if __name__=='__main__':main()
