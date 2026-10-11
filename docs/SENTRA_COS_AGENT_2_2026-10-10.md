# SENTRA OS — CHAT 2/3: prova e bloqueios reais (2026-10-10)

## Mandato / fronteira
Escopo: G02, G12, A01–A05, A09, G08, G11, A08, A10; propriedade
`edge_extension/`, `browser/`, `sentra_mcp/services/chat_access.py`,
`browser_evidence.py`, novas superfícies `action_consent_*`/`web_account_*`/
`code_mode_*` e testes próprios. Não houve alteração em `control_plane.py`,
`sentra_mcp/server.py`, `native_bridge/`, Canvas/CLI, instalador ou CI.
Não houve reset, checkout, stash, commit/push nem leitura de cookie/segredo.

## Código real modificado
1. `sentra_mcp/services/chat_access.py`: tabela `browser_request_messages`
   persistida no MESMO namespace SQLite autoritativo `chat_access`, com
   unicidade por (principal,request_id) e (principal,message_id). Para requests
   vindos do browser, `require_allowed` confere que o coletor segue habilitado,
   revisão de registro não mudou e a identidade `extension_id + worker +
   document_id + conversation_id` corresponde ao documento corrente.
   `require_exact_message(principal, request_id, message_id)` exige também o
   vínculo observado `message.metadata.request_id -> message.id`, além da
   política normal de confiança/bloqueio.
2. `sentra_mcp/services/browser_evidence.py`: na mesma transação
   `BEGIN IMMEDIATE`, grava request/message e respectivos
   extension/tab/document/revisão. Divergência de conversa ou mensagem,
   incluindo reutilização de um message ID por outro request, insere
   `browser_request_conflicts` persistente e QUARENTENA ambos os
   request IDs, sem substituir a propriedade original. Nonce replay continua
   impossível com conteúdo alterado. A observação não cria grants.
3. `sentra_mcp/services/action_consent_gate.py` **novo**: API host-only
   `ActionConsentService` com primeiro consentimento humano versionado
   `allow_api`, proposta limitada a 16KiB/fingerprint SHA-256,
   segundo consentimento `approve_action` para corpo específico,
   expiração e consumo atômico sem reenvio.
   `execute` usa `CentralInteropAdapter.protocol_gate()`,
   `OperationRequest`, `Machine/Capability` reais, decisão do grant
   **api:action:<nome>** no WorkItem central e `gate.execute`
   (durable Operation, fencing, lock) antes de chamar callback host confiável.
   A proposta sozinha e a aprovação humana NÃO criam grants.
   A validação de consentimento ocorre no preflight e novamente dentro
   do ponto de efeito. Replay exato de uma Operation segue o ledger central;
   aprovação consumida não é reciclada para nova Operation.
4. `tests/unit/test_sentra_cos_chat2_action_and_message.py` **novo**:
   fixture Web hermética, duas abas, documento novo, revogação de coletor,
   divergência de request/message, consentimentos separados, corrupção de
   body, falta/revogação de grant, aprovação pendente, CAS de consentimento,
   Operation real no SQLite e proteção contra replay.

## Evidência executada nesta sessão
Comando, em `C:\Users\vitor\OneDrive\Desktop\SENTRA`:

```powershell
python -B -m pytest tests/unit/test_sentra_cos_chat2_action_and_message.py tests/unit/test_sentra_cos_browser_evidence.py tests/unit/test_sentra_cos_chat_access_and_connector_proof.py -q --tb=short
git diff --check -- sentra_mcp/services/chat_access.py sentra_mcp/services/browser_evidence.py tests/unit/test_sentra_cos_chat2_action_and_message.py
```

Resultado terminal: **20 passed in 4.73s** e `git diff --check`
sem saída/erro. O teste de fluxo positivo verificou
`DurableRunService.operation_status(...).state == SUCCEEDED`,
`progress.work_item_id == WI-api-consent`, segundo uso `duplicate`
sem novo callback, ausência de Operation sem grant, negação após revogação.
O ambiente é Windows real com SQLite, mas o navegador e a autorização humana
dos testes são fixtures herméticas: **não é E2E externo ChatGPT**.

## Handoff obrigatório ao coordenador (arquivos centrais reservados)
- Instanciar `ActionConsentService(state_root, store=<ControlPlaneStore>)`
  **no backend host**, compartilhando o storage autoritativo. Se exposto via
  Canvas/CLI, `allow_api(...,human_confirmed=True,expected_revision=N)`
  e `approve_action(...,human_confirmed=True,body_sha256=<hash>)`
  só podem ser chamados após autenticar OPERADOR LOCAL em sessão interativa.
  Nunca expor os dois métodos no MCP, bot, web page/content-script ou
  agentes; o booleano por si só NÃO autentica um humano. Aplicar
  CSRF/origin/bearer no endpoint e revisão CAS no UI, sem auto-consent.
- `propose_action(owner,agent_id,work_item_id,request_id,message_id,
  action,body,ttl_s=120)`: devolver digest para revisão visual segura.
  A identidade `request_id,message_id` deve vir do broker autenticado
  (request MCP e metadata Web), **nunca apenas de campo enviado pelo modelo**.
- `await ActionConsentService.execute(control=<ControlPlaneService>,
  owner=...,run_id=...,work_item_id=...,agent_id=...,request_id=...,
  message_id=...,action_id=...,action=...,body=...,operation_id=...,
  idempotency_key=...,host_effect=<host-selected coroutine>)`:
  chamar apenas para uma implementação de API permitida pelo HOST,
  never executar código arbitrário ou URL enviada por chat.
  Requer grant `api:action:<nome>` para `agent_id` no escopo
  `work_item` real, e Run/WorkItem ativo. A resposta é um
  `OperationResult`, cuja `operation.state` deve ser checada; estado
  FAILED/UNCERTAIN nunca pode virar reenvio automático.
- No broker `ToolPolicyProxy` e relay, inserir 
  `chat_access.require_exact_message(principal, request_id, message_id)`
  onde houver mensagem externa confirmada. A verificação atual
  `require_allowed(principal,request_id)` permanece compatível com
  fontes legadas não vinculadas a browser, mas é INSUFICIENTE para
  uma ação nova de alto impacto.
- Eventos de navegação/account switch/logout exigem que o worker
  publique novo documento ou invalidação autenticada. A nova regra
  invalida requests antigos quando muda `document_id` ou a revisão do
  coletor, porém não prova automaticamente qual conta ChatGPT está ativa.

## Bloqueios e verificações honestas
- **G02/G12/A01–A05/A09**: não foi possível validar conta real,
  perfil Edge, plano, lista de modelos, effort/Automatic nem correlação
  nativa Web em TODOS os renderers ChatGPT. A observação React atual
  cobre somente branches primitivas identificadas e uma extensão
  explicitamente cadastrada; não é atestado criptográfico de conta.
  A falta de prova deve retornar `unverified` para superfícies novas
  e jamais supor quota ou autorização premium.
- **G08/G11**: gate de autorização e dois consentimentos implementado e
  testado sob WorkItem/SQLite, mas ainda sem rotas API host read/action
  integradas ao Canvas/CLI (reservados). A autenticação efetiva do
  operador humano nesses endpoints é indispensável.
- **A08/A10 Code Mode**: QuickJS WASM restrito não está instalado/provado
  no ambiente examinado; não se fez download, execução de scripts upstream,
  shell arbitrário nem fallback inseguro para Node/eval. Falta distribuir
  artefato WASM auditado e pinado, sandbox com CPU/memória/fuel e bridge
  host-only que despache cada tool a `ActionConsentService.execute`
  e à Operation/Grant individual. Sem isso Code Mode deve permanecer
  DESABILITADO, não simular compatibilidade.
- Sem prova de publicação no ChatGPT, schemas remotos, duas contas reais,
  troca de conta sem reload, E2E do navegador, CI verde final,
  instalação limpa, assinatura ou homologação 34/34.

**Status: fatia CHAT 2 implementada e 20 testes focados verdes;
integração host/UI, contas externas e Code Mode completos pendentes.**

---

## RODADA 2 — execução adicional (10/10/2026)

### Implementações verificadas, escopo CHAT 2

