import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import '../src/desktop.css';
import '../src/shell-polish.css';
import { OpenDotsShell } from '../src/shell-app';

// Intentionally use OpenDotsShell and its production shellBridge/api transport.
// The Python QA routes only /api traffic to its own loopback HTTP fixture.
function Harness() {
  const [project, setProject] = useState('qa-turn');
  const controls = window.pywebview?.api ? <div className="shell-native-controls" data-qa-native-controls="true"><button type="button" aria-label="Minimizar janela QA" onClick={() => window.pywebview.api.minimize()}>−</button></div> : null;
  return <OpenDotsShell projectId={project} workspaces={[{ id: 'qa-turn', name: 'QA isolado' }, { id: 'qa-second', name: 'Outro projeto QA' }]} models={['sentra/test-one']}
    onProject={setProject} onWorkspaceCreate={() => {}} onCanvasActive={() => {}} onTools={() => {}} nativeControls={controls} />;
}
createRoot(document.getElementById('desktop-root')).render(<Harness />);
