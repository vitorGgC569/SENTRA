/** Cumulative ShellLivePreviews.view. Equal new characters survive ha → haha. */

const UNCERTAIN = 'Entrega incerta. Não reenvie.';
const COORDINATING = 'Coordenando';
const RECEIVING = 'Recebendo resposta';
const CONFIRMING = 'Confirmando entrega';
const PROVIDER = 'Aguardando ChatGPT';
const RECONNECTING = 'Reconectando conexão';
const WAITING_MODEL = 'Aguardando modelo';
const TOOL_RESULT = 'Resultado da ferramenta recebido';
const TOOL_CALL = /^Executando ferramenta [\u0000-\u007F]{0,48}$/;

function suffix(next, previous) {
  if (typeof next !== 'string' || !next) return '';
  if (typeof previous !== 'string' || !next.startsWith(previous)) return next;
  return next.slice(previous.length);
}

function kindOf(activity) {
  if (activity === UNCERTAIN) return 'uncertain';
  if (activity === COORDINATING) return 'coordinating';
  if (activity === RECEIVING) return 'delta';
  if (activity === CONFIRMING) return 'confirming';
  if (activity === PROVIDER) return 'provider';
  if (activity === RECONNECTING) return 'reconnecting';
  if (activity === TOOL_RESULT || TOOL_CALL.test(activity)) return 'tool';
  if (activity === WAITING_MODEL) return 'standby';
  return 'other';
}

export function feedMotion(view = {}, previous = {}) {
  const base = {
    resend: false,
    authoritative: false,
    closes_trio: false,
    finalAnswer: false,
    success: false,
    stop: false,
    animate: false,
    fragment: '',
    partial: false,
  };
  const previousContent = typeof previous?.content === 'string' ? previous.content : '';
  if (view?.status === 'interrupted') {
    const kept = typeof view?.content === 'string' ? view.content : '';
    const activity = typeof view?.activity === 'string' && view.activity ? view.activity : UNCERTAIN;
    return {
      ...base,
      status: 'interrupted',
      phase: 'uncertain',
      kind: 'uncertain',
      activity,
      fragment: suffix(kept, previousContent),
      content: kept,
      animate: false,
      stop: true,
      partial: true,
    };
  }
  const status = ['generating', 'confirming', 'preview_unavailable'].includes(view?.status)
    ? view.status
    : 'idle';
  if (status === 'idle') {
    return { ...base, status, phase: 'idle', kind: 'idle', activity: '', content: '' };
  }
  if (status === 'preview_unavailable') {
    return {
      ...base, status, phase: 'preview_unavailable', kind: 'unavailable',
      activity: '', content: typeof view?.content === 'string' ? view.content : '', partial: true,
    };
  }
  const previousActivity = typeof previous?.activity === 'string' ? previous.activity : '';
  // The server masks structured directives before projecting this window.
  // Re-parsing a window would alter legitimate prose and its saved reference.
  const raw = typeof view?.content === 'string' ? view.content : '';
  const added = suffix(raw, previousContent);
  const spaceOnly = added.length > 0 && added.trim() === '';
  let activity = typeof view?.activity === 'string' && view.activity ? view.activity : WAITING_MODEL;
  if (spaceOnly && activity === RECEIVING) activity = previousActivity || WAITING_MODEL;
  const kind = kindOf(activity);
  // Changing provider/activity state cannot erase a previously received answer.
  const content = raw;
  const fragment = added;
  const phase = kind === 'uncertain' ? 'uncertain'
    : kind === 'delta' || kind === 'tool' ? 'executing'
    : kind === 'provider' || kind === 'confirming' || kind === 'reconnecting' ? 'waiting'
    : kind === 'coordinating' ? 'planning'
    : 'standby';
  const sameLabel = previousActivity === activity;
  const stop = kind === 'uncertain';
  const animate = !stop && !spaceOnly && (
    kind === 'delta' ? fragment.length > 0 : !sameLabel && kind !== 'other'
  );
  return {
    ...base,
    status,
    phase,
    kind,
    activity,
    fragment,
    content,
    animate,
    stop,
    partial: true,
  };
}
