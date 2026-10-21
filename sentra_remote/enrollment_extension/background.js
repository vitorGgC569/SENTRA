"use strict";
const api = globalThis.browser || globalThis.chrome;
const HOST = "com.sentra.enrollment";
let native = null;
let tasks = Promise.resolve();
const owned = new Set();

function trusted(url) {
  try {
    const value = new URL(url);
    return value.origin === "https://platform.openai.com" && !value.username && !value.password &&
      /^\/settings\/organization\/(?:tunnels|api-keys)(?:\/|$)/.test(value.pathname);
  } catch (_) { return false; }
}
async function candidates() {
  return (await api.tabs.query({url: "https://platform.openai.com/*"})).filter(tab => !tab.incognito);
}
async function getOwned(id) {
  if (!Number.isSafeInteger(id) || !owned.has(id)) throw Error("browser_closed");
  try { return await api.tabs.get(id); } catch (_) { throw Error("browser_closed"); }
}
async function removeOwned() {
  const ids = [...owned]; owned.clear();
  await Promise.all(ids.map(id => api.tabs.remove(id).catch(() => {})));
}
async function kernel(command) {
  const tab = await getOwned(command.tab);
  if (!trusted(tab.url) || tab.incognito) throw Error("bridge_origin_changed");
  // Install the static, packaged function into the isolated extension world.
  await api.scripting.executeScript({target: {tabId: tab.id}, files: ["dom.js"]});
  const results = await api.scripting.executeScript({
    target: {tabId: tab.id},
    func: value => globalThis.SentraEnrollmentDom(value), args: [command],
  });
  if (results.length !== 1 || !results[0].result) throw Error("browser_dom_needs_attention");
  const result = results[0].result;
  if (result.ok !== true) throw Error(result.error || "browser_dom_needs_attention");
  return result.result;
}
async function dispatch(command) {
  if (command.operation === "open") {
    const tabs = await candidates();
    // Duplicate the sole Platform tab through the browser's own API. This
    // preserves Firefox containers without reading cookie stores or guessing
    // whether optional Tab.cookieStoreId metadata was exposed.
    if (tabs.length > 1) {
      throw Error("browser_account_selection_required");
    }
    const options = {url: "https://platform.openai.com/settings/organization/tunnels", active: true};
    if (tabs.length) {
      const duplicate = await api.tabs.duplicate(tabs[0].id);
      owned.add(duplicate.id);
      await api.tabs.update(duplicate.id, options);
      return duplicate.id;
    } else {
      const windows = (await api.windows.getAll({windowTypes: ["normal"]})).filter(window => !window.incognito);
      const window = windows.find(window => window.focused) || windows[0];
      if (!window) throw Error("browser_account_selection_required");
      options.windowId = window.id;
    }
    const tab = await api.tabs.create(options);
    owned.add(tab.id);
    return tab.id;
  }
  if (command.operation === "closed") {
    try { await getOwned(command.tab); return false; } catch (_) { return true; }
  }
  const tab = await getOwned(command.tab);
  switch (command.operation) {
    case "url": {
      if (!trusted(tab.url)) return "";
      const value = new URL(tab.url);
      return value.origin + value.pathname;
    }
    case "close": owned.delete(tab.id); await api.tabs.remove(tab.id); return true;
    case "navigate": {
      if (!trusted(command.url)) throw Error("bridge_origin_changed");
      await api.tabs.update(tab.id, {url: command.url});
      const deadline = Date.now() + 30000;
      while (Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 100));
        if ((await getOwned(tab.id)).status === "complete") return true;
      }
      throw Error("bridge_navigation_failed");
    }
    case "dom": case "extract": return kernel(command);
    default: throw Error("browser_dom_needs_attention");
  }
}
const safeErrors = new Set(["browser_closed", "bridge_origin_changed", "bridge_selector_ambiguous",
  "bridge_element_missing", "bridge_element_disabled", "bridge_navigation_failed", "browser_account_selection_required"]);
async function connect() {
  if (native) return;
  const port = api.runtime.connectNative(HOST); native = port;
  port.onMessage.addListener(command => {
    if (typeof command.status === "string") return;
    if (!Number.isSafeInteger(command.id) || command.id <= 0) return;
    tasks = tasks.then(async () => {
      try {
        const result = await dispatch(command);
        port.postMessage({id: command.id, ok: true, result});
      } catch (error) {
        try { port.postMessage({id: command.id, ok: false,
          error: safeErrors.has(error.message) ? error.message : "browser_dom_needs_attention"}); } catch (_) {}
      }
    });
  });
  port.onDisconnect.addListener(() => {
    void api.runtime.lastError;  // Consume the browser's diagnostic without logging it.
    if (native === port) native = null;
    tasks = tasks.then(removeOwned);
  });
  const tabs = await candidates();
  if (native === port) port.postMessage({protocol: 1, platform_tab: tabs.length > 0});
}
api.action.onClicked.addListener(() => void connect().catch(() => {}));
api.runtime.onStartup.addListener(() => void connect().catch(() => {}));
api.runtime.onInstalled.addListener(() => {
  void api.alarms.create("sentra-setup-reconnect", {periodInMinutes: 1});
  void connect().catch(() => {});
});
api.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "sentra-setup-reconnect") void connect().catch(() => {});
});
void connect().catch(() => {});
