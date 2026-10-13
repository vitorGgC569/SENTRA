# Forja — implementação de executores e composição integral

Data: 2026-10-11. Projeto: `C:/Users/vitor/OneDrive/Desktop/SENTRA`.
Base informada pelo coordenador: checkpoint `3639a2e` em `origin/main`.

**Implementação entregue; validação e aceitação operacional pendentes da liberação
coordenada.** Não executei testes, build, lint, benchmark, QA, serviços, browsers,
Hyper-V/HCS/runsc, cliente RustDesk ou aplicações do usuário. Não fiz commit,
push/reset/stash, recrutamento, uso de skill/MCP SENTRA nem alterações em arquivos
de outros donos. Os testes novos abaixo foram somente escritos.

## Requisitos e fontes de domínio

Lidos contrato shell e plano integral de 11/10, nota Maestri
`todos-os-projetos-ja-estao-clo`, estudos de absorção/checkpoint/Chat On Steroids e
as seções pertinentes completas da auditoria/reavaliação/reuse dos projetos UFO,
Daytona, pywinauto, hcsshim, gVisor, Playwright, Guacamole, RustDesk, RPA e observação
híbrida Arena. A pesquisa OpenDots foi consultada nos fluxos de computer/browser,
VM/guest, autoridade, recovery e matriz G/A. O código atual e os handoffs existentes
foram tratados como implementação a preservar, sem usar resultados históricos
como evidência do estado desta rodada.

Referências principais:

- `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md`.
- `docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md`.
- `docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md`.
- `docs/SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md`.
- `docs/SENTRA_THIRD_PARTY_REUSE_2026-10-08.md`.
- `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md`.
- `docs/SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md`.
- `docs/SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md`.
- `C:/Users/vitor/OneDrive/Desktop/SENTRA_RESEARCH_OPENDOTS/SENTRA_OPEN_DOTS_RESEARCH.md`.
- `sentra_executors/DESKTOP_GUEST_BENCHMARK_HANDOFF_ROUND4.md` e handoffs de lifecycle/remoto.

## Entrega concreta

| Domínio | Implementação desta rodada e reutilização preservada |
|---|---|
| Composição real | `integral.configure_executor` registra e persiste os providers UIA, Hyper-V UIA/lifecycle/artefatos, HCS e runsc no `MachineHost` existente. Configuração não inicia provider nem cria Grant. |
| Posse de entrada | `InputControl` usa o mesmo ControlStore: CAS por epoch, request key/fingerprint/receipt transacionais, TTL, handoff humano/agente/none, vínculo ao WorkItem/Run/grant. `InputBoundPolicy` prende o epoch por operação e o revalida nos checkpoints físicos. |
| Exclusion física | Locks por recurso físico compartilhado impedem aliases de VM/container/desktop de sobrepor workers. Mutex Windows na sessão efetiva serializa patterns UIA, inclusive dentro do guest. Timeout do solicitante não libera o worker que ainda possui I/O. |
| UFO/Windows | `UFOApplicationActions` traduz `click/set_text/toggle/select/read` em observação e ação semântica separadas, com Operations determinísticas centrais. Mantém memória/planos centrais existentes e fornece ranking por capabilities/carga como sugestão. Não importa o dispatcher arbitrário, planner soberano ou fallback pyautogui do UFO. |
| UIA e visão | `observe.hybrid(output)` combina screenshot da janela bound e elementos UIA, observa novamente antes de publicar e rejeita divergência. Referências seguem runtime/process/desktop; password values/text não são projetados. Orçamento composto abrange todos os workers da observação. |
| Windows isolado | O caminho Hyper-V/PowerShell Direct/InteractiveToken já real foi conectado ao host por configuração persistida. GuestLease projeta a reserva/fence central; UIA executa no task protegido do guest. HCS permanece identificado como headless e não substitui o desktop isolado. |
| HCS/gVisor | Consome os providers reais existentes: bridge hcsshim pinado/config preparado, comandos exatos/resources; OCI/runsc pinado, FS/rede/processo sem privilégios, checkpoint/restore experimental e evidência. Leases projetadas do mesmo efeito central e storage privado. |
| Playwright | `PersistentPlaywrightBackend` acoplado automaticamente pelo factory: identidades/cursor/evidências em SessionJournal protegido, lista/status/events/export e recuperação explícita `LOST` após perda do processo. Nenhum relaunch/navigate/click/cookie replay para tentar recuperar. Backend Chromium/CDP/rede/captura existente preservado. |
| Daytona | Acrescenta Computer Use real pelo SDK AT-SPI: start/stop/status/observe/focus/invoke/set_value/screenshot; PID/role/name exatos, nova busca de nó antes de input e invalidação de referências. Acrescenta archive, perfis CIDR e reconciliação de rede sem retry. Preview privado é consultado no host com token oculto e publicado como Artifact bounded. PTY/comandos/stream/cancel/reattach existentes preservados. |
| Guacamole | Preserva guacd/TLS/pins/tunnel/viewer/playback reais. Acrescenta clipboard UTF-8 bounded, opt-in, separado de clipboard do host; input requer posse. Gravação key/mouse/touch/clipboard somente por seleção explícita. `record_output=false` usa buffer efêmero live e recusa export de gravação desabilitada. Playback nunca reenvia canais `input.*`. |
| RustDesk | Amplia patch da própria build pinada: pump IPC de login e key/mouse, operation-bound lease, receipt de input, heartbeat de login real via PeerInfo e snapshot do frame decodificado RGBA/BGRA para PNG/Artifact. GUI própria não injeta entrada fora das Operations; clipboard/files/audio são bloqueados. Build antiga/stock não atende controle e falha explicitamente. |
| RPA/documentos | Preserva `documents.py`/workers reais CSV/TSV/XLSX/PDF, recalculation Excel/LibreOffice e OCR configuráveis, paths e publicação atômica. `DiagnosedExecutor` conserva motivo sanitizado do provider mesmo quando a fronteira física marca UNCERTAIN. |

