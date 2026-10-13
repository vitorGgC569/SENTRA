# Nexo — entrega de implementação e contratos

11/10/2026. Fontes implementadas; **nenhuma validação/homologação executada**.
Preservados checkpoint informado pelo principal, ownership, mudanças anteriores
e assinaturas de continuation/checkpoint Rastro. Sem commit/push/reset/stash,
recrutamento, testes, build, lint, benchmark ou QA.

## Fontes e escopo

Documentos de implementação integral e shell bridge, nota de 465 linhas,
estudo OpenDots (55 achados e matrizes), análise CoS e seções pertinentes de
auditoria/reavaliação/reuse/checkpoint sustentam o domínio. Implementação própria;
não foi copiado nem executado backend upstream como segunda autoridade.
CP/Run/WorkItem/Operation/Grant continuam a autoridade. Canvas/HTTP/MCP/CodeMachine
são root; guards Selo/authorization são Forja, workflows/runtime providers são
Lume, backup/update frontend Vitra é Tessela, browser/voice/anexos/checkpoints são
Cobalto. Reservas/API compartilhadas: `Cobalto-Nexo-contract.md`.

## Arquivos e comportamento entregue

- `sentra_mcp/services/shell_coordinator.py`: Spaces/Dots/conversas/equipes,
  migração aditiva por agent_id/canvas_team_id, IDs estáveis, CAS e journal central
  de request_key. Fingerprint alterado conflita; efeito ambíguo é uncertain e não
  é reenviado. Payload/result/message protegidos; eventos só referências.
- `control_plane.py`, `governance.py`, `durable.py`: facade shell, reassign
  transacional, pause individual desejado, identidade de agente/membership de Runs
  terminais, controle de intenção pending e cleanup fenced. WorkItem/Operation
  não são duplicados por runtime local em hosted. Conclusão de metadados e ack de
  signaling/storage são distintos da conclusão externa/quality gate de tarefas.
- `control_store.py`, `postgres_store.py`: fábrica configured; namespaces reais,
  schemas tenant, owner RLS FORCE, enrollment/revoke/read-only, migrações nativas
  digest/version, SQL compilado explicitamente, locks transacionais e fencing.
  psycopg ausente/DSN ausente/schema incompatível tornam PG indisponível explícito.
- `authority_snapshot.py`, `authority_migration.py`, `postgres_rollback.py`:
  snapshots AESGCM, arquivos/artefatos, valores de keyring, quiesce e digest;
  `authority_paths.py` remapeia somente campos tipados de paths de configurações
  host (incluindo args absolutos e argument_file_pins), atualiza digest e proteção;
  instruções/prosa/IDs/refs não são interpretados como caminhos;
  prepare/import/activate CAS, rollback exporta o estado PG atual e preserva
  original. Runs in-flight RECOVERING, Operations UNCERTAIN, leases invalidadas;
  nenhum replay automático. Backup/restore nativo mantém gate durável quando
  banco/arquivos não acabam de recuperar.
- `sentra_runtime/canvas_authority.py`, `provider_authority.py`,
  `sentra_core/provider_usage.py`: injeção do mesmo CP e budgets; cápsula CLI
  protegida vinculada à execução; lookup de binding shell e contextos PG sem
  ATTACH/fallback de owner cli. IDs/assignee/Run/WI/Operation atuais conferidos.
- `shell_optional_authority.py`, `coordinator_admission.py`,
  `authority_bridge.py`, `central_authority.py`: policy central antes de callback,
  orçamento único, fence/checkpoints/revogação, recibos cifrados recuperáveis;
  coordenador não ganha owner shortcut nem cria Grants de filhos.
- `machine_host.py`, `interop_machine.py`, `observations.py`,
  `machine_configuration.py`: wrappers reais interop/executores/input humano/
  A2A callback/UFO/runtime/terminal/code-mode; restore e inventory reais;
  configurações protegidas, OpenHands config_sha256 create e events defaults.

## Contrato shell público

`ControlPlaneService.shell_dispatch(owner, *, project_id, action, payload,
request_key=None) -> {ok:true,value:...,request_key?}`. Owner vem do servidor;
IDs de autoridade/paths/grants/principal não vêm do renderer. Mutação exige
request_key string 1–128. Root fornece `/api/shell/bridge`, normalização ws/project
e bearer. Action/read scopes conferem project/Space/conversa.

Reads: home, space_get, space_list, dot_list, conversation_list, message_list, message_content,
events, voice_status, attachment_upload_status. Mutations: space_create,
dot_create, dot_update(expected_revision CAS), conversation_create, message_send,
coordinate, voice_start/signal/stop/revoke, attachment_register,
attachment_upload_begin/chunk/complete/abort.

