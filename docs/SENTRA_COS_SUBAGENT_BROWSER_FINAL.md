# Subagente 2 — browser/Electron/Canvas: entrega candidata e evidências

Atualizado 2026-10-11. Produtor independente Host de mensagem implementado e testado na candidata; **homologação e ativação de produção NÃO concluídas**. Conta/calibração, wire/callback assistant homologado, seleção física disponível e regressões preexistentes continuam gates reais. Nenhum envio Web real ou acesso a cookies/tokens, nenhuma instalação global/ativação/reinício de serviço. Gateway PID20956/17842 e upstream17841 não foram operados por esta frente.

## Adendo mais recente: wire default e revisão independente do backend

Cliente `read_host_message` e defaults `_host_observation` user/assistant foram implementados pelo coordenador e exercitados nesta frente sem editar backend. Teste Worker original Edge preservado; nova variante Electron inscreve collector_id/surface/worker no registro host existente, mantém account/activation **fixtures explícitas** com authentication_revision1 e usa callbacks default que leem o Host/control-server/collector reais sobre ponte WebContents→Chromium isolado. Descriptor privado usa PID/target presentes do processo QA; user e assistant possuem IDs/parent/request/body reais do DOM de fixture. Teste Electron nativo separado já exercita WebContents real. Não são conta/calibração homologadas.

Nova variante negativa Host authentication_revision2 vs cap/proof1: receipt negado após um Send, sem duplicar job/Run/Operation/fence, sem SENT/ANSWERED. Primeiro assert esperava motivo interno backend que o produtor corretamente oculta; ajustado para código público sentra_receipt_rejected e estado central. Resultado ampliado executado: **30 PASS em 22.55s**, sendo 3 variantes Worker→Gateway, 1 Canvas→HTTP e 26 casos cliente Host HTTP. Antes da variante negativa: 3 PASS em 9.91s; reexecução inicial com o backend novo: 2 PASS em 7.23s. Comando: `python -m pytest tests/unit/test_sentra_cos_durable_worker_gateway.py tests/unit/test_sentra_cos_durable_canvas_browser.py tests/unit/test_sentra_browser_host_identity.py -q` com QA tree hlczzsv6. Nenhum teste ignorado.

Relógios independentes: regra Hostrevision==Workerrevision **removida**. read_host_message exige host_revision inteiro positivo e revision_source Host. Callback entrega host_observation separado; WebHistoryStore persiste metadados Host e frame na mesma transação provider_content existente. Valida fonte/doc/epoch imutáveis, revisão Host monotônica, ausência de conflitos body/state em mesma revisão; relógio central tem verificação própria. Backend foi lido após implementação. Lacuna `authentication_revision=True` versus int1 foi reportada e corrigida pelo coordenador com type explícito; esta frente reconferiu a fonte.

**P1 doc/epoch original — FECHADO por fonte e teste (2026-10-11).** Reprodução anterior em memória com funções reais, SQLite original e mocks somente de cap/descriptor/HTTP, sem rede/conta/efeitos, demonstrou `{authenticated:true,original_document_matches:false,original_epoch_matches:false,returned_expected_epoch_old:true,actual_query_epoch_new:true}`. Coordenador corrigiu `_host_observation`: tab.documentId/identityEpoch == row.document_id/identity_epoch antes do challenge; observed.document_id/identity_epoch == mesma linha após read, antes de authenticated:true. Fonte reconferida independentemente. Composição default troca doc e epoch separadamente na aba por descriptor real e no snapshot por fixture, mantendo auth/SHA/IDs; ambos negados, receipt conserva SENDING. Não cria receipt/grant extra. Guards se aplicam a user/assistant; proteção adicional assistant/history é preservada. Correção de auth bool/null/texto/revision diferente também coberta. Nenhuma edição de Gateway/Host cliente nem operação nos processos live por esta frente. Conta/calibração, homologação e promoção seguem fechadas; o achado específico está resolvido.

