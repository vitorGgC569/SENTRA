// Trusted regression harness. The candidate may edit ONLY content-script.js.
// Node VM is a DOM test double, NOT a sandbox; execute this file inside Docker.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('edge_extension/content-script.js', 'utf8');

function environment({initial = '', editable = false, fill = x => x, affordance = 'button', buttonAfterCalls = 0} = {}) {
  let value = initial;
  const sent = [];
  let queries = 0;
  const box = {
    isContentEditable: editable, focus() {}, scrollIntoView() {},
    get value() {return value;}, set value(v) {value = fill(v);},
    get innerText() {return value;}, set textContent(v) {value = fill(v);},
    dispatchEvent(e) {if (e.type === 'keydown' && e.key === 'Enter') submit();},
    closest() {return affordance === 'form' ? form : null;},
  };
  function submit() {sent.push(value); value = '';}
  const button = {disabled: false, click: submit};
  const form = {querySelector() {return button;}, requestSubmit: submit};
  // Relógio virtual: setTimeout avança o tempo (evita spin de 15s reais nos waits).
  let virtualNow = Date.now();
  const VirtualDate = class extends Date {
    static now() {return virtualNow;}
  };
  const context = vm.createContext({
    console, Date: VirtualDate,
    setTimeout: (callback, ms) => {virtualNow += (ms || 0); queueMicrotask(callback); return 1;},
    clearTimeout() {},
    window: {location: {href: 'https://chatgpt.com/', pathname: '/'}},
    document: {
      body: {innerText: ''},
      querySelectorAll(selector) {
        queries++;
        const hydrated = queries > buttonAfterCalls;
        if (!hydrated) return [];
        return affordance === 'button' && selector === "button[data-testid='send-button']" ? [button] : [];
      },
      execCommand(op, _, text) {
        if (op === 'delete') value = '';
        // Imita o editor real: insertText em bloco colapsa \n em espaço
        // (insere no cursor, sem separadores extras).
        if (op === 'insertText') value = fill(value + text.replace(/\n/g, ' '));
        if (op === 'insertLineBreak') value = fill(value + '\n');
        if (op === 'insertParagraph') value = fill(value + '\n\n');
      },
    },
    chrome: {runtime: {onMessage: {addListener() {}}}},
    Event: class {constructor(type, options) {this.type=type; Object.assign(this,options);}},
    InputEvent: class {constructor(type, options) {this.type=type; Object.assign(this,options);}},
    KeyboardEvent: class {constructor(type, options) {this.type=type; Object.assign(this,options);}},
    OMA_SELECTORS: {composer: [], assistantMessages: [], stopButton: []},
    omaQueryFirst: () => box, omaIsVisible: () => true, omaGenerationFinished: () => true,
    omaLastAssistantText: () => '',
  });
  vm.runInContext(source, context);
  return {context, box, sent};
}

const expected = 'BEGIN ' + 'linha de código αβ 😀\n'.repeat(90) + ' END';
for (const editable of [false, true]) {
  test(`complete unicode multiline prompt sends exactly once (editable=${editable})`, async () => {
    const {context, sent} = environment({editable});
    const result = await context.omaSendMessage(expected);
    assert.equal(result.accepted, true);
    assert.deepEqual(sent, [expected]);
  });
  for (const fill of [s => s.slice(0,1016), s => s ? s+' stale' : '',
                       s => s ? s.slice(0,-1)+'X' : '']) {
    test(`incomplete or contaminated fill must never submit (editable=${editable}, fill=${fill})`, async () => {
      const {context, sent} = environment({editable, fill});
      await assert.rejects(() => context.omaSendMessage(expected));
      assert.deepEqual(sent, []);
    });
  }
}
for (const affordance of ['button','form','enter']) {
  test(`recheck full prompt before ${affordance} submission`, async () => {
    const {context, box, sent} = environment({initial: expected.slice(0,1016), affordance});
    await assert.rejects(() => context.omaSubmitAttempt(box, expected));
    assert.deepEqual(sent, []);
  });
  test(`matching prompt supports ${affordance}`, async () => {
    const {context, box, sent} = environment({initial: expected, affordance});
    assert.equal((await context.omaSubmitAttempt(box, expected)).accepted, true);
    assert.deepEqual(sent, [expected]);
  });
}
test('late hydration: send affordance appearing after fill still submits once', async () => {
  const {context, sent} = environment({editable: true, buttonAfterCalls: 4});
  const result = await context.omaSendMessage(expected);
  assert.equal(result.accepted, true);
  assert.deepEqual(sent, [expected]);
});
test('nbsp-indented composer matches space-indented prompt', async () => {
  const nbsp = expected.replace(/ /g, ' ');
  assert.notEqual(nbsp, expected);
  const {context, box, sent} = environment({initial: nbsp});
  assert.equal((await context.omaSubmitAttempt(box, expected)).accepted, true);
  assert.deepEqual(sent, [nbsp]);
});
test('exotic spaces fail closed (only NBSP is normalized)', async () => {
  const emsp = expected.replace(/ /g, ' ');
  assert.notEqual(emsp, expected);
  const {context, box, sent} = environment({initial: emsp});
  await assert.rejects(() => context.omaSubmitAttempt(box, expected));
  assert.deepEqual(sent, []);
});
test('old draft is cleared before a new message', async () => {
  const {context, sent} = environment({initial:'OLD DRAFT', editable:true});
  await context.omaSendMessage(expected);
  assert.deepEqual(sent, [expected]);
});
