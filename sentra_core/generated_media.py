"""Binary provider results bound to protected calls, never inferred from links."""
from contextlib import closing
import base64
import hashlib
import io
import json
import re
import time

from .conversations import _encode, _decode

TRANSPORT = 'authenticated-browser-download-v1'
FIELDS = {'type', 'transport', 'request_id', 'conversation_id', 'message_id', 'filename',
          'mime_type', 'byte_length', 'sha256', 'data_base64'}
ID = re.compile(r'^[A-Za-z0-9_-]{8,160}$')
FORMATS = {'image/png': (8 * 1024**2, {'.png'}),
           'image/jpeg': (8 * 1024**2, {'.jpg', '.jpeg'}),
           'application/pdf': (20 * 1024**2, {'.pdf'})}


def validate_asset(payload, request_id):
    if (not isinstance(payload, dict) or set(payload) != FIELDS
            or payload.get('type') != 'sentra.generated_asset' or payload.get('transport') != TRANSPORT
            or payload.get('request_id') != request_id):
        raise ValueError('generated media has no matching authenticated turn')
    for key in ('conversation_id', 'message_id'):
        if not isinstance(payload[key], str) or not ID.fullmatch(payload[key]):
            raise ValueError('generated media requires exact remote message identity')
    mime = payload['mime_type']
    if not isinstance(mime, str) or mime not in FORMATS:
        raise ValueError('unsupported generated media format')
    size, suffixes = FORMATS[mime]
    count = payload['byte_length']
    name = payload['filename']
    if (not isinstance(name, str) or not 1 <= len(name) <= 160 or any(ord(c) < 32 for c in name)
            or '/' in name or '\\' in name or ':' in name or name.startswith('.')
            or not any(name.lower().endswith(suffix) for suffix in suffixes)):
        raise ValueError('generated media filename must match its verified format')
    if type(count) is not int or not 1 <= count <= size:
        raise ValueError('generated media exceeds byte limit')
    encoded = payload['data_base64']
    if not isinstance(encoded, str) or len(encoded) > ((size + 2) // 3) * 4:
        raise ValueError('generated media exceeds encoded byte limit')
    raw = base64.b64decode(encoded, validate=True)
    if (len(raw) != count or base64.b64encode(raw).decode() != encoded
            or hashlib.sha256(raw).hexdigest() != payload['sha256']):
        raise ValueError('generated media integrity mismatch')
    if mime.startswith('image/'):
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != ('PNG' if mime == 'image/png' else 'JPEG') or image.width * image.height > 32_000_000:
                raise ValueError('generated image format or pixel limit mismatch')
            image.verify()
    elif not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-4096:]:
        raise ValueError('generated PDF format mismatch')
    return {key: value for key, value in payload.items() if key not in {'data_base64', 'type'}}, raw