**Fechamento independente final:** após a correção, executei na árvore **cx5hq57r** `python -m pytest tests/unit/test_sentra_cos_gateway_outbox_composition.py tests/unit/test_sentra_cos_durable_worker_gateway.py tests/unit/test_sentra_browser_host_identity.py tests/unit/test_sentra_cos_backend_host_history_clock.py -q`: **48 PASS em 22.59s, zero skip**. Log `C:\Users\vitor\AppData\Local\Temp\sentra-browser-v2-cx5hq57r\final-p1-closure-qa.log` e resumo `SENTRA_P1_CLOSURE_QA_RESULTS.json`. O resultado 48 PASS/20.68s informado pelo coordenador é sua execução separada; não agregá-lo aos 48 desta frente. Rodada encerrada sem novo escopo ou fechamento de agentes. Produção PID20956 permanece sem aplicação desta candidata; bloqueio policy de restart informado pelo coordenador, nenhuma tentativa nesta frente.

Proveniência candidata mais recente reconferida: `C:\Users\vitor\AppData\Local\Temp\sentra-browser-v2-cx5hq57r\SENTRA_QA_PROVENANCE.json`: upstream a13cd09950969f43e3b7e25c71fa43efaf5446c5, 41 paths, host_syntax/typecheck/runtime_build passed, production_activated:false. Patch atual **875d632c9b93b674c7318edd3800686606f66a7e8fe292a7e5ea256defa98d90**; Host f7578e85528675487f574605e5fc61ec8d7e6dae244ad6fc7f39ff77d553d956, control a541dde8ba7bccd8469f70c0031133b0bc6f56732505737e8d3c727bf242f28d, collector d2b496d193dc2741bf9b0f69f46c1fce5f4838496b2d8d7b9e076a9ac3507cf4. CLI/helper iguais aos hashes abaixo. Patch não mudou nesta revalidação; upstream puro continua vazio no git status. As evidências build/29 WorkerHost/4 Electron abaixo permanecem válidas para esta mesma fonte.

## Resultado atual: Host message challenge/snapshot

Dois POSTs privados reais adicionados ao BrowserControlServer existente e ao BrowserHost: `/v1/sentra/message-challenge` emite nonce Host único ligado a expectativas imutáveis com SHA/prazo 10s; `/v1/sentra/message-snapshot` aceita somente esse nonce, consome-o antes da leitura e observa o documento adquirido duas vezes sem transmitir expectativas ao renderer. Role vem exclusivamente de message.author.role committed; parent/request/body/status são observados e comparados exatamente. Mensagem assistant exige parent real user com metadata.request_id real. Callback Worker, body/role/revision enviados pelo Worker, selector, SSE e UUID local não são prova. Corpo não é devolvido/logado; SHA UTF-8 é calculado no Host. Binding/ownership/profile/partition/auth revision são revalidados antes/depois. Até 256 desafios transitórios com expiração e 2048 observações de revisão por aba; não há segundo banco/fila de execução.

`host_revision` é relógio próprio por documento/epoch/conversa/message, nunca eco de revisão Worker; releitura igual conserva revisão, mudanças observadas incrementam 1. `provider_revision` só metadata.revision real ou null, com negação de regressão após valor conhecido. Role/content/schema/parent/metadata inexistentes ou ambíguos e desafio inválido/reutilizado produzem UNKNOWN/negação. Documento, conta e seleção não são elevados por receipt. Aprovação ausente/oculta permanece UNKNOWN; pending exige card visível ou valor explícito committed; idle só valor explícito committed único, cuja semântica provider real **ainda exige calibração**. Account snapshot anterior conserva approval_state:null quando nada observado.

Descriptor: **`sentraMessageCollector:{id:'sentra-committed-message-v1',sha256:...}`**. Snapshot: `collector_id`, `collector_sha256`, `host_source_sha256`, nonce/digest, role/IDs/parent/body_sha256/host_revision/provider_revision/complete/doc/epoch/surface/approval. Contrato completo no CURRENT, seção Atualização 2026-10-11. Coordenador implementou cliente de duas chamadas e callback default sobre job/bindings originais; esta frente não altera Gateway. Aceitar somente matched:true + OBSERVED e fonte/build aprovados. Relógios Host e Worker são validados separadamente; backend persiste Host metadata atomicamente com frame e exige monotonicidade própria. Challenge CHALLENGED não é prova e não autoriza Send.

### Evidência nova executada, após incorporar endpoint no patch

