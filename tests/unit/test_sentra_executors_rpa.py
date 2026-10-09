"""Deterministic primitives; injected verifier failures are explicitly unit tests."""
import os
import tempfile
import unittest
import sys
import subprocess
import json
from pathlib import Path

from sentra_executors.rpa import AuthorizedPaths, ExecutorFailure, atomic_output


class AtomicOutputContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='sentra-rpa-unit-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.paths = AuthorizedPaths((str(self.root),), (str(self.root),))

    def test_verifier_failure_preserves_destination(self):
        output = self.root / 'result.csv'
        output.write_bytes(b'original')
        def failed_verifier(_):
            raise ExecutorFailure('injected_unit_verification_failure')
        with self.assertRaisesRegex(ExecutorFailure, 'injected_unit_verification_failure'):
            atomic_output(self.paths, str(output), lambda p: p.write_bytes(b'new'),
                          failed_verifier, overwrite=True)
        self.assertEqual(output.read_bytes(), b'original')
        self.assertEqual([p for p in self.root.glob('.sentra-*') if p.is_file()], [])

    def test_competing_creator_is_not_overwritten(self):
        output = self.root / 'race.csv'
        def producer(temp):
            temp.write_bytes(b'candidate')
            output.write_bytes(b'other writer')
        with self.assertRaisesRegex(ExecutorFailure, 'output_exists'):
            atomic_output(self.paths, str(output), producer, lambda p: None)
        self.assertEqual(output.read_bytes(), b'other writer')
        self.assertEqual([p for p in self.root.glob('.sentra-*') if p.is_file()], [])

    def test_sibling_prefix_does_not_authorize_escape(self):
        output = str(self.root) + '-sibling/result.csv'
        with self.assertRaises(ValueError):
            self.paths.resolve(output, write=True)

    def test_read_only_roots_do_not_grant_output(self):
        paths = AuthorizedPaths((str(self.root),))
        with self.assertRaises(ValueError):
            paths.resolve(str(self.root / 'out.csv'), write=True)

    def test_unit_checkpoint_revocation_before_promotion_preserves_destination(self):
        # Explicit unit authority probe; this is not proof of central lease I/O.
        from sentra_runtime.effect_boundary import current_effect_context
        class CheckpointProbe:
            calls = 0
            def checkpoint(self):
                self.calls += 1
                if self.calls == 4:
                    raise PermissionError('unit revocation before publication')
        output = self.root / 'revoked.csv'
        output.write_bytes(b'original')
        probe = CheckpointProbe()
        token = current_effect_context.set(probe)
        try:
            with self.assertRaisesRegex(ExecutorFailure, 'effect_checkpoint_denied'):
                atomic_output(self.paths, str(output), lambda p: p.write_bytes(b'new'),
                              lambda p: None, overwrite=True)
        finally:
            current_effect_context.reset(token)
        self.assertEqual(probe.calls, 4)
        self.assertEqual(output.read_bytes(), b'original')

    def test_cross_process_same_output_has_one_no_overwrite_winner(self):
        # Two real OS processes share the output lock, without machine-ID scope.
        script=r'''
import json,sys,time,pathlib
from sentra_executors.rpa import AuthorizedPaths,atomic_output,ExecutorFailure
c=json.loads(sys.stdin.readline()); root=pathlib.Path(c['root'])
(root/('ready-'+c['value'])).write_text('ready')
deadline=time.monotonic()+10
while len(list(root.glob('ready-*')))<2:
    if time.monotonic()>deadline: raise TimeoutError('barrier')
    time.sleep(.01)
def produce(path):
    time.sleep(.2); path.write_text(c['value'])
try:
    artifact=atomic_output(AuthorizedPaths((str(root),),(str(root),)),str(root/'shared.csv'),produce,lambda p:None)
    print(json.dumps({'state':'written','locked':artifact['publication_locked']}))
except ExecutorFailure as exc: print(json.dumps({'state':exc.code}))
'''
        children=[]
        try:
            for value in ('A','B'):
                child=subprocess.Popen([sys.executable,'-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=0x08000000 if os.name=='nt' else 0)
                children.append(child)
                child.stdin.write(json.dumps({'root':str(self.root),'value':value})+'\n'); child.stdin.flush()
            results=[]
            for child in children:
                child.stdin.close(); child.stdin=None
                out,err=child.communicate(timeout=20)
                self.assertEqual(child.returncode,0,err); results.append(json.loads(out))
            self.assertEqual(sorted(r['state'] for r in results),['output_exists','written'])
            self.assertTrue(next(r for r in results if r['state']=='written')['locked'])
            self.assertIn((self.root/'shared.csv').read_text(),('A','B'))
        finally:
            for child in children:
                if child.poll() is None: child.kill(); child.wait()

    def test_unit_durable_capture_runs_under_output_lock_and_returns_identity(self):
        # Explicit capture contract probe; real registry durability is main's acceptance.
        from sentra_runtime.effect_boundary import current_effect_context
        from sentra_executors.rpa import digest
        class CaptureProbe:
            saved=None
            def checkpoint(self): pass
            def capture_output(self,path,*,expected_sha256,max_bytes):
                self.saved=Path(path).read_bytes()
                assert digest(Path(path))==expected_sha256 and len(self.saved)<=max_bytes
                return {'artifact_id':'unit-capture-probe','resource_uri':'sentra://artifact/unit-capture-probe'}
        probe=CaptureProbe(); token=current_effect_context.set(probe)
        output=self.root/'durable.csv'
        try:
            artifact=atomic_output(self.paths,str(output),lambda p:p.write_bytes(b'captured'),lambda p:None)
        finally:current_effect_context.reset(token)
        self.assertEqual(artifact['artifact_id'],'unit-capture-probe')
        self.assertTrue(artifact['durable_capture'])
        output.write_bytes(b'user later changed workspace copy')
        self.assertEqual(probe.saved,b'captured')

    def test_symlink_escape_if_platform_permits_creation(self):
        with tempfile.TemporaryDirectory(prefix='sentra-rpa-outside-') as outside:
            link = self.root / 'link'
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symlink creation unavailable; escape not runtime-tested on this host')
            with self.assertRaises(ValueError):
                self.paths.resolve(str(link / 'escape.csv'), write=True)


if __name__ == '__main__':
    unittest.main()
