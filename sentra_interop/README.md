# SENTRA OS — Interoperabilidade Agent Runtime (CRIT-002 / T-102)

Implementação isolada. **Não inicia** daemon ToolHive, MCP, OpenHands ou
gateway A2A por conta própria, nem edita o SENTRA Runtime ou o Canvas.

## Arquitetura

- gate.py: importa diretamente sentra_runtime.contracts e exige Machine,
  Capability e PolicyDecision explícitos antes de qualquer efeito. Condições
  desconhecidas são negadas; política ausente, inválida, revogada ou com
  erro nega a operação. Journal com lock impede reenvio do mesmo
  operation_id ou idempotency_key dentro da instância. Timeout e erro
  de backend retornam UNCERTAIN, nunca sucesso automático.
- acp.py: ACP v1, JSON-RPC 2.0 por stdio UTF-8 delimitado por newline;
  initialize, session/new, session/prompt, session/update e session/cancel.
  Versões incompatíveis são recusadas. Pedidos recebidos do agente para
  FS, terminal ou permissão são rejeitados. ACPStdioTransport.launch exige
  executável absoluto existente, diretório explícito, requisição com
  capability acp:launch e InteropGate autorizado; policy precisa fixar
  executable_paths e cwd_roots para lançar qualquer processo. Nunca usa
  shell ou instalador ACP Registry. Workspace restringe cwd da sessão.
- a2a.py: identidades tipadas, trust-domain e allowlist obrigatória, envelope
  para Task, TaskStatusUpdateEvent e TaskArtifactUpdateEvent, sequência
  monotônica, ID de task imutável, estados terminais irreversíveis, partes
  text/data e validação de chunks de artefato. Cancelamento só é confirmado
  com ACK explícito do peer. Não expõe HTTP/webhooks.
- mcp.py: ToolHiveMCPBoundary recebe apenas clientes MCP previamente
  autenticados e grants exatos (server_id, tool_name, capability_id).
  Confere os argumentos com OperationRequest.arguments antes de tools/call.
  Trata isError como falha, limita tamanho de entrada/saída e não aplica
  fallback. ToolHiveEndpoint é somente descritor, HTTPS fora do loopback.
- registry.py: importação de metadados de agentes ACP com ID e versão pinados.
  Nenhum npx, uvx ou binário é executado ou instalado.
- openhands.py: evento OpenHands tipado, sem Agent Server e sem SDK carregado.

## Contrato de integração futuro (coordenador)

1. Registrar uma Machine agent com capabilities explícitas acp:launch,
   acp:session, acp:prompt, acp:cancel, a2a:ingest, a2a:cancel e
   mcp:<server>:<tool>.
2. Injetar um callback de autorização SENTRA que devolva diretamente
   sentra_runtime.contracts.PolicyDecision para principal, machine,
   work item e capability. Ausência de policy não libera nenhuma operação.
3. Vincular identidade remota ao principal realmente autenticado por uma
   camada de transporte confiável. Agent Card ou AgentIdentity recebido
   sozinho NÃO autentica ninguém. A2ATaskBoundary exige trusted_agents.
4. Registrar clientes MCP já conectados e grants específicos, mantendo o
   SENTRA como fonte da decisão mesmo que ToolHive implemente outra camada.
5. Conectar journal e sequências ao ledger durável coordenado ANTES de
   habilitar operações remotas entre reinícios. O OperationJournal atual
   vive exclusivamente na memória desta instância.

## Limitações e bloqueios

- ACP stdio foi testado com subprocesso local de teste, NÃO com Codex,
  Antigravity nem OpenHands reais.
- Nenhum daemon ToolHive, OpenHands, A2A ou servidor MCP foi instalado,
  iniciado ou testado. Fronteiras MCP/A2A usam doubles nos testes.
- Nenhuma sessão remota de produção ou transporte A2A autenticado existe
  neste slice. A2A aqui é parsing e admission, não gateway E2E.
- Não há durabilidade entre reinícios nem coordenação multi-processo.
  Efeitos incertos devem ser reconciliados pelo coordenador, nunca repetidos.
- Revogação em operações já em voo requer interrupção/isolaçao no executor
  coordenado; o gate revalida cada operação nova.
- Streaming limita JSON e não baixa arquivos ou URIs remotas, nem interpreta
  mensagens externas como autoridade.
- Projetos terceiros foram estudados como referência. Nenhum código foi
  copiado nem dependência adicional instalada.

## Testes

Executar na raiz:
  python -m pytest -q tests/unit/test_sentra_interop_contracts.py
  python -m compileall -q sentra_interop

Propriedade dos arquivos: sentra_interop/ e tests/unit/test_sentra_interop_*.py.


## PHASE-2 — teste stdio local e endurecimento de fronteiras

A suíte adicional cria **em tmp_path de pytest** um pequeno agente Python
independente. ACPStdioTransport.launch inicia esse script como subprocesso
real, através do sys.executable autorizado por policy, sem shell e com
diretório de trabalho explícito. O teste faz initialize -> session/new ->
session/prompt -> session/update com agent_message_chunk e tool_call.
A tool_call no stream é apenas observação, sem execução pelo SENTRA.

O fixture também envia requisições iniciadas pelo agente:
session/request_permission, terminal/create, fs/write_text_file e tools/call.
Todas devem receber erro JSON-RPC -32601; um arquivo sentinela prova que
não houve escrita de arquivo pelo cliente. São exercitados um turn normal,
cancelamento cooperativo com stopReason=cancelled, timeout sem resposta
(remanescente UNCERTAIN) e idempotência sem reenviar prompt. O teste fecha
o transporte duas vezes (cleanup idempotente) e exige returncode do processo
e tarefa de leitura encerrada. Política ausente e override de ambiente
PYTHONPATH são negados antes de criar processo.

- A2A: rejects de mensagens com variantes múltiplas, IDs conflitantes,
  partes de arquivo/ambíguas, estados desconhecidos e agentes não pinados;
  dedupe/replay concorrente e revogação de grant sem mudança de task.
- MCP: bloqueio de respostas inesperadas, contents não textuais,
  campos não aceitos, structuredContent malformado e isError inválido.
  Respostas malformadas **depois** de chamar um cliente externo deixam a
  operação UNCERTAIN para reconciliação — não são reexecutadas. Dedupe por
  operation_id e idempotency_key é testado, e revogação impede novas calls.
  Somente content.type=text é aceito neste primeiro boundary. Para imagens,
  recursos, links e áudio, é necessária avaliação específica de egress
  e formato antes de habilitar.