| Verificação 2026-10-11 | Resultado | Evidência / limite |
|---|---|---|
| Patch limpo/allowlist/upstream puro | PASS | Mesmos 41 caminhos; upstream.json intacto; source a13cd09950969f43e3b7e25c71fa43efaf5446c5 |
| Typecheck root e runtime build | PASS em duas árvores | `sentra-browser-v2-hlczzsv6` e `sentra-browser-v2-cx5hq57r`; nenhuma ativação |
| Host/control-server syntax | PASS | node --check; segunda proveniência registra host_syntax passed |
| Launcher typecheck + renderer build | PASS | `bun run build` no launcher de hlczzsv6; 441 módulos, Vite6.4.3, dist apenas Temp |
| Host snapshots adversariais novos | **11 PASS / 373 assertions** | Endpoint HTTP real + Chromium isolado; nonce/replay/expiry/bearer/schema; role/getter/parent/request/IDs/body/complete/revisão/doc/partition/auth/stale/alternate/conflicts/approval |
| Conjunto Worker + Host | **29 PASS / 455 assertions** | Log `hlczzsv6/browser-host-worker-qa.log`; Worker continua físico Enter/ACK/receipt/answer |
| Electron processo real | **4 PASS / zero skip** | Canvas isolamento existente e novo Host HTTP executando executeJavaScript sobre WebContents real, sessão não persistente, protocolo inteiro interceptado; nonce replay e corpo alterado negados |
| Gateway + Canvas integrações HTTP reais | **2 PASS em 11.51s** | SQLite/grants/checkpoints temporários; callbacks de conta/assistant/ativação somente fixtures; não são homologação |
| Estado Canvas Node | **2 PASS** | Nenhuma projeção falsa/reenvio/consent boolean |
| Node launcher ampliado reexecutado | **118 PASS / mesmos 3 FAIL** | Mesmos nomes já demonstrados na baseline anterior; log hlczzsv6/launcher-regression-message.log; não afirmar suíte inteira green |
| Reprodutibilidade fonte Host/control e CLI/helper | PASS | SHA iguais entre hlczzsv6 e cx5hq57r |

Novo teste `tests/unit/sentra_cos_host_message_snapshot.test.ts`; runners Electron reais `sentra_electron/test/message-host-runner.cjs` e `message-host.test.cjs`. Npm test sem SENTRA_BROWSER_QA_TREE informa skip explícito do novo teste; resultado 4 PASS acima foi executado **com** árvore candidata definida. Host prototype usa o módulo de produção, controle HTTP e WebContents reais no processo Electron; janela escondida, partition isolada, todas as respostas HTTPS locais. Não lê sessão/default account nem executa BrowserHost constructor de login/cookies.

Primeira execução adversarial: 10 PASS/1 FAIL por logger.warn ausente no harness, que convertia rejeição schema400 em erro500. Harness corrigido; reexecução 11/11 e conjunto29/29 acima passaram. Uma tentativa inicial de regeneração encontrou arquivo novo ausente no upstream puro, antes de escrever patch; ajustado o tratamento /dev/null, regenerado e validado em duas árvores novas. A árvore w97h9k_h era patch anterior e **não** integra evidência atual.

### Proveniência atual para revisão do coordenador

* Patch SHA256 **`875d632c9b93b674c7318edd3800686606f66a7e8fe292a7e5ea256defa98d90`**.
* Host source SHA256 **`f7578e85528675487f574605e5fc61ec8d7e6dae244ad6fc7f39ff77d553d956`**.
* Control-server source SHA256 `a541dde8ba7bccd8469f70c0031133b0bc6f56732505737e8d3c727bf242f28d`.
* Message collector SHA256 **`d2b496d193dc2741bf9b0f69f46c1fce5f4838496b2d8d7b9e076a9ac3507cf4`** (função toString, também no descriptor).
* CLI/helper continuam `ca164ff1c12626bec908a643877ed3691a848b147e4c2629e1c32741b1d5f75c` / `6e848ae952234aee5821ae7b69aa9adbef100eb49cc9d56db7718cb9fd2b5ed5`: endpoint Host é CJS do launcher, não desses bundles.

