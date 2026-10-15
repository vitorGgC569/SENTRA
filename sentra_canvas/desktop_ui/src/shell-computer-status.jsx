import React from 'react';
import { computerStatus } from './shell-computer-status';

export function ComputerStatusStrip({ status }) {
  const view = computerStatus(status);
  return <div className="shell-computer-status" data-settled={view.settled ? 'true' : 'false'} data-power={view.power} aria-label="Estado do computador do Dot">
    <span data-power={view.power}>{view.powerLabel}</span>
    {view.keyboardLabel && <span data-keyboard={view.keyboardOwner}>{view.keyboardLabel}</span>}
    {view.hypervisor === 'unavailable' && <span>VirtualBox indisponível</span>}
    {view.performanceLabel && <span>{view.performanceLabel}</span>}
    {view.copyLabel && <span>{view.copyLabel}</span>}
  </div>;
}