Os testes com MCP e A2A usam clientes/doubles in-process; **não** são
testes de daemon ToolHive, client SDK MCP externo ou A2A HTTP E2E. Nenhum
serviço de terceiros foi iniciado e nenhuma dependência foi instalada.
O fixture ACP comprova interoperabilidade de transporte local, mas não
substitui testes de certificação com agentes ACP de produção.

Comandos:

    python -m pytest -q tests/unit/test_sentra_interop_contracts.py tests/unit/test_sentra_interop_e2e.py tests/unit/test_sentra_interop_boundaries.py
    python -m compileall -q sentra_interop


## GATE-3 / CRIT-002 — Handoff seguro para a API existente

### ACP stdio: teste local real, sem agente de terceiro

Os testes GATE-3 com test_sentra_interop_gate3.py e
test_sentra_interop_e2e.py iniciam somente subprocessos Python fixture sob
tmp_path, enviando e recebendo frames JSON-RPC stdio UTF-8 v1. Validam
respostas concorrentes reordenadas, colisão de IDs entre pedidos
agent-initiated e resposta pendente, rebind de outro adaptador ACP à mesma
conexão, timeout e resposta tardia, cancelamento de coroutine, pendência no
encerramento, JSON com chaves duplicadas, envelope com result+error, NaN,
ID inesperado, EOF e encerramento do filho com retorno de processo.

- ACPStdioTransport NÃO fornece handlers privilegiados: solicitações de
  terminal, filesystem, tools/call e permission solicitadas pelo agente
  recebem -32601. Tool_call de session/update é observação, jamais grant.
- Métodos cliente permitidos: initialize, session/new e session/prompt.
  Notificação cliente permitida: session/cancel. O raw transport deve ser
  acessível apenas a código interno confiável; nunca o entregar a agentes
  ou principals não confiáveis. A fronteira de autorização real é
  ACPSessionAdapter + InteropGate.
- Para ACP launch, PolicyDecision.constraints exige executable_paths,
  cwd_roots e argv_sha256. A assinatura argv é:
    hashlib.sha256(json.dumps(list(argv), ensure_ascii=False,
      separators=(",", ":")).encode("utf-8")).hexdigest()
  Sem hash, path fixado ou se um ambiente customizado for solicitado,
  não inicia nenhum subprocesso. O teste usa exclusivamente um fixture.
- Parâmetros vinculados a OperationRequest.arguments devem ser:
  ACP open: {"cwd": absolute_workspace_cwd};
  ACP prompt: {"session_id": negotiated_session_id, "text": prompt_text};
  ACP cancel: {"session_id": negotiated_session_id}.
  Trocas de conteúdo com o mesmo operation_id não podem reutilizar sucesso.
- O transporte utiliza IDs locais monotônicos, rejeita respostas tardias
  como autoridade para novo pedido e limita a 4096 IDs incertos; exceder
  exige reconciliação e reabertura. Malformed JSON e envelopes ambíguos
  encerram o processo filho sob posse do transporte. Close fecha stdin,
  aguarda PID e é idempotente nos cenários testados.
- Rebind testado = novo adaptador em um transporte stdio já aberto; NÃO
  foi implementado ACP session/load nem reattach durável de produção.

### A2A e MCP ToolHive

- A2A vincula operation_id a event_id, sequência, identidade e payload;
  não aceita alteração do conteúdo com o mesmo operation_id.
- Antes de persistir estado local, A2A revalida a PolicyDecision dentro
  do lock. Resposta de cancelamento somente confirma CANCELLED quando
  identifica exatamente taskId/id e contextId esperados; ACK sem IDs
  deixa a operação UNCERTAIN.
- A2A contexto (context_id) é ligado a OperationRequest.work_item_id.
  O serviço externo de workspace precisa validar principal -> workspace
  -> work item com grant fresco; este slice não consulta storage de
  workspaces nem guarda credenciais.
- MCP exige grants explícitos server/tool/capability, argumentos vinculados
  à OperationRequest e respostas filtradas (somente content.type=text).
  Revogação durante uma call impede SUCCEEDED na conclusão, classificando
  efeito remoto como UNCERTAIN; não significa que o backend foi revertido.

### Integração com sentra_runtime.executor.ExecutorRegistry

O teste test_executor_registry_to_mcp_boundary_policy_e2e implementa um
ExecutorAdapter de teste compatível com discover/start/observe/cancel/
reconcile/cleanup e passa pelo ExecutorRegistry real até o boundary MCP,
sem editar sentra_runtime e sem conectar ToolHive real:

1. ExecutorRegistry.submit deve exigir authorize e Machine capability.
2. O ExecutorAdapter seleciona o boundary ACP/A2A/MCP e encaminha o mesmo
   OperationRequest sem elevar privilégios e sem apagar identidade.
3. InteropGate usa a autoridade de grants SENTRA, retornando
   sentra_runtime.contracts.PolicyDecision, com constraints verificadas.
4. ExecutorRegistry rejeita constraints não vazios no nível genérico;
   verificá-los no boundary específico, sem reduzir a força do grant.
5. Reconcile deve ler o ledger SENTRA antes de autorizar nova ação incerta;
   nunca executar novamente ferramentas remotas apenas porque ocorreu
   timeout, cancelamento ou erro depois de despachar.
6. Para vários processos/máquinas, ControlStore deve coordenar journal,
   lease, token de fencing, workspace grants e revogação em voo.

### Limitações explícitas

- Nenhum daemon ToolHive, servidor A2A, OpenHands ou CLI ACP terceiro
  foi instalado ou inicializado. ACP foi validado com fixture stdio local.
- A negação de requisições agent-initiated NÃO é sandboxing do próprio
  agente: um subprocesso pode agir com os privilégios do SO. Não há
  confinamento Windows Job Object ou cleanup de grandchildren neste slice.
- Journal local não fornece exactly-once após restart ou entre processos.
- Não há HTTP A2A autenticado, reconexão cross-device certificada ou
  cancelamento distribuído garantido. UNCERTAIN exige reconcile.
- Testes de PID verificam subprocessos criados pelo fixture, não garantem
  ausência de descendentes arbitrários de agentes terceiros.


## GATE-4 CRIT-002 — revisão de launch ACP sob concorrência

**Escopo permitido:** apenas sentra_interop/ e testes test_sentra_interop_*.py.
O subprocesso ACP stdio usa Python de fixture local; isso **não valida**
agentes comerciais, daemons ToolHive ou SDKs instalados.

