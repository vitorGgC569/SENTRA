"use strict";
/* Owner configuration and explicit dispatch of centrally admitted workflow steps. */
window.SentraWorkflowPanel=(()=>{
  function node(tag,text,attrs={}){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;Object.assign(n,attrs);return n;}
  function input(placeholder=""){return node("input",undefined,{placeholder});}
  function field(parent,title,control){const label=node("label",title,{className:"machine-field"});label.append(control);parent.append(label);return control;}
  function choices(rows){const n=node("select");for(const [value,title] of rows)n.append(node("option",title,{value}));return n;}
  function button(parent,title,handler){const b=node("button",title,{type:"button",className:"action"});
    b.addEventListener("click",async()=>{b.disabled=true;try{await handler();}finally{b.disabled=false;}});parent.append(b);return b;}
  function mount({host,api,ws,root,agents,machines,selectedMachine,selectionControl,toast,execute,configured,prepare}){
    const section=node("section");section.append(node("h3","Workflows de documentos"));
    section.append(node("p","Defina as etapas, inicie uma execução e avance cada atividade disponível. A consulta recupera o estado preservado."));
    const setup=node("details");setup.append(node("summary","Definir um workflow"));section.append(setup);
    const agent=field(setup,"Agente",choices(agents.map(a=>[a.id,a.name||a.id])));
    const name=field(setup,"Nome do workflow",input("relatorio-mensal"));
    const version=field(setup,"Versão",input("1"));version.value="1";
    const rows=node("div");setup.append(rows);const steps=[];
    const actions=[["table.transform","Transformar CSV ou TSV"],["excel.transform","Atualizar células XLSX"],
      ["pdf.extract_pages","Extrair páginas PDF"],["artifact.verify","Verificar resultado com arquivo de referência"],["wait","Aguardar confirmação"]];
    function addStep(){
      if(steps.length>=30)throw Error("O editor aceita até 30 etapas.");
      const row=node("fieldset"),index=steps.length+1;row.append(node("legend","Etapa "+index));
      const action=field(row,"Atividade",choices(actions));
      const source=field(row,"Arquivo de entrada",input("dados.csv"));
      const output=field(row,"Arquivo de saída",input("resultado.csv"));
      const expected=field(row,"Arquivo de referência",input("esperado.csv"));
      const columns=field(row,"Colunas a conservar, separadas por vírgula",input("nome,valor"));
      const groups=field(row,"Agrupar por",input("categoria"));
      const sums=field(row,"Colunas a somar",input("valor"));
      const cells=field(row,"Células e valores, uma por linha",node("textarea",undefined,{placeholder:"A1=Nome\nB2=42",rows:3}));
      const pages=field(row,"Páginas, separadas por vírgula",input("1,3"));
      const signal=field(row,"Nome da confirmação",input("aprovacao"));
      const metric=field(row,"Comparação",choices([["table","Tabela"],["excel","Planilha"],["pdf","PDF"],["bytes","Conteúdo exato"]]));
      function show(){for(const [control,visible] of [[source,action.value!=="wait"],[output,["table.transform","excel.transform","pdf.extract_pages"].includes(action.value)],
        [expected,action.value==="artifact.verify"],[metric,action.value==="artifact.verify"],
        [columns,action.value==="table.transform"],[groups,action.value==="table.transform"],[sums,action.value==="table.transform"],
        [cells,action.value==="excel.transform"],[pages,action.value==="pdf.extract_pages"],[signal,action.value==="wait"]])control.parentElement.hidden=!visible;}
      action.addEventListener("change",show);show();
      steps.push({action,source,output,expected,columns,groups,sums,cells,pages,signal,metric,index});rows.append(row);
    }
    addStep();button(setup,"Adicionar etapa",async()=>{try{addStep();}catch(e){toast(e.message,"error");}});
    const defaults=new Map();
    const absolute=value=>/^[A-Za-z]:[\\/]|^\//.test(value)?value:root.replace(/[\\/]+$/,"")+"/"+value;
    const split=value=>value.split(",").map(x=>x.trim()).filter(Boolean);
    button(setup,"Salvar definição",async()=>{
      try{
        const values={},definitionSteps=steps.map((row,i)=>{
          const step={step_id:"etapa-"+row.index,dependencies:i?["etapa-"+steps[i-1].index]:[]};
          if(row.action.value==="wait")return {...step,kind:"wait",signal_name:row.signal.value.trim()};
          const args={action:row.action.value};
          for(const [argument,control] of [["input",row.source],["output",row.output],["expected",row.expected]]){
            const needed=argument==="input"||argument==="output"&&row.action.value!=="artifact.verify"||argument==="expected"&&row.action.value==="artifact.verify";
            if(!needed)continue;
            if(!control.value.trim())throw Error("Preencha o arquivo da etapa "+row.index+".");
            const key=step.step_id+"_"+argument;values[key]=absolute(control.value.trim());args[argument]={source:"input",path:[key]};
          }
          if(row.action.value==="table.transform")for(const [key,control] of [["select",row.columns],["group_by",row.groups],["sums",row.sums]])
            if(control.value.trim())args[key]=split(control.value);
          if(row.action.value==="excel.transform"){
            args.cells={};for(const line of row.cells.value.split(/\r?\n/).filter(x=>x.trim())){
              const at=line.indexOf("=");if(at<1)throw Error("Informe célula=valor na etapa "+row.index+".");
              const raw=line.slice(at+1);let value=raw;try{const parsed=JSON.parse(raw);if(parsed===null||["string","number","boolean"].includes(typeof parsed))value=parsed;}catch{}
              args.cells[line.slice(0,at).trim().toUpperCase()]=value;
            }
          }
          if(row.action.value==="pdf.extract_pages")args.pages=split(row.pages.value).map(p=>{if(!/^[1-9]\d*$/.test(p))throw Error("Informe páginas a partir de 1.");return Number(p);});
          if(row.action.value==="artifact.verify")args.metric=row.metric.value;
          return {...step,inputs:args};
        });
        const definitions=[{definition_id:name.value.trim(),version:version.value.trim(),steps:definitionSteps}];
        const machine=await api("/api/center/machine/configure",{ws,agent_id:agent.value,kind:"workflow",definitions});
        defaults.set(machine.machine_id,values);configured(machine);refreshParameters();setup.open=false;
        toast("Workflow configurado. Escolha os arquivos da execução.","success");
      }catch(e){toast(e.message,"error");}
    });
    const definition=field(section,"Definição",choices([]));
    const identity=field(section,"Nome desta execução",input("relatorio-outubro"));
    const parameters=node("div");section.append(parameters);let parameterFields=[],loadedMachine=null;
    const progress=node("p","Selecione uma máquina Workflow.");progress.setAttribute("aria-live","polite");section.append(progress);
    const ready=node("div");section.append(ready);
    function machine(){const value=selectedMachine();if(!value||value.kind!=="workflow")throw Error("Selecione uma máquina Workflow.");return value;}
    function refreshParameters(){
      const m=selectedMachine();if(m?.kind!=="workflow")return;
      if(loadedMachine!==m.machine_id){definition.replaceChildren();for(const d of m.definitions)definition.append(node("option",d.definition_id+" · "+d.version,{value:d.definition_id+":"+d.version}));loadedMachine=m.machine_id;}
      parameters.replaceChildren();parameterFields=[];
      const d=m.definitions.find(v=>v.definition_id+":"+v.version===definition.value);if(!d)return;
      const seen=new Set();for(const step of d.steps)for(const spec of step.input_fields||[]){
        if(spec.path.length!==1||typeof spec.path[0]!=="string")continue;
        const key=spec.path[0];if(seen.has(key))continue;seen.add(key);
        const control=field(parameters,step.step_id+" · "+({input:"Entrada",output:"Saída",expected:"Referência"}[spec.argument]||spec.argument),input());
        control.value=defaults.get(m.machine_id)?.[key]||"";parameterFields.push({key,control});
      }
    }
    definition.addEventListener("change",refreshParameters);
    selectionControl?.addEventListener("change",()=>{ready.replaceChildren();
      progress.textContent="Carregue ou consulte a execução da máquina selecionada.";refreshParameters();});
    button(section,"Carregar definição selecionada",async()=>{try{machine();refreshParameters();}catch(e){toast(e.message,"error");}});
    function args(){if(!identity.value.trim())throw Error("Informe o nome estável desta execução.");return {workflow_id:identity.value.trim(),namespace:""};}
    async function dispatch(capability,argumentsValue){const m=machine();await prepare(m);const result=await execute(m,capability,argumentsValue);
      if(result.state!=="SUCCEEDED"){ready.replaceChildren();progress.textContent="A operação não terminou com sucesso. Consulte a evidência antes de continuar.";return null;}
      return result.evidence?.payload||result.evidence;
    }
    button(section,"Iniciar execução",async()=>{try{
      const m=machine();if(loadedMachine!==m.machine_id)throw Error("Carregue a definição antes de iniciar.");
      const d=m.definitions.find(v=>v.definition_id+":"+v.version===definition.value);if(!d)throw Error("Selecione a definição.");
      const inputs={};for(const {key,control} of parameterFields){if(!control.value.trim())throw Error("Preencha os arquivos desta execução.");inputs[key]=absolute(control.value.trim());}
      const value=await dispatch("workflow:create",{workflow_id:args().workflow_id,definition_id:d.definition_id,definition_version:d.version,inputs});
      if(value){ready.replaceChildren();progress.textContent="Execução criada. Avance para consultar as etapas disponíveis.";}
    }catch(e){toast(e.message,"error");}});
    button(section,"Avançar etapas",async()=>{try{
      const value=await dispatch("workflow:advance",args());if(!value)return;ready.replaceChildren();
      progress.textContent="Estado: "+value.status+" · etapas disponíveis: "+(value.ready||[]).length;
      for(const activity of value.ready||[])button(ready,"Executar "+activity.step_id,async()=>{try{
        const latest=await dispatch(activity.capability_id,activity.arguments);
        if(latest){ready.replaceChildren();progress.textContent="Atividade registrada. Avance para confirmar o resultado e consultar a próxima etapa.";}
      }catch(e){toast(e.message,"error");}});
    }catch(e){toast(e.message,"error");}});
    button(section,"Consultar execução",async()=>{try{const value=await dispatch("workflow:observe",{...args(),checkpoint_id:null});
      if(value){ready.replaceChildren();progress.textContent="Estado preservado: "+value.status+" · "+Object.entries(value.steps||{}).map(([key,row])=>key+": "+row.state).join(" · ");}
    }catch(e){toast(e.message,"error");}});
    const signal=field(section,"Confirmação aguardada",input("aprovacao"));
    const confirmation=field(section,"Mensagem da confirmação",input("Aprovado"));
    button(section,"Enviar confirmação",async()=>{try{const value=await dispatch("workflow:signal",{...args(),name:signal.value.trim(),signal_id:"signal-"+crypto.randomUUID(),payload:confirmation.value});
      if(value)progress.textContent="Confirmação registrada. Avance para continuar.";
    }catch(e){toast(e.message,"error");}});
    button(section,"Solicitar cancelamento",async()=>{try{const value=await dispatch("workflow:cancel",args());
      if(value){ready.replaceChildren();progress.textContent=value.provider_cancel_required?"Cancelamento registrado. Existem operações que ainda exigem acompanhamento.":"Cancelamento registrado.";}
    }catch(e){toast(e.message,"error");}});
    function selectionChanged(){section.hidden=selectedMachine()?.kind!=="workflow";
      ready.replaceChildren();refreshParameters();}
    host.append(setup,section);selectionChanged();
    return {selectionChanged};
  }
  return {mount};
})();
