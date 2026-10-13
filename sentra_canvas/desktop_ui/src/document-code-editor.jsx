import React, {useEffect, useRef} from 'react';
import {EditorState, Compartment} from '@codemirror/state';
import {EditorView, lineNumbers, keymap, drawSelection, highlightActiveLine} from '@codemirror/view';
import {defaultKeymap, historyKeymap, history, indentWithTab} from '@codemirror/commands';
import {syntaxHighlighting, defaultHighlightStyle, bracketMatching, foldGutter, foldKeymap, LanguageDescription} from '@codemirror/language';
import {languages} from '@codemirror/language-data';

// Parser/editor only. No code evaluation, workers with host IO or file writes.
export function DocumentCodeEditor({content, language = '', onChange, readOnly = false, onCursor, collaborative = false, onUndo, onRedo}) {
  const mount = useRef(null), view = useRef(null), callbacks = useRef({});
  const languageSlot = useRef(new Compartment()), permissions = useRef(new Compartment()), historySlot = useRef(new Compartment());
  const external = useRef(false);
  callbacks.current = {onChange, onCursor, onUndo, onRedo};
  useEffect(() => {
    const instance = new EditorView({parent: mount.current, state: EditorState.create({doc: content,
      extensions: [lineNumbers(), drawSelection(), highlightActiveLine(), foldGutter(), bracketMatching(),
        syntaxHighlighting(defaultHighlightStyle), languageSlot.current.of([]), historySlot.current.of(history()),
        permissions.current.of([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]),
        keymap.of([...defaultKeymap, ...foldKeymap, indentWithTab]),
        EditorView.contentAttributes.of({'aria-label': 'Editor de código', spellcheck: 'false'}),
        EditorView.theme({'&': {height: '360px', backgroundColor: '#00000012'}, '.cm-scroller': {overflow: 'auto', fontFamily: 'Consolas, monospace'}, '.cm-gutters': {backgroundColor: 'transparent', color: '#858b96', borderRight: '1px solid #ffffff20'}, '.cm-content': {padding: '12px 0'}}),
        EditorView.updateListener.of(update => {
          if (external.current) return;
          if (update.docChanged) callbacks.current.onChange(update.state.doc.toString());
          if (update.selectionSet) {const range = update.state.selection.main; callbacks.current.onCursor?.(range.anchor, range.head);}
        }),
      ]})});
    view.current = instance;
    return () => {view.current = null; instance.destroy();};
  }, []);
  useEffect(() => {
    if (!view.current || view.current.state.doc.toString() === content) return;
    external.current = true;
    try {view.current.dispatch({changes: {from: 0, to: view.current.state.doc.length, insert: content}});}
    finally {external.current = false;}
  }, [content]);
  useEffect(() => {view.current?.dispatch({effects: permissions.current.reconfigure([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)])});}, [readOnly]);
  useEffect(() => {
    view.current?.dispatch({effects: historySlot.current.reconfigure(collaborative ? keymap.of([
      {key: 'Mod-z', run: () => {callbacks.current.onUndo?.(); return true;}},
      {key: 'Mod-Shift-z', run: () => {callbacks.current.onRedo?.(); return true;}},
    ]) : [history(), keymap.of(historyKeymap)])});
  }, [collaborative]);
  useEffect(() => {
    let active = true;
    const description = LanguageDescription.matchLanguageName(languages, language || 'text', false) || LanguageDescription.matchFilename(languages, `source.${language}`);
    if (description) description.load().then(support => {if (active) view.current?.dispatch({effects: languageSlot.current.reconfigure(support)});}).catch(() => {
      if (active) view.current?.dispatch({effects: languageSlot.current.reconfigure([])});
    });
    else view.current?.dispatch({effects: languageSlot.current.reconfigure([])});
    return () => {active = false;};
  }, [language]);
  return <div className="document-code" ref={mount}/>;
}
