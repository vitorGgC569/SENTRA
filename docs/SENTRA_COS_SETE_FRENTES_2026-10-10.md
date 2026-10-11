# SENTRA / CHAT ON STEROIDS — coordenação integral de 7 frentes (2026-10-10)

## Estado verificado e regras comuns

Checkout real: `C:\Users\vitor\OneDrive\Desktop\SENTRA`, Desktop Commander OGrandeOxta.
Autoridades existentes: `ControlPlaneService` / `AuthorizationService` / `DurableRunService` / `SQLiteControlPlaneStore` / `Canvas` / `TaskRuntime`. Não criar fonte paralela de Run/Grant/WorkItem/Operation nem novos processos fora das fronteiras físicas.
Auditorias: `docs/SENTRA_COS_AGENT_1_2026-10-10.md`, `_2_`, `_3_`, `docs/SENTRA_COS_RODADA_3_2026-10-10.md`. Testes locais cruzados da rodada 2: 126 passed. Novo código rodada 3 de MV3 `identity_epoch` **NÃO compatível** com schema HTTP V1 de `native_bridge/relay.py`; conectar e provar transporte real antes de alegar E2E. Nenhuma conta ChatGPT foi criptograficamente atestada e nenhum schema remoto foi aceito de ponta a ponta.
O Git está MUITO sujo com arquivos alterados pelos diversos agentes. NÃO reset/checkout/stash/clean/commit/push globais, não sobrepor trabalho dos outros agentes. Não acessar cookies, tokens de conta, certificados ou segredos. Nunca enviar prompt Web incerto novamente. Antes de editar, `git status --short`, ler os arquivos reais, evitar conflitos; manter relatórios de cada chat em `docs/SENTRA_COS_AGENT_N_2026-10-10.md`.
E2E exige executar o caminho central verdadeiro com SQLite, grants, operadores humanos, navegador Edge/ChatGPT real quando autorizado e instalador limpo; se recurso externo estiver indisponível, registrar bloqueio, não substituir por fixture e chamar homologado. Sem fechamento 34/34 a partir de testes unitários.

## Direitos de escrita exclusivos e entregas

### Chat 1 (existente) — MCPB + Skills
Principal: `sentra_mcp/services/plugin_bundles.py`, `plugin_host.py`, `tool_exposure.py`, `skill_library.py`, `mcpb_http.py`; `sentra_interop/mcp_http.py`, `mcp_stdio.py`, testes `test_sentra_cos_mcpb_*`, `test_sentra_cos_skill_*`.
Entregar OAuth2 Authorization Code + PKCE/refresh/revoke e vault seguro; MCP HTTP Streamable com sessão/event framing e SSRF fail-closed; lifecycle worker/lease/crash/health/restart, dependências offline pinadas, update/rollback/uninstall com safe purge; schema local seletivo. Reconciliação Docker via contrato com coordenador para `mcpb_sandbox.py` (NÃO EDITAR esse arquivo). Não fingir provedor autorizado no ChatGPT remoto. Handoff de APIs owner-auth e provas.
Relatório: `docs/SENTRA_COS_AGENT_1_2026-10-10.md`.

### Chat 2 (existente) — Conta e prova Web + MV3
Principal: `edge_extension/`, `browser/`, `sentra_mcp/services/browser_evidence.py`, `chat_access.py`, `web_account_dispatch.py` e testes `test_sentra_cos_chat2_*`. APENAS suporte de `action_consent_gate.py` sob acordo com Chat 4 (Chat 4 é dono desta API a partir de agora).
Dar schema oficial V2 `identity_epoch` a Chat 3: `challenge`, `observe`, `invalidate`; coordenação de documento+worker+build+generation e bloqueio imediato em logout/perfil incerto, sem confiar em DOM. Detectar conta/modelo/effort somente por prova independente; se indisponível, unknown/deny. Estender envelope de mensagem `metadata.request_id`, estado aprovação humana, lifecycle de tabs; testes JS MV3 e Python com SQLite, Chromium real somente com inspeção autorizada. NUNCA alterar `native_bridge/`, ControlPlane ou Canvas. Prova ponta a ponta requer teste Edge real além da fixture.
Relatório: `docs/SENTRA_COS_AGENT_2_2026-10-10.md`.

