# SENTRA — OpenHands, contexto e descoberta seletiva: segunda onda

Estado: implementação e aceitações preparadas; **validação adiada por instrução expressa do usuário**. Nenhum teste, lint, typecheck, build, benchmark ou validação de runtime foi executado nesta onda. Os resultados da onda ACP anterior são evidência histórica, não conclusão desta entrega nem do objetivo integral dos 37 projetos.

## Fontes e comportamento incorporado

- OpenHands SDK/Agent Server `1.53.0`, clone `third_party/openhands-agent-sdk`, HEAD `2804c1273b4093e632e332a7a572894782c7b1e1`: `conversation_router.py`, `event_router.py`, `models.py`, `sdk/conversation/request.py`, `impl/remote_conversation.py`, tipos de eventos e `context/condenser/llm_summarizing_condenser.py`.
- ToolHive, clone `third_party/toolhive`, HEAD `33ba170aad633e20520f380500a45cd158f24aed`: `pkg/vmcp/optimizer/optimizer.go`, configuração de busca híbrida e `pkg/authz/response_filter.go` para a separação entre relevância e visibilidade autorizada. Não se importou um daemon ou um serviço de embeddings por padrão.
- Reavaliação dos 37 projetos de 09/10 e documentos originais de 08/10 continuam definindo o objetivo integral. Esta onda amplia SDK OpenHands/ToolHive/contexto/CLI, sem reabrir licenças.

O Agent Server deste clone não usa o framing JSONL do harness SENTRA nem uma sequência global de eventos. A rota real é HTTP `/api/conversations`; eventos usam `/events/search`, `page_id`, `next_page_id` e `sort_order=TIMESTAMP`. A recuperação lê desde o início e deduplica por ID/digest para recuperar inclusive inserções com timestamp anterior. O ordinal local de ingestão não é apresentado como sequência do servidor.

## Arquivos da onda

| Arquivo | Conteúdo |
|---|---|
| `sentra_interop/openhands.py` | Parser adicional de eventos SDK reais, vínculos action/observation/tool, digest e evidência tipada sem converter relatório em autoridade |
| `sentra_interop/openhands_provider.py` | HTTP opt-in, associação durável, create/read/reattach/events/evidence/message/run/cancel e integração com gate físico central |
| `sentra_interop/openhands_local.py` | Harness JSONL preservado como harness; cleanup da árvore possuída e compatibilidade com contexto físico central |
| `sentra_interop/tool_catalog.py` | Catálogo fornecido pelo host, visibilidade autorizada, ranking lexical/semântico, estimativa de tokens e invalidação de schema/version |
| `sentra_core/context.py` | Condensação incremental e wrapper explícito de callback LLM usando o ledger existente |
| `sentra_core/conversations.py` | Cache de resumos protegido e aditivo no banco existente; transcript original preservado; commit de chamada auxiliar de contexto |
| `sentra_cli/agent.py` | Contexto padrão conectado antes de cada rodada, callback LLM opt-in e instruções/recibos de máquinas do Canvas nativo |
| `tests/unit/test_sentra_interop_openhands_provider.py` | Aceitações com autoridade central real e transporte HTTP fixture explicitamente identificado |
| `tests/unit/test_sentra_interop_tool_catalog.py` | Aceitações de autorização, relevância, revogação, embeddings explícitos e invalidação |
| `tests/unit/test_sentra_context_condensation.py` | Aceitações de transcript, resumos/ledger, CLI e conservação de operation IDs incertos |

`central.py`, `central_gate.py`, runtime/machine host, CanvasBridge/host, quality, executors e arquivos ACP da primeira onda não foram editados nesta onda. O helper de processos ACP existente é reutilizado sem modificá-lo. O trabalho prévio dos arquivos compartilhados foi preservado com alterações pontuais; não houve reset ou commit.

## Provider OpenHands: configuração e contrato exato

O host cria:

```python
config = OpenHandsServerConfig(
    base_url="https://agent-server.example/api",
    provider_id="openhands-host-1",
    remote_workspace="/workspace/project",
    agent_profile_id="UUID_DO_PROFILE_PROVISIONADO_NO_SERVIDOR",
    enabled=True,
)
transport = OpenHandsHTTPTransport(config, api_key=trusted_api_key)
associations = OpenHandsIdentityStore(database, workspace=trusted_local_workspace)
provider = OpenHandsAgentServerProvider(
    host.protocol_gate(), config=config,
    identity_store=associations, transport=transport,
    authorize_parent=optional_host_parent_reference_pdp,
)
```