1. **`browser_evidence.py`**: novo ledger durável
   `browser_revoked_documents(extension_id,worker,document_id,reason,revoked)`
   no **mesmo SQLite `chat_access`**, sem store paralelo. `challenge` para
   novo documento revoga o anterior ANTES do scan React (mesmo se o scan falhar).
   `observe`/novo `challenge` recusam documento revogado sem ressuscitar
   request antiga. Método host-only `invalidate_document(extension_id,
   source_sha256,worker,document_id,reason)` transacional:
   `tab_closed|navigation|signed_out|account_changed|profile_changed|
   identity_unknown`. Limpa challenges, invalida a associação à conversa e
   reavalia gate por aba. Para logout/troca de conta/perfil, estado global
   desconhecido bloqueia novas operações; para fechamento/navegação simples,
   outra aba observada e saudável pode continuar. Notificação atrasada de
   documento anterior não invalida novo documento. Persistência confirmada
   após instanciar outro BrowserEvidenceService no mesmo disco.
   `requests` com dois request IDs para mesmo `message_id` agora são
   recusadas antes de INSERT (não há `INSERT OR IGNORE` parcial silencioso).
2. **`chat_access.py`**: `require_exact_message(...,_db=None)` usa
   `BEGIN IMMEDIATE` quando chamada isoladamente; `require_allowed(...,
   _db=None)` permite checagem na mesma transação SQLite do consumo de
   consentimento. Sem janela separada entre verificar trust/documento e ler
   join de mensagem. `ActionConsentService._claim` usa sua conexão de
   `BEGIN IMMEDIATE` para exigir exact message e consumir o ticket de
   aprovação de uso único.
3. **`web_account_dispatch.py`** (novo): `AuthenticatedWebLink` imutável
   (principal, request_id, message_id, extension_id, worker, document_id);
   `WebMCPMessageDispatchGuard(...,authenticated_link=<host_cb>,
   verified_account=<host_cb>)` oferece `tool_observer(ctx,name)` para
   `ToolPolicyProxy(request_observer=...)`. Compara identidade REAL do
   contexto MCP, `x-request-id`, binding autenticado do broker, o join
   `message.metadata.request_id`/message, extension/tab/doc no banco,
   gate de aprovação humana e status idle recente. Tudo verificado antes
   de executar o corpo da tool. O callback `verified_account` é
   obrigatório na prática: quando ausente ou não retorna exatamente
   `True`, NEGA ("account identity unverified"). **Nenhuma conta externa
   foi atestada nesta rodada.** Callback de conta válido deve ser criado
   exclusivamente pela integração HOST a partir de prova independente,
   vinculada à aba/perfil/epoch. Não derivar booleano de DOM, da extensão
   cadastrada, de header da chamada nem de parâmetro do modelo.
4. **`action_consent_gate.py`**: `read_api(control,owner,run_id,
   work_item_id,agent_id,request_id,message_id,resource,body,operation_id,
   idempotency_key,host_read)`, read-only host-selected, primeiro consentimento
   humano revogável e grant independente `api:read:<resource>`, usando
   `CentralInteropAdapter.protocol_gate()`, Operation central, idempotência,
   revalidação junto do efeito. A API de ação continua com primeiro
   consentimento + revisão do SHA-256 na aprovação humana individual
   + grant separado `api:action:<nome>`. Grant action NÃO autoriza read,
   e grant read NÃO autoriza action. Não registrar host_read/host_effect
   arbitrário vindo do browser ou da mensagem do agente.
5. **`edge_extension/conversation-evidence.js`**: leitor MAIN-world
   agora recusa tanto um request atribuído a duas mensagens diferentes
   quanto uma mensagem atribuída a dois requests, ao invés de sobrescrever
   um `Map`. Não lê cookies, sessões, token, texto de mensagem nem
   valores de tools. Shape desconhecido retorna `null`, não identidade.
   **`edge_extension/manifest.json`** recebeu
   `stamp_extension_identity` oficial: hash
   `5206d79f9916dee9030cd94c592aa1a33a543daa127404b9f216847360085b97`.
   Recalcular novamente no build se outros agentes mudarem os 7 arquivos
   cobertos pelo manifesto.

### Testes novos / evidências da Rodada 2

- `tests/unit/test_sentra_cos_chat2_dispatch_round2.py`:
  documento novo revoga anterior mesmo sem scan, SQLite após restart,
  logout/fechamento/stale event, duas abas, header MCP adulterado,
  mensagem trocada, extensão/documento divergentes, approval pendente,
  gate no `ToolPolicyProxy` de verdade. Atestado de conta positivo é
  explicitamente fixture local; sem ele o dispatch NEGA.
- `tests/unit/test_sentra_cos_chat2_action_and_message.py`:
  caso adicional `read_api` prova primeiro consentimento, falta de grant,
  grant action independente, leitura real da fixture via Operation
  `SUCCEEDED`, replay `duplicate` sem segundo callback, revogação.
- `tests/unit/sentra_cos_evidence_round2.cjs` +
  `tests/unit/test_sentra_cos_chat2_evidence_js.py`:
  executam o JavaScript REAL do leitor React MAIN contra grafo React/DOM
  hermético com Node **apenas como test runner**; duplicação/mismatch
  retorna `null`. Não é QuickJS/Code Mode.

Rodada dirigida (depois da correção do manifesto):

```powershell
python -B -m pytest tests/unit/test_sentra_cos_chat2_evidence_js.py tests/unit/test_sentra_cos_chat2_dispatch_round2.py tests/unit/test_sentra_cos_chat2_action_and_message.py tests/unit/test_sentra_cos_browser_evidence.py tests/unit/test_sentra_cos_chat_access_and_connector_proof.py tests/unit/test_extension_versions.py tests/unit/test_extension_protocol.py -q --tb=short -p no:cacheprovider
```

**61 passed, 0 failed, 9.16 s**. `git diff --check` nos arquivos
rastreados relevantes exit 0; aviso CRLF→LF do manifesto apenas.
`py_compile` das quatro classes alteradas e `node --check` do leitor
JS passaram em teste anterior. Sem regressão integral de todos os módulos,
E2E ChatGPT, nem prova de segunda conta ou conta atual.

### Contrato exato e PATCH DE HANDOFF à coordenação (NÃO aplicado)

A) **Chat 3/relay reservado** `native_bridge/relay.py`,
em `Handler.do_POST` logo após `/browser-evidence/observe`;
reutilizar `_authorized()`, `_browser_collector(data)`, CORS/origin
`chrome-extension://` e digest do build oficial:
```python
if self.path == "/browser-evidence/invalidate":
    if set(data) != {"source_sha256","worker","document_id","reason"}:
        raise ValueError("exact browser invalidation schema required")
    collector = self._browser_collector(data)
    return self._send(state.browser_evidence.invalidate_document(
        **collector, document_id=data["document_id"], reason=data["reason"]))
```
Não permitir endpoint model/MCP exposto. Em `edge_extension/service-worker.js`
(CHAT 2) ligar produtor apenas DEPOIS de haver rota: em
`chrome.tabs.onRemoved`, eventos de navegação/URL, logout/perfil/conta
confirmado e perda de prova, emitir invalidation DENY-ONLY com
`source_sha256:OMA_SOURCE_HASH`, `worker:'TAB-'+tabId`, `document_id`
do último scan autenticado e razão da allowlist acima. Persistir
identidade mínima por profile local para sobreviver à suspensão MV3,
mas nunca cookie/token. Não considerar um HTTP 404 como revogação efetiva;
com erro de rede, bloquear a operação, não criar grant nem reenviar submit.
A rota e esse produtor ainda **NÃO estão integrados**, porque
`native_bridge/` pertence ao CHAT 3.

B) **Fachadas reservadas** `sentra_mcp/server.py`/
`sentra_mcp/tool_policy.py`:
- Após autenticar owner, extensão, build, profile/tab e vínculo real da
  requisição MCP pelo broker, guardar em contexto HOST privado
  `AuthenticatedWebLink(principal,request_id,message_id,extension_id,
  worker,document_id)`. `authenticated_link(ctx)` deve consultar
  SOMENTE essa associação criada pelo servidor, jamais argumentos MCP,
  `x-web-message-id` ou fragmento de URL.
