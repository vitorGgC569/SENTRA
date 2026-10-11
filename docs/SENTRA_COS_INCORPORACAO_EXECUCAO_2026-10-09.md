# SENTRA × Chat On Steroids — registro operacional de incorporação

**Data:** 2026-10-09. Fonte pinada `third_party/chat-on-steroids`, commit `151e7ef96bc16bf594ffbd35efe620e4ef6e4c2c`. O plano-base é `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md`.

**Regra de aceite:** COPIADO/CRIADO não equivale a integrado; INTEGRADO não equivale a testado; TESTADO em isolamento não equivale a homologado no instalador. A autoridade sobre Run, WorkItem, Machine, grants, operações e efeitos continua em `sentra_mcp/services/control_plane.py`. Nunca mover esse núcleo para Electron/Node.

## Implementado neste checkout (com código efetivamente ligado ao SENTRA)

| Capacidade | Integração real | Limite explícito |
| --- | --- | --- |
| Filtro durável de confiança/bloqueio por conversa | `sentra_mcp/services/chat_access.py`, namespace `chat_access` no `control_store.py`, serviço em `ControlPlaneService`, verificação de requisições em `ToolPolicyProxy`, endpoints Canvas autenticados e modal React | Sem produtor de prova DOM+request_id no Edge, a correlação permanece **não comprovada** na maioria das chamadas Web. O modo estrito opcional nega chamadas sem correlação; nunca afirmar que bloquear um chat basta para chamadas de origem desconhecida. |
| Políticas de chat no Canvas | `/api/center/chat-access`, `chat-access-dialog.jsx`, menu do Canvas atualizado | O painel declara explicitamente quando não há request IDs provados e não fornece grants. |
| Busca e exportação de conversas | Reutiliza `sentra_core/conversations.py::search_page` e `messages`; `Canvas.center_conversation_search`, `center_conversation_export`, rotas autenticadas, `conversation-search-dialog.jsx` | Somente o próprio principal/workspace, até 1000 mensagens e 2 MiB por export. Não implementa indexação FTS grande/Web turn streaming. |
| Evidência local de MCP/túnel | `sentra_remote/connector_proof.py`, observação pós-policy em `ToolPolicyProxy` e `SentraMCPServer`, integração no assistente desktop, GET Canvas e `plugin-status-dialog.jsx` | OBSERVAR uma chamada MCP não comprova que plugin foi criado, instalado ou atualizado na conta ChatGPT. Essa etapa fica explicitamente `unverified`. |
| Diagnósticos compartilháveis | `sentra_remote/diagnostics.py::shareable_report`; CLI padrão somente campos da allowlist, `--internal` para relatório privado de manutenção local | Não transmite automaticamente; usuário deve revisar a saída antes de compartilhar. |
| Pacotes MCPB importados sem execução | `sentra_mcp/services/plugin_bundles.py`, namespace `plugin_bundle`, anexado ao mesmo Control Plane; rotas autenticadas `/api/center/plugin-bundles`; `plugin-bundles-dialog.jsx` | Apenas staged/inactive. **Ainda falta** instalação de dependências, supervisão real do worker, health/restart, OAuth e ativação por grant/WorkItem/Operation; não anunciar plugin executável. |
| Frontend recompilado | `npm run build --prefix sentra_canvas/desktop_ui`, gera `static/desktop-assets` e manifesto SHA256 | Warning de bundle > 500 KB permanece; binário Windows/Setup/MSI novos ainda não gerados a partir desta incorporação. |

## Matriz integral dos 13 grupos inicialmente mapeados

