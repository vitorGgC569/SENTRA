// Inspect an existing send without ever passing its content to a mutation.
export function confirmedMessageRequest(value, original, scope) {
  const message = value?.message;
  return value?.status === 'confirmed' && value.confirmed === true && value.automatic_retry === false &&
    value.request_key === original?.request_key && message?.request_key === original?.request_key &&
    typeof message.message_id === 'string' && message.message_id.length > 0 && message.role === 'user' &&
    ['queued', 'running', 'dispatched', 'waiting_approval', 'not_submitted'].includes(message.status) &&
    ['project_id', 'space_id', 'conversation_id'].every(key => message[key] === scope?.[key] && original?.[key] === scope?.[key]);
}

export async function inspectMessageRequest(bridge, original, scope) {
  if (original?.action !== 'message_send' || typeof original.request_key !== 'string' || !original.request_key ||
      !['project_id', 'space_id', 'conversation_id'].every(key => typeof scope?.[key] === 'string' &&
        scope[key] && original[key] === scope[key])) throw new Error('Escopo original do envio indisponível.');
  const value = await bridge({ action: 'message_request_status', project_id: scope.project_id,
    space_id: scope.space_id, conversation_id: scope.conversation_id, request_key: original.request_key });
  if (value?.confirmed === true && !confirmedMessageRequest(value, original, scope)) {
    throw new Error('A consulta não confirmou a mensagem original.');
  }
  return value;
}
