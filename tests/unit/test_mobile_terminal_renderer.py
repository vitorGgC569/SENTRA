import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not os.environ.get('SENTRA_ELECTRON_TEST_BINARY'),reason='explicit isolated Electron renderer binary required')
def test_offline_mobile_terminal_document_restores_state_without_network_or_input(tmp_path):
    app=ROOT/'integrations/orca-mobile/app'
    binary=Path(os.environ['SENTRA_ELECTRON_TEST_BINARY']).resolve(strict=True)
    (tmp_path/'profile').mkdir()
    source=(app/'terminal/document.ts').read_text(encoding='utf-8')
    html=json.loads(source.split('export const TERMINAL_DOCUMENT=',1)[1].strip().removesuffix(';'))
    (tmp_path/'terminal.html').write_text(html.replace('__SENTRA_VIEW_ID__','qa-terminal'),encoding='utf-8')
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    subprocess.run([shutil.which('node'),str(app/'test/terminal-fixture.mjs'),str(tmp_path/'fixture.json')],
        check=True,capture_output=True,text=True,timeout=15,creationflags=flags)
    result=subprocess.run([str(binary),str(app/'test/terminal-renderer.cjs'),'--terminal-test='+str(tmp_path)],
        capture_output=True,text=True,timeout=35,creationflags=flags)
    assert result.returncode==0,result.stderr[-4000:]
    assert json.loads((tmp_path/'result.json').read_text())['passed']
