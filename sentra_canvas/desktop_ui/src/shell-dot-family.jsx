import React, { useId, useState } from 'react';

const DELETE_PHRASE = 'EXCLUIR DOT';

export function DotFamilyControls({ dot, bridge, projectId, spaceId }) {
  const [name, setName] = useState('');
  const [phrase, setPhrase] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [receipt, setReceipt] = useState(null);
  const nameId = useId();
  const phraseId = useId();
  const named = name === dot?.name;
  async function send(action) {
    if (busy || !named) return;
    if (action === 'dot_delete_request' && phrase !== DELETE_PHRASE) return;
    setBusy(true); setError('');
    try {
      const result = await bridge({
        action, project_id: projectId, space_id: spaceId, dot_id: dot.dot_id, confirm_name: name,
        ...(action === 'dot_delete_request' ? { confirm_phrase: phrase } : {}),
        request_key: crypto.randomUUID(),
      });
      if (!result?.receipt_id) throw Error('A família não devolveu recibo. Consulte o estado. Nada foi reenviado.');
      if (result.dot_deleted || result.physical_effect_performed || result.vm_deleted || result.removed) {
        throw Error('O recibo indica efeito físico. A tela para aqui.');
      }
      if (action === 'dot_delete_request' && result.status !== 'deletion_blocked_pending_user_approval') {
        throw Error('A exclusão não ficou bloqueada à espera da pessoa.');
      }
      setReceipt(result);
    } catch (failure) {
      setError(failure.uncertain ? 'Resultado incerto. Consulte o recibo. Não repita o envio.' : failure.message);
    } finally { setBusy(false); }
  }
  return <section className="shell-dot-family" aria-label={'Família de ' + (dot?.name || 'Dot')}>
    <p>Pausar e retomar não excluem o Dot. Pedir exclusão só registra o bloqueio. Nenhum Dot, VM ou conversa é apagado.</p>
    <label htmlFor={nameId}>Nome exato do Dot
      <input id={nameId} className="dot-family-name" value={name} disabled={busy} autoComplete="off" onChange={event => setName(event.target.value)} />
    </label>
    <label htmlFor={phraseId}>Para pedir exclusão, escreva EXCLUIR DOT
      <input id={phraseId} className="dot-family-phrase" value={phrase} disabled={busy} autoComplete="off" onChange={event => setPhrase(event.target.value)} />
    </label>
    <div>
      <button type="button" className="dot-family-pause" disabled={busy || !named} onClick={() => void send('dot_pause_family')}>Pausar família</button>
      <button type="button" className="dot-family-resume" disabled={busy || !named} onClick={() => void send('dot_resume_family')}>Retomar família</button>
      <button type="button" className="dot-family-delete" disabled={busy || !named || phrase !== DELETE_PHRASE} onClick={() => void send('dot_delete_request')}>Pedir exclusão</button>
    </div>
    {receipt && <p className="dot-family-receipt" role="status" data-status={receipt.status} data-receipt={receipt.receipt_id} data-deleted="false">
      Recibo {receipt.receipt_id}. Status {receipt.status}.
    </p>}
    {error && <p className="shell-error" role="alert">{error}</p>}
  </section>;
}
