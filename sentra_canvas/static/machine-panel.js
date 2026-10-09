"use strict";
/* Native controls over the authenticated central machine API. */
window.SentraMachinePanel = (() => {
  const element = (tag, text, attrs = {}) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    Object.assign(node, attrs);
    return node;
  };
  const field = (form, title, node) => {
    const label = element("label", title, {className: "machine-field"});
    label.append(node); form.append(label); return node;
  };
  const input = (placeholder = "") => element("input", undefined, {placeholder});
  const select = (options) => {
    const node = element("select");
    for (const [value, title] of options) node.append(element("option", title, {value}));
    return node;
  };
  const docActions = [
    ["table.inspect", "Ler CSV ou TSV"], ["table.transform", "Transformar tabela"],
    ["excel.inspect", "Ler planilha XLSX"], ["excel.transform", "Atualizar células XLSX"],
    ["pdf.inspect", "Inspecionar PDF"], ["pdf.text", "Extrair texto do PDF"],
    ["pdf.extract_pages", "Salvar páginas do PDF"]
  ];
  const scalar = text => { try { const v = JSON.parse(text); if (v === null || ["string", "number", "boolean"].includes(typeof v)) return v; } catch {} return text; };
  const list = text => text.split(",").map(x => x.trim()).filter(Boolean);
  const absolute = (root, path) => /^[A-Za-z]:[\\/]|^\//.test(path) ? path : root.replace(/[\\/]+$/, "") + "/" + path;

  async function open({api, state, toast, requireWS}) {
    const ws = requireWS();
    const agents = state.detail?.agents || [];
    if (!agents.length) throw Error("Adicione um agente ao workspace antes de configurar uma máquina.");
    const info = await api("/api/center/machines?ws=" + encodeURIComponent(ws));
    if (state.ws !== ws) return;
    const root = state.detail.workspace.path;
    const panel = document.getElementById("inspector"); panel.hidden = false;
    document.getElementById("inspector-title").textContent = "Máquinas e documentos";
    document.getElementById("inspector-label").textContent = "EXECUÇÃO DO WORKSPACE";
    document.getElementById("inspector-tabs").hidden = true;
    const content = document.getElementById("inspector-content"); content.replaceChildren();
    const host = element("section", undefined, {className: "machine-panel"}); content.append(host);
    host.append(element("p", "Configure uma máquina para o agente e escolha a tarefa. Cada resultado fica vinculado à execução."));
    const machines = info.machines.slice();
    const tasks = new Map();
    for(const work of info.work_items||[])for(const cap of work.capabilities){
      const key=work.machine_id+":"+cap;if(!tasks.has(key))tasks.set(key,work.work_item_id);
    }
    const sessions = new Map();
    const output = element("pre", "Nenhuma operação enviada.", {className: "machine-result"});
    const status = element("p", "Nenhuma operação enviada."); status.setAttribute("aria-live", "polite");
    const inventory = select([]);
    field(host,"Máquina em uso",inventory);
    function refresh() {
      const previous = inventory.value; inventory.replaceChildren();
      for (const m of machines) {
        const owner = agents.find(a => a.id === m.agent_id)?.name || m.agent_id;
        inventory.append(element("option", ({documents:"Documentos",browser:"Navegador",openhands:"OpenHands",workflow:"Workflow",daytona:"Daytona",guacamole:"Guacamole",rustdesk:"RustDesk"}[m.kind]||m.kind) + " · " + owner, {value: m.machine_id}));
      }
      if (machines.some(m => m.machine_id === previous)) inventory.value = previous;
    }
    function report(result) {
      if (state.ws !== ws) return;
      output.textContent = JSON.stringify(result, null, 2);
      status.textContent = result.operation_id ? (
        result.state === "SUCCEEDED" ? "Operação concluída. A evidência foi preservada." :
        result.state === "UNCERTAIN" ? "Resultado ainda incerto. Consulte a operação para acompanhar." :
        "A operação não foi concluída: " + (result.error || result.state)) : "Configuração atualizada.";
      if(result.evidence?.payload?.completion_confirmed===false)
        status.textContent="O servidor confirmou a solicitação. Consulte os eventos para acompanhar o agente.";
      if (result.operation_id) {
        output.dataset.operation = result.operation_id;
        if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(result.state)) delete output.dataset.pending;
        else output.dataset.pending = result.operation_id;
        toast(result.state === "SUCCEEDED" ? "Operação concluída com evidência." :
          result.state === "UNCERTAIN" ? "Resultado incerto. Consulte a operação antes de tentar novamente." : "Operação: " + result.state,
          result.state === "SUCCEEDED" ? "success" : "info");
      }
    }
    const configure = element("form");
    configure.append(element("h3", "Configurar máquina"));
    const agent = field(configure, "Agente", select(agents.map(a => [a.id, a.name || a.id])));
    const kind = field(configure, "Recurso", select([["documents", "Planilhas, tabelas e PDF"], ["browser", "Navegador isolado"],["openhands","Servidor OpenHands"]]));
    const origins = field(configure, "Sites permitidos para o navegador, um por linha", element("textarea", undefined, {placeholder: "https://example.com", rows: 3}));
    const submitForms = field(configure, "Permitir envio de formulários aos sites escolhidos", element("input", undefined, {type: "checkbox"}));
    const ohServer=field(configure,"Servidor OpenHands",input("http://127.0.0.1:8000"));
    const ohProfile=field(configure,"ID do perfil de agente no servidor",input("Perfil configurado no OpenHands"));
    const ohWorkspace=field(configure,"Diretório de trabalho no servidor",input("/workspace"));
    const ohSecret=field(configure,"Credencial cadastrada no SENTRA, quando necessária",input("ID da credencial"));
    function showConfiguration(){
      for(const control of [origins,submitForms])control.parentElement.hidden=kind.value!=="browser";
      for(const control of [ohServer,ohProfile,ohWorkspace,ohSecret])control.parentElement.hidden=kind.value!=="openhands";
    }
    kind.addEventListener("change",showConfiguration);showConfiguration();
    const setup = element("button", "Configurar", {type: "submit", className: "action"}); configure.append(setup);
    configure.addEventListener("submit", async event => {
      event.preventDefault(); setup.disabled = true;
      try {
        const body = {ws, agent_id: agent.value, kind: kind.value};
        if (kind.value === "browser") {
          const allowed = origins.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean).map(x => new URL(x).origin);
          if (!allowed.length) throw Error("Informe os sites permitidos para esta sessão.");
          body.profiles = [{name: "sites-escolhidos", mode: "allowlist", allowed_origins: [...new Set(allowed)],
            methods: submitForms.checked ? ["GET", "HEAD", "POST", "OPTIONS"] : ["GET", "HEAD"], max_redirects: 8}];
        }
        if(kind.value==="openhands"){
          body.provider_config={enabled:true,base_url:ohServer.value.trim(),agent_profile_id:ohProfile.value.trim(),
            remote_workspace:ohWorkspace.value.trim(),provider_id:"canvas-openhands-"+agent.value};
          if(ohSecret.value.trim())body.provider_config.secret_ref=ohSecret.value.trim();
        }
        const configured = await api("/api/center/machine/configure", body);
        if (!machines.some(m => m.machine_id === configured.machine_id)) machines.push(configured);
        refresh(); inventory.value = configured.machine_id;showResource();
        report(configured); toast("Máquina configurada. Escolha a tarefa.", "success");
      } catch (error) { toast(error.message, "error"); }
      finally { setup.disabled = false; }
    });
    host.append(configure);
    const diagnosticDetails=element("details");diagnosticDetails.append(element("summary","Diagnóstico do runtime"));
    const diagnosticForm=element("form");diagnosticDetails.append(diagnosticForm);
    const collector=field(diagnosticForm,"Collector local",input("http://127.0.0.1:4318/v1/traces"));
    const diagnosticEnabled=field(diagnosticForm,"Exportar resumos de execução",element("input",undefined,{type:"checkbox"}));
    const diagnosticButton=element("button","Atualizar diagnóstico",{type:"submit",className:"action"});
    diagnosticForm.append(diagnosticButton);
    const diagnosticStatus=element("p","O diagnóstico é opcional. A fila informa entregas e perdas.");diagnosticDetails.append(diagnosticStatus);
    diagnosticForm.addEventListener("submit",async event=>{
      event.preventDefault();diagnosticButton.disabled=true;
      try{
        const configuration={enabled:diagnosticEnabled.checked};if(configuration.enabled)configuration.endpoint=collector.value.trim();
        const result=await api("/api/center/telemetry",{ws,configuration});
        diagnosticStatus.textContent=result.enabled?"Fila: "+result.pending+" · entregues: "+result.delivered+" · descartados: "+result.dropped:"Exportação desativada.";
      }catch(error){toast(error.message,"error");}finally{diagnosticButton.disabled=false;}
    });host.append(diagnosticDetails);
    const ohForm=element("form");ohForm.append(element("h3","Conversa no OpenHands"));
    const ohAction=field(ohForm,"Ação",select([["create","Criar conversa"],["message","Enviar mensagem"],["read","Consultar conversa"],
      ["events","Recuperar eventos"],["run","Executar agente"],["cancel","Pausar agente"]]));
    const ohLocal=field(ohForm,"Identidade local da conversa",input("minha-conversa"));
    const ohMessage=field(ohForm,"Mensagem",element("textarea",undefined,{rows:4}));
    const ohButton=element("button","Aplicar à conversa",{type:"submit",className:"action"});ohForm.append(ohButton);
    ohForm.addEventListener("submit",async event=>{
      event.preventDefault();ohButton.disabled=true;
      try{
        const machine=machines.find(m=>m.machine_id===inventory.value&&m.kind==="openhands");
        if(!machine)throw Error("Selecione uma máquina OpenHands.");
        const sessionKey=machine.machine_id+":openhands-session";
        if(!tasks.has(sessionKey)){
          const known=machine.capabilities.map(cap=>tasks.get(machine.machine_id+":"+cap));
          if(known.every(Boolean)&&new Set(known).size===1)tasks.set(sessionKey,known[0]);
        }
        if(!tasks.has(sessionKey)){
          const prepared=await api("/api/center/task/prepare",{ws,machine_id:machine.machine_id,
            capabilities:machine.capabilities,objective:"Gerenciar a conversa OpenHands escolhida pelo usuário"});
          tasks.set(sessionKey,prepared.work_item.work_item_id);
          for(const cap of machine.capabilities)tasks.set(machine.machine_id+":"+cap,prepared.work_item.work_item_id);
        }
        const args={local_id:ohLocal.value.trim()};
        if(!args.local_id)throw Error("Informe uma identidade estável para a conversa.");
        if(ohAction.value==="create"){
          args.parent_local_id=null;
          if(ohMessage.value.trim())args.message=ohMessage.value;
        }else if(ohAction.value==="message")args.message=ohMessage.value;
        else if(ohAction.value==="events"){args.page_id=sessions.get(sessionKey+":"+args.local_id)||null;args.limit=100;}
        else if(ohAction.value==="cancel")args.immediate=true;
        const result=await execute(machine,"openhands:"+ohAction.value,args);
        const payload=result.evidence?.payload;
        if(ohAction.value==="events"&&result.state==="SUCCEEDED"&&payload?.next_page_id!==undefined)
          sessions.set(sessionKey+":"+args.local_id,payload.next_page_id||args.page_id);
      }catch(error){toast(error.message,"error");}finally{ohButton.disabled=false;}
    });host.append(ohForm);
    const experienceForm=element("form");experienceForm.append(element("h3","Experiências anteriores"));
    const experienceQuery=field(experienceForm,"O que você quer recuperar?",input("table transform, Excel ou PDF"));
    const experienceButton=element("button","Consultar experiências",{type:"submit",className:"action"});
    experienceForm.append(experienceButton);
    experienceForm.addEventListener("submit",async event=>{
      event.preventDefault();experienceButton.disabled=true;
      try{
        const machine=machines.find(m=>m.machine_id===inventory.value);
        if(!machine)throw Error("Escolha uma máquina configurada.");
        const capability=machine.capabilities.find(c=>c.includes("inspect"))||machine.capabilities[0];
        const work=await ensureTask(machine,capability);
        const result=await api("/api/center/experiences",{ws,work_item_id:work,machine_id:machine.machine_id,query:experienceQuery.value});
        output.textContent=JSON.stringify(result,null,2);
        status.textContent=result.experiences.length+" experiências pertinentes, com origem e validade.";
      }catch(error){toast(error.message,"error");}finally{experienceButton.disabled=false;}
    });host.append(experienceForm);
    const task = element("form"); task.append(element("h3", "Executar tarefa"));
    refresh();
    const action = field(task, "Tarefa de documento", select(docActions));
    const source = field(task, "Arquivo de entrada", input("relatorio.csv"));
    const destination = field(task, "Arquivo de saída, quando necessário", input("resultado.csv"));
    const columns = field(task, "Colunas da tabela, separadas por vírgula", input("nome,valor"));
    const groups = field(task, "Agrupar por colunas", input("categoria"));
    const sums = field(task, "Somar colunas", input("valor"));
    const cells = field(task, "Células da planilha, uma atualização por linha", element("textarea", undefined, {placeholder: "A1=Nome\nB2=42", rows: 3}));
    const pages = field(task, "Páginas do PDF, separadas por vírgula", input("1,3"));
    const run = element("button", "Executar documento", {type: "submit", className: "action"}); task.append(run);
    async function ensureTask(machine, capability) {
      const key = machine.machine_id + ":" + capability;
      if (!tasks.has(key)) {
        const prepared = await api("/api/center/task/prepare", {ws, machine_id: machine.machine_id,
          capabilities: [capability], objective: machine.kind === "browser" ? "Operar sessão de navegador escolhida pelo usuário" : "Processar documento escolhido pelo usuário"});
        tasks.set(key, prepared.work_item.work_item_id);
      }
      return tasks.get(key);
    }
    async function execute(machine, capability, args) {
      if (output.dataset.pending) throw Error("Consulte a operação pendente antes de enviar outra ação");
      const work = await ensureTask(machine, capability);
      const key = "machine-ui-" + crypto.randomUUID();
      // A failure is observed by this same identity; no automatic retry/new key.
      const operation = "op-" + crypto.randomUUID(); output.dataset.operation = operation; output.dataset.pending = operation;
      const result = await api("/api/center/execute", {ws, machine_id: machine.machine_id,
        work_item_id: work, capability_id: capability, operation_id: operation,
        request_key: key, arguments: args});
      report(result); return result;
    }
    task.addEventListener("submit", async event => {
      event.preventDefault(); run.disabled = true;
      try {
        const machine = machines.find(m => m.machine_id === inventory.value && m.kind === "documents");
        if (!machine) throw Error("Selecione uma máquina de documentos.");
        const args = {action: action.value, input: absolute(root, source.value.trim())};
        if (!source.value.trim()) throw Error("Informe o arquivo de entrada.");
        const writing = /transform|extract_pages$/.test(action.value);
        if (writing) { if (!destination.value.trim()) throw Error("Informe o arquivo de saída."); args.output = absolute(root, destination.value.trim()); }
        if (action.value === "table.transform") {
          if (columns.value.trim()) args.select = list(columns.value);
          if (groups.value.trim()) args.group_by = list(groups.value);
          if (sums.value.trim()) args.sums = list(sums.value);
        }
        if (action.value === "excel.transform") {
          args.cells = {};
          for (const row of cells.value.split(/\r?\n/).filter(x => x.trim())) {
            const split = row.indexOf("="); if (split < 1) throw Error("Use uma célula e seu valor em cada linha.");
            args.cells[row.slice(0, split).trim().toUpperCase()] = scalar(row.slice(split + 1));
          }
        }
        if (action.value.startsWith("pdf.") && pages.value.trim()) {
          if (action.value !== "pdf.inspect") args.pages = list(pages.value).map(x => {
            if (!/^[1-9]\d*$/.test(x)) throw Error("As páginas começam em 1."); return Number(x);
          });
        }
        await execute(machine, writing ? "document:transform" : "document:inspect", args);
      } catch (error) { toast(error.message + ". Consulte a operação se ela já foi enviada.", "error"); }
      finally { run.disabled = false; }
    });
    host.append(task);
    const workflowPanel=window.SentraWorkflowPanel?.mount({host,api,ws,root,agents,machines,
      selectedMachine:()=>machines.find(m=>m.machine_id===inventory.value),selectionControl:inventory,toast,execute,
      configured:machine=>{machines.push(machine);refresh();inventory.value=machine.machine_id;report(machine);showResource();},
      prepare:async machine=>{
        const known=machine.capabilities.map(cap=>tasks.get(machine.machine_id+":"+cap));
        if(known.every(Boolean)&&new Set(known).size===1)return known[0];
        const result=await api("/api/center/task/prepare",{ws,machine_id:machine.machine_id,
          capabilities:machine.capabilities,objective:"Executar o workflow de documentos escolhido pelo usuário"});
        for(const cap of machine.capabilities)tasks.set(machine.machine_id+":"+cap,result.work_item.work_item_id);
        return result.work_item.work_item_id;
      }});
    const browser = element("section"); browser.append(element("h3", "Navegador"));
    const url = field(browser, "Página", input("https://example.com"));
    const observed = element("div", undefined, {className: "machine-elements"});
    const text = field(browser, "Texto para preencher um controle", input("Texto"));
    let observation = null;
    function browserMachine() {
      const machine = machines.find(m => m.machine_id === inventory.value && m.kind === "browser");
      if (!machine) throw Error("Selecione uma máquina de navegador."); return machine;
    }
    async function browserAction(name) {
      const machine = browserMachine(); let session = sessions.get(machine.machine_id);
      if (!session) {
        const opened = await execute(machine, "browser:operate", {action: "open", profile: "sites-escolhidos"});
        session = opened.evidence?.session_id || opened.evidence?.payload?.session_id;
        if (!session || opened.state !== "SUCCEEDED") throw Error("Não foi possível confirmar a sessão do navegador.");
        sessions.set(machine.machine_id, session);
      }
      const args = {action: name, session_id: session};
      if (name === "navigate") args.url = url.value.trim();
      const result = await execute(machine, "browser:operate", args);
      if (name === "close" && result.state === "SUCCEEDED") { sessions.delete(machine.machine_id); observation = null; observed.replaceChildren(); }
      if (name === "observe" && result.state === "SUCCEEDED") {
        observation = result.evidence?.observation || result.evidence?.payload?.observation || result.evidence;
        observed.replaceChildren();
        for (const item of observation.elements || []) {
          const row = element("div"); row.append(element("span", (item.role || "elemento") + " · " + (item.name || item.text || item.element_ref)));
          for (const [verb, label] of [["read", "Ler"], ["click", "Clicar"], ["fill", "Preencher"]]) {
            const button = element("button", label, {type: "button"});
            button.addEventListener("click", async () => {
              button.disabled = true;
              try {
                const request = {action: verb, session_id: session, observation_id: observation.observation_id,
                  page_id: observation.page_id, revision: observation.revision, element_ref: item.element_ref};
                if (verb === "fill") request.text = text.value;
                await execute(machine, "browser:operate", request);
                if (verb !== "read") { observation = null; observed.replaceChildren(); }
              } catch (error) { toast(error.message, "error"); }
              finally { button.disabled = false; }
            }); row.append(button);
          } observed.append(row);
        }
      }
    }
    for (const [name, title] of [["navigate", "Abrir página"], ["observe", "Observar controles"], ["evidence", "Consultar diagnóstico"], ["close", "Encerrar sessão"]]) {
      const button = element("button", title, {type: "button"});
      button.addEventListener("click", async () => { button.disabled = true; try { await browserAction(name); } catch (error) { toast(error.message, "error"); } finally { button.disabled = false; } });
      browser.append(button);
    }
    browser.append(observed); host.append(browser);
    const remotePanel=window.SentraRemotePanel?.mount({host,api,ws,root,agents,execute,toast,
      selectedMachine:()=>machines.find(m=>m.machine_id===inventory.value),
      configured:machine=>{machines.push(machine);refresh();inventory.value=machine.machine_id;report(machine);showResource();}});
    function showResource(){const machine=machines.find(m=>m.machine_id===inventory.value);
      task.hidden=machine?.kind!=="documents";ohForm.hidden=machine?.kind!=="openhands";
      browser.hidden=machine?.kind!=="browser";workflowPanel?.selectionChanged();remotePanel?.selectionChanged();
    }
    inventory.addEventListener("change",showResource);showResource();
    const recover = element("button", "Consultar última operação", {type: "button"});
    recover.addEventListener("click", async () => {
      try { if (!output.dataset.operation) throw Error("Nenhuma operação enviada."); report(await api("/api/center/operation?ws=" + encodeURIComponent(ws) + "&operation_id=" + encodeURIComponent(output.dataset.operation))); }
      catch (error) { toast(error.message, "error"); }
    });
    const details = element("details"); details.append(element("summary", "Dados e evidências da operação"), output);
    host.append(element("h3", "Resultado e evidência"), status, recover, details);
  }
  return {open};
})();