- `verified_account(ctx,link,conversation_id)` precisa devolver
  `True` somente diante de identidade de conta ChatGPT verificada de
  forma independente, perfil correto, epoch atual e ausência de logout.
  Como não há essa prova hoje, **retornar False** e manter ferramentas
  externas BLOQUEADAS. Não inferir modelo, effort ou Automatic de rótulos.
- Construir:
```python
guard = WebMCPMessageDispatchGuard(
    chat_access=chat_access, browser_evidence=browser_evidence,
    authenticated_link=host_authenticated_link,
    verified_account=host_verified_account)
```
- Usar `request_observer=guard.tool_observer` no `ToolPolicyProxy`.
  Se já houver observador de métricas/proveniência, encadear:
```python
def joined_observer(ctx, name):
    guard.tool_observer(ctx, name)  # primeiro: falha impede efeito
    previous_observer(ctx, name)
```
  Não substituir sem preservar o anterior. Antes de cada efeito
  `Operation/Grant`, revalidar a mesma identidade; não tratar o retorno
  da prova do browser como grant. O teste
  `test_mcp_tool_wrapper_exact_join_precedes_real_tool_body_and_approval`
  fornece integração hermética com o wrapper real.

C) **Canvas owner-auth somente**, sem edição de `sentra_canvas/`:
expor leitura `read_api` via grant `api:read:<resource>` e confirmação
inicial revisável no host, ação via proposta SHA-256/consentimento
`approve_action` separado e grant `api:action:<nome>`. Sessão local
interativa devidamente autenticada, anti-CSRF/origin, revalidação de
ticket e revisão; jamais repassar `human_confirmed=True` direto de
campo MCP/modelo ou aceitar callable/endpoint/arquivo arbitrário.
Os dois métodos de consentimento humano não devem aparecer no catálogo
MCP. Os métodos do service já executam contra Run/WorkItem/Operation/grant
reais, mas **as rotas de Canvas ainda não existem** nesta frente.

### Bloqueios preservados e próximos testes de aceitação

- Conta ChatGPT real (incluindo troca **sem reload** do mesmo documento),
  perfil de Edge, identidade estável, plano, modelos disponíveis, effort,
  Automatic e quota **não comprovados**. Documento/URL/chat não provam
  conta e `account_identity` retorna apenas afirmação verificada pelo
  HOST, inexistente na produção atual. O guard falha fechado.
- Leitor de `message.metadata.request_id` é restrito a ramos React
  committed com IDs primitivos; versão desconhecida do Web DOM não pode
  estabelecer identidade. Não foi feita inspeção de cookies/segredos.
- Dispatch contra uma conta ChatGPT real, associação request MCP em
  chamada remota de verdade, extensão própria SENTRA instalada,
  receiver de invalidation, API Canvas humana e UI revisável dependem
  de coordenação e E2E. Não há segurança confirmada em troca de conta
  de mesmo documento sem um sinal externo autenticado.
- Não há QuickJS WASM pinado/auditado distribuído nem sandbox de
  memória/fuel/time/host IO comprovado. **Code Mode segue DESABILITADO**;
  Node VM usado para TESTE do leitor não é fallback de execução do produto.
  Não executar scripts upstream nem baixar artefatos sem validação da supply chain.
- Sem alteração em `native_bridge/`, `control_plane.py`,
  `sentra_mcp/server.py`, Canvas, instalador, CI; sem reset, stash,
  commit ou push global. **Nenhuma afirmação de homologação 34/34**.

---

## RODADA 3 — produtor MV3 de invalidação deny-only (10/10/2026)

### Alterações reais, somente escopo Chat 2

**`edge_extension/service-worker.js`:**
- Novo bloco isolável `SENTRA_IDENTITY_REVOCATION_BEGIN/END` no
  MV3 *de produção*: `omaIdPrepare`, `omaIdInvalidate`,
  `omaIdFlushInvalidations`, `omaIdOnTabUpdated`,
  `omaIdInvalidateAll` e `omaIdReconcileTabs`.
- Persistência mínima em `chrome.storage.local`, por worker/aba:
  `sentra_id_doc_<tabId>` contém somente `worker`, `document_id`,
  `identity_epoch` aleatório, `profile_epoch` aleatório persistido
  no perfil, `route` `/c/` reduzida a ID, `source_sha256` do build e
  `observed` (bool). Não armazena URL completa/query, texto da
  conversa, login, token, email, cookie ou argumento de tool.
  `profile_epoch` distingue instalação/perfil local **sem**
  alegação de identificação real da conta ChatGPT.
- `sentra_id_revoke_<tabId>` retém evento deny-only antes de remover a
  identidade local. Exato JSON de rede: `{source_sha256,worker,
  document_id,identity_epoch,reason}`. Razões restritas a
  `tab_closed`, `navigation`, `signed_out`,
  `account_changed`, `profile_changed`, `identity_unknown`.
  Sem payload de chat, prompt, account/model/effort ou segredos.
- `onRemoved` gera `tab_closed`; `onUpdated` URL/rota e
  `status=loading` mesmo na mesma URL revogam a geração anterior;
  rota conhecida de login dispara `signed_out` como sinal de
  *navegação*, não como atestado de usuário. Desaparecimento do
  leitor, troca de rota não conciliável e aba sem identidade usam
  `identity_unknown`; `onInstalled` e `onStartup` invalidam
  registros herdados do contexto anterior.
  `omaIdReconcileTabs` compara IDs de aba + IDs de conversa
  na inicialização MV3, sem ler cookie/sessão.
- O scan do leitor `conversation-evidence.js` é agora precedido
  por `omaIdPrepare`: é enviado `identity_epoch` no challenge;
  `observe` inclui a mesma época. Só registra `observed=true`
  após ACK `observed`/`unchanged` do relay.
  Mudança de aba/documento exige ACK de invalidação antes de
  publicar nova prova. Com relay offline, HTTP 4xx, timeouts ou
  callback incerto, evento permanece durável na fila, sem falsificar
  sucesso e sem reenvio de mensagens Web.
  `omaIdFlushInvalidations` é reentrante no SW, reenvia apenas
  notificações deny-only idempotentes e limita a varredura a 16 por
  rodada. Limite de 128 pendências: novas provas são negadas;
  não se executa limpeza permissiva dos eventos.
- `conversation-evidence.js` também gera novo `document_id`
  quando a rota SPA muda dentro do mesmo documento Chromium,
  mantendo ID estável dentro de uma geração. Um scan que cruza
  mudança de rota retorna `null`; DOM novo/desconhecido não
  valida identidade.

**`sentra_mcp/services/browser_evidence.py`:**
- Novo `browser_document_epochs` persistente no **SQLite central
  `chat_access`**, identificando `extension_id,worker,
  document_id,identity_epoch` com chave única.
- `BrowserEvidenceService.challenge(...,identity_epoch=None)`
  aceita V2, vincula época à geração do documento, nega mudança
  posterior de epoch no mesmo documento. O V1 sem época mantém
  compatibilidade com fixtures legadas; um documento previamente
  cadastrado com época V2 **não pode ser downgrade para V1**.
- `observe(...,evidence)` permite exatamente schema V1 ou V2
  (com único campo adicional `identity_epoch`) e nega mismatch,
  epoch ausente para documento V2 e epoch V2 sem desafio vinculado.
- `invalidate_document(...,identity_epoch=None)` confere época
  contra `browser_document_epochs`, antes da revogação; falsificação,
  downgrade ou geração divergente negam, sem apagar outra aba.
  Invalidação repetida sobre mesmo documento e mesma época é
  idempotente e mantém fail-closed após restart.

### Validação executada / evidência verdadeira

`tests/unit/sentra_cos_identity_mv3_round3.cjs` carrega o bloco
**real** do service-worker MV3 com `node:vm` como **test harness
hermético**, simulando `chrome.storage.local`, eventos de tab,
relay 404/offline, restart do worker e ACK posterior. Comprova:
pending gravado sem sucesso remoto, bloqueio de novo document,
reenviar somente deny-only, `profile_epoch` mantido e
`identity_epoch` rotacionado, URL de login como `signed_out`,
SPA navigation, reload na MESMA URL, fechamento de aba,
reconciliação após restart, `profile_changed` deny-only e
schema exato sem cookies nem credenciais. O trace `SENTRA_MV3_TRACE`
é JSON de IDs sintéticos, não tráfego remoto de conta.

