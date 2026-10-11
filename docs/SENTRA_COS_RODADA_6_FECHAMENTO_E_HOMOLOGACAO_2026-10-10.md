# SENTRA — RODADA 6: fechamento integral CoS, integração e homologação

**Data:** 2026-10-10; coordenação nesta conversa. **Objetivo real:** fechar tecnicamente todas as lacunas G01–G13 + A01–A21 do `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md` e verificar entrega no produto Windows. Não basta elaborar adapters, relatórios ou subir teste mock. Não declarar "34/34 homologado" sem E2E remoto, binaries atuais, assinatura legítima e instalação limpa provada. A tarefa dos agentes é implementar, testar e entregar contratos importáveis ao núcleo; os bloqueios externos/operador devem continuar explicitamente identificados.

**Fonte vigente:** `docs/SENTRA_AUDITORIA_RETORNOS_R5_CODEX_2026-10-10.md`, `docs/SENTRA_COS_RODADA_5_INTEGRACAO_CENTRAL_2026-10-10.md`, `docs/SENTRA_COS_SETE_FRENTES_2026-10-10.md` e os seis `docs/SENTRA_COS_AGENT_N_2026-10-10.md`. A pesquisa `C:\Users\vitor\OneDrive\Desktop\SENTRA_RESEARCH_OPENDOTS\SENTRA_OPEN_DOTS_RESEARCH.md` é **somente referencial**, não permissão para importar um backend paralelo ou código não auditado. Priorize fechamento CoS em vez de novas funcionalidades OpenDots.

**Estado de dispatch:** 15h42 BRT, o Edge mostra **Chats 1–5 gerando, Chat 6 livre**. NÃO interromper nem enviar prompt aos 1–5 até ficarem ociosos. O sétimo executor é o Codex implementador ToolPolicy, além dos seis chats; o pesquisador OpenDots já entregou e NÃO é executor de código. A sétima frente de arquitetura/coordenador continua sendo esta conversa.

## Regras de segurança e repositório

Checkout compartilhado `C:\Users\vitor\OneDrive\Desktop\SENTRA`, 243 mudanças no `git status --short` na inspeção; nunca executar reset/checkout/stash/clean globais, commit/push global ou sobrescrever arquivos de outros agentes. Cada chat escreve EXCLUSIVAMENTE no escopo herdado; mensagens e efeitos Web `UNCERTAIN` nunca são reemitidos sem prova de ausência e nova autorização. Nunca ler cookies, tokens de conta ChatGPT, credenciais ou certificados de terceiros. Não inferir Free/Plus, modelo ou effort de DOM ou túnel. Antes de ligar efeitos, provar host-owner consent e mesmo SQLite ControlPlane/Run/WorkItem/Operation/grants e observabilidade. Não desligar gates para passar testes.

A instalação é **mais perigosa** que os testes: não substituir `dist/`, registrar instalador, instalar/desinstalar, parar serviços ou alterar banco real enquanto há seis agentes ativos; Chat 6 só pode empacotar/homologar após congelamento coordenado, QA em VM descartável e condições de assinatura atendidas. Código em `tmp_path`, subprocessos efêmeros e regressão hermética liberados dentro de seus escopos.

## Agente 1 — MCPB/Skills (Chat original 1)

**Somente** `sentra_mcp/services/{plugin_bundles,plugin_host,tool_exposure,skill_library,mcpb_http,mcpb_offline,mcpb_oauth,mcpb_oauth_callback,mcpb_orphans}.py`, `sentra_interop/` e testes próprios. Chat 1 concluiu recuperação de container STOPPED pelo ID/labels com Ledger/grant/click, e `confirm_uncertain_absence` que apenas inspeciona após crash, além de OAuth2 loopback/PKCE, MCP HTTP sessions, worker restart e purge parcial. NÃO refazer.
**Fechamento exigido:** esquema único de lifecycle MCPB (stage→inspect→approved enable→workitem-bound schema/tool exposure→OAuth callback state/CSRF/refresh/revoke→worker real health/restart→disable/uninstall→cleanup físico por ID); testes de falha em TODAS as transições/SQLite e controles owner/grant; server session GET/Last-Event-ID/DELETE e dependências wheel offline no mesmo Docker job sem egress. **Entrega de handoff** contendo método exato a integrar em `mcpb_sandbox.py` (reservado ao coordenador) e publicação de esquema na conta externa somente quando houver consentimento e cliente real. Atualize `docs/SENTRA_COS_AGENT_1_2026-10-10.md`. Sem ler conta real por atalho, sem backend paralelo.

