"use strict";
const OMA_RELAY = "http://127.0.0.1:8765";
const form = document.getElementById("pair");
const token = document.getElementById("token");
const enabled = document.getElementById("enabled");
const status = document.getElementById("status");

(async () => {
  const manifestVersion = chrome.runtime.getManifest().version;
  const versionState = await chrome.storage.local.get({
    oma_bridge_loaded_version: "",
  });
  if (versionState.oma_bridge_loaded_version !== manifestVersion) {
    await chrome.storage.local.set({
      oma_bridge_loaded_version: manifestVersion,
      oma_pool_size: 1,
    });
    chrome.runtime.reload();
    return;
  }

  const settings = await chrome.storage.local.get({
    oma_relay_token: "",
    oma_enabled: false,
    oma_pool_size: 1,
  });
  token.value = settings.oma_relay_token || "";
  enabled.checked = !!settings.oma_enabled;
})();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const value = token.value.trim();
    const response = await fetch(OMA_RELAY + "/auth/check", {
      headers: { Authorization: "Bearer " + value },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("relay indisponível");
    await chrome.storage.local.set({
      oma_relay_token: value,
      oma_enabled: enabled.checked,
      oma_pool_size: 1,
    });
    status.textContent = "Pareamento confirmado e configuração salva.";
  } catch (error) {
    status.textContent = String(error);
  }
});
