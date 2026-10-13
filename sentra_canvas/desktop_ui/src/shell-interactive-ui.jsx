import React, { useState } from 'react';
import './shell-interactive-ui.css';
import { prepareSentraUiReply } from './shell-interactive-ui-reply.js';

// A local-only view of strictly validated data. No URL loads, HTML injection,
// form submission, tool invocations, browser storage or host actions.
export function SentraInteractiveUi({ spec, onReply }) {
  const [answers, setAnswers] = useState({}), [prepared, setPrepared] = useState(false);
  const changed = (id, value) => { setPrepared(false); setAnswers(previous => ({...previous, [id]:value})); };
  const reply = onReply ? prepareSentraUiReply(spec, answers) : null;
  return <section className="sentra-smart-ui" aria-label={'Painel interativo: '+spec.title}>
    <header><strong>{spec.title}</strong><small>Interação local · não executa comandos</small></header>
    <div className="sentra-smart-ui-content">{spec.elements.map((item,index) => {
      const key = item.id || index;
      switch(item.type) {
        case 'text': return <p key={key}>{item.text}</p>;
        case 'metric': return <div className="sentra-smart-metric" key={key}><small>{item.label}</small>
          <strong>{item.value}</strong>{item.detail && <span>{item.detail}</span>}</div>;
        case 'progress': return <div className="sentra-smart-progress" key={key}>
          <div><span>{item.label}</span><strong>{item.value}%</strong></div>
          <progress max="100" value={item.value} aria-label={item.label}/></div>;
        case 'table': return <div className="sentra-smart-table-wrap" key={key}>
          <table><thead><tr>{item.columns.map((name,i)=><th key={i} scope="col">{name}</th>)}</tr></thead>
            <tbody>{item.rows.map((row,r)=><tr key={r}>{row.map((value,c)=><td key={c}>{value}</td>)}</tr>)}</tbody></table></div>;
        case 'choice': return <fieldset key={key} className="sentra-smart-choice">
          <legend>{item.label}</legend>
          <div>{item.options.map((name,i)=><label key={i}>
            <input type="radio" name={'sentra-choice-'+item.id} value={name}
              checked={(answers[item.id] ?? item.default ?? item.options[0]) === name}
              onChange={()=>changed(item.id,name)}/>{name}</label>)}</div></fieldset>;
        case 'checklist': return <fieldset key={key} className="sentra-smart-choice">
          <legend>{item.label}</legend>
          <div>{item.items.map((name,i)=><label key={i}>
            <input type="checkbox" checked={Boolean(answers[item.id]?.[i])}
              onChange={event=>changed(item.id,{...answers[item.id],[i]:event.target.checked})}/>{name}</label>)}</div></fieldset>;
        default: return null;
      }
    })}</div>
    {reply && <footer><button type="button" onClick={() => {
      if (onReply(reply) === true) setPrepared(true);
    }}>Preparar respostas no editor</button>
      {prepared && <small role="status">Resposta preparada. Revise o texto e clique em Enviar mensagem.</small>}
    </footer>}
  </section>;
}
