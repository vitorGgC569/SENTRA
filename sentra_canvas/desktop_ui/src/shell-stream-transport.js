// No mutation/replay capability is present in this module.
const MAX_FRAME = 2_000_000;

export async function* sseFrames(body, onBytes = () => {}) {
  const reader = body.getReader(), decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '', fields = { event: 'message', data: [] }, frameSize = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        if (buffer || fields.data.length) throw new Error('Incomplete SSE frame');
        return;
      }
      onBytes();
      buffer += decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newline).replace(/\r$/, '');
        buffer = buffer.slice(newline + 1);
        frameSize += line.length;
        if (frameSize > MAX_FRAME) throw new Error('SSE frame budget exceeded');
        if (!line) {
          if (fields.data.length) yield {
            event: fields.event, id: fields.id, data: JSON.parse(fields.data.join('\n')),
          };
          fields = { event: 'message', data: [] }; frameSize = 0;
        } else if (!line.startsWith(':')) {
          const colon = line.indexOf(':');
          const key = colon < 0 ? line : line.slice(0, colon);
          const data = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
          if (key === 'data') fields.data.push(data);
          else if (key === 'event') fields.event = data;
          else if (key === 'id' && !data.includes('\0')) fields.id = data;
        }
      }
      if (buffer.length > MAX_FRAME) throw new Error('SSE line budget exceeded');
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function reduceProjection(previous, event) {
  if (!event || !Number.isSafeInteger(event.sequence) || event.sequence < 1 ||
      !['delta', 'snapshot'].includes(event.kind) || typeof event.text !== 'string' ||
      !event.preview || event.preview.operation_id !== event.operation_id) throw new Error('Invalid stream event');
  if (previous && event.sequence <= previous.sequence) return previous;
  if (event.kind === 'delta' && (!previous || previous.sequence !== event.base_sequence ||
      previous.operation_id !== event.operation_id)) throw new Error('Stream gap; snapshot required');
  const content = (event.kind === 'delta' ? previous.content : '') + event.text;
  if (content.length > 200_000) throw new Error('Stream projection budget exceeded');
  return { ...event.preview, content, sequence: event.sequence, persisted: true,
    authoritative: false, partial: true, closes_trio: false, automatic_retry: false };
}

export function reconnectDelay(attempt, random = Math.random) {
  return Math.min(15_000, 500 * 2 ** Math.min(attempt, 6) * (.8 + random() * .4));
}

