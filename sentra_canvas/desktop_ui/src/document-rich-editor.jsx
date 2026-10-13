import React, {useEffect, useRef, useState} from 'react';
import {useEditor, EditorContent} from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Link from '@tiptap/extension-link';
import {TableKit} from '@tiptap/extension-table';
import {Markdown} from '@tiptap/markdown';

export function DocumentRichEditor({content, onChange, readOnly = false}) {
  const [slash, setSlash] = useState(null), [slashIndex, setSlashIndex] = useState(0);
  const slashState = useRef({}); slashState.current = {slash, slashIndex};
  const editorHandle = useRef(null);
  const slashCommands = [
    ['Título', chain => chain.toggleHeading({level: 2})],
    ['Lista', chain => chain.toggleBulletList()],
    ['Lista numerada', chain => chain.toggleOrderedList()],
    ['Citação', chain => chain.toggleBlockquote()],
    ['Bloco de código', chain => chain.toggleCodeBlock()],
    ['Tabela', chain => chain.insertTable({rows: 3, cols: 3, withHeaderRow: true})],
  ];
  const executeSlash = (current, index) => {
    const range = slashState.current.slash;
    if (!range) return;
    slashCommands[index][1](current.chain().focus().deleteRange(range)).run(); setSlash(null);
  };
  const editor = useEditor({
    extensions: [StarterKit.configure({link: false}), Link.configure({openOnClick: false,
      protocols: ['http', 'https', 'mailto'], autolink: false}), TableKit, Markdown],
    content, contentType: 'markdown', editable: !readOnly,
    onUpdate: ({editor: current}) => {
      onChange(current.getMarkdown());
      const {$from, from} = current.state.selection;
      if ($from.parent.textBetween(0, $from.parentOffset) === '/') {setSlash({from: from - 1, to: from}); setSlashIndex(0);}
      else setSlash(null);
    },
    editorProps: {attributes: {'aria-label': 'Conteúdo do documento', role: 'textbox', 'aria-multiline': 'true'},
      handleKeyDown: (_view, event) => {
        if (!slashState.current.slash) return false;
        if (event.key === 'Escape') {setSlash(null); return true;}
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          setSlashIndex((slashState.current.slashIndex + (event.key === 'ArrowDown' ? 1 : slashCommands.length - 1)) % slashCommands.length); return true;
        }
        if (event.key === 'Enter' && editorHandle.current) {executeSlash(editorHandle.current, slashState.current.slashIndex); return true;}
        return false;
      }},
  });
  editorHandle.current = editor;
  useEffect(() => { if (editor && editor.getMarkdown() !== content) editor.commands.setContent(content, {contentType: 'markdown', emitUpdate: false}); }, [editor, content]);
  useEffect(() => { editor?.setEditable(!readOnly); }, [editor, readOnly]);
  if (!editor) return <p role="status">Abrindo editor…</p>;
  const command = (label, run, active) => <button type="button" disabled={readOnly} aria-pressed={Boolean(active)} onClick={run}>{label}</button>;
  return <div className="document-rich">
    <div className="document-format-bar" role="toolbar" aria-label="Formatação">
      {command('Negrito', () => editor.chain().focus().toggleBold().run(), editor.isActive('bold'))}
      {command('Itálico', () => editor.chain().focus().toggleItalic().run(), editor.isActive('italic'))}
      {command('Título', () => editor.chain().focus().toggleHeading({level: 2}).run(), editor.isActive('heading'))}
      {command('Lista', () => editor.chain().focus().toggleBulletList().run(), editor.isActive('bulletList'))}
      {command('Numerada', () => editor.chain().focus().toggleOrderedList().run(), editor.isActive('orderedList'))}
      {command('Citação', () => editor.chain().focus().toggleBlockquote().run(), editor.isActive('blockquote'))}
      {command('Código', () => editor.chain().focus().toggleCodeBlock().run(), editor.isActive('codeBlock'))}
      {command('Tabela', () => editor.chain().focus().insertTable({rows: 3, cols: 3, withHeaderRow: true}).run())}
      {command('+ linha', () => editor.chain().focus().addRowAfter().run())}
      {command('+ coluna', () => editor.chain().focus().addColumnAfter().run())}
      {command('Excluir tabela', () => editor.chain().focus().deleteTable().run())}
      {command('Desfazer', () => editor.chain().focus().undo().run())}
      {command('Refazer', () => editor.chain().focus().redo().run())}
    </div>
    <EditorContent editor={editor}/>
    {slash && !readOnly && <div className="document-slash-menu" role="menu" aria-label="Comandos do documento">{slashCommands.map(([label], index) =>
      <button key={label} role="menuitem" className={slashIndex === index ? 'selected' : ''} onMouseDown={event => event.preventDefault()} onClick={() => executeSlash(editor, index)}>{label}</button>)}</div>}
  </div>;
}
