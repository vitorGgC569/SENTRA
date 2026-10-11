# Contrato backend CoS — SUBAGENTE 1 (2026-10-10)

Ownership: **SUBAGENTE 1 backend** possui `native_bridge/`, `sentra_core/`,
`sentra_runtime/`, `sentra_executors/goal_loop.py`, testes backend e este contrato.
Coordenador possui Gateway/TurnAuthority, CLI, Canvas/service, MCP/server/policy,
factory browser_relay e ControlPlane/control_store. Subagente 2 possui browser,
extensão, integrations e Electron. Mudanças preexistentes são preservadas.

## API de integração implementada

`from native_bridge.web_send import WebSendAuthority`

`web = WebSendAuthority(control, jobs)` recebe **a instância ControlPlane existente**
e **o JobStore/RelayState existente**, nunca abre outro outbox nem cria Run,
Operation, WorkItem ou Grant. TurnAuthority.issue continua sendo o proprietário
da criação de Run/Operation. O host fornece as identidades autenticadas.

```python
web.admit(owner, *, request_identity, run_id, operation_id, work_item_id,
          principal_id, grant_id, workspace, conversation_key, prompt,
          conversation_url=None, requested_model=None, requested_effort=None,
          target_worker="", timeout_s=180, dispatch_mode="external", submission_index=0)
web.stage_request(owner, *, request_identity, run_id, operation_id, payload)
web.request_payload(owner, request_id)
web.status(owner, job_id)
web.claim(owner, job_id, *, worker)
web.pre_send(owner, job_id, *, worker, lease_token, resource_key, fencing_token)
web.receipt(owner, job_id, *, worker, lease_token, evidence, request_id,
            extension_id, source_sha256, document_id, identity_epoch)
web.reconcile(owner, job_id, *, worker, request_id, extension_id,
              source_sha256, document_id, identity_epoch)
web.failure(owner, job_id, *, reason)
```

`admit` retorna `job_id`, `request_identity_sha256`, estado e `automatic_resend=False`.
O job é `websend_` + SHA256 canônico da identidade owner/request + submission_index; a mesma
identidade com conteúdo/modelo/effort/destino/autoridade divergentes é conflito.
Mapping da admissão fica no namespace central `session_checkpoint`; prompt
físico e ChatResult ficam cifrados no JobStore existente. Histórico assistant
usa WebHistoryStore protegido existente. Crash entre admission
e submit é recuperado pelo replay exato de admit, sem segunda intenção.

`dispatch_mode="external"` reserva o job para o adapter upstream Responses:
poll da extensão não pode consumi-lo. O host usa `claim` com worker físico
autenticado; `dispatch_mode="relay"` usa poll normal. Nunca ambos.

`pre_send` exige lease do job, grant `web:send` original no WorkItem, mesmo
Run/Operation/principal/workspace e lease/fence central existente pertencente
à Operation. Persiste fence e fase `sending` antes de retornar `ok=True`.
ACK é **single-use**: uma segunda chamada não concede outra permissão de clique.
ACK perdido/crash após fence => UNCONFIRMED, zero resend automático.

`receipt` usa **o broker/recibo V2 existente**, sem novo esquema:
`evidence={conversation_id,message_id,prompt_sha256,images_attached}` e vínculo
request/message/collector/worker/document/identity_epoch autenticado. `receipt`
e `reconcile` não enviam mensagens. Recibo tardio pode recuperar UNCONFIRMED
com a mesma lease/token originais e prova ainda válida. Nunca inferir not-run.
Os callbacks V2 do RelayState consultam também esse mapping.

Estados projetados: QUEUED/PREFLIGHT/READY/SENDING/UNCONFIRMED/SENT/ANSWERING/
ANSWERED/REJECTED/CANCELLED/FAILED; HTTP 200 upstream sozinho não significa SENT
ou ANSWERED. Modelo/effort persistidos são **pretendidos**, não verificados.
Atestado V2 prova associação de mensagem; não prova conta/Plus/modelo/effort.
Não há criação automática de grants; falta de WorkItem/grant => negação.

## Reutilização já presente

- JobStore: submit/poll/progress/delivery_receipt/result, WAL/FULL, ciphertext OS.
- AuthenticatedWebReceiptBroker: accept/attest_existing/require_attested.
- WebContinuation: stage/allocate_new_target/claim_new_target/commit/reconcile;
  mantém Run/chat/WorkItem/grant. Central checkpoint protegido e CAS.
- BoundedGoalLoop: open/advance/status/stop sobre Goal/WorkItem existentes.
  Cada advance explicitamente aprovado, nenhum efeito automático.

Ainda **não homologado Web real**.