Home: project_id, space, spaces, dots, conversations, teams, documents, run,
activity, capabilities, voice/attachments `{available:boolean,reason?}`.
Documents reais são compostos pelo root/Tessela; o coordenador não inventa docs.
Entities usam snake_case: space_id/dot_id/agent_id/conversation_id/team_id,
project_id/space_id, revision, created_at/updated_at. Dot inclui model:string,
effort:null|automatic|low|medium|high|xhigh|max|ultra, instructions:string e role.
`dot_update` modifica name/role/instructions com expected_revision.
Listas: `{project_id,items,page:{offset,limit,returned,total,next_offset}}`,
limit 1–200; mensagens cronológicas. Eventos after_seq >=0, limit 1–200:
`{items,cursor,next_cursor,has_more}`; seq autoritativo.
Runtime messages acima de 100 mil caracteres usam chunks protegidos, preview
65536 e `content_ref:{message_id,revision,total_chars,sha256,action:message_content}`,
`content_truncated:true`. Nenhuma perda silenciosa: read message_content exige
space_id/conversation_id/message_id/revision, offset e limit <=65536; retorna
content/offset/next_offset/total_chars/sha256. Limite total explícito de 20 MB;
o journal upstream segue fonte protegida original. Root/Prisma compõem leitura
dedicada do overflow na UI/allowlist HTTP.

Coordinate payload `{space_id,conversation_id?,intent:{kind,...}}`:

| kind | campos exatos da intenção |
|---|---|
| create_team | name, coordinator_dot_id, worker_dot_ids |
| connect | source_dot_id, target_dot_id |
| delegate | team_id, dot_id, objective |
| handoff | source_dot_id, target_dot_id, content |
| pause / resume / cancel | somente kind; Run do projeto |
| pause_dot / resume_dot | dot_id |
| reassign | work_item_id, dot_id; WI PENDING/QUEUED/BLOCKED sem lock ativo |

Prosa não provoca efeitos. Retornos mutáveis incluem run_id/work_item_id/
operation_id, status, receipt_id (ou null), result; control mutations têm também
shell_receipt_id. waiting_approval/uncertain não afirmam conclusão remota.
Message_send `{space_id,conversation_id,content,attachments?:refs}` é persistido
antes de dispatch. Ref validada pelo adapter real, nunca path renderer.

## APIs de composição

`cp.attach_shell_runtime(runtime)` exige resolve_project/admit_dot/
dispatch_message/coordinate; update_dot e reconcile_message implementados pelo
root. Reads de reconcile não reenviam. `cp.shell.get_space(space_id,owner,
project_id=pid)` e `cp.shell.resolve_run(pid,owner)->run_id RUNNING` são callbacks
Tessela. `cp.reassign_work_item(target_work_item_id,owner,agent_id=target)` preserva
identidade e escopo; não cria Grant.

`CanvasAuthorityRuntime(state_root,canvas_store,*,control,owner)` é a assinatura
injetável, já usada pelo root. Lifetime CP pertence ao root.

CLI hosted precisa **antes de cada subprocess** (shell e tarefas legadas):
`prepare_provider_binding(control, *, state_root, owner, principal,
conversation_id, run_id, work_item_id, operation_id, project_id,
ttl_seconds=3600)` de `sentra_runtime.provider_authority`. Retorno environment
tem somente SENTRA_CONTROL_BINDING_FILE com path de cápsula protegida. Remover
env herdado dessa chave e atualizar com environment retornado. CLI factories
configured e UsageLedger consomem a cápsula; DSN não vai plaintext no ambiente.
`canvas_shell_provider_bindings` namespace shell permanece a tabela publicada.
ConversationStore deriva principal da cápsula validada no filho, não do usuário
do SO; principal explícito conflitante é negado. Capsule legada task_* usa o
binding servidor e valida WorkItem/Operation nativos atuais, sem depender de
um Run/agent SQLite local. Conexões SQLite CP já abertas verificam selection
antes de statement/commit para impedir writes depois do cutover.
Não permitir root PG explícito + CLI SQLite por ausência de seleção persistida.

MachineHost:

- configure_interop(...,kind=acp|a2a|mcp|channels|acp_registry,provider_config)
  seleciona factories Lume concretas/catalog; channels exige pré-configuração.
- configure_executor(...,kind,provider_config) usa helper síncrono Forja e restore
  seis EXECUTOR_KINDS exportados (restore consulta o export). configure_session
  usa actions binding reais.
- input_status(...): resource_id/principal_id retirados; ttl_remaining_seconds e
  grant_status unknown/granted/denied; input_handoff deriva resource host-only,
  request_key obrigatório, InputControl keyword-only, CAS expected_epoch.
- dispatch_human(...,expected_epoch) usa human_input_scope e `_dispatch` async;
  renderer não fornece owner/resource/principal/human flags.
