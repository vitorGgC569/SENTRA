export function shouldPollTerminalOutput({ outputEnabled, alive, workspace, activeWorkspace, hidden }) {
  return outputEnabled === true && alive !== false && workspace === activeWorkspace && hidden !== true;
}

export function terminalReconcileAction(outputEnabled) {
  return outputEnabled === true ? 'apply' : 'hold';
}