Configuração é opt-in; base URL é HTTPS ou loopback HTTP, sem credenciais na URL ou redirects. O token é um argumento separado usado apenas em `X-Session-API-Key`; não integra OperationRequest, config fingerprint, SQLite, erro ou telemetria. O transporte real carrega `httpx` somente quando necessário, usa cliente assíncrono, timeout/limite de resposta, TLS padrão, `trust_env=False`, JSON sem keys duplicadas/nonfinite e sem retries de efeitos. Um cliente injetado é propriedade do host e não é fechado implicitamente pelo provider.

O workspace remoto e Agent Profile são configuração confiável do host; não se aceitam tool modules, client tools, secrets, hooks ou comandos arbitrários do catálogo. Criar a conversa usa `workspace.working_dir`, `agent_profile_id`, `conversation_id` e, quando solicitado, `parent_conversation_id`/`initial_message` com `run=False`. O profile remoto continua responsável por configurar seu agente, LLM e ferramentas. SENTRA não afirma autorizar cada ação executada internamente pelo agente remoto.

Todas as operações exigem `OperationRequest` da Machine/WorkItem/grantee concedidos. A tabela abaixo define igualdade exata de argumentos; campos extras não são ignorados. IDs remotos são UUIDs explícitos, escolhidos antes do POST. Hashes usam a função `_digest` do módulo (JSON canônico, UTF-8); usar `create_arguments` para evitar divergência.

| Método | Capability | Argumentos |
|---|---|---|
| `create(request, local_id, conversation_id, parent_local_id=None, initial_message=None)` | `openhands:create` | `create_arguments(...)`: local_id, conversation_id UUID normalizado, parent_local_id, initial_message_sha256 ou null, config_sha256 |
| `read(request, local_id=...)` / `reattach(...)` | `openhands:read` | `{"local_id": id}` |
| `events(request, local_id=..., page_id=None, limit=100)` | `openhands:events` | `{"local_id": id, "page_id": cursor_or_null, "limit": 1..100}` |
| `evidence(request, local_id=..., event_id=...)` | `openhands:evidence` | `{"local_id": id, "event_id": id}` |
| `send_message(request, local_id=..., text=..., run=False)` | `openhands:message` | `{"local_id": id, "text_sha256": digest(text), "run": bool}` |
| `run(request, local_id=...)` | `openhands:run` | `{"local_id": id}` |
| `cancel(request, local_id=..., immediate=True)` | `openhands:cancel` | `{"local_id": id, "immediate": bool}` |

Os métodos retornam `DispatchOutcome`. `run` é um POST separado e nunca envia novamente uma mensagem. O HTTP 429 da rota de mensagens tem uma semântica especial no clone: a mensagem já foi salva, mas não há capacidade de run. O provider registra `UNCERTAIN` com `message_saved=True`, `resend_message=False`, `run_capacity_full=True`. Não faz retry nem POST automático de run. Timeout/desconexão também não justificam reenvio com outro ID.

`reattach` é somente GET. Associação PREPARED/UNCERTAIN conserva o UUID pré-selecionado, permitindo consultar o mesmo ID depois de um POST interrompido. Outra tentativa de create com o mesmo local_id é bloqueada mesmo com nova key. Um 404 não cria outra conversa.

`recover_events(local_id=..., request_factory=..., max_pages=32)` é um iterador assíncrono. O factory recebe `(capability_id, exact_arguments)` e deve construir uma operação de leitura nova e autorizada por página. A recuperação retorna páginas `DispatchOutcome`, parte do início e só usa GETs. IDs/digests repetidos não geram outra evidência; um mesmo ID com conteúdo diferente é rejeitado. Cursor cíclico é rejeitado. Esgotar o limite levanta `OpenHandsRecoveryLimit` com `.cursor`, para continuação explícita por `events`; não declara recuperação completa.

## Autoridade central e vínculos pai/filho

O provider exige gate injetado com `physical_context`; não oferece fallback de autoridade real para um journal em memória. Métodos chamados diretamente usam `gate.execute`, reserve/fence/lock e evidência do journal central. O HTTP verifica checkpoint antes da I/O física.

Se `host.bind_provider` já admitiu e cercou **o mesmo pedido**, o provider reconhece o contexto atual, verifica fingerprint/escopo, faz checkpoint e executa o corpo sem uma segunda reserva/lock. O callback do host deve desembrulhar o retorno:

