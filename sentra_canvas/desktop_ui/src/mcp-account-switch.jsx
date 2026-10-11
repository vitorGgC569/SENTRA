import React, { useEffect, useState } from 'react';
import { api, route } from './api';

const muted = { fontSize: 12, color: '#abaeb7', lineHeight: 1.6 };
const action = { padding: '9px 12px', borderRadius: 9, border: '1px solid #474950',
  color: '#eeeef0', background: '#26272c', cursor: 'pointer' };

/** ChatGPT-registered MCP client account, not a browser-profile switch. */
export function MCPAccountSwitch({ ws }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  async function refresh() {
    setError('');
    try { setStatus(await api(route('/api/center/mcp-account', { ws }))); }
    catch (e) { setError(e.message); }
  }
  useEffect(() => { setStatus(null); setMessage(''); refresh(); }, [ws]);

  async function submit(actionName) {
    if (busy) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const data = { ws, action: actionName, approve: true };
      if (actionName !== 'begin') data.attempt_id = status.attempt_id;
      const result = await api('/api/center/mcp-account', data);
      setStatus(result);
      setMessage(actionName === 'begin'
        ? 'A troca foi iniciada. Faça a autorização na conta Plus pelo ChatGPT.'
        : actionName === 'mark_steps'
          ? 'Etapas declaradas pelo operador. A identidade da conta ainda precisa de prova independente.'
          : 'Assistente encerrado. Nenhuma conta remota foi desconectada.');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function copyTunnel() {
    if (!status?.tunnel_id) return;
    try {
      await navigator.clipboard.writeText(status.tunnel_id);
      setMessage('ID público do túnel copiado (não é uma chave de acesso).');
    } catch {
      setMessage('Selecione o identificador exibido para copiar manualmente.');
    }
  }

  if (!status && !error) return <p style={muted}>Consultando o vínculo MCP local…</p>;
  return <section aria-label="Trocar conta do plugin MCP" style={{
    marginTop: 15, paddingTop: 14, borderTop: '1px solid #393a40',
    display: 'grid', gap: 11 }}>
    <strong style={{ fontSize: 13 }}>Trocar conta do SENTRA MCP</strong>
    <p style={{ ...muted, margin: 0 }}>
      Este procedimento migra a conexão do <strong>plugin no ChatGPT</strong>, não o perfil do
      navegador nem a chave da OpenAI Platform. A autorização é feita na conta Plus por você.
    </p>
    {status && <div style={{ display: 'grid', gap: 5, fontSize: 12 }}>
      <span style={{ color: status.tunnel_configured ? '#b5d5c6' : '#e3b59d' }}>
        {status.tunnel_configured
          ? 'Túnel MCP atual: configurado; será reutilizado'
          : 'Túnel MCP não configurado — conclua a conexão inicial do SENTRA'}
      </span>
      <span style={{ color: '#dbbf90' }}>Conta e plano ativos: não verificados</span>
      {status.active && <span style={{ color: '#c5c5cc' }}>
        Destino solicitado: ChatGPT Plus · {status.operator_steps_completed
          ? 'etapas marcadas como concluídas' : 'aguardando autorização do proprietário'}
      </span>}
      {status.new_mcp_activity_observed && <span role="status" style={muted}>
        Nova atividade MCP observada no túnel após o início. Ela NÃO identifica a conta ou o plano.
      </span>}
    </div>}

    {status?.tunnel_configured && !status.active && <button type="button"
      style={{ ...action, background: '#3c4048' }} disabled={busy}
      onClick={() => submit('begin')}>Trocar para a conta Plus</button>}

    {status?.active && <>
      <div style={{ display: 'grid', gap: 5 }}>
        <small style={muted}>ID público do túnel existente — nunca compartilhe a chave de execução:</small>
        <code style={{ padding: 8, background: '#1c1d21', borderRadius: 7,
          overflowWrap: 'anywhere', fontSize: 11 }}>{status.tunnel_id || 'Indisponível'}</code>
        <button type="button" style={action} disabled={busy}
          onClick={copyTunnel}>Copiar ID do túnel</button>
      </div>
      <ol style={{ ...muted, paddingLeft: 19, margin: '0 0 0 2px' }}>
        <li>Na conta ChatGPT <strong>Plus</strong>, abra Configurações → Plugins e localize SENTRA.</li>
        <li>Conecte ou instale o plugin nessa conta. Revise as permissões e, se solicitado, reutilize o túnel acima.</li>
        <li>Na conta Free, desconecte SENTRA separadamente para revogar aquela conexão.</li>
        <li>Execute uma chamada de teste com SENTRA pela conta Plus e confira a atividade abaixo.</li>
      </ol>
      <button type="button" style={{ ...action, background: '#353842' }}
        onClick={() => window.open('https://chatgpt.com/', '_blank', 'noopener,noreferrer')}>
        Abrir gerenciamento no ChatGPT
      </button>
      <button type="button" style={action} disabled={busy || status.operator_steps_completed}
        onClick={() => submit('mark_steps')}>Já conectei na Plus</button>
      <button type="button" style={action} disabled={busy}
        onClick={() => submit('cancel')}>Encerrar assistente</button>
    </>}

    <button type="button" style={action} disabled={busy}
      onClick={refresh}>Verificar conexão local</button>
    {status?.operator_steps_completed && <small style={muted} role="status">
      Sua confirmação foi registrada. Sem uma identidade de conta autenticada no serviço,
      o SENTRA não pode afirmar que o plugin usa Plus nem que o acesso da Free foi revogado.
    </small>}
    {message && <p role="status" style={{ ...muted, color: '#b2d6c2', margin: 0 }}>{message}</p>}
    {error && <p role="alert" style={{ ...muted, color: '#ffaaa3', margin: 0 }}>{error}</p>}
  </section>;
}
