# Codex — composição da implementação integral

Implementação em andamento. Nenhum teste, lint, benchmark ou QA executado.
O usuário autorizou uma exceção visual: dependências e assets materializados para
abrir a interface em estado isolado. Registro em `PREVIEW_AUTORIZADO.md`; isso
não libera a validação geral. O processo de preview PID 47408 permanece intocado.
Checkpoint inicial `3639a2e` confirmado na main local e em origin/main por
`git ls-remote`. A regra de validação apenas ao final continua vigente.

## Código concreto adicionado pelo principal

- `sentra_canvas/__main__.py`: POST bearer `/api/shell/bridge`, limite de corpo
  específico, URL do sidecar apenas em document_session e conflitos CAS HTTP 409.
- `sentra_canvas/service.py`: composição de `ControlPlaneService.shell` e
  `CanvasShellRuntime`; documentos e callbacks do sidecar; ProjectReviewService
  com root derivado de workspace autenticado; kinds de execução/interoperabilidade.
- `sentra_canvas/shell_runtime.py`: resolve/admissão/atualização de Dots pelos
  mesmos agentes Canvas e Control Plane; coordenação estruturada; fila protegida
  no namespace central shell; CLI real com conversation_id persistente; recibos
  de respostas no journal protegido; operações interrompidas ficam incertas e
  não são reenviadas; encerramento preserva posse se workers não terminaram.
- `docs/integral/COORDINATOR_TERMINALS.md`: seis sessões OpenCode retomadas em
  interface interativa persistente; modelo gratuito e esforço high confirmados.
- `sentra_canvas/shell_requests.py`: reserva protegida/fingerprint antes de efeitos
  de host, replay do resultado e estado incerto sem reenvio após interrupção.
- `sentra_canvas/shell_machines.py`: sete ações exatas de máquinas/InputControl/viewer;
  Operation IDs derivados do request_key; WorkItem, agente, grant, projeto e Run
  conferidos; status da sessão Guacamole precisa scope_verified e transporte vivo.
  Tickets view/human, listener loopback lazy port=0/origins do CanvasServer, input
  humano por dispatch_human com epoch, revogação/encerramento dos WS próprios.
- `sentra_canvas/shell_optional.py`: VoiceRuntime e AttachmentStore usando
  control.store; configuração apenas host (`SENTRA_SHELL_CONFIG_FILE` ou env de
  voz); callbacks de disponibilidade; call/ref/upload vinculados ao projeto,
  Space e conversa; chunks/status preservam request_key e bytes rechecados.
- `service.py` e `__main__.py`: raw POST `/api/interop/webhook/<machine_id>`
  limitado a 1 MiB; factory A2A configurada, projeto conferido antes do ingresso,
  segredo de callback/pin task/context/replay validados pelo provider. Ingresso
  só registra evidence; não despacha. Channels/registry na configuração existente.
- `shell_runtime.py`: binding de uso do provider instalado apenas sob lock da
  conversa ao iniciar o turno; fila concorrente não troca o WorkItem vigente.
  Recuperação de Operation SUCCEEDED publica journal/recibo verificados sem
  nova chamada ao modelo.
- `service.py`/`__main__.py`: endpoints center existentes ligados a versões,
  latest, review, upgrade e rollback da SkillLibrary com WorkItem/agente scoped;
  inventário MCPB inclui status supervision; sweep separado exige owner autenticado
  e callback host, produz tíquetes de IDs exatos sem remover contêineres;
  chat-access inclui projeção de consentimento/pendências da conversa.
- `service.py`: `_control_service` escolhe uma única fábrica configurada CP;
  `CanvasAuthorityRuntime(control)` e MachineHost recebem os mesmos serviços,
  sem construir TaskRuntime SQLite independente. Hosted ainda exige fechar
  seleção única nos subprocessos CLI/gateway (Nexo/Cobalto).
- `sentra_canvas/code_machine.py`: adapter concreto Code Mode quickjs-wasm,
  configurado/restaurado pelo mesmo MachineHost via center machine configure;
  policy/Grant/Run/WorkItem/budget central, source/results protegidos por intenção,
  inner tools allowlisted e fenced, resultado privado conferido com receipt da
  Operation SUCCEEDED. Inventory/PROPOSED não afirmam execução A08. Artefato/SBOM
  e wasmtime continuam pendentes de materialização final; nenhuma execução feita.
- `sentra_canvas/shell_code.py`: code_propose/execute/cancel usam machine_execute
  central, source/WorkItem/proposal scoped e request_key; code_status/discovery
  lêem o factory configurado. Status A08 exige receipt central SUCCEEDED, não
  somente linha local de execução nem nome do engine.
- `sentra_mcp/server.py`: factory ControlPlaneService.from_store fornece
  durable/context compartilhados também ao MCP, sem criar autoridade SQLite
  independente no caminho hospedado.

## Contrato contextual de máquinas — fonte composta, execução ainda não homologada

Envelope: `action`, `project_id`, `request_key` por mutação; `space_id` e
`conversation_id` opcionais conferidos. Campos owner/principal/resource/grant
e Operation ID de mutação não vêm do renderer.

