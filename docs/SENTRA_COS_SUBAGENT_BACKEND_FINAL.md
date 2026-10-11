# SUBAGENTE 1 — backend CoS, 2026-10-10

Ownership: native_bridge, sentra_core, sentra_executors/goal_loop.py e persistência
backend. BrowserEvidenceService recebeu extensão host-only por solicitação
explícita do coordenador. Nenhuma edição em Gateway/TurnAuthority, CLI/Canvas,
browser/extensão/Electron, control_plane.py ou control_store.py nesta missão.
Checkout compartilhado preservado; sem commit, push, stash, reset ou clean.
Gateway/upstream existentes não foram reiniciados ou reconfigurados.

O contrato implementado e suas assinaturas estão em
`docs/SENTRA_COS_BACKEND_CONTRACT_CURRENT.md`.

## Implementação entregue

- `native_bridge/web_send.py`: intenção Responses cifrada antes do upstream;
  admission idempotente owner/request_identity/submission_index; Run, Operation,
  WorkItem, principal, workspace e grant originais existentes. Fence single-use
  antes de ACK pré-send, lease central pertencente à Operation e lease física
  exata. Failure e recuperação UNCONFIRMED nunca requeue/send.
- Mesmo broker/recibo V2 existente, com request → user message único. Resposta
  assistant exige observação independente host de parent/role/body/revision e
  complete. Reconcile preserva ANSWERING; nunca deduz ANSWERED por ter message ID.
  Final real encerra/ACKa SOMENTE o job original, com ChatResult cifrado existente.
  Status/reconcile recuperam crash final-central → result/ACK sem enviar.
- `native_bridge/job_store.py`: claim externo explícito; poll não entrega job
  external à extensão. Transações SQLite serializam claim/progress; duas
  conexões independentes não adquirem o mesmo job. Nenhum banco/outbox paralelo.
- `native_bridge/relay.py`: mapping central admitido nos callbacks V2; pre-send
  admite somente lease/fence central existentes. Continuidade revalida o grant
  original antes de poll e ACK, inclusive revoke/reissue. UNION remove duplicação
  legítima entre allocation e transfer do mesmo job após claim.
- `native_bridge/web_delivery.py` e `protocol.py`: fingerprint inclui escolhas
  pretendidas/dispatch sem mudar fingerprints legados; ACK de continuidade
  single-use usa o journal V2 existente e writer transaction.
- `native_bridge/continuation_web.py`: valida Run/principal/WorkItem ativos e
  assignee antes da autoridade de continuidade já existente.
- `native_bridge/conversation_continuation.py`: serviço Compact&Resume comum;
  checkpoint protegido real, grant e conta host verificados antes de submit.
  Sem conta/grant retorna BLOCKED; sem recibo exato não publica sucessor. Resume
  valida owner/conversa/Run/workspace ANTES do efeito. Após restart exige prova
  de conta novamente. Reutiliza stage/allocation/claim/commit existentes.
- `sentra_executors/goal_loop.py`: ConversationGoalLoop persistente e comum;
  status {goal,goal_id,loop,state}, UNSET sem objetivo/loop. Owner somente
  principal/cli:principal/canvas:principal e mesmo workspace. Objetivo cifrado
  na projeção central; Goal recebe digest. Loop pinado ao grant original,
  limites/steps/custo/deadline persistentes; grant ausente retorna BLOCKED.
  Nenhum Grant/Run automático; cada step aprovado cria um WorkItem sem executá-lo.
- `sentra_core/conversations.py`: preferências model/effort cifradas por sessão
  e workspace, requested=True/observed=False; projeção Web cifrada em tabela
  separada, display_only=True, sem inclusão em messages/history/provider context.
- `sentra_mcp/services/browser_evidence.py` e
  `native_bridge/web_evidence_ingress.py`: collector Electron explicitamente
  inscrito kind=electron com collector/source/surface/worker reais; mesma central
  e mesmo broker. Nenhum extension ID ou TAB inventado. Endpoints Edge continuam
  estritos. Enrollment não cria grants nem comprova conta; prova host é separada.

