import React, { memo, useMemo, useRef, useState, useEffect } from 'react';
import { lexer } from 'marked';
import { parseSentraUi, parseSentraUiInlineMessage } from './shell-interactive-ui-schema';
import { SentraInteractiveUi } from './shell-interactive-ui';

// React nodes only: HTML stays text and images require an explicit click.
export function safeMarkdownHref(value) {
  try {
    const url = new URL(String(value));
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
function tokenNodes(tokens, onReply, depth = 0) {
  if (depth > 32) return '[Conteúdo aninhado demais]';
  return (tokens || []).map((token, index) => {
    const children = () => tokenNodes(token.tokens, onReply, depth + 1);
    const wrap = Tag => <Tag key={index}>{children()}</Tag>;
    switch (token.type) {
      case 'space': case 'def': case 'checkbox': return null;
      case 'strong': return wrap('strong');
      case 'em': return wrap('em');
      case 'del': return wrap('del');
      case 'br': return <br key={index} />;
      case 'hr': return <hr key={index} />;
      case 'codespan': return <code key={index}>{token.text}</code>;
      case 'paragraph': return wrap('p');
      case 'heading': { const Tag = 'h' + Math.min(6, token.depth + 2); return wrap(Tag); }
      case 'blockquote': return wrap('blockquote');
      case 'html': return <React.Fragment key={index}>{token.raw}</React.Fragment>;
      case 'escape': return <React.Fragment key={index}>{token.text}</React.Fragment>;
      case 'text': return <React.Fragment key={index}>{token.tokens ? children() : token.text}</React.Fragment>;
      case 'image': case 'link': {
        const href = safeMarkdownHref(token.href);
        const label = token.type === 'image' ? 'Imagem: ' + (token.text || 'abrir imagem') : children();
        return href ? <a key={index} href={href} title={token.title || undefined} target="_blank" rel="noopener noreferrer">{label}</a>
          : <span key={index}>{label}</span>;
      }
      case 'code': return <MarkdownCode key={index} text={token.text} language={token.lang || ''} onReply={onReply} />;
      case 'list': {
        const Tag = token.ordered ? 'ol' : 'ul';
        return <Tag key={index} start={token.ordered && token.start !== 1 ? token.start : undefined}>
          {token.items.map((item, i) => <li key={i} className={item.task ? 'shell-markdown-task' : undefined}>
            {item.task && <span role="img" aria-label={item.checked ? 'Concluído' : 'Pendente'}>{item.checked ? '☑' : '☐'} </span>}
            {tokenNodes(item.tokens, onReply, depth + 1)}</li>)}</Tag>;
      }
      case 'table': return <div key={index} className="shell-markdown-table" role="region" aria-label="Tabela da resposta" tabIndex={0}>
        <table><thead><tr>{token.header.map((cell, i) => <th key={i} scope="col" style={{ textAlign: token.align[i] || undefined }}>{tokenNodes(cell.tokens, onReply, depth + 1)}</th>)}</tr></thead>
          <tbody>{token.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j} style={{ textAlign: token.align[j] || undefined }}>{tokenNodes(cell.tokens, onReply, depth + 1)}</td>)}</tr>)}</tbody></table></div>;
      default: return <React.Fragment key={index}>{token.text || token.raw || ''}</React.Fragment>;
    }
  });
}
const MarkdownCode = memo(function MarkdownCode({ text, language, onReply }) {
  const spec = useMemo(() => language === 'sentra-ui' ? parseSentraUi(text) : null, [text, language]);
  const [copyState, setCopyState] = useState(''), timer = useRef(null), code = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  async function copy() {
    try { await navigator.clipboard.writeText(text); setCopyState('Copiado'); }
    catch {
      const selection = window.getSelection(), range = document.createRange();
      range.selectNodeContents(code.current); selection?.removeAllRanges(); selection?.addRange(range);
      setCopyState('Código selecionado. Use Ctrl+C.');
    }
    clearTimeout(timer.current); timer.current = setTimeout(() => setCopyState(''), 3000);
  }
  if (spec) return <SentraInteractiveUi spec={spec} onReply={onReply} />;
  return <div className="shell-markdown-code"><div className="shell-code-toolbar"><span>{language || 'Código'}</span>
    <button type="button" onClick={copy} aria-label={'Copiar código' + (language ? ' ' + language : '')}>Copiar</button></div>
    <pre tabIndex={0} aria-label={language ? 'Código ' + language : 'Código'}><code ref={code}>{text}</code></pre>
    <span className="shell-visually-hidden" role="status">{copyState}</span></div>;
});
// The lexer understands GFM; completed block subtrees remain memoized on deltas.
const MarkdownBlock = memo(function MarkdownBlock({ token, onReply }) {
  return <>{tokenNodes([token], onReply)}</>;
}, (old, next) => old.token.raw === next.token.raw && old.token._linksKey === next.token._linksKey && old.onReply === next.onReply);

export const ConversationMarkdown = memo(function ConversationMarkdown({ content, onReply }) {
  const source = String(content || '');
  const inlineSpec = useMemo(() => parseSentraUiInlineMessage(source), [source]);
  const parsed = useMemo(() => {
    const tokens = lexer(source, { gfm: true, breaks: false });
    const key = JSON.stringify(tokens.links || {});
    for (const token of tokens) token._linksKey = key;
    return tokens;
  }, [source]);
  if (inlineSpec) return <div className="shell-markdown"><SentraInteractiveUi spec={inlineSpec} onReply={onReply} /></div>;
  return <div className="shell-markdown">{parsed.map((token, i) => <MarkdownBlock key={i} token={token} onReply={onReply} />)}</div>;
});