Árvores completas: `C:\Users\vitor\AppData\Local\Temp\sentra-browser-v2-hlczzsv6` e `C:\Users\vitor\AppData\Local\Temp\sentra-browser-v2-cx5hq57r`. Proveniência de cx5hq57r inclui patch/hashes/host_syntax/typecheck/runtime_build e production_activated:false. Resultado auditável consolidado em `hlczzsv6/SENTRA_MESSAGE_QA_RESULTS.json`, além dos logs citados. QA reutiliza dependências root/launcher locais; o empacotador runtime upstream executa instalação production/frozen-lockfile/ignore-scripts **somente em dist/runtime/app descartável**, sem instalação global ou payload live.

Reprodução adicional à sequência abaixo: incluir `tests/unit/sentra_cos_host_message_snapshot.test.ts` no comando Bun e definir SENTRA_BROWSER_QA_TREE também ao `npm test --prefix sentra_electron`. `prepare_durable_qa.py --verify-build` agora verifica sintaxe e registra hashes Host/control no manifest.

**Gates finais reais:** schema conta não calibrado ⇒ account_verified:false; native collector role desconhecido ⇒ UNKNOWN; approval_state:null/UNKNOWN quando não observado; model/effort null e selection_verified:false quando menu oculto; callback Host assistant/user conectado em QA, P1 doc/epoch e tipo auth fechados por fonte/teste; source aprovado/aplicado em runtime live e homologação de provider/message/status/revision ainda pendentes. A implementação de produtor assistant já existe na candidata; “assistant host proof missing” nas evidências da rodada anterior descreve o gate de produção ainda não homologado, não ausência atual do endpoint. Não declarar produção complete. Rodada browser/UX encerrada para revisão, sem fechar agentes ou abrir novo escopo.

As seções abaixo preservam as alterações e evidências da rodada 2026-10-10. A proveniência acima substitui o hash antigo para revisão da candidata atual.

## Escopo e preservação

`git status --short` inspecionado antes das alterações. Checkout compartilhado já continha muitas mudanças; preservadas. Sem AGENTS.md na raiz. Não houve commit/push/reset/stash/clean nem outros agentes. Não foram editados native_bridge, sentra_cli, gateway.py, Canvas service/__main__, MCP server/tool_policy ou browser_relay. Ajustes backend observados nos testes foram realizados pelo coordenador/backend.

O relatório de contrato foi escrito antes da implementação em `docs/SENTRA_COS_BROWSER_CONTRACT_CURRENT.md` e atualizado conforme os endpoints reais. Fontes de desenho: docs obrigatórios da missão, CoS input/start-input/recorder/correlation/store/continuation/handoff/resume-gate/goal/chat-models e contratos V2 SENTRA existentes. Não há fila, banco ou cópia de armazenamento CoS novos no produtor/React.

## Mudanças desta frente

* `integrations/codex_chatgpt_web/sentra-upstream.patch`: integração física no BrowserWorker e helper IPC, flag estrita durable/legacy, preflight com prompt transformado + SHA privado, ACK sending antes de Enter, receipt user observado, streaming/final assistant observado. Mudanças novas concentradas nos seis caminhos allowlisted browser-worker/index/launcher-helper-client/browser-helper-main/browser-host/control-server. Todos os demais hunks da integração existente foram preservados. Os **41 patch_files e upstream.json permaneceram iguais**.
* `integrations/codex_chatgpt_web/prepare_durable_qa.py`: archive do commit pinado em árvore temporária, valida upstream puro e allowlist, git apply --check/apply, junctions das dependências locais, typecheck e build completo em Temp. Grava proveniência/hashes/production_activated:false; empacotamento upstream instala dependências production apenas na árvore descartável.
* React `sentra_canvas/desktop_ui/src/durable-web-state.js`, `durable-web-dialog.jsx`, `compact-resume-panel.jsx`, entradas QA `src/qa/durable-web-test.html/.jsx`; inserção de botão/dialog no `main.jsx` e estilos pontuais `desktop.css`. Outras alterações preexistentes desses arquivos não pertencem a esta frente.
* Testes próprios: `tests/unit/sentra_cos_durable_browser_worker.test.ts`, `sentra_cos_durable_gateway_runner.ts`, `test_sentra_cos_durable_worker_gateway.py`, `sentra_cos_durable_canvas.test.mjs`, `test_sentra_cos_durable_canvas_browser.py`; Electron `sentra_electron/test/isolation-runner.cjs` e `isolation.test.cjs`.

