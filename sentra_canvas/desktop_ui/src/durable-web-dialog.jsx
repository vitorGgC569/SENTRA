import React, { useEffect, useRef, useState } from 'react';
import { api, route } from './api';
import { Modal } from './primitives';
import { deliveryView, goalCost, loopRequest } from './durable-web-state';
import { CompactResumePanel } from './compact-resume-panel';

export function DurableWebDialog({ ws, close }) {
  const [messages, setMessages] = useState([]), [goals, setGoals] = useState([]);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [objective, setObjective] = useState('');
  const [limits, setLimits] = useState({ steps: '4', cost: '', seconds: '600' });
  const generation = useRef(0), alive = useRef(true);
  async function refresh(signal) {
    const current = ++generation.current;
    const results = await Promise.allSettled([
      api(route('/api/center/web-delivery', { ws, action: 'list' }), undefined, { signal }),
      api(route('/api/center/goal-loop', { ws, action: 'status' }), undefined, { signal }),
    ]);
    if (!alive.current || current !== generation.current || signal?.aborted) return;
    setMessages(results[0].status === 'fulfilled' && Array.isArray(results[0].value.messages)
      ? results[0].value.messages.map(deliveryView) : []);
    setGoals(results[1].status === 'fulfilled' && Array.isArray(results[1].value.goals) ? results[1].value.goals : []);
    const failures = results.filter(result => result.status === 'rejected').map(result => result.reason.message);
    if (results[0].status === 'fulfilled' && results[0].value.available === false) {
      failures.push('Entrega Web indisponível: ' + (results[0].value.reason || 'autoridade não disponível'));
    }
    setError(failures.join(' · '));
  }
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    setMessages([]); setGoals([]); setError('');
    refresh(controller.signal);
    return () => { alive.current = false; generation.current++; controller.abort(); };
  }, [ws]);
  async function mutate(body) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const result = await api('/api/center/goal-loop', body);
      await refresh();
      const blocked = result.goals?.find(goal => goal.state === 'BLOCKED');
      if (alive.current && blocked) setError('Ação bloqueada: ' + (blocked.block_reason || 'autorização central indisponível'));
    } catch (failure) {
      // No optimistic completion or retry: consult the central journal after uncertain HTTP.
      if (alive.current) setError(failure.message);
    } finally { if (alive.current) setBusy(false); }
  }
  return <Modal open onOpenChange={open => { if (!open) close(); }} title="Entrega Web e objetivos"
    description="Estado confirmado pela autoridade central do workspace. Atualizar consulta o journal sem repetir mensagens.">
    <div className="durable-web-panel" aria-busy={busy}>
      <button disabled={busy} onClick={() => refresh()}>Atualizar estado</button>
      {error && <p role="alert">{error}</p>}
      <h3>Entrega por mensagem</h3>
      {!messages.length && <p role="status">Nenhuma entrega disponível.</p>}
      {messages.length > 0 && <div className="durable-table-scroll"><table><caption>Mensagens Web deste workspace</caption>
        <thead><tr><th scope="col">Pedido / mensagem</th><th scope="col">Entrega</th><th scope="col">Modelo / esforço</th></tr></thead>
        <tbody>{messages.map(message => <tr key={message.request_id}>
          <td><code>{message.request_id}</code>{message.message_id && <small>{message.message_id}</small>}</td>
          <td><strong>{message.label}</strong>{message.reason && <small>{message.reason}</small>}
            {message.requires_reconciliation && <small>Reconciliação necessária. O envio permanece bloqueado.</small>}</td>
          <td>{message.model || 'Indisponível'} · {message.effort || 'Indisponível'}<small>{message.model_state === 'VERIFIED'
            ? 'Verificado na sessão Web' : `Seleção: ${message.model_state}`}</small></td>
        </tr>)}</tbody></table></div>}
      <h3>Goal / Loop</h3>
      <form onSubmit={event => { event.preventDefault(); mutate({ ws, action: 'set', objective: objective.trim() }); }}>
        <label>Objetivo <textarea required maxLength={8000} value={objective} onChange={event => setObjective(event.target.value)} /></label>
        <button disabled={busy || !objective.trim()}>Salvar objetivo</button>
      </form>
      <fieldset disabled={busy}><legend>Limites para iniciar o Loop</legend>
        <label>Passos (1–16) <input type="number" min="1" max="16" value={limits.steps} onChange={event => setLimits({ ...limits, steps: event.target.value })} /></label>
        <label>Custo máximo (USD) <input type="number" min="0" step="0.01" value={limits.cost} onChange={event => setLimits({ ...limits, cost: event.target.value })} /></label>
        <label>Duração (segundos) <input type="number" min="1" max="86400" value={limits.seconds} onChange={event => setLimits({ ...limits, seconds: event.target.value })} /></label>
      </fieldset>
      {goals.map(goal => <section key={goal.goal_id} aria-label="Objetivo persistido">
        <strong>{goal.objective}</strong><p>{goal.state || 'Estado indisponível'} · Iteração {goal.iteration ?? '—'} / {goal.max_steps ?? '—'}</p>
        <p>Custo contabilizado: {goalCost(goal)}</p>
        {goal.next_action && <p>Próxima ação: {goal.next_action}</p>}
        {goal.block_reason && <p role="status">Bloqueio: {goal.block_reason}</p>}
        <button disabled={busy || Boolean(goal.loop_id) || !limits.cost} onClick={() => {
          try { mutate(loopRequest(ws, goal, limits)); } catch (failure) { setError(failure.message); }
        }}>Iniciar Loop com estes limites</button>
        <button disabled={busy} onClick={() => mutate({ ws, action: 'stop', goal_id: goal.goal_id,
          ...(goal.loop_id ? { loop_id: goal.loop_id } : {}) })}>Interromper objetivo / Loop</button>
        {Array.isArray(goal.history) && goal.history.length > 0 && <details><summary>Histórico de execução</summary>
          <ol>{goal.history.map((entry, index) => <li key={entry.operation_id || index}>{entry.state} · {entry.summary || entry.operation_id}</li>)}</ol>
        </details>}
      </section>)}
      <CompactResumePanel key={ws} ws={ws} />
    </div>
  </Modal>;
}