## Testes e verificações executados

Testes próprios:
`tests/unit/test_sentra_cos_backend_web_send.py`,
`tests/unit/test_sentra_cos_backend_conversation_goals.py`,
`tests/unit/test_sentra_cos_backend_conversation_continuation.py`,
`tests/unit/test_sentra_cos_backend_host_collector.py`.
Também atualizado `tests/unit/test_durable_relay.py`: fixture legada agora
verifica negação de alias BROWSER_WORKER para lease TAB exata, preservando
canonicalização de URL e o guard V2 já existente ao início da missão.

As interrupções são SystemExit injetados em fronteiras duráveis; restart fecha
e reabre os serviços/stores reais. Concorrência usa threads com conexões SQLite
independentes. Browser/conta/assistant são fixtures controladas identificadas
como tais; nenhum teste é apresentado como conta real ou E2E em produção.

Seleção anterior ampla: 138 passed em 60.40s. Seleção final de ACK/composição:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_backend_web_send.py tests/unit/test_sentra_cos_gateway_outbox_composition.py tests/unit/test_sentra_cos_backend_host_collector.py tests/unit/test_durable_relay.py tests/unit/test_sentra_cos_web_relay_authenticated_routes.py tests/unit/test_sentra_cos_web_v2_transport.py tests/unit/test_sentra_cos_web_delivery.py
```

Resultado: **51 passed em 25.23s**, inclusive a segunda fase física da composição
Gateway → outbox, final → ACK crash gap, resposta parcial mantendo lease e
prompt físico oversized negado sem job/intenção/Send.

Comandos `git status --short` foram lidos antes das edições e novamente durante
a missão; o checkout já continha muitas mudanças, mantidas. `git diff --check`
nos arquivos tracked próprios retornou exit 0. Parse AST dos 11 arquivos backend
listados acima retornou `AST OK: 11 backend files` / exit 0, sem iniciar serviços.

Falhas intermediárias reais corrigidas: fixture Operation sem idempotency_key;
uso incorreto do retorno string de ConversationStore.open; BEGIN dentro de
transação SQL legada no poll; fixture que ainda aceitava alias TAB. A seleção
antiga ampla registrou 77 passed / 2 failed antes dessas correções; o teste
legado atualizado teve uma tentativa com nome de erro incorreto, corrigida
para UNKNOWN_OR_FOREIGN_JOB. A segurança do matching exato não foi relaxada.

## Limitações verificáveis

- ChatJob ChatGPT aceita no máximo **20.000 chars do prompt físico exato**.
  Teste de 20.001 nega antes de criar job/intenção. Sem truncamento. Payload
  Responses pode ser maior, mas transformação multipart não remove esse gate.
- Answer/ChatResult conserva limite **200.000 chars**. Model/effort persistidos
  são pedidos, sem comprovação de conta/Plus/modelo/contexto do provedor.
- APIs account_attestor/assistant_attestor não instaladas permanecem failclosed;
  enrollment de collector não fornece esses atestados automaticamente.
- Continuidade legada usa grant original, lease física e journal V2 existente;
  lease/fence da Operation real se aplica à nova admissão WebSendAuthority.
  O helper não fabrica Operation/lease para adaptar continuidade legada.
- Goal objective deste adapter é protegido; objetivos de WorkItems e texto de
  steps existentes continuam sujeitos ao schema Governance/pacing existente.
- Não executado navegador/conta real, envio real ou recuperação por kill de
  processo de produção. Não se afirma at-most-once físico no provedor: o
  invariante implementado é autorização de Send única e ausência de resend
  automático em incerteza, com reconciliação por recibo exato.

Seleção ampla final, após ACK final/host collector/single-use progress:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_durable_relay.py tests/unit/test_sentra_cos_backend_web_send.py tests/unit/test_sentra_cos_backend_host_collector.py tests/unit/test_sentra_cos_backend_conversation_goals.py tests/unit/test_sentra_cos_backend_conversation_continuation.py tests/unit/test_sentra_cos_gateway_outbox_composition.py tests/unit/test_sentra_cos_web_delivery.py tests/unit/test_sentra_cos_web_outbox_encryption.py tests/unit/test_sentra_cos_web_authenticated_ingress.py tests/unit/test_sentra_cos_web_continuation_receipts.py tests/unit/test_sentra_cos_web_relay_authenticated_routes.py tests/unit/test_sentra_cos_web_v2_transport.py tests/unit/test_sentra_cos_web_v2_http_ingress.py tests/unit/test_sentra_cos_web_r5_central.py tests/unit/test_sentra_cos_web_r5_checkpoint_crypto.py tests/unit/test_sentra_cos_web_r6_full_cycle.py tests/unit/test_sentra_cos_browser_evidence.py tests/unit/test_sentra_executors_cos_goal_loop.py tests/unit/test_sentra_executors_cos_goal_budget.py tests/unit/test_sentra_executors_cos_host_pricing.py tests/unit/test_sentra_cos_central_transport_composition.py tests/unit/test_conversation_persistence.py tests/unit/test_sentra_context_condensation.py tests/unit/test_sentra_cli_model_effort.py tests/integration/test_relay_transport_roundtrip.py
```