## Comportamento físico e autoridade

Somente `client_metadata.sentra_durable_web === true` ativa o handshake no adapter/helper/Worker. Flag ausente conserva legacy; presente não possui fallback. Gateway deve ativar exclusivamente a partir de modo durable_v2 persistido e gates aprovados. Patches/binários stale não foram usados para ativar produção.

Cada envio físico, incluindo parte multipart, usa submission_index próprio sobre capability/Run/Operation EXISTENTES. Prompt físico pós-transformação vai apenas no preflight privado, com SHA; nem prompt nem corpo assistant são registrados pelo produtor em logs. Preflight sem account_verified:true, sending ACK incompleto, seleção alterada, aprovação pendente ou documento/epoch/surface alterados impedem Enter. O latch de ambiguidade antecede o HTTP sending; ACK perdido nunca repete Send. Failure é conservador e não autoriza replay.

Receipt exige user message.id + metadata.request_id observados no React committed, texto cujo SHA corresponde ao prompt, IDs novos em relação ao baseline, mesma superfície/documento/epoch e conversa. Turn ID/seletor/SSE/UUID local não substituem mensagem. Após receipt a conversa fica vinculada; mudança durante ACK é revalidada. Reader sem metadata apropriada permanece bloqueado.

Answer exige assistant message.id real e metadata.request_id correspondente OU parent_id observado igual ao user receipt. Parent user só viaja se observado. Revisões aumentam com mudança de conteúdo/final; repetição sem mudança não publica revisão nova. Streaming usa callback dentro do loop de observação do Worker; final ocorre depois da conclusão DOM e antes do completion fence. ACK precisa ANSWERING/ANSWERED e job/message/revision exatos. Mudança de documento ou corpo final durante ACK impede conclusão. SSE response.completed isolado não prova resposta.

O primeiro teste Worker→Gateway revelou ausência de answer_message_id/answer_revision no status backend e falhou `sentra_answer_ack_invalid`; coordenador/backend corrigiu a projeção. Reexecução com API real passou com parent observado, partial/final, revisão 2 e ANSWERED. Validação do Worker permaneceu estrita.

## Snapshot host privado e limitações de identidade

Implementado POST `/v1/sentra/identity-snapshot` no BrowserControlServer existente; endpoint/token do descriptor, bearer obrigatório e loopback. Binding requerido traceId/surface_id/document_id/identity_epoch. Snapshot não aceita modelo solicitado ou ID de conta declarados como evidência. Antes/depois do executeJavaScript valida aba automatic/running adquirida, origem, documento/epoch e authentication_revision.

Coletor lê somente primitives account.id/user.id no ancestry committed do botão da conta, ignorando getters; não lê session endpoints, cookies, tokens, storage ou objetos completos. Retorna profile/partition, IDs observados quando disponíveis, doc/epoch/surface, observed_at, collector_sha256 e host_source_sha256. Hash/verified:false registrados no descriptor. Sem novo cache/banco. O coordenador implementou cliente readonly `sentra_model_gateway/browser_host_identity.py` para este endpoint.

Provider selection vem de controles DOM atuais, independentemente da seleção solicitada: radio explícito, descrição de família e slider visíveis/concordantes. Nenhuma inferência de família a partir de Latest ou Pro genérico. Controle ausente/oculto/ambíguo => model/effort null e selection_verified:false. O Worker verifica os controles existentes antes/depois dos awaits; Host não abre menus nem mantém seleção anterior como prova atual.

**Gates ainda fechados:** schema account.id não calibrado em documento real autorizado; snapshot sempre account_verified:false, mesmo com ID observado. Profile/partition/PID/tab/doc/model não provam conta. Ausência de cartão não prova idle: approval_state null. Menu desmontado/oculto depois de Escape não fornece seleção atual suficiente ao snapshot. Host ainda não oferece attestor assistant independente homologado para message/parent/body SHA/revision. Nenhum fixture foi promovido a prova de conta, build instalado ou homologação Web real.

