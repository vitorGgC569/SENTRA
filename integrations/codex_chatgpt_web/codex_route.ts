/** Reuse the pinned upstream's journal/snapshot/rollback implementation for Codex. */
import {
  deactivateCodexIntegration,
  inspectCodexIntegration,
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
  throw new Error("Native provider routing is not managed by SENTRA. Select Web models in SENTRA instead.");
} else {
  throw new Error("usage: bun run integrations/codex_chatgpt_web/codex_route.ts <status|install|disconnect> [gateway-port]");
}