Resultado: **141 passed em 61.38s**, exit 0.

## Revisão independente do Gateway — ownership do coordenador

P1 encontrado em `sentra_model_gateway/gateway.py:1433` e caminho JSON de
`_proxy` em `:1344`: resposta terminal durable é publicada após delivery_view,
sem require_receipts. O gate existe nos endpoints internal complete/browser-
complete (:1805), porém não no retorno HTTP/SSE upstream. Assim upstream
response.completed/HTTP200 pode chegar ao cliente apesar de outbox UNCONFIRMED;
retire posterior (:2019) não retira o sucesso já entregue ao cliente.

Reprodução local sem serviço/restart: GatewayHandler.__new__, _upstream fixture
HTTP200, delivery_view fixture UNCONFIRMED, require_receipts fixture que nega.
Chamado `_proxy('POST','/v1/responses',delivery_capability='fixture-capability')`
com frame SSE response.completed completo e depois JSON status=completed.
O comando Python via stdin está registrado no transcript da missão. Saída:

```text
{'kind': 'text/event-stream', 'status': 200, 'receipt_gate_calls': 0, 'completed_published': True, 'connection_closed_as_uncertain': False}
{'kind': 'application/json', 'status': 200, 'receipt_gate_calls': 0, 'completed_published': True, 'connection_closed_as_uncertain': False}
```

Correção necessária no owner Gateway: gate require_receipts antes de encaminhar
sucesso terminal durable, inclusive JSON. Falha de prova deve terminar o stream
com erro/incerteza e nunca emitir response.completed ou encerramento limpo de
sucesso. Caminhos legados e eventos upstream de erro devem manter sua semântica.
Também existe risco de framing no ramo terminal que grava chunk hex sem conferir
downstream_chunked quando o upstream tem Content-Length e injeta bytes extras.

Backend próprio e composição de admission/send/receipt/answer passaram; os
141 testes não homologam esse ramo terminal do proxy. Nenhuma edição nos arquivos
do coordenador nesta revisão. Achado reportado para correção coordenada.

## Adendo final — UsageLedger, CLI e revisão das correções do coordenador

Entrega adicional própria: `sentra_core/provider_usage.py` e
`tests/unit/test_sentra_cos_backend_goal_usage.py` (6 testes). A assinatura
`UsageLedger.context(ident,workspace)` foi preservada. Agora valida a sessão
da ConversationStore e enriquece apenas com binding central de owner/sessão
exatos, Goal ACTIVE e Goal/Run/owner/workspace reais no durable.sqlite3 existente.
As consultas adicionais são readonly; não há novos Run/Grant/bancos. Run,
WorkItem, agent e operation do Canvas permanecem intactos, mesmo se houver
binding de Goal de outro Run. Mapping inválida bloqueia; tabela inexistente
preserva compatibilidade legada. Objetivo privado não entra no ledger.

