"""Typed Daytona AT-SPI desktop actions using the pinned official SDK.

Selectors are host configured. A fresh exact lookup must match the observation
before input; callers cannot pass arbitrary remote accessibility node IDs.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import uuid
from urllib.parse import urlsplit

from .rpa import ExecutorFailure, atomic_output, effect_checkpoint

COMPUTER_ACTIONS = frozenset({'computer.start', 'computer.stop', 'computer.status',
    'computer.observe', 'computer.focus', 'computer.invoke', 'computer.set_value',
    'computer.screenshot', 'preview.fetch'})


@dataclass(frozen=True)
class ComputerSelector:
    key: str
    role: str
    name: str
    actions: tuple[str, ...] = ('read',)

    def __post_init__(self):
        if (not self.key or not self.role or not self.name or len(self.name) > 512 or
                not set(self.actions) <= {'read', 'focus', 'invoke', 'set_value'}):
            raise ValueError('exact_daytona_computer_selector_required')


def _node(sandbox, binding, selector):
    effect_checkpoint()
    result = sandbox.computer_use.accessibility.find_nodes(scope='pid', pid=binding.computer_pid,
        role=selector.role, name=selector.name, name_match='exact', limit=2)
    matches = result.matches or []
    if result.truncated or len(matches) != 1:
        raise ExecutorFailure('daytona_accessibility_selector_missing_or_ambiguous')
    node = matches[0]
    if not node.id or node.role != selector.role or node.name != selector.name:
        raise ExecutorFailure('daytona_accessibility_identity_mismatch')
    return node


def perform_computer(backend, sandbox, row, binding, arguments):
    action = arguments['action']; computer = sandbox.computer_use
    if row['metadata']['resource_kind'] != 'sandbox':
        raise ExecutorFailure('computer_use_requires_parent_sandbox')
    if action in {'computer.start', 'computer.stop'}:
        if not row['metadata'].get('managed'):
            raise ExecutorFailure('cannot_manage_computer_use_of_borrowed_sandbox')
        effect_checkpoint()
        value = computer.start() if action == 'computer.start' else computer.stop()
        backend.journal.update(row, metadata=dict(row['metadata'], computer_references={}))
        return {'session_id': row['id'], 'requested_action': action,
                'provider_status': value.to_dict(), 'attested_isolation': False}
    if action == 'computer.status':
        effect_checkpoint()
        return {'session_id': row['id'], 'provider_status': computer.get_status().to_dict()}
    if action == 'preview.fetch':
        return _preview(sandbox, binding, arguments)
    if action == 'computer.screenshot':
        effect_checkpoint(); value = computer.screenshot.take_full_screen(show_cursor=False)
        encoded = value.screenshot
        if not isinstance(encoded, str) or len(encoded) > 24 * 1024 * 1024:
            raise ExecutorFailure('daytona_screenshot_byte_limit')
        if encoded.startswith('data:image/png;base64,'):
            encoded = encoded.split(',', 1)[1]
        payload = base64.b64decode(encoded, validate=True)
        if len(payload) > 16 * 1024 * 1024 or not payload.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ExecutorFailure('daytona_screenshot_not_bounded_png')
        artifact = atomic_output(binding.paths, arguments['output'], lambda p: p.write_bytes(payload),
            lambda p: _verify_bytes(p, payload), max_output_bytes=16 * 1024 * 1024)
        return {'artifact': artifact, 'session_id': row['id'], 'scope': 'isolated_sandbox_desktop',
                'coordinate_input_used': False}
    if not binding.computer_pid or not binding.computer_selectors:
        raise ExecutorFailure('daytona_computer_process_and_selectors_not_configured')
    if action == 'computer.observe':
        references = {}; elements = []; revision = uuid.uuid4().hex
        for selector in binding.computer_selectors:
            node = _node(sandbox, binding, selector)
            token = revision + ':' + selector.key
            references[token] = {'selector_key': selector.key, 'node_id': node.id,
                                 'role': node.role, 'name': node.name}
            elements.append({'reference': token, 'selector_key': selector.key, 'role': node.role,
                'name': node.name, 'states': node.states, 'actions': list(selector.actions),
                'bounds': node.bounds.to_dict() if node.bounds else None})
        effect_checkpoint()
        backend.journal.update(row, metadata=dict(row['metadata'], computer_references=references))
        return {'session_id': row['id'], 'revision': revision, 'pid': binding.computer_pid,
                'elements': elements, 'observation_mode': 'at_spi', 'attested_isolation': False}
    reference = row['metadata'].get('computer_references', {}).get(arguments['reference'])
    if reference is None:
        raise ExecutorFailure('daytona_computer_reference_stale_or_unowned')
    selector = next(s for s in binding.computer_selectors if s.key == reference['selector_key'])
    operation = action.removeprefix('computer.')
    if operation not in selector.actions:
        raise ExecutorFailure('daytona_computer_selector_action_denied')
    node = _node(sandbox, binding, selector)
    if (node.id != reference['node_id'] or node.name != reference['name'] or node.role != reference['role']):
        raise ExecutorFailure('daytona_computer_element_recreated')
    effect_checkpoint()
    # Invalidate before dispatch, even when the response is lost.
    backend.journal.update(row, metadata=dict(row['metadata'], computer_references={}))
    try:
        if operation == 'focus':
            computer.accessibility.focus_node(node.id)
        elif operation == 'invoke':
            invoke_action = arguments['invoke_action']
            if invoke_action not in (node.actions or []):
                raise ExecutorFailure('daytona_computer_pattern_not_available')
            computer.accessibility.invoke_node(node.id, action=invoke_action)
        elif operation == 'set_value':
            computer.accessibility.set_node_value(node.id, arguments['value'])
    except ExecutorFailure:
        raise
    except Exception as exc:
        raise ExecutorFailure('daytona_computer_input_requires_reconciliation', uncertain=True) from exc
    effect_checkpoint()
    return {'session_id': row['id'], 'action': action, 'requires_new_observation': True,
            'effect_semantically_verified': False, 'coordinate_input_used': False}


def _verify_bytes(path, expected):
    if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(expected).digest():
        raise ExecutorFailure('daytona_artifact_bytes_changed')


def _preview(sandbox, binding, arguments):
    """Fetch a private preview on the host. Credential never reaches the renderer."""
    import httpx
    from .playwright_browser import origin
    effect_checkpoint()
    preview = sandbox.get_preview_link(arguments['port'])
    if preview.sandbox_id != sandbox.id or origin(preview.url) not in binding.preview_origins:
        raise ExecutorFailure('daytona_preview_origin_or_sandbox_mismatch')
    parsed = urlsplit(preview.url)
    if parsed.scheme != 'https' or parsed.query or parsed.fragment:
        raise ExecutorFailure('daytona_private_https_preview_required')
    # The official preview-token header authenticates the gateway. Redirects are
    # forbidden so the token cannot be forwarded to another origin.
    effect_checkpoint(); payload = bytearray()
    with httpx.Client(timeout=binding.connection.request_timeout_seconds,
                      follow_redirects=False, trust_env=False) as client:
        with client.stream('GET', preview.url.rstrip('/') + arguments.get('path', '/'),
                           headers={'x-daytona-preview-token': preview.token}) as response:
            if response.status_code != 200:
                raise ExecutorFailure('daytona_preview_http_error', evidence={'status': response.status_code})
            for block in response.iter_bytes():
                effect_checkpoint(); payload.extend(block)
                if len(payload) > binding.max_preview_bytes:
                    raise ExecutorFailure('daytona_preview_response_byte_limit')
            content_type = response.headers.get('content-type', 'application/octet-stream')[:256]
    data = bytes(payload)
    artifact = atomic_output(binding.paths, arguments['output'], lambda p: p.write_bytes(data),
        lambda p: _verify_bytes(p, data), max_output_bytes=binding.max_preview_bytes)
    return {'artifact': artifact, 'port': arguments['port'], 'content_type': content_type,
            'preview_credentials_exposed': False}
