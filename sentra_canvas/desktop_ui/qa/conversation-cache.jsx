import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import '../src/desktop.css';
import '../src/shell-polish.css';
import '../src/shell-coucou-macos.css';
import { ShellConversation } from '../src/shell-conversation';
import { shellBridge } from '../src/shell-bridge';
import { conversationCache } from '../src/shell-conversation-cache';

const conversation = { project_id: 'qa-cache', space_id: 'qa-space', conversation_id: 'qa-conversation', title: 'Histórico sintético' };
const dot = { dot_id: 'qa-dot', name: 'Dot de QA', status: 'idle' };
window.qaCacheStats = () => conversationCache.stats();
function Harness() {
  const [open, setOpen] = useState(true);
  return <div className="opendots-shell" style={{ display: 'block' }}><button onClick={() => setOpen(value => !value)}>{open ? 'Fechar QA' : 'Abrir QA'}</button>
    <main style={{ height: '1000px', width: '100%' }}>{open && <ShellConversation conversation={conversation} dot={dot} bridge={shellBridge} onCoordinate={() => {}} onModel={() => {}} onCanvas={() => {}} onTools={() => {}} onChanged={() => {}} />}</main></div>;
}
createRoot(document.getElementById('desktop-root')).render(<Harness />);