### Chat 3 (existente) — Relay + Web A→B, histórico/anexos/quota
Principal: `native_bridge/`, `sentra_mcp/services/session_checkpoint.py`, `web_history_store.py`, `web_history_assets.py`, `web_history_usage.py`, testes de `test_sentra_cos_web_*` e `test_sentra_cos_continuation*`. `sentra_executors/` deixa de ser escopo desta frente (ver Chat 4).
**P0** corrigir schema HTTP V2 em `native_bridge/relay.py` para `identity_epoch` sem downgrade, assinar/documentar contrato exato com Chat 2; testar chamada HTTP loopback com extensão V2 real fixture e SQLite, mismatch, revogação, restart, wrong doc/worker, envio incerto. Integrar `AuthenticatedWebReceiptBroker` com relay host e WorkItem; fase `sending` pré-clique, recebimento exato A→B, estado `UNCERTAIN` sem retry. Streaming frames autenticados, anexos/upload com receipt remoto e quotas somente observadas de conta provada; aprovar por host. Não editar `edge_extension/` nem fachadas centrais.
Relatório: `docs/SENTRA_COS_AGENT_3_2026-10-10.md`.

### Chat 4 (NOVO) — Code Mode + APIs e execução de agentes
Principal: `sentra_mcp/services/action_consent_gate.py`, pacote novo `sentra_code_mode/`, `sentra_executors/` (goal_loop, operation_receipts, conpty_sessions), testes `test_sentra_code_mode_*`, `test_sentra_executors_cos_*` e `test_sentra_action_consent_*`. Não editar módulos `browser_evidence.py`/Web, `native_bridge/`/Canvas/ControlPlane ou release.
Integrar read/action à mesma autoridade central `OperationRequest`/grant, consentimento humano versionado e tickets single-use; não confiar no booleano fornecido pelo modelo. QuickJS WASM **com pacote legítimo SHA/SBOM verificado**, sem Python eval, JS Node VM host, network ou filesystem e limites CPU/RAM/tempo/fuel; se artefato não disponível, code mode deve continuar disabled e documentar blocker. Agentes: finalização GoalLoop com limites reais, ConPTY `write_stdin` sob `DurableOperationGate` do executor existente, stdout streaming/head-tail/exit, GC somente com ownership OS kernel-handle provado, nunca matar PID de terceiros. Tests reais local com SQLite/PTY e física; handoff para coordenador conectar o host central.
Relatório: `docs/SENTRA_COS_AGENT_4_2026-10-10.md`.

### Chat 5 (NOVO) — Canvas UI, editor/PDF, UX, histórico
Principal: `sentra_canvas/project_review.py`, `sentra_canvas/desktop_ui/src/` e CSS; novos testes UI `test_sentra_cos_canvas_ux_*`, Node/Vite tests de a11y. **Não editar** `sentra_canvas/service.py`, `__main__.py`, `task_runtime.py`, `sentra_mcp/`, `native_bridge/`; pedir coordenador para rotas novas via handoff.
Entregar renderização de PDF visual segura e local sem OCR implícito, limites de páginas/tamanho/tempo; watcher com debounce, path confinement, revisão SHA e UI de diff; docks persistentes, atalhos, busca, reduced-motion, acessibilidade ARIA/keyboard, testes DPI 100/125/150. Consumir somente endpoints existentes ou escrever contrato claro para o coordenador integrar. Experiência minimalista corporativa, sem poluição, sem redesign incompatível com Canvas. Mostrar histórico protegido, consentimentos, anexos apenas após owner-auth. Provar build Vite e comportamento local.
Relatório: `docs/SENTRA_COS_AGENT_5_2026-10-10.md`.

### Chat 6 (NOVO) — Windows instalador, diagnóstico, atualização e CI
Principal: `sentra_remote/`, `scripts/commander/`, `sentra_electron/`, `.github/workflows/`, testes build/release e docs de instalação; **não editar** `sentra_canvas/service.py`, `__main__.py`, `sentra_mcp/`, `edge_extension/`, `native_bridge/`. Evitar compilar/instalar em cima de aplicações dos outros agentes; validar segurança de builds antes de qualquer ação de grande efeito.
Entrega app+Canvas+CLI+extension+WebModels+MCPB+Skills com artefatos versionados/SBOM/hashes, Doctor e reparo sem vazamento de segredo, updater staged, rollback, migração DB e clean first install em ambiente isolado. Build Setup/MSI, assinatura Authenticode SOMENTE se certificado legítimo disponível; nunca fingir assinatura ou homologação. Não alterar publicação remota sem aprovação. Provar smoke paths com artifact checks e testes de integração.
Relatório: `docs/SENTRA_COS_AGENT_6_2026-10-10.md`.

