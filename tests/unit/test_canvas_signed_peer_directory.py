"""Staged signed discovery acceptance; this is not actual Hamachi runtime proof."""
import json

from sentra_canvas.peer_directory import PeerNodeIdentity,SignedPeerDirectory


def test_identity_is_protected_stable_and_presence_is_scope_bound(tmp_path):
    from sentra_canvas.service import Canvas
    app=Canvas(tmp_path/'project',state_dir=tmp_path/'state'/'canvas',principal='owner')
    try:
        first=app.create_workspace('First')['id'];second=app.create_workspace('Second')['id']
        identity=PeerNodeIdentity(app.store,first)
        assert PeerNodeIdentity(app.store,first).node_id==identity.node_id
        other=PeerNodeIdentity(app.store,second)
        sender=SignedPeerDirectory(identity=identity,mesh_key='a'*43,label='First node',address='127.0.0.1',clock=lambda:1000)
        receiver=SignedPeerDirectory(identity=other,mesh_key='a'*43,label='Second node',address='127.0.0.2',target_addresses=('127.0.0.1',),clock=lambda:1000)
        packet=sender.announcement()
        peer=receiver.accept(packet,'127.0.0.1')
        assert peer['node_id']==identity.node_id and peer['authenticated_mesh_member'] is True
        assert peer['execution_authorized'] is False and peer['capabilities']==['presence']
        assert receiver.accept(packet,'127.0.0.1') is None
        assert receiver.accept(sender.announcement(),'127.0.0.3') is None
        wrong=SignedPeerDirectory(identity=other,mesh_key='b'*43,label='Wrong mesh',address='127.0.0.2',target_addresses=('127.0.0.1',),clock=lambda:1000)
        assert wrong.accept(sender.announcement(),'127.0.0.1') is None
        value=json.loads(sender.announcement());value['presence']['label']='Forged';
        assert receiver.accept(json.dumps(value).encode(),'127.0.0.1') is None
        later=SignedPeerDirectory(identity=other,mesh_key='a'*43,label='Expired',address='127.0.0.2',target_addresses=('127.0.0.1',),clock=lambda:2000)
        assert later.accept(sender.announcement(),'127.0.0.1') is None
        row=app.store.db.execute('SELECT private_key FROM canvas_peer_identity WHERE workspace=?',(first,)).fetchone()
        assert row[0].startswith(('dpapi:','keyring:'))
    finally:app.shutdown()