Diagnóstico confirmado por revisão: a versão anterior executava spawn por
InteropGate.execute, que deliberadamente sintetiza FAILED/UNCERTAIN sem expor
exceções internas. ACPStdioTransport.launch então emitia uma única exceção
genérica, sem informar se a autorização foi negada, o sistema operacional
falhou ou a política foi revogada *após o subprocesso existir*. Quando o
segundo check não permitia sucesso, o processo criado podia perder seu
proprietário antes do fechamento. Isso é um defeito de observabilidade e
limpeza real; **não prova a causa exata** dos 3 failures intermitentes da
auditoria original, cujo traceback não incluía o motivo interno.

ACPStdioTransport.launch agora preserva a mesma admissão por gate e journal:
a decisão inicial valida capability, principal, cwd, executável absoluto
pinado e SHA-256 dos argumentos; uma reserva no journal impede replay e
spawns duplicados; o subprocesso tem ambiente explícito vazio e NUNCA shell.
A política é reavaliada depois do subprocesso criado e antes de confirmar
SUCCEEDED. Todas as falhas posteriores à reserva persistem como UNCERTAIN;
o processo possuído é encerrado e aguardado antes de propagar erro.
Consultas de policy pré/pós-spawn e spawn têm deadline explícita, por
padrão 20 segundos (spawn_timeout, configurável somente pelo chamador).
A classe ACPLaunchError oferece code e state, sem exibir exceções do SO,
paths, argumentos, segredos ou conteúdo dos grants:

- INVALID_REQUEST / INVALID_CONFIG / ENV_DENIED: FAILED antes do spawn
- POLICY_DENIED / POLICY_TIMEOUT: FAILED antes do spawn
- DUPLICATE_OR_CONFLICT: não inicia novo processo; state do journal
- SPAWN_TIMEOUT / SPAWN_OS_ERROR / SPAWN_FAILED: UNCERTAIN
- POST_POLICY_DENIED / POST_POLICY_TIMEOUT: UNCERTAIN, subprocesso recolhido
- SPAWN_CANCELLED / CLEANUP_UNCERTAIN: UNCERTAIN, sem replay automático

Testes determinísticos isolam delay de policy, timeout de spawn, OSError,
revogação após spawn, cancelamento enquanto o filho existe, oito spawns
simultâneos sob atraso, oito calls concorrentes do mesmo operation_id,
argument pin, ambientes, shutdown e ausência de órfãos após close. O teste
prévio com fixture valida requests agent-initiated terminal/filesystem/MCP
como sempre recusadas com -32601, inclusive durante a simulação de reattach.
Envelopes A2A e responses MCP malformados continuam rejeitados e controlados
por PolicyDecision; payload remoto não é permissão.

### Instrução de handoff à API existente

O coordenador deve registrar um ExecutorAdapter em
sentra_runtime.executor.ExecutorRegistry e fornecer
sentra_runtime.contracts.PolicyDecision do serviço de autorização.
O adapter deve registrar Machine com capacidades ACP explícitas e passar
o mesmo InteropGate e OperationRequest para launch, session/open,
session/prompt e cancel. Para ACP launch, os constraints *obrigatórios* são:
executable_paths, cwd_roots, argv_sha256. O argumento enviado na operação
deve conter executable, args e cwd exatos. Em todas as novas operações de
sessão: cwd igual ao request.arguments["cwd"], prompt igual a
request.arguments["text"] e session_id autenticado, cancel_id da mesma
sessão. Nunca fazer dispatch de requests agent-initiated diretamente por
stdout do agente; o canal atual rejeita-os invariavelmente.

Os códigos de ACPLaunchError são informações diagnósticas internas, e não
justificativa para retry imediato de UNCERTAIN. Um reconciliador durável do
SENTRA precisa conferir lease, PID/processo, revogação e efeitos já iniciados
antes de qualquer reexecução. journal e task state locais são em memória;
uma reinicialização do host ainda exige reconciliação externa. A garantia de
cleanup aqui cobre o subprocesso direto possuído pelo adaptador, não sua
árvore inteira nem processos que um agente autorizado possa criar por si.
O runtime, seus contratos e a política global não foram editados.


## GATE-5 — catálogo versionado, mapeamento e EventBridge

Referências inspecionadas (snapshots locais, **sem executar código de terceiros**):
- third_party/agent-client-protocol/docs/protocol/v1/session-setup.mdx:
  session/new, MCP por sessão, session/load condicional à capacidade anunciada.
- third_party/acp-registry/agent.schema.json, registry.schema.json,
  codex-acp/agent.json e antigravity-acp/agent.json: índice versão/agents,
  versões estável e preview, distribuição npx/uvx/binary por plataforma.
- third_party/a2a/docs/topics/a2a-and-mcp.md: tarefas de agentes x ferramentas.
- third_party/mcp-typescript-sdk/docs/clients/calling.md: client.callTool,
  content e isError, structuredContent.
- third_party/toolhive/docs/authz.md e runtime-implementation-guide.md:
  authorize por solicitação, workload lifecycle e isolamento de rede.
- third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/event/
  base.py, types.py, streaming_delta.py e conversation_state.py:
  Event IDs, parent_id, source agent/user/environment/hook, deltas efêmeros.
- third_party/activepieces/README.md, langgraph/README.md,
  temporal/README.md, comparados com orchestrator/ e sentra_mcp/services/.

### APIs locais adicionadas

| Interface | Garantia e limite |
|---|---|
| ACPVersionedCatalog.from_index | Snapshot de índice limitado a 2 MiB, schema_version explicitamente fixado, seleção por agent_id + version; rejeita duplicatas, pins ausentes, preview implícito; sem download ou execução |
| ACPRegistryEntry.from_mapping(channel=stable/preview) | Versão exata pinada por canal; distribuição binary catalogada como "manual-approval-required", sem confiar em URL/cmd externos |
| InteropRequestMapper | Principal, machine, work_item e workspace fornecidos pelo SENTRA; capability allowlist; OperationRequest real, JSON limitado a 64 KiB e protegido contra campos de credenciais; copia argumentos antes de devolver |
| InteropRequestMapper.acp_session/acp_prompt | Vincula cwd dentro do workspace e texto/session_id ao pedido autorizado |
| InteropRequestMapper.mcp_call | Vincula (server,tool,capability), paths/cwd/workspace locais confinados ao workspace; não transporta segredos explícitos |
| InteropRequestMapper.a2a_event | Vincula task_id, context_id, agent_id, trust_domain, estado, sequência e event_id à identidade/work_item atestada |
| A2ATaskBoundary(require_mapped_arguments=True) | Quando habilitado, recusa argumentos diferentes do envelope local validado; a opção default False é legado para a suíte existente e **não é a configuração recomendada ao coordenador** |
| InteropRequestMapper.openhands_event | Transporta apenas conversa/event_id/parent_id/kind/source/sequence; sem conteúdo, ferramenta ou credencial |
| OpenHandsEventBridge | Confere conversa autenticada pelo hospedeiro, principal, work_item, capability OpenHands, payload de metadados, replays, ordem e PolicyDecision; nunca executa action events |
| ToolHiveMCPBoundary | Exige MCPClient explicitamente injetado, grant server/tool, PolicyDecision e request.arguments exatos; bloqueia secret-like keys/strings em output, restringe conteúdo a text e classifica resposta inválida como UNCERTAIN |