```python
async def configured_create(operation):
    outcome = await provider.create(
        operation, local_id=trusted_local_id, conversation_id=preselected_uuid,
        initial_message=trusted_content_matching_request_digest,
    )
    return provider.host_result(outcome)

host.bind_provider("openhands:create", configured_create)
```

`host_result` retorna payload para sucesso ou o OperationResult para estados como UNCERTAIN/CANCELLED. O host, não o provider, confirma/persiste o resultado da operação já cercada. Request de outro contexto é recusado. Isso evita repetir a reserva de uma operação que o centro já está executando.

Também há `provider.host_handler(operation)` pronto para registro por capability: `host.bind_provider(capability, provider.host_handler)`. Ele roteia as sete capabilities da tabela. Para mensagens ou create com initial_message, fornecer `message_resolver(operation)` ao construtor; o resolver confiável, síncrono ou assíncrono, recupera texto protegido que deve coincidir com o hash do pedido. Falta de resolver nega a submissão. Não há texto de prompt oculto em um novo banco de operações. `provider.close()` fecha somente o cliente HTTP possuído; não pausa nem apaga conversas remotas.

O banco `OpenHandsIdentityStore` guarda associação local/remota, fingerprint de provider/config, principal/Machine/WorkItem, parent local, estado/cursor e eventos/projeções. Não contém tabelas Run/Operation/Grant/Lease. Eventos completos ficam protegidos por DPAPI/keyring; a lista padrão retorna apenas tipos, vínculos, timestamp e SHA-256. Ler conteúdo exige a capability separada `openhands:evidence`.

Pai e filho conservam IDs separados. Por padrão, uma referência ao pai só é aceita no mesmo principal/Machine/WorkItem/config. Para filhos pertencentes a outra tarefa/agente, `authorize_parent(parent_binding_metadata, child_request)` deve retornar uma `PolicyDecision` explícita e sem constraints não avaliadas, derivada da autoridade do host para a referência ao recurso pai. O callback não concede a capability de criação da criança; essa continua subordinada ao gate. Falta de callback nega referência entre escopos. A API remota também exige mesmo workspace.

IDs de `sub_conversation_ids` recebidos não criam bindings ou grants locais automaticamente. Cada child precisa ser explicitamente associado pelo host. O papel desse mapa é correlacionar sessões; relações autoritativas Run/WorkItem/Chat continuam no centro existente.

## Eventos, ferramentas e cancelamento

`OpenHandsSDKEvent.from_mapping(raw)` usa os discriminators reais de classes (`ActionEvent`, `ObservationEvent`, `MessageEvent`, `ACPToolCallEvent`, etc.), o sentinel parent `__root__`, source e IDs estáveis. Action/observation exigem tool_name/tool_call_id e a observação aponta para action_id. JSON de ação/observação permanece dado protegido, sem execução automática de ferramenta ou leitura de paths reportados.

`ACPToolCallEvent` iniciado e terminal são **dois eventos com IDs distintos** do clone, correlacionados por tool_call_id. Ambos ficam preservados; a projeção de tool aponta para o evento terminal. Um started que chega atrasado não rebaixa uma projeção terminal. Não foi inventado um `AgentServerToolCallEvent` mutável.

Evidências indicam `evidence_origin=openhands-agent-server` e `verified_sentra_effect=False`. Não se converte relato de ação ou observation em comprovação de efeito SENTRA. Uma observação pode trazer exit code/output/diff, mas seu significado e sua verificação pertencem ao executor/consumidor autorizado.

`cancel(immediate=True)` usa `/interrupt`; false usa `/pause`, que no clone espera a chamada LLM atual. Depois do ACK, GET confirma estado `paused`. Só essa confirmação retorna CANCELLED. Se faltar confirmação, registra UNCERTAIN; após ACK seguido de falha de leitura inclui `STATUS_UNAVAILABLE_AFTER_ACK`. Sempre registra `effects_rolled_back=False`: pausar não desfaz ferramentas executadas. Reconciliar é ler a mesma conversa/operação, não reenviar mensagem ou run.

O módulo `openhands_local.py` continua explicitamente um harness JSONL que não é o Agent Server. Ele reutiliza grupos/Job Objects de processos possuídos e o contexto central, inclusive no cancel, sem representar o ACK do harness como prova de provider externo.

## Contexto conectado à CLI

`RollingContextCondenser(max_chars=120000, keep_first=2, keep_recent=16, summary_chars=6000)` projeta mensagens com seq/id/role/content. Preserva system prompt, mensagens iniciais, mensagens de sistema e contexto recente. Recibos de máquina contendo UNCERTAIN e o journal de ferramentas recuperadas permanecem exatos; pressionar o budget com esses dados causa erro explícito, em vez de apagar IDs ou instruções silenciosamente. Mensagem mais recente que não cabe não é truncada.