| Grupo | Estado |
| --- | --- |
| P0 MCPB / gerenciamento completo de plugins | **PARCIAL:** ingestão segura inativa; falta ativação e OAuth com Control Plane |
| P0 catálogo real de modelos da conta | **BASE PREEXISTENTE:** /model e Canvas; observação da conta Web/caso Automatic ainda pendentes |
| P0 Compact & Resume A→B transacional | **PENDENTE:** não foi incorporado |
| P0 Outbox/recibos exatos de mensagens Web | **PENDENTE:** journals de operações já existiam, falta correlação de entrega Web |
| P1 Goal/Loop e workers | **BASE PREEXISTENTE/PARCIAL:** controle de agentes do SENTRA; revisão CoS não implantada |
| P1 exec_command/write_stdin em terminal durável | **BASE PREEXISTENTE/PARCIAL:** ConPTY e executor presentes; paridade de streaming não implementada |
| P1 Skills SKILL.md versionadas | **PENDENTE** de importador/revisão no centro |
| P1 API local leitura/ações opt-in | **BASE PREEXISTENTE/PARCIAL:** broker Canvas autenticado; diferença de consentimento por ação não portada |
| P1 Setup/Doctor/repair | **PARCIAL:** prova local MCP e status plugin no Canvas; fluxo da conta externa não automatizado |
| P1 editor CodeMirror/PDF/diffs | **PENDENTE** de integração ao Canvas |
| P2 command allowlist parser | **BASE PREEXISTENTE:** policy SENTRA, parser CoS não portado |
| P2 browser/extension observations | **PENDENTE:** estado Edge existente; request_id ChatGPT ainda não capturado |
| P2 acessibilidade, docks, UX | **BASE PREEXISTENTE/PARCIAL:** React Flow/Radix; novas telas compactas; aceitação DPI/teclado pendente |

## Matriz das 21 subfrentes identificadas na segunda auditoria

| Identificador | Estado atual |
| --- | --- |
| A01 correlação exata x-request-id→chat | **PARCIAL**: tabela e API interna duráveis; sem fonte autenticada do modelo da página |
| A02 bloqueio por chat | **PARCIAL**: filtro MCP e UI ativos sobre correlações comprovadas; sem garantia sobre chamadas anônimas |
| A03 confiança de chat/default-deny | **PARCIAL**: persistência, revision/fencing, UI e strict mode; associação real de requests pendente |
| A04 cartão de aprovação pendente ChatGPT | **PENDENTE** |
| A05 provas MCP/túnel/plugin | **PARCIAL**: chamadas MCP e túnel; prova de plugin instalado na conta pendente |
| A06 schema refresh no ChatGPT | **PENDENTE** |
| A07 MCP surfaces discovery separadas | **BASE PREEXISTENTE/PARCIAL**, sem publicação dinâmica por superfície completa |
| A08 Code Mode QuickJS WASM | **PENDENTE** |
| A09 browser/extension installed + signed-in proof | **PENDENTE** |
| A10 API leitura/ação opt-in | **BASE PREEXISTENTE/PARCIAL** |
| A11 busca textual entre conversas | **INTEGRADO** para conversas SENTRA CLI protegidas; não Web externo |
| A12 anexos de mensagens Web | **PENDENTE** |
| A13 streaming Web por message_id | **PENDENTE**; ConversationStore protegido preexistente |
| A14 uso/quota Web observado | **PENDENTE**; ledger financeiro SENTRA preexistente |
| A15 export diagnóstico anonimizado | **INTEGRADO** no CLI de diagnóstico |
| A16 resumo de evidências das tool calls | **BASE PREEXISTENTE/PARCIAL**; nova projeção uniforme pendente |
| A17 GC/ownership de processos de worker | **PENDENTE** de comparação e política |
| A18 Git/diff watch com revisão | **BASE PREEXISTENTE/PARCIAL**; painel live changes pendente |
| A19 updater staged e schema coordinated | **BASE PREEXISTENTE/PARCIAL**; coordenação de plugin/extensão pendente |
| A20 Markdown export de conversas | **INTEGRADO** para sessões CLI até o limite; UI Canvas |
| A21 Git pinned Skills catalog | **PENDENTE** |

## Próximas implementações obrigatórias, antes de declarar absorção integral

