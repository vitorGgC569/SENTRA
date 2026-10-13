# Prisma — fechamento Pacto e superfícies do produto

Ownership atual: `REDISTRIBUICAO_CODEX.md`. UI anterior preservada. Nenhum
teste, build, install, lint, benchmark ou QA; preview PID47408 intocado.
Este relato acompanha implementação em andamento, não homologa A08.

## Contrato root recebido (11/10/2026)

Bridge única bearer `/api/shell/bridge`, contextual `project_id`, `space_id` e
`conversation_id`, sem owner/Grant/opID do browser:

- `code_propose {machine_id,work_item_id,source}`.
- `code_execute` / `code_cancel {machine_id,work_item_id,proposal_id}`.
- Reads `code_status {machine_id,proposal_id}`, `code_discovery {machine_id?}`.
- Mutações `{operation_id,state,evidence,value?}`; resultado privado apenas
  depois de SUCCEEDED + receipt hash; chave mantida em resposta incerta.
- Configuração host via center machine configure `kind=code-mode`, com pins
  aprovados, limits e tools host-selected; nenhum adapter duplicado.
- WorkItem existente + Grant `code:propose/execute/status/cancel/discovery` e
  `code-tool:name`. O renderer não concede essas capabilities.

Root possui `code_machine.py`/`shell_code.py`. Alterações dispatcher/runner
ficam em `sentra_code_mode/*`. Guardas/PG centrais continuam com Nexo.

## Pendências de composição e distribuição

Root informa status A08 baseado no receipt central SUCCEEDED; a verificação
dispatcher será ligada ao resultado completo protegido e evidência de runtime
real, jamais apenas ao nome do engine ou digest histórico.

Tessela/Vitra: preservar pipeline guest e preparar ship de WASM/SBOM/provenance
e wasmtime na fase final autorizada; não construir/instalar agora. Binário
materializado não equivale a execução/homologação A08.

Forja/Selo: learning continua proposta pinada/revisada; ativação da Skill exige
ação explícita e vínculo WorkItem. Skills não criam Grants.

## Arquivos em fechamento

- `shell-bridge.js`: ações `code_*` recebidas. Source não entra no journal
  sessionStorage de mutações; execução/cancel podem conservar apenas IDs.
- UI Code Mode e runner/dispatcher: implementação em andamento.

## Nova composição produto Pacto — root registra sem endpoint paralelo

`sentra_mcp.services.pacto_product`: `PACTO_ACTIONS` / `PACTO_READS` e
`dispatch_pacto_product(canvas,project_id,action,params)`. Root registra no
dispatch shell; ações mutantes passam pelo MESMO ShellHostRequests journal
antes do callback. Esquemas exatos por ação em `_SKILL`/`_PLUGIN`; unknown
fields recusados. Scope Space/conversa + WorkItem/agente/projeto validados.

Reads skill_list/review/versions/latest/disclose/activations;
mutations skill_import/git/github/revoke/activate/deactivate/upgrade/rollback/
replace. `source` seleciona pasta de import no workspace; `resource` seleciona
recurso virtual da Skill, sem liberar payload.path geral.

Reads plugin_bundle_list/inspect, plugin_supervision/transport_status/
connection_proof; mutations plugin_bundle_stage/register/disable/update/
rollback/uninstall e plugin_supervision_sweep. Catalog owner actions não são
autorização de tool/runtime; execuções stdio/HTTP/OAuth seguem MachineHost/CP.
Root também propaga reads/allowlist Nexo. Nenhum endpoint root editado.

Dialogs `skill-library-dialog`, `plugin-bundles-dialog`, `plugin-status-dialog`
consomem bridge única agora. Até root registrar esses nomes o servidor retorna
indisponibilidade explícita; não há fallback oculto para rota center.
Source/resultado Code Mode continuam só memória. `message_content` na UI faz
paginação revision/offset/total/SHA com teto20MiB; export recupera original,
nunca trata preview como mensagem completa.

Reserva Prisma: `skill_library.py` (learning binding e origem/revisões;
não guardas gerais Nexo) e novo `learning_skills.py`, `mcpb_lifecycle.py`
(delegação stdio fenced existente), `pacto_product.py`, dispatcher/guest/runner.
Nexo mantém control_store/authorization/CP/central guards e classificação.

### Learning Skill — composição Forja/Codex