O catálogo oferece **integridade de snapshot para comparação/auditoria**
via SHA-256, não autenticidade de editora ou assinatura de supply chain.
Nenhuma versão selecionada do ACP Registry pode ser iniciada automaticamente:
ACPStdioTransport.launch ainda exige executável absoluto existente,
argv_sha256, cwd_roots, executable_paths e autorização atual. Mesmo o
catálogo clonado local deve passar por aprovação independente de hash,
proveniência e sandbox antes de uso.

OpenHandsEventBridge não substitui o SDK, não grava conteúdo, não reconecta
conversas remotas e não processa comandos: trata action/observation/message/
streaming_delta como **metadados não privilegiados**. A fonte pode incluir
parent_id e source hook, como nos tipos oficiais; mensagens completas não
são reencaminhadas. Rejeita qualquer campo explícito de credencial no
evento de entrada. Deltas são efêmeros: não prometemos persistência de
conteúdo OpenHands nem reconstrução de conversas.

### Matriz de incorporação e sobreposição

| Clone | O que incorporar agora | Necessidade no SENTRA pessoal/entre amigos | Sobreposição que deve ser evitada |
|---|---|---|---|
| agent-client-protocol | **P0:** stdio v1 + sessões/prompt/stream/cancel, com policy; fixture local validado | Necessário para aceitar agentes ACP compatíveis | Não recriar o processo de autorização/terminal do SENTRA |
| acp-registry | **P1:** somente catálogo offline pinado, seleção versão/canal e manifest auditable | Útil na descoberta, **não necessário para executar** agentes já configurados | Não criar instalador autônomo ou autoexecução de pacotes remotos |
| a2a | **P1:** envelope, identidade, estado/artefatos e cancelamento, gateway autenticado futuramente | Útil só para agentes externos/entre dispositivos; hoje boundary local | Não duplicar WorkItems, run ledger e scheduler do SENTRA |
| mcp-typescript-sdk | **P1:** shape/protocolo de calls e responses, clients injetados de forma opcional | Necessário para tools MCP somente quando se usar provider conectado | Não criar novo host MCP de permissões paralelas |
| toolhive | **P1 opcional:** isolamento/operacionalização de servidor MCP já aprovado, endpoint/policy boundary | Útil se hospedar muitos servidores; **nenhum daemon obrigatório** | Não delegar grants SENTRA ao ToolHive nem replicar seu gestor de workloads sem necessidade |
| openhands-agent-sdk | **P1 opcional:** envelopes de eventos, observabilidade de turnos, provider boundary | Útil se um provider OpenHands for expressamente escolhido | Não importar o Agent Server inteiro nem segundo canvas/orquestrador |
| activepieces | **P2 opcional:** catálogo de connectors/pieces ou MCP endpoints aprovados, sem autoimportar fluxos | Só necessário para muitas integrações SaaS/no-code; inexistente requisito obrigatório hoje | Seu engine de flows, schedulers, aprovação e storage duplicam orchestrator/, sentra_mcp/services/durable |
| langgraph | **P2 opcional:** execução de **subgrafo interno de um único agente**, retornando OperationResult ao SENTRA | Útil se agentes exigirem estados/revisões complexos; não exigido para canvas multi-agente atual | Graph planner, memory, replays e checkpoint de LangGraph não podem substituir autoridade de WorkItems/ControlStore |
| temporal | **P3 adiar:** estudar garantias de history/replay e workers para implantação multi-node de alto volume | **Não necessário** no escopo pessoal/entre amigos atualmente | Durable workflow, timers, retries, workers e history replicam sentra_mcp/services/durable e orchestrator/ |

**Decisão:** nenhum dos três (Activepieces, LangGraph e Temporal) é
pré-requisito para fechar o SENTRA atual. Activepieces é o primeiro candidato
**apenas se houver demanda concreta por conectores externos não atendidos**
(com controles MCP e LGPD); LangGraph é opção local para raciocínio de um
provider, não dono do controle; Temporal só se testes de confiabilidade
multi-node do SENTRA indicarem lacuna estrutural sem solução incremental.
Adotar as três plataformas como runtimes soberanos duplicaria dados,
autorização, agendamento, retries e observabilidade, elevando muito o risco.

### Handoff ao coordenador

1. Criar Machine com capabilities explícitas ACP/A2A/MCP/OpenHands e
   InteropGate com callback de PolicyDecision real (nunca policy None).
2. Gerar pedidos pelos métodos InteropRequestMapper sob principal autenticado;
   o resultado de mapper.authorize é **preflight**, não substitui
   ExecutorRegistry.submit/gate.execute no instante de execução.
3. Instanciar A2ATaskBoundary com trusted_agents e
   require_mapped_arguments=True; context_id deve corresponder ao work_item_id
   de um workspace autorizado. Não confiar em Agent Cards remotos.
4. Instanciar OpenHandsEventBridge com conversa e work item autenticados
   externamente, conferir event.metadata em OperationRequest, e não
   executar conteúdo bruto recebido por SDK ou websocket.
5. Injetar apenas MCPClient já autenticado e autorizável; não fazer descoberta
   de rede automática nem registrar endpoints de registry como servidores.
6. Reconciliar journal, leases, fencing e effects UNCERTAIN via autoridade
   durável do SENTRA; nenhuma destas interfaces garante exactly-once
   cross-process. Para validação final de terceiros reais, exigir serviço
   isolado, hashes assinados/proveniência, política por workspace e teste
   explícito de revogação.

 
## SPRINT 3x3 CRIT-002 — 3 integrações E2E LOCAIS verificáveis

Classificação: **IMPLEMENTADO COM E2E LOCAL EM FIXTURE INDEPENDENTE**, NÃO
**PRODUÇÃO E2E VALIDADA**. Sem Codex/Antigravity/OpenHands real, sem ToolHive
real, sem A2A externo, sem npx/uvx, credenciais de usuário ou rede pública.

