"use strict";
const form = document.getElementById("pair");
const token = document.getElementById("token");
const enabled = document.getElementById("enabled");
const status = document.getElementById("status");
chrome.storage.local.get({ oma_relay_token: "", oma_enabled: false }).then((settings) => {
  token.value = settings.oma_relay_token;
  enabled.checked = settings.oma_enabled;
});
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    // Worker identity for pairing diagnostics never receives an actual job.
    const response = await fetch("http://127.0.0.1:8765/auth/check", {
      headers: { Authorization: `Bearer ${token.value.trim()}` }, signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("relay indisponível");
    await chrome.storage.local.set({ oma_relay_token: token.value.trim(), oma_enabled: enabled.checked });
    status.textContent = "Pareamento confirmado e configuração salva.";
  } catch (error) { status.textContent = String(error); }
});
