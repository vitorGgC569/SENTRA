import React from 'react';

const labels = {
  sending: 'Enviando…',
  created: 'Ainda não iniciado', active: 'Ativo', starting: 'Iniciando', available: 'Disponível', stopped: 'Parado', revoked: 'Revogado', expired: 'Expirado',
  connected: 'Viewer conectado', connecting: 'Conectando viewer', closed: 'Viewer desconectado',
  queued: 'Solicitado', dispatched: 'Entregue ao Dot', waiting_approval: 'Aguardando aprovação',
  waiting_chatgpt_user_approval: 'Aguardando aprovação no ChatGPT', uncertain: 'Resultado ainda não confirmado',
  pending: 'Solicitado', running: 'Em execução', paused: 'Interrompido', cancelled: 'Cancelado',
  failed: 'Falhou', completed: 'Resultado registrado', succeeded: 'Resultado registrado', ready: 'Disponível', idle: 'Ocioso',
  requested:'Solicitado',delivered:'Entregue ao Dot',waiting_confirmation:'Aguardando confirmação',verified:'Concluído e verificado',
  interrupted: 'Interrompido', not_sent: 'Não enviado', unconfirmed: 'Envio não confirmado', sent: 'Enviado',
};
export function Status({ value }) {
  return <span className="shell-status" data-state={String(value || 'unknown').toLowerCase()}>{labels[String(value).toLowerCase()] || value || 'Estado não informado'}</span>;
}
export function OperationReceipt({ value }) {
  if (!value) return null;
  return <div className="shell-receipt">{value.role==='assistant'&&value.receipt_id&&!['uncertain','unconfirmed'].includes(value.status)?<span className="shell-status">Resposta recebida</span>:<Status value={value.task_lifecycle?.stage || value.lifecycle?.stage || value.status || value.state} />}
    {value.reason && <p className="shell-delivery-reason" role="status">{value.reason}</p>}
    {value.handoff_recorded && <span>Troca de posse registrada · epoch {value.epoch}</span>}
    {value.receipt_id && <span className="shell-receipt-confirmed">Recibo registrado</span>}
    {(value.operation_id || value.work_item_id || value.receipt_id || value.run_id) && <details>
      <summary>Detalhes da operação</summary><dl>
        {value.task_verification&&<><dt>Evidência</dt><dd>Integridade dos arquivos conferida no instante registrado.</dd><dt>Arquivos</dt><dd>{value.task_verification.files.map(f=>f.path).join(', ')}</dd></>}
        {['run_id', 'work_item_id', 'operation_id', 'receipt_id'].filter(key => value[key]).map(key =>
          <React.Fragment key={key}><dt>{key}</dt><dd>{value[key]}</dd></React.Fragment>)}
      </dl></details>}
  </div>;
}
export function EventList({ items = [] }) {
  return <ol className="shell-events">{items.map(event => <li key={event.event_id || event.id}>
    <div><strong>{event.kind || event.type || 'Atividade'}</strong><time>{event.created_at ? new Date(event.created_at).toLocaleString('pt-BR') : ''}</time></div>
    {event.payload?.summary && <p>{event.payload.summary}</p>}
    {(event.payload?.status || event.payload?.operation_id) && <OperationReceipt value={event.payload} />}
    <details><summary>Registro</summary><pre>{JSON.stringify(event, null, 2)}</pre></details>
  </li>)}</ol>;
}