### Fatia 1 — ACP v1 stdio, recuperação local

Arquivos: sentra_interop/acp.py, sentra_interop/acp_local.py,
tests/unit/test_sentra_interop_sprint3_acp.py.
Métodos: ACPLocalLifecycle.start, .prompt, .updates, .cancel, .reconcile,
.close; ACPLocalLedger.reserve, .finish e .reconcile.

O teste parametrizado em 26 rodadas inicia em cada uma DOIS subprocessos
Python separados via sys.executable apontando para agente fixture em tmp_path.
O primeiro realiza launch autorizado por PolicyDecision pinada por executável
absoluto, cwd, SHA256 de argv e ambiente vazio; initialize, session/new,
prompt, session/update, cancel/timeout ou roundtrip; reconciliação e cleanup.
A segunda sessão só é iniciada após novo OperationRequest explicitamente
autorizado. Na rota roundtrip, pedidos fs/write_text_file, terminal/create,
tools/call e session/request_permission vindos do agente recebem -32601.
Nenhum arquivo sentinela é escrito. A rodada confirma PID finalizado.

O ledger SQLite local armazena somente fingerprint SHA256, estado e PID
informativo; não registra prompts ou segredos. Reservas são transacionais e
impedem retry automático por operation_id e idempotency_key mesmo após
reiniciar o controlador. Operações IN_FLIGHT após restart viram UNCERTAIN,
não SUCCEEDED. Não implementa session/load, attach/retomada de PID remoto,
exactly-once distribuído ou ownership de árvores de processos netos.
SQLite local não substitui ControlStore/fencing da autoridade SENTRA.

### Fatia 2 — A2A HTTP loopback autenticado

Arquivos: sentra_interop/a2a_loopback.py, sentra_interop/a2a.py,
tests/unit/test_sentra_interop_sprint3_a2a.py.
Métodos: A2ALoopbackServer.start/close/_route,
A2ALoopbackClient.request, A2ATaskBoundary.accept/state/cancel.

Servidor e cliente usam TCP real da stdlib asyncio com bind *somente*
127.0.0.1 e porta efêmera: NÃO há acesso de rede pública. Todas as rotas
exigem token de fixture temporário aleatório (32+ chars), comparado em tempo
constante, incluindo Agent Card fixo no host. POST /v1/events recebe
A2A Task/statusUpdate/artifactUpdate, principal/contexto/AgentIdentity
derivados exclusivamente do host autenticado, sequence e idempotência.
GET /v1/tasks/{id} consulta status; GET /v1/tasks/{id}/artifacts retorna
artefato text/data validado; POST /v1/tasks/{id}:cancel exige autorização
e usa ACK de peer **local de laboratório**, com replay sem novo efeito.
Testes negam token inválido, workspace divergente, mensagens fora de ordem,
revogação, cancelamento de tarefa terminal e chamadas após close.
Envelope limitado, file URI rejeitada, sem fallback.
Não é implementação plena de gateway A2A remoto/Agent Card assinado/TLS,
streaming/SSE, nem conexão com agentes externos.

### Fatia 3 — MCP JSON-RPC stdio e ToolHive boundary

Arquivos: sentra_interop/mcp_stdio.py, sentra_interop/mcp.py e
sentra_interop/gate.py (pinning habilitado para mcp:launch),
tests/unit/test_sentra_interop_sprint3_mcp.py.
Métodos: MCPStdioClient.launch, .initialize, .list_tools,
.call_tool_authorized e .close, ToolHiveMCPBoundary.call.

Servidor Python fixture local separado em tmp_path; protocolo JSON-RPC 2.0
stdio, versionamento MCP 2025-06-18, initialize, notifications/initialized,
tools/list, tools/call, notifications/cancelled e erro de método não
suportado -32601 para roots/list iniciado pelo servidor.
Política mcp:launch exige executable_paths, cwd_roots, argv_sha256 pinados.
O boundary exige MCPToolGrant por server/tool/capability, argumentos exatos,
workspace, PolicyDecision e valida payloads/respostas; resultado isError
vira FAILED, timeout vira UNCERTAIN sem retransmissão. Os testes exercitam
echo/fail/slow, dedupe, ausência de fallback, revogação e child cleanup.
O cliente de laboratório bloqueia call_tool() diretamente; somente
call_tool_authorized com OperationRequest e política atual permite RPC.
Não há daemon ToolHive, client TypeScript SDK, endpoint remoto autenticado,
nem prova de isolamento OS contra subprocessos filhos arbitrários.

### Handoff e limites

As três fatias são locais, não autorizam habilitação de produção.
A ligação coordenada aos grants de AuthorizationService, ExecutorRegistry
e ControlStore deve preservar OperationRequest, idempotency_key, scope,
lease/fencing, cancelamento e reconciliação durável antes de conectar
Canvas/CLI. A policy de launch precisa comparar argv_sha256 com um hash
aprovado por fonte confiável, e não calculado cegamente de valores remotos.

ExecutorRegistry e ControlStore NÃO foram duplicados ou alterados aqui.
Somente teste de subprocessos diretos e loopback; nenhum serviço terceiro
foi instalado ou iniciado. A2A loopback é HTTP sem TLS por estar isolado em
127.0.0.1, não é apto a interface pública. Operações UNCERTAIN nunca devem
ser automaticamente repetidas por um host novo.

Comando PowerShell (raiz do repo):
  $cases = Get-ChildItem tests/unit -Filter 'test_sentra_interop_*.py' -File
  python -m pytest -q --tb=short ($cases | ForEach-Object FullName)
  python -m compileall -q sentra_interop


## SPRINT 3×3 — Fase 2 CRIT-002 (três slices NOVOS e independentes)

Escopo EXCLUSIVO: sentra_interop/ e tests/unit/test_sentra_interop_*.py.
Não há código upstream copiado, instalação/execução de SDK externo,
segredo SaaS, servidor público, scheduler Temporal, execução de LangGraph
ou conexão a um Activepieces/OpenHands real. Todos os sockets de laboratório
escutam apenas 127.0.0.1; subprocessos são Python fixtures controlados.

### 1. Activepieces: webhook/action HTTP local, autenticação e grants

Arquivos: activepieces_loopback.py e
tests/unit/test_sentra_interop_phase2_activepieces.py.
Métodos: ActivepiecesLoopbackServer.start/_handle/close,
ActivepiecesActionClient.call.

