"use strict";
/* Explicit owner configuration and scoped session controls. No connection on mount. */
window.SentraRemotePanel=(()=>{
  const kinds=new Set(["daytona","guacamole","rustdesk"]);
  function node(tag,text,attrs={}){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;Object.assign(n,attrs);return n;}
  function input(placeholder=""){return node("input",undefined,{placeholder});}
  function field(parent,title,control){const label=node("label",title,{className:"machine-field"});label.append(control);parent.append(label);return control;}
  function choices(rows){const n=node("select");for(const [value,title] of rows)n.append(node("option",title,{value}));return n;}
  const labels={"session.list":"Consultar sessões preservadas",open:"Abrir conexão",read:"Consultar retorno",reattach:"Reanexar conexão",close:"Encerrar conexão",
    "evidence.export":"Salvar evidência", "recording.export":"Salvar gravação", "recording.read":"Consultar gravação",
    "sandbox.create":"Criar sandbox","sandbox.read":"Consultar sandbox","sandbox.reconcile":"Verificar recurso criado",
    "sandbox.start":"Iniciar sandbox","sandbox.stop":"Parar sandbox","sandbox.delete":"Excluir sandbox próprio",
    "pty.create":"Criar terminal","pty.reattach":"Reanexar terminal","pty.read":"Ler terminal","pty.write":"Enviar ao terminal",
    "pty.resize":"Redimensionar terminal","pty.cancel":"Cancelar processo do terminal","pty.disconnect":"Desconectar terminal",
    "command.create":"Criar sessão de comandos","command.execute":"Executar comando permitido","command.read":"Ler retorno do comando",
    "command.input":"Enviar entrada ao comando","command.cancel":"Cancelar comando"};
  const split=text=>text.split(/[,\r\n]+/).map(x=>x.trim()).filter(Boolean);
  function mount({host,api,ws,root,agents,selectedMachine,execute,toast,configured}){
    const setup=node("details");setup.append(node("summary","Configurar uma sessão remota"));
    const form=node("form");setup.append(form);
    const agent=field(form,"Agente",choices(agents.map(a=>[a.id,a.name||a.id])));
    const kind=field(form,"Serviço",choices([["daytona","Daytona"],["guacamole","Guacamole"],["rustdesk","RustDesk nativo"]]));
    const groups={};for(const value of kinds){groups[value]=node("fieldset");form.append(groups[value]);}
    const day=groups.daytona;day.append(node("legend","Sandbox e terminal"));
    const apiURL=field(day,"Endereço da API",input("https://servidor-daytona"));
    const target=field(day,"Destino configurado no Daytona",input("destino"));
    const secret=field(day,"Credencial cadastrada no SENTRA",input("ID da credencial"));
    const versions=field(day,"Versões do SDK autorizadas",input("Versão instalada e conferida"));
    const ptyPin=field(day,"SHA256 do PtyHandle autorizado",input("Hash da implementação instalada"));
    const snapshot=field(day,"Snapshot escolhido para novas máquinas",input("Nome do snapshot"));
    const commands=field(day,"Comandos permitidos, um por linha",node("textarea",undefined,{rows:3}));
    const allowInput=field(day,"Permitir envio de entrada aos processos",node("input",undefined,{type:"checkbox"}));
    const guac=groups.guacamole;guac.append(node("legend","Conexão ao desktop"));
    const guacd=field(guac,"Endereço do guacd",input("127.0.0.1"));
    const guacPort=field(guac,"Porta do guacd",input("4822"));guacPort.value="4822";
    const tls=field(guac,"Usar TLS no guacd",node("input",undefined,{type:"checkbox",checked:true}));
    const certificate=field(guac,"SHA256 do certificado do guacd",input("Hash do certificado DER"));
    const ca=field(guac,"Arquivo de CA, se necessário",input("Caminho absoluto do certificado CA"));
    const protocol=field(guac,"Protocolo do desktop",choices([["rdp","RDP"],["vnc","VNC"],["ssh","SSH"]]));
    const hostname=field(guac,"Endereço da máquina de destino",input("Máquina configurada"));
    const desktopPort=field(guac,"Porta de destino, quando necessária",input("3389"));
    const username=field(guac,"Usuário do desktop",input("Usuário"));
    const passwordRef=field(guac,"Credencial do desktop cadastrada no SENTRA",input("ID da credencial"));
    const keyboard=field(guac,"Permitir teclado e mouse",node("input",undefined,{type:"checkbox"}));
    const native=groups.rustdesk;native.append(node("legend","Cliente nativo próprio"));
    const alias=field(native,"Nome da máquina",input("Meu desktop"));
    const peer=field(native,"ID do peer",input("ID fixado no inventário"));
    const peerPin=field(native,"SHA256 da chave do peer",input("Hash da identidade do peer"));
    const rendezvous=field(native,"Servidor RustDesk",input("servidor:21116"));
    const serverKey=field(native,"Chave pública do servidor",input("Chave conferida do servidor"));
    const executable=field(native,"Executável do build próprio",input("Caminho absoluto do cliente"));
    const executablePin=field(native,"SHA256 do executável",input("Hash do build"));
    const manifest=field(native,"Manifesto do build",input("Caminho absoluto do manifesto"));
    const revision=field(native,"Commit usado no build",input("Revisão completa da fonte"));
    native.append(node("p","A identidade do peer e o login do desktop são confirmados separadamente.",{className:"remote-session-status"}));
    function showKind(){for(const [name,group] of Object.entries(groups))group.hidden=name!==kind.value;}
    kind.addEventListener("change",showKind);showKind();
    const save=node("button","Configurar recurso",{type:"submit",className:"action"});form.append(save);
    form.addEventListener("submit",async event=>{
      event.preventDefault();save.disabled=true;
      try{
        let provider_config;
        if(kind.value==="daytona"){
          provider_config={enabled:true,connection:{api_url:apiURL.value.trim(),target:target.value.trim(),credential_ref:secret.value.trim(),
            allowed_sdk_versions:split(versions.value),pty_handle_sha256:ptyPin.value.trim()},
            allow_pty_input:allowInput.checked,allowed_commands:commands.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean)};
          if(snapshot.value.trim())provider_config.trusted_snapshot=snapshot.value.trim();
        }else if(kind.value==="guacamole"){
          const parameters={hostname:hostname.value.trim()};if(desktopPort.value.trim())parameters.port=desktopPort.value.trim();
          if(username.value.trim())parameters.username=username.value.trim();
          provider_config={enabled:true,host:guacd.value.trim(),port:Number(guacPort.value),protocol:protocol.value,
            parameters,tls:tls.checked,allowed_input:keyboard.checked?["key","mouse"]:[],secret_refs:{}};
          if(tls.checked)provider_config.server_certificate_sha256=certificate.value.trim();
          if(ca.value.trim())provider_config.ca_file=ca.value.trim();
          if(passwordRef.value.trim())provider_config.secret_refs.password=passwordRef.value.trim();
        }else provider_config={enabled:true,peer_alias:alias.value.trim(),peer_id:peer.value.trim(),peer_key_sha256:peerPin.value.trim(),
          rendezvous_server:rendezvous.value.trim(),rendezvous_public_key:serverKey.value.trim(),executable:executable.value.trim(),
          executable_sha256:executablePin.value.trim(),build_manifest:manifest.value.trim(),source_revision:revision.value.trim()};
        const machine=await api("/api/center/machine/configure",{ws,agent_id:agent.value,kind:kind.value,provider_config});
        configured(machine);setup.open=false;toast("Recurso configurado. A conexão será verificada ao abrir a sessão.","success");
      }catch(e){toast(e.message,"error");}finally{save.disabled=false;}
    });
    const section=node("section");section.append(node("h3","Sessões remotas"));
    const state=node("p","Consulte as sessões ou abra uma conexão.",{className:"remote-session-status"});state.setAttribute("aria-live","polite");section.append(state);
    const sessions=field(section,"Sessão preservada",choices([]));const action=field(section,"Ação",choices([]));
    const command=field(section,"Comando permitido",input());
    const text=field(section,"Entrada para o processo",node("textarea",undefined,{rows:3}));
    const rows=field(section,"Linhas do terminal",input("24"));rows.value="24";
    const cols=field(section,"Colunas do terminal",input("100"));cols.value="100";
    const destination=field(section,"Arquivo de evidência",input("sessao-remota.json"));
    const send=node("button","Aplicar à sessão",{type:"button",className:"action"});section.append(send);
    const output=node("pre","",{className:"machine-result"});section.append(output);
    const cursors=new Map(),known=new Map();let loadedMachine=null;
    function chosen(){const machine=selectedMachine();if(!machine||!kinds.has(machine.kind))throw Error("Selecione um recurso de sessão remota.");return machine;}
    function showAction(){const a=action.value;
      sessions.parentElement.hidden=["session.list","open","sandbox.create"].includes(a);
      command.parentElement.hidden=a!=="command.execute";
      text.parentElement.hidden=!["pty.write","command.input"].includes(a);
      for(const control of [rows,cols])control.parentElement.hidden=!["pty.create","pty.resize"].includes(a);
      destination.parentElement.hidden=!["recording.export","evidence.export"].includes(a);
    }
    action.addEventListener("change",showAction);
    function refreshSessions(machine){const previous=sessions.value;sessions.replaceChildren();
      for(const value of known.get(machine.machine_id)||[])sessions.append(node("option",value.id+" · "+(value.state||""),{value:value.id}));
      if([...sessions.options].some(o=>o.value===previous))sessions.value=previous;
    }
    function selectionChanged(){const machine=selectedMachine();section.hidden=!machine||!kinds.has(machine.kind);if(section.hidden)return;
      if(loadedMachine!==machine.machine_id){action.replaceChildren();
        for(const value of machine.actions[machine.capabilities[0]]||[])if(labels[value])action.append(node("option",labels[value],{value}));
        action.value="session.list";loadedMachine=machine.machine_id;refreshSessions(machine);output.textContent="";state.textContent="Consulte o estado preservado antes de reanexar.";
      }showAction();
    }
    send.addEventListener("click",async()=>{
      send.disabled=true;
      try{
        const machine=chosen(),a=action.value,args={action:a};
        if(!["session.list","open","sandbox.create"].includes(a)){if(!sessions.value)throw Error("Consulte ou abra uma sessão antes desta ação.");args.session_id=sessions.value;}
        if(["read","pty.read","command.read","recording.read"].includes(a))args.after=cursors.get(machine.machine_id+":"+sessions.value)||0;
        if(["read","pty.read","command.read"].includes(a)&&machine.kind!=="rustdesk")args.wait_seconds=.5;
        if(["pty.create","pty.resize"].includes(a)){args.rows=Number(rows.value);args.cols=Number(cols.value);}
        if(a==="command.execute")args.command=command.value;
        if(["pty.write","command.input"].includes(a))args.text=text.value;
        if(["recording.export","evidence.export"].includes(a)){
          const path=destination.value.trim();if(!path)throw Error("Informe o arquivo de evidência.");
          args.output=/^[A-Za-z]:[\\/]|^\//.test(path)?path:root.replace(/[\\/]+$/,"")+"/"+path;
        }
        const result=await execute(machine,machine.capabilities[0],args);if(result.state!=="SUCCEEDED")return;
        const value=result.evidence?.payload||result.evidence;
        if(value.sessions){known.set(machine.machine_id,value.sessions);refreshSessions(machine);state.textContent=value.sessions.length+" sessões preservadas. O estado ao vivo é confirmado por consulta ao serviço.";}
        if(value.session_id){const list=known.get(machine.machine_id)||[];if(!list.some(s=>s.id===value.session_id))list.unshift({id:value.session_id,state:"Consulta necessária"});known.set(machine.machine_id,list);refreshSessions(machine);sessions.value=value.session_id;}
        if(Number.isInteger(value.cursor))cursors.set(machine.machine_id+":"+sessions.value,value.cursor);
        if(value.peer_authenticated===true||value.identity_last_verified===true)state.textContent="Peer verificado. Login e disponibilidade do desktop ainda não confirmados.";
        else if(value.gap)state.textContent="O registro informa uma lacuna de dados. A consulta não comprova uma reprodução completa.";
        else if(!value.sessions)state.textContent="Retorno recebido do serviço. Consulte a evidência da operação.";
        if(value.events){const decoder=new TextDecoder();output.textContent=value.events.filter(e=>["pty","stdout","stderr","gap"].includes(e.channel)).map(e=>{
          try{return decoder.decode(Uint8Array.from(atob(e.data_base64),v=>v.charCodeAt(0)));}catch{return "[Segmento ilegível]";}}).join("");
        }else output.textContent=JSON.stringify(value,null,2);
        showAction();
      }catch(e){toast(e.message,"error");}finally{send.disabled=false;}
    });
    host.append(setup,section);selectionChanged();return {selectionChanged};
  }
  return {mount};
})();
