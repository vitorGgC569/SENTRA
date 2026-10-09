# Rodada 3 — workflows subordinados e Activepieces

Implementação preparada em 09/10/2026. **Nenhuma validação desta rodada foi executada**, conforme a coordenação: implementação integral primeiro, validação conjunta ao final. Os resultados focados da rodada ACP são históricos e não comprovam estes providers.

## Fontes efetivamente consultadas

Reavaliação37: seções 16 (LangGraph), 17 (Temporal) e 33 (Activepieces), preservando o domínio de workflows subordinados a WorkItem.

| Clone / HEAD local | Contratos incorporados |
| --- | --- |
| LangGraph `bfcfea554ed5c7f7be562cebf8825e911b493ab1` | `libs/checkpoint/langgraph/checkpoint/base/__init__.py`: parent checkpoints e pending writes; `libs/langgraph/langgraph/pregel/_retry.py`: progresso e idle timeout; `libs/checkpoint/langgraph/store/base/__init__.py`: namespace e TTL. |
| Temporal `bae8771853cff3f127b979310e22dcd61c28375c` | `service/history/workflow/retry.go`, `common/retrypolicy/retry_policy.go`: classificação, backoff, expiração e máximo incluindo a primeira tentativa; `service/history/workflow/update/registry.go`: admitido versus concluído e recuperação. |
| Activepieces `a9b86f6ed9e55b74fdf27028a585135e75815e0e` | `packages/pieces/framework/src/lib/piece.ts`, `action/action.ts`, `trigger/trigger.ts`, `context/index.ts`, `context/versioning.ts`: SDK real, forms, output descriptors, hooks, `_dedupe_key`, contexto V2. `packages/server/api/src/app/flows/step-run/sample-data.controller.ts`, `flows/flow-run/flow-run-service.ts`, `pieces/metadata/piece-metadata-controller.ts`: rotas HTTP reais. `packages/server/engine/src/lib/variables/connection-token.ts` e `helper/error-handling.ts`: conexão armazenada e retry interno. |

São semânticas incorporadas ao SENTRA e um transporte Activepieces efetivo; não se afirma execução de servidor Temporal ou runtime LangGraph. Esses serviços continuam exigindo SDKs/workers/deployment próprios quando houver um subworkload que os justifique.

## Autoridade e binding ao host

`CheckpointedWorkflowWorker` e `ActivepiecesPieceProvider` recebem o **gate durável real do host** e usam `HostScopedInteropGate`. Sob `center.bind_provider`, o adapter empresta somente o intent ContextVar com `_fingerprint` idêntico. O nested helper não reserva outra operação, não toma outro lock e não encerra lease/ack. O handler outer permanece o único committer. Fora desse contexto, o mesmo helper delega normalmente ao DurableInteropGate.

Não existem tabelas próprias de Run, WorkItem, Operation, grant ou lease. As tabelas `wf_*` e `ap_*` persistem projeções, referências, payloads protegidos, checkpoints e dedupe. **Não importar fixtures loopback como providers reais.** `activepieces_loopback.py` foi preservado para seus testes históricos.

Assinatura de integração no domínio já existente:

```python
bridge = SubagentWorkflowBridge(
    center.protocol_gate(), database=projection_database,
    workspace_root=workspace, workflow_id=workflow_id,
    work_item_id=work_item_id, principal_id=agent_id,
)
worker = bridge.bind_worker(
    definitions=definitions, bindings=bindings, worker_version="worker1",
    compatible_worker_versions=frozenset(),
    payload_resolver=resolve_protected_workflow_payload,
)
# O host precisa já anunciar essas capabilities e conceder escopo adequado.
for cap in (
    "workflow:create", "workflow:advance", "workflow:resume", "workflow:signal",
    "workflow:cancel", "workflow:observe", "workflow:output", "workflow:memory",
):
    center.bind_provider(cap, worker.host_handler)
center.bind_provider(binding.capability_id, worker.host_activity_handler)
center.bind_provider(binding.observe_capability, worker.host_activity_handler)
```

`worker.host_handler(request)` / `worker.host_activity_handler(request)` retornam `dict` ou `OperationResult`, compatíveis com o handler central. **Não retornam DispatchOutcome ao host outer.** Os métodos diretos retornam DispatchOutcome para callers fora de bind_provider.

Para compartilhar uma capability entre pieces avulsas e workflows, registrar **um único dispatcher**; `bind_provider` rejeita duplicação:

