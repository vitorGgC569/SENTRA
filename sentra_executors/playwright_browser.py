"""Real, opt-in Playwright executor. Does not change the read-only lab adapter.

The sync Playwright API is confined to one actor thread (GuardedExecutor's
to_thread pool does not preserve thread affinity). No persistent profile or
remote CDP attachment: internal CDP belongs solely to the launched browser.
Browser routing is an application control, not OS network containment.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import time
import uuid
import base64
import threading
from contextvars import copy_context
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .rpa import (AuthorizedPaths, DiagnosedExecutor, ExecutorFailure,
                  atomic_output, dependency, dependency_versions, effect_checkpoint, OwnedProcessHandle)

BROWSER_ACTIONS = frozenset({'open', 'close', 'navigate', 'observe', 'click',
                            'fill', 'read', 'screenshot', 'evidence', 'network',
                            'diagnostics', 'capture.start', 'capture.stop'})
RESOURCE_TYPES = frozenset({'document', 'stylesheet', 'image', 'media', 'font',
                           'script', 'xhr', 'fetch', 'texttrack', 'eventsource', 'other'})


def origin(url: str) -> str:
    if type(url) is not str or len(url) > 8192 or any(c.isspace() for c in url):
        raise ValueError('invalid_browser_url')
    p = urlsplit(url)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password:
        raise ValueError('http_url_without_credentials_required')
    host = p.hostname.lower()
    if ':' in host:
        host = f'[{host}]'
    port = p.port or (443 if p.scheme == 'https' else 80)
    return f'{p.scheme}://{host}:{port}'


def redacted_url(url: str) -> str:
    try:
        # Queries/fragments can hold credentials. Paths may still be sensitive.
        return origin(url) + (urlsplit(url).path or '/')
    except ValueError:
        return 'non_http_url'


@dataclass(frozen=True)
class NetworkProfile:
    name: str
    mode: str = 'offline'  # offline, loopback, allowlist
    allowed_origins: tuple[str, ...] = ()
    methods: tuple[str, ...] = ('GET', 'HEAD')
    resource_types: tuple[str, ...] = tuple(sorted(RESOURCE_TYPES))
    max_requests: int = 1000
    max_redirects: int = 8
    max_response_bytes: int = 16 * 1024 * 1024

    def __post_init__(self):
        if (not self.name or self.mode not in {'offline', 'loopback', 'allowlist'} or
                not self.methods or not set(self.methods) <= {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'} or
                not self.resource_types or not set(self.resource_types) <= RESOURCE_TYPES or
                type(self.max_requests) is not int or not 1 <= self.max_requests <= 10000 or
                type(self.max_redirects) is not int or not 0 <= self.max_redirects <= 20 or
                type(self.max_response_bytes) is not int or self.max_response_bytes < 1):
            raise ValueError('invalid_network_profile')
        normalized = tuple(origin(u) for u in self.allowed_origins)
        if any(urlsplit(u).path not in ('', '/') or urlsplit(u).query or urlsplit(u).fragment
               for u in self.allowed_origins):
            raise ValueError('network_allowlist_requires_origins_not_paths')
        if self.mode == 'offline' and normalized:
            raise ValueError('offline_has_no_origins')
        if self.mode != 'offline' and not normalized:
            raise ValueError('explicit_origins_required')
        if self.mode == 'loopback':
            for u in normalized:
                try:
                    if not ipaddress.ip_address(urlsplit(u).hostname).is_loopback:
                        raise ValueError('numeric_loopback_required')
                except ValueError as exc:
                    raise ValueError('numeric_loopback_required') from exc
        object.__setattr__(self, 'allowed_origins', normalized)

    def permits(self, url, method='GET', resource_type='document', redirects=0):
        try:
            return (self.mode != 'offline' and origin(url) in self.allowed_origins and
                    method in self.methods and resource_type in self.resource_types and
                    redirects <= self.max_redirects)
        except ValueError:
            return False


@dataclass(frozen=True)
class PlaywrightBrowserBinding:
    capability_id: str
    network_profiles: tuple[NetworkProfile, ...]
    artifact_paths: AuthorizedPaths | None = None
    actions: tuple[str, ...] = tuple(sorted(BROWSER_ACTIONS))
    timeout_seconds: float = 30.0
    action_timeout_seconds: float = 8.0
    max_sessions: int = 4
    max_elements: int = 100
    max_text_chars: int = 32768
    max_screenshot_bytes: int = 16 * 1024 * 1024
    evidence_events: int = 200
    max_evidence_bytes: int = 256 * 1024
    max_frames: int = 32
    max_dom_candidates: int = 10000
    max_capture_bytes: int = 8 * 1024 * 1024
    capture_resource_types: tuple[str, ...] = ('xhr', 'fetch')
    max_capture_records: int = 200
    max_capture_seconds: float = 60.0
    record_console_text: bool = False
    headless: bool = True

    def __post_init__(self):
        if (not self.capability_id or not self.network_profiles or
                len({p.name for p in self.network_profiles}) != len(self.network_profiles) or
                not set(self.actions) <= BROWSER_ACTIONS or not self.actions or
                not 2 <= self.timeout_seconds <= 120 or
                not 0 < self.action_timeout_seconds < self.timeout_seconds or
                type(self.headless) is not bool or type(self.record_console_text) is not bool or
                any(type(n) is not int or n < 1 for n in (self.max_sessions, self.max_elements,
                    self.max_text_chars, self.max_screenshot_bytes, self.evidence_events)) or
                self.max_sessions > 16 or self.max_elements > 500 or self.evidence_events > 2000):
            raise ValueError('invalid_playwright_binding')
        if (not 1 <= self.max_frames <= 128 or not 100 <= self.max_dom_candidates <= 100000 or
                not 1 <= self.max_capture_bytes <= 64 * 1024 * 1024 or
                not 1 <= self.max_capture_records <= 2000 or not 1 <= self.max_capture_seconds <= 300 or
                not 1024 <= self.max_evidence_bytes <= 8 * 1024 * 1024 or
                not set(self.capture_resource_types) <= RESOURCE_TYPES - {'eventsource', 'media'}):
            raise ValueError('invalid_browser_capture_bounds')


@dataclass
class _Session:
    context: object
    page: object
    binding: PlaywrightBrowserBinding
    scope: str
    profile: NetworkProfile
    page_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    observation: dict | None = None
    references: dict = field(default_factory=dict)
    events: deque = field(default_factory=deque)
    requests: int = 0
    sequence: int = 0
    event_bytes: int = 0
    observations: int = 0
    active_deadline: float = 0.0
    frame_ids: dict = field(default_factory=dict)
    reference_frames: dict = field(default_factory=dict)
    channels: list = field(default_factory=list)
    hop_counts: dict = field(default_factory=dict)
    capture: dict | None = None
    created_at: float = field(default_factory=time.monotonic)
    last_action: str = 'open'
    network_mutation_dispatched: bool = False

    def record(self, kind, **data):
        self.sequence += 1
        record={'sequence': self.sequence, 'kind': kind, **data}
        size=len(json.dumps(record,ensure_ascii=False).encode('utf-8'))
        if size>self.binding.max_evidence_bytes:
            record={'sequence':self.sequence,'kind':kind,'event_omitted':'byte_budget'}
            size=len(json.dumps(record).encode())
        while self.events and (len(self.events)>=self.binding.evidence_events or
                self.event_bytes+size>self.binding.max_evidence_bytes):
            self.event_bytes-=len(json.dumps(self.events.popleft(),ensure_ascii=False).encode('utf-8'))
        self.events.append(record); self.event_bytes+=size

    def invalidate(self):
        self.observation = None
        for handle in self.references.values():
            try:
                handle.dispose()
            except Exception:
                pass
        self.references.clear()
        self.reference_frames.clear()


# Fixed internal script, never supplied by an OperationRequest. DOM revision is
# freshness evidence, not a security authority against malicious page scripts.
_INIT = """(() => {
  const state = {documentId: globalThis.crypto?.randomUUID?.() ||
    Date.now().toString(36) + Math.random().toString(36), revision: 0, closedRoots:0};
  Object.defineProperty(window, '__sentraFreshness', {value: state});
  const roots = new WeakSet();
  function watch(root) {
    if (roots.has(root)) return;
    roots.add(root);
    new MutationObserver(() => state.revision++).observe(root,
      {subtree:true, childList:true, attributes:true, characterData:true});
    root.addEventListener('input', () => state.revision++, true);
    root.addEventListener('change', () => state.revision++, true);
  }
  watch(document);
  const original = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function(options) {
    const root = original.call(this, options);
    watch(root); state.revision++;
    if(options.mode==='closed') state.closedRoots++;
    return root;
  };
  // Declarative shadow roots can bypass attachShadow. Register existing open
  // roots during bounded observation, without assigning attributes to the DOM.
  state.watch = watch;
})()"""
_FRESH = "() => ({document_id: window.__sentraFreshness.documentId, dom_revision: window.__sentraFreshness.revision})"
_SCAN_ROOTS = """limit => {
  const state=window.__sentraFreshness, stack=[document], seen=new Set();
  let count=0, openRoots=0;
  while(stack.length && count<limit) {
    const node=stack.pop(); count++;
    if(node.shadowRoot) { state.watch(node.shadowRoot); stack.push(node.shadowRoot); openRoots++; }
    for(let child=node.lastElementChild; child && stack.length<limit; child=child.previousElementSibling)
      stack.push(child);
  }
  return {candidates:count, truncated:stack.length>0, open_roots:openRoots, closed_roots:state.closedRoots};
}"""
_READ_BOUNDED = """(el, bounds) => {
  if(['INPUT','TEXTAREA','SELECT'].includes(el.tagName)) {
    const value=el.value || ''; return {text:value.slice(0,bounds.chars),truncated:value.length>bounds.chars};
  }
  const stack=[el], parts=[]; let remaining=bounds.chars, visited=0;
  while(stack.length && remaining>0 && visited<bounds.nodes) {
    const node=stack.pop(); visited++;
    if(node.nodeType===Node.TEXT_NODE) {
      const value=node.nodeValue || '', piece=value.slice(0,remaining);
      parts.push(piece); remaining-=piece.length;
    } else {
      if(node.nodeType===Node.ELEMENT_NODE) {
        if(['SCRIPT','STYLE','TEMPLATE'].includes(node.tagName)) continue;
        const style=getComputedStyle(node);
        if(style.display==='none' || style.visibility==='hidden') continue;
        if(node.shadowRoot) { stack.push(node.shadowRoot); continue; }
      }
      for(let child=node.lastChild; child && stack.length<bounds.nodes; child=child.previousSibling) stack.push(child);
    }
  }
  return {text:parts.join(''),truncated:stack.length>0 || remaining===0 || visited>=bounds.nodes};
}"""
_META = """el => {
  const tag = el.tagName.toLowerCase();
  const roles = {body:'document',button:'button',a:'link',textarea:'textbox',
    select:'combobox',h1:'heading',h2:'heading',h3:'heading',summary:'button'};
  let role = el.getAttribute('role') || roles[tag] || (tag==='input' ?
    ({checkbox:'checkbox',radio:'radio',button:'button',submit:'button',number:'spinbutton'}[el.type] || 'textbox') : 'generic');
  let name = el.getAttribute('aria-label') ||
    (el.getAttribute('aria-labelledby') || '').split(/\\s+/).map(id =>
      el.getRootNode().getElementById?.(id)?.textContent || '').join(' ').trim() ||
    Array.from(el.labels || []).map(l => l.textContent).join(' ').trim() ||
    (['button','a','summary','h1','h2','h3'].includes(tag) ? el.textContent : '') ||
    el.getAttribute('placeholder') || el.getAttribute('title') || '';
  const shadow_path=[]; let node=el;
  while(node.getRootNode().host && shadow_path.length<32) {
    node=node.getRootNode().host;
    shadow_path.unshift({tag:node.tagName.toLowerCase(),id:node.id.slice(0,128)});
  }
  return {role, name:name.trim().slice(0,256), tag, shadow_path,
    input_type: tag==='input' ? el.type : null, disabled:!!el.disabled,
    editable: !el.disabled && (tag==='textarea' || el.isContentEditable ||
      (tag==='input' && ['text','password','email','number','search','tel','url',
       'date','datetime-local','month','time','week'].includes(el.type)))};
}"""


class _TargetChannel:
    """CDP non-flattened child transport; policy is armed before target runs.

    OOPIF and worker targets recursively attach through their owning target.
    Only the fresh browser launched by this backend is connected.
    """
    def __init__(self, backend, parent, session_id, session, target_type):
        self.backend, self.parent, self.session_id = backend, parent, session_id
        self.session, self.target_type = session, target_type
        self.counter, self.responses = 0, {}

    def send(self, method, params=None):
        self.counter += 1
        key = self.counter
        self.parent.send('Target.sendMessageToTarget', {'sessionId': self.session_id,
            'message': json.dumps({'id': key, 'method': method, 'params': params or {}})})
        deadline = min(self.session.active_deadline, time.monotonic() + self.session.binding.action_timeout_seconds)
        while key not in self.responses:
            if time.monotonic() >= deadline:
                raise ExecutorFailure('browser_cdp_deadline')
            # A real CDP roundtrip pumps incoming child responses/events.
            self.backend._root.send('Browser.getVersion')
        response = self.responses.pop(key)
        if 'error' in response:
            raise ExecutorFailure('browser_cdp_protocol_error', evidence={'method': method})
        return response.get('result', {})

    def received(self, message):
        if 'id' in message:
            self.responses[message['id']] = message
            return
        method, params = message.get('method'), message.get('params', {})
        if method == 'Target.receivedMessageFromTarget':
            self.backend._received(params)
        elif method == 'Target.attachedToTarget':
            self.backend._attached(self, params, self.session)
        elif method == 'Target.detachedFromTarget':
            self.backend._channels.pop(params['sessionId'], None)
        elif method == 'Fetch.requestPaused':
            self.backend._intercept(self, params)
        elif method == 'Fetch.authRequired':
            self.send('Fetch.continueWithAuth', {'requestId': params['requestId'],
                'authChallengeResponse': {'response': 'CancelAuth'}})


class PlaywrightBrowserBackend:
    """One real Playwright actor and one ephemeral context per session."""
    def __init__(self):
        self._actor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sentra-playwright')
        self._playwright = None
        self._browser = None
        self._headless = None
        self._sessions = {}
        self._closed = False
        self._root = None
        self._contexts, self._channels = {}, {}
        self._diagnostic_lock = threading.Lock()
        self._diagnostics = {}
        self._browser_handle = None
        self._deadline_terminated = False

    def run(self, binding, arguments):
        if arguments['action'] == 'diagnostics':
            # Cached diagnostics remain usable while the actor is busy/hung.
            with self._diagnostic_lock:
                items = [dict(v) for v in self._diagnostics.values()
                         if v['scope'] == arguments['_scope'] and
                         ('session_id' not in arguments or v['session_id'] == arguments['session_id'])]
            for item in items: item.pop('scope', None)
            for item in items:
                item['deadline_expired'] = time.monotonic() >= item.pop('active_deadline_monotonic')
            return {'backend_closed': self._closed, 'restart_required':self._deadline_terminated,
                    'sessions': items, 'cached': True,
                    'providers': dependency_versions()}
        if self._closed:
            raise ExecutorFailure('browser_backend_closed')
        deadline = time.monotonic() + binding.timeout_seconds - 0.5
        # The dedicated thread must inherit the durable authority/lease context.
        context = copy_context()
        def expired():
            # Killing the retained kernel handle aborts a blocked IO.read/CDP
            # call. Never identify or terminate the user's browser by name/PID.
            if self._browser_handle is not None:
                self._deadline_terminated = True
                self._browser_handle.terminate()
        watchdog = threading.Timer(max(0.001, deadline-time.monotonic()), expired)
        watchdog.daemon = True
        watchdog.start()
        try:
            return self._actor.submit(context.run, self._dispatch, binding, arguments, deadline).result()
        finally:
            watchdog.cancel()

    def _launch(self, b, deadline):
        dependency('playwright', (1, 51, 0))
        if self._browser is not None:
            if self._headless != b.headless:
                raise ExecutorFailure('browser_launch_profile_mismatch')
            if not self._browser.is_connected():
                raise ExecutorFailure('browser_disconnected_restart_backend_required')
            return
        from playwright.sync_api import sync_playwright
        effect_checkpoint()
        pw = sync_playwright().start()
        try:
            if not Path(pw.chromium.executable_path).is_file():
                raise ExecutorFailure('playwright_chromium_binary_missing', evidence={
                    'install_command': 'python -m playwright install chromium'})
            browser = pw.chromium.launch(headless=b.headless,
                timeout=max(1, int((deadline - time.monotonic()) * 1000)),
                args=['--disable-background-networking', '--no-first-run',
                      '--force-webrtc-ip-handling-policy=disable_non_proxied_udp','--site-per-process'])
        except Exception:
            pw.stop()
            raise
        self._playwright, self._browser, self._headless = pw, browser, b.headless
        self._root = browser.new_browser_cdp_session()
        self._root.on('Target.attachedToTarget', lambda p: self._attached(self._root, p))
        self._root.on('Target.receivedMessageFromTarget', self._received)
        self._root.on('Target.detachedFromTarget', lambda p: self._channels.pop(p['sessionId'], None))
        self._root.send('Target.setAutoAttach', {'autoAttach': True,
            'waitForDebuggerOnStart': True, 'flatten': False})
        processes = self._root.send('SystemInfo.getProcessInfo')['processInfo']
        browser_pids = [int(p['id']) for p in processes if p['type'] == 'browser']
        if len(browser_pids) != 1:
            raise ExecutorFailure('browser_process_ownership_ambiguous')
        self._browser_handle = OwnedProcessHandle(browser_pids[0])

    def _received(self, params):
        channel = self._channels.get(params['sessionId'])
        if channel:
            channel.received(json.loads(params['message']))

    def _attached(self, parent, params, inherited=None):
        info = params['targetInfo']
        session = self._contexts.get(info.get('browserContextId')) or inherited
        if session is None or len(session.channels) >= session.binding.max_frames * 2 or info['type'] == 'page' and any(
                c.target_type == 'page' for c in session.channels):
            # Popups are not declared actionable targets. This happens before
            # their scripts run and before releasing the target debugger pause.
            self._root.send('Target.closeTarget', {'targetId': info['targetId']})
            return
        channel = _TargetChannel(self, parent, params['sessionId'], session, info['type'])
        self._channels[channel.session_id] = channel
        session.channels.append(channel)
        try:
            channel.send('Target.setAutoAttach', {'autoAttach': True,
                'waitForDebuggerOnStart': True, 'flatten': False})
            channel.send('Fetch.enable', {'patterns': [{'urlPattern': '*', 'requestStage': 'Request'}],
                                         'handleAuthRequests': True})
            effect_checkpoint()
            channel.send('Runtime.runIfWaitingForDebugger')
            session.record('target_guarded', target_type=info['type'])
        except Exception:
            self._root.send('Target.closeTarget', {'targetId': info['targetId']})
            session.record('target_policy_install_failed', target_type=info['type'])
            raise

    def _intercept(self, channel, event):
        s, request = channel.session, event['request']
        rid = event['requestId']
        response_stage = 'responseStatusCode' in event or 'responseErrorReason' in event
        resource = event['resourceType'].lower()
        capture = s.capture
        if capture and capture['state']=='recording' and time.monotonic()>=capture['deadline']:
            capture['state']='duration_limit'
        try:
            if time.monotonic() >= s.active_deadline:
                raise ExecutorFailure('browser_network_deadline')
            effect_checkpoint()
            if not response_stage:
                previous = event.get('redirectedRequestId')
                depth = 0 if previous is None else s.hop_counts.get(
                    (channel.session_id, previous), s.profile.max_redirects) + 1
                s.requests += 1
                if s.requests <= s.profile.max_requests:
                    s.hop_counts[(channel.session_id, rid)] = depth
                permitted = (s.requests <= s.profile.max_requests and s.profile.permits(
                    request['url'], request['method'], resource, depth))
                s.record('request', url=redacted_url(request['url']), method=request['method'],
                         resource_type=resource, redirect_depth=depth, allowed=permitted)
                if not permitted:
                    if previous is not None: s.record('redirect_blocked', url=redacted_url(request['url']), depth=depth)
                    raise ExecutorFailure('browser_request_policy_denied')
                capture_this = (capture is not None and capture['state'] == 'recording' and
                    resource in s.binding.capture_resource_types and
                    time.monotonic() < capture['deadline'])
                # Chromium follows redirects itself; each next request pauses
                # here again. No proxy fetch, URL rewrite or cookie substitution.
                if request['method'] not in {'GET','HEAD','OPTIONS'}:
                    s.network_mutation_dispatched=True
                channel.send('Fetch.continueRequest', {'requestId': rid, 'interceptResponse': capture_this})
                return
            status = event.get('responseStatusCode', 0)
            if not capture or capture['state'] != 'recording' or status in (204, 304) or (
                    300 <= status < 400) or request['method'] == 'HEAD':
                channel.send('Fetch.continueResponse', {'requestId': rid})
                return
            headers = event.get('responseHeaders', [])
            encoding=next((h['value'].lower() for h in headers if h['name'].lower()=='content-encoding'),'identity')
            if encoding not in {'identity',''}:
                # Preserve compressed responses unchanged; do not guess whether
                # this Chromium build's IO stream exposes encoded/decoded bytes.
                s.record('capture_skipped_encoding',encoding=encoding[:128],url=redacted_url(request['url']))
                capture['skipped_encoded_responses']+=1
                channel.send('Fetch.continueResponse',{'requestId':rid}); return
            if time.monotonic() >= capture['deadline'] or len(capture['records']) >= s.binding.max_capture_records:
                capture['state'] = 'limit_reached'
                channel.send('Fetch.continueResponse', {'requestId': rid})
                return
            limit = min(s.profile.max_response_bytes, s.binding.max_capture_bytes - capture['bytes'])
            if limit < 1:
                capture['state'] = 'limit_reached'
                channel.send('Fetch.continueResponse', {'requestId': rid})
                return
            stream = channel.send('Fetch.takeResponseBodyAsStream', {'requestId': rid})['stream']
            body = bytearray()
            def stream_expired():
                capture['state']='timeout'
                if self._browser_handle is not None:
                    self._deadline_terminated=True; self._browser_handle.terminate()
            stream_watchdog=threading.Timer(max(.001,min(s.active_deadline,capture['deadline'])-time.monotonic()),stream_expired)
            stream_watchdog.daemon=True; stream_watchdog.start()
            try:
                while True:
                    if time.monotonic() >= min(s.active_deadline, capture['deadline']):
                        raise ExecutorFailure('browser_capture_deadline')
                    effect_checkpoint()
                    chunk = channel.send('IO.read', {'handle': stream, 'size': min(65536, limit-len(body)+1)})
                    data = base64.b64decode(chunk['data']) if chunk.get('base64Encoded') else chunk['data'].encode('utf-8')
                    if len(body) + len(data) > limit:
                        raise ExecutorFailure('browser_capture_byte_limit')
                    body.extend(data)
                    if chunk['eof']: break
            finally:
                stream_watchdog.cancel()
                channel.send('IO.close', {'handle': stream})
            effect_checkpoint()
            # The stream is consumed. Return the actual captured bytes, with
            # transport encoding/length reflecting the decoded body supplied.
            forwarded = [h for h in headers if h['name'].lower() not in
                         {'content-encoding', 'content-length', 'transfer-encoding'}]
            forwarded.append({'name': 'Content-Length', 'value': str(len(body))})
            channel.send('Fetch.fulfillRequest', {'requestId': rid, 'responseCode': status,
                'responseHeaders': forwarded, 'body': base64.b64encode(body).decode('ascii')})
            capture['bytes'] += len(body)
            capture['records'].append({'url': redacted_url(request['url']), 'status': status,
                'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                'body_base64': base64.b64encode(body).decode('ascii')})
            s.record('response_captured', bytes=len(body), status=status)
        except Exception as exc:
            if capture and response_stage:
                capture['state'] = 'failed'
            s.record('request_blocked', error=exc.code if isinstance(exc, ExecutorFailure) else 'browser_cdp_error')
            try: channel.send('Fetch.failRequest', {'requestId': rid, 'errorReason': 'BlockedByClient'})
            except Exception: pass

    def _cache_diagnostics(self, sid, s, *, closed=False):
        item = {'scope': s.scope, 'session_id': sid, 'page_id': s.page_id,
            'state': 'closed' if closed else ('page_closed' if s.page.is_closed() else 'open'),
            'last_action': s.last_action, 'age_seconds': round(time.monotonic()-s.created_at, 3),
            'profile': s.profile.name, 'request_count': s.requests, 'event_sequence': s.sequence,
            'evidence_bytes':s.event_bytes,
            'frames_observed': len(s.frame_ids), 'guarded_targets': len(s.channels),
            'capture_state': s.capture['state'] if s.capture else 'inactive',
            'capture_bytes': s.capture['bytes'] if s.capture else 0,
            'active_deadline_monotonic': s.active_deadline,
            'deadline_expired': time.monotonic() >= s.active_deadline}
        with self._diagnostic_lock:
            if len(self._diagnostics) >= 256 and sid not in self._diagnostics:
                self._diagnostics.pop(next(iter(self._diagnostics)))
            self._diagnostics[sid] = item

    def _new_session(self, b, a, deadline):
        if sum(s.scope == a['_scope'] for s in self._sessions.values()) >= b.max_sessions:
            raise ExecutorFailure('browser_session_limit')
        self._launch(b, deadline)
        profile = next(p for p in b.network_profiles if p.name == a['profile'])
        before_contexts = set(self._root.send('Target.getBrowserContexts')['browserContextIds'])
        effect_checkpoint()
        context = self._browser.new_context(accept_downloads=False, service_workers='block',
            permissions=[], ignore_https_errors=False, java_script_enabled=True,
            viewport={'width': 1280, 'height': 800})
        try:
            context.add_init_script(script=_INIT)
            # Create after HTTP and websocket controls are installed.
            session = _Session(context, None, b, a['_scope'], profile,
                               events=deque(maxlen=b.evidence_events), active_deadline=deadline)
            added_contexts = set(self._root.send('Target.getBrowserContexts')['browserContextIds']) - before_contexts
            if len(added_contexts) != 1:
                raise ExecutorFailure('browser_context_identity_ambiguous')
            context_id = added_contexts.pop()
            self._contexts[context_id] = session
            def block_websocket(ws):
                session.record('websocket_blocked', url=redacted_url(ws.url))
                ws.close()
            context.route_web_socket('**/*', block_websocket)
            context.set_offline(profile.mode == 'offline')
            effect_checkpoint()
            page = context.new_page()
            session.page = page
            # Only this page is actionable. HTTP routing also applies to popups.
            context.on('page', lambda popup: popup.close() if popup != page else None)
            page.on('dialog', lambda dialog: dialog.dismiss())
            def console(message):
                text = message.text
                data = {'level': message.type, 'text_sha256': hashlib.sha256(text.encode()).hexdigest()}
                if b.record_console_text:
                    data['text'] = text[:2048]
                session.record('console', **data)
            page.on('console', console)
            page.on('pageerror', lambda error: session.record('pageerror',
                text_sha256=hashlib.sha256(str(error).encode()).hexdigest()))
            page.on('response', lambda response: session.record('response',
                url=redacted_url(response.url), status=response.status))
            page.on('requestfailed', lambda r: session.record('requestfailed',
                url=redacted_url(r.url), failure=str(r.failure)[:256]))
            sid = uuid.uuid4().hex
            self._sessions[sid] = session
            self._cache_diagnostics(sid, session)
            return {'session_id': sid, 'page_id': session.page_id, 'profile': profile.name,
                    'isolated_context': True, 'providers': dependency_versions()}
        except Exception:
            context.close()
            raise

    def _session(self, b, a):
        s = self._sessions.get(a['session_id'])
        if s is None or s.scope != a['_scope'] or s.binding != b:
            raise ExecutorFailure('browser_session_scope_mismatch')
        return s

    def _observe(self, s, deadline):
        for attempt in range(3):
            try: return self._observe_once(s,deadline)
            except ExecutorFailure as exc:
                if exc.code!='page_changed_during_observation' or attempt==2 or time.monotonic()>=deadline:
                    raise
        raise ExecutorFailure('page_changed_during_observation')

    def _observe_once(self, s, deadline):
        s.invalidate()
        s.observations += 1
        frames = list(s.page.frames)
        if len(frames) > s.binding.max_frames:
            raise ExecutorFailure('browser_frame_limit')
        before, frame_views = {}, []
        elements = []
        handles = []
        truncated = False
        try:
            for frame in frames:
                if time.monotonic() >= deadline:
                    raise ExecutorFailure('browser_observation_deadline')
                if frame.is_detached():
                    raise ExecutorFailure('page_changed_during_observation')
                fid = s.frame_ids.setdefault(frame, uuid.uuid4().hex)
                scan = frame.evaluate(_SCAN_ROOTS, s.binding.max_dom_candidates)
                if scan['truncated']:
                    raise ExecutorFailure('browser_dom_candidate_limit')
                before[fid] = frame.evaluate(_FRESH)
                frame_views.append(dict(before[fid], frame_id=fid,
                    parent_frame_id=s.frame_ids.get(frame.parent_frame),
                    url=redacted_url(frame.url), name=frame.name[:128], **scan))
                # Playwright CSS locators pierce open shadow roots. Handles,
                # not re-resolved nth selectors, are retained for later actions.
                locator = frame.locator('body,button,a[href],input,textarea,select,[role],[contenteditable=true],h1,h2,h3,summary')
                count = locator.count()
                for index in range(min(count, s.binding.max_elements * 10)):
                    if time.monotonic() >= deadline:
                        raise ExecutorFailure('browser_observation_deadline')
                    if len(elements) >= s.binding.max_elements:
                        truncated = True
                        break
                    handle = locator.nth(index).element_handle()
                    if handle is None:
                        raise ExecutorFailure('page_changed_during_observation')
                    handles.append(handle)
                    if handle.is_visible():
                        ref = f'e{len(elements)}'
                        elements.append(dict(handle.evaluate(_META), element_ref=ref, frame_id=fid))
                        s.references[ref], s.reference_frames[ref] = handle, frame
                    else:
                        handle.dispose()
                truncated |= count > min(count, s.binding.max_elements * 10)
            after = {s.frame_ids[f]: f.evaluate(_FRESH) for f in frames}
            if before != after or list(s.page.frames) != frames:
                raise ExecutorFailure('page_changed_during_observation')
            main = after[s.frame_ids[s.page.main_frame]]
            observation = dict(main, page_id=s.page_id, revision=s.observations,
                observation_id=uuid.uuid4().hex, elements=elements,
                frames=frame_views, frame_revisions=after,
                semantic_summary='\n'.join(f"{e['frame_id']} {e['element_ref']} {e['role']} {e['name']}" for e in elements)[:s.binding.max_text_chars],
                truncated=truncated, shadow_dom='open roots supported; closed roots counted, not actionable',
                name_source='bounded DOM role/label observation; not a full accessibility-tree dump')
            s.observation = observation
            return observation
        except Exception:
            s.invalidate()
            for handle in handles:
                try: handle.dispose()
                except Exception: pass
            raise

    def _reference(self, s, a):
        o = s.observation
        if (not o or any(a[k] != o[k] for k in ('observation_id', 'page_id', 'revision')) or
                not self._fresh(s)):
            raise ExecutorFailure('stale_browser_observation')
        ref = a['element_ref']
        handle = s.references.get(ref)
        metadata = next((e for e in o['elements'] if e['element_ref'] == ref), None)
        if handle is None or metadata is None or not handle.evaluate('el => el.isConnected'):
            raise ExecutorFailure('invalid_browser_element_reference')
        if any(a[k] != metadata[k] for k in ('role', 'name','frame_id') if k in a):
            raise ExecutorFailure('semantic_element_mismatch')
        if not handle.is_visible():
            raise ExecutorFailure('browser_element_not_visible')
        return handle, metadata

    def _fresh(self, s):
        if not s.observation: return False
        frames = list(s.page.frames)
        if {s.frame_ids.get(f) for f in frames} != set(s.observation['frame_revisions']): return False
        try:
            return all(not f.is_detached() and f.evaluate(_FRESH) ==
                s.observation['frame_revisions'][s.frame_ids[f]] for f in frames)
        except Exception:
            return False

    def _dispatch(self, b, a, deadline):
        if time.monotonic() >= deadline:
            raise ExecutorFailure('browser_queue_deadline')
        action, dispatched, s = a['action'], False, None
        try:
            if action == 'open':
                return self._new_session(b, a, deadline)
            s = self._session(b, a)
            s.active_deadline = deadline
            s.network_mutation_dispatched=False
            s.last_action = action
            self._cache_diagnostics(a['session_id'], s)
            if action == 'close':
                if s.capture is not None: raise ExecutorFailure('browser_capture_export_required_before_close')
                s.invalidate()
                dispatched = True
                s.context.close()
                self._cache_diagnostics(a['session_id'], s, closed=True)
                for key in [k for k,v in self._contexts.items() if v is s]: del self._contexts[key]
                del self._sessions[a['session_id']]
                return {'session_id': a['session_id'], 'closed': True}
            if action == 'evidence':
                # Failed/aborted navigation can leave a Chromium error page
                # without an execution context. The already captured evidence
                # must remain readable even when the page cannot evaluate JS.
                pump_available = not s.page.is_closed()
                if pump_available:
                    try:
                        s.page.evaluate('() => 0')
                    except Exception:
                        pump_available = False
                events = [e for e in s.events if e['sequence'] > a.get('after_sequence', 0)]
                return {'events': events, 'last_sequence': s.sequence,
                        'dropped_before_sequence': s.events[0]['sequence'] if s.events else 0,
                        'event_pump_available': pump_available,
                        'queries_headers_bodies_cookies_recorded': False}
            if s.page.is_closed() and action != 'capture.stop':
                raise ExecutorFailure('browser_page_closed')
            timeout = max(1, int(min(b.action_timeout_seconds, deadline-time.monotonic()) * 1000))
            s.page.set_default_timeout(timeout)
            s.page.set_default_navigation_timeout(timeout)
            if action == 'capture.start':
                if s.capture is not None:
                    raise ExecutorFailure('browser_capture_must_be_exported_before_restart')
                effect_checkpoint()
                s.capture = {'state': 'recording', 'deadline': time.monotonic()+b.max_capture_seconds,
                             'bytes': 0, 'records': [],'skipped_encoded_responses':0}
                return {'capture_state': 'recording', 'byte_budget': b.max_capture_bytes,
                        'resource_types': list(b.capture_resource_types)}
            if action == 'capture.stop':
                if s.capture is None: raise ExecutorFailure('browser_capture_not_started')
                previous = s.capture['state']
                s.capture['state'] = 'stopped'
                payload = json.dumps({'session_id': a['session_id'], 'page_id': s.page_id,
                    'prior_state': previous, 'bytes': s.capture['bytes'], 'records': s.capture['records'],
                    'skipped_encoded_responses':s.capture['skipped_encoded_responses'],
                    'resource_types':list(b.capture_resource_types),'completeness_asserted':False},
                    ensure_ascii=False).encode('utf-8')
                artifact = atomic_output(b.artifact_paths, a['output'], lambda p: p.write_bytes(payload),
                    lambda p: json.loads(p.read_text(encoding='utf-8')))
                s.capture = None
                return {'artifact': artifact, 'capture_state': 'exported', 'prior_state': previous}
            if action == 'network':
                profile = next(p for p in b.network_profiles if p.name == a['profile'])
                s.invalidate()
                effect_checkpoint()
                dispatched = True
                # Previously issued requests are not rolled back; route closure
                # reads this profile for every subsequent request/redirect.
                s.profile, s.requests = profile, 0
                s.hop_counts.clear()
                s.context.set_offline(profile.mode == 'offline')
                return {'profile': profile.name, 'applies_to': 'subsequent requests',
                        'inflight_requests_not_revoked': True}
            if action == 'navigate':
                if not s.profile.permits(a['url']):
                    raise ExecutorFailure('browser_navigation_network_denied')
                s.invalidate()
                effect_checkpoint()
                dispatched = True
                response = s.page.goto(a['url'], wait_until='domcontentloaded', timeout=timeout)
                if not s.profile.permits(s.page.url):
                    raise ExecutorFailure('browser_final_url_denied', uncertain=True)
                return {'url': redacted_url(s.page.url), 'status': response.status if response else None,
                        'page_id': s.page_id, 'requires_new_observation': True}
            if action == 'observe':
                return self._observe(s, deadline)
            if action in {'click', 'fill', 'read'}:
                handle, metadata = self._reference(s, a)
                if action == 'read':
                    if metadata['input_type'] == 'password':
                        raise ExecutorFailure('password_read_denied')
                    captured = handle.evaluate(_READ_BOUNDED, {'chars':b.max_text_chars,'nodes':b.max_dom_candidates})
                    if not self._fresh(s):
                        raise ExecutorFailure('page_changed_during_read')
                    return {'text': captured['text'], 'truncated': captured['truncated'],
                            'observation_id': a['observation_id'], 'element_ref': a['element_ref']}
                if metadata['disabled'] or (action == 'fill' and not metadata['editable']):
                    raise ExecutorFailure('browser_element_not_actionable')
                if action == 'click' and metadata['role'] not in {'button', 'link', 'checkbox', 'radio', 'tab', 'menuitem', 'option', 'switch'}:
                    raise ExecutorFailure('browser_click_role_denied')
                effect_checkpoint()
                dispatched = True
                try:
                    if action == 'click': handle.click(timeout=timeout)
                    else: handle.fill(a['text'], timeout=timeout)
                finally:
                    s.invalidate()
                return {'action': action, 'element_ref': a['element_ref'], 'requires_new_observation': True}
            if action == 'screenshot':
                # Fixed viewport avoids uncontrolled full-page bitmap growth.
                effect_checkpoint()
                payload = s.page.screenshot(type='png', full_page=False, timeout=timeout)
                if len(payload) > b.max_screenshot_bytes:
                    raise ExecutorFailure('browser_screenshot_size_limit')
                def verify(temp):
                    if not temp.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                        raise ExecutorFailure('invalid_screenshot_png')
                artifact = atomic_output(b.artifact_paths, a['output'], lambda p: p.write_bytes(payload), verify)
                return {'artifact': artifact, 'page_id': s.page_id, 'viewport': [1280, 800]}
            raise ExecutorFailure('unsupported_browser_action')
        except ExecutorFailure as exc:
            if s is not None and s.network_mutation_dispatched or dispatched and exc.code == 'effect_checkpoint_denied':
                raise ExecutorFailure(exc.code, uncertain=True, evidence=exc.evidence) from exc
            raise
        except Exception as exc:
            # Never echo provider exceptions containing URLs, credentials or DOM.
            code = 'browser_provider_timeout' if type(exc).__name__ == 'TimeoutError' else 'browser_provider_error'
            raise ExecutorFailure(code, uncertain=dispatched or s is not None and s.network_mutation_dispatched,
                                  evidence={'provider_exception_type': type(exc).__name__}) from exc
        finally:
            if s is not None and a.get('session_id') in self._sessions:
                self._cache_diagnostics(a['session_id'], s)

    def shutdown(self):
        """Host lifecycle hook, not Operation cleanup; closes every owned context."""
        if self._closed:
            return
        self._closed = True
        try:
            self._actor.submit(self._shutdown).result(timeout=15)
        finally:
            self._actor.shutdown(wait=False, cancel_futures=True)

    def _shutdown(self):
        try:
            for s in list(self._sessions.values()):
                s.invalidate()
                try: s.context.close()
                except Exception: pass
            self._sessions.clear()
            self._contexts.clear()
            self._channels.clear()
            if self._browser is not None:
                try: self._browser.close()
                except Exception: pass  # Watchdog may already have terminated it.
        finally:
            if self._playwright is not None:
                try: self._playwright.stop()
                except Exception: pass
            self._browser = self._playwright = None
            if self._browser_handle is not None:
                self._browser_handle.close()
                self._browser_handle = None


class PlaywrightBrowserExecutor(DiagnosedExecutor):
    kind = 'playwright_browser'

    def __init__(self, *, machine_id, owner_principal_id, bindings, policy=None, backend=None):
        if len({b.capability_id for b in bindings}) != len(bindings):
            raise ValueError('duplicate_browser_capability')
        super().__init__(machine_id=machine_id, owner_principal_id=owner_principal_id,
            bindings={b.capability_id: b for b in bindings}, policy=policy)
        self.backend = backend if backend is not None else PlaywrightBrowserBackend()

    def _validate(self, request, b):
        a = dict(request.arguments)
        action = a.get('action')
        if type(action) is not str or action not in b.actions:
            raise ValueError('browser_action_denied')
        fields = {'open': {'profile'}, 'close': set(), 'network': {'profile'},
            'navigate': {'url'}, 'observe': set(), 'screenshot': {'output'},
            'evidence': {'after_sequence'}, 'diagnostics': set(),
            'capture.start': set(), 'capture.stop': {'output'},
            'click': {'observation_id', 'page_id', 'revision', 'element_ref', 'role', 'name','frame_id'},
            'fill': {'observation_id', 'page_id', 'revision', 'element_ref', 'role', 'name','frame_id','text'},
            'read': {'observation_id', 'page_id', 'revision', 'element_ref', 'role', 'name','frame_id'}}[action]
        if set(a) - ({'action'} | fields | ({'session_id'} if action != 'open' else set())):
            raise ValueError('invalid_browser_arguments')
        if action not in {'open', 'diagnostics'} and (type(a.get('session_id')) is not str or not a['session_id']):
            raise ValueError('browser_session_required')
        if action == 'diagnostics' and 'session_id' in a and (type(a['session_id']) is not str or not a['session_id']):
            raise ValueError('invalid_diagnostic_session')
        if action in {'open', 'network'} and a.get('profile') not in {p.name for p in b.network_profiles}:
            raise ValueError('declared_network_profile_required')
        if action == 'navigate':
            origin(a.get('url'))
        if action in {'click', 'fill', 'read'}:
            if any(type(a.get(k)) is not str or not a[k] for k in ('observation_id', 'page_id', 'element_ref')):
                raise ValueError('observation_reference_required')
            if type(a.get('revision')) is not int or a['revision'] < 1:
                raise ValueError('observation_revision_required')
            for k in ('role', 'name','frame_id'):
                if k in a and (type(a[k]) is not str or len(a[k]) > 256):
                    raise ValueError('invalid_semantic_constraint')
        if action == 'fill' and (type(a.get('text')) is not str or len(a['text']) > b.max_text_chars):
            raise ValueError('invalid_browser_text')
        if action in {'screenshot', 'capture.stop'}:
            if b.artifact_paths is None:
                raise ValueError('browser_artifact_scope_required')
            output = b.artifact_paths.resolve(a.get('output'), write=True)
            if output.suffix.lower() != ('.png' if action == 'screenshot' else '.json'):
                raise ValueError('invalid_browser_artifact_extension')
            a['output'] = str(output)
        if 'after_sequence' in a and (type(a['after_sequence']) is not int or a['after_sequence'] < 0):
            raise ValueError('invalid_evidence_cursor')
        a['_scope'] = json.dumps([self.machine_id, self.owner_principal_id, b.capability_id, request.work_item_id])
        a['_operation_id'] = request.operation_id
        return a

    def _run(self, binding, arguments):
        return self.backend.run(binding, arguments)


def declare_playwright_browser_machine(*, machine_id, owner_principal_id, bindings, policy, backend=None):
    from sentra_runtime.contracts import Capability, Machine
    from .discovery import MachineDeclaration
    executor = PlaywrightBrowserExecutor(machine_id=machine_id, owner_principal_id=owner_principal_id,
                                        bindings=bindings, policy=policy, backend=backend)
    return MachineDeclaration(Machine(machine_id, executor.kind, owner_principal_id,
        tuple(Capability(b.capability_id, 'Isolated Playwright browser', 'high')
              for b in bindings)), executor)
