import { api } from './api.js';

export function accountSection({ alive, button }) {
  const section = document.createElement('section');
  section.className = 'inspect-field';
  const title = document.createElement('h3'); title.textContent = 'Conta ChatGPT';
  const status = document.createElement('p'); status.setAttribute('role', 'status');
  status.textContent = 'Consultando conexão…';
  const note = document.createElement('p'); note.className = 'center-note';
  note.textContent = 'O login é feito pela janela de autenticação do SENTRA. Cada conversa de um Dot reutiliza seu próprio chat salvo.';
  const actions = document.createElement('div'); actions.className = 'inspect-actions';
  let timer = null, disposed = false;
  async function refresh(action = 'status') {
    if (!alive() || disposed) return;
    try {
      const value = await api('/api/web-models/account', action === 'login' ? { action } : undefined);
      if (!alive() || disposed) return;
      status.textContent = value.authenticated ? 'Conectado · sessão verificada'
        : value.login_open ? 'Conclua o login na janela do SENTRA. A conexão será verificada automaticamente.'
        : value.available ? 'ChatGPT desconectado. Entre para conversar com seus Dots.'
        : 'O serviço de modelos ainda não está disponível.';
      connect.textContent = value.authenticated ? 'Verificar conexão' : 'Conectar ChatGPT';
      if (value.login_open && !value.authenticated) timer = setTimeout(() => refresh(), 4000);
    } catch {
      if (alive() && !disposed) status.textContent = 'Não foi possível verificar a conta. Tente verificar a conexão novamente.';
    }
  }
  const connect = button('Conectar ChatGPT', () => refresh('login'));
  actions.append(connect, button('Verificar conexão', () => refresh()));
  section.append(title, status, actions, note);
  const observer = new MutationObserver(() => {
    if (!section.isConnected) { disposed = true; clearTimeout(timer); observer.disconnect(); }
  });
  queueMicrotask(() => { if (section.isConnected) observer.observe(section.parentNode, { childList: true }); });
  void refresh();
  return section;
}