## Contrato comum Goal/Loop para CLI e Canvas

```python
from sentra_executors.goal_loop import ConversationGoalLoop
goals = ConversationGoalLoop(control, conversations=None)  # ConversationStore existente opcional
goals.set(owner, conversation_id, *, run_id, objective, operator_approved=False)
goals.status(owner, conversation_id)
goals.stop(owner, conversation_id, *, operator_approved=False)
goals.open(owner, conversation_id, *, principal_id, max_steps=2,
           max_cost_usd=0.0, deadline_seconds=120, operator_approved=False)
goals.loop_status(owner, conversation_id)
goals.loop_stop(owner, conversation_id, *, operator_approved=False)
goals.advance(owner, conversation_id, *, objective, operator_approved=False,
              estimated_cost_usd=None)
```

`conversation_id` é a identidade **lógica** estável do ConversationStore/Canvas,
nunca URL física A/B. `set` precisa do `run_id` real JÁ existente e cria/atualiza
somente o Goal central. Mapping por `(owner,conversation_id)` no namespace
`execution_workspace`; objetivo protegido na projeção existente e digest no
Goal central. Quando ConversationStore é fornecido, status/owner/workspace da
conversa são validados antes de cada chamada. `status` retorna goal/run/loop e
`automatic_execution=False`; sem objetivo retorna `state='UNSET'`.

`open` delega a BoundedGoalLoop e retorna `state='BLOCKED',blocked=True,reason`
na falta de grant `goal:iterate` no Goal. **Nunca cria grant**. `stop` cancela
Goal e interrompe pacing; loop_stop interrompe só pacing. Nenhum stop reaplica
ou cancela silenciosamente efeito físico em andamento. APIs host-only exigem
`operator_approved=True` das rotas owner-auth do coordenador, não de modelos.
Após restart, a mesma conversa recupera Goal, loop, limites e WorkItems.

## Ajustes publicados durante a integração (implementados)

- `stage_request` cifra o payload Responses no **mesmo SQLite central**,
  tabela `web_response_requests`; não cria job físico, Run, Operation ou Grant.
  Cada submission_index físico é admitido exatamente uma vez por `admit`;
  o prompt é o texto **exato após transformação upstream**, não JSON Responses.
- `claim` devolve o envelope ChatJob com `lease_token`, `deadline`, `lease_until`.
  Schema SQL original do JobStore: `jobs.id`, `jobs.lease`; não há colunas
  `jobs.job_id`/`jobs.lease_token`. Tokens permanecem host-only.
- `failure` consulta os dois journals; fence/pending => UNCONFIRMED. Nenhum
  parâmetro may_have_sent e nenhuma conversão para QUEUED. Sem fence => FAILED.
- `WebSendAuthority(..., assistant_attestor=None)` oferece `answer(owner,job_id,
  request_id=...,worker=...,browser_principal=...,conversation_id=...,message_id=...,
  revision=...,body=...,identity_epoch=...,complete=False,parent_user_message_id=None)`.
  Quando assistant compartilha metadata.request_id com o user, fornecer
  parent_user_message_id do recibo e injetar callback **host-only**
  `assistant_attestor(**expected)`; expected contém owner/run/job/worker,
  conversation_id/message_id/parent_user_message_id/revision/body_sha256/
  identity_epoch/role='assistant'/state='partial|complete'. Callback devolve
  `{**expected,authenticated:True}` somente de observação independente do host.
  Sem callback: deny. Nunca cadastrar dois messages no mesmo request original.
  Se parent for omitido, deriva-se do recibo user existente; callback continua
  obrigatório. Request assistant distinto exige também require_exact_message
  para assistant, além da prova host de parent/role/body/revision/complete.
- `receipt/reconcile` preservam ANSWERING; somente answer complete com identidade
  comprovada produz ANSWERED. Histórico é protegido e revisões monotônicas.
- Goal status inclui `{goal,goal_id,loop,state}`; loop_status sem objetivo/loop
  retorna UNSET. ConversationStore aceita somente principal exato ou prefixos
  cli:/canvas: desse mesmo principal. Objetivo sensível cifrado na projeção;
  Goal central recebe apenas digest, sem objetivo original em claro.

## Preferências por conversa e Compact&Resume (assinaturas para integração)