Evidência: consumo de 12 tokens fica no Goal/Run correto, sobrevive à retomada
do outbox e bloqueia chamada subsequente pelo budget hard-stop de Goal; outra
sessão fica fora desse escopo. Report ausente permanece unknown e bloqueia
budget de Goal. Teste do CLI real (SentraAgent.step_stream com provider fixture,
sem conta/serviço real) verifica objetivo no contexto protegido, primeiro
consumo real reportado de 10 tokens e segundo envio negado ANTES da callback
provider. Canvas com mapping no mesmo Run recebe Goal; mapping de outro Run
não substitui Run/task/work/agent. Nenhum grant automático.

Comandos adicionais executados:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_backend_goal_usage.py tests/unit/test_provider_usage.py tests/unit/test_sentra_cos_backend_conversation_goals.py tests/unit/test_sentra_cos_backend_conversation_continuation.py tests/unit/test_sentra_cos_gateway_outbox_composition.py tests/unit/test_sentra_cos_cli_canvas_entrypoints.py tests/unit/test_sentra_cli_model_effort.py tests/unit/test_sentra_model_gateway.py tests/unit/test_web_turn_authority.py
```

Resultado: **109 passed em 49.48s**, exit 0, antes de acrescentar o sexto teste
do CLI real. A seleção ampla de 141 citada acima foi repetida acrescentando
`tests/unit/test_sentra_cos_backend_goal_usage.py` (então 5 testes) e
`tests/unit/test_provider_usage.py`: **154 passed em 68.77s**, exit 0.
Após acrescentar o sexto teste do CLI e a correção do pin pelo coordenador:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_backend_goal_usage.py tests/unit/test_web_turn_authority.py tests/unit/test_sentra_cos_gateway_outbox_composition.py
git diff --check -- native_bridge/job_store.py native_bridge/protocol.py native_bridge/relay.py sentra_core/conversations.py sentra_core/provider_usage.py tests/unit/test_durable_relay.py
```

Resultado: **22 passed em 7.91s**, exit 0; diff --check exit 0.
Estes números são seleções independentes, não devem ser somados.

Revisão independente atual das integrações do coordenador, sem editar seu scope:

- Preflight marca ready no JobStore real. Replay READY revalida autoridade
  original e mesma identidade física, reutiliza job sem nova lease. Crash entre
  claim/ready e mapping do gateway bloqueia replay; não há resend inseguro,
  porém essa janela ainda exige reconciliação para recuperar disponibilidade.
- Failure consulta mapping original antes do heartbeat/conta; valida
  job/document/epoch/digest exatos. Perder página após SENDING permite registrar
  UNCONFIRMED. may_have_sent=False não transforma incerteza em NOT_SENT/requeue.
  Teste composition efetivo cobre essa perda de página após a segunda fase.
- Pin principal/grant em TurnCapability e gateway_bound_web_turns foi conferido
  após a correção do coordenador; browser_event compara owner/run/work/principal/
  grant e rehydrate antigo sem pin nega. Composition nega substituição de grant
  antes de criar jobs e verifica pin após restart. Testes 22 acima incluem isto.
- Migração de submissions usa BEGIN IMMEDIATE antes do DDL/PRAGMA e preserva
  chave token/Operation/index. Fase sucessora não colide com index zero anterior.
- Lifecycle mantém Operation por fase no mesmo Run/WorkItem, leases existentes,
  fences e trace físico exato. Complete interno passa pelo gate de todas as
  submissões ANSWERED; SENT/partial não bastam. Nenhum novo P1 confirmado nessa
  transição. Leitura do descriptor/host identity não cria calibração de conta.
- Proxy conecta antes de escrever request e não reconecta após erro ambíguo;
  stream truncado não recebe chunk final limpo. Esses guards não resolvem o P1
  terminal de sucesso sem require_receipts, ainda presente na leitura final.

