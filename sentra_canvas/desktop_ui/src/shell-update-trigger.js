// Presentation-only decision. Detection and execution belong to trusted Python.
export function classifyLocalUpdateOffer(value) {
  if (!value || value.kind !== 'local_checkout_code' || value.available !== true ||
      value.installed_update_available !== false ||
      !['apply_full_updates', 'apply_code_updates'].includes(value.action) ||
      typeof value.revision !== 'string' || !/^\d+:\d+$/.test(value.revision)) return null;
  // Do not label a code compilation as an installed signed release.
  if (value.action === 'apply_full_updates' && value.backend_changed !== true) return null;
  if (value.action === 'apply_code_updates' && value.frontend_stale !== true) return null;
  return {
    revision: value.revision,
    action: value.action,
    title: 'Atualização do código disponível',
    explanation: value.action === 'apply_full_updates'
      ? 'Alterações nos serviços locais. É necessário atualizar o Canvas com segurança.'
      : 'Alterações na interface local. Uma recompilação permite usar o novo código.',
    installedRelease: false,
  };
}

// Compatibility with a native window opened before check_update_notification
// was added. This detects only stale frontend assets, never guesses that the
// persistent Python services or signed installed EXE need replacement.
export function legacyFrontendOffer(status) {
  if (!status || status.frontend_stale !== true ||
      typeof status.frontend_source_time_ns !== 'number' ||
      typeof status.bundle_time_ns !== 'number') return null;
  return classifyLocalUpdateOffer({
    kind: 'local_checkout_code', available: true,
    installed_update_available: false, action: 'apply_code_updates',
    frontend_stale: true, backend_changed: false,
    revision: String(status.frontend_source_time_ns) + ':' + String(status.bundle_time_ns),
  });
}

export function shouldShowUpdateNotice(offer, dismissedRevision) {
  return Boolean(offer && offer.revision !== dismissedRevision);
}