| Ação | Campos específicos |
|---|---|
| machine_list | nenhum |
| input_status | machine_id, work_item_id?, capability_id? |
| input_handoff | machine_id, holder, expected_epoch, ttl_seconds?, work_item_id?/capability_id?/arguments? para agent |
| remote_viewer_open | machine_id, work_item_id, capability_id?, session_id, control_mode=view ou human, expected_epoch apenas human |
| remote_viewer_close | viewer_id |
| machine_execute | machine_id, work_item_id, capability_id?, arguments |
| machine_observe | target_operation_id |

Viewer retorna ws_url/viewer_id/scope IDs/control_mode/input_epoch/TTL30/max300/
single_connection/input_channels/grant_status. Capability omitida só é derivada
quando há exatamente uma capability no vínculo máquina/WorkItem. Tickets e
resultados privados no journal são protegidos; a URL não é gravada em log.
Reabrir após expiração exige novo request_key. Fechar não deleta sessão do OS.
Não houve startup do listener nem rebuild da UI nesta composição.

## Contratos e composição ainda necessários

- Nexo: resolver UsageLedger pela tabela `canvas_shell_provider_bindings`
  no namespace shell. Campos: owner, project_id, workspace, conversation_id,
  run_id, work_item_id, operation_id, agent_id, principal. Validar todos os
  vínculos e estados atuais antes do custo/chamada; nunca fallback cli separado.
  Implementado por Nexo; binding protegido e lifecycle ainda requerem etapa final.
- Nexo: reassign_work_item transacional preservando alvo, permissões e Run.
  Rever identidade do agente ao criar nova Run após terminalidade: os Dots
  continuam os mesmos e não devem duplicar agentes nem conflitar IDs centrais.
  Implementado por Nexo; hosted factory e TaskRuntime sem autoridade SQLite
  paralela permanecem em composição.
- Brisa/Rastro: anexos scoped, protegidos, upload real com receipt independente
  e dispatcher multimodal ligado à fila central; não aceitar mero READY_LOCAL.
  Storage/chunks estão compostos. Helper inicial de Rastro que dividia N imagens
  em N envios do prompt foi devolvido para ajuste: message_send precisa um turno
  com o conjunto de anexos, admission e recibo correspondentes, sem split implícito.
  PDF e outros tipos anunciados continuam requisitos de transporte do modelo.
- Brisa: voz com protocolo de provider real, recibos verificados pelo servidor,
  callbacks de disponibilidade, consentimento, stop/revoke/recovery.
  Callbacks/provider estão compostos; Nexo implementa fence/lifecycle central dos
  efeitos opcionais. Recibo local de armazenamento/signaling não prova conclusão
  externa. Transcrição provisional não confere tool execution.
- Pulso: registrar facade allowlisted após owner canonical, scope, fingerprint
  e reserva antes de efeitos; configurar workflow runtime e callbacks reais.
- Lume: compor protocolos/elicitation/registry e webhook bruto assinado de canais.
- Forja: compor InputControl, viewer Guacamole, novos recursos de execução nas
  superfícies HTTP/CLI/MCP. Configuração e Grants continuam server-side.
- Pacto: compor lifecycle/consentimento/Skills/Code Mode e distribuir guest
  QuickJS real com ABI, hashes e SBOM; subset JS não substitui o requisito.
- Selo: ligar políticas, identidade, auditoria, learning, Langfuse e release gates.
- Vitra: ligar runners/configuração/setup/backup/migração/update/distribuição;
  provenance extension/Web Models e manifests depois das alterações dos donos.
- Prisma/Tessela: bundle final e superfícies principais/refinamento; instalar
  dependências e materializar somente quando todas as implementações estiverem
  completas, conforme a ordem expressa do usuário.

Ainda faltam implementação e composição em várias frentes. Relatórios de
agentes não representam aceitação integral. A matriz de Meridiano permanece
aberta até confronto de todos os requisitos com evidência no estágio final.

## Transferência após quota OpenCode

O usuário autorizou UM Codex adicional gpt-6.1-sol high. Cobalto ficou inicialmente
com as seis frentes OpenCode, com tarefa `tasks/Cobalto.md` e status inicial
`Cobalto-status.md` (fontes atuais por domínio, código faltante, composição e
ambiente). Os terminais/históricos originais foram preservados, sem reiniciar
trabalho perdido. Donos Codex ativos e composição root mantêm seus arquivos.

Depois o usuário pediu redistribuir aos Codex disponíveis. A tabela corrente é
`REDISTRIBUICAO_CODEX.md`: Cobalto Brisa/Rastro, Prisma Pacto, Lume Pulso,
Forja Selo, Tessela Vitra, Nexo núcleo e Meridiano backlog de todas as cláusulas.
`maestri check` confirmou os quatro implementadores trabalhando nas novas frentes;
handoff dos arquivos já alterados registrado em `Cobalto-handoff.md`.
Nenhum terminal novo foi aberto nesta redistribuição e nenhuma validação liberada.