**P1 adicional confirmado no CLI**: `sentra_cli/agent.py:328`, fallback de
`_bind_existing_web_authority`, substitui run_id do contexto por pinned.run_id
quando faltam work/agent, sem comparar o Run original. Com UsageLedger ligado
ao Goal, isso confere budget no Run A e envia no Run B. Reprodução por stdin
usou ConversationStore, Goal, dois Runs, WorkItem/Grant reais de fixture e
SentraAgent.__new__ com client admin stub: imprimiu
`mismatched_run_bound=True, admin_bind_calls=1`. Não houve HTTP/envio real.
Correção necessária no owner CLI: se context.run_id estiver presente e diferir
do pinned.run_id, negar ANTES do /bind, preservando a autoridade existente.
Mesmo cuidado para agent/work já presentes. Achado informado ao coordenador.

P1s pendentes na última leitura: (1) proxy publica terminal SSE/JSON sem gate de
recibos; (2) fallback CLI pode trocar Run do Goal por Run do binding. Pin de
grant/principal foi corrigido e não é listado como pendência atual. Não há
afirmação de homologação geral com esses P1s externos ao ownership backend.

A reprodução do fallback retornou a evidência acima e depois falhou no cleanup
do TemporaryDirectory com WinError32, devido a handle SQLite ainda aberto.
Após terminar o processo, a tentativa de remover somente o diretório temporário
criado pela revisão foi rejeitada pela revisão automática: “blocked by policy”.
Permanece `C:\Users\vitor\AppData\Local\Temp\sentra-goal-bind-review-vbk1wnm1`;
nunca foi diretório de checkout/estado de produção. Nenhuma tentativa de contornar
a rejeição. Gateway/upstream preservados, sem restart, sem contas reais.

## Retomada 2026-10-11 — testes do terminal HTTP e scopes host

Ownership adicional autorizado: NOVO
`tests/unit/test_sentra_cos_gateway_completion_gate.py`. Usa dois servidores
HTTP temporários em loopback com porta efêmera. Subclasse altera somente a rota
de teste; `_proxy` e `_upstream` reais são executados. O gate
DurableWebTransport.require_receipts consulta mapping central, WebSendAuthority,
JobStore, receipt V2 e histórico protegido reais. Capability e observações host
são fixtures explícitas; não constituem E2E de conta real. Produção não é acessada.

Primeira execução com os seis testes originais de UsageLedger:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_gateway_completion_gate.py tests/unit/test_sentra_cos_backend_goal_usage.py
```

**21 passed em 12.06s**, exit 0. Os 15 casos HTTP daquele momento verificaram
UNCONFIRMED/ANSWERING/SENT com response.completed e [DONE] negados sem chunk
terminal limpo; JSON 409 com web_completion_unconfirmed/automatic_retry:false;
ANSWERED permite SSE/JSON; failed/incomplete e HTTP503 preservados. Depois foram
acrescentados cases de múltiplas submissões, mapping vazio e terminal >8KiB.

Entrega própria adicional em provider_usage.py: `_web_context` readonly usa
SOMENTE binding central existente em durable_v2 com logical URI exata e owner.
Valida Run RUNNING/desired RUNNING, workspace, WorkItem não terminal no mesmo
Run e assignee/agent exatos. Não substitui scopes preenchidos; Operation
existente deve pertencer ao mesmo owner/Run. Não cria Run/Operation/Grant.
`require(..., authority_context=None)` compara snapshot host com resolução
central atual e usa essa resolução para orçamento. O snapshot não é mutado.
Budget de work/run/agent é aplicado antes do provider e recebe consumo real.
Ausência de binding não fabrica autoridade; modo legado preservado.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_backend_goal_usage.py tests/unit/test_provider_usage.py tests/unit/test_sentra_cos_cli_canvas_entrypoints.py
```

**25 passed em 9.91s**, exit 0, antes dos dois novos regressions do CLI.

Revisão depois das correções do coordenador identificou três regressões reais:

1. CLI: contexto enriquecido já preenche run/work/agent e pula fallback que
   fornecia grant_id; comparison binding.get('grant_id') perde o pin e aceita
   grant substituto. Teste real `_bind_existing_web_authority` com scope completo,
   revoke/reissue e admin stub confirma ausência de PermissionError.
2. CLI: a leitura de fonte mostrou `_delivery(submitted)` resolvendo context
   novamente enquanto `_usage` usava snapshot aprovado. A primeira reprodução
   foi classificada incorretamente como corrida após aprovação: o fixture
   pausava Goal ANTES de ModelClient._delivery chamar on_before_provider.
   Portanto summary input_tokens=0 daquela execução não comprovava corrida
   A→B. Coordenador corrigiu o fixture para pausar APÓS o hook de admissão,
   mantendo a asserção de 10 tokens no Goal aprovado. Ambos callbacks agora
   usam `_approved_provider_context`. Nenhuma edição CLI feita pelo subagente.
3. Gateway: terminal SSE completo >8192 bytes tem event: response.completed
   removido do sse_tail truncado, portanto é encaminhado SEM gate. HTTP real
   confirmou resposta.completed publicada com UNCONFIRMED; ANSWERED grande é
   encaminhado mas stream fica quebrado. Detectar terminal no frame SSE inteiro
   antes de publicar bytes, sem depender da cauda truncada. Owner informado;
   nenhuma edição em Gateway pelo subagente.

Comandos/resultados das regressões, preservados sem ocultar falhas:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_backend_goal_usage.py -k 'original_web_grant or same_approved_goal'
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_gateway_completion_gate.py -k large
```

Primeiro: **2 failed, 14 deselected em 2.07s**, exit 1. Segundo:
**2 failed, 18 deselected em 5.51s**, exit 1. Seleção ampla iniciada antes dos
cases large: **2 failed, 129 passed em 62.38s**, exit 1. Não é suíte verde.

Avaliação solicitada de execução automática do GoalLoop: não há executor
genérico central de objetivos. RoutineSchedulerService.tick chama fire_routine
e enfileira WorkItems, sem executar. BoundedGoalLoop.advance cria WorkItem
PENDING, sem required_capabilities/machine binding/argumentos, e declara
automatic_execution=False. CentralExecutorFactory._validate_link/submit exige
Run e WorkItem RUNNING, assignee exato, capability declarada, máquina registrada
e política/grant vivo; CentralMachineHost.dispatch exige adicionalmente metadata
workspace_id/machine_id compatíveis com configuração host. goal:iterate não
fornece essas permissões. Depende de plano host explícito e durável por step
(machine/capability/arguments/principal/workspace, WorkItem execution binding,
grant de efeito e Operation/receipt estritos) e executor registrado. Um callback
genérico após advance não cria esse vínculo e não é entregue como autonomia.
Não foi criado worker/grant para contornar dependência; status continua honesto.

Última seleção desta retomada, após acrescentar todos os regressions HTTP e
fechar explicitamente conexões readonly do ledger (contextlib.closing):

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_backend_goal_usage.py tests/unit/test_provider_usage.py tests/unit/test_sentra_cos_gateway_completion_gate.py
```

Resultado: **4 failed, 40 passed em 23.64s**, exit 1. Falhas são os dois casos
CLI acima e UNCONFIRMED/ANSWERED de terminal >8KiB. Arquivo HTTP contém 20 cases;
arquivo Goal/Usage contém 16 cases, incluindo os seis originais rerodados.
Sem skip/xfail das regressões. Diff --check provider_usage exit 0 e AST dos três
arquivos próprios aprovados. Correções adicionais pertencem ao coordenador;
última leitura ainda continha sse_tail truncado antes de detecção e os dois
caminhos CLI citados. Nenhuma homologação final foi inferida desse resultado.

## Revisão após correções e relógio host independente — 2026-10-11

