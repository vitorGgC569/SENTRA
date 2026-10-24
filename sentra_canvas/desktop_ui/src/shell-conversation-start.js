import { conversationInstant } from './shell-dates.js';

export function conversationTitleFromMessage(text) {
  const words = String(text || '').trim().replace(/\s+/gu, ' ').split(' ').filter(Boolean);
  if (!words.length) return 'Nova conversa';
  const title = words.slice(0, 8).join(' ');
  const chars = Array.from(title);
  return chars.length > 72 ? chars.slice(0, 69).join('').trimEnd() + '…' : title;
}

export function matchesConversationStart(start, scope) {
  return Boolean(start?.id && start.content?.trim()
    && start.project_id === scope.project_id && start.space_id === scope.space_id
    && start.conversation_id === scope.conversation_id);
}

export function homeAttachmentError(file) {
  if (!file?.size) return 'Escolha um arquivo que tenha conteúdo.';
  const image = file.type?.startsWith('image/') || /\.(png|jpe?g)$/i.test(file.name || '');
  if (file.size > (image ? 8 : 20) * 1024 * 1024) return image ? 'A imagem deve ter até 8 MiB.' : 'O documento deve ter até 20 MiB.';
  return '';
}

export function recentStartConversations(rows, limit = 5) {
  return [...rows].sort((a, b) => (conversationInstant(b.updated_at || b.created_at) || 0)
    - (conversationInstant(a.updated_at || a.created_at) || 0)).slice(0, limit);
}