O connector usa um contrato HTTP JSON *próprio do SENTRA para laboratório*,
NÃO declara ser a API nativa oficial do Activepieces. Cada request exige
Bearer temporário de teste de 32+ caracteres, na memória, sem gravar segredo;
hmac.compare_digest, método/caminho fixos, argument keys allowlisted, payload
JSON <= 32 KiB e principal/workspace derivados do host autenticado. O
SENTRA InteropGate aplica grant atual tanto no cliente quanto no servidor.
Os journals distintos impedem repetir a mesma ação em ambos os lados:
duplicate -> receipt sem novo efeito; timeout/erro/parsing inválido depois
de possível efeito -> UNCERTAIN, sem resend. O teste de rede TCP real cobre
roundtrip, dedupe, payload fora da allowlist, outro workspace, Bearer
incorreto, resposta malformada, timeout remoto, revogação, ausência de
fallback após encerramento e contagem de ações efetivamente invocadas.
Os handlers são apenas funções async de fixture de teste; nenhuma integração
SaaS ativa, trigger externo ou fluxo de produção foi executado.

### 2. OpenHands Agent SDK: stream tipado sobre processo local pinado

Arquivos: openhands_local.py (novo), openhands.py (EventBridge preexistente),
tests/unit/test_sentra_interop_phase2_openhands.py.
Métodos: OpenHandsLocalStream.launch/start/attach/artifacts/cancel/close;
OpenHandsEventBridge.accept/observe.

O agente fixture Python independente imprime JSONL com campo version=1,
handshake de conversation_id e sequências de eventos event/artifact,
tool_request, cancel_ack e done. **Esse fio local é um contrato de teste
conservador, NÃO é o protocolo de transporte oficial do SDK OpenHands.**
Gate exige openhands:launch, argv_sha256/executable_paths/cwd_roots fixos
e env vazio, além de scopes/grants para openhands:start/event/artifact/read
e cancel. Cada evento é tipado via OpenHandsEvent.from_mapping e persistido
em memória somente como metadado por OpenHandsEventBridge, que revalida a
política. Artefatos text <= 16 KiB, digest SHA-256 e grant específico.
Reattach autorizado ocorre somente com cursor no MESMO processo vivo,
não recria effects nem é recovery cross-processo. Tool_request do agente
recebe tool_denied incondicionalmente; filesystem/terminal/tools arbitrários
não são invocados. Cancelamento só é confirmado com cancel_ack do fixture;
shutdown fecha e aguarda o processo direto. Testes: stream, artefato,
parent_id, reattach após cursor, revogação read/cancel, denial cross-workspace,
tool denial sem sentinel e limpeza. SDK remoto e Agent Server não foram usados.

### 3. LangGraph/Temporal: bridge subordinate de subworkflow durável local

Arquivos: workflow_bridge.py (novo) e
tests/unit/test_sentra_interop_phase2_workflow.py.
Métodos: SubagentWorkflowBridge.run_step/checkpoint/reconcile,
_reserve/_finish (checkpoints SQLite com BEGIN IMMEDIATE e compare-and-swap).
O workflow **não** agenda jobs autonomamente, não toma posse do WorkItem
e não possui segundo ExecutorRegistry. Um WorkItem + OperationRequest
SENTRA de capability workflow:step, principal/workspace/machine/step_id e
checkpoint_version=1 são obrigatórios em cada etapa. Antes de cada worker
há check de PolicyDecision, reserva única de operation_id/idempotency_key/
(workflow_id,step_id) e rechecagem no InteropGate. Checkpoints schema=1
têm revision global e revision por etapa; escritas condicionais por CAS.
Resultado contém apenas digest SHA-256 de recibo validado, sem credenciais.
O teste executa de verdade DOIS subprocessos Python fixtures como efeitos
assíncronos de dois workers concorrentes e prova sobreposição dos tempos
de trabalho. Reinicializa outro objeto com a mesma base SQLite, confirma
estado SUCCEEDED e nega replay. Outros testes cobrem dois workers tentando
a mesma etapa, scope, grant revogado durante efeito -> UNCERTAIN, timeout,
IN_FLIGHT recuperado -> UNCERTAIN e schema/work item conflitante negados.
**Não é execução do pacote langgraph nem Temporal Server.** São referências
de checkpoint sem replicar scheduler/retry engine de produção.

### Licenças e atribuição

Foram consultados os LICENSE locais:
- third_party/activepieces/LICENSE: código-base MIT Expat, com exclusões
  explícitas para packages/ee e server/api/src/app/ee, licenciadas
  separadamente; **não** copiamos fonte desse repositório.
- third_party/openhands-agent-sdk/LICENSE: MIT, copyright OpenHands
  contributors (2026); o EventBridge é implementação local independente.
- third_party/langgraph/LICENSE: MIT, copyright LangChain, Inc. (2024);
  sem importar framework ou copiar implementação.
- third_party/temporal/LICENSE: MIT, copyright Temporal Technologies
  (2025) e Uber Technologies (2020); sem servidor executado.

A revisão documental não substitui análise de licenças por arquivo em
eventual redistribuição comercial. Os novos módulos são implementações
originais de boundary baseadas em interfaces públicas; não há assets nem
arquivos upstream copiados.

### Handoff e o que FALTA para produção

* Substituir policy fixtures por AuthorizationService -> PolicyDecision
  atestado; principal, scope, WorkItem e capability são parâmetros
  emitidos pela autoridade SENTRA, nunca inferidos de mensagens remotas.
* Fazer integração coordenada com ControlStore/ExecutorRegistry, leases,
  fencing e journal durável único; os SQLite locais de laboratório
  não garantem exactly-once distribuído.
* Tornar explícito quem controla processos/netos e revoga operações externas;
  um grant revogado não desfaz um efeito remoto já iniciado.
* Para Activepieces real: implementar auth/protocolo próprio da API em rede
  aprovada com webhook HMAC, tenant/workspace e política de egress.
* Para OpenHands SDK real: mapear eventos do SDK e lifecycle oficial,
  assinar/autenticar o endpoint, sandbox real e lifecycle de reconnect.
* Para LangGraph/Temporal: não promover uma segunda autoridade; integrar
  checkpoints e results como evidência subordinada às Operations SENTRA.
* Nenhuma das três fatias deve ser rotulada PRODUÇÃO E2E VALIDADA sem
  prova de serviço real autenticado e integração real com Canvas/CLI.


## SPRINT 3×3 FASE 3 / CRIT-002 — três fatias novas E2E LOCAIS

Nesta fase foram implementadas **exatamente três novas fatias**, sem repetir
as fases ACP stdio, A2A HTTP task, MCP Python stdio, Activepieces, OpenHands
e bridge de workflow. Escopo exclusivo: sentra_interop/ e
tests/unit/test_sentra_interop_*.py. Não executar npx/uvx/SDK upstream.

