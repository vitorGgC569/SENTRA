# Lume — interoperabilidade integral e canais

Data: 2026-10-11. Base de coordenação informada: `3639a2e296428db8e3bb0839fac87d9237ec8592`.

Implementação de domínio entregue na árvore compartilhada. **Não homologada.** Nenhum teste, build, lint, benchmark, execução de provider, instalação de SDK ou QA foi executado por Lume nesta rodada. A liberação da validação continua pertencendo ao Codex após integração de todas as frentes. Não houve recrutamento, commit, push, reset ou stash; arquivos dos demais donos foram preservados.

## Fontes e requisitos

Lidos o documento de implementação integral, contrato shell, nota Maestri `todos-os-projetos-ja-estao-clo` e os recortes completos pertinentes de auditoria37, reavaliação37, third-party reuse, Gate5, checkpoint09, CoS e pesquisa OpenDots. Consultados os contratos atuais dos clones ACP v1/v2, ACP Registry, A2A proto/spec/streaming, MCP TypeScript SDK, OpenHands Agent SDK/Agent Server e OpenHands cursor/health. A expansão CF16/FF13 foi recebida e incorporada por APIs oficiais Slack, Telegram e WhatsApp Cloud.

Requisitos cobertos por código novo/estendido:

- Factory ACP/A2A/MCP compatível com MachineHost, admissão e receipts centrais, sem Control Plane paralelo.
- ACP launch owned, hash de executável/argumentos/arquivos, ambiente explícito reservado, lifecycle negociado, config/model category/mode, updates parciais com diferença entre ausência/null, uso/custo desconhecido distinto de zero, projeções de planos/mensagens/terminais, cancelamento incerto, reattach sem replay e entrada humana durável.
- ACP Registry: catálogo/version/platform pinados, distribuição binary/npx/uvx, staging real, downloads HTTPS limitados, ZIP/TAR contidos, locks npm/Python, promoção imutável, bloqueio de downgrade e reconciliação do manifesto depois de interrupção.
- A2A: JSON-RPC PascalCase da revisão do clone, HTTPS/loopback explicitamente configurado, Agent Card aprovado por hash e interface, extended card, task/context mapping, send/continue/input-required, get/cancel, SSE/resubscribe, snapshots/artefatos incrementais, referência de arquivos sem download automático e push inbox autenticada.
- MCP: processo stdio owned/fenced, resources/prompts/tools com paginação/allowlists, schema fingerprints/invalidação, SDK TypeScript **real** como dependência/host original, revisão negociada/pinada, subscriptions legacy/modern, cancelamento sem reenvio, reverse elicitation e modern input_required sem auto-fulfilment.
- OpenHands: preservação do provider existente, arquivo de fontes antes de `/condense`, health persistido, tombstone de delete e ligação explícita tool-call → Operation central pelo resolver do host.
- Canais: assinatura/autenticação de webhook, allowlist de origem/sender/roteamento, inbox protegida, claim/ack para Pulso, outbox antes de efeito, provider ACK separado de recipient receipt, renovação Slack, vault rotation, revoke/delete e fallback explícito para ações que os providers não oferecem por API.

## Arquivos próprios

Novos:

- `sentra_interop/provider_machine.py`, `provider_store.py`, `acp_provider.py`, `interactions.py`.
- `sentra_interop/a2a_provider.py`, `a2a_push.py`.
- `sentra_interop/mcp_session.py`, `sdk/mcp_host.mjs`, `sdk/package.json`, `sdk/NOTICE.md`.
- `sentra_interop/registry_runtime.py`, `registry_machine.py`.
- `sentra_interop/channels.py`, `channel_machine.py`, `WHATSAPP_NOTICES.md`.
- `tests/unit/test_sentra_interop_integral_lume.py` (preparado, não executado).

Estendidos: `sentra_interop/acp.py`, `acp_session.py`, `a2a.py`, `mcp_stdio.py`, `central.py`, `openhands_provider.py`, `__init__.py`.

Não alterados por Lume: `workflow*`, `activepieces*`, core/runtime, Canvas/HTTP/MCP server, configuração raiz, arquivos de outros donos.

## Contrato MachineHost — Nexo

Exportações:

```python
from sentra_interop.provider_machine import InteropProviderMachine, INTEROP_CAPABILITIES
from sentra_interop.channel_machine import ChannelProviderMachine
from sentra_interop.registry_machine import RegistryProviderMachine

InteropProviderMachine(control, *, owner, agent_id, machine_id,
    workspace_root, kind, configuration)       # kind acp | a2a | mcp
ChannelProviderMachine(control, *, owner, agent_id, machine_id,
    workspace_root, configuration)             # kind channels
RegistryProviderMachine(control, *, owner, agent_id, machine_id,
    workspace_root, configuration)             # kind acp_registry
```