Coordenador corrigiu o terminal durable usando frame SSE completo e flag
terminal acumulada. Pin original de grant agora é consultado mesmo quando
run/work/agent já estão completos. Delivery e uso compartilham
`_approved_provider_context`. O teste de corrida do Goal foi corrigido pelo
coordenador para pausar APÓS `on_before_provider` concluir a admissão. A primeira
reprodução pausava antes desse hook e não provava a corrida alegada; classificação
anterior corrigida acima, mantendo históricos dos comandos/falhas sem atribuir
esse zero-token inválido a uma violação comprovada. A asserção continua exigindo
10 tokens no Goal A aprovado. Não foram afrouxados guards ou assertions.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_gateway_completion_gate.py tests/unit/test_sentra_cos_backend_goal_usage.py tests/unit/test_provider_usage.py tests/unit/test_sentra_cos_cli_canvas_entrypoints.py tests/unit/test_sentra_cli_model_effort.py tests/unit/test_sentra_cos_gateway_outbox_composition.py tests/unit/test_web_turn_authority.py tests/unit/test_sentra_model_gateway.py
```

**133 passed em 63.09s**, exit 0. Inclui os 20 cases HTTP temporários e os 16
cases Goal/Usage. P1s terminal sem gate, terminal >8KiB e grant substituto estão
cobertos e corrigidos no código candidato; Run A/B e snapshot aprovado também.
Não há P1 pendente confirmado nessas correções na revisão atual. Isso não
homologa conta, navegador real, rollout nem processo de produção já iniciado.

Entrega própria adicional autorizada:

- `sentra_mcp/services/web_history_store.py`: parâmetro aditivo host_observation
  em record_frame; nova projeção `web_history_host_observations` no MESMO
  provider_content existente, uma row por mensagem, sem novo outbox. Host
  clock independente do central frame. BEGIN IMMEDIATE grava ambos atomically;
  regressão host, body/state diferentes no mesmo host revision, mudança de
  collector/source/document/epoch e omissão de pin existente negam. Replay
  central idêntico pode renovar host revision maior; purge aprovado remove
  ambos na mesma transação. Mensagem final conserva imutabilidade já existente.
- `native_bridge/web_evidence_ingress.py`: record_answer mantém assinatura;
  só encaminha a projeção do callback autenticado, não browser/model payload.
  Epoch e documento retornados são revalidados contra prova enrolled do user
  original. Callbacks trusted de teste sem projeção continuam no ramo legado
  apenas quando não há pin host prévio.
- `tests/unit/test_sentra_cos_backend_host_history_clock.py`: 12 cases sobre
  SQLite/protected history e ingress/receipt reais com observações fixtures.
  Central revision2/host1 aceita; restart, concorrência, source swap, regressão,
  conflito no mesmo clock e crash depois das duas escritas antes de commit
  preservam invariantes. Final completa somente o original ChatResult existente.

Primeira seleção de host clock: **1 failed, 56 passed em 29.81s**, exit 1.
Única falha foi assertion usando campo `text`, enquanto ChatResult existente
expõe `result`; corrigido somente o teste. Foco posterior:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_backend_host_history_clock.py
```

