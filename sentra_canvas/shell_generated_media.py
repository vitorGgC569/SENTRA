"""Publish only confirmed protected provider binaries in their original chat."""
from contextlib import closing

from sentra_core.conversations import _encode, _decode
from sentra_core.generated_media import GeneratedMediaStore
from .store import Denied


class ShellGeneratedMedia:
    def __init__(self, runtime):
        self.runtime, self.control, self.owner = runtime, runtime.control, runtime.owner
        self.provider = GeneratedMediaStore(runtime.conversations)
        with closing(self.control.store.connect('shell')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS canvas_shell_generated_media('
                'owner TEXT NOT NULL,project_id TEXT NOT NULL,conversation_id TEXT NOT NULL,'
                'message_id TEXT NOT NULL,asset_id TEXT NOT NULL,operation_id TEXT NOT NULL,'
                'protected_manifest TEXT NOT NULL,PRIMARY KEY(owner,project_id,message_id,asset_id))')

    def publish(self, message, dot, assistant_id):
        refs = self.provider.for_operation(message['conversation_id'], message['operation_id'],
            owner=self.owner, work_item_id=message['work_item_id'], agent_id=dot['agent_id'], run_id=message['run_id'])
        manifests = [{key: ref[key] for key in ('asset_id', 'filename', 'mime_type', 'byte_length', 'sha256')} for ref in refs]
        # Web relay binaries are not CLI provider calls. Link them only when
        # the exact original websend_ operation has an authenticated final.
        with closing(self.control.store.connect('shell')) as db:
            web_turn = db.execute('SELECT job_id FROM canvas_shell_web_turns WHERE owner=? AND operation_id=?',
                (self.owner,message['operation_id'])).fetchone()
        if web_turn and web_turn['job_id']:
            with closing(self.control.store.connect('session_checkpoint')) as db:
                rows = db.execute('SELECT i.*,r.conversation_id AS remote_conversation_id '
                    'FROM web_send_intents i JOIN authenticated_web_receipts r ON r.job_id=i.job_id '
                    "WHERE i.job_id=? AND i.stage='ANSWERED'", (web_turn['job_id'],)).fetchall()
            if len(rows) == 1:
                bound = rows[0]
                if (bound['owner'],bound['run_id'],bound['work_item_id'],bound['operation_id'],
                    bound['principal_id']) == (self.owner,message['run_id'],message['work_item_id'],
                                                message['operation_id'],dot['agent_id']):
                    from native_bridge.web_generated_assets import WebGeneratedAssets
                    native = WebGeneratedAssets(self.control)
                    decision = native.verdict(
                        owner=self.owner, run_id=message['run_id'],
                        work_item_id=message['work_item_id'], operation_id=message['operation_id'],
                        job_id=web_turn['job_id'], conversation_id=bound['remote_conversation_id'],
                        message_id=bound['answer_message_id'])
                    if decision.get('generated_asset_verified') is True and decision.get('success') is True:
                        manifests.extend(native.for_job(
                            owner=self.owner, run_id=message['run_id'],
                            work_item_id=message['work_item_id'], operation_id=message['operation_id'],
                            job_id=web_turn['job_id'], conversation_id=bound['remote_conversation_id'],
                            message_id=bound['answer_message_id']))
        with closing(self.control.store.connect('shell')) as db, db:
            for manifest in manifests:
                db.execute('INSERT OR IGNORE INTO canvas_shell_generated_media VALUES(?,?,?,?,?,?,?)',
                    (self.owner, message['project_id'], message['conversation_id'], assistant_id,
                     manifest['asset_id'], message['operation_id'], _encode(manifest)))
        return manifests

    def messages(self, project_id, conversation_id, items):
        with closing(self.control.store.connect('shell')) as db:
            rows = db.execute('SELECT message_id,protected_manifest FROM canvas_shell_generated_media '
                'WHERE owner=? AND project_id=? AND conversation_id=?', (self.owner,project_id,conversation_id)).fetchall()
        decoded = [(row['message_id'], _decode(row['protected_manifest'])) for row in rows]
        hidden = set()
        native_ids = [manifest.get('asset_id') for _message_id, manifest in decoded
                      if isinstance(manifest, dict) and str(manifest.get('asset_id', '')).startswith('web-native-')]
        if native_ids:
            try:
                from native_bridge.web_generated_assets import WebGeneratedAssets
                hidden = WebGeneratedAssets(self.control).fenced_asset_ids(self.owner, native_ids)
            except Exception:
                hidden = set(native_ids)
        by_message = {}
        for message_id, manifest in decoded:
            if isinstance(manifest, dict) and manifest.get('asset_id') in hidden:
                continue
            by_message.setdefault(message_id, []).append(manifest)
        return [{**item, 'generated_assets': by_message[item['message_id']]} if item['message_id'] in by_message else item for item in items]

    def read(self, project_id, space_id, conversation_id, message_id, asset_id):
        with closing(self.control.store.connect('shell')) as db:
            self.control.shell._entity(db, self.owner, project_id, 'conversation', conversation_id, space_id=space_id)
            row = db.execute('SELECT a.operation_id,a.protected_manifest,m.receipt_id FROM canvas_shell_generated_media a '
                'JOIN shell_messages m ON m.message_id=a.message_id AND m.owner=a.owner AND m.project_id=a.project_id '
                "AND m.conversation_id=a.conversation_id AND m.operation_id=a.operation_id AND m.role='assistant' "
                'WHERE a.owner=? AND a.project_id=? AND a.conversation_id=? AND a.message_id=? AND a.asset_id=?',
                (self.owner,project_id,conversation_id,message_id,asset_id)).fetchone()
        if row is None or not row['receipt_id']:
            raise Denied('generated file is outside this confirmed message')
        op = self.control.durable.operation_status(row['operation_id'], self.owner)
        if op['state'] != 'SUCCEEDED' or (op.get('result') or {}).get('receipt_id') != row['receipt_id']:
            raise Denied('generated file delivery is unconfirmed')
        manifest = _decode(row['protected_manifest'])
        if asset_id.startswith('web-native-'):
            from native_bridge.web_generated_assets import WebGeneratedAssets
            metadata, data = WebGeneratedAssets(self.control).read(
                owner=self.owner,operation_id=row['operation_id'],asset_id=asset_id)
        else:
            metadata, data = self.provider.read(conversation_id, asset_id)
        if any(manifest.get(key) != metadata.get(key) for key in ('filename','mime_type','byte_length','sha256')):
            raise Denied('generated file manifest changed')
        return manifest, data