## Arquivos próprios novos

- `sentra_executors/integral.py`.
- `sentra_executors/input_control.py`.
- `sentra_executors/browser_sessions.py`.
- `sentra_executors/daytona_computer.py`.
- `sentra_executors/ufo_actions.py`.
- `sentra_executors/INTEGRAL_PROVENANCE.json`.
- `tests/unit/test_sentra_executors_integral_forja.py` (não executado).
- Este documento.

Arquivos próprios alterados, preservando mecanismos anteriores:

- `sentra_executors/central_integration.py`.
- `sentra_executors/uia_semantic.py`.
- `sentra_executors/playwright_browser.py`.
- `sentra_executors/daytona_sessions.py`.
- `sentra_executors/remote_guacamole.py`.
- `sentra_executors/remote_rustdesk.py`.
- `sentra_executors/remote_rustdesk_gate.rs`.
- `sentra_executors/remote_rustdesk_build.py`.
- `sentra_executors/rpa.py`.

Não alterei `goal_loop.py`, `conpty_sessions.py`, `operation_receipts.py`, benchmarks,
core/runtime, HTTP Canvas, MCP server, UI, interop ou shipping.

## Contratos finais de composição

### Configuração host-only — Nexo

```python
configure_executor(host, *, workspace_id, workspace_root, agent_id, kind, provider_config) -> dict
# Síncrono; internamente host._call(_configure_executor(...)), no loop existente.
```

`EXECUTOR_KINDS` contém exatamente:
`windows_uia_semantic`, `windows_guest_uia`, `windows_guest_lifecycle`,
`windows_guest_artifact`, `windows_hcs_native`, `gvisor_workload`.

Retorno: `machine_id/kind/workspace_id/agent_id/capabilities/actions`,
`registered=true`, `grant_created=false`, `provider_verified=false`,
`transport_ready=unverified`, `physical_resource_sha256`.

O helper registra `host._factories`/`host._inventory` e persiste `{kind,
workspace_id, workspace_root, agent_id, provider_config}` em
`host.configurations`. Não grava callback/credencial resolvida na configuração.
Restore revalida workspace/agente/root e chama o mesmo helper; não restaura
processos por PID, input lease, browser cookies ou efeitos.

Provider config possui `enabled=true`, somente dados JSON e campos do binding:

- UIA: `bindings=[{capability_id,identity,desktop,window_title,selectors,actions,...}]`.
  Paths são derivados do workspace no servidor. Uma declaração possui um desktop.
- Guest UIA: mesmos bindings + `guest` com VM GUID/hardware/transport/source pins,
  task/spool/paths, `username_ref/password_ref`; callbacks resolvem secrets no vault.