### Coordenador (ESTA conversa) — arquitetura e integração no centro
Principal EXCLUSIVO: `sentra_mcp/services/control_plane.py`, `sentra_mcp/server.py`, `sentra_mcp/tool_policy.py`, `sentra_canvas/service.py`, `sentra_canvas/__main__.py`, `sentra_canvas/task_runtime.py`, `sentra_runtime/central_authority.py`, testes de integração HTTP/ControlPlane. Não editar componentes exclusivos de Chats 1–6.
Integrar as APIs entregues pelo Chat 1/2/3/4 nas fachadas autoritativas, ativação do relay com `authenticated_control` na fábrica host, owner bearer + CSRF/origin, controles humanos, `WebMCPMessageDispatchGuard`, UI/API com policy deny-by-default; seleção de providers/Skills, operações duráveis, recepção autenticada sem privilegiar DOM. Testar regressão real com SQLite e chamadas HTTP; coordenar contratos e reconciliar colisões, não reenviar Web incerto. Antes de disponibilizar qualquer rota de efeito, provar origin, grants, replay, approval e epoch. Auditar entregas dos seis agentes e não marcar homologado até E2E e instalação.

## Procedimento de execução e critérios de entrega

1. Cada chat deve iniciar lendo ESTE documento e seu relatório anterior, inspecionar arquivos e tomar decisões de escrita só no escopo. Coordenador integra somente APIs comprovadas.
2. Criar código e testes reais em fatias completas. Se uma operação depende de autorização do operador/conta real, manter disabled e relatar bloqueio.
3. Cada entrega atualiza `docs/SENTRA_COS_AGENT_N_2026-10-10.md` com arquivos/testes/erros/handoff exato. Validar diff/check e não usar checkout/reset/stash.
4. E2E exigido para aceite: plugin completo+OAuth, extensão produtora V2+relay, conta/models comprovados, Chat A→B com receipts, histórico/anexo, ConPTY e execução durável, UX Canvas, clean Setup/MSI e assinatura verdadeira. Nenhum test mock substitui prova de conta externa.
5. Cada conversa Edge deve permanecer como URL /c e não deve receber novo prompt enquanto resposta anterior estiver em progresso.

## Identidades dos seis chats Edge persistentes

Todas as missões [SENTRA | 7 FRENTES | CHAT N] foram enviadas exatamente uma vez e observadas como turno de usuário com URL /c no Edge, sem abrir chats substitutos para os três existentes:
- 1 MCPB Skills: https://chatgpt.com/c/6aca2883-cba4-83e9-a371-cf7eef1cb959
- 2 browser Web: https://chatgpt.com/c/6aca28cf-617c-83ea-b866-dc4f85b40b7f
- 3 Relay A→B: https://chatgpt.com/c/6aca2920-0150-83e8-9d06-ccaf180d7fd2
- 4 Code Mode/Executores: https://chatgpt.com/c/6aca3fd9-62d8-83e9-8779-b27fb1d96fb0
- 5 Canvas UI/PDF: https://chatgpt.com/c/6aca4006-60c8-83e8-a010-0eaa86d22edd
- 6 Release/Instalador: https://chatgpt.com/c/6aca4034-6014-83e8-ae48-bd4a68dcdd36

Enviado pelo Edge no perfil atual com extensão ChatGPT 'Control your browser' previamente observada com acesso ao site; **não foi confirmado que a extensão proprietária SENTRA é a mesma instalada**. Enviar mensagem não equivale a concluir código: validar relatórios e regressões separadamente. Coordenador é esta própria conversa.

## Coordenação — entrega implementada nesta execução

**Fatia 1: administração MCP HTTP pelo Canvas REAL, sem efeito MCP.**
Arquivos do coordenador alterados:
- `sentra_mcp/services/control_plane.py`: agora possui uma única `MCPHttpRegistry(self)` compartilhando o `SQLiteControlPlaneStore` central. APIs `mcp_http_list/register/disable` owner/workspace bound, aprovação explícita, auditoria; `mcp_http_call_tool` host-only delega a `MCPHttpRegistry.execute` com Run/WorkItem/Operation/grants físicos, sem criar autoridade nova.
- `sentra_canvas/service.py`: `Canvas.center_mcp_http` executa somente `list/register/disable`, com workspace raiz validado, owner do `TaskRuntime`, revogação de server inexistente convertida para `Denied`. NÃO permite `call_tool` por interface de navegador.
- `sentra_canvas/__main__.py`: `GET /api/center/mcp-http?ws=...` owner bearer, projeção; `POST /api/center/mcp-http` com esquema JSON exato e `approve is True`, somente register/disable, nunca token/grant/args/host callable em request.
- `tests/unit/test_sentra_cos_central_mcp_http_facade.py`: HTTP real `CanvasServer` e SQLite, negação sem bearer/aprovação, schema extra, host externo, workspace diferente, revogação, zero grants/worker após cadastro, sem alegação de publicação de schema ou ChatGPT.

