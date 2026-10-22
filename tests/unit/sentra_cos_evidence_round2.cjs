/* Hermetic DOM/React fixture for the production MAIN-world evidence reader.
 * Node is ONLY the test harness, not a QuickJS/Code Mode fallback. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const source = fs.readFileSync(path.resolve(__dirname,
  "../../edge_extension/conversation-evidence.js"), "utf8");
const chatId = "conversation-123456789";
const nonce = "nonce-123456789";

function inspect(messages, route = chatId) {
  const root = {tag: 3, child: null, return: null, memoizedProps: {}};
  root.stateNode = {current: root};
  const child = {tag: 5, return: root, memoizedProps: {
    conversationId: chatId, messages
  }};
  root.child = child;
  const element = {"__reactFiber$test": child};
  const context = {
    crypto: {randomUUID: () => "document-123456789"},
    location: {origin: "https://chatgpt.com", pathname: "/c/" + route},
    document: {
      querySelectorAll: () => [element],
      querySelector: selector => selector.includes("composer-input") ? {} : null
    }
  };
  context.globalThis = context;
  vm.runInNewContext(source, context, {timeout: 1000});
  return context.__sentraConversationEvidence.observe(nonce);
}
const first = {id: "message-11111111", author:{role:'user'}, metadata: {request_id: "request-11111111"}};
const other = {id: "message-22222222", author:{role:'user'}, metadata: {request_id: "request-11111111"}};
const reuse = {id: "message-11111111", author:{role:'user'}, metadata: {request_id: "request-33333333"}};
const ok = inspect([first, first]);
assert.ok(ok);
assert.equal(ok.requests.length, 1);
assert.equal(ok.requests[0].message_id, "message-11111111");
assert.equal(ok.state, "idle");
for(const role of ['assistant','tool',undefined])assert.equal(inspect([{...first,author:{role}}]).requests.length,0);
assert.equal(inspect([first, other]), null);
assert.equal(inspect([first, reuse]), null);
assert.equal(inspect([first], "conversation-other-123"), null);
console.log("sentra MAIN-world evidence fixture passed");