### 1. MCP TypeScript SDK — compatibility bridge via Node fixture real

Arquivos: mcp_sdk_compat.py, mcp_stdio.py (extensão da allowlist de métodos
read-only e mínimo SystemRoot Windows), test_sentra_interop_phase3_mcp_sdk.py.
O subprocesso local é Node 24, com programa .cjs emitindo JSON-RPC 2.0 por
stdio e protocolo MCP pinado em 2025-06-18. Testa initialize,
notifications/initialized, tools/list, tools/call com grants do
ToolHiveMCPBoundary, isError => FAILED, resposta JSON-RPC error => UNCERTAIN
sem retry, resources/list, resources/read de URI estritamente allowlisted
sentra://fixture/help, prompts/list/get do prompt allowlisted summarize.
Request iniciado pelo servidor roots/list recebe -32601; nenhum privilégio
fs, terminal, sampling ou roots é oferecido. O transporte bloqueia tools/call
direto, exige OperationRequest e PolicyDecision recente. Recursos/prompts
não incluem URLs externas, file://, anexos ou conteúdo binário; resposta
text/plain até 16 KiB. Paths/cwd/argv pinados no spawn, sem shell, PATH,
npm ou tokens. Node para Windows necessita apenas a variável de sistema
SystemRoot obtida via GetWindowsDirectoryW (não herda ambiente do usuário);
fora do Windows o ambiente permanece vazio.

**Evidência de upstream:** snapshot third_party/mcp-typescript-sdk, contrato
de client/tool/resource/prompt conforme documentação. O snapshot NÃO possui
node_modules ou dist instalados no host; não foi instalado SDK e o teste é
interop com **fixture Node escrita localmente**, não o SDK npm real. O
licenciamento do clone está em transição MIT -> Apache-2.0, com
contribuições/documentação sob regras distintas (LICENSE local). Nenhum
código desse SDK foi copiado.

### 2. ACP Registry — verified resolver offline sem execução

Arquivos: acp_verified.py, test_sentra_interop_phase3_registry.py.
ACPVerifiedResolver.resolve recebe catálogo schema=1, publisher,
sequence monotônico, entries provider/version/executable/cwd/argv/sha256
e um autenticador HMAC SHA-256 fornecido por uma raiz EXTERNA de confiança
injetada pelo host. **HMAC não equivale a assinatura de publisher
distribuída**; somente possui autenticidade enquanto a chave simétrica
estiver protegida e houver provisionamento independente. O catálogo não
cria trust roots, não instala binários e não chama subprocessos.
Cada seleção valida digest do catálogo, assinatura constante, publisher
não revogado, provider/semver determinístico, executável absoluto dentro
de install_root, ausência de traversal, arquivo real, SHA-256 do executável
(pin de conteúdo <=100 MiB) e argv limitado; revê PolicyDecision
acp:resolve antes e dentro da transação. SQLite guarda maior sequence
e versão aceitos por provider; rollback, versão inferior, conflito de hash
da mesma sequência, payload alterado e publisher revogado falham.
Retorna VerifiedACPEntrypoint sem *poder de execução*. Para lançar,
a camada ACPStdioTransport exige autorização acp:launch independente,
pinning executable_paths/cwd_roots/argv_sha256 e sandbox aprovado.
O teste usa um binário de dados estáticos em tmp_path que não é executado.

**Limites:** o teste valida HMAC de laboratório, não assinatura pública de
upstream, não prova integridade após a seleção se arquivo substituir entre
verificação e eventual spawn (TOCTOU); sem auto-update, sem PATH, sem
npx/uvx, sem download. Upstream third_party/acp-registry é catálogo
Apache-2.0; implementação original local sem cópia de código.

### 3. A2A SSE — endpoint HTTP read-only em loopback com SQLite

Arquivos: a2a_sse.py e test_sentra_interop_phase3_a2a_sse.py.
A2ASSELedger.append recebe somente OperationRequest a2a:sse_publish
com principal/work_item/task fixos, payload {state,text}, limite, gate
SENTRA antes e após efeito, operação/idempotency_key únicos e SQLite
com sequence por task estritamente crescente. Persistência real no fixture,
reabertura da conexão/banco sem replay do efeito após o restart.
A2ASSEServer escuta exclusivamente 127.0.0.1 porta efêmera; aceita SOMENTE
GET /v1/tasks/{task}/events, Bearer fixture (hmac.compare_digest),
X-Principal, X-Work-Item, Last-Event-ID inteiro válido e policy a2a:sse_read
revalidada antes de cada evento ou heartbeat. Replay tem janela máxima 8,
responde 409 quando excedida ou cursor avança indevidamente. Framing SSE:
id: <sequence>, event: task-status, data: JSON, heartbeat por comentário.
Backpressure usa writer buffer <= 8*4096 bytes e drain(timeout .25s).
Canal fecha no status terminal canceled/completed/failed, revogação ou
prazo máximo de 2 segundos; close() recolhe conexões.
A2ASSEClient usa socket TCP real para teste de stream/resume/cancelamento.
**Read-only na rede**: servidor não oferece POST, ferramentas ou comandos.
Teste de slow-consumer inclui writer sintético cujo buffer excede o
limite, além de replay real saturado na rede.

**Limites:** não é servidor A2A completo, não há TLS público, agent-card
assinado, SSE remoto autenticado, EventSource browser, streaming multi-node,
tarefas entre agentes terceiros ou reconciliação distribuída. O SQLite
local é fixture de laboratório; autoridade ControlStore/SENTRA continua
externa. Upstream third_party/a2a/LICENSE: Apache-2.0; sem código copiado.

### Matriz final de aceite

| Slice Fase 3 | Estado local | Bloqueio de produção |
|---|---|---|
| MCP TS compatibility | [E2E LOCAL] Node stdio JSON-RPC | [PROD BLOQUEADO] npm upstream ausente, sem servidor MCP externo autenticado |
| ACP verified resolver | [E2E LOCAL] manifesto/arquivo/SQLite e negativos | [PROD BLOQUEADO] PKI/assinatura real, secure install, TOCTOU, sandbox do executável |
| A2A SSE read-only | [E2E LOCAL] HTTP loopback/TCP/SQLite | [PROD BLOQUEADO] ControlStore, TLS/identidade remota, operação distribuída e auditoria |

Importante: somente SENTRA PolicyDecision/InteropGate determina autoridade.
Nenhuma dessas fatias cria ExecutorRegistry, AuthorizationService ou outro
scheduler. UNCERTAIN nunca autoriza resend. Resultados sob fixtures NÃO são
evidência de produto externo funcionando em produção.


