'use strict';
// Candidate Host/control-server in a real, hidden Electron process. Every https
// response belongs to an isolated protocol fixture; no account/network session.
const { app, BrowserWindow, session } = require('electron');
const assert = require('node:assert/strict');
const path = require('node:path');
const { createHash, randomBytes } = require('node:crypto');
const sha = s => createHash('sha256').update(s).digest('hex');
const tree = process.env.SENTRA_BROWSER_QA_TREE;
const timer = setTimeout(() => { console.error('Host Electron QA timeout'); app.exit(5); }, 20000);
app.whenReady().then(async () => {
  let server, window;
  try {
    const { BrowserHost } = require(path.join(tree, 'launcher/electron/browser-host.cjs'));
    const { BrowserControlServer } = require(path.join(tree, 'launcher/electron/control-server.cjs'));
    const partition = 'sentra-message-host-qa-' + randomBytes(12).toString('hex');
    const isolated = session.fromPartition(partition);
    isolated.protocol.handle('https', request => new Response(
      request.url === 'https://chatgpt.com/c/qa-conversation' ? '<!doctype html><article data-message-id="qa-anchor"></article>' : '',
      { status: request.url === 'https://chatgpt.com/c/qa-conversation' ? 200 : 403, headers: { 'Content-Type': 'text/html' } }));
    window = new BrowserWindow({ show: false, webPreferences: { partition, nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true } });
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    await window.loadURL('https://chatgpt.com/c/qa-conversation');
    const prefs = window.webContents.getLastWebPreferences();
    assert.equal(prefs.nodeIntegration, false); assert.equal(prefs.contextIsolation, true); assert.equal(prefs.sandbox, true);
    assert.equal(isolated.isPersistent(), false); assert.notEqual(isolated, session.defaultSession);
    assert.equal(await window.webContents.executeJavaScript('typeof require'), 'undefined');
    const doc = { document_id: 'a'.repeat(32), identity_epoch: 'b'.repeat(32), surface_id: 'qa-host-surface' };
    await window.webContents.executeJavaScript(`(() => {
      Object.defineProperty(globalThis,'__SENTRA_WEB_DOCUMENT__',{value:Object.freeze(${JSON.stringify(doc)}),writable:false});
      const messages = [
        {id:'qa-user-message',author:{role:'user'},metadata:{request_id:'qa-user-request'},content:{parts:['prompt fixture']},status:'finished_successfully'},
        {id:'qa-assistant-message',author:{role:'assistant'},parent_id:'qa-user-message',metadata:{revision:1},content:{parts:['partial fixture']},status:'in_progress'}
      ];
      const root = {tag:3,stateNode:{},memoizedProps:{}}; root.stateNode.current=root;
      const child={memoizedProps:{conversationId:'qa-conversation',messages},return:root};root.child=child;
      document.querySelector('article').__reactFiber$qa=child;globalThis.qaMessages=messages;
    })()`, false);
    const tab = { id: 'qa-host-tab', traceId: 'qa-host-trace', surfaceId: doc.surface_id, status: 'running', interactionMode: 'automatic',
      sentraDocument: doc, view: { webContents: window.webContents } };
    const host = Object.assign(Object.create(BrowserHost.prototype), { turnTabs: new Map([[tab.id, tab]]), profile: 'development', partition, authenticationRevision: 0 });
    server = new BrowserControlServer({ logger: { info() {}, warn() {}, error() {} }, getPreferences: () => ({}), getBrowserHost: () => host });
    await server.start();
    const descriptor = server.descriptor();
    const post = async (route, data) => {
      const response = await fetch(descriptor.endpoint + '/v1/sentra/' + route, { method: 'POST', headers: {
        authorization: 'Bearer ' + descriptor.token, 'content-type': 'application/json' }, body: JSON.stringify(data) });
      assert.equal(response.status, 200); return response.json();
    };
    const expected = { traceId: tab.traceId, ...doc, conversation_id: 'qa-conversation', message_id: 'qa-assistant-message', expected_role: 'assistant',
      observed_request_id: 'qa-user-request', parent_user_message_id: 'qa-user-message', body_sha256: sha('partial fixture'), complete: false };
    const challenge = await post('message-challenge', expected);
    const observed = await post('message-snapshot', { challenge_id: challenge.challenge_id });
    assert.equal(observed.matched, true); assert.equal(observed.role, 'assistant'); assert.equal(observed.parent_user_message_id, 'qa-user-message');
    assert.equal(observed.observed_request_id, 'qa-user-request'); assert.equal(observed.host_revision, 1);
    assert.equal(observed.account_verified, false); assert.equal(observed.approval_state, 'UNKNOWN'); assert.equal(observed.body_sha256, expected.body_sha256);
    const replay = await post('message-snapshot', { challenge_id: challenge.challenge_id });
    assert.equal(replay.state, 'UNKNOWN'); assert.equal(replay.matched, false);
    const changing = await post('message-challenge', expected);
    await window.webContents.executeJavaScript("qaMessages[1].content.parts=['changed fixture']; true", false);
    const denied = await post('message-snapshot', { challenge_id: changing.challenge_id });
    assert.equal(denied.state, 'UNKNOWN'); assert.equal(denied.reason, 'body_changed');
    await server.close(); server = null; window.destroy(); window = null;
    console.log('SENTRA_MESSAGE_HOST_ELECTRON_OK'); clearTimeout(timer); app.quit();
  } catch (error) {
    console.error(error.message); await server?.close(); window?.destroy(); clearTimeout(timer); app.exit(6);
  }
});