- Guest lifecycle: `guest`, `actions` exatas (`status/start/stop/snapshot/reset/prepare`).
- Guest artifacts: `guest`, `artifacts={key:absolute_guest_path}`; dispatch só escolhe key.
- HCS: `binding` com bridge/config SHA/container/commands/actions e
  `host_read_roots` explícitos para assets preparados. Paths de outputs são host-owned.
- gVisor: `binding` pinado (binary/bundle/config/program/profile/actions/mounts).
  State/checkpoints ficam no storage privado do host, nunca em grant de output do agente.

### Input/handoff — Nexo e Codex

```python
InputControl(control, *, owner, clock=time.time)
status(*, resource_id, workspace_id) -> dict
handoff(*, resource_id, workspace_id, machine_id, holder, expected_epoch,
        request_key, ttl_seconds=60, request=None) -> dict
```

`holder=human|agent|none`; request_key obrigatório <=128; TTL 1..300s.
Agente exige `OperationRequest` confiável e grant/WorkItem/Run ativos.
resource_id deriva somente de `factory._input_resources[machine_id]` no servidor.
Não aceitar resource_id, owner, Grant ou principal como autoridade do renderer.
Receipt de handoff é histórico (`handoff_recorded`, epoch, request_key,
`status_requires_fresh_read`); consulta live usa status separado.

Troca de epoch, expiração, handoff para humano e revogação do grant cortam os
próximos checkpoints de input. Reaquisição não ressuscita worker com epoch antigo.
Handoff não desfaz eventos já enviados ao SO. Nenhum dado de teclado/clipboard
é guardado na tabela de posse. Status de outro workspace não expõe principal/WorkItem.
Recurso expirado/liberado pode ser adquirido por outro workspace do mesmo dono com CAS.

### UFO — Nexo

```python
UFOApplicationActions(host._dispatch)
await execute(*, workspace_id, work_item_id, machine_id, capability_id,
              operation_id, request_key, command, selector_key, text=None) -> dict
```

Callback é a assinatura **posicional async** existente de MachineHost._dispatch:
`(workspace_id, work_item_id, machine_id, cap, oid, arguments, key)`.
Nexo compõe `application_action` usando `host._call`; não chamar o wrapper sync
`host.dispatch` dentro do próprio loop. Comandos allowlisted; resultado inclui
Operation e observação de origem. Erro/UNCERTAIN interrompe a sequência sem retry.

### Providers — Codex/Nexo

Preservam `MachineDeclaration`/`GuardedExecutor`:
`discover(machine)`, `start(OperationRequest)`, `observe(operation_id)`,
`cancel(operation_id)`, `reconcile(operation_id)`, `cleanup(operation_id)`.
Observação local do adapter não substitui recovery durável do host.

Factory central:
`register_execution(declaration)`, `dispatch_request(...)`,
`await submit(run_id, request)`, `await reconcile(run_id, request)`,
`cancel_from_control(run_id, operation_id, work_item_id)`, `await cleanup(request)`.
Inventory sozinho não autoriza dispatch. Cleanup de Operation não destrói recursos
remotos; destruição é ação explícita admitida, sobre ownership comprovado.
Shutdown fecha somente handles/processos/conexões locais próprios.

Nexo confirmou por mensagem a composição de configuração/restore dos seis kinds,
InputControl keyword-only/request_key, RustDesk vault/tuplas, Guacamole clipboard
control/record_input. `application_action` foi contratado. Isso é coordenação de
implementação, ainda não demonstra o funcionamento em runtime.

### Extensões de ações

- Playwright: `session.list(limit?)`, `session.status(session_id)`,
  `session.events(session_id,after?)`, `session.export(session_id,output.json)`.
- UIA: `observe.hybrid(output.png)` habilitado explicitamente em binding.actions.
- Daytona: `computer.*` acima; referências requeridas no focus/invoke/set_value;
  invoke também recebe `invoke_action` anunciado pelo nó. `preview.fetch` recebe
  `port/path/output`, somente portas/origins HTTPS declarados, sem redirect ou token
  no renderer. `sandbox.archive` exige sandbox stopped e owned;
  `sandbox.network(profile)` usa CIDRs declarados e
  `sandbox.network.reconcile` registra o perfil observado sem reenviar a mudança.