`ReviewedLearningSkills(control,learning,owner,workspace,workspace_id)` recebe
exclusivamente `SeloHostFacade.learning` (`ProtectedLearningStore`, mesma
control.store/owner/projeto). Root compõe por projeto após configurar Selo;
construtor apenas registra o resolver host na SkillLibrary, não ativa nada.
Reads `skill_learning_review {suggestion_id}`; mutation
`skill_learning_stage {suggestion_id,expected_sha256,expected_review_revision}`.
Falta de resolver é indisponibilidade explícita, não ReviewedLearningStore
SQLite independente. UI inclui revisão e import inativo via mesma bridge.

Nova tabela governance `skill_learning_bindings(owner,workspace,package_id,
suggestion_id,review_revision,protected_manifest)` PK(owner,workspace,package_id).
Manifesto OS-cifrado; a SkillLibrary repete review revision/TTL/manifest/Grant
existente em ativação/upgrade/replace e disclosure de arquivo. Pacote com
source selo-learning sem binding é negado. Revogar/withdraw/expirar sugestão
nega novas disclosures; desativar contexto não cria/revoga Grant.

## Dependências concretas Nexo/Codex (por arquivo, não editar por Prisma)

- `sentra_runtime/observations.py` / `sentra_interop/central.py`: inner tools
  usam agora machine_id da metadata WorkItem, mesma máquina central (removida
  identidade sintética por owner). Os três callbacks read-only root
  `code-tool:machine_inventory`, `code-tool:project_file_list` e
  `code-tool:project_file_preview` precisam classificação host read-only para
  usarem lease de observation, sem competir com lease física de code:execute.
  Nunca classificar nomes arbitrários/model arguments como read-only. Nexo é
  dono da classificação e dos guardas; Prisma não toca esses arquivos.
- `sentra_canvas/code_machine.py`: evidence A08 deve combinar cap execute +
  `value.ok is True` + `value.a08_satisfied is True` +
  `value.execution_verified is True`; status combina dispatcher proof +
  central receipt SUCCEEDED/hash, não apenas engine/state. Dispatcher agora
  recusa finalizar QuickJS sem proof real.
- Namespace `governance` herdado: nova tabela
  `code_mode_dispatch_bindings(owner,operation_id,request_key,intent_sha256,
  proposal_id)` PK(owner,operation_id), UNIQUE(owner,request_key). Mesmo
  BEGIN IMMEDIATE/advisory-lock do wrapper Nexo; nenhum store paralelo.

### Adendo de fencing físico (Nexo/Codex)

Além da lease, `_ResourceLock` atualmente usa request.machine_id mesmo para
observation. Inner read precisa reutilizar o scope físico pai já admitido
(mesmo WorkItem/máquina), com reservation/fence própria, ou classificação
física host equivalente. Sem isso nested read disputa o OS lock pai.
Prisma mantém machine_id real; não introduz alias artificial para burlar lock.

Dispatcher exige `current_effect_context` code:execute já admitido, mesmos
owner/Run/WorkItem/principal/opID/key; execução usa `context.run_blocking`.
Timeout do waiter deixa UNCERTAIN e retém a exclusão do worker emprestado até
guest/tool terminar de fato. Nenhuma thread órfã libera lock para outra
execução. Cancel persistido em proposal.reason é observado entre processos.
Replay protegido reutiliza a conexão transacional atual, sem advisory lock
recursivo em nova conexão PG. Reservas Cobalto preservadas e ampliadas.

## Coordenador — UI Grants scoped (delta root)

Lido `Codex-coordinator-contract.md`. `shell-turn-permissions.jsx` montado na
conversa e oculto sem desmontar. Reads `turn_permission_list` com contexto
Space/conversa e WorkItem opcional. Mutations grant/revoke enviam somente
`space_id,conversation_id,work_item_id,capabilities,ttl_seconds?` + key.
Nenhum owner/principal/Grant/opID do browser; nenhum envio/model turn/tool
retoma automaticamente depois da concessão. Chave incerta preservada.

Campos de projeção consumidos (schema final root ainda aguardado):
`{items:[{work_item_id,objective?,agent_id?|assignee_agent_id?,state,
required_capabilities:[string],missing_capabilities?:[string],grants:[{capability,
...status/expiry}]}],capabilities?:[string]}`; alias tolerado work_items e
allowed_capabilities. UI só oferece capabilities declaradas nesse WI ou
Grants existentes, intersectadas com allowlist root de coordenador/model/Web.
TTL escolhas60/300/900/3600. Unknown caps ficam explícitas fora deste fluxo.
Grants são ações humanas explícitas distintas de confiar/bloquear ChatGPT.