As três factories expõem `capabilities: tuple`, `actions: dict`, `policy`, `catalog()`, `dispatch_request(*,run_id,work_item_id,machine_id,capability_id,operation_id,arguments,idempotency_key=None)`, `async submit(*,run_id,request)` e `async shutdown()`.

`catalog()` é inventário/configuração, não concessão de grants; retorna `registered:true`, `grant_created:false`, `validation_status:pending`. A identidade vem do host. `dispatch_request` protege conteúdo pelo ProviderContentStore antes da submissão e substitui o conteúdo por hash no intent. `submit` usa CentralInteropAdapter e CentralEffectContext; não admite Run inativo, não promove operação incerta e não cria outra autoridade.

Nexo confirmou a composição inicial `configure_interop`/restore para ACP/A2A/MCP e solicitou os contratos para channels/acp_registry. Foram enviados via Maestri. O inventário deve usar `factory.catalog()` e os IDs Canvas do host. O kind continua necessário para restore.

**Namespaces para registro pelo Nexo em ControlStore:**

| Namespace | SQLite local |
|---|---|
| interop_projections | interop-projections.sqlite3 |
| interop_interactions | interop-interactions.sqlite3 |
| interop_installations | interop-installations.sqlite3 |
| interop_push | interop-push.sqlite3 |
| channels | channels.sqlite3 |

O namespace `provider_content` existente é reutilizado. Não existe fallback para ledger in-memory quando o backend não estiver configurado. DDL e projeções pertencem aos módulos do domínio; grants/Run/WorkItem/Operation continuam nos serviços centrais. A nova classificação de observação em `central.is_interop_observation` permite consulta de receipts/estado após efeito incerto sem repetir o efeito físico. Nexo também recebeu os conjuntos para `runtime.observations`.

### Configuração ACP

Campos: `enabled:true`, `provider_id`, `executable` absoluto, `executable_sha256`, `args:list`, `host_process_consent:true`, `supported_versions:[1]` ou `[1,2]`, `elicitation` opcional, `argument_file_pins:{absolute_path:sha256}` opcional e `environment:{values:{},secret_refs:{}}` opcional.

O consentimento de processo local é explícito e não é alegação de sandbox. O transporte encerra somente a árvore owned (Windows JobObject/POSIX sessão). Ambiente não herda PATH/tokens do usuário; variáveis reservadas do registry são recusadas. Secret refs são vinculadas à identidade/purpose no vault e conteúdo resolvido fica protegido por hash no intent.

| Capability | Argumentos públicos |
|---|---|
| acp:launch | local_id |
| acp:session / resume / load / close / delete / cancel / state / transport_close | local_id |
| acp:prompt | local_id, message |
| acp:config | local_id, config_id, value |
| acp:mode | local_id, mode_id |
| acp:list | local_id, cursor opcional |
| acp:events | local_id, after=-1, limit=100 |

`session/new` não é fallback de resume. `transport_close` fecha a posse local sem apagar sessão remota; novo launch e resume exigem novas operações. `events`/`state` podem ler a associação persistida após restart sem lançar processo. A revisão2 fica opt-in. Terminal emitido pela revisão2 é uma projeção display-only; não se transforma em terminal de execução SENTRA. Requests de fs/terminal/sampling não suportados continuam recusados, em vez de ativar um executor privilegiado por conteúdo remoto.

### Configuração MCP

Mesmos pins/consentimento/environment de processo; `transport:stdio|sdk_http`, `protocol_version:2025-06-18|2025-11-25|2026-07-28`, allowlists `tools`, `resources`, `prompts`, `resource_templates`. SDK HTTP requer endpoint aprovado e `args:[absolute_path_to_sentra_interop/sdk/mcp_host.mjs]`, executável Node pinado e dependência oficial provisionada separadamente. O hash do host JavaScript é incluído no intent antes do spawn.

| Capability | Argumentos públicos |
|---|---|
| mcp:launch / connect / close / unlisten | nenhum |
| mcp:list / resources_list / templates_list / prompts_list | cursor opcional |
| mcp:resource_read / subscribe / unsubscribe | uri |
| mcp:prompt_read | name, arguments={} |
| mcp:listen | filter (notification types/allowlisted resourceSubscriptions) |
| mcp:notifications | limit=100 |
| mcp:tool:<name> | arguments, schema_sha256; continuação opcional input_operation_id, input_responses |

