import { api } from './api.js';

export function accountSection({ alive, button }) {
  const section = document.createElement('section');
  section.className = 'inspect-field';
  const title = document.createElement('h3'); title.textContent = 'Conta ChatGPT';
  const status = document.createElement('p'); status.setAttribute('role', 'status');
  status.textContent = 'Consultando conexão…';
  const note = document.createElement('p'); note.className = 'center-note';
  note.textContent = 'Configurar conexão autoriza criar ou selecionar o túnel e criar uma chave com todas as permissões, sem expiração, protegida neste Windows. Login e autorização do app são confirmados no navegador integrado. Os modelos oficiais mantêm suas configurações.';
  const actions = document.createElement('div'); actions.className = 'inspect-actions';
  let timer = null, disposed = false;
  let verificationPrompt = '';
  async function refresh(action = 'status') {
    if (!alive() || disposed) return;
    try {
      clearTimeout(timer);
      const value = await api('/api/web-models/account', action === 'setup' ? { action, approved: true } : action === 'login' ? { action } : undefined);
      if (!alive() || disposed) return;
      const setup = value.setup || {};
      verificationPrompt = setup.verification_prompt || '';
      copy.hidden = !verificationPrompt;
      configure.disabled = setup.running === true;
      configure.textContent = setup.running ? 'Configurando…' : setup.state === 'needs_attention' ? 'Retomar configuração' : 'Configurar conexão';
      status.textContent = setup.running || setup.state === 'needs_attention' || setup.state === 'verified' ? setup.detail : value.authenticated ? 'Conectado · sessão verificada'
        : value.login_open ? 'Conclua o login na janela do SENTRA. A conexão será verificada automaticamente.'
        : value.available ? 'ChatGPT desconectado. Entre para conversar com seus Dots.'
        : 'O serviço de modelos ainda não está disponível.';
      connect.textContent = value.authenticated ? 'Verificar conexão' : 'Conectar ChatGPT';
      if (setup.running || (value.login_open && !value.authenticated)) timer = setTimeout(() => refresh(), 4000);
    } catch {
      if (alive() && !disposed) status.textContent = 'Não foi possível verificar a conta. Tente verificar a conexão novamente.';
    }
  }
  const connect = button('Conectar ChatGPT', () => refresh('login'));
  const configure = button('Configurar conexão', () => refresh('setup'));
  const copy = button('Copiar teste de conexão', async () => {
    try { await navigator.clipboard.writeText(verificationPrompt); }
    catch { status.textContent = 'Não foi possível copiar. Abra novamente a configuração para continuar o teste.'; }
  });
  copy.hidden = true;
  actions.append(configure, connect, button('Verificar conexão', () => refresh()), copy);
  section.append(title, status, actions, note);
  const observer = new MutationObserver(() => {
    if (!section.isConnected) { disposed = true; clearTimeout(timer); observer.disconnect(); }
  });
  queueMicrotask(() => { if (section.isConnected) observer.observe(section.parentNode, { childList: true }); });
  void refresh();
  return section;
}
