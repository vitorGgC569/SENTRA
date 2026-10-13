import React from 'react';
import { parseSentraUi, parseSentraUiInlineMessage } from './shell-interactive-ui-schema';
import { SentraInteractiveUi } from './shell-interactive-ui';

// A presentation-only Markdown subset. Raw HTML is always rendered as text.
function inline(text) {
  return String(text).split(/(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g).map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    const match = part.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
    if (match) return <a key={index} href={match[2]} target="_blank" rel="noopener noreferrer">{match[1]}</a>;
    return part;
  });
}
export function ConversationMarkdown({ content, onReply }) {
  const inlineSpec = parseSentraUiInlineMessage(content);
  if (inlineSpec) return <div className="shell-markdown"><SentraInteractiveUi spec={inlineSpec} onReply={onReply} /></div>;
  const lines = String(content || '').split('\n'), blocks = [];
  let paragraph = [], code = null, language = '';
  const flush = () => { if (paragraph.length) { blocks.push(<p key={blocks.length}>{inline(paragraph.join('\n'))}</p>); paragraph = []; } };
  for (const line of lines) {
    if (line.startsWith('```')) {
      flush();
      if (code !== null) { const raw = code.join('\n'); const spec = language === 'sentra-ui' ? parseSentraUi(raw) : null;
        blocks.push(spec ? <SentraInteractiveUi key={blocks.length} spec={spec} onReply={onReply} /> : <pre key={blocks.length} aria-label={language ? 'Código ' + language : 'Código'}><code>{raw}</code></pre>); code = null; }
      else { code = []; language = line.slice(3).trim(); }
    } else if (code !== null) code.push(line);
    else if (!line.trim()) flush();
    else if (/^#{1,3} /.test(line)) {
      flush(); const match = line.match(/^(#{1,3}) (.*)$/); const Tag = 'h' + (match[1].length + 2);
      blocks.push(<Tag key={blocks.length}>{inline(match[2])}</Tag>);
    } else if (/^> /.test(line)) { flush(); blocks.push(<blockquote key={blocks.length}>{inline(line.slice(2))}</blockquote>); }
    else paragraph.push(line);
  }
  flush(); if (code !== null) blocks.push(<pre key={blocks.length}><code>{code.join('\n')}</code></pre>);
  return <div className="shell-markdown">{blocks}</div>;
}
