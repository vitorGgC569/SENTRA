// Local presentation gate for coordinated native Canvas maintenance.
// Never persists across navigation, never replays work or changes durable receipts.
let updating = false;
export function beginCanvasMaintenance() { updating = true; }
export function endCanvasMaintenance() { updating = false; }
export function canvasMaintenanceActive() { return updating; }
