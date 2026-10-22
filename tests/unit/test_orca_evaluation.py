import json
import pytest
from sentra_canvas.evaluation import prepare_state,seed,prepare_assets
from sentra_canvas import evaluation
from sentra_canvas.service import Canvas


def test_evaluation_refuses_an_existing_unmarked_installation(tmp_path):
    (tmp_path/'canvas.sqlite3').write_bytes(b'existing installed state')
    with pytest.raises(ValueError,match='separate empty'):prepare_state(tmp_path)
    assert (tmp_path/'canvas.sqlite3').read_bytes()==b'existing installed state'
    assert not (tmp_path/'sentra-evaluation.json').exists()


def test_evaluation_marker_is_validated_before_reuse(tmp_path):
    state=prepare_state(tmp_path/'evaluation')
    assert prepare_state(state)==state
    (state/'sentra-evaluation.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='Unknown evaluation'):prepare_state(state)


def test_evaluation_has_own_resources_and_asset_entry(tmp_path,monkeypatch):
    # This unit test covers isolated copying/navigation, not renderer compilation.
    # Native workspace acceptance exercises the real generated renderer separately.
    source=tmp_path/'fixture-source'
    static=source/'sentra_canvas/static/desktop-assets';static.mkdir(parents=True)
    (static/'bootstrap.js').write_text('// isolated bootstrap fixture',encoding='utf-8')
    build=source/'sentra_canvas/desktop_ui/.tmp/orca-workspace-build';build.mkdir(parents=True)
    (build/'desktop.js').write_text('// compiled renderer fixture',encoding='utf-8')
    (build/'index.html').write_text('<html><head><title>SENTRA Desktop</title></head><body></body></html>',encoding='utf-8')
    monkeypatch.setattr(evaluation,'ROOT',source)
    state=prepare_state(tmp_path/'evaluation')
    app=Canvas(state/'workspace',state_dir=state)
    try:
        scope=seed(app);assert seed(app)==scope
        assert len(app.store.workspaces())==1
        value=app.shell_bridge({'action':'workspace_inventory',**scope})['value']
        assert value['dot_id']==scope['dot_id']
        target=prepare_assets(state,scope)
        assert target.is_relative_to(state)
        html=(target/'desktop.html').read_text(encoding='utf-8')
        assert 'Avaliação ORCA' in html and 'evaluation-bootstrap.js' in html
        script=(target/'desktop-assets/evaluation-bootstrap.js').read_text(encoding='utf-8')
        assert 'sentra-orca-workspace-enabled' in script and scope['dot_id'] in script
        assert (target/'desktop-assets/desktop.js').read_bytes()==(build/'desktop.js').read_bytes()
        assert (target/'desktop-assets/bootstrap.js').read_bytes()==(static/'bootstrap.js').read_bytes()
        assert not (target/'broker.json').exists()
    finally:app.shutdown()


def test_evaluation_refuses_missing_compiled_renderer(tmp_path,monkeypatch):
    monkeypatch.setattr(evaluation,'ROOT',tmp_path/'missing-source')
    state=prepare_state(tmp_path/'evaluation')
    with pytest.raises(RuntimeError,match='Run build:orca-validation first'):
        prepare_assets(state,{'dot_id':'fixture'})
    assert not (state/'evaluation-ui').exists()