export class ProjectFeed {
  constructor({ open, readHead, random = Math.random, batchMs = 50, headTimeoutMs = 10_000, silenceMs = 30_000 }) {
    this.open = open; this.readHead = readHead; this.random = random; this.batchMs = batchMs;
    this.headTimeoutMs = headTimeoutMs; this.silenceMs = silenceMs;
    this.listeners = new Set(); this.cursor = undefined; this.state = 'connecting'; this.stopped = false;
  }
  subscribe(scope, observer) {
    const entry = { scope, observer, head: null, queue: [], active: true, syncing: false, timer: null };
    this.listeners.add(entry);
    observer.onState?.(this.state);
    void this.sync(entry);
    if (!this.task && !this.stopped) this.task = this.run();
    return () => { entry.active = false; entry.syncController?.abort(); clearTimeout(entry.timer); clearTimeout(entry.syncRetryTimer); this.listeners.delete(entry); };
  }
  status(state) {
    if (state === this.state) return;
    this.state = state;
    for (const entry of this.listeners) entry.observer.onState?.(state === 'connected' && entry.needsSync ? 'reconnecting' : state);
  }
  notify(entry) {
    if (entry.timer != null) return;
    entry.timer = setTimeout(() => {
      entry.timer = null;
      if (entry.active && entry.head) {
        entry.observer.onState?.(this.state === 'connected' && entry.needsSync ? 'reconnecting' : this.state);
        entry.observer.onPreview({ ...entry.head, received_at_ms: entry.receivedAt });
      }
    }, this.batchMs);
  }
  async sync(entry, force = false) {
    if (!entry.active) return;
    if (entry.syncing) { if (force) entry.resync = true; return; }
    clearTimeout(entry.syncRetryTimer);
    entry.syncing = true; entry.resync = false;
    const controller = new AbortController(); entry.syncController = controller;
    const timeout = setTimeout(() => controller.abort(), this.headTimeoutMs);
    let succeeded = false;
    try {
      const cancelled = new Promise((_resolve, reject) => {
        controller.signal.addEventListener('abort', () => reject(new Error('Snapshot read interrupted')), { once: true });
      });
      const head = await Promise.race([this.readHead(entry.scope, { signal: controller.signal }), cancelled]);
      if (!entry.active) return;
      if (!Number.isSafeInteger(head.sequence) || head.sequence < 0) throw new Error('Invalid snapshot cursor');
      if (!entry.head || head.sequence >= entry.head.sequence) {
        entry.head = { ...head, authoritative: false, partial: true, closes_trio: false, automatic_retry: false };
        this.notify(entry);
      }
      const queued = entry.queue.splice(0);
      for (const event of queued) entry.head = reduceProjection(entry.head, event);
      this.notify(entry);
      succeeded = true; entry.needsSync = false; entry.syncFailures = 0;
    } catch (error) {
      // Keep the last durable content through a transient failed read. Queue
      // subsequent deltas until a fresh head repairs the projection gap.
      entry.needsSync = true;
      if (entry.active) {
        if ([401, 403].includes(error.status)) entry.observer.onState?.('reauth_required');
        else {
          entry.observer.onState?.('reconnecting');
          entry.syncRetryTimer = setTimeout(() => void this.sync(entry),
            reconnectDelay(entry.syncFailures || 0, this.random));
          entry.syncFailures = (entry.syncFailures || 0) + 1;
        }
      }
    } finally {
      clearTimeout(timeout); controller.abort(); entry.syncController = null;
      entry.syncing = false;
      if (entry.resync && succeeded) { entry.resync = false; void this.sync(entry); }
    }
  }
  receive(frame) {
    if (frame.event === 'unavailable') throw new Error('Presentation feed unavailable');
    if (frame.event === 'snapshot') {
      if (!frame.data?.reset || !Number.isSafeInteger(frame.data.cursor) || frame.data.cursor < 0) throw new Error('Invalid stream reset');
      this.cursor = frame.data.cursor;
      for (const entry of this.listeners) { entry.queue = []; void this.sync(entry, true); }
    } else if (frame.event === 'shell') {
      const item = frame.data;
      if (!Number.isSafeInteger(item?.sequence) || String(item.sequence) !== frame.id) throw new Error('Invalid event cursor');
      if (this.cursor != null && item.sequence <= this.cursor) return;
      for (const entry of this.listeners) {
        if (item.conversation_id !== entry.scope.conversation_id || item.space_id !== entry.scope.space_id) continue;
        entry.receivedAt = performance.now();
        if (entry.syncing || !entry.head || entry.needsSync) {
          // Bound a slow-reader queue. The durable head supersedes older fragments.
          entry.queue.push(item);
          if (entry.queue.length > 128) { entry.queue = []; entry.resync = true; }
          void this.sync(entry);
        } else {
          try { entry.head = reduceProjection(entry.head, item); this.notify(entry); }
          catch { entry.queue.push(item); void this.sync(entry); }
        }
      }
      this.cursor = item.sequence;
    } else if (frame.event === 'heartbeat') {
      for (const entry of this.listeners) if (!entry.head || entry.resync || entry.needsSync) void this.sync(entry);
    } else throw new Error('Unknown stream frame');
  }
  async run() {
    let attempt = 0;
    while (!this.stopped) {
      this.controller = new AbortController();
      let watchdog, retryAfter = 0;
      const connectedAt = Date.now();
      const touch = () => { this.lastBytesAt = Date.now(); clearTimeout(watchdog); watchdog = setTimeout(() => this.controller?.abort(), this.silenceMs); };
      try {
        touch();
        const response = await this.open(this.cursor, this.controller.signal);
        for await (const frame of sseFrames(response.body, touch)) {
          if (this.stopped) break;
          this.receive(frame); this.status('connected');
        }
        if (!this.stopped) throw new Error('Observation stream ended');
      } catch (error) {
        if (this.stopped) break;
        if ([401, 403].includes(error.status)) { this.status('reauth_required'); break; }
        if ([404, 501].includes(error.status)) { this.status('unavailable'); break; }
        retryAfter = Math.max(0, Number(error.retryAfter) || 0) * 1000;
        this.status('reconnecting');
      } finally { clearTimeout(watchdog); this.controller.abort(); }
      if (Date.now() - connectedAt >= 30_000) attempt = 0;
      if (!this.stopped) await new Promise(resolve => {
        this.wake = resolve;
        this.retryTimer = setTimeout(resolve, Math.max(retryAfter, reconnectDelay(attempt++, this.random)));
      });
    }
  }
  resume() {
    if (this.stopped || ['reauth_required', 'unavailable'].includes(this.state)) return;
    // Browser sleep freezes timers. On wake/online, reconnect only observation
    // using the existing cursor and repair each currently visible snapshot.
    if (this.lastBytesAt != null && Date.now() - this.lastBytesAt >= this.silenceMs) this.controller?.abort();
    clearTimeout(this.retryTimer); this.wake?.();
    for (const entry of this.listeners) void this.sync(entry, true);
  }
  close() {
    this.stopped = true; this.controller?.abort(); clearTimeout(this.retryTimer); this.wake?.();
    for (const entry of this.listeners) { entry.active = false; entry.syncController?.abort(); clearTimeout(entry.timer); clearTimeout(entry.syncRetryTimer); }
    this.listeners.clear();
  }
}