```python
store.set_model_preferences(session_id, model, effort, *, workspace=None)
store.model_preferences(session_id, *, workspace=None)
# {requested_model, requested_effort, requested: True, observed: False}
store.record_web_delivery(session_id, view, *, workspace=None)
store.web_delivery_status(session_id, *, workspace=None)
# último view + display_only=True; sem projeção retorna None

from native_bridge.conversation_continuation import ConversationWebContinuation
continuity = ConversationWebContinuation(control, jobs, conversations=None,
                                        account_attestor=None)
continuity.prepare(owner, conversation_id, *, run_id, chat_id, work_item_id,
                   principal_id, request_key, summary, cursor=None,
                   target_url=None, operator_approved=False)
continuity.status(owner, conversation_id, *, allocation_id=None,
                  continuation_id=None)
continuity.resume(owner, conversation_id, *, allocation_id=None,
                  continuation_id=None, operator_approved=False)
```

Preferências ficam cifradas no **ConversationStore existente**, ligadas a
session/owner/workspace; `None` limpa a escolha correspondente. Sem preferência,
requested_model/requested_effort são None. Workspace opcional aplica `_owned`.
Projeção `sentra.web_delivery` fica na tabela cifrada separada
conversation_web_delivery_views; não aparece em messages/history/context.
É somente exibição, nunca consultada como grant, recibo ou admissão. Nenhuma
projeção transforma UNCONFIRMED em autorização para enviar novamente.

`prepare` grava checkpoint protegido e imutável no ControlPlane existente.
Não cria Run, Operation, WorkItem nem Grant. Sem web:send original ou sem
`account_attestor` host-only, retorna BLOCKED com checkpoint_id e motivo;
nenhum successor é declarado pronto. Callback recebe owner/run/chat/WorkItem/
principal/workspace/source_conversation_id e devolve todos os valores exatos
com authenticated=True. Ausência/negação impede submit. Com gates válidos,
target_url ausente chama allocate_new_target; presente chama stage. Resultado
fica WAITING_RECEIPT até prova real. `resume` chama claim_new_target e commit
somente após recibo exato atestado; status/restart não enviam nem fazem commit.
Prova de conta é revalidada também em resume e em successor_ready após publish;
sem callback após restart, resume continua BLOCKED mesmo com recibo salvo.
CLI/Canvas são owners da apresentação e do binding autenticado dos argumentos.

Fases multipart com Operation distinta: stage_request usa identidade
`root_request_identity + ':phase:' + operation_id`; root fica em metadados
cifrados. Admit usa identidade da fase exata e submission_index explícito.
Mesma identidade staged ligada a outra Operation continua negada. Admit sem
stage serve envios independentes de Responses; o Gateway exige stage antes de
qualquer chamada upstream e usa o mesmo run_id/operation_id na fase.

## Collector Electron host-only, separado do Edge

```python
evidence.configure_host(*, kind="electron", collector_id, source_sha256,
                        principal, workspace, surface_id, worker,
                        enabled, expected_revision)
evidence.challenge_host(*, collector_id, source_sha256, surface_id, worker,
                        document_id, identity_epoch)
evidence.observe_host(*, collector_id, source_sha256, surface_id, worker, evidence)
evidence.invalidate_host(*, collector_id, source_sha256, surface_id, worker,
                         document_id, identity_epoch, reason)
evidence.browser_principal_for(worker, *, collector_id=None,
                               source_sha256=None, surface_id=None)  # str principal
```

Somente chamadas diretas do host autenticado; não expostas pelo relay Edge.
kind='electron', collector_id e surface_id reais, worker real (até 100 chars)
e SHA256 do build real são inscritos explicitamente no mesmo namespace
chat_access. Coluna legada extension_id armazena o collector_id real; kind
separa sua semântica, sem gerar extension ID ou TAB fictício. Surface/worker
ficam vinculados em browser_host_surfaces. Endpoints Edge continuam exigindo
extension a-p32 e TAB-n, além de kind='edge'. Broker/recibos existentes aceitam
o collector_id real em seu argumento legado extension_id após observe_host;
autoridade, grant, digest, nonce, revision e epoch continuam obrigatórios.
browser_principal_for exige enrollment enabled e unívoco do worker real;
é lookup, não prova. require_exact_message e broker exigem observação já
persistida e documento/epoch/revision vivos. O collector Electron atual é
sentra-committed-account-menu-v1, nunca convertido em extension/TAB fictício.

WebSendAuthority.status projeta também answer_message_id e answer_revision
da intenção central para ACK do worker. GoalLoop conserva grant_id original;
revoke/reissue não retoma loop implicitamente.

ANSWERED final encerra e ACKa SOMENTE o job original no formato ChatResult
protegido existente, com texto final real e recibo exato. SENT/ANSWERING não
liberam lease. Status/reconcile fecham crash entre commit final central e ACK
do outbox verificando a mensagem assistant complete e revisão exatas no
histórico protegido; nenhuma mensagem é enviada nessa recuperação.

