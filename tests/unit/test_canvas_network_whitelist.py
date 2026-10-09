"""Staged VPN configuration acceptance without a live Hamachi/Radmin claim."""
import pytest

from test_sentra_runtime_canvas_center_http import running_canvas,request


def test_owner_can_save_empty_vpn_whitelist_and_retrieve_pairing_secret_privately(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace('VPN configuration')['id']
        code,value=request(server,'/api/center/network?ws='+ws)
        assert code==200 and value['configuration']['revision']==0 and value['presence']['peers']==[]
        body={'ws':ws,'configuration':{'enabled':False,'adapter_kind':'radmin','allowed_ips':[],
            'interface_address':'','port':37037,'expected_revision':0}}
        code,value=request(server,'/api/center/network',json_body=body)
        assert code==200 and value['configuration']['revision']==1
        assert value['configuration']['adapter_kind']=='radmin' and value['configuration']['allowed_ips']==[]
        assert 'mesh_key' not in value['configuration'] and value['pairing_key_configured'] is True
        assert value['presence']['running'] is False and value['collaboration_transport_ready'] is False
        code,pairing=request(server,'/api/center/network/pairing',json_body={'ws':ws})
        assert code==200 and len(pairing['mesh_key'])>=32
        row=app.store.db.execute('SELECT content FROM canvas_network_settings WHERE workspace=?',(ws,)).fetchone()
        assert pairing['mesh_key'] not in row[0]
        code,_=request(server,'/api/center/network',json_body=body)
        assert code==400


def test_agent_whitelist_config_cannot_extract_or_replace_pairing_material(tmp_path):
    from sentra_canvas.network_settings import WorkspaceNetworkSettings
    with running_canvas(tmp_path) as (app,server):
        ws=app.create_workspace('Agent whitelist')['id']
        settings=WorkspaceNetworkSettings(app.store)
        result=settings.configure(ws,{'enabled':False,'allowed_ips':['25.1.2.3','25.1.2.3'],
            'interface_address':'25.4.5.6','expected_revision':0},agent=True)
        assert result['configuration']['allowed_ips']==['25.1.2.3']
        assert 'mesh_key' not in result['configuration']
        with pytest.raises(ValueError):settings.configure(ws,{'mesh_key':'x'*43,'expected_revision':1},agent=True)
        with pytest.raises(ValueError):settings.configure(ws,{'allowed_ips':['host.example'],'expected_revision':1},agent=True)
        assert settings.status(ws)['configuration']['revision']==1