1. **Correlação verificável no Edge**: portar coleta restrita de `metadata.request_id` do CoS, com identidade exata e proteção contra DOM desatualizado, transporte assinado da extensão e admissão central. Só então bloqueios por chat poderão afetar chamadas reais e ser homologados.
2. **Ciclo MCPB completo**: registrar/descobrir tools/manifesto, supervisionar execução isolada via PluginWorkerHost sob grant real do SENTRA, no-repeat no ponto de efeito, OAuth, restart, revogar, remover e atualizar.
3. **Continuidade transacional e mensagens Web**: A→B com commit/recovery, outbox com receipts, imagens/anexos por artifact, streaming Web canônico, proteção de contexto, perda de resposta e duas abas simultâneas.
4. **Plugins e Modelos na conta real**: refresh de schema e provas externas, catálogo/effort observado, aprovação humana aguardando, limites de uso Web separados do consumo SENTRA.
5. **Produtividade**: Code Mode WASM limitado, Skills Git por SHA, Git diff/watch, preview PDF/editor, search Web, GC de workers, resumos tool calls, atualização coordenada.
6. **QA de produto**: full tests, WebView2 instalado, extensões sob consentimento, plugin autenticado pelo usuário, MSI/Setup assinado, primeira instalação/desinstalação limpa.

## Não incorporar automaticamente

- Cópia de cookies, perfis ou segredos da sessão ChatGPT; gravação irrestrita de tela/conversa;
- O Electron do CoS como segundo Canvas;
- Shell irrestrito ou avaliação JS no processo privilegiado;
- Adivinhar ownership de chat por timestamp, nome de ferramenta ou aba ativa;
- Permissão de acesso ao usuário/computador a partir de um status "trusted".

**Estado:** incorporação **parcial e rastreada**, sem promessas de equivalência que não tenham evidência. Alterações permanecem no checkout de trabalho; não houve publicação de release, troca do aplicativo em execução nem commit/push.

## Atualização de QA nesta rodada

- Host existente `sentra_mcp/services/plugin_host.py::_method_descriptors` endurecido: no máximo **256 métodos**, rejeição de nomes conflitantes sem distinção de caixa, antes de publicar um worker como VERIFIED. Testes em `test_sentra_cos_plugin_namespace.py`: 3 aprovados.
- Testes de Canvas na janela nativa: os mocks antigos não ofereciam o evento `window.events.shown` recém utilizado pelo ícone oficial; fixtures de `test_native_app.py` e `test_sentra_canvas_broker.py` foram atualizadas com fake explícito de registro de evento e verificação de callback (ambos os testes corrigidos aprovaram). Isso não altera o código de produção da janela.
- Testes focados: núcleo MCP e onboarding 41/41; Control Plane/HTTP de conversas e provas 7/7; MCPB e integração Canvas 10/10; colaboradores Node 54/54; build Vite/React concluído. `git diff --check`: exit 0, avisos de normalização CRLF/LF.
- Uma suíte completa `pytest tests/unit` foi iniciada enquanto as fixtures de WebView2 ainda estavam antigas; portanto **o resultado desta primeira execução não deverá ser registrado como green sem uma reexecução posterior com as fixtures atualizadas**. A atualização das fixtures não remove os novos testes de segurança nem a obrigação de corrigir outras possíveis falhas.
- A entrega continua **parcial**: o importador MCPB não executa ou registra ferramentas de forma autônoma; correlação no ChatGPT Web, autenticação por chat, OAuth e o restante da matriz ainda dependem de fatias reais e E2E.

## Resultados finais do ciclo de validacao de 09/10/2026

**Reexecucao integral de todas as unidades sobre o codigo atualizado: 1.991 passed, 37 skipped, 0 failures, 0 errors, 14 subtests passed, 1 warning**, tempo **487,55 s** (comando: `python -B -m pytest -q -p no:cacheprovider tests/unit --disable-warnings --tb=short`). Isso inclui os mocks do evento `shown` da janela WebView2 devidamente atualizados. A primeira corrida havia concluido com 1.986 passed e duas falhas de fixtures, ambas reparadas antes da segunda execucao. **Duas assercoes de seguranca MCP adicionais foram criadas apos a coleta da segunda corrida** e passaram no teste focado, portanto nao inflar a contagem de 1.991.

