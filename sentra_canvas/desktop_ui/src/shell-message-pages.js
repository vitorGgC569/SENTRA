// Observation only; compatibility never repeats message_send or another effect.
export async function readRecentMessagePage(bridge, scope) {
  const fields = { project_id: scope.project_id, space_id: scope.space_id, conversation_id: scope.conversation_id };
  let result, requestedOffset = 0;
  try { result = await bridge({ action: 'message_list', ...fields, tail: true, limit: 50 }); }
  catch (error) {
    if (error.status !== 400) throw error;
    result = await bridge({ action: 'message_list', ...fields, offset: 0, limit: 50 });
  }
  if (result.page?.tail !== true) {
    const total = result.page?.total ?? result.items?.length ?? 0;
    if (!Number.isSafeInteger(total) || total < 0) throw Error('Invalid message page');
    if (total > 50) {
      requestedOffset = total - 50;
      result = await bridge({ action: 'message_list', ...fields, offset: requestedOffset, limit: 50 });
    }
  }
  const total = result.page?.total ?? result.items?.length ?? 0;
  const offset = result.page?.offset ?? requestedOffset;
  if (!Array.isArray(result.items) || result.items.length > 50 ||
      !Number.isSafeInteger(total) || total < 0 || !Number.isSafeInteger(offset) || offset < 0 || offset > total ||
      offset + result.items.length !== total) throw Error('Incomplete recent message page');
  return { ...result, page: { ...result.page, offset, total, tail: true,
    previous_offset: offset > 0 ? Math.max(0, offset - 50) : null } };
}

// Only overlapping/adjacent ranges may be merged. A newer disjoint window
// remains available explicitly while the reader keeps their current position.
export function recentPageDisposition(previous, incoming, following) {
  if (!previous || incoming.total < previous.total) return 'replace';
  if (incoming.offset > previous.total) return following ? 'replace' : 'defer';
  return 'merge';
}
