import React, { useState } from 'react';
import { ArrowDown, ArrowUp, Layers, Pin, Pencil, ShieldAlert, Trash2 } from 'lucide-react';
import { ActionMenu, Modal } from './primitives';
import { DotFamilyControls } from './shell-dot-family.jsx';
import { DotMascot } from './shell-mascot';

export function ShellDotContextMenu({ dot, favorite, canMoveUp, canMoveDown, onEdit, onFavorite, onMove, onCanvas, onArchiveChange, archivedLocal = false, bridge, projectId, spaceId, children, className = '', ...rowProps }) {
  const [preflight, setPreflight] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmName, setConfirmName] = useState(''), [receipt, setReceipt] = useState(null);
  const [authorityPhrase, setAuthorityPhrase] = useState(''), [authorityReceipt, setAuthorityReceipt] = useState(null);
  const [authorityPendingKey, setAuthorityPendingKey] = useState(null), [vmPreview, setVmPreview] = useState(null);
  async function inspectRemoval() {
    setBusy(true); setError(''); setConfirmName(''); setAuthorityPhrase(''); setReceipt(null); setAuthorityReceipt(null);
    setVmPreview(null);
    try {
      const result = await bridge({ action: 'dot_remove_preflight', project_id: projectId,
        space_id: spaceId, dot_id: dot.dot_id });
      setPreflight(result);
      if (result.resources?.vm_configured) {
        try { setVmPreview(await bridge({ action: 'dot_vm_retire_preflight', project_id: projectId,
          space_id: spaceId, dot_id: dot.dot_id })); }
        catch { setVmPreview({ status: 'unavailable', deletion_available: false }); }
      }
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  async function updateLocalArchive(action) {
    if (!preflight || busy) return;
    setBusy(true); setError('');
    try {
      const result = await bridge({ action, project_id: projectId, space_id: spaceId, dot_id: dot.dot_id,
        ...(action === 'dot_archive_local' ? { confirm_name: confirmName, snapshot: preflight.snapshot } : {}) });
      if (!result.receipt_id || result.remote_archive_verified !== false) {
        throw Error('Sem recibo local confirmado; consulte o estado antes de repetir.');
      }
      setReceipt(result); setPreflight(null);
      await onArchiveChange?.();
    } catch (failure) {
      setError(failure.uncertain ? 'Resultado incerto: consulte as mutações pendentes, sem reenviar.' : failure.message);
    } finally { setBusy(false); }
  }
  async function closeDotAuthority() {
    if (busy || !preflight?.authority_close_ready || authorityPendingKey) return;
    setBusy(true); setError('');
    const requestKey = crypto.randomUUID();
    try {
      const result = await bridge({ action: 'dot_retire_authority_close', project_id: projectId,
        space_id: spaceId, dot_id: dot.dot_id, request_key: requestKey,
        confirm_name: confirmName, confirm_phrase: authorityPhrase, snapshot: preflight.snapshot });
      if (result.status === 'uncertain') {
        setAuthorityPendingKey(requestKey);
        setError('Encerramento incerto: observe o recibo; nunca reenvie o comando.');
      } else if (result.status === 'authority_closed' && result.receipt_id) {
        setAuthorityReceipt(result);
        const fresh = await bridge({ action: 'dot_remove_preflight', project_id: projectId,
          space_id: spaceId, dot_id: dot.dot_id });
        setPreflight(fresh);
      } else throw Error('Encerramento não comprovado. Consulte o diário.');
    } catch (failure) {
      if (failure.uncertain) setAuthorityPendingKey(requestKey);
      setError(failure.uncertain ? 'Resultado incerto: observe a operação sem repetir efeitos.' : failure.message);
    } finally { setBusy(false); }
  }
  async function reconcileAuthority() {
    if (!authorityPendingKey || busy) return;
    setBusy(true); setError('');
    try {
      const value = await bridge({ action: 'dot_retire_authority_reconcile',
        project_id: projectId, space_id: spaceId, dot_id: dot.dot_id,
        retirement_key: authorityPendingKey });
      if (value.status === 'authority_closed') {
        setAuthorityReceipt(value); setAuthorityPendingKey(null);
        setPreflight(await bridge({ action: 'dot_remove_preflight', project_id: projectId,
          space_id: spaceId, dot_id: dot.dot_id }));
      } else setError('Há efeitos ainda incertos: observe os recibos antes de qualquer nova operação.');
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  const items = [
    { label: 'Editar Dot', icon: <Pencil size={15} />, action: () => { setMenuOpen(false); requestAnimationFrame(onEdit); } },
    ...(onCanvas ? [{ label: 'Abrir canvas', icon: <Layers size={15} />, action: onCanvas }] : []),
    { label: favorite ? 'Desafixar dos favoritos' : 'Fixar nos favoritos', icon: <Pin size={15} />, action: () => onFavorite(!favorite) },
    { label: 'Mover para cima', icon: <ArrowUp size={15} />, disabled: !canMoveUp, action: () => onMove('up') },
    { label: 'Mover para baixo', icon: <ArrowDown size={15} />, disabled: !canMoveDown, action: () => onMove('down') },
    { separator: true },
    { label: archivedLocal ? 'Ver arquivo local' : 'Arquivamento e remoção…', icon: <Trash2 size={15} />, danger: true, action: inspectRemoval },
  ];
  const menu = <ActionMenu label={'Opções de ' + dot.name} items={items} open={menuOpen} onOpenChange={setMenuOpen}
    side={children ? 'right' : 'bottom'} sideOffset={children ? 24 : 10} align={children ? 'start' : 'end'} className="shell-dot-menu"
    heading={<><DotMascot mascot={dot.mascot} identity={dot.agent_id} name={dot.name} size="nav" decorative /><span>{dot.name}<small>Gerenciar Dot</small></span></>} />;
  return <>
    {children ? <div className={className} {...rowProps}
      onContextMenu={event => { event.preventDefault(); setMenuOpen(true); }}
      onKeyDown={event => { if (event.key === 'ContextMenu' || event.shiftKey && event.key === 'F10') {
        event.preventDefault(); setMenuOpen(true);
      } }}>{children}{menu}</div> : menu}
    <Modal open={Boolean(preflight)} onOpenChange={open => { if (!open && !busy) setPreflight(null); }}
      title={'Ciclo de vida de ' + dot.name} description="Pré-verificação de recursos; nenhuma exclusão nesta etapa."
      className="shell-modal" busy={busy}>
      {preflight && <div className="shell-dot-removal-preflight">
        <p><ShieldAlert size={16} /> Exclusão definitiva bloqueada. Nenhum Dot, conversa ou disco será excluído.</p>
        <dl>
          <div><dt>Conversas para arquivar</dt><dd>{preflight.resources.conversations}</dd></div>
          <div><dt>Dots no canvas</dt><dd>{preflight.resources.canvas_dots}</dd></div>
          <div><dt>Relações do canvas</dt><dd>{preflight.resources.canvas_links}</dd></div>
          <div><dt>Terminais</dt><dd>{preflight.resources.canvas_terminals}</dd></div>
          <div><dt>VM configurada</dt><dd>{preflight.resources.vm_configured ? 'Sim' : 'Não'}</dd></div>
          <div><dt>ChatGPT remoto vinculado</dt><dd>{preflight.resources.remote_conversations}</dd></div>
          <div><dt>Grants ativos / WorkItems ativos</dt><dd>{preflight.resources.active_grants} / {preflight.resources.active_work_items}</dd></div>
          <div><dt>Turnos incertos ou pendentes</dt><dd>{preflight.resources.pending_shell_turns}</dd></div>
        </dl>
        <ul>{preflight.blockers.map(item => <li key={item.kind}>{item.message}</li>)}</ul>
        {vmPreview && <p>VM/VDI: {vmPreview.status} · identidade {vmPreview.identity_verified ? 'confirmada' : 'não confirmada'} · estado desligado {vmPreview.poweroff_verified ? 'sim' : 'não'}. Exclusão física indisponível; nenhum disco foi tocado.</p>}
        {preflight.authority_close_ready && !preflight.archived_local && !authorityReceipt && !authorityPendingKey && <>
          <p><strong>Encerrar sessões e autorizações deste Dot:</strong> fecha apenas terminais exclusivos,
            coloca os agentes em espera, revoga Grants vinculados e cancela WorkItems não finalizados.
            Não remove dados remotos, VM, VDI ou o próprio Dot.</p>
          <label>Nome exato do Dot: {dot.name}
            <input value={confirmName} disabled={busy} onChange={event => setConfirmName(event.target.value)} autoComplete="off" />
          </label>
          <label>Confirme escrevendo ENCERRAR AUTORIZACOES
            <input value={authorityPhrase} disabled={busy} onChange={event => setAuthorityPhrase(event.target.value)} autoComplete="off" />
          </label>
          <button type="button" disabled={busy || confirmName !== preflight.name ||
            authorityPhrase !== 'ENCERRAR AUTORIZACOES'} onClick={() => void closeDotAuthority()}>
            Encerrar sessões e autorizações deste Dot
          </button>
        </>}
        {!preflight.authority_close_ready && <p>Encerramento de autoridade bloqueado: {(preflight.authority_close_blockers || []).join(', ')}.</p>}
        {authorityPendingKey && <button type="button" disabled={busy} onClick={() => void reconcileAuthority()}>
          Observar efeitos incertos (não reenviar)
        </button>}
        {authorityReceipt && <p role="status">Autorizações encerradas com recibo {authorityReceipt.receipt_id}.
          Dots, conversas e discos preservados.</p>}
        <p>O arquivo local é reversível e não arquiva no ChatGPT, não revoga Grants e não remove VMs ou VDIs.</p>
        {preflight.archived_local ?
          <button type="button" disabled={busy} onClick={() => void updateLocalArchive('dot_restore_local')}>Restaurar marcador local</button> :
          preflight.archive_ready ? <>
            <label>Confirme digitando o nome exato do Dot: {dot.name}
              <input value={confirmName} disabled={busy} onChange={event => setConfirmName(event.target.value)} autoComplete="off" />
            </label>
            <button type="button" disabled={busy || confirmName !== preflight.name}
              onClick={() => void updateLocalArchive('dot_archive_local')}>Arquivar somente no SENTRA</button>
          </> : <p>Arquivo local não disponível: {preflight.archive_blockers.join(', ')}.</p>}
        <DotFamilyControls dot={dot} bridge={bridge} projectId={projectId} spaceId={spaceId} />
        <button type="button" disabled={busy} onClick={() => setPreflight(null)}>Fechar</button>
      </div>}
    </Modal>
    {receipt && <div role="status">{receipt.archived_local ? 'Arquivado localmente' : 'Restaurado localmente'} · recibo {receipt.receipt_id}. Recursos preservados.</div>}
    {error && <div className="shell-error" role="alert">{error}</div>}
  </>;
}
