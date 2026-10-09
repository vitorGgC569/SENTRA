"use strict";
/* Read projections of the same durable Run, WorkItems and Operations used by dispatch. */
window.SentraCenterPanel=(()=>{
  const labels={CREATED:"Criada",RUNNING:"Em execução",PAUSED:"Pausada",QUEUED:"Na fila",PENDING:"Pendente",
    STARTING:"Iniciando",WAITING_EXTERNAL:"Aguardando retorno",UNCERTAIN:"Resultado incerto",CANCEL_REQUESTED:"Cancelamento solicitado",
    SUCCEEDED:"Concluída",FAILED:"Falhou",CANCELLED:"Cancelada",COMPLETED:"Entregue",VALIDATING:"Em validação",BLOCKED:"Bloqueada",READY:"Disponível"};
  function node(tag,text,attrs={}){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;Object.assign(n,attrs);return n;}
  function field(parent,title,control){const label=node("label",title,{className:"machine-field"});label.append(control);parent.append(label);return control;}
  function input(value=""){return node("input",undefined,{value});}
  function status(value){const n=node("span",labels[value]||value,{className:"center-state"});n.dataset.state=value;return n;}
  function action(parent,title,callback){const b=node("button",title,{type:"button",className:"action"});
    b.addEventListener("click",async()=>{b.disabled=true;try{await callback();}finally{b.disabled=false;}});parent.append(b);return b;}
  async function open({api,state,toast,requireWS,machines}){
    const ws=requireWS(),panel=document.getElementById("inspector");panel.hidden=false;
    document.getElementById("inspector-title").textContent="Central do workspace";
    document.getElementById("inspector-label").textContent="EXECUÇÃO E EVIDÊNCIA";
    document.getElementById("inspector-tabs").hidden=true;
    const content=document.getElementById("inspector-content");content.replaceChildren();
    const host=node("section",undefined,{className:"center-panel"});content.append(host);
    let operationOffset=0,workOffset=0,generation=0;
    const alive=()=>state.ws===ws&&host.isConnected;
    const guarded=fn=>async()=>{try{await fn();}catch(e){if(alive())toast(e.message,"error");}};
    function section(title){const n=node("section",undefined,{className:"center-section"});n.append(node("h3",title));host.append(n);return n;}
    function empty(parent,text){parent.append(node("p",text,{className:"center-empty"}));}
    function paginate(parent,page,kind){const controls=node("div",undefined,{className:"center-pagination"});
      controls.append(node("span",page.total?"Itens "+(page.offset+1)+"–"+(page.offset+page.returned)+" de "+page.total:"Nenhum item"));
      if(page.offset>0)action(controls,"Anteriores",guarded(async()=>{if(kind==="operations")operationOffset=Math.max(0,page.offset-page.limit);else workOffset=Math.max(0,page.offset-page.limit);await refresh();}));
      if(page.next_offset!==null)action(controls,"Próximos",guarded(async()=>{if(kind==="operations")operationOffset=page.next_offset;else workOffset=page.next_offset;await refresh();}));parent.append(controls);
    }
    async function planEditor(item,parent){
      const loaded=await api("/api/center/plan",{ws,work_item_id:item.work_item_id,action:"read"});if(!alive())return;
      const editor=node("details");editor.open=true;editor.append(node("summary","Plano · revisão "+loaded.revision));parent.append(editor);
      editor.append(node("p","As revisões organizam a proposta. Salvar, desfazer ou refazer não executa atividades.",{className:"center-note"}));
      const rows=node("div");editor.append(rows);let steps=loaded.steps.map(s=>JSON.parse(JSON.stringify(s)));const controls=[];
      function addRow(step){const row=node("fieldset"),locked=loaded.executed_step_ids.includes(step.id);row.append(node("legend",locked?"Etapa com efeito iniciado":"Etapa proposta"));
        const title=field(row,"Descrição",input(step.title));title.maxLength=500;
        const cap=node("select");for(const value of item.required_capabilities||[])cap.append(node("option",value,{value}));cap.value=step.capability_id;field(row,"Capacidade",cap);
        const dependencies=field(row,"Depende das etapas",input((step.depends_on||[]).join(", ")));
        row.append(node("small","Identidade: "+step.id));
        if(step.operation_id)row.append(node("small","Operação: "+step.operation_id));
        if(locked){title.disabled=true;cap.disabled=true;dependencies.disabled=true;}
        else action(row,"Remover etapa",async()=>{steps=steps.filter(s=>s.id!==step.id);row.remove();});
        controls.push({step,title,cap,dependencies,locked});rows.append(row);
      }
      steps.forEach(addRow);
      action(editor,"Adicionar etapa",guarded(async()=>{
        if(!item.required_capabilities?.length)throw Error("Esta tarefa não anuncia capacidades para o plano.");
        const step={id:"step-"+crypto.randomUUID().replaceAll("-","").slice(0,20),title:"Nova etapa",capability_id:item.required_capabilities[0],depends_on:[]};steps.push(step);addRow(step);
      }));
      const buttons=node("div",undefined,{className:"center-actions"});editor.append(buttons);
      action(buttons,"Salvar revisão",guarded(async()=>{
        const active=new Set(steps.map(s=>s.id));const updated=controls.filter(c=>active.has(c.step.id)).map(c=>c.locked?c.step:
          {...c.step,title:c.title.value.trim(),capability_id:c.cap.value,depends_on:c.dependencies.value.split(",").map(x=>x.trim()).filter(Boolean)});
        await api("/api/center/plan",{ws,work_item_id:item.work_item_id,action:"revise",steps:updated,expected_revision:loaded.revision});
        if(alive()){editor.remove();await planEditor(item,parent);toast("Revisão do plano preservada.","success");}
      }));
      if(loaded.revision>0)for(const [verb,label] of [["undo","Desfazer revisão"],["redo","Refazer revisão"]])action(buttons,label,guarded(async()=>{
        await api("/api/center/plan",{ws,work_item_id:item.work_item_id,action:verb,expected_revision:loaded.revision});
        if(alive()){editor.remove();await planEditor(item,parent);}
      }));
    }
    async function refresh(){
      const current=++generation;
      const value=await api("/api/center/overview?ws="+encodeURIComponent(ws)+"&operation_offset="+operationOffset+"&work_item_offset="+workOffset);
      if(!alive()||current!==generation)return;host.replaceChildren();
      const head=node("div",undefined,{className:"center-actions"});host.append(head);
      action(head,"Atualizar",guarded(refresh));action(head,"Máquinas e workflows",guarded(machines));
      const stats=node("div",undefined,{className:"center-stats"});host.append(stats);
      for(const [label,count] of [["Máquinas configuradas",value.machines.length],["Tarefas nesta execução",value.work_items.page.total],
        ["Operações registradas",value.operations.page.total],["Resultados incertos",value.operations.state_counts.UNCERTAIN||0]]){
        const card=node("div",undefined,{className:"center-stat"});card.append(node("strong",String(count)),node("span",label));stats.append(card);
      }
      const run=section("Execução atual");run.append(status(value.run.state),node("p",value.run.run_id,{className:"center-note"}));
      const runActions=node("div",undefined,{className:"center-actions"});run.append(runActions);
      if(value.run.state==="RUNNING")action(runActions,"Pausar",guarded(async()=>{await api("/api/run/control",{ws,action:"pause"});await refresh();}));
      if(["CREATED","PAUSED"].includes(value.run.state))action(runActions,"Retomar",guarded(async()=>{await api("/api/run/control",{ws,action:"resume"});await refresh();}));
      const work=section("Tarefas");
      if(!value.work_items.items.length)empty(work,"As tarefas preparadas para agentes e máquinas aparecem aqui.");
      for(const item of value.work_items.items){const row=node("div",undefined,{className:"center-row"});
        row.append(node("strong",item.objective||item.work_item_id),status(item.state));
        row.append(node("p",item.work_item_id,{className:"center-note"}));
        if(item.blockers?.length)row.append(node("p","Impedimentos: "+item.blockers.join(", "),{className:"center-note"}));
        action(row,"Revisar plano",guarded(async()=>{if(!row.querySelector("details"))await planEditor(item,row);}));work.append(row);
      }paginate(work,value.work_items.page,"work");
      const operations=section("Operações e evidências");
      if(!value.operations.items.length)empty(operations,"As ações executadas ficam registradas com sua identidade e seu estado.");
      for(const item of value.operations.items){const row=node("div",undefined,{className:"center-row"});
        row.append(node("strong",item.capability_id||item.kind),status(item.state));row.append(node("p",item.operation_id,{className:"center-note"}));
        if(item.work_item_id&&["sentra.machine","sentra.machine.observation"].includes(item.kind)){action(row,"Consultar evidência",guarded(async()=>{
          const result=await api("/api/center/operation?ws="+encodeURIComponent(ws)+"&operation_id="+encodeURIComponent(item.operation_id));if(!alive())return;
          let details=row.querySelector("details");if(!details){details=node("details");details.append(node("summary","Evidência preservada"));row.append(details);}
          let output=details.querySelector("pre");if(!output){output=node("pre",undefined,{className:"machine-result"});details.append(output);}output.textContent=JSON.stringify(result,null,2);details.open=true;
        }));}operations.append(row);
      }paginate(operations,value.operations.page,"operations");
      const registered=section("Máquinas e provedores");
      if(!value.machines.length)empty(registered,"Configure um recurso para o agente em Máquinas e workflows.");
      for(const m of value.machines){const row=node("div",undefined,{className:"center-row"});
        row.append(node("strong",({documents:"Documentos",browser:"Navegador",openhands:"OpenHands",workflow:"Workflow",daytona:"Daytona",guacamole:"Guacamole",rustdesk:"RustDesk"}[m.kind]||m.kind)),
          node("span","Configurada",{className:"center-state"}),node("p",m.machine_id,{className:"center-note"}));
        row.append(node("p",m.capabilities.length+" capacidades · agente "+m.agent_id,{className:"center-note"}));registered.append(row);
      }
      registered.append(node("p","O cadastro informa a configuração. A evidência de cada operação informa o resultado da execução.",{className:"center-note"}));
      if(value.restore_errors.length)registered.append(node("p",value.restore_errors.length+" configurações não puderam ser restauradas. Consulte a configuração do recurso.",{className:"center-note"}));
      const cost=section("Uso e limites");
      cost.append(node("p","Tokens registrados: "+Number(value.cost.total_tokens||0).toLocaleString("pt-BR")+
        " · consumo de quota: "+Number(value.cost.quota||0).toLocaleString("pt-BR")));
      cost.append(node("p","Valor de custo contabilizado: "+Number(value.cost.actual||0).toLocaleString("pt-BR"),{className:"center-note"}));
      cost.append(node("p","Admissões de execução podem consumir quota sem um preço informado. Este resumo reflete os eventos registrados.",{className:"center-note"}));
      if(!value.budget_policies.length)empty(cost,"Nenhuma política de limite cadastrada para este workspace.");
      for(const policy of value.budget_policies)cost.append(node("p",policy.scope_type+" · "+(policy.enabled?"Ativa":"Desativada")+" · "+policy.mode,{className:"center-note"}));
      const diagnostic=section("Diagnóstico");diagnostic.append(node("p",value.telemetry.enabled?
        "Fila: "+value.telemetry.pending+" · entregues: "+value.telemetry.delivered+" · descartados: "+value.telemetry.dropped:"Exportação de diagnóstico desativada."));
    }
    host.append(node("p","Carregando o estado central…",{className:"center-empty"}));
    try{await refresh();}catch(e){if(alive()){host.replaceChildren(node("p",e.message,{className:"center-empty"}));action(host,"Tentar consulta novamente",guarded(refresh));}}
  }
  return {open};
})();
