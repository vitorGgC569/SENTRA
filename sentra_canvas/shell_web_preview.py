"""Scoped observations of an original Web send, never a delivery receipt.

The queue selects the owner, WorkItem and actor. Browser message identity comes
from the original send receipt; no renderer argument may select these fields.
"""
from contextlib import closing
import json

from sentra_core.conversations import _decode
from sentra_core.model_prose import prose_prefix


def web_preview(runtime, project_id, conversation_id, *, include_full=False):
    control, owner = runtime.control, runtime.owner
    with closing(control.store.connect('shell')) as db:
        row = db.execute('SELECT * FROM canvas_shell_queue WHERE owner=? AND project_id=? '
            'AND conversation_id=? AND state IN (\'queued\',\'running\') ORDER BY created_at DESC LIMIT 1',
            (owner, project_id, conversation_id)).fetchone()
    if row is None:
        return {'status': 'idle'}
    original = _decode(row['protected_input'])
    message, dot = original['message'], original['dot']
    operation = control.durable.operation_status(row['operation_id'], owner)
    if operation['state'] not in {'STARTING', 'RUNNING', 'WAITING_EXTERNAL', 'UNCERTAIN'}:
        return {'status': 'idle'}
    provider_ids = []
    with runtime.conversations._connect() as journal:
        owned = journal.execute('SELECT owner FROM conversations WHERE id=?', (conversation_id,)).fetchone()
        if owned is not None:
            runtime.conversations._owned(journal, conversation_id)
            for call in journal.execute('SELECT c.provider_id,p.context_json FROM calls c '
                    'JOIN provider_context p ON p.call_id=c.id WHERE c.conversation_id=? '
                    "AND c.kind='provider' AND json_extract(p.context_json,'$.operation_id')=?",
                    (conversation_id, message['operation_id'])):
                context = json.loads(call['context_json'])
                if all(context.get(k) == v for k, v in {
                    'owner': owner, 'run_id': message['run_id'], 'work_item_id': message['work_item_id'],
                    'agent_id': dot['agent_id'], 'operation_id': message['operation_id']}.items()):
                    provider_ids.append(call['provider_id'])
    with closing(control.store.connect('session_checkpoint')) as db:
        # Both native Responses and binary relay sends use this same ledger.
        # Native tool rounds have separate provider Operations. Bind them by
        # the protected call context and gateway turn identity, never timing.
        if not db.execute('PRAGMA table_info(web_send_intents)').fetchall() or not db.execute('PRAGMA table_info(authenticated_web_receipts)').fetchall():
            return {'status': 'idle'}
        operation_ids = [message['operation_id']]
        if provider_ids and db.execute('PRAGMA table_info(gateway_bound_web_turns)').fetchall():
            for provider_id in provider_ids:
                operation_ids.extend(r['operation_id'] for r in db.execute(
                    'SELECT operation_id FROM gateway_bound_web_turns WHERE owner=? AND run_id=? '
                    'AND work_item_id=? AND principal_id=? AND turn_id=? AND conversation_uri=?',
                    (owner, message['run_id'], message['work_item_id'], dot['agent_id'], provider_id,
                     'conversation://sentra-cli/' + conversation_id)))
        placeholders = ','.join('?' for _ in operation_ids)
        send = db.execute('SELECT i.*,r.browser_principal,r.conversation_id AS remote_id,'
            'r.message_id AS parent_message_id,r.identity_epoch '
            'FROM web_send_intents i JOIN authenticated_web_receipts r ON r.job_id=i.job_id '
            'AND r.owner=i.owner AND r.run_id=i.run_id '
            'WHERE i.owner=? AND i.run_id=? AND i.work_item_id=? AND i.principal_id=? '
            'AND i.operation_id IN (' + placeholders + ') '
            'AND i.send_fence>0 AND r.worker=i.worker ORDER BY i.created DESC LIMIT 1',
            (owner, message['run_id'], message['work_item_id'], dot['agent_id'], *operation_ids)).fetchone()
    if send is None:
        return {'status': 'idle'}
    result = {'status': 'generating', 'operation_id': message['operation_id'],
        'partial': True, 'authoritative': False, 'activity': 'Aguardando ChatGPT', 'content': '',
        'web_job_id': send['job_id']}
    mid, revision = send['answer_message_id'], send['answer_revision']
    if not mid or mid == send['parent_message_id'] or revision is None:
        return result
    # Prefer host-proved partial history. The StreamingLedger additionally
    # holds raw observed snapshots, but unproved text never becomes a final.
    with closing(control.store.connect('provider_content')) as db:
        if not db.execute('PRAGMA table_info(web_history_messages)').fetchall():
            return result
        frame = db.execute('SELECT * FROM web_history_messages WHERE owner=? AND workspace=? '
            'AND conversation_id=? AND message_id=? AND revision=? AND role=\'assistant\'',
            (owner, send['workspace'], send['remote_id'], mid, revision)).fetchone()
    if frame is None:
        return result
    from sentra_mcp.services.web_history_store import _plain
    body = _plain(frame['protected_body'])
    if not isinstance(body, str):
        return result
    import hashlib
    if hashlib.sha256(body.encode()).hexdigest() != frame['body_sha256']:
        return result
    with closing(control.store.connect('chat_access')) as db:
        if db.execute('PRAGMA table_info(browser_stream_content)').fetchall():
            snapshot = db.execute('SELECT protected_text,sha256 FROM browser_stream_content '
                'WHERE principal=? AND conversation_id=? AND message_id=? AND revision=?',
                (send['browser_principal'], send['remote_id'], mid, revision)).fetchone()
            if snapshot is not None and snapshot['sha256'] == frame['body_sha256']:
                observed_body = _decode(snapshot['protected_text'])
                if isinstance(observed_body, str) and hashlib.sha256(observed_body.encode()).hexdigest() == snapshot['sha256']:
                    body = observed_body
    # Tool intent bytes are retained for the authoritative CLI dispatcher,
    # never executed or presented as partial prose by this endpoint.
    body = prose_prefix(body)
    from .shell_stream import content_window
    content = body if include_full else content_window(body)
    return {**result, 'content': content, 'truncated': content != body,
        'message_id': mid, 'revision': revision,
        'status': 'confirming' if frame['state'] == 'complete' else 'generating',
        'activity': 'Confirmando entrega' if frame['state'] == 'complete' else 'Recebendo resposta',
        'observed_at': frame['observed_at']}