Schema root já materializado e consumido por leitura de shell_permissions.py:
projeção single turn `{work_item_id,agent_id,work_item_state,operation_state,
operation_id,capabilities:[{capability,allowed,source,has_turn_grant}]}` (ou
work_item_id null antes da primeira mensagem). UI adaptada ao single turn;
nenhum fallback de capabilities inventadas. Grant observado e decisão de
política separados, inclusive Grant existente com veto atual. Mutações
retornam permission_change_recorded/grant_created/automatic_retry:false;
UI mostra alteração registrada, nunca turno executado. TTL root1..3600.

Bridge actions adicionadas; root registra e resolve destinatário/capabilities
sob autoridade central conforme seu contrato. Até schema final e registro,
erros não são tratados como concessão. Sem validação/rebuild/preview.

## FB-55 — culling gráfico com sessões independentes

`main.jsx` agora usa `ReactFlow.onlyRenderVisibleElements=true`. Leitura do
pacote local @xyflow/react12.12.0 confirma culling de node bounds e edge bounds;
os arrays completos de nodes/edges/seleção permanecem no estado autoritativo da
vista. `TerminalPool.reconcile` já cria/mantém entries por workspace/terminal,
independentemente do DOM: cleanup PtySlot apenas detach/place; dispose só na
remoção real do recurso/destroy da janela, sem fechar/reiniciar PTY backend.
NoteDrafts/timers permanecem no main fora do componente cullado. Não alterado
terminal-pool.js nem arquivos document-*; nenhum benchmark/QA executado.

### Alinhamento por arquivo — PG Pacto

Prisma ajusta somente defaults de construtor em `plugin_bundles.py`,
`plugin_host.py`, `chat_access.py`, `action_consent_gate.py` para aceitar a
store central injetada/seleção configurada em lugar de construir SQLite raw.
Nexo/root devem passar `store=control.store` explicitamente na composição CP
(`MCPBBundleCatalog(durable.state_root,store=durable.store)` em control_plane.py
reservado Nexo). Prisma não modifica control_plane/control_store/PG guards.
Comparações path_for(None) não provam mesma autoridade PG: fonte de facade
Pacto será checada por identidade de store, tenant/principal e DSN protegido,
sem projetar qualquer segredo. Guardas comuns/membership/RLS seguem Nexo.

## FB-05 — elicitation/permission reais já publicados pelo root

`shell-interactions.jsx` usa interaction_list/reply existentes. Poll somente
projeto/visível; pergunta original/schema/deadline/operation ID exibidos;
formulários primitivos/enum e JSON complexo limitado com validação final
server Draft202012Validator. ACP oferece somente allow_once/reject_once
anunciados, nunca allow_always; cancel/decline explícitos. Answer só em memória
(pode conter segredo), mesma key incerta, nada aprovado/reenviado sozinho.
Pergunta permanece montada enquanto resposta incerta, mesmo se polling já
omitir ANSWERED, para consultar a mesma resposta. Resposta não cria Grant.
Provider original consome uma vez conforme ProtocolInteractionService.
Root/Lume ainda devem expor status de interação por ID para recuperação
após reload sem persistir valores sensíveis no browser, e ampliar DTO com
WorkItem/machine context quando necessário. Nenhuma execução/QA feita.

## Delta root recebido — composição presente em fonte

Root confirmou registro PACTO_ACTIONS/READS no shell + ShellHostRequests e
A08 evidence com todos quatro bools + status receipt hash. A ausência de
registro anterior neste relato fica superada. Root também publicou o schema
single-turn consumido pela UI. Não inferir runtime/operabilidade/homologação.

### Recibo de permissões — contrato final root aplicado

UI OperationReceipt agora recebe `operation_id=permission_operation_id`,
`work_item_id=permission_work_item_id`, `state=permission_operation_state` e
receipt_id próprios da metadata mutation. `operation_state` do modelo fica
somente no painel de trabalho; não é usado para declarar a concessão concluída.
Mensagem limita confirmação à alteração de permissões e preserva
control_mutation_only/external_completion_claimed=false do contrato root.
Não alterados shell_permissions/governance/root nem preview; nenhuma QA.