**12 passed em 1.31s**, exit 0.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_sentra_cos_backend_host_history_clock.py tests/unit/test_sentra_cos_web_history_protected.py tests/unit/test_sentra_cos_backend_web_send.py tests/unit/test_sentra_cos_backend_host_collector.py tests/unit/test_sentra_cos_gateway_completion_gate.py tests/unit/test_sentra_cos_gateway_outbox_composition.py tests/unit/test_sentra_cos_backend_goal_usage.py tests/unit/test_provider_usage.py tests/unit/test_sentra_cos_cli_canvas_entrypoints.py tests/unit/test_sentra_cli_model_effort.py tests/unit/test_web_turn_authority.py tests/unit/test_sentra_browser_host_identity.py
```

**141 passed em 50.93s**, exit 0. Novamente seleções independentes, não somar.
Diff --check provider_usage/ingress exit 0; AST de seis arquivos próprios OK.
Sem edição em Gateway/CLI/constructor; não interferiu nos testes de startup
do coordenador nem criou agente, conta, grant, banco paralelo ou restart.

## Encerramento verificável desta rodada

Seleção final própria (iniciada com 12 cases de host clock):

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/unit/test_durable_relay.py tests/unit/test_sentra_cos_backend_web_send.py tests/unit/test_sentra_cos_backend_host_collector.py tests/unit/test_sentra_cos_backend_conversation_goals.py tests/unit/test_sentra_cos_backend_conversation_continuation.py tests/unit/test_sentra_cos_backend_goal_usage.py tests/unit/test_sentra_cos_backend_host_history_clock.py tests/unit/test_sentra_cos_gateway_completion_gate.py tests/unit/test_provider_usage.py tests/unit/test_sentra_cos_gateway_outbox_composition.py tests/unit/test_sentra_cos_web_delivery.py tests/unit/test_sentra_cos_web_outbox_encryption.py tests/unit/test_sentra_cos_web_authenticated_ingress.py tests/unit/test_sentra_cos_web_continuation_receipts.py tests/unit/test_sentra_cos_web_relay_authenticated_routes.py tests/unit/test_sentra_cos_web_v2_transport.py tests/unit/test_sentra_cos_web_v2_http_ingress.py tests/unit/test_sentra_cos_web_r5_central.py tests/unit/test_sentra_cos_web_r5_checkpoint_crypto.py tests/unit/test_sentra_cos_web_r6_full_cycle.py tests/unit/test_sentra_cos_browser_evidence.py tests/unit/test_sentra_cos_web_history_protected.py tests/unit/test_sentra_executors_cos_goal_loop.py tests/unit/test_sentra_executors_cos_goal_budget.py tests/unit/test_sentra_executors_cos_host_pricing.py tests/unit/test_sentra_cos_central_transport_composition.py tests/unit/test_conversation_persistence.py tests/unit/test_sentra_context_condensation.py tests/unit/test_sentra_cli_model_effort.py tests/unit/test_sentra_cos_cli_canvas_entrypoints.py tests/unit/test_sentra_browser_host_identity.py tests/integration/test_relay_transport_roundtrip.py
```

**229 passed em 107.59s**, exit 0, sessão executada 17468. Depois foram
acrescentados quatro cases de revision inválida (0, -1, bool, float) que não
gravam nenhuma row e um case purge/consent que remove frame e projeção host
juntos. Foco completo do arquivo final: **17 passed em 3.04s**, exit 0.
Não somar seleções. Consolidado 23 módulos do coordenador permanece evidência
do coordenador, não é declarado como comando executado pelo subagente.

Arquivos próprios desta retomada: `sentra_core/provider_usage.py`,
`native_bridge/web_evidence_ingress.py`,
`sentra_mcp/services/web_history_store.py`,
`tests/unit/test_sentra_cos_backend_goal_usage.py`,
`tests/unit/test_sentra_cos_gateway_completion_gate.py`,
`tests/unit/test_sentra_cos_backend_host_history_clock.py` e estes dois docs
backend (contrato/relatório). Alterações anteriores da missão estão enumeradas
na seção Implementação entregue. A correção do hook do teste de corrida foi
realizada pelo coordenador e preservada; nenhuma edição concorrente foi perdida.

Estado final da revisão: P1s confirmados tratados no código candidato e testes
passando; ausência de conta/modelo/calibração/grants reais continua failclosed.
Não há afirmação de homologação da rota real. GoalLoop é pacing persistente,
não executor autônomo: dependência formal de plano host e gates físicos permanece.
Limites existentes: prompt ChatGPT 20.000 chars, ChatResult 200.000 chars;
WebHistoryStore também exige frame <=131.072 bytes UTF-8 e workspace <=8MiB.
Portanto ChatResult aceitar texto não significa history aceitar o mesmo frame.
Não se ampliaram limites nem se truncou texto. Keyrings/credenciais existentes
preservados; foi usada a proteção OS existente, sem migração de chaves.
Nenhuma operação em processos de produção, incluindo Gateway/upstream, nesta
retomada. O bloqueio do restart reportado pelo coordenador não foi contornado.