Cada nome de tool possui capability distinta. Descoberta só retorna tools já autorizadas no WorkItem; um schema antigo não chama uma tool nova. `input_required` retorna `interaction_ids`/`input_requests`. O proprietário responde pelo serviço de entrada humana, e a continuação só consome respostas correspondentes e ainda válidas, em nova Operation, uma vez. requestState permanece protegido/opaque; o SDK não cumpre/reenvia automaticamente. Modern usa `server/discover`/`subscriptions/listen`; legacy mantém initialize/subscribe. Cada fetch do SDK pede `sentra/checkpoint` ao efeito central original. Sampling/roots não são expostos.

Modern pode reconstruir sessão pela identidade e DiscoverResult persistidos; legacy conserva o cliente vivo e rejeita substituição de uma sessão remota após restart do processo SDK quando não há reconstrução segura. Isso aparece como erro explícito de reconciliação, nunca session replacement ou tool replay.

### Configuração A2A

Campos: `enabled`, `provider_id`, `endpoint` HTTPS/loopback, `trust_domain`, `card_sha256` aprovado fora do catálogo, `card_url` opcional na mesma origem, `tenant` opcional, `secret_ref` opcional, `callback_url` e `callback_secret_ref` opcionais. Interface Agent Card precisa anunciar o endpoint JSONRPC selecionado; card não escolhe outro destino nem cria capability.

| Capability | Argumentos públicos |
|---|---|
| a2a:discover / extended_card | nenhum |
| a2a:send / continue | local_id, message |
| a2a:get / cancel | local_id |
| a2a:subscribe | local_id, limit=100 |
| a2a:events | local_id, after=-1, limit=100 |
| a2a:artifact | local_id, artifact_id |
| a2a:push_set / push_delete | local_id, config_id |
| a2a:callback | local_id, event_id da inbox autenticada |

IDs message/task/context vêm do host/peer pinado e ficam associados ao WorkItem. Cancel só retorna CANCELLED quando o peer confirma. Artefatos têm chunks idempotentes, flags append/final, limite protegido e SHA256. Se o peer não oferece identidade de replay para append, subscribe recupera o Task completo com GetTask, sem tentar adivinhar a quantidade de chunks idênticos. URL de artifact é descriptor inerte; não existe fetch arbitrário de URI.

`factory.receive_callback(*,raw_body:bytes,headers:dict)` autentica Bearer do callback_secret_ref, confere task/context em uma associação única e grava inbox protegida; retorna `{ok,event_id,project_id,workspace_id,local_id,duplicate,effect_dispatched:false}`. Codex recebeu sugestão `POST /api/interop/webhook/<machine_id>` com body raw limitado. Nexo recebeu a solicitação de fachada no MachineHost. Consumo posterior usa `a2a:callback` em Operation autorizada; ingestão HTTP nunca faz task admission ou dispatch.

### Registry

Configuração: `enabled:true`, `provider_id`, `catalog` index bruto, `schema_version`, `pinned_versions`, `channels` opcional e `installations:{agent_id:installation_config}`. `catalog` só contém seleção pinada.

Capabilities `acp:catalog`, `acp:plan`, `acp:install`, `acp:installed`. Catalog aceita offset/limit; demais ações só `agent_id` e usam distribuição/configuração do host, sem URL/runner/path enviados pelo renderer.

Installation config requer `system`, `architecture`, `kind`, `executable_sha256` independente. Binary requer `archive_sha256` independente. npx requer `lock_text` lockfileVersion3 com root dependency exata/integrity e runner `{executable,sha256,npm_cli,npm_cli_sha256}`, com `entrypoint` relativo. uvx requer `lock_text` de requirements hash-locked, runner `{executable:uv_absolute,sha256}`, `entrypoint`. Não há shell, npx.cmd implícito, hooks npm, upgrade automático ou execução de agente durante install. O ambiente do descriptor não é adotado automaticamente no launch.

Instalações ficam sob `control.durable.root/interop-installed/<machine>/<agent>/<version>`. Falha conserva staging para diagnóstico e a versão boa. Promoção não substitui diretório existente. `acp:installed` reconcilia manifesto/pins/inventário/link targets e reconstitui metadado depois de crash após rename, sem relançar instalador.

### OpenHands

Preservado `OpenHandsMachine` do Nexo. Dependências enviadas: incluir `config_sha256=self.config.fingerprint` no intent create; normalizar eventos `page_id=None,limit=100`; registrar capacidades novas `openhands:condense {local_id}`, `openhands:health {}`, `openhands:tool_link {local_id,tool_call_id,operation_id}`, `openhands:delete {local_id}`.

