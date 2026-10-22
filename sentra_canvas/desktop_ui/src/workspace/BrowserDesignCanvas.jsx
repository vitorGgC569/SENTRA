import React,{useState} from 'react';
import {MousePointer2,MessageSquare,Copy} from 'lucide-react';
import {designElements,pickDesignElement,designRequest} from './browser-design';
import './browser-design.css';

export function BrowserDesignCanvas({observation,onDiscuss}){
 const [selected,setSelected]=useState(null),[instruction,setInstruction]=useState(''),[notice,setNotice]=useState('');
 const elements=designElements(observation),element=elements.find(e=>e.element_ref===selected);
 const image=observation.viewport_image,request=designRequest(observation,element,instruction);
 function select(event){const rect=event.currentTarget.getBoundingClientRect();const hit=pickDesignElement(observation,
  (event.clientX-rect.left)/rect.width*image.width,(event.clientY-rect.top)/rect.height*image.height);setSelected(hit?.element_ref||null);setNotice(hit?'':'Selecione um elemento visível.');}
 return <section className="sw-design" aria-label="Design Mode"><header><MousePointer2 size={16}/><strong>Design Mode</strong><span>Selecione para inspecionar</span></header>
  <div className="sw-design-frame" role="img" aria-label="Página observada; selecione um elemento na lista para usar o teclado" onClick={select}>
   <img src={'data:image/jpeg;base64,'+image.base64} alt={observation.title||'Página observada'} draggable={false}/>
   {element&&<span className="sw-design-selection" style={{left:element.design.box.x/image.width*100+'%',top:element.design.box.y/image.height*100+'%',width:element.design.box.width/image.width*100+'%',height:element.design.box.height/image.height*100+'%'}}/>}
  </div>
  <label>Elemento<select value={selected||''} onChange={e=>setSelected(e.target.value)}><option value="">Selecione na imagem ou nesta lista</option>{elements.map(e=><option key={e.element_ref} value={e.element_ref}>{e.tag} · {e.name||e.design.selector}</option>)}</select></label>
  {element&&<><code className="sw-design-selector">{element.design.selector}</code><dl>{Object.entries(element.design.styles||{}).map(([key,value])=><React.Fragment key={key}><dt>{key}</dt><dd>{value}</dd></React.Fragment>)}</dl>
   <label>O que você quer mudar?<textarea value={instruction} maxLength={4000} onChange={e=>setInstruction(e.target.value)} placeholder="Ex.: aumentar o espaço entre o título e o botão"/></label>
   <div className="sw-design-actions">{onDiscuss&&<button disabled={!request} onClick={()=>onDiscuss(request)}><MessageSquare size={14}/>Conversar sobre a mudança</button>}<button disabled={!request} onClick={async()=>{try{await navigator.clipboard.writeText(request);setNotice('Contexto copiado.')}catch{setNotice('Não foi possível copiar. Use a conversa para continuar.')}}}><Copy size={14}/>Copiar contexto</button></div>
  </>}
  <p role="status">{notice||'Selecionar não modifica a página. A mudança é preparada como rascunho para o Dot.'}</p>
 </section>;
}
