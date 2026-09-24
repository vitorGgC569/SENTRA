/** Reuse the pinned upstream's journal/snapshot/rollback implementation for Codex. */
import { loadConfig } from "../../third_party/codex-chatgpt-web/src/config";
import {
  deactivateCodexIntegration,
  inspectCodexIntegration,
  installCodexIntegration,
} from "../../third_party/codex-chatgpt-web/src/codex-integration";

const [action = "status", rawPort = "17842"] = process.argv.slice(2);
const port = Number(rawPort);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("invalid gateway port");
const origin = `http://127.0.0.1:${port}`;
const gatewayRoute = `${origin}/v1`;

async function gatewayHealthy(): Promise<boolean> {
  try {
    const health = await fetch(`${origin}/healthz`, { signal: AbortSignal.timeout(5000) });
    if (!health.ok) return false;
    const body = await health.json() as { service?: unknown };
    return body.service === "sentra-model-gateway";
  } catch {
    return false;
  }
}

if (action === "status") {
  const status = inspectCodexIntegration();
  console.log(JSON.stringify({
    ...status,
    gatewayRoute,
    gatewayHealthy: await gatewayHealthy(),
    pointsToSentra: status.routeUrl === gatewayRoute,
  }, null, 2));
} else if (action === "disconnect") {
  console.log(JSON.stringify(deactivateCodexIntegration(), null, 2));
} else if (action === "install") {
  if (!await gatewayHealthy()) {
    throw new Error("SENTRA Model Gateway is not healthy");
  }
  const config = loadConfig();
  const result = installCodexIntegration(
    { ...config, host: "127.0.0.1", port },
    { replaceExistingRoute: true },
  );
  const status = inspectCodexIntegration();
  if (!status.installed || !status.active || status.routeUrl !== gatewayRoute) {
    throw new Error("Codex route transaction completed but did not point to the SENTRA Gateway");
  }
  console.log(JSON.stringify({
    active: true,
    route: gatewayRoute,
    journal: result.version,
    pointsToSentra: true,
    codexRestartRequired: true,
  }, null, 2));
  console.error("Restart Codex to refresh its model catalog.");
} else {
  throw new Error("usage: bun run integrations/codex_chatgpt_web/codex_route.ts <status|install|disconnect> [gateway-port]");
}