## Agente 2 — extensão/conta/ChatTrust (Chat original 2)

**Somente** `edge_extension/`, `browser/`, `sentra_mcp/services/{browser_evidence,chat_access,web_account_dispatch}.py`, testes. Não editar native_bridge/relay, server/tool_policy, ControlPlane/Canvas.
**Fechamento exigido:** produtor MV3 do MESMO build/worker/doc/identity_epoch source SHA, request_id/message_id host bound, guard host-only importável; revogar perfil global em logout/troca, bloquear approval pending, evidenciar mensagem sem DOM como conta, comprovar HTTP real para relay V2, reinício/logout, ACK perdido e no duplicate Web. Reconciliar schema com Chat3 sem editar arquivos dele; TESTAR extensão real no Edge pareado apenas sob autorização, sem capturar cookies nem assumindo plano/effort. Source manifest hash estampado DEPOIS das mudanças. Atualize `docs/SENTRA_COS_AGENT_2_2026-10-10.md`.

## Agente 3 — relay/continuidade Web A→B (Chat original 3)

**Somente** `native_bridge/`, `sentra_mcp/services/{session_checkpoint,web_history_store,web_history_assets,web_history_usage}.py`, testes. Fábrica `sentra_remote/browser_relay.py` é do coordenador; não editar extensão/server/Canvas/sentra_executors.
**Fechamento exigido:** pipeline completo de recibo V2 `challenge→observe→phase sending→delivery-receipt→attest/reconcile→WebContinuation.commit→claim_new_target`, mesmo Run/WorkItem/grant, ciphertext local, zero reenvio UNCERTAIN, crash por fase e idempotência após nova autorização, target grant original e importação de frames/attachments só com evidência da conta/worker. Provar HTTP loopback/SQLite REAL com `authenticated_control` injetado; entregar o contrato ao coordenador para factory e integração no produto. ChatGPT A→B externo só com conta atestada e consentimento do owner; se impossível, registrar bloqueio e NÃO fingir E2E. Atualize relatório 3.

## Agente 4 — Code Mode/ActionConsent/GoalLoop/ConPTY (Chat original 4)

**Somente** `sentra_mcp/services/action_consent_gate.py`, `sentra_code_mode/`, `sentra_executors/`, testes. Não editar central/Canvas/relay/extension/release.
**Fechamento exigido:** contratos host-only de DOIS cliques com `HostOwnerClickAuthenticator`, sessão real/Origin/CSRF, nonce/TTL/consume-once e revogação; API read/action, `ExistingConPTYSession` start/write/read/close fenced por Operation (sem terminal paralelo/GC PID-only), custo real reconciliável além de reserva host-priced, cancel/restart e receipt. Fornecer testes de HTTP owner-auth por contrato sem editar Canvas; entregar métodos para coordenador. **QuickJS WASM deve continuar DESABILITADO** se não houver engine auditado, limits CPU/memory/fuel, no host I/O e SBOM; não usar eval/Node fallback. Atualize relatório 4.

## Agente 5 — Canvas PDF/UX (Chat original 5)

**Somente** `sentra_canvas/project_review.py`, `sentra_canvas/desktop_ui/src/`, CSS/tests UI; não editar `sentra_canvas/{service.py,__main__.py,task_runtime.py}` que pertencem ao coordenador.
**Fechamento exigido:** usar rota de PDF visual GET owner-auth JÁ integrada, garantir 401/403 no fallback deny, 503 do PDFium indisponível, formato PNG/SHA/paginação rigoroso, DOM React/Chromium→HTTP real→SQLite e QA watcher revisions, ARIA/teclado/focus/docks em DPI virtual; documentos suspeitos sempre só read-only. Fallback HTTP 500 é falha de backend reservada ao coordenador: entregar teste para 503 e não alterar handler. WebView2 instalado e DPI físico 125/150 continuam QA final. Rebuild Vite apenas para outDir isolado enquanto seis agentes trabalham. Handoff wheel pypdfium2 pin e UX pronta ao release. Atualize relatório 5.