O padrão é condensação **extractive-offline**, com trechos identificados por origem e ID, sem chamar modelo. Não se declara compreensão semântica completa do texto resumido. O provider recebe uma mensagem de dados de usuário com origem, source digest, summary digest e through_seq; o resumo não se torna mensagem de sistema com novas instruções. Original continua recuperável pelo MEMORY/transcript.

`ConversationStore.context_window(ident, system_prompt=..., condenser=..., summarizer=...)` lê originais protegidos e grava revisões de `ContextSummary` em tabela aditiva `context_summaries` no banco já existente. O payload do resumo também é protegido por OS. O fingerprint da política incorpora system prompt e limites; alterações de política não reutilizam um resumo de outra configuração. A revisão registra through_seq, digest da fonte encadeado, digest da revisão anterior, intervalo/contagem da fonte, origem e timestamp. Conflito de revisão concorrente é recusado. `messages` não é sobrescrita nem apagada.

`SentraAgent._history()` usa essa projeção e `_step_stream` a recarrega antes de **cada** chamada de modelo. Novos resultados de ferramentas vêm do transcript protegido, e não de uma lista recortada em memória. `agent.context_projection` expõe contagens, resumo e estimativa UTF-8/4; a estimativa não é billing nem tokenizer específico do modelo.

Para um resumo LLM real, o host chama:

```python
agent.configure_context_summarizer(
    provider="provider_real", model="modelo_real", complete=accounted_llm_callback,
)
```

`complete(SummaryRequest)` deve efetuar uma única submissão real e retornar `SummaryCompletion(text, usage)` com usage realmente reportado. O request fornece call_id, mensagens esquecidas, previous_summary, max_output_chars e source_digest. O callback não instala/configura outro modelo implicitamente. Condensação LLM exige turno ativo; a biblioteca exige `LedgerSummaryRunner`, sem aceitar callback arbitrário rotulado como contabilizado.

O wrapper chama `UsageLedger.require`, faz admissão proposta no mesmo budget existente, grava `provider_state(submitted)` no journal de calls existente, registra usage real/flush e comita a chamada auxiliar sem acrescentar resposta de resumo ao transcript. Token proposto é estimativa; token efetivo vem do provider. Sem relatório completo, as regras preexistentes de hard budget continuam bloqueando o que não podem verificar. Exceção/timeout permanece incerto e não tem fallback para segunda submissão. Nenhum novo ledger de custo ou operações foi criado.

Revisões LLM também guardam provider/model/call_id, vinculando sua origem à chamada e ao usage no ledger existente. Revisões offline deixam esses campos null; não se inventa submissão ou custo para um resumo extractivo.

## Canvas nativo no prompt da CLI

O prompt inclui `[[CANVAS|machine_list]]`, execução com objeto contendo work_item_id/machine_id/capability_id/arguments, e `[[CANVAS|machine_observe|operation_id]]`. Configurar máquina e preparar tarefa continuam com o owner em `/api/center/machine/configure` e `/api/center/task/prepare`; lista de máquinas não concede execução.

As respostas machine_execute/machine_observe continuam JSON e recebem `machine_operation_receipts` no início, preservando o objeto original. Essa posição conserva IDs antes de evidências longas sujeitas ao limite de visualização. UNCERTAIN acrescenta orientação de observar o **mesmo operation_id**, sem criar nova identidade ou repetir machine_execute. O journal de tool existente preserva o resultado integral. Não houve alteração de CanvasBridge ou host.

## Descoberta seletiva de ferramentas

`ToolDescriptor.from_mapping` recebe tool_id/capability_id/name/description/version/inputSchema. `AuthorizedToolCatalog(gate, authorize_tool=host_resource_pdp, embedding=None)` recebe o catálogo real do host por `replace(descriptors)`. Não cria ferramentas imaginárias nem busca pacotes na internet.

`discover(request, query=..., limit=8, semantic=False, semantic_weight=.35)` exige `tools:discover` e argumentos exatos `query`, `limit`, `semantic`, `semantic_weight`. O PDP por ferramenta retorna `PolicyDecision` com constraints já avaliadas pelo host; constraints restantes negam visibilidade. Filtragem precede ranking, cache e embeddings. Falta de PDP nega descoberta. A autorização é refeita após I/O de embeddings e mudança de geração interrompe o resultado.