`tests/unit/test_sentra_cos_chat2_round3_mv3.py` consome o JSON
literal gerado pelo JS e o passa ao **BrowserEvidenceService
de produção**, com SQLite real em `tmp_path`: challenge V2,
observe V2, mensagem MCP exata, mismatch de época negado,
invalidation V2 real, gate bloqueado, novo challenge revogado,
replay idempotente após nova instância do serviço, isolamento
entre `TAB-100`/`TAB-101`, e hash atual de build.

Comando executado após reestampar a extensão:

```powershell
node tests/unit/sentra_cos_identity_mv3_round3.cjs
python -B -m pytest tests/unit/test_sentra_cos_chat2_round3_mv3.py tests/unit/test_sentra_cos_chat2_evidence_js.py tests/unit/test_sentra_cos_chat2_dispatch_round2.py tests/unit/test_sentra_cos_chat2_action_and_message.py tests/unit/test_sentra_cos_browser_evidence.py tests/unit/test_sentra_cos_chat_access_and_connector_proof.py tests/unit/test_extension_versions.py tests/unit/test_extension_protocol.py -q --tb=short -p no:cacheprovider
```

Resultado final observado nesta rodada: **65 passed, 0 failed**,
9.36 segundos no pytest. `node --check` dos dois JS e
`compileall` do `browser_evidence.py` passaram na revisão.
O `scripts.commander.extension_identity.stamp_extension_identity`
registrou novo `sentra_source_hash` no
`edge_extension/manifest.json`:
`dcab821cec0fde7aae2739ad17f0730587224aba1b39e611741f3a9bfc96105b`.
Todos os hashes devem ser recalculados se outro agente modificar
qualquer dos sete arquivos assinados no source bundle.

### HANDOFF preciso para CHAT 3 — native_bridge/relay.py

Inspeção real atual: `native_bridge/relay.py::Handler.do_POST`
já publica as três rotas, mas **`challenge` e `invalidate`
ainda exigem schema V1**; o produtor V2 não pode operar com ele.
Não modificar automaticamente esta fachada enquanto o CHAT 3
trabalha. Patch mínimo, dentro do ramo autenticado existente
(`_authorized`, `_browser_collector` valida origem da extensão
pareada, SHA da versão e `worker`):

```python
if self.path == "/browser-evidence/challenge":
    if set(data) != {"source_sha256", "worker", "document_id", "identity_epoch"}:
        raise ValueError("exact V2 browser challenge schema required")
    collector = self._browser_collector(data)
    return self._send(state.browser_evidence.challenge(
        **collector,
        document_id=data["document_id"],
        identity_epoch=data["identity_epoch"]))
if self.path == "/browser-evidence/observe":
    if set(data) != {"source_sha256","worker","evidence"}:
        raise ValueError("exact browser evidence ingress schema required")
    collector = self._browser_collector(data)
    return self._send(state.browser_evidence.observe(
        **collector, evidence=data["evidence"]))
if self.path == "/browser-evidence/invalidate":
    if set(data) != {"source_sha256","worker","document_id",
                     "identity_epoch","reason"}:
        raise ValueError("exact V2 browser invalidation schema required")
    collector = self._browser_collector(data)
    outcome = state.browser_evidence.invalidate_document(
        **collector, document_id=data["document_id"],
        identity_epoch=data["identity_epoch"], reason=data["reason"])
    # Preserve existing worker-release behavior only after owner-safe
    # reconciliation with active leases/uncertain Web sends, as Chat 3 governs.
    return self._send(outcome)
```

`_browser_collector` deve continuar comprovando extensão/origin/build
no relay pareado; header de worker e época enviados pelo cliente
não devem ser considerados, sozinhos, identidade de conta.
Para rollout que ainda aceita clientes V1, compatibilidade deve ser
explicitamente versionada e V1 jamais pode alterar documento ligado
a época V2. Depois de integrar, testar POST loopback autenticado,
origem errada, build/hash errado, worker alheio, epoch trocado,
documento antigo, 404/offline, restart com ACK perdido e nenhuma
retransmissão `CHAT_SEND` incerta.

**Blocker de integração agora presente:** com o relay V1 atual,
`/browser-evidence/challenge` rejeita o novo campo como 400,
e `/browser-evidence/invalidate` também rejeita `identity_epoch`.
O MV3 mantém a fila e **não produz nova prova**. Não desativar o
campo nem suprimir erro para fingir E2E. Os testes acima são
contrato entre componentes reais e fixture JS, não teste HTTP
loopback da nova rota nem conta ChatGPT real.

### Limites honestos
- Nenhuma identificação/atestado REAL de conta ou de plano,
  modelos, effort, Automatic, quota ou logout sem navegação foi
  extraída. O `profile_epoch` é identificador gerado localmente;
  não autentica conta, nem detecta troca de conta silenciosa
  na mesma página, sem evento e sem prova externa do HOST.
  `WebMCPMessageDispatchGuard.verified_account` ainda é
  **False/fail-closed** sem callback independente do operador.
- O `onRemoved` MV3 é assíncrono; em crash abrupto no meio da
  gravação local não se pode provar entrega exata sem o endpoint e
  reconciliation do host. A fila após storage persistido é recuperável,
  mas Chromium não promete concluir todo trabalho no handler que
  foi encerrado. Não afirmar garantia de revogação síncrona remota.
- Ausentes prova real de extensão instalada/conta ChatGPT, E2E
  HTTP V2, interface Canvas de consentimento humana, QuickJS WASM
  verificado/pinado, CI/release assinado e homologação 34/34.
  Code Mode continua DESABILITADO; Node é apenas test runner.
- Não houve alteração em `native_bridge/`, `control_plane.py`,
  `sentra_mcp/server.py`, Canvas, CI, instalador, ou segredos.
  Não houve reset/checkout/stash/commit/push global.

### Complemento da validação final — 2026-10-10T10:26:57-03:00

O contrato de `WebMCPMessageDispatchGuard` foi endurecido nesta mesma
rodada: `AuthenticatedWebLink` inclui opcionalmente
`identity_epoch: str | None`. Se `browser_document_epochs`
contiver época V2 para extension/worker/document, a época do link
HOST autenticado DEVE corresponder byte a byte; ausência,
substituição ou tentativa de usar V2 sem binding são negadas
ANTES do efeito. Clientes legados V1 preservam o comportamento
anterior somente quando o documento não possui época V2.
Foi acrescentado `test_web_mcp_dispatch_bound_to_v2_identity_epoch`
que demonstra match, negação por ausência/tamper e revogação de
`identity_unknown`, sem atestar conta externa.

**Resultado mais recente substitui a seleção de 65:** os mesmos
8 módulos direcionados, agora com o teste de despacho V2,
terminaram **66 passed, 0 failed, 9.74s**; depois,
`python -B -m compileall -q` do browser_evidence e
web_account_dispatch, `node --check` de service-worker.js e
conversation-evidence.js e `git diff --check` de service-worker
e manifesto encerraram sem erros. Apenas warning CRLF/LF
preexistente em `edge_extension/manifest.json`.
Testes de 126/126 mencionados pelo coordenador pertencem à
auditoria ANTERIOR à Rodada 3; não são um novo E2E independente
deste código. Git do checkout compartilhado continua sem
commit/push, sem reset e com mudanças dos outros agentes intactas.

Handoff adicional ao coordenador: `host_authenticated_link(ctx)`
deve preencher `AuthenticatedWebLink.identity_epoch` somente da
correlação autenticada com o documento V2, nunca de header
ou argumento de modelo; `verified_account` permanece
deny por padrão até prova externa de conta/perfil/epoch. O
`profile_epoch` persistido pela extensão é estritamente um
marcador opaco local; não foi colocado em logs ou no payload
de invalidação, e não é prova de identidade ChatGPT.


---

## SETE FRENTES — CHAT 2 — INTEGRAÇÃO V2 E PROVA HTTP REAL (10/10/2026)

### Direitos de escrita e inspeção inicial