`OpenHandsAgentServerProvider(...,operation_resolver=callback)` aceita resolver central do Nexo: `(request,operation_id)->{operation_id,work_item_id,intent_sha256}`. Referências precisam pertencer ao mesmo WorkItem; a ligação não afirma que ação remota foi verificada pelo SENTRA. Health não dispara probes. Condense arquiva o histórico antes da chamada real ao servidor e não cobra um modelo adicional; a transcrição original permanece protegida, e o resultado ainda exige recuperar/verificar o evento de condensação. Delete conserva tombstone do mapping.

## Entrada humana — Codex/Prisma

`ProtocolInteractionService(control,*,owner)`:

- `pending(*,workspace_id,limit=100)` → interactions com ID, Operation, método, pergunta/schema, expiry e `grants_created:false`.
- `reply(*,workspace_id,interaction_id,answer,request_key)` → answered/deduplicated; exige WorkItem ativo, workspace exato, schema e resposta permitida; consumo posterior uma vez.

Compor somente com bearer owner já existente, sem publicar segredo ao renderer. Form recebe `{action:accept|decline|cancel,content?}`. Permission ACP só permite options anunciadas one-shot (`allow_once`/`reject_once`) ou cancel, sem `allow_always`. Resposta humana não cria Grant, não muda ChatTrust e não executa filesystem/terminal do host. RPC reader é desacoplado do contexto de launch expirado; reverse requests só emprestam a única Operation ativa correta.

## Canais — Codex/Pulso/Nexo

```python
ChannelService(control, *, owner)
configure(*, connector_id, configuration, expected_revision=0)
receive(*, connector_id, raw_body: bytes, headers: dict)
challenge(connector_id, query)  # WhatsApp GET handshake, sem efeito
list_connectors(*, project_id, limit=100)
owner_receipt(*, connector_id, project_id, operation_id)
pending_inbound(*, connector_id, project_id, limit=100)
claim(*, connector_id, event_id, consumer_id, expected_revision, lease_seconds=60)
ack(*, claim_id, work_item_id, operation_id, receipt_id=None)
```

Configuração comum: `kind:slack|telegram|whatsapp_cloud`, `enabled:true`, `project_id` Canvas, `agent_id` CP, `scopes:list`, `routes:[{external_workspace,external_conversation,sender_ids,conversation_id,space_id?}]`. Owner/project/Space/conversa/agente devem ser conferidos pelo Canvas ao configure; renderer nunca define principal/Grant.

- Slack: `team_id`, `token_ref`, `signing_secret_ref`; scope `chat:write`; refresh opcional `client_id`, `client_secret_ref`, `refresh_token_ref`. HMAC v0 sobre body raw/timestamp ±5min, team/channel/sender allowlisted, event_id durável.
- Telegram: `bot_id`, `token_ref`, `webhook_secret_ref`, `webhook_url` HTTPS opcional; scope local `bot.send`. Header secret_token, update_id/idade/mapeamento chat/sender, setWebhook/deleteWebhook reais.
- WhatsApp Cloud: `business_id`, `phone_number_id`, `api_version` pin explícito, `token_ref`, `app_secret_ref`, `verify_token_ref`; scope `whatsapp_business_messaging`. HMAC SHA256 raw, challenge, business/phone/sender allowlisted, message IDs, statuses de delivery/read autenticados.

`configure` retorna `{connector_id,project_id,workspace_id:project_id,kind,revision,enabled,grant_created:false,chat_trust_inherited:false}`. `receive` retorna ACK depois da inbox persistida, `{ok,connector_id,project_id,workspace_id,accepted:[{event_id,project_id,workspace_id,conversation_id,space_id,duplicate}],receipts_recorded,effect_dispatched:false}`. Slack challenge retorna `{challenge}`.

Codex aceitou composição ingress-only `POST /api/channels/webhook/<connector_id>` (raw ≤1MiB, sem bearer owner no callback, assinatura do provider obrigatória) e handshake GET WhatsApp. Config/list/receipts/entrada humana continuam sob autenticação owner no mesmo serviço.

`pending_inbound` fornece texto protegido já autenticado/roteado para Pulso, sem grant ou tarefa implícita. `claim` devolve chave `channel:<connector_id>:<event_id>` para admissão central pelo workflow. Claim expirado não é reatribuído automaticamente; efeito incerto exige reconciliação. `ack` confere Operation/Run/WorkItem/projeto centrais e só marca ACKNOWLEDGED se Operation SUCCEEDED. Pulso recebeu o contrato e iniciou integração.