```python
async def pieces_dispatch(request):
    if request.arguments.get("workflow") is not None and request.capability_id in {
        binding.capability_id, binding.observe_capability,
    }:
        return await worker.host_activity_handler(request)
    return await pieces.host_handler(request)

center.bind_provider("activepieces:action", pieces_dispatch)
center.bind_provider("activepieces:observe", pieces_dispatch)
center.bind_provider("activepieces:cancel", pieces.host_handler)
```

Não chamar `worker.advance` e em seguida despachar um activity intent dentro do **mesmo** handler central de advance. Isso tentaria emprestar outra identidade enquanto o controle outer mantém seu fence. O caller recebe `ready`, retorna do controle e submete cada intent a uma operação central distinta.

## Contrato de workflow

`WorkflowDefinition(definition_id, version, worker_version, steps)` é um DAG imutável com fingerprint de definição. `ActivitySpec` suporta:

- `kind="activity"`: `handler_id`, `handler_version`, dependências, `inputs_json`, retry, idle/total timeout;
- `kind="wait"`: sinal declarado e/ou deadline persistido; deadline com sinal expira com `SIGNAL_EXPIRED`;
- `kind="subflow"`: definição/versão filha fixadas, namespace descendente, inputs mapeados e output reutilizado.

Inputs usam valores literais ou objetos `{source: "input"|"activity"|"signal"|"literal", step_id?, path?, value?}`. Outputs de dependências só ficam disponíveis após confirmação central. O worker verifica o pin de cada binding e a versão originalmente persistida; `compatible_worker_versions` é uma decisão explícita do host, não um bypass automático de schema/definição.

`WorkflowActivityBinding(handler_id, version, capability_id, arguments, invoke, observe=None, observe_capability=None, observe_arguments=None)`:

- `arguments(inputs, workflow_reference) -> dict`: intent exato, vinculado pelo grant central;
- `invoke(request, inputs, workflow_reference, heartbeat) -> ActivityReceipt`, async ou sync;
- `observe(request, entry, workflow_reference, heartbeat) -> ActivityReceipt`, async: consulta real, sem repetir o efeito;
- `observe_arguments(entry, workflow_reference) -> dict`: intent da capability de observação.

Referência imutável de atividade: `{workflow_id, namespace, step_id, attempt, definition_sha256}`. `ActivityReceipt` distingue SUCCEEDED/FAILED/WAITING/UNCERTAIN/CANCELLED e NOT_STARTED/COMPLETED/UNKNOWN, com output, failure_type, retryable, provider_reference e artifacts. SUCCEEDED exige COMPLETED. Retryable exige FAILED+NOT_STARTED.

`RetryPolicy` impõe allowlist de failure types, max_attempts incluindo a primeira tentativa, backoff limitado e expiração. **UNCERTAIN nunca produz outra tentativa de efeito.** Falha confirmada antes do início pode produzir attempt seguinte após o deadline; essa tentativa recebe sua própria identidade central. Não existe loop de retry de effects dentro do worker.

Antes do efeito, grava-se IN_FLIGHT. Depois do receipt real, grava-se pending write protegido e PENDING_ACK. `advance/resume` confirma status e `receipt_sha256` no journal central antes de usar output ou liberar retry. Perda de ack, digest divergente ou falta de receipt tornam o nó UNCERTAIN. Etapas independentes podem continuar; dependências do nó incerto permanecem bloqueadas.

Um observer persiste outro pending write com a identidade da **operação de observação**. Só o ack central dessa observação pode promover o resultado consultado. Isso pode desbloquear o workflow sem falsificar/reescrever a autoridade da operação original incerta. `reconciliation` contém capability, args e original_operation_id para o host consultar o provider.

O timeout por inatividade só é renovado por heartbeat real do binding/transport; não há heartbeat artificial para esconder processo parado. Total timeout e cancelamento aguardam a limpeza do binding owned. Cancelar o workflow impede próximos efeitos em filhos, retorna IDs ativos também dos namespaces descendentes e nunca declara rollback. Cancelar efeito remoto exige `activepieces:cancel` separado e observação do provider.

Intents de controle, sempre com args exatos:

| Capability | Arguments |
| --- | --- |
| `workflow:create` | workflow_id, definition_id, definition_version, definition_sha256, input_sha256 |
| `workflow:advance`, `workflow:resume`, `workflow:cancel` | workflow_id, namespace (raiz é `""`) |
| `workflow:signal` | workflow_id, namespace, name, signal_id, payload_sha256 |
| `workflow:observe` | workflow_id, namespace, checkpoint_id (ou null) |
| `workflow:output` | workflow_id, namespace, step_id |
| `workflow:memory` | workflow_id, namespace, action, key, value_sha256, query, limit, ttl_seconds |

