export function rowsInSpace(rows, projectId, spaceId) {
  return (rows || []).filter(row => row.project_id === projectId && row.space_id === spaceId);
}

export function canvasNavigation(dot) {
  return { view: 'canvas', project_id: dot.project_id, space_id: dot.space_id,
    dot_id: dot.canvas_root_dot_id || dot.dot_id, conversation_id: null };
}

export function confirmedConversation(value, request) {
  return Boolean(value && value.status !== 'uncertain' && typeof value.conversation_id === 'string'
    && value.conversation_id && value.project_id === request.project_id
    && value.space_id === request.space_id && value.dot_id === request.dot_id);
}
