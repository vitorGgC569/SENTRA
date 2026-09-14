"""Prepare the trusted tool image and exercise the real isolation boundary.

Build downloads dependencies. Smoke/test containers always run without network.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workspace.docker_runner import DEFAULT_IMAGE, DockerClient, DockerCommandRunner

SMOKE = """
import os, pathlib, socket, json
assert os.getuid() == 65532
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not pathlib.Path('/workspace/.env').exists()
assert not pathlib.Path('/workspace/.docker').exists()
assert not any(k for k in os.environ if any(s in k.upper() for s in ('SECRET','TOKEN','API_KEY')))
assert pathlib.Path('/workspace/probe.txt').read_text() == 'source stays unchanged'
for path in ('/workspace/probe.txt', '/etc/oma-write-probe'):
    try:
        pathlib.Path(path).write_text('forbidden')
    except OSError:
        pass
    else:
        raise AssertionError('filesystem writable: '+path)
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1).close()
except OSError:
    pass
else:
    raise AssertionError('network egress available')
status = pathlib.Path('/proc/self/status').read_text()
assert 'CapEff:\\t0000000000000000' in status
assert 'NoNewPrivs:\\t1' in status
assert 'Seccomp:\\t2' in status
print(json.dumps({'nonroot': True, 'readonly': True, 'network_blocked': True,
                  'secrets_absent': True, 'capabilities_dropped': True, 'seccomp': True}))
"""


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true', help='Download/build trusted dependencies explicitly')
    parser.add_argument('--smoke', action='store_true', help='Run real isolation assertions')
    args = parser.parse_args(argv)
    client = DockerClient()
    if args.build:
        print('Building trusted tools only (network enabled for dependency installation)...', flush=True)
        build = await client.call(['build', '--tag', DEFAULT_IMAGE, str(ROOT/'sandbox_runtime')], 900)
        print(build['stdout'] + build['stderr'], flush=True)
        if not build['passed']:
            return 2
    image = await client.prepare(DEFAULT_IMAGE)
    print(json.dumps({'image_id': image, 'backend': 'docker'}), flush=True)
    if args.smoke:
        with tempfile.TemporaryDirectory(prefix='oma-docker-smoke-') as folder:
            root = Path(folder)
            (root/'probe.txt').write_text('source stays unchanged')
            (root/'.env').write_text('FAKE_TEST_SECRET=not-a-real-secret')
            (root/'.docker').mkdir()
            (root/'.docker'/'config.json').write_text('{}')
            result = await DockerCommandRunner(root, {'probe': ['python', '-c', SMOKE]}, image=image).run_command('[[TEST|probe]]', 30)
            print(json.dumps(result, indent=2), flush=True)
            assert (root/'probe.txt').read_text() == 'source stays unchanged'
            return 0 if result['passed'] else 1
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        raise SystemExit(asyncio.run(main()))
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