- Guacamole: `clipboard.read(wait_seconds?)`, `clipboard.write(text)` quando
  `clipboard_enabled`. Transferências/filesystem/audio permanecem negadas no tunnel;
  coleta de arquivo autorizada usa o provider guest/artifacts ou document paths.
- RustDesk: `login`, `desktop.status`, `frame(output.png)`,
  `input.key(keycode,down)` com keycodes explícitos e
  `input.mouse(mask,x,y)` com limites e allowed_input. Nenhum input string arbitrário.

DTO Daytona aceita computer_selectors JSON (`key/role/name/actions`), computer_pid,
preview_ports/preview_origins/max_preview_bytes e network_profiles. Os selectors
são convertidos no próprio binding. A rede padrão continua `blocked`; CIDR /0 nega.

### UI/HTTP/MCP — Codex, Prisma e Lume

Expor somente rotas autenticadas e workspace derivado do servidor, preservando
`POST /api/shell/bridge` e seu envelope. Configuração host-only não vira tool
que aceita owner/Grant/root/credential arbitrários. As ações usam o dispatch
existente e request key; UI é projeção de receipt/status, nunca autoridade.

Atualizar classificação de leituras/budgets para os novos reads de sessão,
computer/status/observe, hybrid, clipboard.read, native desktop.status/frame e
reads HCS/runsc/guest. Predicados ficam sob ownership Nexo; foram comunicados.
Catálogo deve refletir binding.actions/capabilities concedidas, sem habilitar
todos os comandos só porque o provider existe.

Guacamole viewer/tunnel/playback existentes precisam composição no painel
contextual com o bundle real `guacamole-common-js`; ticket curto não substitui
grant e cada input continua passando pelo dispatcher central. `record_output=false`
é live-only: export/playback devolvem indisponibilidade explícita.

## Dependências reais e limites

1. **Integração HTTP/MCP/UI:** donos centrais devem concluir exposição autenticada
   de input_handoff/status, application_action e configuração/catálogo de providers.
   Não alterei esses pontos de ownership nem os presumi operantes.
2. **Ambientes reais:** VM Hyper-V preparada com task InteractiveToken/usuário
   limitado e identidade/pins; bridge HCS compilada/camada uVM; Linux/runsc/OCI;
   Daytona SDK versão/PTy pin/endpoint/credenciais/toolbox; Chromium instalado;
   guacd/guest TLS/credenciais; RustDesk rendezvous/peer/key e build própria.
   Ausência resulta em erro explícito, nunca backend fixture/fallback host.
3. **RustDesk shipping (Vitra):** usar `native_peer_gate_patch` ampliado sobre o pin
   upstream e compilar somente na etapa final autorizada. Manifest exige
   `control_extension=sentra-desktop-control-v1` para login/frame/input. Pin do
   launcher sozinho não basta: DLLs/assets e manifesto do bundle continuam pinados.
   Patch é código preparado; build nativa não foi materializada nesta rodada.
4. **Pulso:** PTY Daytona e seu journal/cursor existentes estão disponíveis ao
   terminal persistente. Nenhuma mudança nos arquivos exclusivos de ConPTY/Goal/receipts.
5. **Memory/recovery:** UFO usa ExperienceMemory/plan_history centrais existentes;
   sugestões de máquina e memória não concedem permission nem repetem efeito.
   Browser perdido não é recuperável por relaunch silencioso. Checkpoint de VM/runsc
   não resolve automaticamente efeito externo incerto ou restaura sockets.
6. **Isolamento:** UIA no host confere identidade/posse; não confina o usuário.
   Workloads não confiáveis usam guest isolado configurado. HCS é headless.
   Routes/CDP Playwright não substituem isolamento OS de rede.
7. **Licenças/proveniência:** ver `INTEGRAL_PROVENANCE.json`; Vitra deve carregar
   LICENSE/NOTICE das dependências/pacotes/builds efetivos. Nenhum clone foi alterado
   ou executado para gerar cópia sem provenance. Backend Daytona e build RustDesk
   têm obrigações AGPL distintas dos clientes Python de API Apache.

## Validação futura preparada — sem execução

Arquivo novo `tests/unit/test_sentra_executors_integral_forja.py` cobre:

- Grant real ControlPlane/SQLite obrigatório para posse de entrada; troca de
  epoch humana e reaquisição não liberam worker antigo; revogação nega.
- Handoff CAS/idempotência/fingerprint, restart/TTL e redaction entre workspaces.
- Identidade/cursor/evidência Playwright persistidos; novo backend informa LOST,
  rejeita replay e não lança browser de fixture para fingir retomada.