`payload_resolver(request, digest_argument_name)` retorna o payload protegido exato (pode ser async). Ex.: input_sha256, payload_sha256, value_sha256. O worker confere o digest; payload não precisa aparecer nos argumentos/journal público. Inputs vazios e sinal null dispensam resolver.

Sinais registram fase ADMITTED após admissão de controle; somente sinais cuja operação central foi SUCCEEDED podem ser consumidos. Consumo e checkpoint são uma transação, passando a COMPLETED. IDs duplicados com mesmo conteúdo não geram nova atualização; conflito de conteúdo é recusado. `observe` retorna fases sem revelar o payload. Checkpoints históricos são somente leitura: não executam efeitos nem desfazem o mundo. Criação com mesmo workflow_id e input/parent alterados é recusada.

Memória de workflow faz busca lexical por namespace descendente, com TTL e digest; não instala embeddings nem autoriza outro namespace. Checkpoints/outputs/sinais usam a proteção DPAPI/keyring existente, sem fallback plaintext. `SubagentWorkflowBridge.run_step`, `checkpoint` e `reconcile` permanecem compatíveis em modo fixture e são recusados após `bind_worker`; o modo real exige intents admitidos de observe/advance e bindings configurados.

## Pieces reais e catálogo

```python
descriptor = PieceDescriptor.from_metadata(
    name=package_name, version=exact_version, metadata=actual_sdk_metadata,
)
pieces = ActivepiecesPieceProvider(
    center.protocol_gate(), catalog=ActivepiecesCatalog([descriptor]),
    store=ActivepiecesProjectionStore(piece_database, workspace=workspace),
    backend=backend,
    connection_resolver=resolve_scoped_connection,
    input_resolver=resolve_protected_piece_inputs,
    trigger_admitter=admit_existing_central_task,
    trigger_lookup=lookup_existing_central_task,
)
binding = pieces.workflow_binding(
    handler_id="connector1", piece_name=descriptor.name,
    piece_version=descriptor.version, member=action_name,
    connection_id=connection_id, hook="action", subscription_id=None,
)
# ActivitySpec.handler_version deve ser binding.version.
```

`pieces.intent(...) -> dict` fixa nome/version/member/hook, invocation_id, props_sha256, conexão, descriptor_sha256, backend_sha256, workflow, subscription_id e trigger_payload_sha256. `invocation_id` já utilizado recusa um novo efeito mesmo se vier outro Operation ID. Em workflows é derivado da referência/attempt. Catálogo ou backend alterado exige outra decisão/pin; discovery não autoriza nem instala.

O catálogo valida propriedades obrigatórias e tipos estáticos, apresenta forms e o outputSchema original. **OutputSchema do SDK é uma estrutura de campos para UI, não JSON Schema.** Propriedades dinâmicas/provider validators não são inventados. O host fornece valores já resolvidos e tipados; campos secretos são resolvidos pela conexão, não como props comuns. O resolver de conexão recebe `(connection_id, request, descriptor)` e entrega o AppConnectionValue real V2 da conexão autorizada; não se faz OAuth refresh implícito. `connections.get(key)` só aceita essa conexão.

Provider métodos: `execute(request, props=..., trigger_payload=None)`, `observe(request, invocation_id=..., cancel=False, workflow=None)`, `artifact(request, invocation_id=..., artifact_id=...)`, `catalog_read(request, piece_name=..., piece_version=..., project_id=...)`, `ingest_trigger(...)`, `reconcile_trigger(...)`; `host_handler` faz dispatch e resolve payload protegido.

### SDK owned

`InstalledPieceBundle(piece_name, piece_version, module_path, export_name, package_json, module_sha256, lock_file, lock_sha256)` aponta para um **bundle construído e instalado explicitamente pelo proprietário**, com framework/dependências completos. O provider nunca executa install, npx, arbitrary catalog scripts ou metadata imports automáticos.

`OwnedPieceSDKBackend(node_executable, install_root, bundles, artifact_root, project_id, flow_id, flow_version, project_external_id=None, file_publisher=None, schedule_handler=None, webhook_url=None, server_context=None, timeout=120)` verifica paths/digests/package version e chama `activepieces_worker.mjs` com Node absoluto. Credenciais vão por stdin, não argv/env/logs. O worker importa o export aprovado, verifica `piece.metadata()` contra o descriptor e chama **getAction(...).run / getTrigger(...).run, onEnable, onDisable, onRenew** reais. Contexto suportado é V2 do clone (floor SDK 0.82.0); V1/legado é recusado.

