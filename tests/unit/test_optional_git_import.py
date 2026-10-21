"""Core startup and ordinary workspace inspection must not require native Git."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def run_without_git(code):
    env = os.environ.copy()
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32') if os.name == 'nt' else '/nonexistent'
    env.pop('GIT_PYTHON_GIT_EXECUTABLE', None)
    env.pop('GIT_PYTHON_REFRESH', None)
    script = 'import sys; sys.path.insert(0, ' + repr(str(ROOT)) + ');\n' + code
    return subprocess.run([sys.executable, '-I', '-c', script], cwd=ROOT,
                          env=env, capture_output=True, text=True, timeout=30)


def test_core_imports_do_not_import_gitpython_without_git():
    result = run_without_git('''
import workspace
from sentra_mcp.main import parser
from sentra_remote.agent import main
assert 'git' not in sys.modules
assert 'SENTRA' in parser().format_help()
print('core-imports-ok')
''')
    assert result.returncode == 0, result.stderr
    assert 'core-imports-ok' in result.stdout


def test_plain_workspace_inspection_and_git_mutation_refusal_without_git(tmp_path):
    (tmp_path / 'readme.txt').write_text('owned fixture')
    result = run_without_git('''
import asyncio, json
from pathlib import Path
from workspace.git_manager import GitManager
root = Path(''' + repr(str(tmp_path)) + ''')
manager = GitManager(root)
assert manager.repo is None
assert 'readme.txt' in asyncio.run(manager.inspect_repository())
assert asyncio.run(manager.commit_result(paths=['readme.txt'])) is False
assert not (root / '.git').exists()
print(json.dumps({'inspection': True, 'git_mutation_refused': True}))
''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'inspection': True, 'git_mutation_refused': True}