- Hybrid UIA só publica screenshot consistente; divergência preserva output.
- Configuração persiste provider e não chama UIA nem cria Grant.
- Seleção de dispositivo exige todas as capabilities e distingue carga desconhecida.

Na etapa final, ampliar com execução dos testes existentes/new e aceitação real
por provider: input_handoff autenticado+crash/revoke, PID/HWND/runtime recriado,
guest desktop/task/artefatos, HCS/runsc resource cleanup, browser isolation/CDP e
restart, Daytona AT-SPI/PTy/preview/rede/archive, Guacamole live/clipboard/recording
opt-in/playback, RustDesk patch/build/login/frame/input/lease revoke, RPA semântica
e replay de Operation incerta. Fixtures unitárias não substituem estes ambientes.

## Comunicação

Executei `maestri list` primeiro. Contratos e expansões foram enviados cedo e
durante a implementação com `maestri ask Codex`, `maestri ask Nexo` e
`maestri ask Meridiano`. A entrega completa referencia este documento e mantém
pendências reais de composição/ambiente/validação explicitamente abertas.

## Adendo — shell contextual InputControl/Guacamole (2026-10-11)

Prisma/Codex solicitaram o viewer contextual e controle humano opt-in. Acrescentei
o caminho `human_input_scope` tipado, somente para host autenticado, e
`CentralExecutorFactory.submit_human_input`. A posse human não autoriza ferramentas
do agente: elas continuam negadas fora deste contexto. No contexto, cada input
confere epoch/TTL/machine/workspace e conserva os mesmos grants/WorkItem/Run,
reserva e fronteira de efeito centrais. Nenhuma flag de payload renderer cria esse contexto.

```python
human_input_scope(control, *, owner, workspace_id, machine_id, resource_id, expected_epoch)
await factory.submit_human_input(*, run_id, request, workspace_id, expected_epoch)
```

Nexo compõe `dispatch_human` ao redor de `await host._dispatch(...)` no loop próprio,
derivando owner/resource do servidor. Codex compõe `shell_machine.py`/listener.

Nomes congelados no `POST /api/shell/bridge`:

| action | Payload específico | value |
|---|---|---|
| `machine_list` | project_id | machines + work_items; catálogo concedido/actions |
| `input_status` | machine_id, work_item_id?/capability_id? | machine_id, holder, epoch, live, expires_at?, ttl_remaining_seconds, grant_status granted/denied/unknown, input_channels, grant_created=false |
| `input_handoff` | machine_id, holder, expected_epoch, ttl_seconds, request_key; WorkItem/cap/action para holder agent | receipt handoff_recorded/epoch/request_key/status_requires_fresh_read; consulta live separada |
| `remote_viewer_open` | machine_id, work_item_id, session_id, capability_id?, control_mode view(default)/human, expected_epoch? | viewer_id, machine/work/session/cap, control_mode, input_epoch, ws_url, expires_in_seconds, max_connection_seconds, single_connection, input_channels (view=[]), grant_status |
| `remote_viewer_close` | viewer_id, request_key | viewer_id, closed=true, remote_os_session_deleted=false |
| `machine_execute` / `machine_observe` | contrato existente de Operation | receipt/status central existente |

Envelope conserva request_key/project_id/space_id/conversation_id; renderer nunca
fornece owner/principal/resource_id/Grant, credencial ou path de configuração.
Capability omitida só pode ser derivada se houver uma única capability autorizada
compatível; ambiguidade falha. URL/ticket ficam em memória, sem localStorage/log.

`GuacamoleTunnelServer` agora suporta:

```python
GuacamoleTunnelServer(dispatch=callback, port=0, allowed_origins=(canvas_origin,))
listener = tunnel.serve()  # somente startup lazy de runtime; não foi chamado aqui
# self.port é atualizado por listener.socket.getsockname()[1], no socket já bound
tunnel.issue(session_id=..., machine_id=..., principal_id=..., capability_id=...,
             work_item_id=..., run_id=..., workspace_id=..., control_mode='view',
             input_epoch=None, lifetime_seconds=30)
tunnel.viewer_scope(viewer_id)  # host-only, para autorização por workspace
tunnel.revoke(viewer_id)        # invalida ticket/fecha somente WS próprio
tunnel.revoke_all()             # teardown host; depois listener.shutdown() e join
```