`ChannelProviderMachine` usa configuração `{connector_id}` de um canal já registrado para o agente. Capabilities: channel:send `{recipient,message}`, channel:receipt `{operation_id}`, channel:inbox `{limit?}` e lifecycle sem parâmetros: renew/revoke/delete/webhook_set/webhook_delete. O destino vem da allowlist, conteúdo cifrado/hash e outbox antes HTTP. WA opaque callback data liga status ao Operation mesmo quando o ACK HTTP se perde; statuses que chegam antes do ACK são preservados. Slack/Tg não têm leitura/delivery receipt universal; resposta allowlisted ao message/thread gera prova `recipient_replied`, e a limitação aparece explicitamente. Provider_accepted não é delivery/completion.

Slack refresh/revoke têm chamadas reais; Telegram token renewal/revoke e configuração Slack/WhatsApp por console seguem fallback explícito para vault rotation/console do proprietário. Revogação local impede novos ingress/sends; delete remove conteúdo e mantém tombstones/recibos para no-repeat. **Nenhum canal herda ChatTrust.**

## Pendências reais e limites

1. Confirmação pelo Nexo do registro de todos os namespaces/factories/fachada callback e addons OpenHands; Lume enviou as dependências e não alterou arquivos alheios.
2. Confirmação da composição final HTTP/shell pelo Codex e painéis/forms/recibos pelo Prisma; assinatura real entregue antes da integração.
3. Provisionamento externo após liberação: agente ACP pinado; peer A2A/Card/token; Agent Server OpenHands; SDK TS 2.3.1/Node e dependências; npm/uv/locks/binary archives; credenciais/scopes e endpoint HTTPS público para canais. Ausência resulta em erro explícito, sem fixture simular provider pronto.
4. Modern MCP restart tem mapeamento/discovery persistido; legacy SDK restart não substitui sessão e pode exigir reconciliação do provider. FS/terminal privileged host requests ACP permanecem indisponíveis no cliente padrão; terminais agent-owned são display-only e execução local depende do domínio executor/Pulso, sem autorização remota implícita.
5. WhatsApp desta entrega é Cloud API oficial. O clone Invisible Dots não está disponível localmente e nenhum libsignal foi importado; a variante QR/libsignal não foi implementada como substituto oculto. Notice separado registra GPL3 se essa dependência vier a ser incorporada. Meridiano foi avisado para registrar variante/limite na matriz, sem tratar Cloud API como prova de QR.
6. O processo local owned não prova sandbox de SO; TOCTOU/supply chain/egress precisam do gate final e dos provedores de isolamento de Forja. Pins, argv, ambiente e fonte do SDK são rechecados na fronteira, sem alegar isolamento inexistente.
7. Backend PostgreSQL pertence ao Nexo; estes módulos usam `control.store` e SQL transacional, precisam da adaptação dos dialects já exigida pelo core. Não foi executada migração ou comparação de backends nesta rodada.

## Validação futura (somente após liberação do Codex)

- Executar o arquivo preparado `tests/unit/test_sentra_interop_integral_lume.py`: chunks/CAS/dedup/restart/scope/gap, Slack assinatura/replay/sender e claims.
- Suites existentes de ACP lifecycle/launch/registry/central gates/OpenHands/A2A/MCP e regressões de MachineHost/Canvas/shell.
- Contrato real com 2 agentes ACP, consentimento/refusal, revisão2/partial null/terminal bytes/custos desconhecidos, cancel/restart/reattach sem replay e processo/netos owned.
- TS SDK oficial provisionado: revisão legacy/modern, subscriptions, elicitation/input_required/answer consume, schema drift, revogação antes de cada fetch, resumption e sem auto resend.
- Peer A2A real: Card/TLS/tenant, continuidade/input-required, artifact/SSE duplicado/sem event_id, callback da identidade errada, perda de ACK/receipts, cancel e restore.
- Registry: binário e pacote npm/Python reais autorizados, hooks negados, downgrade/plataforma/env, staging falho, links/traversal, crash entre rename e metadados, launch separadamente admitido.
- OpenHands real: condensação preserva instruções/transcrição/pendências, event recovery fora de ordem, tool→Operation, health/cancel/delete/restart.
- Canais reais: signup/scopes/webhook/refresh/revoke/delete, dois senders e projetos, replay, ACK perdido/status antecipado, callbacks após revoke, claim/Operation uncertain e receipt do destinatário separado de ACK.

Esta lista é plano de execução, não evidência de aprovação. A implementação não foi declarada homologada por leitura de arquivos.