RPCs SDK efetuam trabalho real sob checkpoint do fence: store FLOW/COLLECTION protegido e scoped; arquivo bounded de saída real; output.update/tags.add persistidos como artefatos; conexão selecionada; project.externalId configurado. `files.upload` exige callback real `(request, path, name) -> {id, url HTTPS}`; `setSchedule` exige callback real `(request, schedule)`. O scheduler do host deve associar schedule à subscription_id e somente disparar operações autorizadas; o provider não cria scheduler global. RPCs de assinatura void são aguardados antes de sucesso.

Cleanup usa o helper owned existente: session/process group POSIX ou Windows JobObject, inclusive sucesso, desconexão, timeout e cancelamento. Encerrar processo não comprova rollback de SaaS. Import/module initialization pode produzir efeito; erro após spawn é UNKNOWN, inclusive antes de run(). Arquivos binários são artefatos reais no artifact_root configurado, sob permissões de filesystem do host; JSON, tags e progresso são protegidos no SQLite.

**Perfil ainda deliberadamente incompleto:** APP_WEBHOOK/createListeners, flows.list, run.stop/respond e waitpoints internos de pieces exigem serviços reais adicionais e falham explicitamente. Wait/signal/subflow de SENTRA já funciona no worker, mas não se apresenta como API de waitpoint do servidor AP. Observer SDK genérico não existe: após perda de resposta externa, o host precisa fornecer observação específica do conector. Métodos SDK REST auxiliares só funcionam com server_context real explicitamente configurado. Retries internos de biblioteca/conector dependem da sua idempotência; o host deve selecionar/rever o bundle antes de habilitar efeitos.

### HTTP nativo

`WorkflowHTTPClient(base_url, token, enabled=True, client=None, timeout=60)` usa HTTPS ou loopback, opt-in, sem redirects/env/retries automáticos, JSON bounded, duplicatas/NaN rejeitados. Requer httpx e serviço AP real com workers habilitados.

`ActivepiecesHTTPBinding(piece_name, piece_version, action_name, project_id, flow_id, flow_version_id, step_name, step_sha256, props_sha256, connection_id=None, connection_name=None)` vincula o host ao snapshot literal armazenado. `connection_id` é ID scoped SENTRA; `connection_name` é o nome AP explicitamente associado. O provider verifica o input auth armazenado, project, versão, member, step digest, inputs literais e retryOnFailure desligado. Templates de sample data/dynamic input são recusados; para inputs resolvidos em tempo real, usar SDK. A credencial do resolver não é enviada ao endpoint; o serviço utiliza sua conexão persistida conforme o mapping pinado.

Transportes reais:

1. GET `/v1/flows/{flow_id}?versionId=...&projectId=...` confirma snapshot;
2. POST `/v1/sample-data/test-step` com projectId/flowVersionId/stepName **executa efeitos reais** e retorna FlowRun;
3. GET `/v1/flow-runs/{id}?projectId=...` observa steps/output/status;
4. POST `/v1/flow-runs/cancel` com projectId/flowRunIds, seguido de GET, confirma cancelamento sem alegar rollback;
5. GET `/v1/pieces/{scope}/{name}?version=...&projectId=...` (ou nome sem scope), sob `activepieces:catalog`, retorna metadata para revisão, sem substituir catálogo vivo.

Não existe endpoint inventado `/execute`. A resposta de enqueue é WAITING/UNKNOWN, com run ID persistido. Só output real do step SUCCEEDED prova conclusão. Perda do POST sem run ID permanece UNCERTAIN; nem HTTP 429 após POST prova que nada iniciou. HTTP pré-POST recusado/transitório pode certificar NOT_STARTED. Cancelamento não é um receipt genérico de sucesso da peça.

### Triggers e admissão de tarefas

Hooks usam `activepieces:trigger_enable/trigger_disable/trigger_renew/trigger_run`; `subscription_id` é obrigatório e fixa escopo, descriptor/member e conexão. onEnable é único; onRenew/run exige ack central do enable; onDisable bloqueia imediatamente ingress/polling e seu efeito externo deve ser confirmado pelo próprio hook/observer. Falha incerta do disable não reabre assinatura nem habilita outra tentativa silenciosa.

