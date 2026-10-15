import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sseFrames, reduceProjection, reconnectDelay, ProjectFeed } from '../src/shell-stream-transport.js';

const encoder = new TextEncoder();
function frame(event, data, id) {
  return (id == null ? '' : `id: ${id}\n`) + `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}
function observation(sequence, text, kind = 'snapshot', base = 0, conversation = 'c') {
  return { sequence, conversation_id: conversation, space_id: 's', operation_id: 'op',
    kind, base_sequence: base, text, preview: { operation_id: 'op', status: 'generating', authoritative: true } };
}
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check) {
  for (let i = 0; i < 250; i++) { if (check()) return; await wait(10); }
  throw new Error('Condition not reached');
}

test('fragmented UTF-8, CRLF, multiline data and multiple frames survive network boundaries', async () => {
  const text = ': comment\r\nevent: shell\r\nid: 1\r\ndata: {"text":\r\ndata: "Olá 🪐 haha"}\r\n\r\n' + frame('heartbeat', { cursor: 1 });
  const bytes = encoder.encode(text);
  const stream = new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  } });
  const events = [];
  for await (const event of sseFrames(stream)) events.push(event);
  assert.equal(events.length, 2);
  assert.equal(events[0].data.text, 'Olá 🪐 haha');
  assert.equal(events[1].event, 'heartbeat');
});

test('partial event and oversized frame cannot masquerade as a successful stream', async () => {
  for (const payload of ['event: shell\ndata: {"text":"unfinished"}', 'data: ' + 'x'.repeat(2_000_001)]) {
    const stream = new ReadableStream({ start(c) { c.enqueue(encoder.encode(payload)); c.close(); } });
    await assert.rejects(async () => { for await (const ignored of sseFrames(stream)) void ignored; });
  }
});

test('ordered deltas preserve repeated text, reject gaps and cannot confer authority', () => {
  const one = reduceProjection(null, observation(1, 'ha'));
  const two = reduceProjection(one, observation(2, 'ha', 'delta', 1));
  assert.equal(two.content, 'haha');
  assert.equal(two.authoritative, false);
  assert.equal(two.automatic_retry, false);
  assert.equal(reduceProjection(two, observation(1, 'old')), two);
  assert.throws(() => reduceProjection(two, observation(4, 'gap', 'delta', 3)), /gap/);
  assert.equal(reduceProjection(two, observation(5, 'replacement')).content, 'replacement');
});

test('bounded astral windows retain immutable overflow references across cursor updates', async () => {
  const event=observation(1,'🪐'.repeat(65536));
  event.preview={...event.preview,truncated:true,content_offset:34464,content_ref:{
    reference_id:'stream-original',action:'stream_content',total_chars:100000,
    total_utf8_bytes:400000,sha256:'a'.repeat(64),page_max_chars:65536,page_max_utf8_bytes:262144}};
  const payload=encoder.encode(frame('shell',event,1));
  assert.ok(payload.length<2_000_000);
  const stream=new ReadableStream({start(controller){
    for(let offset=0;offset<payload.length;offset+=4093)controller.enqueue(payload.slice(offset,offset+4093));
    controller.close();
  }});
  let parsed;
  for await(const value of sseFrames(stream))parsed=value.data;
  const first=reduceProjection(null,parsed);
  assert.equal([...first.content].length,65536);
  assert.equal(first.content.length,131072);
  assert.equal(first.content_ref.reference_id,'stream-original');
  const next=observation(2,'','delta',1);
  next.preview={...event.preview,content_offset:34465,content_ref:{...event.preview.content_ref,
    reference_id:'stream-next',total_chars:100001,total_utf8_bytes:400004,sha256:'b'.repeat(64)}};
  const second=reduceProjection(first,next);
  assert.equal(second.content,first.content);
  assert.equal(second.content_ref.reference_id,'stream-next');
  assert.equal(second.sequence,2);
  assert.equal(second.content_offset,34465);
  assert.equal(second.authoritative,false);
  assert.equal(second.automatic_retry,false);
});

test('one feed serves multiple listeners and reconnects by read cursor without resubmission', async () => {
  const opens = [], seen = [], other = [];
  const feed = new ProjectFeed({ random: () => 0, batchMs: 1,
    readHead: async () => ({ status: 'idle', sequence: 0, content: '' }),
    open: async (after, signal) => {
      opens.push(after);
      return { body: new ReadableStream({ start(c) {
        if (opens.length === 1) {
          c.enqueue(encoder.encode(frame('snapshot', { reset: true, cursor: 0, items: [] }) +
            frame('shell', observation(1, 'ha'), 1)));
          c.close();
        } else {
          c.enqueue(encoder.encode(frame('shell', observation(1, 'ha'), 1) +
            frame('shell', observation(2, 'ha', 'delta', 1), 2)));
          signal.addEventListener('abort', () => c.close(), { once: true });
        }
      } }) };
    },
  });
  feed.subscribe({ space_id: 's', conversation_id: 'c' }, { onPreview: value => seen.push(value.content) });
  feed.subscribe({ space_id: 's', conversation_id: 'different' }, { onPreview: value => other.push(value.content) });
  try {
    await until(() => seen.includes('haha'));
    assert.deepEqual(opens, [undefined, 1]);
    assert.ok(!other.some(value => value?.includes('ha')));
    assert.equal(feed.cursor, 2);
  } finally { feed.close(); await feed.task; }
});

test('expired credentials stop read reconnection and backoff remains bounded', async () => {
  let opens = 0;
  const states = [];
  const feed = new ProjectFeed({
    open: async () => { opens++; throw Object.assign(new Error('expired'), { status: 401 }); },
    readHead: async () => ({ status: 'idle', sequence: 0 }),
  });
  feed.subscribe({ conversation_id: 'c' }, { onPreview() {}, onState: state => states.push(state) });
  await feed.task;
  assert.equal(opens, 1);
  assert.equal(states.at(-1), 'reauth_required');
  for (let attempt = 0; attempt < 30; attempt++) assert.ok(reconnectDelay(attempt, () => 1) <= 15000);
  feed.close();
});

test('a gap resynchronizes the scoped snapshot and replaces a superseded round', async () => {
  let current = { status: 'generating', operation_id: 'op', sequence: 1, content: 'old' };
  let reads = 0;
  const seen = [];
  const feed = new ProjectFeed({ batchMs: 1,
    readHead: async scope => { assert.equal(scope.conversation_id, 'c'); reads++; return current; },
    open: (_after, signal) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('closed')))),
  });
  feed.subscribe({ space_id: 's', conversation_id: 'c' }, { onPreview: view => seen.push(view.content) });
  await until(() => seen.includes('old'));
  current = { status: 'generating', operation_id: 'op', sequence: 5, content: 'new' };
  feed.receive({ event: 'shell', id: '5', data: observation(5, 'new', 'delta', 4) });
  await until(() => seen.includes('new'));
  assert.equal(reads, 2);
  feed.close(); await feed.task;
});

test('reset during an older snapshot read forces a fresh snapshot even without another delta', async () => {
  let resolveOld, reads = 0;
  const seen = [];
  const feed = new ProjectFeed({ batchMs: 1,
    readHead: async () => {
      reads++;
      return reads === 1 ? new Promise(resolve => { resolveOld = resolve; }) :
        { status: 'confirming', operation_id: 'op', sequence: 9, content: 'persistido atual' };
    },
    open: (_cursor, signal) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('closed')))),
  });
  feed.subscribe({ space_id: 's', conversation_id: 'c' }, { onPreview: view => seen.push(view.content) });
  feed.receive({ event: 'snapshot', id: '9', data: { reset: true, cursor: 9, items: [] } });
  resolveOld({ status: 'generating', operation_id: 'op', sequence: 1, content: 'antigo' });
  await until(() => seen.includes('persistido atual'));
  assert.equal(reads, 2);
  feed.close(); await feed.task;
});

test('a failed snapshot read retains durable prose and queues deltas until the next head succeeds', async () => {
  let reads = 0, available = true;
  const seen = [], states = [];
  const feed = new ProjectFeed({ batchMs: 1,
    readHead: async () => {
      reads++;
      if (!available) throw new Error('temporary broker outage');
      return { status:'generating',operation_id:'op',sequence:reads === 1 ? 1 : 4,content:reads === 1 ? 'retido' : 'retido recuperado' };
    },
    open: (_after, signal) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('closed')))),
  });
  feed.subscribe({ space_id:'s',conversation_id:'c' }, {onPreview:view => seen.push(view.content),onState:state => states.push(state)});
  try {
    await until(() => seen.includes('retido'));
    feed.status('connected');
    available = false;
    feed.receive({event:'shell',id:'3',data:observation(3,'gap','delta',2)});
    await until(() => states.includes('reconnecting'));
    assert.equal([...feed.listeners][0].head.content, 'retido');
    assert.equal(seen.at(-1), 'retido');
    feed.notify([...feed.listeners][0]);
    await wait(10);
    assert.equal(states.at(-1), 'reconnecting');
    available = true;
    feed.receive({event:'heartbeat',data:{cursor:4}});
    await until(() => seen.includes('retido recuperado'));
    assert.equal([...feed.listeners][0].needsSync, false);
  } finally { feed.close(); await feed.task; }
});

test('a hung snapshot is aborted and retried without blocking subsequent recovery', async () => {
  let reads=0, firstSignal;
  const seen=[];
  const feed = new ProjectFeed({batchMs:1,headTimeoutMs:20,
    readHead: async (_scope, {signal}) => {
      reads++;
      if (reads===1) { firstSignal=signal; return new Promise(() => {}); }
      return {status:'confirming',operation_id:'op',sequence:6,content:'recuperado'};
    },
    open: (_cursor, signal) => new Promise((_resolve,reject) => signal.addEventListener('abort',() => reject(new Error('closed')))),
  });
  feed.subscribe({space_id:'s',conversation_id:'c'}, {onPreview:view => seen.push(view.content)});
  try {
    await until(() => firstSignal.aborted);
    feed.receive({event:'heartbeat',data:{cursor:6}});
    await until(() => seen.includes('recuperado'));
    assert.equal(reads,2);
  } finally {feed.close();await feed.task;}
});

test('resuming observation wakes read backoff using the cursor and preserves the confirmed operation', async () => {
  const opens=[],seen=[];
  const feed = new ProjectFeed({batchMs:1,random:()=>1,
    readHead: async () => ({status:'confirming',operation_id:'op',sequence:8,content:'salvo'}),
    open: async (after, signal) => {
      opens.push(after);
      return {body:new ReadableStream({start(c) {
        if (opens.length===1) {c.enqueue(encoder.encode(frame('snapshot',{reset:true,cursor:8,items:[]})));c.close();}
        else {c.enqueue(encoder.encode(frame('heartbeat',{cursor:8})));signal.addEventListener('abort',()=>c.close(),{once:true});}
      }})};
    },
  });
  feed.subscribe({space_id:'s',conversation_id:'c'}, {onPreview:view=>seen.push(view.content)});
  try {
    await until(() => feed.state==='reconnecting' && feed.retryTimer != null);
    const resumedAt=Date.now();feed.resume();
    await until(() => feed.state==='connected' && opens.length===2);
    assert.ok(Date.now()-resumedAt<250);
    assert.deepEqual(opens,[undefined,8]);
    assert.equal([...feed.listeners][0].head.content,'salvo');
  } finally {feed.close();await feed.task;}
});

test('failed head recovery retries with bounded read backoff without waiting for another heartbeat', async () => {
  let reads=0;const seen=[];
  const feed=new ProjectFeed({batchMs:1,random:()=>0,
    readHead:async()=>{
      if(++reads===1)throw new Error('temporary read failure');
      return {status:'confirming',operation_id:'op',sequence:3,content:'sem perder a resposta'};
    },
    open:(_cursor,signal)=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('closed')))),
  });
  feed.subscribe({space_id:'s',conversation_id:'c'}, {onPreview:view=>seen.push(view.content)});
  try{
    await until(()=>seen.includes('sem perder a resposta'));
    assert.equal(reads,2);
  }finally{feed.close();await feed.task;}
});
