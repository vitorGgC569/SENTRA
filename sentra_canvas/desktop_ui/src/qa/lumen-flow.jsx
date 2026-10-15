// Browser QA harness only. Not linked from the Canvas production entry.
import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { HomeBoard } from '../shell-home-board.jsx';
import { homeBoard } from '../shell-home-board.js';
import { FailureNotice } from '../shell-failure.jsx';
import { ComputerStatusStrip } from '../shell-computer-status.jsx';
import { summarizePhases, taskPresentation } from '../shell-canvas-state.js';
import { classifyUpdate, versionDecision, BUNDLE_VERSION } from '../shell-updates.js';
import { DotFamilyControls } from '../shell-dot-family.jsx';
import '../desktop.css';

const home = {
  space: { space_id: 's1' },
  run: { state: 'RUNNING' },
  dots: [
    { dot_id: 'd1', name: 'Atlas', status: 'ready' },
    { dot_id: 'd2', name: 'Nara', status: 'idle' },
  ],
  conversations: [
    { conversation_id: 'c1', dot_id: 'd2', space_id: 's1', title: 'Revisão do mapa', status: 'waiting_approval' },
    { conversation_id: 'c2', dot_id: 'd1', space_id: 's1', title: 'Entrega do relatório', status: 'completed' },
  ],
  spaces: [
    { space_id: 's1', project_id: 'p1', name: 'Mapa', description: 'em curso' },
    { space_id: 's2', project_id: 'p1', name: 'Arquivo', description: 'parado' },
  ],
  activity: { items: [
    { event_id: 'e1', kind: 'operation_failed', payload: { status: 'uncertain', summary: 'Cópia não confirmada' } },
    { event_id: 'e2', kind: 'receipt', payload: { status: 'succeeded', summary: 'Recibo do terminal' } },
  ] },
};

const tasks = [
  { id: 'task-exec', status: 'running', agent_id: 'atlas', progress: '1/3', work_item_id: 'wi-1' },
  { id: 'task-wait', status: 'waiting_approval', depends_on: 'task-exec' },
];
const deliveries = [{ work_item_state: 'IN_REVIEW', operation_state: 'SUCCEEDED' }];

function LumenFlow() {
  const [query, setQuery] = useState('');
  const [log, setLog] = useState([]);
  const [notice, setNotice] = useState('');
  const [failureVisible, setFailureVisible] = useState(true);
  const record = line => setLog(old => [...old, line]);
  const board = useMemo(() => homeBoard(home, {
    query,
    pending: [{ request_key: 'req-1', action: 'conversation_create' }],
    surface: { view: 'canvas', project_id: 'p1', space_id: 's1', dot_id: 'd1', conversation_id: null },
  }), [query]);
  const phases = summarizePhases(tasks, deliveries);
  const task = taskPresentation(tasks[0], { owner: 'Atlas' });
  function chooseUpdate(kind) {
    const classified = classifyUpdate(kind);
    if (kind === 'version') {
      const decision = versionDecision({ installed: null, available: BUNDLE_VERSION, dataRefresh: false });
      setNotice(classified.notice + ' ' + decision.reason);
      record('update:version apply=' + decision.apply);
      return;
    }
    setNotice(classified.notice);
    record('update:' + kind + ' reload=' + classified.reloadsWindow + ' install=' + classified.installsBits + ' compile=' + classified.compilesCode);
  }
  return <div className="opendots-shell" data-theme="light">
    <main id="lumen-flow">
      <HomeBoard board={board} query={query} onQuery={setQuery}
        onContinue={surface => record('continue:' + surface.view)}
        onOpenDot={row => record('dot:' + row.dot_id)}
        onOpenSpace={row => record('space:' + row.space_id)}
        onOpenApproval={item => record('approval:' + item.conversation_id)} />
      <ul id="lumen-phase-legend" className="shell-phase-legend" aria-label="Estados do Canvas">
        {phases.map(item => <li key={item.id} data-phase={item.id}><strong>{item.label}</strong><span>{item.count}</span><small>{item.safeNext}</small></li>)}
      </ul>
      <article id="lumen-task" data-phase={task.phase} data-resend={String(task.resend)}>
        <span className="shell-phase" data-phase={task.phase}>{task.label}</span>
        <span>{task.owner}</span><span>{task.progress}</span><span>{task.receipt}</span>
      </article>
      <ComputerStatusStrip status={{
        vm: { vm_state: 'running', last_project_import: { guest_path: '/home/dot/mapa' } },
        input: { live: true, holder: 'human' },
        host: { reserved_cpus: 2, max_cpus: 8, reserved_memory_mb: 4096, max_memory_mb: 16384 },
      }} />
      {failureVisible && <div id="lumen-failure"><FailureNotice message="A operação permanece incerta." uncertain
        onConsult={() => record('failure:consult resend=false')}
        onDismiss={() => { setFailureVisible(false); record('failure:dismiss'); }} /></div>}
      <div className="shell-update-menu" id="lumen-updates">
        <button type="button" id="lumen-update-data" onClick={() => chooseUpdate('data')}>Atualizar dados</button>
        <button type="button" id="lumen-update-code" onClick={() => chooseUpdate('code')}>Atualizar código local</button>
        <button type="button" id="lumen-update-version" onClick={() => chooseUpdate('version')}>Versão instalada</button>
      </div>
      <p id="lumen-update-notice" role="status">{notice}</p>
      <DotFamilyControls dot={{ dot_id: 'd2', name: 'Nara' }} projectId="p1" spaceId="s1"
        bridge={async payload => {
          record('family:' + payload.action + ':' + (payload.confirm_phrase || ''));
          if (payload.action === 'dot_delete_request') {
            return { status: 'deletion_blocked_pending_user_approval', receipt_id: 'dot-delete-request-qa',
              physical_effect_performed: false, dot_deleted: false, vm_deleted: false, removed: false, effects_executed: 0 };
          }
          if (payload.action === 'dot_pause_family' || payload.action === 'dot_resume_family') {
            return { status: payload.action === 'dot_pause_family' ? 'paused' : 'resumed',
              receipt_id: 'dot-family-qa', physical_effect_performed: false, dot_deleted: false, removed: false };
          }
          throw Error('ação fora da família');
        }} />
      <pre id="lumen-qa-log">{log.join('\n')}</pre>
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<LumenFlow />);
