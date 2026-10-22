import { islandSessions, islandClock } from './shell-island-state.js';
import { validatedExecutionIsWorking } from './dot-motion.js';
// Project only display metadata, never prompts, commands, keys or tool arguments.
function actionLabel(event) {
  const kind = String(event?.kind || '').toLowerCase();
  if (/approval|permission|access.*request/.test(kind)) return 'Solicitação de acesso';
  if (/terminal/.test(kind)) return 'Atividade no terminal';
  if (/file|document/.test(kind)) return 'Trabalhando com arquivos';
  if (/browser|computer/.test(kind)) return 'Atividade no computador';
  if (/delegat|handoff|coordinat/.test(kind)) return 'Coordenando trabalho';
  if (/message|conversation/.test(kind)) return 'Atualização na conversa';
  if (/fail|error/.test(kind)) return 'Uma etapa precisa de atenção';
  if (/receipt|verif/.test(kind)) return 'Resultado registrado';
  if (/task|work_item|operation/.test(kind)) return 'Atualização do trabalho';
  return 'Atividade do projeto';
}
export function desktopProjection({ enabled, projectId, projectName, dots, conversations, events = [], decisions,
  observedAt, connected }) {
  const sessions = islandSessions({ dots, conversations, events: [], limit: 64 });
  const rows = [...events].sort((a, b) => (b.seq || 0) - (a.seq || 0));
  return { schema: 1, enabled: enabled === true, projectId, projectName, observedAt,
    connected: connected === true, decisions: Number.isInteger(decisions) ? decisions : 0,
    sessions: sessions.map(row => {
      const event = rows.find(event => (event?.payload?.dot_id || event?.dot_id) === row.dotId ||
        (event?.payload?.agent_id && event.payload.agent_id === row.dot?.agent_id));
      return { dotId: row.dotId, conversationId: row.conversationId || '', spaceId: row.spaceId || '',
        name: row.name, mascot: row.mascot || '',
        tone: row.tone === 'work' && !validatedExecutionIsWorking(row.dot?.execution) ? 'idle' : row.tone,
        workingValidated: validatedExecutionIsWorking(row.dot?.execution), label: row.label,
        detail: event && ['work', 'wait'].includes(row.tone) ? actionLabel(event) : row.detail };
    }),
    events: rows.slice(0, 12).map((event, index) => ({ id: String(event.event_id || event.seq || index),
      label: actionLabel(event), dotId: event?.payload?.dot_id || event?.dot_id || '',
      time: islandClock(event.created_at || event.timestamp) })),
  };
}