## Agente 6 — Instalador/CI/Doctor/Updater (Chat original 6)

**Somente** `sentra_remote/` EXCETO `browser_relay.py` (coordenador), `sentra_electron/`, `scripts/commander/`, `.github/workflows/`, testes e doc release. NÃO editar Canvas central/server/extension/native_bridge/MCPB.
**Fechamento exigido:** inventário completo de app/CLI/Canvas/WebModels/extension/MCPB/Skills/PDFium, hashes SBOM/provenance, offline pinned wheel, Doctor+repair owner-host approval, upgrade SQLite staged+WAL crash/restart, rollback, uninstall ownership, CI actionlint/release gate; teste hermético de primeira instalação/atualização/remoção e scripts de VM descartável. **Não gerar nem instalar binários agora**: espere freeze coordenado. Quando congelado e VM disponível, gerar Setup+MSI contemporâneos, rodar first install/upgrade/rollback e Authenticode SOMENTE com certificado real. Reportar blockers por item sem alegar assinatura quando não houver. Atualize relatório 6.

## Agente 7 EXTRA — Codex ToolPolicy (`gpt-6.1-sol`, high)

A sessão antiga `sentra_codex_implement.log` falhou antes de abrir arquivos por `helper_unknown_error: setup refresh had errors` e `MCP tool call requires approval, but approval policy is never`; zero código, não fingir executor ativo. Proprietário do Codex: `sentra_mcp/server.py`, `sentra_mcp/tool_policy.py`, testes NOVOS `tests/unit/test_sentra_cos_toolpolicy_codex_*.py`, relatório `docs/SENTRA_COS_CODEX_TOOLPOLICY_2026-10-10.md`. Não editar outros arquivos. Prioridade única: compor `WebMCPMessageDispatchGuard.tool_observer` de Chat2 com observador diagnóstico preexistente em `ToolPolicyProxy` de TODA ferramenta com evento host-verificado, perfil/doc/epoch/request/message, Run/WorkItem/Grant e deny de unknown/browser; preservar clientes locais autorizados e testes de HTTP real/SQLite. Primeiro restabelecer acesso a ferramentas e reproduzir teste; se continuar bloqueado, entregar erro e NÃO alegar que integraram ToolPolicy. Sem escalonar privilégios/grants nem afrouxar política de approval para prosseguir.

## Coordenador (ESTA conversa) — sétima frente arquitetural, não o Codex

Arquivos exclusivos: `sentra_remote/browser_relay.py`, `sentra_mcp/services/{control_plane,mcpb_sandbox}.py`, `sentra_canvas/{service.py,__main__.py,task_runtime.py}`, testes centrais. Não editar `sentra_mcp/server.py` ou `tool_policy.py` enquanto agente Codex reivindicar. Integrar factory relay `authenticated_control=control` com same store e lifecycle; substituir cleanup Docker unsafe por ledger ownership safe; GET PDF visual mapping 503 específico, implementar endpoints host-only two-click + ConPTY/cost receipt, conectar releases/doctor por plano seguro, revisar 34 critérios e cross-suite. Não construir uma fonte paralela de autoridade.

## Homologação final e critérios de pronto