- receive_interop_callback(machine_id,raw_body,headers) apenas factory A2A,
  autenticação própria callback, sem owner bearer e sem efeito despachado.
- application_action(...) usa UFOApplicationActions(self._dispatch), mesmo loop.
- attach_runtime_adapters(runtime_host_resolver=callable workspace_id->host,
  canvas=CanvasService); configure_runtime(workspace_id,workspace_root,agent_id,
  provider,binding_id,runtime_host=None); configure_terminal(...,canvas=None).
  Host fornecido deve ter control por identidade e mesmo owner; attach antes de
  restore para runtime-temporal/runtime-langgraph/terminal. Factories/SDK async
  e PG de Pulso são Lume, sem TaskRuntime fork. Se runtime_host oferecer
  `async restore_async(binding_id)`, MachineHost o aguarda no seu loop para
  preparar o cache antes do constructor sync da machine; loader Temporal sync
  que tenta asyncio.run neste loop continua explicitamente indisponível.
- attach_configuration_handler("code-mode",handler); handler(host,**kwargs)
  chama configure_code_machine com Canvas capturado pelo root. configure_code e
  restore code-mode invocam handler antes de qualquer execução.

## Coordenador agente — CF05/CF14

`cp.execute_coordinator_intent(owner, *, project_id, conversation_id, run_id,
work_item_id, parent_operation_id, agent_id, intent, request_key, compose,
process_alive, connected_agents)`.
Callbacks server-only: compose(resolved_intent,authority)->dict;
process_alive()->bool; connected_agents(project_id,agent_id)->IDs atuais.
Parent token é root shell:<operation>, WorkItem/Operation/assignee atuais e
binding shell são conferidos em cada checkpoint; role coordinator/coordenador
e conexões dirigidas restringem alvos. create_dot usa name/role/model/effort/
instructions; demais intents são os da tabela acima. Cap exata por kind é
`canvas.coordinator.<dot_create|team_create|connect|delegate|handoff|pause|
resume|cancel|reassign|pause_dot|resume_dot>`. Grant existente scoped no WI/Run
e required_capabilities do parent são obrigatórios; ausência retorna
waiting_approval. Intenção central/Operation/receipt deduplica request e registra
o efeito via compose. Sem novo Grant; filha precisa admissão/cap/Grant próprios
antes de iniciar modelo/terminal/provider. Compose deve executar somente o
mutador correspondente, revalidar model catalog e usar checkpoint antes de
cada efeito composto. Admissão de controle/canvas não é permissão genérica de
owner nem substitui executor de child task. Root mantém token/process/UI/MCP.

## PostgreSQL / C09 administrativo

`ControlPlaneService.from_store(state_root,backend="configured",dsn=None,
tenant_id=None,principal_id=None)`. Shared store é explícita em todos os serviços
own. Runtime PG não pode ser superuser/BYPASSRLS. `provision` administrativo
enrolla tenant/principal e grants de SQL runtime; não cria Grant de capability.
store.schema(ns)/lock_key(ns)/connect(ns), db.raw psycopg `%s`; db.execute qmarks
somente subset nativo admitido. path_for=None. Guards multi-namespace seguem
ordem de nomes e SELECT FOR UPDATE; Tessela já adaptou collaboration guard.

`store.backup(directory,*,quiesced,file_roots=None,recovery_key=None)` e
`restore(directory,*,manifest_sha256,quiesced,file_roots=None,recovery_key=None)`:
AESGCM/ciphertext real, optional host recovery key bytes32, keyring refs,
arquivos/artefatos e SQLite sidecars via snapshot in-memory/WAL, PG REPEATABLE READ
com locks. Default raiz tenant; artefatos externos exigem raízes host explícitas.
Restore exige paths originais, application schema compatível, memberships
inalteradas. Gate incomplete recovery bloqueia CP; repetir mesmo digest conclui
o fluxo sem replay. DPAPI interno exige perfil original (hash dos artefatos não
é alterado para fingir portabilidade). Psycopg3/cryptography/keyring/DPAPI são
prerequisitos reais configuráveis, nenhum pacote instalado nesta fase.

`NativeAuthorityMigration(source_root,target_store administrator)`:
prepare(directory,quiesced,recovery_key=None), commit(directory,
manifest_sha256,quiesced,recovery_key=None), activate(...,expected_revision,...),
rollback(...,expected_revision,...). Import multi-principal exige enrollment
prévio no tenant, preserva memberships; namespace SQL/rows importados numa
transação, arquivos copiados ao root nativo e artifact.path remapeado somente
como campo autoritativo de path. Selection protegida CAS é ponto de cutover.
Rollback exporta dados PG atuais para shadows SQLite, copia arquivos nativos
atuais e remapeia artifact.path de volta; nunca volta para snapshot SQLite velho.
Originais/native DB são retidos; nenhum efeito automaticamente repetido.
Stores PG que observaram a selection mantêm sua revisão: cutover/rollback/CAS
mudado invalida conexões antigas e cápsulas CLI daquela revisão. Enrollment,
role administrador e revogação são rechecados, não só lidos no constructor.
CP também confere que Context e Durable compartilham tenant/principal/DSN/root.

