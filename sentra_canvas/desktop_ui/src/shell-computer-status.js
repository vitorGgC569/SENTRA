const POWER = {
  running: 'Ligada', paused: 'Pausada', poweroff: 'Desligada', saved: 'Salva',
  not_created: 'Ainda não criada', aborted: 'Interrompida',
};
const ACTION_LABEL = {
  'pause-or-resume': 'Pausar ou retomar',
  shutdown: 'Desligar',
  handoff: 'Assumir ou devolver o teclado',
  start: 'Iniciar',
  configure: 'Configurar a máquina',
};

function unknownView(label) {
  return {
    settled: false, power: 'unknown', powerLabel: label, keyboardOwner: 'unknown', keyboardLabel: '',
    hypervisor: 'unknown', performance: null, performanceLabel: '', importedPath: null, copyLabel: '',
    actions: [], actionLabels: [],
  };
}

function copyReceiptLabel(vm) {
  if (!vm || typeof vm !== 'object') return '';
  const record = vm.last_project_import;
  const path = record && typeof record === 'object' ? record.guest_path : '';
  if (typeof path === 'string' && path.trim()) return '';
  const sawMachine = typeof vm.vm_state === 'string' && vm.vm_state.trim().length > 0;
  const sawReceiptField = record != null || Object.prototype.hasOwnProperty.call(vm, 'last_project_import');
  if (!sawMachine && !sawReceiptField) return '';
  return 'Nenhum recibo de cópia confirmada';
}

function performanceNote(status, host) {
  if (status == null || (host && typeof host === 'object')) return '';
  return 'Desempenho da VM ainda não consultado';
}

export function computerStatus(status) {
  if (status == null) return unknownView('Consultando o computador…');
  const vm = status.vm && typeof status.vm === 'object' ? status.vm : null;
  const state = typeof vm?.vm_state === 'string' ? vm.vm_state.trim() : '';
  const host = status.host && typeof status.host === 'object' ? status.host : null;
  const hypervisor = status.hypervisor_available === true ? 'available'
    : status.hypervisor_available === false ? 'unavailable' : 'unknown';
  if (!state) {
    return {
      ...unknownView('Estado ainda não confirmado'),
      settled: true,
      hypervisor,
      performanceLabel: performanceNote(status, host),
      copyLabel: copyReceiptLabel(vm),
    };
  }
  const input = status.input || {};
  const holder = input.live && input.holder === 'human' ? 'human'
    : input.live && input.holder === 'agent' ? 'agent' : 'none';
  const actions = state === 'running' || state === 'paused' ? ['pause-or-resume', 'shutdown', 'handoff']
    : state === 'not_created' ? ['configure'] : ['start'];
  return {
    settled: true,
    power: state,
    powerLabel: POWER[state] || 'Estado ainda não confirmado',
    keyboardOwner: holder,
    keyboardLabel: holder === 'human' ? 'Você tem o teclado' : holder === 'agent' ? 'O Dot tem o teclado' : 'Teclado sem posse ativa',
    hypervisor,
    performance: host ? {
      reservedCpus: host.reserved_cpus, maxCpus: host.max_cpus,
      reservedMemoryMb: host.reserved_memory_mb, maxMemoryMb: host.max_memory_mb,
    } : null,
    performanceLabel: performanceNote(status, host),
    importedPath: vm.last_project_import?.guest_path || null,
    copyLabel: copyReceiptLabel(vm),
    actions,
    actionLabels: actions.map(id => ACTION_LABEL[id] || id),
  };
}