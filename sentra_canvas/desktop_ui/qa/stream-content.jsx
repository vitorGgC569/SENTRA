import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import '../src/desktop.css';
import '../src/shell-polish.css';
import { ShellStreamContent } from '../src/shell-stream-content.jsx';

function Harness() {
  const [preview, setPreview] = useState(window.qaInitialPreview);
  const [scope, setScope] = useState({ project_id: 'qa-content', space_id: 'qa-space', conversation_id: 'qa-conversation' });
  window.qaSetPreview = setPreview; window.qaSetScope = setScope;
  return <main className="opendots-shell" style={{ display: 'block', padding: '30px' }}>
    <h1>Prévia sintética</h1><p className="qa-retained-window">{preview.content}</p>
    <ShellStreamContent scope={scope} preview={preview} onAccessDenied={() => { window.qaAccessDenied = true; }} />
  </main>;
}
createRoot(document.getElementById('desktop-root')).render(<Harness />);