1. **Prova integrada do caminho real** — extensão identificada → relay V2 doc/epoch → MCP ToolPolicy observer → Run/WorkItem/Operation/Grant → A→B e recibo autenticado sem reenvio UNCERTAIN; client ChatGPT Plus, account/model/effort somente com prova do provedor/usuário.
2. **MCPB/Skills** — stage/enable/disable, sandbox real image pinned/ledger, OAuth callback/grants/session, processo supervisionado, wheel na sandbox, reconciliação crash e tombstones/uninstall, refresh real do cliente quando autorizado.
3. **Canvas e host** — dois consentimentos humanos que geram tickets distintos, ConPTY/Goals fenced, PDF PNG owner-auth com 503/fallback, UX com testes Chromium/Node e diagnóstico redigido; QuickJS somente se engine homologado, senão requisito A08 fica **PENDENTE**.
4. **Distribuição** — freeze, testes Python integral/Node/Chromium/CI, builds atuais, Setup/MSI, VM Windows primeiro uso/rollback/uninstall, assinatura legítima e proveniência/SBOM.
5. **Evidência e sign-off** — tabela G01–G13/A01–A21 com linha por item: arquivos, testes, recepção cliente real (quando exigido), install VM, blocker, aprovado/não aprovado. Proibido marcar cobertura 34/34 por mock/local apenas. Nenhum commit/push global ou deploy sem autorização do proprietário.

## Mensagens e interação entre chats

Enviar este documento como ordem de trabalho para todos os seis chats originais **somente quando não houver resposta em andamento**. Cada chat também atualiza o próprio relatório e marca método pronto/handoff específico. Mensagens ChatGPT/Edge at-most-once; em erro de clique ou confirmação incerta NÃO reenviar. A coordenação deve verificar os seis históricos /c originais e não abrir chats novos.


## Despacho automatizado — tentativa de 10/10/2026, 15h47 BRT

- **Chat 6:** já tinha recebido `[SENTRA R6 FECHAMENTO CHAT 6]` e sido confirmado anteriormente (`SENT_RENDERED`); **não reenviado**.
- **Chats 1 a 5:** nenhuma nova entrega confirmada nesta tentativa. Na última inspeção anterior, às 15h42 BRT, os cinco ainda estavam respondendo. O estado atual não foi confirmado.
- O comando destinado a executar **uma vez por chat** o script existente `sentra_r6_one_shot.py` foi **bloqueado pelos controles de segurança da ferramenta antes de executar**. Não foi feita tentativa alternativa, não houve clique em Enviar e nenhum chat foi interrompido.
- **Situação:** despacho pendente por bloqueio de ferramenta; requer inspeção e envio manual seguro no Edge ou uma autorização/fluxo de automação permitido. Não reexecutar automaticamente essa mesma ação por outro caminho. Nenhuma homologação decorre desta tentativa.

## Despacho e implementação confirmados nesta conversa (~15h50 BRT)

- A **Rodada 6 CHAT 6** foi publicada uma única vez na conversa original `/c/6aca4034-6014-83e8-ae48-bd4a68dcdd36` (`SENT_RENDERED`, 436 caracteres). Não reiniciar build/instalador até freeze/VM.
- A **Rodada 6 CHAT 1** foi publicada uma única vez na conversa original `/c/6aca2883-cba4-83e9-a371-cf7eef1cb959` (`SENT_RENDERED`, 437 caracteres).
- Os **Chats 2, 3, 4 e 5** permaneciam com botão Parar/geração ativa na inspeção, receberam `BUSY_NO_SEND`, sem envio ou interrupção. Foi criada verificação condicional horária para entregar a missão R6 apenas quando cada conversa encerrar, com comparação do marcador e recusa de clique incerto; não duplicar.
- **Codex implementador R6**: uma nova sessão `gpt-6.1-sol`, effort `high`, sandbox `workspace-write` foi realmente lançada, log `%LOCALAPPDATA%\Temp\sentra_codex_toolpolicy_r6.log`. Repetiu erro `helper_unknown_error: setup refresh had errors` ANTES de ler arquivos. **Nenhum código foi escrito ou testado por esse Codex**. A responsabilidade de `sentra_mcp/server.py` e `sentra_mcp/tool_policy.py` fica de fallback com o coordenador, APENAS após confirmar que não há processo Codex efetivamente trabalhando nesses arquivos; jamais ignorar gates/elevar approval para mascarar a falha.
- **Fatia implementada diretamente pelo coordenador**: `sentra_canvas/__main__.py` agora retorna HTTP **503** e `Cache-Control:no-store` pela infraestrutura existente quando apenas `pdf_visual` falha por ausência exata do PDFium ou `TimeoutError`. Outros `RuntimeError` continuam 500 e 401/403 mantêm negação. Novo teste em `tests/unit/test_sentra_cos_pdf_visual_center_integration.py` confirma os 503, 500 e 401, sem grants. Regressão `test_sentra_cos_pdf_visual_center_integration.py`, `test_sentra_cos_canvas_ux_http_r5.py`, `test_sentra_cos_canvas_http_integration.py`: **9 passed, 0 failed, exit 0, 9.50 s**; Python compile e `git diff --check` exit0.
- Automação diária de coordenação atualizada para esta Rodada 6; automação anterior isolada do Chat 1 desativada para evitar mensagens concorrentes. Nenhum reset/commit/push global, instalação, acesso a conta real ou repetição de efeito Web UNCERTAIN.

