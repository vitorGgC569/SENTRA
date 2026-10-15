/** Copy already used by the shell. Marks stay still; entry uses SurfaceMotion. */

export const LOADING_COPY = {
  home: 'Consultando seu trabalho…',
  canvas: 'Carregando terminais do Canvas…',
  chat: 'Carregando a conversa…',
  messages: 'Consultando mensagens…',
  documents: 'Consultando documentos…',
};

export function loadingFrame(surface, { reduced = false } = {}) {
  return {
    role: 'status',
    ariaBusy: 'true',
    text: LOADING_COPY[surface] || 'Consultando…',
    reduced: Boolean(reduced),
    marks: 3,
    animation: 'none',
  };
}