Lido `docs/SENTRA_COS_SETE_FRENTES_2026-10-10.md`. Escopo
exclusivo desta fatia: `edge_extension/`, `browser/`,
`sentra_mcp/services/browser_evidence.py`,
`chat_access.py`, `web_account_dispatch.py` e testes
`test_sentra_cos_chat2_*`. O `native_bridge/relay.py`
foi apenas lido: no início **ainda aceitava apenas V1**
(`challenge` sem `identity_epoch`, `invalidate` sem
`identity_epoch`). NÃO foi modificado. Nenhum arquivo
ControlPlane, Canvas ou pertencente ao CHAT 4 foi alterado.

### Código efetivamente implementado nesta rodada

1. `browser/evidence_http_v2.py` **NOVO**, roteador de contrato
   `dispatch_authenticated_v2(*, service: BrowserEvidenceService,
   path: str, payload: Mapping[str,Any], extension_id: str,
   source_sha256: str, worker: str) -> dict`.
   Suporta somente três rotas V2 `/browser-evidence/challenge`,
   `/browser-evidence/observe` e
   `/browser-evidence/invalidate`, com schemas exatos, sem
   campos de conta/modelo/effort. Confere igualdade de worker/hash
   recebido com identidade JÁ VERIFICADA pelo host; não considera
   `Origin` ou `worker` fornecidos pelo cliente uma autoridade
   isolada. É adapter para a rota HTTP autenticada do CHAT 3,
   **não** um servidor HTTP público, emissor de grant ou atestado
   de identidade de conta.
2. `edge_extension/service-worker.js`: `omaIdFlushInvalidations`
   agora exige ACK `invalidated` ou `unchanged` E
   `grants_created === false`. A resposta `absent` **não
   prova revogação** (pode representar SQLite/worker errado), logo
   permanece na fila persistente e bloqueia nova prova da aba.
   Após scan React, antes de POST `observe`, o MV3 relê do
   `chrome.storage.local` a associação document + identity_epoch
   + source_sha256 e a fila de deny; aborta observação atrasada
   após navegação/tab closed/novo documento. Não envia novo
   `CHAT_SEND` quando efeito Web anterior é incerto.
3. `sentra_mcp/services/browser_evidence.py`: tabela
   `browser_profile_uncertainty(extension_id,principal,reason,detected)`
   persistida no MESMO SQLite central `chat_access`. Eventos de
   `signed_out`, `account_changed`, `profile_changed` ou
   `identity_unknown` fazem INSERT/UPDATE transacional, antes
   de revogar o documento. Uma nova observação `idle`, outra
   aba, restart ou re-enrollment da extensão NÃO limpam o
   sinal de identidade incerta. `dispatch_state` devolve
   `identity_unknown,send_blocked=True` no principal sob
   incerteza. Fechamento/navegação simples continuam restritos
   ao documento, sem poison global automático.
4. `sentra_mcp/services/chat_access.py`: `require_allowed`
   nega pedidos browser-sourced vinculados a um coletor cuja
   identidade do perfil/conta permaneça incerta, ANTES da checagem
   do documento. `require_exact_message` herda esse bloqueio.
   Isso evita usar request/message de uma aba alternativa após
   logout ou troca de perfil. Legado local sem binding Web não
   recebe nova identidade nem grant a partir desses sinais.
5. `tests/unit/test_sentra_cos_chat2_action_and_message.py`:
   somente fixtures de teste adequadas à **nova** exigência
   `owner_authenticator` + `owner_proof` único por clique,
   introduzida de forma concorrente pelo CHAT 4 no módulo
   `action_consent_gate.py`. O autenticador é sintético, somente
   teste. **Não houve redução dos requisitos do CHAT 4**.

### Prova real: JS do produtor + HTTP TCP + SQLite

Novos arquivos:
- `tests/unit/sentra_cos_mv3_http_v2.cjs`: executa literalmente
  os blocos **reais** `omaId*` e `omaObserveConversation` do
  service-worker e a implementação real de
  `edge_extension/conversation-evidence.js` com grafo
  committed React sintético. Executa `fetch` HTTP real à
  porta efêmera `127.0.0.1` do teste, com cabeçalhos de
  extensão e bearer de **fixture**, sem consultar sessão real.
  Testa challenge → observe metadata.request_id/message.id →
  observação de `awaiting_approval` → navegação para login
  → outbox deny-only offline → reinicialização simulada do SW
  → transporte do invalidation → navegação NO MEIO do scan com
  cancelamento de POST tardio.
- `tests/unit/test_sentra_cos_chat2_http_v2.py`: cria
  `ThreadingHTTPServer` real exclusivamente loopback, porta
  dinâmica, origin/bearer de fixture, payload <= 64KiB e
  `dispatch_authenticated_v2` sobre
  `BrowserEvidenceService(tmp_path)` real. Verifica
  contra origem errada, bearer inválido, source SHA errado,
  wrong worker, ausência/troca de epoch, JSON V1 rejeitado,
  replay após restart, receipt de invalidation registrado no
  SQLite e `require_exact_message` negado após revogação.
  Em `awaiting_approval`, a request observada não é admitida
  apesar dos IDs coerentes. Um scan em voo, depois invalidado,
  **NÃO envia** outro `observe`; registro de `identity_unknown`
  é mantido.
- A mesma suíte contém prova de duas abas e duas conversas:
  `profile_changed` em TAB-11 bloqueia request autenticada
  originalmente de TAB-22, continua bloqueada após uma página
  nova com estado idle e após re-enrollment de coletor. Nenhum
  DOM de conta/modelo é usado para reabilitação.
- `tests/unit/sentra_cos_identity_mv3_round3.cjs` ampliado:
  resposta `absent` de invalidation não limpa fila,
  mantém deny-only após reinício do worker e permite escoar
  somente após ACK `invalidated`.

**Precisão do ensaio:** houve transporte TCP HTTP loopback REAL,
e classes de produção SQLite/React reader/produtor realmente
executadas, mas a `ThreadingHTTPServer` é uma instância de
contrato de TESTE, não `native_bridge.relay`; o MV3 foi
executado em Node VM como harness, não instalado num perfil Edge
autenticado. Nenhuma alegação de extensão/conta ChatGPT real
ou aceite Web E2E. Node não é fallback QuickJS/Code Mode.

### Resultado final e contrato de integração para o CHAT 3

Comando executado: python -B -m pytest -q -p no:cacheprovider --tb=short
com 9 módulos explícitos:
test_sentra_cos_chat2_http_v2.py,
test_sentra_cos_chat2_round3_mv3.py,
test_sentra_cos_chat2_evidence_js.py,
test_sentra_cos_chat2_dispatch_round2.py,
test_sentra_cos_chat2_action_and_message.py,
test_sentra_cos_browser_evidence.py,
test_sentra_cos_chat_access_and_connector_proof.py,
test_extension_versions.py e test_extension_protocol.py.

**Resultado final: 70 PASSED, 0 FAILED, 12.02 s, exit 0.**
Testes negativos incluem bearer/origin adulterados, worker sem
host-ownership, epoch/build não reconhecidos, payload sem epoch,
aprovação humana pendente, revogação, restart e duas abas.
Testes concorrentes do CHAT 4 exigem agora owner_authenticator e
owner_proof frescos. Adaptei APENAS as fixtures antigas do CHAT 2
com asserção sintética de clique; não modifiquei ActionConsentService.

Adaptador novo: browser/evidence_http_v2.py.
Assinatura exata:
  dispatch_authenticated_v2(
      *, service: BrowserEvidenceService, path: str,
      payload: Mapping[str, Any], extension_id: str,
      source_sha256: str, worker: str,
      authorized_worker: Callable[[str, str], bool]
  ) -> dict[str, Any]

Rotas e esquemas exatos:
  POST /browser-evidence/challenge
    {source_sha256,worker,document_id,identity_epoch}
    => {nonce,expires_in}
  POST /browser-evidence/observe
    {source_sha256,worker,evidence:{
      nonce,document_id,conversation_id,route_conversation_id,
      state,requests:[{request_id,message_id}],identity_epoch}}
    => {state,requests,grants_created:false}
  POST /browser-evidence/invalidate
    {source_sha256,worker,document_id,identity_epoch,reason}
    => {state,grants_created:false}

O source SHA do MV3 foi recalculado por
scripts.commander.extension_identity.stamp_extension_identity:
dbd4bf0d9eda1bee57caf8c690217b3e2e0182c7d11d3feb1e775af2c94c005e.
O teste de identidade do manifest confirmou esse hash.