**Status:** 2 de 6 chats R6 receberam instruções de forma comprovada; 4 seguem ocupados; Codex 7 bloqueado por ferramenta, não homologado; trabalho central PDF 503 entregue com testes. Não alegar 34/34.

## Auditoria de retomada — 16h05, 10/10/2026 (Brasília)

**Estado conferido nas seis URLs originais do Edge: TODOS tinham botão Parar / geração em andamento**. Tags `[SENTRA R6 FECHAMENTO CHAT 1]` e `[SENTRA R6 FECHAMENTO CHAT 6]` já no histórico; Chats 2–5 ainda sem tag R6, mas estão ocupados e NÃO foram interrompidos. Nenhuma mensagem foi duplicada. Monitor de despacho `SENTRA — concluir despachos R6` ativado hourly condition_watch SOMENTE para Chats 2–5, com envio único confirmado quando cada um ficar livre. NÃO reenviar Chats 1 e 6.

**Relatório Chat 1 atualizado 16h03:** integra `MCPBWorkItemLifecycle` com registros e grants no mesmo Run/WorkItem, OAuth e MCP HTTP/vault, actions de sessão e refresh/revoke gateados e provas locais. Regressão declarada **68 passed, 1 skipped, 0 failed**. Pendente P0: `sentra_mcp/services/mcpb_sandbox.py` real usar mesmo contêiner de execução para wheels e ledger/cleanup físico por ID; OAuth/chat-client externo e UI owner-auth real não atestados. Handoff exato em `docs/SENTRA_COS_AGENT_1_2026-10-10.md`.

**Relatório Chat 6 atualizado 15h55:** `sentra_remote/wal_checkpoint.py` snapshot WAL read-only e crash-safe sem alterar DB em uso; staged migration/recovery journal, owner repair marker TOCTOU, pin PDFium 4.30.0, CI freeze/QA independente, MSI SHA gate e preflight smoke de VM. Regressão declarada **125 passed, 1 warning, zero failed**, Node Electron 2 passed, actionlint exit0; **não houve build de Setup/MSI, assinatura Authenticode, instalação VM nem migração do banco real**. Release permanece BLOCKED até freeze real, owner callback central, VM autorizada e certificado legítimo.

**Coordenação pendente:** `sentra_remote/browser_relay.py` continua sem `authenticated_control=control`; `sentra_mcp/server.py` ainda não compõe `WebMCPMessageDispatchGuard` no `ToolPolicyProxy` (Codex adicional travou por ferramenta). `mcpb_sandbox.py` ainda usa cleanup por nome/force. Associar à mesma store SQLite ControlPlane e testar Security/HTTP sem liberar default permissivo. Integrar ActionConsent/ConPTY host, API owner-auth; concluir QA Canvas PDF e release apenas sob aceite. Nenhuma das 34 entradas G/A será marcada homologada por testes locais somente.

**Risco de concorrência:** Chat 1 e Chat 6 ainda estavam na resposta em geração mesmo depois de escreverem relatórios R6; não disparar missões adicionais a esses chats até obter encerramento e reauditar. Chats 2–5 só receberão missões R6 por monitor at-most-once ao terminar. Nenhum reset/stash/clean/commit/push global e sem ler cookies/credenciais.
