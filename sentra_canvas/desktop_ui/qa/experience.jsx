import React, { useRef, useState, Profiler } from 'react';
import { createRoot } from 'react-dom/client';
import '../src/desktop.css';
import '../src/shell-polish.css';
import { ConversationMarkdown } from '../src/shell-markdown';
import { ShellMessageWindow } from '../src/shell-message-window';
import { ComputerResizeHandle } from '../src/shell-computer-resize';
import { ShellConversation } from '../src/shell-conversation';
import { HomeResumePanel } from '../src/shell-home-resume';

// Synthetic presentation data. No model, account, OS action or live service.
export const SAMPLE = '# Resultado do trabalho\n\nTexto com **negrito**, *ênfase*, ~~revisão~~ e `código`.\n\n- Primeiro item\n  - Item interno\n- [x] Conferido\n- [ ] Pendente\n\n3. Terceiro\n4. Quarto\n\n| Componente | Estado |\n| --- | --- |\n| Chat | Preservado |\n| Conexão | Recuperável |\n\n> A confirmação vem do recibo.\n\n```js\nconst mensagem = "Olá 🪐";\nconsole.log(mensagem);\n```\n\n[Link seguro](https://example.com) e [inseguro](javascript:alert(1)).\n\n<script>window.hacked=true</script>\n\n![imagem externa](https://example.com/tracker.png)\n\n[referência][ref]\n\n[ref]: https://example.com/reference\n';
const sampleMessages = Array.from({ length: 1000 }, (_, index) => ({ message_id: 'message-' + index, role: index % 2 ? 'assistant' : 'user',
  content: index === 999 ? SAMPLE : 'Mensagem ' + index + '\n\n' + ('Trecho de leitura preservado. '.repeat(index % 13 === 0 ? 32 : 2)),
  created_at: new Date(1700000000000 + index * 1000).toISOString(), status: 'succeeded' }));
let canonical = [...sampleMessages];
window.appendCanonical = () => { canonical = [...canonical, { ...sampleMessages[999], message_id: 'appended', content: 'Nova mensagem confirmada', created_at: new Date().toISOString() }]; document.dispatchEvent(new Event('visibilitychange')); };
const bridge = async request => {
  if (request.action === 'message_list') return { items: canonical.slice(request.offset, request.offset + request.limit), page: { total: canonical.length, next_offset: request.offset + request.limit < canonical.length ? request.offset + request.limit : null } };
  if (request.action === 'access_status') return { mode: 'ask', requests: [] };
  return { items: [] };
};
function Harness() {
  const mode = new URLSearchParams(location.search).get('mode') || 'markdown';
  const [text, setText] = useState(SAMPLE), [messages, setMessages] = useState(sampleMessages), [all, setAll] = useState(false);
  const scroll = useRef(null), panel = useRef(null);
  window.setMarkdown = setText;
  window.appendWindow = () => setMessages(old => [...old, { message_id: 'next', content: 'Nova mensagem do fim' }]);
  window.prependWindow = () => setMessages(old => [{ message_id: 'previous', content: 'Mensagem anterior carregada' }, ...old]);
  window.experienceCommits ||= [];
  if (mode === 'home') return <div className="opendots-shell" style={{ minHeight: '100vh', display: 'block', padding: '24px' }}><main style={{ maxWidth: '960px', margin: 'auto' }}><h1>O que vamos fazer hoje?</h1><HomeResumePanel
    home={{ project_id: 'qa', spaces: [{ project_id: 'qa', space_id: 's' }], dots: [{ project_id: 'qa', space_id: 's', dot_id: 'd', name: 'Astra' }], conversations: [
      { project_id: 'qa', space_id: 's', dot_id: 'd', conversation_id: 'release', title: 'Plano de release', status: 'succeeded', updated_at: 1700000000 },
      { project_id: 'qa', space_id: 's', dot_id: 'd', conversation_id: 'uncertain', title: 'Verificar entrega da tarefa', status: 'uncertain', updated_at: 1700000100 },
    ] }} surface={{ project_id: 'qa', space_id: 's', dot_id: 'd', conversation_id: 'release', view: 'chat' }}
    onConversation={row => { window.openedConversation = row.conversation_id; }} onNavigate={value => { window.openedSurface = value; }} /></main></div>;
  if (mode === 'conversation') return <div className="opendots-shell" style={{ height: '100vh', display: 'block' }}>
    <ShellConversation conversation={{ project_id: 'qa', space_id: 'qa-space', conversation_id: 'qa-chat', title: 'Revisão de experiência' }} dot={{ dot_id: 'qa-dot', agent_id: 'qa-agent', name: 'Astra', status: 'idle' }} bridge={bridge} onCoordinate={() => {}} onModel={() => {}} onCanvas={() => {}} onTools={() => {}} onChanged={() => {}} />
  </div>;
  if (mode === 'resize') return <div className="opendots-shell" style={{ height: '100vh', display: 'block' }}><div className="dot-computer-workspace is-open" style={{ display: 'grid', height: '100%' }}><main><h1>Conversa com Astra</h1><p>O chat mantém espaço durante o redimensionamento.</p></main><aside ref={panel} className="dot-computer-panel"><ComputerResizeHandle panelRef={panel} expanded={false} /><h2>Computador de Astra</h2></aside></div></div>;
  if (mode === 'window') return <div className="opendots-shell" style={{ height: '100vh', display: 'block' }}><button onClick={() => setAll(value => !value)}>Alternar histórico completo</button><div ref={scroll} className="shell-transcript" style={{ height: '75vh', padding: '16px' }}><ShellMessageWindow items={messages} scrollRef={scroll} follow={false} enabled={!all}>{message => <article className="shell-message"><strong>{message.message_id}</strong><ConversationMarkdown content={message.content} /></article>}</ShellMessageWindow></div></div>;
  return <div className="opendots-shell" style={{ display: 'block', padding: '24px', minHeight: '100vh' }}><main style={{ maxWidth: '760px', margin: 'auto' }}><Profiler id="markdown" onRender={(_id, phase, actualDuration) => window.experienceCommits.push({ phase, actualDuration })}><ConversationMarkdown content={text} /></Profiler></main></div>;
}
createRoot(document.getElementById('root')).render(<Harness />);