PASSO 1 — CHAT 3: em native_bridge/relay.py, substitua SOMENTE
os três handlers V1 por dispatch_authenticated_v2, após verificar
self._authorized(), Origin da extensão e SHA atual no cadastro.
O parâmetro extension_id deve vir da origem autenticada, nunca do
JSON. Worker e SHA devem corresponder ao registro do HOST.
A implementação atual de _browser_collector copia worker do JSON:
**isso sozinho não comprova ownership!**

PASSO 2 — CHAT 3: forneça authorized_worker(extension_id,worker)
consultando o pool/registry/lease autoritativo do relay, comprovando
que aquele TAB-id pertence ao coletor/profil cadastrado. O adapter
NEGA se não houver função de verificação ou se ela não retornar
literalmente True. O teste HTTP usa um registro host sintético
restrito a extensão a...a e TAB-77 apenas no ambiente hermético.
Não usar retorno constante True na produção.
O CHAT 3 deve preservar a semântica existente de workers/leasing:
revogar documento não autoriza reenvio de CHAT_SEND incerto,
não mata PIDs, não libera worker alheio.

PASSO 3 — CHAT 3: use exclusivamente serviço SQLite central atual:
state.browser_evidence (nenhum storage paralelo). Envelopes V1 sem
identity_epoch não podem ser aceitos em endpoint V2 nem modificar
documento com epoch já vinculado. Reexecutar teste POST com HTTP
loopback no native_bridge real, com origem/bearer falsos, SHA antigo,
worker errado, epoch/documento errados e crash/restart.
O producer existente mantém fila deny-only quando o relay HTTP V1
retorna erro 400 ou o ack é absent. Não falsificar sucesso.

### Handoff exato ao coordenador — identidade Web e MCP

A classe sentra_mcp/services/web_account_dispatch.py::
WebMCPMessageDispatchGuard permanece deny-by-default, sem
autorização de conta real. Na fachada central reservada, instanciar:

  guard = WebMCPMessageDispatchGuard(
      chat_access=chat_access, browser_evidence=browser_evidence,
      authenticated_link=host_authenticated_link,
      verified_account=host_verified_account)

Encadear guard.tool_observer(ctx,name) em
ToolPolicyProxy(request_observer=...) ANTES de executar cada tool.
host_authenticated_link(ctx) retorna somente ligação criada no
servidor por ingressos autenticados:
AuthenticatedWebLink(principal,request_id,message_id,extension_id,
worker,document_id,identity_epoch). Nunca derivar diretamente
de campo MCP/model, header arbitrário de cliente ou DOM incerto.
O serviço require_exact_message verifica associação entre
metadata.request_id e ID de mensagem, doc, epoch, quarentena,
bloqueios da conversa e incerteza do perfil em SQLite.
Isso NÃO cria grant ou Operation. Ferramentas ainda precisam
passar pela AuthorizationService e gate durável centrais.

host_verified_account(ctx,link,conversation_id) precisa consultar
prova independente, HOST-BOUND, com sessão/perfil/conta/epoch
atuais e ausência de logout. Na falta de prova real retorna False.
Um label de modelo/effort/Automatic, avatar, seletor, URL ou
branch React não basta. O próprio ChatGPT Web real e a extensão
instalada não foram exercitados nesta rodada. Conta e modelo
continuam UNKNOWN e ferramentas com essa exigência continuam
BLOQUEADAS.

### Bloqueio de perfil e riscos honestos

BrowserEvidenceService gravou a nova tabela
browser_profile_uncertainty(extension_id,principal,reason,detected).
Ela torna a política de tabs fail-closed em signed_out,
account_changed, profile_changed ou identity_unknown. Mesmo novo
scan idle, nova aba, reinício do SQLite ou nova revisão do
collector NÃO removem o poison. Ainda não há API host-attested
para remover o bloqueio: essa recuperação deverá exigir prova
independente de conta/perfil pelo coordenador, trilha auditável e
proteção contra abuso por modelo e JS. O estado conservador pode
bloquear outras conversas do mesmo principal por segurança;
não mascarar esse efeito colateral.

Fluxo de teste HTTP: porta efêmera 127.0.0.1, Python
ThreadingHTTPServer TESTE, Node fetch REAL, reader React REAL,
trecho de service-worker MV3 REAL, BrowserEvidenceService e SQLite
REAIS; bearer e grafo DOM eram fixtures herméticas. Não foi
instalado, aberto ou autenticado um Edge novo para este ensaio.
Não chamar isso de E2E da extensão carregada em Edge ou de conta
ChatGPT verificada. Não há prova criptográfica de conta,
modelo/effort/Automatic, troca silenciosa de conta na mesma aba,
plan/quota ou schema remoto ChatGPT. QuickJS WASM e ActionConsent
de produção pertencem ao CHAT 4, fora deste escopo.

Riscos residuais: se o MV3 encerrar abruptamente antes de gravar
um evento, a revogação remota não é garantida; necessidade de
reconciliação real de worker/lease no relay. A fila persistida
faz retry SOMENTE da notificação DENY-ONLY. ACK absent NÃO
desbloqueia e desconhecimento de conta/perfil não vira grant.
Nenhuma credencial/cookie/token do Edge foi consultada.
Checkout compartilhado intacto para os outros agentes; sem
reset/checkout/stash/clean/commit/push, sem edição em
native_bridge, Canvas, ControlPlane, tool_policy ou CHAT 4.

---

## RODADA 4 / 7 FRENTES — CHAT 2 — produtor REAL de receipt V2 (10/10/2026)

### Auditoria inicial e escopo preservado

Lidos docs/SENTRA_COS_RODADA_4_2026-10-10.md e
docs/SENTRA_COS_SETE_FRENTES_2026-10-10.md; git status inicial
real do checkout OGrandeOxta inspecionado. A área do CHAT 2 se
restringiu a edge_extension/service-worker.js, testes próprios,
manifesto estampado e ESTE relatório. NÃO modificado
native_bridge/relay.py (CHAT 3), control_plane.py, server.py,
tool_policy.py, Canvas, sentra_runtime, action_consent_gate.py
(CHAT 4) nem arquivos de CI/installer. Nenhum reset/checkout/
stash/clean/commit/push global ou processo de agentes encerrado.

O relay CHAT 3 já recebe challenge/observe/invalidate com
identity_epoch V2 e POST /jobs/delivery-receipt com 8 chaves
exatas (incluindo identity_epoch). Verificado que a implementação
host exige Run/WorkItem e grant ORIGINAL web:send,
prompt_sha256 armazenado, mesmo worker da lease, token, fase
sending, documento inscrito e join browser metadata request_id
→ message.id no SQLite de chat_access. Forma de 4 chaves
continua explicitamente PRELIMINAR.

### Implementação no service-worker MV3 de PRODUÇÃO

1. **omaRecordDeliveryReceipt(identity,job,sent,sendingConfirmed=false)**:
   mantém forma de 4 chaves como PRELIMINAR caso não haja
   prova no browser (inclusive approval pending, documento
   incerto, metadata ausente, conta desconhecida, worker/lease
   divergente). Nunca eleva o recibo de mensagem produzido
   pelo content-script a prova por si só, não deriva request_id
   de job_id, texto, URL, avatar, DOM de conta/modelo/effort.
   Quando existe correspondência exata, envia JSON V2 com
   {job_id,worker,lease_token,evidence,request_id,
   source_sha256,document_id,identity_epoch}; evidence permanece
   estritamente {conversation_id,message_id,prompt_sha256,
   images_attached}. A identidade da extensão é derivada do
   build local estampado. Regra: confirmação de fase sending,
   ownership em active job (job_id/worker/lease_token + sent
   !== true) e mesma mensagem/conversa no leitor React.
   O callback faz uma única chamada /jobs/delivery-receipt;
   erro HTTP ou ACK perdido após a tentativa V2 NÃO dispara
   fallback 4-key, retry de receipt ou novo clique Web.