`input_resolver(request)` retorna props da ação/hook; para trigger-run, envelope **exato** `{props, trigger_payload}`; para trigger_ingest, events array. Trigger output vira artefato protegido e integra evidence central.

`ingest_trigger(request, subscription_id=..., invocation_id=..., events=...)` exige capability/args `{subscription_id, invocation_id, events_sha256}`, confirmação central do enable e de um trigger-run da mesma subscription, e digest do artefato de saída real correspondente. Para cada `_dedupe_key` (ou digest se ausente), persiste claim antes de chamar `trigger_admitter(request, stable_task_key, event) -> {work_item_id}`. **O callback usa a admissão de tarefa central existente**, em seu escopo legítimo; nenhuma outra Operation/Run é reservada aqui. Novo evento duplicado reutiliza o WorkItem confirmado; mesmo key/conteúdo conflitante é recusado.

Se o callback cria tarefa mas sua resposta se perde, o claim fica pendente e bloqueia nova emissão. `reconcile_trigger(request, subscription_id=..., event_key=...)`, capability `activepieces:trigger_reconcile`, args `{subscription_id,event_key}`, chama somente `trigger_lookup(request, stable_task_key) -> {work_item_id}|None` para recuperar **tarefa já existente**. Nenhuma criação ocorre nessa consulta. Integração necessária: host deve fornecer admissão/lookup com ID determinístico e origem no seu próprio ControlPlane; não passar callbacks simulados.

## Aceitação preparada para o fim da implementação

Arquivos novos de testes:

- `tests/unit/test_sentra_interop_workflow_worker.py`: escrita real local dentro do fence central; bind_provider emprestado; restart/pending ack; lost reply sem resend; observação real do arquivo; etapas independentes; sinal ADMITTED/COMPLETED; subflow/cancel ancestral; idle timeout; retry somente antes do início; freeze de input/version; CAS; memória/TTL/scope.
- `tests/unit/test_sentra_interop_activepieces_provider.py`: **fixture de protocolo explicitamente httpx.MockTransport** para rotas/payloads/pins/WAITING/lost POST/cancel/digests/catalog, usando SQLite central real; dedupe/subscription/storage protegido; teste SDK separado opt-in com piece/framework instalado real. Fixtures não contam como prova de SaaS/AP server.

Comandos PowerShell **documentados para execução futura pelo coordenador; não executados nesta rodada**:

```powershell
python -m pytest tests/unit/test_sentra_interop_workflow_worker.py tests/unit/test_sentra_interop_activepieces_provider.py -q
python -m pytest tests/unit/test_sentra_interop_phase2_workflow.py tests/unit/test_sentra_interop_phase2_activepieces.py -q
```

Para teste SDK real, configurar `SENTRA_ACCEPTANCE_AP_SDK_PROFILE` com arquivo protegido pelo proprietário e executar o teste acima ao final. Perfil JSON tem: node_executable absoluto, install_root, artifact_root contido, project_id/flow_id/flow_version reais do perfil standalone, piece_name/version, member, props, metadata da serialização de `piece.metadata()`, bundle com todos os campos de InstalledPieceBundle, expected_output_sha256. Usar peça útil aprovada cujos efeitos e output sejam conhecidos. Perfil ausente é skip explícito, nunca sucesso simulado. A árvore transitive instalada e lock são responsabilidade do provisionamento aprovado; pin do módulo não promete integridade de todos os arquivos transitive.

Aceitação com AP server externo (não comprovada por fixture): configurar binding literal sem retries internos, grant scoped e conexão real; executar uma ação real, preservar run ID e observar output; interromper resposta do POST e comprovar que uma nova submissão com mesmo invocation_id não dispara outra ação; cancelar execução e observar status; exercitar um webhook/polling real com SDK+callback de schedule, repetir o mesmo evento e conferir um único WorkItem central, executar disable e verificar remoção da assinatura externa. Também exercitar revogação durante transporte e perda de ack central em conjunto com os testes do host.

## Próximas ligações do coordenador

Anunciar/conceder capabilities e ligar os handlers ao host/Canvas/CLI por `bind_provider`; fornecer resolvers protegidos, catálogo de conectores selecionados e bundles/serviço real; implementar schedule, arquivo publicado e admissão/lookup de trigger no ControlPlane existente; mapear UI forms/output descriptors sem tratá-los como JSON Schema; realizar validação conjunta inclusive lease renewal/revogação/recuperação e provas externas. Nada deste documento declara essas ligações já operacionais no host ou provedores ausentes como validados.
