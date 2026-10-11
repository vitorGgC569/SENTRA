// Node native tests for deterministic desktop project UI behavior (no DOM grants).
const test = require('node:test');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const fs = require('node:fs');
const helpers = import(pathToFileURL(path.resolve(
  __dirname, '../../sentra_canvas/desktop_ui/src/project-ux-state.js')).href);

test('docks persist only compact workspace-scoped preference booleans', async () => {
  const h = await helpers;
  const memory = new Map();
  const storage = { getItem: k => memory.get(k), setItem: (k, v) => memory.set(k, v) };
  assert.deepEqual(h.loadProjectDocks(storage, 'ws-1'), { files: true, details: false });
  assert.equal(h.saveProjectDocks(storage, 'ws-1', { files: false, details: true, owner: 'ignored' }), true);
  assert.deepEqual(h.loadProjectDocks(storage, 'ws-1'), { files: false, details: true });
  assert.deepEqual(h.loadProjectDocks(storage, 'ws-2'), { files: true, details: false });
  assert.equal(h.saveProjectDocks(storage, '../../suspicious', { files: false }), false);
  assert.equal(memory.size, 1);
  assert.deepEqual(JSON.parse([...memory.values()][0]), { files: false, details: true });
  assert.deepEqual(h.loadProjectDocks({ getItem: () => { throw Error('denied'); } }, 'ws-1'),
    { files: true, details: false });
});

test('DPI mapping stays in renderer three authorized budgets', async () => {
  const h = await helpers;
  assert.equal(h.dpiForScale(100), 72);
  assert.equal(h.dpiForScale(125), 90);
  assert.equal(h.dpiForScale(150), 108);
  assert.equal(h.dpiForScale(10000), 72);
});

test('SHA watcher UI rejects malformed revisions and distinguishes change', async () => {
  const h = await helpers, before = 'a'.repeat(64), after = 'b'.repeat(64);
  assert.equal(h.nextRevision(before, { sha256: before }), 'same');
  assert.equal(h.nextRevision(before, { source_sha256: after }), 'changed');
  assert.equal(h.nextRevision(before, { sha256: 'invalid' }), 'invalid');
});

test('passive viewer displays only valid bounded PNG data URLs', async () => {
  const h = await helpers, png = 'iVBORw0KGgoAAA==';
  const good = { rendered: true, mime: 'image/png', width: 240, height: 160, image_base64: png };
  assert.equal(h.pngDataUrl(good), 'data:image/png;base64,' + png);
  assert.equal(h.pngDataUrl({ ...good, mime: 'application/pdf' }), null);
  assert.equal(h.pngDataUrl({ ...good, width: 50000 }), null);
  assert.equal(h.pngDataUrl({ ...good, image_base64: '<svg/onload=x>' }), null);
  assert.equal(h.pngDataUrl({ ...good, rendered: false }), null);
});

test('key bindings avoid implicit save: Ctrl+S requests review only', async () => {
  const h = await helpers;
  const key = (k, ctrlKey = true) => ({ key: k, ctrlKey, metaKey: false, altKey: false });
  assert.equal(h.projectShortcut(key('s'), { editing: true }), 'review');
  assert.equal(h.projectShortcut(key('s'), { editing: false }), null);
  assert.equal(h.projectShortcut(key('k')), 'search');
  assert.equal(h.projectShortcut(key('b')), 'files');
  assert.equal(h.projectShortcut(key('i')), 'details');
  assert.equal(h.projectShortcut({ ...key('k'), altKey: true }), null);
  assert.deepEqual(h.filterProjectEntries([{ name: 'Summary.md' }, { name: 'index.py' }], 'summ'), [{ name: 'Summary.md' }]);
});

test('accessibility and reduced motion ship in Vite source', () => {
  const root = path.resolve(__dirname, '../../sentra_canvas/desktop_ui/src/');
  const source = fs.readFileSync(path.join(root, 'project-review-dialog.jsx'), 'utf8');
  const style = fs.readFileSync(path.join(root, 'desktop.css'), 'utf8');
  for (const phrase of ['aria-label="Navegação do PDF"', 'aria-pressed=', 'onKeyDown={arrowNavigation}',
    'aria-label="Página PDF renderizada"', 'role="alert"', 'review_token:', 'decoding="async"']) {
    assert.ok(source.includes(phrase), 'missing accessible/secure UI contract: ' + phrase);
  }
  assert.ok(style.includes('prefers-reduced-motion: reduce'));
  assert.ok(style.includes('forced-colors: active'));
  assert.ok(style.includes('focus-visible'));
});

test('R5 PDF only falls back for explicit unavailable read-only route', async () => {
  const h = await helpers;
  for (const status of [404, 501, 503]) assert.equal(h.isPdfTextFallbackAllowed({status}), true);
  for (const status of [0, 400, 401, 403, 408, 409, 422, 500, 502]) {
    assert.equal(h.isPdfTextFallbackAllowed({status}), false);
  }
  assert.equal(h.isPdfTextFallbackAllowed(new Error('network unavailable')), false);
});

test('R5 PDF visual rejects untrusted owner/workspace/revision envelopes', async () => {
  const h = await helpers;
  const request = {path:'folder/sample.pdf',page:1,dpi:72};
  const good = {read_only:true, grants_created:false, ocr_used:false,
    path:request.path,page:request.page,dpi:request.dpi,pages:2,
    width:40,height:30,source_sha256:'a'.repeat(64),
    mime:'image/png',rendered:true,image_base64:'iVBORw0KGgoAAA=='};
  assert.equal(h.validatedPdfVisualResponse(good,request),'data:image/png;base64,iVBORw0KGgoAAA==');
  for (const mutant of [{path:'../sample.pdf'},{page:2},{dpi:108},{pages:201},
     {source_sha256:'fake'}, {grants_created:true}, {read_only:false},
     {ocr_used:true}, {mime:'application/pdf'}, {image_base64:'<script>'}]) {
    assert.equal(h.validatedPdfVisualResponse({...good,...mutant},request),null);
  }
});