## CRIT-002 — Integração à autoridade central real: bloqueio P0 confirmado

STATUS: módulo central.py ligado a ControlPlaneService, AuthorizationService,
GovernanceService, DurableRunService e ExecutorRegistry REAIS com SQLite de
teste; EXECUÇÃO DE EFEITOS REMOTOS INTENCIONALMENTE BLOQUEADA.

### Diagnóstico da API central

- sentra_mcp/services/durable.py: DurableRunService.create_operation
  persiste run_id, owner e idempotency_key, mas não reserva um fingerprint
  completo de OperationRequest de forma atômica com fence.
- DurableRunService.acquire_lease e update_operation(resource_key,
  fencing_token) verificam leases, mas não equivalem a reserva da intenção
  completa com fencing no mesmo boundary de efeito.
- sentra_runtime/durable_admission.py: DurableOperationGate EXIGE
  DurableIntentAuthority.reserve_intent(), fence_active() e record_result().
  DurableRunService não implementa estes três métodos.
- Não foi criada segunda autoridade de grants, ledgers ou scheduler.
  A autoridade existente é BoundWorkItemPolicy, apoiada no SQLite
  AuthorizationService e GovernanceService e suas trilhas de auditoria.

### Código entregue

sentra_interop/central.py: CentralInteropAdapter(control, run_id, owner,
machine) requer ControlPlaneService real. decision(request) verifica
pertencimento WorkItem->Run, estados, capability e BoundWorkItemPolicy.
register(existing_registry) liga ao ExecutorRegistry do host;
registry() cria um registro opt-in para testes locais. start(request)
nega qualquer efeito externo quando falta reserva/fencing atômicos:
estado FAILED, razão MISSING_ATOMIC_INTENT_RESERVATION_AND_EFFECT_FENCE.
Após grant válido registra somente um recibo de NEGAÇÃO em tabelas centrais
durable.create_operation/update_operation(state=FAILED), progress com hash
da intenção e work_item_id. Esse recibo NÃO é permissão de execução nem
pretende reter a intenção para posterior replay. Mesmo após futura inclusão
da API durável, efeito permanece bloqueado até fiscalização do fencing
na fronteira física de I/O. observe/reconcile leem recibos sem repetir
efeitos; cancel/cleanup não criam efeitos não autorizados.

### Exatamente 3 testes integrados com serviços SQLite reais do SENTRA

tests/unit/test_sentra_interop_central_real.py:

1. ACP Verified Registry: cria Run/Agent/WorkItem reais do ControlPlaneService,
   obtém grant persistido acp:resolve, verifica HMAC e hash de arquivo local;
   com grant acp:launch submete via ExecutorRegistry oficial. O resultado
   é FAILED e o DurableRunService central registra motivo exato.
   Um novo adaptador reconcilia o recibo central. Não inicia agente: falta
   reserva/fence, portanto nenhuma escalada fs/terminal foi possível.
2. A2A loopback + SSE: dois clientes com tokens/identidades distintas usam
   sockets reais 127.0.0.1. Leitura SSE heartbeat utiliza grant persistido
   a2a:sse_read, outro WorkItem/identidade é negado; grant revogado interrompe
   stream e nega reconexão. Envio a2a:ingest via ExecutorRegistry oficial
   falha antes de qualquer evento/artefato ser gerado.
3. MCP/ToolHive + OpenHands/Activepieces: capacidades e grants persistidos
   mcp:echo, openhands:start e activepieces:echo são checados pelo
   ExecutorRegistry oficial; todos efeitos remotos são FAILED com audit
   receipt no SQLite central; revogação bloqueia chamadas adicionais.
   Listener Activepieces real em loopback permanece sem chamadas action.
   Node fixture stdio real permite read-only initialize e tools/list via
   grant mcp:list autoritativo, mas não recebe tools/call; grant revogado
   impede descoberta posterior.

### Handoff mínimo P0 para core e host (fora do escopo CRIT-002)

1. ControlStore central: implementar e provar atomicamente
   reserve_intent(run_id, owner, request, intent_sha256) -> IntentReceipt,
   fence_active(receipt), record_result(receipt, result), comparando
   fingerprint completo e idempotency_key, com fences monotônicos,
   recuperação de crash, grant vigente e replay proibido para UNCERTAIN.
2. Executor de efeito físico: impor o mesmo fencing_token no instante do
   I/O, com cleanup/reconcile. Quando estes contratos existirem, host
   chama CentralInteropAdapter.register(existing_registry) e adiciona
   dispatch protegido via DurableOperationGate; até lá, start() permanece
   fail-closed.

Classificação: INTEGRAÇÃO REAL DE CONTROLE / E2E DE NEGAÇÃO LOCAL.
NÃO é E2E de execução externa, nem integração Codex/Antigravity, A2A SaaS,
ToolHive daemon ou OpenHands SDK externo. Nenhum core, Canvas, executors
ou auth foi alterado pela CRIT-002.


### Evidências executadas nesta integração central

Windows/PowerShell no root C:\Users\vitor\OneDrive\Desktop\SENTRA:
- python -m pytest -q --tb=short tests/unit/test_sentra_interop_central_real.py
  -> 3 passed (Run, Agent, WorkItem, grants e Durable Operation em bancos
  reais do ControlPlaneService, mais servidores HTTP/SSE em loopback e
  Node stdio somente leitura; operações com efeito são negadas).
- Suíte combinada tests/unit/test_sentra_interop_*.py, mais os arquivos
  test_sentra_runtime_authority_bridge.py,
  test_sentra_runtime_durable_admission.py e
  test_sentra_executors_registry.py -> 164 passed em 22.62s.
- python -m compileall -q sentra_interop -> sucesso.
- Oito rodadas adicionais de test_sentra_interop_central_real.py ->
  8 x 3 = 24 passed, 0 failures, 0 Node fixture orphan PIDs.
- Estado Git: sentra_interop/ e tests/unit/test_sentra_interop_*.py
  ainda UNTRACKED (??), sem reset, clean ou commit.

Prova negativa vinculada ao ControlStore é pré-condição de segurança:
ainda que o grant real exista e WorkItem esteja RUNNING, operação que
produziria efeitos fora do processo deve ser recusada até a entrega da
reserva atômica e do enforcement físico. Um recibo FAILED no SQLite é
a evidência de NÃO execução; não representar como SUCCEEDED ou E2E
operacional. O Node fixture foi criado pelo próprio teste e executou
apenas initialize/tools/list, não foi iniciado como efeito SENTRA.