2. **omaObserveConversation(tabId,expected=null)**:
   preserva scans existentes, mas em modo receipt witness
   exige committed React page evidence de estado idle,
   exatamente uma associação
   message.metadata.request_id → message.id que coincida
   com o message_id do delivery_receipt, conversation_id
   igualmente válido, worker inscrito, documento, source_sha256,
   identity_epoch V2, absence de pending deny-only e confirmação
   do BrowserEvidenceService via challenge + observe HTTP.
   Revalida Chrome tab e storage novamente após o ACK do
   servidor. Com approval pending/generating/unknown não
   devolve witness; no máximo persiste observação deny-aware.
   DOM diferente/virtualizado dá resultado sem witness.
3. **Fencing de envio** em AMBOS os caminhos
   CHAT_START/CHAT_SEND e CHAT_TASK: antes do
   SEND_MESSAGE (clique), confirma /jobs/progress
   phase=sending. Para ChatGPT, se não houve ACK explícito
   ok:true, aborta ANTES do efeito com SEND_FENCED.
   Fase sending latched no relay impede retry físico
   at-most-once de envio cujo resultado seja UNCERTAIN.
   A chamada de recibo recebe sendingConfirmed booleano
   do próprio retorno HTTP, não de parâmetro do modelo.
   Gemini preserva seu fluxo independente, sem promover
   receipt ChatGPT.
4. O formato de documento/epoch da Rodada 3 é mantido:
   identidade por documento, fila deny-only, bloqueio ao
   mudar de aba/logout/profile, sem ler cookie/token.
   O perfil e conta ChatGPT continuam NOT_ATTESTED; receipt
   V2 prova unicamente associação do efeito Web ao
   documento/mensagem cadastrados, NÃO prova plano/modelos.

### Teste de integração REAL do produtor ao relay/SQLite

Arquivos novos:
- tests/unit/sentra_cos_chat2_receipt_v2_pipeline.cjs
  extrai e executa do arquivo de PRODUÇÃO service-worker.js:
  SENTRA_IDENTITY_REVOCATION_BEGIN/END,
  omaRecordDeliveryReceipt, omaObserveConversation e
  omaProgressPhase. Também executa a implementação real
  edge_extension/conversation-evidence.js contra um grafo
  committed-React sintético. Usa fetch REAL em TCP loopback
  contra o RelayServer CHAT 3 e bearer DESCARTÁVEL do
  teste, sem acesso a Edge/conta/segredos.
- tests/unit/test_sentra_cos_chat2_receipt_v2_pipeline.py
  usa helpers de testes CHAT 3 sobre RelayServer REAL,
  WebContinuation, controle com SQLite central,
  WorkItem/Run, grant original web:send, JobStore e
  lease 'TAB-337' do mesmo worker. Nenhuma cópia de
  authority/gate, nenhum envio ao ChatGPT. Em 12 cenários:
  V2 positivo sent→attested→WebContinuation.commit
  PUBLISHED; aprovação pendente; metadata ausente;
  message_id diferente; epoch errado; downgrade para
  V1 7-key; document_id errado; profile_changed com
  poison central persistido; ausência de sending;
  worker ativo de outro TAB; ACK V2 perdido depois de
  receipt persistido (1 POST e ZERO fallback);
  ACK sending com HTTP 200 mas ok:false (nega
  promoção e, na execução de produção, impede clique).
  POST V2 negativo 403 não cria authenticated_web_receipts,
  não requeue e permanece 1 job no SQLite relay.
  Nenhuma identidade de conta/modelo/effort é fingida.

Rodada focal executada após alterações de código:
python -B -m pytest -q -p no:cacheprovider --tb=short
tests/unit/test_sentra_cos_chat2_receipt_v2_pipeline.py
=> 12 passed, 0 failed, 18.20 s.

Previamente o conjunto com 10 cenários + test_http_v2
=> 14 passed, 0 failed, 17.36 s, antes da inclusão dos
cenários de falha de ACK. NÃO somar como testes distintos.

### Hash oficial e handoff de segurança

O source foi carimbado com
scripts.commander.extension_identity.stamp_extension_identity,
após alterar service-worker.js:
22e81083a203aeb9645773de6842b595c66aad1751dc9e445dcdc0354860b464

**Coordenador / ToolPolicyProxy:** instalar
WebMCPMessageDispatchGuard(chat_access=...,browser_evidence=...,
authenticated_link=host_authenticated_link,
verified_account=host_verified_account). Executar
guard.tool_observer(ctx,tool_name) ANTES de bodies de tools.
AuthenticatedWebLink só é produzido no HOST a partir da
associação autenticada de principal,request_id,message_id,
extension_id,worker,document_id,identity_epoch. Não conceder
grants pela observação Web. verified_account deve continuar
retornando False sem fonte INDEPENDENTE de conta/perfil/epoch;
nenhuma prova de conta/modelo/effort/Automatic foi obtida.
ControlPlane/durable authorization originais ainda são
obrigatórios e devem ser revalidados imediatamente antes do
efeito. Callback do novo V2 não autentica conta humana,
nem aprova ferramentas MCP automaticamente.

**CHAT 3:** manter exato schema V2 8 chaves no endpoint
/jobs/delivery-receipt; fase sending, Run/WorkItem,
grant web:send, lease/token/worker document/epoch e
metadata.request_id/message.id no SQL autoritativo;
preliminar 4-key jamais autoriza WebContinuation.commit.
Uma resposta HTTP errada/ausente após clique é UNCERTAIN;
permitir apenas reconciliador host-only já existente
reconcile_web_receipt, nunca segundo Web submit.
Não editar extensão a partir do CHAT 3 nem enfraquecer
identity_epoch e o perfil poison.

### Consolidação final da Rodada 4 (após reestampar extensão)

Comando de regressão executado no checkout real, SEM -k/exclusões:
python -B -m pytest -q -p no:cacheprovider --tb=short
  tests/unit/test_sentra_cos_chat2_receipt_v2_pipeline.py
  tests/unit/test_sentra_cos_chat2_http_v2.py
  tests/unit/test_sentra_cos_chat2_round3_mv3.py
  tests/unit/test_sentra_cos_chat2_evidence_js.py
  tests/unit/test_sentra_cos_chat2_dispatch_round2.py
  tests/unit/test_sentra_cos_chat2_action_and_message.py
  tests/unit/test_sentra_cos_browser_evidence.py
  tests/unit/test_sentra_cos_chat_access_and_connector_proof.py
  tests/unit/test_sentra_cos_web_v2_transport.py
  tests/unit/test_sentra_cos_web_v2_http_ingress.py
  tests/unit/test_extension_versions.py
  tests/unit/test_extension_protocol.py

RESULTADO REAL: **90 PASSED, 0 FAILED, 50.81s, exit 0**.
A seleção inclui módulos do próprio CHAT 3 para provar que o
caminho MV3 V2 não quebra o RelayServer/SQLite central. O teste
de compatibilidade de hash do manifest executou e aprovou.
Sintaxe: python compileall de Web/tests, node --check dos JS
modificados e git diff --check dos arquivos Git rastreados:
exit 0, somente aviso CRLF/LF do manifesto.
Nova identidade pós-mudança completa e estampada:
22e81083a203aeb9645773de6842b595c66aad1751dc9e445dcdc0354860b464.

**Sem efeito Web incerto duplicado:** os testes comprovam que
a perda do ACK APÓS o relay gravar authenticated_web_receipts
produz somente UM POST V2 no produtor, ZERO fallback preliminar,
UM job em JobStore e nenhum segundo SEND_MESSAGE no harness.
O verdadeiro fluxo de produção deixa o relay entrar em phase
sending ANTES do clique (retorno ok:true obrigatório), e sua
persistência de may_have_sent controla fail-closed; não tenta
novo envio em lease incerta. Reconciliação sem clique permanece
exclusivamente host-only no CHAT 3/coordenador.

**Handoff ToolPolicyProxy/guard:** o coordenador deve compor
request_observer=guard.tool_observer ANTES de qualquer callback
MCP; não derivar authenticated_link de dados de modelo ou
headers arbitrários; preencher epoch via correlação host da
extensão worker/document e request observado. verified_account
é host-only e deve retornar False sem prova independente,
mesmo que um recibo Web retorne state='attested'. Receipt V2
não é grant, consentimento humano nem prova de conta Plus.
O estado de aprovação pendente é observado e bloqueia atestado
via o produtor (mantém apenas recibo preliminar); a proteção
de efeito MCP continua dependente do guard central integrado.
Verificar no host que ToolPolicyProxy não substitua observers
existentes e revalide grants/Operation central no efeito.