Busca lexical usa nome/descrição e ponderação pela frequência no catálogo autorizado. Busca semântica só funciona com provider explícito `identity` (provider/model/revision) e `async embed(texts)`. Somente descrições autorizadas e a consulta chegam a esse provider. Vetores precisam ser finitos e dimensionalmente compatíveis; similaridade nunca concede permissão. O host deve aplicar suas próprias regras de dados/budget ao provider de embeddings.

`require_current(tool_id, fingerprint=...)` verifica somente freshness. Schema ou versão diferente invalida o resultado e requer rediscovery. Invocar a ferramenta continua exigindo a capability/pedido/grant correspondente no executor/gate existente. O retorno de discovery sempre indica `execution_authorization_required=True`.

`catalog.host_handler(operation)` pode ser registrado como `tools:discover` no host. Como o provider OpenHands, ele reconhece contexto físico já admitido para o pedido exato, sem nova reserva ou lock. Fora desse contexto usa o gate injetado normalmente.

Token metrics comparam o payload do catálogo autorizado com os descriptors retornados, incluindo fingerprints/scores. UTF-8/4 é uma estimativa identificada; não replica promessa percentual do ToolHive nem inventa economia medida pelo provider. Cache de vetores é separado por identity do embedding e fingerprint do descriptor; replace descarta entradas de descriptors removidos/alterados.

## Pré-requisitos e aceitação diferida

- SENTRA e Agent Server do clone exigem Python compatível; o clone declara Python >=3.12 e versões SDK/server 1.53.0. O server tem entry point `agent-server = openhands.agent_server.__main__:main`.
- Cliente HTTP requer `httpx` instalado separadamente; o SDK clonado declara `httpx[socks]>=0.28.1`. Não se alterou automaticamente requirements/lock nem se instalou dependência.
- Provisionar previamente Agent Server, um Agent Profile válido, seu LLM/credenciais/ferramentas, workspace remoto e persistência. O provider SENTRA não provisiona servidor, LLM ou sandbox.
- API key via canal protegido do host; TLS fora de loopback. Persistência de transcript/eventos/resumos exige DPAPI Windows ou keyring funcional; indisponibilidade falha sem fallback para texto aberto.
- Machine/WorkItem/grantee e capabilities da tabela devem ser preparados/concedidos pelo centro. Embeddings e callback LLM são opcionais e explícitos. Discovery lexical e contexto extractivo não exigem serviço externo.

Comandos reservados para a **validação integral final**, não executados agora:

```powershell
python -m pytest -q tests/unit/test_sentra_interop_openhands_provider.py tests/unit/test_sentra_interop_tool_catalog.py tests/unit/test_sentra_context_condensation.py
python -m pytest -q tests/unit/test_sentra_cli.py tests/unit/test_sentra_cli_model_effort.py tests/unit/test_sentra_interop_phase2_openhands.py tests/unit/test_sentra_interop_gate5.py
```

Os testes HTTP usam `httpx.MockTransport` identificado como fixture de protocolo, com ControlPlane/SQLite reais para admissão. Isso não comprova Agent Server externo operando. Os doubles de summary/embedding provam ordem de admissão/contabilização/visibilidade, sem afirmar LLM/embedding real. Testes da CLI/contexto usam transcript protegido real quando o backend OS está disponível. Todos permanecem **não executados nesta onda**.

Aceitação externa posterior: configurar provider autorizado; criar UUID explícito e filho; interromper conexão; reattach por GET; recuperar todas as páginas sem duplicar IDs; verificar um par action/observation; confirmar interrupt/pause por GET; verificar que 429 não repete mensagem; comparar summary callback real com usage/budget ledger e original protegido; renovar versão/schema e provar invalidação de descoberta. Não apagar conversas externas automaticamente como cleanup sem autorização.

## Integrações que permanecem pendentes

O main deve registrar callbacks/providers no host/Canvas e conceder capabilities específicas; esta frente fornece as interfaces consumíveis, sem editar esses módulos. As novas ferramentas descobertas precisam ser expostas pelo inventário autorizado real e invocadas pelo gate/executor existente. Callback LLM e embeddings reais precisam de configuração/budget próprios. Agent Server externo, seus tools e sandbox ainda requerem aceitação real. Live WebSocket (com handshake próprio do SDK), reprovision/fork, confirmação interativa de tools e lifecycle de credenciais não foram habilitados nesta onda; recuperação usa a API HTTP persistida efetiva. O objetivo integral dos 37 permanece ativo.