Teste inicial identificou endpoint revogado fora do workspace retornando 500; corrigido para Denied/403. Regressão final deste conjunto `test_sentra_cos_central_mcp_http_facade.py`, `test_sentra_cos_mcpb_http.py`, `test_sentra_cos_mcpb_registration.py`, `test_sentra_runtime_canvas_center_http.py`: **12 passed / 0 failed / exit0 (8,66s)**. MCP HTTP real de tool pelo WorkItem já possui teste próprio `test_sentra_cos_mcpb_http.py`, incluído aqui. Não significa OAuth2, plugin instalado na conta ou E2E ChatGPT real. Essas APIs NÃO oferecem execução modelo-facing e a UX de list/register ainda pode precisar de apresentação por Chat 5.

Coordenação com novas frentes não interrompeu os três chats originais; seis URLs permanentes documentadas acima. Não houve commit/push/reset global. Suíte integral, MSI/Setup, Authenticode e Web E2E seguem NÃO homologados.

## Implementação exclusiva do coordenador — troca de conta no SENTRA MCP

Pedido proprietário: trocar a conta do **plugin MCP ChatGPT** atualmente associada à conta Free por uma conta Plus, sem trocar o perfil do navegador nem a chave/túnel do OpenAI Platform. **Somente** a interface oficial do ChatGPT pode selecionar/instalar/revogar o plugin para a conta do proprietário; SENTRA não pode inferir conta/Plus por DOM, túnel ou chamada MCP.

Foi implementado de verdade:
- `sentra_canvas/mcp_account_switch.py`: persistência SQLite simples, owner-scoped, tentativa idempotente com prazo, fingerprint do túnel e baseline de contagem de ferramentas do `ConnectorProof`. Nenhuma credencial, cookie, conta/e-mail ou token armazenado. Etapas `begin`, `mark_steps`, `cancel`, `status`, com consentimento explícito e verificação de attempt_id; owner pode retomar após reiniciar. Nova atividade de chamadas MCP é informativa e **não prova** que veio da Plus, não concede grants ou rotaciona segredo. A Free não é revogada silenciosamente.
- `sentra_canvas/service.py`: fachada unificada `center_mcp_account`; vínculo ao mesmo owner e state root já usados por `ConnectorProof`.
- `sentra_canvas/__main__.py`: GET/POST `/api/center/mcp-account` protegidos por bearer local, Host/Origin/Sec-Fetch, esquemas JSON exatos e `approve is True`, sem aceitar dados de credencial no corpo.
- `sentra_canvas/desktop_ui/src/mcp-account-switch.jsx`: wizard premium compacto: iniciar Plus, copiar **ID público** do tunnel existente, abrir ChatGPT para Configurações > Plugins, conectar/autorização feita diretamente pelo proprietário, instrução para remover autorização Free, marcar conclusão e verificar atividade. Mostra conta/plano como **não verificado**, mesmo após confirmação humana/ligação local.
- `sentra_canvas/desktop_ui/src/plugin-status-dialog.jsx`: wizard dentro da aba já existente de diagnóstico MCP, e `main.jsx` renomeia menu para `Conta e conexão ChatGPT (MCP)` (Mais ferramentas).
- `tests/unit/test_sentra_mcp_account_switch.py`: testes de SQLite persistente e retomada, consentimento, tentativa antiga, separação de owner, token/bearer, schema exato, túnel não configurado, nenhuma alegação de Plus ou revogação remota.

Regressão após mudança do menu e da interface: `python -B -m pytest -q -p no:cacheprovider tests/unit/test_sentra_mcp_account_switch.py tests/unit/test_sentra_cos_chat_access_and_connector_proof.py tests/unit/test_sentra_cos_central_mcp_http_facade.py tests/unit/test_sentra_runtime_canvas_center_http.py --tb=short --disable-warnings` => **16 passed, 0 failed, exit 0 (7,76s)**. `npm run build --prefix sentra_canvas/desktop_ui` materializou desktop-assets (2144 módulos, warning de chunk e scripts clássicos já existentes), exit0. `python -B -m compileall` exit0; `git diff --check` exit0 (warning CRLF legado).

**Limitação de ativação:** o Canvas Python atualmente executando não foi reiniciado à força porque seis outros agentes usam o computador e há ConPTY/processos em andamento. A nova API passa a atender quando o Canvas atualizado for aberto/reiniciado com segurança. O usuário deve autorizar a conexão na conta Plus e revogar a Free pela gestão oficial de Plugins; não fingir migração concluída sem prova remota independente. Nenhum commit/push/reset global.