**Limitação não mascarada:** o ensaio usou o source JS MV3 REAL
em harness Node (não serviço Chrome instalado), HTTP de rede
127.0.0.1 contra RelayServer REAL e SQLite real, mas mensagens
React, worker Chrome e token do relay foram fixtures; não houve
conta ChatGPT real, CAPTCHA, alteração de modelos/effort nem
métricas reais. Uma mensagem cuja metadata.request_id não
está acessível no React committed é corretamente PRELIMINAR
e só pode ser conciliada pelo host mais tarde; sem metadata
não se inventa request_id nem atestado. Não homologado.

---

## RODADA 5 — MV3 / ChatTrust / receipt host-only (2026-10-10)

Escopo conferido pela leitura dos arquivos docs/SENTRA_COS_RODADA_5_INTEGRACAO_CENTRAL_2026-10-10.md e docs/SENTRA_COS_RETOMADA_7_FRENTES_OPEN_DOTS_2026-10-10.md, antes de alterar. Git status consultado no checkout compartilhado do OGrandeOxta. Nenhuma alteração em native_bridge, Canvas, ToolPolicyProxy, ControlPlane, CodeMode ou scripts de release. Sem reset/checkout/stash/clean/commit/push global.

### Alterações concretas

1. edge_extension/service-worker.js: novo SENTRA profile poison em chrome.storage.local (sentra_id_profile_poison), com razão e geração opaca aleatória. NÃO é prova de conta. signed_out/account_changed/profile_changed/identity_unknown gravam primeiro o bloqueio e TODAS as notificações de revogação dos documentos rastreados em quaisquer abas e somente depois removem a prova local. Navegação e tab_closed sem mudança de conta revogam apenas a aba identificada. Navegação explícita a login pode disparar poison mesmo vindo de tab sem documento prévio. A fila de revogação repete SOMENTE deny-only; não repete envio Web.

2. omaIdPrepare e omaObserveConversation bloqueiam challenge, nova observação e testemunho de recibo quando o perfil está poisoned, mesmo após ACK da última revogação, reinício do service worker ou abertura de nova aba. O marcador é rechecado antes/depois dos awaits do leitor, preservando document_id, worker, identity_epoch, source_sha256 e request_id/message_id exatos. A recuperação do perfil NÃO ocorre por DOM idle ou seleção de conta; requer desenho posterior de fluxo host-attested e autorização do operador.

3. omaRecordDeliveryReceipt: marcador durável de primeira tentativa sentra_id_receipt_<job_id>, sem prompt, token, cookie, conta ou lease; e Set em memória para impedir interleaving concorrente. A marca é persistida ANTES do HTTP delivery-receipt, seja preliminar ou V2. Retries, reinício ou ACK perdido resultam em estado uncertain/automatic_resend false, sem segundo POST e sem downgrade V2 para 4-key. A execução física SEND_MESSAGE permanece at-most-once sob fase sending com ACK ok:true do relay antes do clique. O atestado V2 exige nonce/observação React metadata.request_id -> message.id no MESMO doc/worker/epoch e documento ao vivo; aprovação pendente não promove receipt.

4. sentra_mcp/services/web_account_dispatch.py: novo HostWebReceiptRef(owner,run_id,job_id) frozen e factory importável guard_from_durable_web_receipts(*, control, host_receipt_ref, verified_account=None). Exige callback de job vindo EXCLUSIVAMENTE do host autenticado (não model args, DOM ou header). Confere Run/workspace e linha de authenticated_web_receipts do SQLite CENTRAL de session_checkpoint; reconstitui extension_id, worker, document_id e identity_epoch a partir de browser_request_messages e browser_document_epochs, negando ausência, colisão ou downgrade. Constrói WebMCPMessageDispatchGuard já existente; sem callback de conta independente, FAIL-CLOSED. Não cria grants, WorkItems nem Operations.

### Prova HTTP / SQLite / Node

Novos testes tests/unit/test_sentra_cos_chat2_host_guard_r5.py: RelayServer real do Chat3, WorkItem/Run, grant web:send, entrega atestada, SQLite e factory host-only. Verificam source ausente, request alterado, ChatTrust strict/trust/block revisionado, approval pending e profile_changed. A aceitação com verified_account=True é SOMENTE uma fixture host de teste: NÃO valida conta ChatGPT real.

Tests tests/unit/sentra_cos_chat2_receipt_v2_pipeline.cjs e tests/unit/test_sentra_cos_chat2_receipt_v2_pipeline.py ampliados: executam CÓDIGO-FONTE do MV3 e conversation-evidence.js em Node VM de teste, com HTTP TCP REAL a RelayServer e SQLite central. Novos cenários multi_tab_logout (documentos de TAB-337/TAB-338 revogados; poison global e nova aba recusada), reload, duplicação de callback e ACK incerto com uma única tentativa HTTP; preservam cenários anteriores de request/message errado, wrong epoch, downgrade e approval pending. Zero Web prompt enviado a ChatGPT externo; Node não é fallback de CodeMode.

As fixtures antigas sentra_cos_identity_mv3_round3.cjs, test_sentra_cos_chat2_round3_mv3.py e test_sentra_cos_chat2_http_v2.py foram alinhadas à política nova: ACK de revogação após logout NÃO é prova de conta recuperada. Sem afrouxar política do produto.

Regressão observada após reestampar: 13 módulos selecionados (host_guard_r5, receipt_v2_pipeline, http_v2, round3_mv3, dispatch_round2, evidence_js, action_and_message, browser_evidence, chat_access_and_connector_proof, web_v2_transport, web_v2_http_ingress, extension_versions, extension_protocol): **93 PASSED, 0 FAILED, exit 0, 47.61 segundos**. Nenhum -k nem skip proposital. Apenas posteriormente um ramo morto do próprio teste Python foi retirado; nenhuma fonte da extensão foi editada após esse resultado.

O manifesto foi reestampado com scripts.commander.extension_identity.stamp_extension_identity, após a última edição da extensão. Source SHA-256: d9bedb0f746e2249e3d56350899a4a25c936686ebc5625e8c238512870735c85. O conjunto acima inclui teste de conformidade do hash da extensão.

### Handoff exato — coordenador / Codex ToolPolicyProxy

Importar HostWebReceiptRef e guard_from_durable_web_receipts de sentra_mcp.services.web_account_dispatch.

Chamar guard_from_durable_web_receipts(control=control, host_receipt_ref=callback_host_only, verified_account=callback_host_attestation_or_None). O callback_host_only(ctx) retorna HostWebReceiptRef(owner,run_id,job_id) SOMENTE do broker da sessão autenticada com o vínculo da invocação MCP ao job; NUNCA do header x-request-id, do modelo, do URL, do DOM ou de argumentos da ferramenta. A factory exige o recibo previamente atestado no SQLite e reconstrói a ligação Web; apenas observação da extensão não substitui esse atestado.

Compor guard.tool_observer dentro de ToolPolicyProxy(request_observer=...), preservando observers existentes e mantendo checagem de owner/grants/Run/WorkItem/Operation durável antes de qualquer efeito. A factory e o observer não emitem autorização por si. verified_account é fonte HOST independente de conta/perfil/epoch atual. Sem prova independente: retorne False ou deixe None para negar TODOS os tools dependentes de identidade Web. Receipt V2 não prova conta, Plus, modelos, effort ou Automatic.

### Limitações e riscos

Prova HTTP/SQLite e código fonte do MV3 reais em ambiente de integração HERMÉTICO, mas Chrome/Edge executado com extensão carregada e conta ChatGPT REAL não foram homologados. As árvores React, Origin/bearer e perfil do navegador foram fixtures isoladas. Um crash de MV3 antes de persistir o evento ainda requer reconciliação por worker/lease do host; apenas DENY-ONLY pode ser reenviado. Poison local é conservador e NÃO possui limpeza automática; recuperação com owner-auth e prova de conta pertence à coordenação. Nenhum cookie, segredo, credencial de conta ou prompt remoto foi inspecionado. Nenhum efeito Web UNCERTAIN foi reenviado.