Limite verificado: prompt físico ChatGPT até 20.000 chars no ChatJob existente.
20.001 é negado antes de criar intenção/job/Send; nunca se trunca o prompt.
Payload Responses pode ser maior, porém a transformação física continua
sujeita a esse limite. ChatResult/answer conserva limite existente de 200.000
chars. Modelo, effort e capacidade de contexto da conta não são inferidos.

UsageLedger.context(session_id, workspace) agora valida owner/workspace da
ConversationStore e enriquece run_id/goal_id por conversation_goal_bindings
do MESMO namespace execution_workspace. Consulta readonly ao durable.sqlite3
existente exige Goal ACTIVE, owner exato do contexto, sessão exata, Goal no
Run da binding e workspace do Run igual à conversa. Binding inválida bloqueia;
tabela ausente mantém compatibilidade legada. Dados de objetivo não são lidos
nem projetados para o ledger. Run/work/agent/operation já vindos do Canvas são
preservados: mapping com Run diferente não fornece Goal nem substitui Run.
Não há criação de Run/Grant ou banco paralelo. require/flush existentes aplicam
orçamento do Goal e projetam consumo real a partir do outbox existente.

2026-10-11 — context também compõe `_web_context` readonly SOMENTE em
gateway_web_transport_mode='durable_v2', buscando o binding host existente
`conversation://sentra-cli/{session_id}` com owner exato no mesmo namespace
session_checkpoint. Enriquece run_id/work_item_id/agent_id somente após validar
Run RUNNING/desired RUNNING, mesmo owner/workspace, WorkItem não terminal no
mesmo Run e assignee exato do agent real. Scopes preenchidos (inclusive Goal
Run) não são substituídos: conflito nega. Operation existente deve pertencer
ao mesmo owner/Run e é preservada; não se cria Operation para o ledger.
Binding ausente/legado não cria autoridade. Context não transporta grant_id,
que NÃO é scope permitido de provider usage: o CLI deve ler o pin original
do binding host e compará-lo ao grant atual antes de chamar /bind.

`UsageLedger.require(ident, workspace, provider, *, authority_context=None)`:
argumento opcional privado do host, nunca HTTP/model. Context atual é resolvido
pela autoridade central; se diferir do snapshot fornecido, nega antes do
budget check. Não usa snapshot como substituto da resolução. Não modifica o
dict recebido. Ledger/usage devem atribuir consumo ao mesmo snapshot aprovado
e persistido em provider_context antes do efeito, mesmo se Goal mudar durante
resposta. `_delivery(submitted)` e `_usage` do CLI devem usar esse MESMO snapshot.

GoalLoop ainda declara automatic_execution=False. RoutineSchedulerService
apenas enfileira WorkItems. CentralExecutorFactory.dispatch_request/submit
exigem máquina registrada, Run/WorkItem RUNNING, assignee exato, capability
declarada em required_capabilities e grant real de execução. GoalLoop cria
WorkItem PENDING sem máquina/capability/argumentos, com grant goal:iterate que
nunca autoriza efeitos físicos. Falta plano host explícito step→machine/
capability/arguments/authority; callback genérico não supre esses gates e não
é implementado como execução autônoma.

Relógio host independente de revisão Worker/central (2026-10-11):
`WebHistoryStore.record_frame(owner,workspace,*,conversation_id,message_id,
revision,role,state,body,host_observation=None)` é aditivo. `host_observation`
exige exatamente revision (int positivo até 2**53), body_sha256, state,
collector_id, source_sha256, document_id e identity_epoch, retornados pelo
callback host autenticado. Não aceita igualdade de relógios como prova:
central revision=2 e host revision=1 são válidos se body/state/documento forem
os mesmos observados. No MESMO provider_content/SQLite/BEGIN IMMEDIATE do
frame, tabela web_history_host_observations mantém um registro por mensagem,
sem outbox novo. Regressão host, mesma revisão com body/state diferentes,
troca de collector/source/document/epoch ou omissão depois de pin negam.
Falha do frame/commit reverte também o relógio host. Replay central idêntico
pode renovar a observação host para revisão maior sem duplicar mensagem.
Purge autorizado remove frame e projeção host na mesma transação.

`AuthenticatedWebFrameIngress.record_answer` mantém assinatura e só encaminha
host_observation do retorno do assistant_attestor, após authenticated=True e
todos campos esperados iguais. Epoch/documento são revalidados contra prova
enrolled do user original. Parâmetro não vem do browser/model payload. Callbacks
trusted de teste sem host_observation continuam no ramo legado quando não há
pin host prévio; esse ramo não permite apagar/bypassar pin já persistido.