- `tests/failure tests/integration`: **183 passed, 10 skipped**, 151,40 s.
- `npm test --prefix sentra_collab`: **54 passed / 0 failed**.
- Regressao focada CoS/Canvas/MCPB/plugin namespace/WebView2: **30 passed**; testes adicionais de filtro por request_id: **7 passed** no modulo completo.
- Build frontend `npm run build --prefix sentra_canvas/desktop_ui`: exit 0, 2.139 modules transformed, SHA256 do bundle atualizado; warnings de scripts legados e tamanho do bundle, sem erro fatal.
- `git diff --check`: exit 0, apenas avisos de normalizacao CRLF/LF; checkout third_party/chat-on-steroids permanece limpo em `151e7ef`.

**Aceite correto:** testes verdes demonstram a seguranca e estabilidade destas fatias locais. NAO demonstram incorporacao completa de 34 frentes/subfrentes, assinatura do instalador, atualizacao de plugin em conta externa, web correlation autenticada, remotos ou E2E Windows com uma instalacao nova. Nenhum dos itens pendentes da matriz foi promovido indevidamente a implementado.

## Fatia adicional: continuidade transacional local A→B

**Arquivos alterados:** `sentra_mcp/services/session_checkpoint.py` (tabela
`session_continuations`, idempotência e transições), `sentra_mcp/services/control_plane.py`
(métodos `prepare_chat_continuation`, `commit_chat_continuation`,
`reconcile_chat_continuation`, `cancel_chat_continuation`),
`sentra_mcp/services/durable.py` (CAS opcional
`expected_conversation_id` no rebind), e
`tests/unit/test_sentra_cos_continuation.py`.

A transferência preserva o mesmo Run, Chat lógico, Agent e checkpoint; uma
requisição simultânea é rejeitada por índice único parcial persistente.
O commit local exige aprovação explícita e revalida a revisão do checkpoint.
O rebind usa compare-and-swap da conversa anterior. Em falha entre os
SQLite, `REBINDING` ou `UNCERTAIN` são reconciliados pela identidade
durável real, **sem retransmitir mensagens ou reexecutar operações**.
Após reinício, estado indeterminado permanece bloqueado até conciliação;
reproduzir request_key nunca causa novo rebind.

**Limite:** o commit altera exclusivamente o vínculo local do Chat lógico no
DurableRunService. Não inicia uma conversa no navegador, não observa cartão
de aprovação humano, não envia o checkpoint ao ChatGPT e não confirma
prontidão da conta. O retorno explicita `remote_target_attested=False`.
Falta o produtor verificado de identidade Web e a integração no Canvas.
Não promover Compact & Resume ao estado INTEGRADO integral nesta matriz.

**QA deste incremento:** 23 testes direcionados passaram (governança,
continuação, política por chat e journal de handoff), 0 falhas; `git diff
--check` exit 0, com avisos CRLF/LF da árvore já modificada. Essa
contagem não substitui a reexecução da suíte integral após todos os
incrementos.

## Fatia adicional: assinatura do catálogo MCP efetivamente registrado

`sentra_mcp/server.py` agora calcula SHA-256 canônico da lista do SDK
após `_register_tools`, incluindo nomes e esquemas de entrada/saída,
sem publicar parâmetros secretos. `ConnectorProof.record_local_schema`
persiste a assinatura por identidade de túnel e superfície. Quando ocorre
uma chamada **autenticada** observada no servidor, grava a assinatura
local correspondente. Uma mudança posterior é exposta como
`local_schema_changed_since_authenticated_call=True`, e não como prova
de sincronização remota. Chamadas não autenticadas não zeram o alerta;
mudança de túnel isola evidências antigas.

O painel `plugin-status-dialog.jsx` passou a mostrar o total de métodos
publicados e um prefixo de SHA-256, com aviso de mudança do catálogo.
`plugin_installed_in_chatgpt` e `schema_current_in_chatgpt` permanecem
explicitamente **unverified**; não existe leitura comprovada do cache de
schemas do ChatGPT nesta fatia.

**QA:** 43 testes dirigidos de segurança/continuidade/governança passaram;
outros 13 testes de Canvas HTTP, MCPB e namespace de plugin passaram.
Build React/Vite: 2.139 módulos, exit 0 e assets materializados.
Persistem warnings pré-existentes de scripts não-modulares e chunk
desktop.js >500 kB. A homologação E2E do refresh na conta ChatGPT permanece
pendente.
