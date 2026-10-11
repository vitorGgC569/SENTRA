# SENTRA / Chat On Steroids — auditoria da rota ativa de envio Web (10/10/2026)

**Escopo:** inspeção de fontes do checkout atual via plugin SENTRA. Nenhuma mensagem Web enviada, conta/tokens alterados, processo reiniciado, grant elevado ou código de produção modificado. Não equivale à homologação E2E.

## Achado P0

A rota do SENTRA CLI em uso é `sentra_cli/client.py::_responses_stream` → POST `/v1/responses` → `sentra_model_gateway/gateway.py` → upstream `codex-chatgpt-web`/browser. `sentra_cli/agent.py::step_stream` bloqueia um novo turno se há provider call `uncertain`; `sentra_cli/repl.py::/resolve` exige decisão manual com evidência. Isso é um comportamento fail-closed correto, mas **não há correlator browser message-ID para a tentativa específica do CLI nessa rota**. O menu `/model` usa os modelos anunciados pelo Gateway; `/v1/models` possui fallback cache/valores genéricos, que não provam seletor/effort da sessão Web.

O SENTRA **já tem outra pilha**: `native_bridge/job_store.py` + `web_delivery.py` (SQLite/WAL, jobs protegidos DPAPI, lease/progress pré-Send e `sending`, recibo exato, estado não confirmado sem reenvio), `native_bridge/web_evidence_ingress.py` (request/message/document/epoch), `edge_extension/service-worker.js` + `content-script.js` (produtor/recibo). `native_bridge/continuation_web.py` e `sentra_executors/goal_loop.py` fornecem contratos locais adicionais. **Busca efetiva no checkout**: `sentra_cli/` e `sentra_model_gateway/` sem chamadas a `WebDeliveryJournal`, `WebContinuation` ou `web_delivery`; `sentra_canvas/service.py` sem uso de `WebContinuation` ou `BoundedGoalLoop`.

Lacunas de *composição central* ainda visíveis: `sentra_mcp/server.py` instancia `ToolPolicyProxy(request_observer=self._observe_mcp_request)`, mas não localiza `WebMCPMessageDispatchGuard`; `sentra_remote/browser_relay.py` sem `authenticated_control`. Falta comprovar producer V2 → relay V2 → receipt autenticado → mesmo Run/WorkItem/Operation → Canvas/CLI no browser real.

## Padrão Chat On Steroids verificado localmente

Checkout `third_party/chat-on-steroids/` no commit documentado em `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md`. `src/main/session/input.ts` possui outbox durável, mensagens por UUID, propriedade de transporte, estados e `sendAuthorizedAt` persistido **antes do clique Send**, `authorizeBrowserInput`, `acknowledgeBrowserInput` associado a conversa/message-ID, sem replay após autorização incerta. `start-input.ts` persiste a entrada antes de acordar browser/túnel. `goal.ts` persiste objetivos e switches por `conversationId`, com `setGoalObjectiveNow` esperando gravação durável e `moveGoalObjective` no handoff.

**Limite honesto:** nenhuma automação DOM pode prometer exatamente-uma-entrega confirmada em todos os casos. Depois de clique com ACK perdido, o resultado permanece `unconfirmed`; ausência de recibo não comprova não-envio. A melhoria é não perder o pedido, impedir repetição indevida e reconciliar com prova exata antes de retomar.

## Desenho de convergência (um único Control Plane)

1. **Admissão única:** CLI/Canvas/API criam um WebSendIntent/Outbox com `request_key` estável, owner, principal, Run/WorkItem/Operation, workspace, conversation identity e conta/epoch. Persistir **antes** da UI/browser; nunca enviar diretamente ao Gateway fora desse gate.
2. **Autoridade única de envio:** escolher e adaptar um produtor compatível com o navegador realmente usado (Codex Web GPT Electron e/ou extensão Edge). Não há garantia de que a extensão instalada no Edge observe automaticamente o WebView Electron. Antes do clique: fence + lease + grant + `sending` durável/ACK 200; no máximo um clique por intenção.
3. **Recibo:** validar no coletor confiável `request_id`, `message_id`, `conversation_id`, `identity_epoch`, document/worker, perfil, SHA do texto e estado de aprovação ChatGPT. Distinguir `QUEUED/READY/SENDING/UNCONFIRMED/SENT/ANSWERED` na UX. Sem prova, aguardar reconciliação; jamais retry automático se Send pode ter ocorrido.
4. **Continuidade:** conectar `WebContinuation` ao mesmo Run/WorkItem/contexto/objetivo, sem copiar grants nem executar tool effects novamente. Compact&Resume somente publica B após receipt e bind de identidade.
5. **Goal/Loop:** vincular CLI/Canvas ao `BoundedGoalLoop` + budget/deadline, objetivo e switches persistidos por conversa lógica; cada iteração exige autorização/WorkItem; `/goal`, `/loop`, stop/status/continue observáveis. Não ativar por padrão nem iniciar cobranças involuntárias.
6. **Modelo/conta:** o catálogo deve distinguir `advertised`, `observed` e `verified`; a seleção explícita valida conta/perfil e seletor no instante do envio. `auto` usa o default observado sem afirmar GPT-6 High; troca de conta invalida a confirmação anterior.

## Critérios mínimos de aceite

- 1 envio completo na conta Web autorizada: outbox intent → ACK pré-Send → browser `message_id` real → resposta → journal/Run/WorkItem, sem ID inventado.
- Perda de ACK pós-Send, reload, crash, duas abas, navegador fechado, card de aprovação humana, troca de perfil/conta: zero reenvio incerto, reconciliação só com evidência; estados distinguíveis no Canvas e CLI.
- `/goal` persistido através de restart, handoff A→B e parada humana; worker/Run mantidos, budgets respeitados.
- Prova de políticas MCP por conversa: origem V2/epoch compatível no ToolPolicyProxy, deny para identidade desconhecida sem privilégio implícito.
- Testes de contrato + integração contra SQLite/HTTP reais + E2E no Codex Web GPT e Edge + build do launcher, sem reutilizar fixture como prova de browser.
- Não reprocessar mensagens antigas pendentes da sessão do usuário automaticamente. Nenhuma alteração de modo de processo, OAuth ou grants nessa migração.

**Situação:** esta é uma decisão de integração e um diagnóstico do caminho ativo; a migração de transporte e o aceite E2E **não foram executados** nesta auditoria.