class GeneratedMediaStore:
    def __init__(self, conversations):
        self.conversations = conversations
        with conversations._tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS generated_provider_media('
                'asset_id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,call_id TEXT NOT NULL REFERENCES calls(id),'
                'bytes_count INTEGER NOT NULL,protected_metadata TEXT NOT NULL,protected_bytes TEXT NOT NULL,'
                'created REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS generated_provider_media_chunks('
                'asset_id TEXT NOT NULL REFERENCES generated_provider_media(asset_id),part INTEGER NOT NULL,'
                'sha256 TEXT NOT NULL,protected_bytes TEXT NOT NULL,PRIMARY KEY(asset_id,part))')

    def stage(self, conversation_id, turn_id, provider, request_id, payload):
        metadata, raw = validate_asset(payload, request_id)
        with self.conversations._tx() as db:
            self.conversations._owned(db, conversation_id)
            call = db.execute("SELECT id,state FROM calls WHERE conversation_id=? AND turn_id=? "
                "AND kind='provider' AND operation=? AND provider_id=?", (conversation_id, turn_id, provider, request_id)).fetchone()
            if call is None or call['state'] != 'started':
                raise PermissionError('generated media requires its original active provider call')
            ident = 'media-' + hashlib.sha256((call['id'] + '\x00' + metadata['message_id'] + '\x00' + metadata['sha256']).encode()).hexdigest()[:40]
            existing = db.execute('SELECT protected_metadata FROM generated_provider_media WHERE asset_id=?', (ident,)).fetchone()
            if existing:
                if _decode(existing['protected_metadata']) != metadata:
                    raise ValueError('generated media identity conflict')
                return ident
            rows = db.execute('SELECT COUNT(*) count,COALESCE(SUM(bytes_count),0) total FROM generated_provider_media WHERE conversation_id=?', (conversation_id,)).fetchone()
            per_call = db.execute('SELECT COUNT(*) FROM generated_provider_media WHERE call_id=?', (call['id'],)).fetchone()[0]
            if per_call >= 8 or rows['total'] + len(raw) > 128 * 1024**2:
                raise ValueError('generated media quota exceeded')
            db.execute('INSERT INTO generated_provider_media VALUES(?,?,?,?,?,?,?)',
                (ident, conversation_id, call['id'], len(raw), _encode(metadata),
                 _encode(None), time.time()))
            for part, offset in enumerate(range(0, len(raw), 65536)):
                chunk = raw[offset:offset + 65536]
                db.execute('INSERT INTO generated_provider_media_chunks VALUES(?,?,?,?)',
                    (ident, part, hashlib.sha256(chunk).hexdigest(), _encode(base64.b64encode(chunk).decode())))
        return ident

    def for_operation(self, conversation_id, operation_id, *, owner, work_item_id, agent_id, run_id):
        with self.conversations._connect() as db:
            self.conversations._owned(db, conversation_id)
            rows = db.execute('SELECT a.asset_id,a.protected_metadata,p.context_json FROM generated_provider_media a '
                "JOIN calls c ON c.id=a.call_id JOIN provider_context p ON p.call_id=c.id WHERE a.conversation_id=? "
                "AND c.state='completed' AND json_extract(p.context_json,'$.operation_id')=? ORDER BY a.created",
                (conversation_id, operation_id)).fetchall()
        result = []
        for row in rows:
            context = json.loads(row['context_json'])
            if all(context.get(key) == value for key, value in {'owner':owner, 'work_item_id':work_item_id,
                    'agent_id':agent_id, 'run_id':run_id, 'operation_id':operation_id}.items()):
                meta = _decode(row['protected_metadata'])
                result.append({'asset_id': row['asset_id'], **{key: meta[key] for key in
                    ('filename', 'mime_type', 'byte_length', 'sha256', 'conversation_id', 'message_id')}})
        return result

    def read(self, conversation_id, asset_id):
        with self.conversations._connect() as db:
            self.conversations._owned(db, conversation_id)
            row = db.execute('SELECT a.* FROM generated_provider_media a JOIN calls c ON c.id=a.call_id '
                "WHERE a.conversation_id=? AND a.asset_id=? AND c.state='completed'", (conversation_id, asset_id)).fetchone()
            if row is None:
                raise PermissionError('generated media is unavailable or unconfirmed')
            parts = db.execute('SELECT * FROM generated_provider_media_chunks WHERE asset_id=? ORDER BY part', (asset_id,)).fetchall()
            if [part['part'] for part in parts] != list(range(len(parts))):
                raise ValueError('stored generated media chunk is missing')
            content = []
            for part in parts:
                chunk = base64.b64decode(_decode(part['protected_bytes']), validate=True)
                if len(chunk) > 65536 or hashlib.sha256(chunk).hexdigest() != part['sha256']:
                    raise ValueError('stored generated media chunk integrity mismatch')
                content.append(chunk)
        meta = _decode(row['protected_metadata'])
        raw = b''.join(content)
        if len(raw) != meta['byte_length'] or hashlib.sha256(raw).hexdigest() != meta['sha256']:
            raise ValueError('stored generated media integrity mismatch')
        return meta, raw
