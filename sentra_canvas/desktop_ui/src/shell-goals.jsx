import React, { useEffect, useRef, useState } from 'react';
import { Field, Modal } from './primitives';

export function ShellGoalDialog({ scope, dot, bridge, argument = '', onClose, onSend }) {
  const initialObjective = argument.replace(/^set\s+/i, '');
  const [value, setValue] = useState(null), [objective, setObjective] = useState(['status', 'stop'].includes(argument) ? '' : initialObjective);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [pending, setPending] = useState(null);
  const key = useRef(crypto.randomUUID());
  useEffect(() => { let active = true;
    bridge({ action: 'goal_status', ...scope }).then(result => { if (!active) return;
      setValue(result); setObjective(old => old || result.goal?.objective || '');
    }).catch(e => { if (active) setError(e.message); }); return () => { active = false; };
  }, [scope.conversation_id]);
  async function mutate(action, sendAfter = false) {
    if (busy) return; setBusy(true); setError('');
    const request = pending?.request || { action, ...scope, request_key: key.current,
      ...(value?.goal_id ? { goal_id: value.goal_id } : {}), ...(action === 'goal_set' ? { objective: objective.trim() } : {}) };
    try {
      const result = await bridge(request);
      if (result.status === 'uncertain') { setPending({ request, sendAfter }); setError('Resultado ainda não confirmado. Consulte a mesma operação.'); return; }
      setValue(result); setPending(null); key.current = crypto.randomUUID();
      if (pending?.sendAfter || sendAfter) { onSend(request.objective); onClose(); }
    } catch (e) { setError(e.message); if (e.uncertain) setPending({ request, sendAfter }); else key.current = crypto.randomUUID(); }
    finally { setBusy(false); }
  }
  return <Modal open onOpenChange={open => { if (!open && !pending) onClose(); }} busy={busy || Boolean(pending)}
    className="shell-modal" title={'Objetivo de ' + (dot?.name || 'Dot')} description="O objetivo fica salvo nesta conversa e acompanha as próximas mensagens.">
    <form className="shell-form" onSubmit={e => { e.preventDefault(); void mutate('goal_set'); }}>
      <Field label="Objetivo"><textarea autoFocus required maxLength={16000} value={objective} disabled={Boolean(pending)} onChange={e => setObjective(e.target.value)} /></Field>
      {value?.goal && <p role="status">Estado: {value.state === 'ACTIVE' ? 'Ativo' : value.state === 'SUCCEEDED' ? 'Concluído' : value.state === 'CANCELLED' ? 'Interrompido' : value.state}</p>}
      <p className="shell-notice">Salvar define o objetivo. Iniciar envia uma mensagem ao Dot; as próximas etapas podem ser enviadas pela conversa.</p>
      {error && <p className="shell-error" role="alert">{error}</p>}
      {pending ? <button type="button" disabled={busy} onClick={() => mutate(pending.request.action)}>Consultar mesma operação</button> : <>
        {value?.state === 'ACTIVE' && <div className="shell-goal-actions"><button type="button" disabled={busy} onClick={() => mutate('goal_stop')}>Interromper objetivo</button>
          <button type="button" disabled={busy} onClick={() => mutate('goal_complete')}>Marcar como concluído</button></div>}
        <footer><button type="button" disabled={busy} onClick={onClose}>Fechar</button><button disabled={busy || !objective.trim()}>Salvar objetivo</button>
          <button type="button" className="shell-primary" disabled={busy || !objective.trim()} onClick={() => mutate('goal_set', true)}>Salvar e iniciar</button></footer></>}
    </form>
  </Modal>;
}