Estado explícito para revisão do coordenador: **native collector role UNKNOWN**, `approval_state:null`, `account_verified:false`, menu oculto ⇒ `selection_verified:false`/model/effort null, **assistant host proof missing**. O snapshot de identidade não atesta role user/assistant; seu role ausente/desconhecido não pode ser promovido a assistant. A observação de message/parent pelo Worker e o callback sintético dos testes não suprem essa prova independente. Todos esses valores mantêm o gate fechado, inclusive com rota HTTP saudável.

O 503 crítico e o health 200 na porta17842 são estados operacionais informados pelo coordenador; health 200 não prova build ativo, conta, seleção, receipt ou ANSWERED. Esta frente não executou restart, atualização de payload ou operação nos serviços existentes.

Contrato exato de wire/calibração está no relatório CURRENT. Account attestor deve juntar requested_model/effort da intenção original protegida, autenticar conta/collector/build/approval e comparar seleção física. Assistant attestor deve confirmar binding observado independentemente. Activation validator não pode aprovar por booleanos de modelo/HTTP/fixture. Esses gates impedem declarar missão de produção complete.

## Canvas e Compact&Resume

Dialog utiliza `/api/center/web-delivery` e `/api/center/goal-loop` autenticados e vinculados ao workspace. Mensagens exibem estados centrais; UNCONFIRMED exige reconciliação e não oferece resend. Model state ausente/ilegível permanece UNKNOWN. A projeção backend atual não devolve model/effort no status: UI mostra Indisponível; coordenador pode projetar seleção observada/solicitada com proveniência explícita, sem atribuir verificação à escolha solicitada.

Goal set/start/stop/status usam IDs centrais; Start exige limites finitos explícitos e não envia operator_approved. Sem grant retorna bloqueio central exibido, mesmo quando refresh recupera Goal ACTIVE. Custo ausente permanece Indisponível. Nenhum Run/WorkItem/grant é criado pela UI.

Compact&Resume utiliza POST `/api/center/compact-resume` com prepare/status/resume e arguments allowlisted. Formulário informa chat/WorkItem/principal EXISTENTES, request_key estável, resumo revisado com preview literal e target_url opcional. Checkbox local não é prova backend nem viaja no request. Cursor opcional backend não é editado nesta UI. Inspector recebe allocation_id OU continuation_id real; mostra estado/checkpoint/motivo e não fabrica ready. Resume exige estado central com conta/collector/receipt confirmados e backend revalida. ACK de prepare perdido não produz retry automático.

## Verificação auditável

| Verificação | Resultado final | Alcance / limite |
|---|---|---|
| Preparo limpo + allowlist + patch apply | PASS | Commit a13cd09950969f43e3b7e25c71fa43efaf5446c5; upstream puro, 41 caminhos |
| Typecheck upstream `tsc --noEmit` | PASS | Bun 1.4.0, dependências locais, source patched temporário |
| Build runtime completo upstream | PASS duas árvores | CLI/helper/runtime/licenses; não instalado |
| Reprodutibilidade CLI + helper | PASS | SHA iguais em duas árvores independentes |
| Worker/Host/DOM/Bun próprios | **18 PASS, 82 expectations** | Chromium isolado, produção sendAttachedPrompt/reader/handshake/control HTTP; provider DOM e seleção de teste controlados |
| Worker → Gateway real temporário → SQLite | PASS | Uma Run, uma Operation, um job/fence, receipt user + assistant partial/final/revisão2; prompt protegido |
| React → Vite → Canvas HTTP real → SQLite | PASS | Delivery UNCONFIRMED sem replay; Goal set/Start negado/Stop; Compact prepare bloqueado, status WAITING_RECEIPT e resume backend bloqueado |
| Estado Canvas Node próprio | 2 PASS | Limites finitos, estado incerto, sem booleans de aprovação |
| Electron processo real isolado | 3 PASS | Production main.cjs, perfil QA temporário, sessão não persistente, sandbox/contextIsolation, sem Node renderer e popup negado |
| React build Vite após Compact | PASS | 2147 módulos; artefatos apenas em Temp; warnings existentes classic scripts/chunk grande |
| Regressões Bun ampliadas | 145 PASS / 19 FAIL | Mesmos 19 FAIL na baseline reconstruída sem adições desta frente |
| Regressões Node launcher ampliadas | 118 PASS / 3 FAIL | Mesmos 3 FAIL na baseline reconstruída |

