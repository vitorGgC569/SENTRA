import React, { useEffect, useState } from 'react';
import { shellBridge } from './shell-bridge';
import { Modal } from './primitives';
import { MCPAccountSwitch } from './mcp-account-switch';

/** Evidence, not a claim that ChatGPT account authorization happened. */
export function PluginStatusDialog({ ws, close }) {
  const [proof, setProof] = useState(null), [error, setError] = useState('');
  function refresh() {
    setError('');
    shellBridge({ project_id: ws, action: 'plugin_connection_proof' }).then(setProof).catch(e => setError(e.message));
  }
  useEffect(refresh, [ws]);
  const item = (label, description, ready) => <div style={{
    display: 'grid', gap: 3, padding: '9px 0', borderBottom: '1px solid #35353a' }}>
    <span style={{ fontWeight: 600, fontSize: 13 }}>{label}
      <small style={{ float: 'right', color: ready ? '#88d0b1' : '#a9a9b1' }}>
        {ready ? 'Observado' : 'Pendente'}
      </small></span>
    <small style={{ color: '#a4a4ae' }}>{description}</small>
  </div>;
  return <Modal open onOpenChange={v => { if (!v) close(); }}
    title="Conexão do ChatGPT" description="Etapas verificadas de forma independente, sem inferir autorizações.">
    <div style={{ maxWidth: 460, paddingBottom: 15 }}>
      {item('Secure MCP Tunnel', 'Identidade do túnel configurada neste perfil', proof?.tunnel_configured)}
      {item('Acesso ao MCP', 'Chamadas recebidas pelo servidor deste túnel',
        proof?.mcp_tool_observed)}
      {item('MCP autenticado', 'Há ao menos uma chamada observada com autenticação', proof?.authenticated_tool_observed)}
      {item('Catálogo local do SENTRA',
        proof?.local_schemas?.length
          ? `${proof.local_schemas[0].method_count} ferramentas publicadas · SHA-256 ${proof.local_schemas[0].schema_sha256.slice(0, 12)}…`
          : 'Aguardando inicialização do servidor MCP neste perfil',
        !!proof?.local_schemas?.length)}
      {proof?.local_schema_changed_since_authenticated_call &&
        <p role="status" style={{ fontSize: 12, color: '#d7ac85' }}>
          O catálogo local mudou desde a última chamada autenticada. Confira a
          atualização das ferramentas na conta ChatGPT antes de executar novas ações.
        </p>}
      {item('Plugin na conta ChatGPT', 'Verificação externa na conta ainda necessária', false)}
      {item('Catálogo atualizado no ChatGPT', 'O cache remoto não pode ser validado por uma chamada local', false)}
      <p style={{ fontSize: 12, color: '#a9a9b1' }}>O SENTRA não instala nem autoriza silenciosamente um plugin em sua conta. Conclua a aprovação no ChatGPT e faça uma chamada de teste.</p>
      <div style={{ display: 'flex', gap: 9 }}>
        <button onClick={refresh}>Atualizar</button>
        <button onClick={() => window.open('https://chatgpt.com/', '_blank', 'noopener,noreferrer')}>Abrir ChatGPT</button>
      </div>
      <MCPAccountSwitch ws={ws} />
      {error && <p role="alert" style={{ color: '#ff9d95' }}>{error}</p>}
    </div>
  </Modal>;
}