## Dependências/pêndencias reais de composição e ambiente

Root precisa injetar cápsula CLI em shell e legado e ligar o token coordenador
ao helper central; source preparada, composição em arquivos root não editada.
Lume fecha SDK restore async no owned loop (Temporal factory sync antiga nega
loop ativo) e projeta seu RuntimeProviderHost pela store nativa. Forja fecha
authorization/veto nativo; Cobalto checkpoints antes de cada HTTP/filesystem em
voice/attachment e integra CLI/gateway factory configured. Tessela compõe
quiesce/backup/migration/rollback nas APIs C09 sem duplicar crypto.
Prisma/root mantêm allowlists/read/availability e modelos de conta reais.
Credenciais, serviços externos, SDKs/binaries/builds/distribuição e perfil DPAPI
original continuam prerequisites de ambiente, não provas de execução.
Ainda não existe evidência runtime desta entrega. Nenhum requisito homologado.

## Plano futuro após liberação expressa da validação

Exercitar migração repeatable sem Dot/Team duplicados; Run terminal→novo preserva
agentes; CAS concorrente; duplicate/digest collision/uncertain sem reenvio;
coordenador com token morto/reassign/revoke/conexão removida; optional cada efeito
fenced e receipts de signaling/storage; input epoch human/agent. PG real:
multi-tenant/principal reader/revoke, transações/locks/fences/crash, prepared/imported/
activated cutover, rollback após writes nativos, backup full files/keys/digests e
crash entre banco/arquivos; schemas e consumidores reais. CLI hosted usa mesma
autoridade/budget, sem SQLite fallback. Providers reale/manifest/pins e release
somente quando todas as fontes/composições estiverem integradas e root liberar.

## ACK do contrato Codex-coordinator-contract.md

Composto no domínio Nexo: callback opcional
`runtime.message_capabilities(project_id,owner,dot,conversation,refs)->list[str]`
antes de `_authority` message_send; lista exata sem wildcard, até64, sem duplicatas,
vai para required_capabilities do WorkItem. Retornar declarações não cria Grants.
O helper exige capability expressamente presente no parent WI **inclusive quando
a lista está vazia**; ausência é PermissionError (não há Grant a aprovar fora da
declaração). Requirements e Run state/desired/assignee/Operation/binding/process/
conexões e role canônica atual do Dot são rechecados em checkpoints. Grant scoped faltante continua
waiting_approval. Delegate/handoff descendentes declaram model:invoke por callback
root; filho tem WI/Operation/Grant próprios, jamais herda owner shortcut.
O contexto central fenced dessas duas capabilities também registra
parent_work_item_id e parent_coordinator_operation_id/agent_id, sem IDs fornecidos
pelo renderer. Budgets de WorkItem pai aplicam-se ao descendente e somam seus
cost_events/quota/tokens; ancestry é owner/Run checked, cycles/depth negam.
UsageLedger confere reports incompletos também nos descendentes, sem tratar
token/preço desconhecido como zero ou escapar do limite criando outro WI.

Self pause/cancel de Run ou pause_dot do próprio coordenador registra ACK por
`CentralDurableIntentAuthority.record_metadata_transition(receipt,request,result)`:
verifica digest/intent/cap/principal/WI/fence e estado durável PAUSED/CANCELLED ou
agent desired WAITING. Não reabre policy depois de parar; nenhuma ação subsequente
fica permitida. Retorno/evidence têm terminal_metadata_transition_ack e
subsequent_effects_denied. Efeito não terminal cuja autoridade mudou antes do ACK
vira UNCERTAIN. Receipt é metadata e não prova conclusão de filhos.

Turn permissions/UI/tokens/context CLI e generic coordinator_intent continuam
com root/Prisma/Tessela conforme contrato. Sem alterações nesses arquivos e sem
resposta síncrona bloqueante para implementar esta composição.

ACK do ajuste exato de permissões: `complete_control_mutation` inclui
`turn_permission_grant` e `turn_permission_revoke` na allowlist. Mantém receipt
kind control_mutation, owner/request_key/project, WI PENDING/COMPLETED sem locks;
completa somente o WorkItem de metadados da permissão, sem fechar o turno/modelo
original. Root conserva permission_operation_id/permission_work_item_id e audit
SUCCEEDED separados. Nenhum arquivo Prisma/Forja/root foi editado para isso.