Issue retorna `url` (Codex projeta como `ws_url`), viewer_id, expires_in_seconds,
control_mode/input_epoch, max_connection_seconds e single_connection.
`port=0` antes do bind recusa issue. Não há port probe/release/rebind.
Origins são derivados da porta do CanvasServer no servidor. Listener é loopback,
aberto lazy somente por remote_viewer_open; configuração/import não o inicia.
Scope de viewers fechados é retido por até 600s/128 entradas para autorizar close
idempotente, sem conservar o token de conexão.

Ticket view bloqueia raw key/mouse/touch antes do dispatcher; canais extras do
viewer são negados. Ticket human prende input_epoch; callback envia apenas
key/mouse/touch para dispatch_human(expected_epoch=ticket.input_epoch). Reads e
sync/ack/nop/close usam dispatch ordinário. Cada evento tem Operation/request key
único derivado no servidor. Holder human, epoch live e grant são revalidados.

### Status de sessão sem probe remoto

Guacamole ganhou `action=status`, sessão obrigatória, sem guacd/socket I/O:

```json
{
  "provider": "guacamole", "session_id": "...", "state": "CONNECTED", "epoch": 0,
  "scope_verified": true, "session_scope_sha256": "...", "binding_sha256": "...",
  "local_transport_connected": true, "remote_state_observed": false,
  "view_only": true, "allowed_input": [], "clipboard_enabled": false,
  "record_output": true, "provider_accessed": false
}
```

Host chama dispatch com action=status e usa `result.evidence`; status passa pelos
grants e WorkItem centrais, mas o backend apenas chama SessionJournal.get com
scope `SessionScope.from_request(request).key` e fingerprint do binding. Confere
session_id/scope_verified e, internamente, scope hash esperado; nenhum campo de
escopo é inferido do renderer. Local transport indica presença do objeto/socket
local não marcado closed, não prova liveness/login do desktop remoto. Nexo deve
classificar status como observation; binding.actions precisa conter status.

### Biblioteca e proveniência do renderer

Há fonte Apache em `third_party/guacamole-client/guacamole-common-js`; os caminhos
consultados não possuem pacote instalado no node_modules da UI, bundle dist do
clone ou `sentra_canvas/static/guacamole-common.js`. Não anunciei bundle pronto.

Metadados primários consultados em
`https://registry.npmjs.org/guacamole-common-js/latest`: versão `1.5.0`, licença
`Apache 2.0`, repository `https://github.com/padarom/guacamole-common-js`.
Este npm é um reempacotamento distinto do clone Apache atual. Pin preparado para
Prisma: `guacamole-common-js: 1.5.0`, tarball
`https://registry.npmjs.org/guacamole-common-js/-/guacamole-common-js-1.5.0.tgz`,
SRI `sha512-zxztif3GGhKbg1RgOqwmqot8kXgv2HmHFg1EvWwd4q7UfEKvBcYZ0f+7G8HzvU+FUxF0Psqm9Kl5vCbgfrRgJg==`.
Preservar licença/notices e provenance desse pacote efetivo; não atribuir a ele
o SHA do clone Apache. Dependência/sources podem ser preparados sem install/build.

Foram acrescentados testes futuros de contexto humano, ticket view que rejeita
raw input, close idempotente scoped e port=0 antes de bind. Nenhum foi executado.
Nenhum listener/browser/build/QA foi iniciado nem o preview PID 47408 tocado.

## Redistribuição Selo — entrega de fontes 11/10/2026

Ownership herdado e liberação explícita Nexo para authorization/capabilities/
guards aplicados. APIs reais, configuração CAS/vault e estado configurado,
learning/eval/telemetry/audit/Grype/benchmark gate estão registrados em
[Forja-fechamento.md](Forja-fechamento.md). Esse documento é o contrato vigente
para composição Codex/Nexo/Prisma/Pacto/Tessela e consolidação Meridiano.
Root/runtime/core e arquivos de outros donos não foram editados; nenhum
teste/build/install/lint/QA/scanner/benchmark/provider foi executado. Pendências
de composição, checkpoints internos OPA/Nexo, instrumentação global e ambientes
reais estão explícitas, sem alegar homologação. Comunicação por arquivo, sem
ask-back síncrono conforme REDISTRIBUICAO_CODEX.md.