Testes Worker chamam o método físico de produção com Enter real no DOM isolado; activeComposer e espera de aceitação são controlados no harness. HTTP Gateway, ControlPlane, grants/leases/fences/SQLite/cripto são implementações reais em diretórios temporários. Account/assistant/rollout callbacks são **exclusivamente fixtures**. Testes não representam login/receipt de conta real nem substituem homologação do runBrowserTurn completo em provider real.

Revalidação após as melhorias backend do coordenador: o comando pytest das duas integrações acima foi executado novamente com `SENTRA_BROWSER_QA_TREE=...\sentra-browser-v2-q5x87620`: **2 passed in 6.64s**. Inclui Compact&Resume prepare/status/resume com checkpoint real/owner API e negação de publicação sem prova. Proveniência candidata reconferida: typecheck/build passed, production_activated:false; log Worker 18 pass/0 fail/82 expectations; upstream puro continua sem mudanças. Essa revalidação não instala nem ativa candidato.

As regressões antigas incluem expectativas Codex Native2 versus SENTRA tunnel, mocks effort sem `.count()`, assertions/mocks de rotas fixed e launcher heartbeat/usage. Comparação realizada em cópia temporária com as novas inserções revertidas pontualmente pelo script `baseline-revert.py`, sem alterar checkout compartilhado/upstream. Idênticos nomes/contagens: nenhuma nova falha detectada nessa comparação. Não declaramos a suíte ampliada inteiramente green. Correções de testes upstream fora de patch_files não foram incorporadas à allowlist.

Tentativas iniciais falharam por timeout Bun padrão5s, assert de mock/teste e dependência launcher não ligada ao tree; corrigidas no harness/preparo. P1 ACK backend corrigido por sua frente. Resultados finais acima substituem essas tentativas, sem ocultar regressões/gates.

## Proveniência e reprodução da rodada anterior (2026-10-10)

Patch SHA256 `19fa989891f925eae88718524583a46e8ac3e93767cd3c01bbb8ee82c4daceba`.

CLI SHA256 `ca164ff1c12626bec908a643877ed3691a848b147e4c2629e1c32741b1d5f75c`.

Helper SHA256 `6e848ae952234aee5821ae7b69aa9adbef100eb49cc9d56db7718cb9fd2b5ed5`.

Árvores compiladas independentes `C:\Users\vitor\AppData\Local\Temp\sentra-browser-v2-l4vu012y` e `...\sentra-browser-v2-q5x87620`. A segunda contém `SENTRA_QA_PROVENANCE.json` com hashes/build/typecheck/production_activated:false e `worker-qa-final.log`. Logs regressão em `...\sentra-browser-baseline-tfu9p4dm\baseline-bun.log`, `baseline-node.log` e árvore candidata `launcher-regression.log`. Canvas build final em `...\sentra-canvas-durable-compact-build-20261010`. Artefatos temporários são candidatos de QA, não payload instalado.

```powershell
python integrations/codex_chatgpt_web/prepare_durable_qa.py --verify-build
# Definir abaixo o caminho impresso pelo comando anterior.
$env:SENTRA_BROWSER_QA_TREE='C:\Users\vitor\AppData\Local\Temp\sentra-browser-v2-q5x87620'
$env:SENTRA_QA_CHROMIUM="$env:LOCALAPPDATA\ms-playwright\chromium-1234\chrome-win64\chrome.exe"
& .\.sentra\toolchain\node_modules\bun\bin\bun.exe test --timeout 30000 tests/unit/sentra_cos_durable_browser_worker.test.ts
python -m pytest tests/unit/test_sentra_cos_durable_worker_gateway.py tests/unit/test_sentra_cos_durable_canvas_browser.py -q
node --test tests/unit/sentra_cos_durable_canvas.test.mjs
npm test --prefix sentra_electron
```

`git diff --check` do patch-text aponta context lines contendo um espaço (formato unified diff); não removê-los, pois são contexto válido. `git apply --check` e compilação são a verificação da fonte aplicada. Upstream `git status --porcelain` permaneceu vazio; manifest upstream.json sem diff.

Próxima decisão do coordenador: revisar candidato/contratos, resolver regressões antigas e preparar homologação específica de identidade/provider/assistant com autorização separada. Esta entrega não habilita durable_v2 em ambiente live.
