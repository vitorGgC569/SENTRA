"""Read-only headless mirrors. This child has neither PTY input nor host credentials."""
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import uuid
import zlib


class SnapshotUnavailable(RuntimeError):
    pass


class TerminalSnapshots:
    def __init__(self):
        self.available=False;self.error=None;self.process=None
        self.responses=queue.Queue(2);self.lock=threading.Lock()
        root=Path(__file__).resolve().parents[1]/'integrations/orca-terminal'
        node=os.environ.get('SENTRA_TERMINAL_NODE') or shutil.which('node')
        if getattr(sys,'frozen',False):
            try:
                from scripts.commander.stage_mobile import validate_mobile_runtime
                from scripts.commander.stage_terminal import validate_terminal_runtime
                install=Path(sys.executable).resolve().parent
                root=install/'sentra-terminal';node=install/'sentra-mobile/node.exe'
                validate_mobile_runtime(node.parent);validate_terminal_runtime(root)
            except (OSError,ValueError,KeyError,TypeError):
                self.error='snapshot_runtime_integrity_unconfirmed';return
        if not node or not (root/'dist/engine.cjs').is_file():
            self.error='snapshot_runtime_unavailable';return
        try:
            manifest=json.loads((root/'dist/manifest.json').read_text(encoding='utf-8'))
            if manifest.get('version')!=1:raise SnapshotUnavailable('snapshot_build_mismatch')
            for name,digest in manifest['sources'].items():
                source=(root/name).resolve()
                if not source.is_relative_to(root.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
                    raise SnapshotUnavailable('snapshot_build_stale')
            if hashlib.sha256((root/'dist/engine.cjs').read_bytes()).hexdigest()!=manifest['output']:
                raise SnapshotUnavailable('snapshot_build_mismatch')
            environment={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP','PATH'}}
            self.process=subprocess.Popen([str(node),str(root/'src/worker.mjs')],cwd=root,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                text=True,encoding='utf-8',env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            threading.Thread(target=self._read,daemon=True).start()
            ready=self.responses.get(timeout=3)
            if (ready.get('ready') is not True or ready.get('engine_version')!=1 or ready.get('pid')!=self.process.pid
                    or ready.get('build_id')!=manifest['build_id']):
                raise SnapshotUnavailable('snapshot_protocol_mismatch')
            self.available=True
        except (OSError,ValueError,KeyError,TypeError,AttributeError,queue.Empty,SnapshotUnavailable):
            self.error='snapshot_runtime_unconfirmed'
            self.close()

    def _read(self):
        try:
            while True:
                line=self.process.stdout.readline(1_100_001)
                if not line:return
                if len(line)>1_100_000:raise ValueError('mirror frame exceeded limit')
                try:self.responses.put_nowait(json.loads(line))
                except queue.Full:return
        except (OSError,ValueError):pass

    def call(self,method,terminal_id,**fields):
        with self.lock:
            if not self.available:raise SnapshotUnavailable(self.error or 'snapshot_unavailable')
            ident=uuid.uuid4().hex
            request=json.dumps({'id':ident,'method':method,'terminal_id':terminal_id,**fields},ensure_ascii=False)+'\n'
            def send():
                try:self.process.stdin.write(request);self.process.stdin.flush()
                except (OSError,ValueError):
                    try:self.responses.put_nowait({'id':ident,'transport_error':True})
                    except queue.Full:pass
            threading.Thread(target=send,daemon=True).start()
            try:value=self.responses.get(timeout=3)
            except queue.Empty:
                self.available=False;self.error='snapshot_observation_timeout'
                raise SnapshotUnavailable(self.error) from None
            if value.get('id')!=ident or value.get('transport_error'):
                self.available=False;self.error='snapshot_transport_unconfirmed'
                raise SnapshotUnavailable(self.error)
            if not value.get('ok'):raise SnapshotUnavailable('snapshot_resource_unavailable')
            return value['value']

    def close(self):
        self.available=False
        if self.process:
            try:self.process.stdin.close()
            except (OSError,ValueError):pass
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Explicit shutdown of our observation-only child, never a PTY.
                self.process.terminate();self.process.wait(timeout=2)


def encode_checkpoint(frame):
    raw=json.dumps(frame,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(raw)>1024*1024:raise SnapshotUnavailable('checkpoint_plaintext_limit')
    encoded=base64.b64encode(zlib.compress(raw)).decode('ascii')
    if len(encoded)>196608:raise SnapshotUnavailable('checkpoint_transport_limit')
    return {'version':1,'encoding':'deflate-json-base64','data':encoded,
            'cursor':frame['cursor'],'sequence':frame['sequence']}
