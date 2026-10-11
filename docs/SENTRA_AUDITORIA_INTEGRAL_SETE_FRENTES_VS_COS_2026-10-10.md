# SENTRA × Chat On Steroids — auditoria cruzada das sete frentes
**Data da inspeção:** 10/10/2026, ~11h22–11h26 BRT.  
**Checkout:** `C:\Users\vitor\OneDrive\Desktop\SENTRA`, Desktop Commander OGrandeOxta.  
**Referências:** `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md` (upstream CoS `151e7ef96bc16bf594ffbd35efe620e4ef6e4c2c`, 13 G + 21 A), `docs/SENTRA_AUDITORIA_COBERTURA_CHAT_ON_STEROIDS_2026-10-09.md`, `docs/SENTRA_COS_SETE_FRENTES_2026-10-10.md`, seis relatórios `docs/SENTRA_COS_AGENT_1_2026-10-10.md` … `_6_`, e os fontes abaixo. **Esta auditoria não executa nem modifica conta ChatGPT remota.**

## Método e padrão de aceite

Nível **L**: código+prova **local** (teste hermético/SQLite, HTTP, Chromium, Docker ou ConPTY conforme declarado); nível **P**: base/recurso **parcial** ainda não ligado ao ponto de uso central ou com gate requerido ausente; nível **B**: funcionalidade específica bloqueada/não implementada com segurança. Estes níveis não são percentuais de trabalho. Nenhuma classificação local equivale a aceite integral **E2E remoto + produto instalado**. A cobertura antiga 0/34 E2E era relativa a 09/10 e não deve ser repetida como se provasse ausência de código após as sete frentes; até esta inspeção, **nenhuma das 34 entradas tem prova de aceite integral contra todos os critérios originais**. Alguns requisitos estritamente locais já possuem ensaios E2E locais satisfatórios.

Auditoria feita sem reescrever os módulos dos agentes e sem reset/checkout/stash/clean/commit/push global. `git HEAD=e4b3968` e worktree possui alterações rastreadas e numerosos novos arquivos não rastreados. Os seis chats compartilham o mesmo checkout. Logs de testes escritos por outros agentes são **evidência reportada, não resultados automaticamente reexecutados**. Não somar contagens de diferentes seleções com sobreposição. O clone upstream é fonte pinada de desenho; não foram executados scripts upstream.

## Veredito das sete frentes

| Responsável | Entrega concreta constatada em fontes/relatório | O que ainda impede o objetivo integral |
|---|---|---|
| **Chat 1: MCPB/Skills** | `plugin_bundles.py`, `mcpb_http.py`, `mcpb_oauth.py`, `mcpb_offline.py`, `mcpb_orphans.py`, `skill_library.py`, catálogo/versionamento e testes stdio Docker/HTTP SSE/PKCE DPAPI/owner. Rodada anterior reportou 47 pass, 1 skip; fontes/novos testes de rodada 4 apareceram enquanto auditávamos | Callback OAuth externo real, GET/Last-Event-ID/DELETE completos, relaunch supervisionado, instalar wheels no Docker físico, reconciliar contêiner/ownership efetivamente em `mcpb_sandbox.py`, uninstall/rollback físico, schema atualizado na conta ChatGPT; novos testes não bastam sem integração |
| **Chat 2: prova da conta/MV3** | `edge_extension/service-worker.js`, `browser/evidence_http_v2.py`, `browser_evidence.py`, `web_account_dispatch.py`, request↔message/identity_epoch, deny-only, produtor receipt V2 no source com testes HTTP+SQLite (90 pass reportados, manifesto SHA reestampado) | Edge MV3 realmente instalado/pareado, prova independente conta/Plus/modelo/effort/Automatic, lifecycle de logout/aba em navegador real, `WebMCPMessageDispatchGuard` realmente conectado ao ToolPolicyProxy central |
| **Chat 3: Relay/continuidade Web** | `native_bridge/relay.py`, `job_store.py`, `web_evidence_ingress.py`, `continuation_web.py`, `web_history_*`: outbox DPAPI, rota V2 epoch, receipt preliminar≠atestado, WebContinuation/frames/history SQLite, transport HTTP e crash/restart testados | Fábrica instalada `sentra_remote/browser_relay.py` **não injeta** `authenticated_control`: produção ainda sem atestado central; A→B sem prova ChatGPT real e envio de anexo Web sem upload/receipt remoto. Não garantir quota/modelo/conta por DOM |
| **Chat 4: Code Mode, ActionConsent, Goal/ConPTY** | `sentra_code_mode/` com negação de WASM não auditado; `action_consent_gate.py` de duas provas host-only; `sentra_executors/{goal_loop,conpty_sessions,operation_receipts}.py` com SQLite/grants/custo micro-USD; teste PowerShell ConPTY real handle-owned. 17 pass reportados na seleção final | QuickJS WASM permanece `enabled=False`; autenticador de clique do host e integração via Canvas/CLI/ToolPolicy pendentes; medição do custo efetivo/GC e lifecycle de PTY após crash no host |
| **Chat 5: Canvas/UX/PDF** | `project_review.py` PDFium subprocess read-only, watcher SHA/debounce; React docks/teclado/ARIA/reduced-motion; Chromium headless DOM local com 6 pass reportados, Python 18 pass/1 skip, Node 6 pass | Rota `pdf_visual` **ausente** de `sentra_canvas/__main__.py` e `service.py`; wheel `pypdfium2==4.30.0` sem distribuição/isolamento kernel comprovados; QA Chromium usou HTTP mock, DPI físico só 96 (125/150 emulação), WebView2 final não verificado |
| **Chat 6: instalação/update/CI** | `updater.py` anti-ZIP slip/size/collision, `scripts/commander/release_doctor.py`, CI e testes de SBOM/hashes/signer, `sentra_remote/install_doctor.py` surgiu no checkout durante rodada 4 | Setup/MSI em `dist/` continuam de 01/10, fontes atuais não empacotadas/assinadas, first-install limpa Windows não testada, rollback/migrations com crash e ownership, actionlint/CI remoto pendentes; observar relatório final da rodada 4 quando concluir |
| **Coordenação (7ª frente)** | `control_plane.py` MCPHttpRegistry central, `Canvas.center_mcp_http` + GET/POST owner auth, MCPB stdio Docker gated em `mcpb_sandbox.py`, wizard de troca de conta MCP no Canvas e testes HTTP SQLite | Injetar `authenticated_control` na factory do relay, ligar guard Web ao `ToolPolicyProxy`, callback owner-auth real para ActionConsent e host ConPTY; habilitar GET `pdf_visual` de forma segura; reconciliar instalação/CI. Wizard Plus é intenção de reautorização, **não prova Plus** |

## Matriz atualizada — 13 frentes principais

| ID | Estado | Implementação/cobertura comprovável hoje | Pendente para aceite integral |
|---|---|---|---|
| **G01** MCPB lifecycle | L/P | stage ZIP, catálogo, stdio Docker gated, HTTP local/session, PKCE vault e worker health | OAuth externo+callback e runtime supervisionado, dependências instaladas, restart/recovery/uninstall físico, refresh conta |
| **G02** modelos por conta/effort/Automatic | P | CLI `/model`/`/effort`, catálogo Gateway e política unknown | atestado da conta, picker real, Automatic, troca Free→Plus segura e fonte independente por sessão |
| **G03** Compact & Resume | L/P | WebContinuation em SQLite, commit condicionado a receipt, Run/WorkItem preservados em ensaio | ChatGPT Web A→B efetivo, contexto injetado/recebido, concorrência/crash e confirmação no provedor |
| **G04** outbox de entrega Web | L/P | JobStore ciphertext, send/uncertain, V2 receipt authenticated em fixture, sem retry após ACK perdido | produtor/relay/host em execução ligados, evidência de mensagem no ChatGPT real |
| **G05** Goal/Loop + workers | L/P | loop com limites, preço estimado host, worker state/health e quality gate | supervisão/restart/GC final real, custos medidos, fluxos de stop/cancel |
| **G06** terminal persistente | L/P | ConPTY real consented Start/Write/Close com handle owned e Operation/grants no teste | host/Canvas expor API owner-auth e gerenciar lifetime real sem PID-only |
| **G07** Skills versionadas | L/P | SKILL.md revisão SHA e pin Git, ACL/workitem, update/revoke com testes | integrar descoberta/ativação no uso cotidiano+UX e ciclo update/rollback |
| **G08** API read/action opt-in | L/P | ActionConsentService two-proof, grants/Operation; Canvas APIs guardadas | conectar autenticador de clique host real, rate/deadline/paginação em todos endpoints |
| **G09** Setup/Doctor/repair | L/P | onboarding+proof local, release doctor e install_doctor preliminar | reparo proprietário real, Setup/MSI contemporâneos, clean install, auth e schema remotos |
| **G10** editor/diff/PDF | L/P | editor ticket revisado e diff, PDF textual e renderer visual subprocesso | rota visual owner-auth ausente; wheel/isolamento, testes no app instalado |
| **G11** allowlist de comandos | P | policy central e grants, entradas ConPTY allowlisted | paridade/fixtures abrangentes do parser CoS e validação de filhos/quoting/sandbox verdadeiro |
| **G12** observabilidade browser | L/P | MV3 V2, epoch, challenge/observe/invalidate, request/message, receipt producer em harness | Edge instalado/pareado, prova de conta; guard MCP central e worker real |
| **G13** UX acessível | L/P | docks, atalhos, reduced-motion, QA React/Chromium headless/DPR | leitor de tela, WebView2 e DPI físico 125/150, perf/regressão instalador |

## Matriz atualizada — 21 subfrentes

| ID | Estado | Evidência local existente | Prova/integração restante |
|---|---|---|---|
| **A01** | L/P | request ID ↔ message ID ↔ epoch/doc em BrowserEvidence e ingress V2 | guard em TODA chamada MCP e ChatGPT real |
| **A02** | L/P | bloqueio de conversa vinculado ao request conhecido | alcance em chamadas sem origem e UX owner confirmada |
| **A03** | L/P | ChatTrust/revisão/strict default deny na política local | herança após sucessor Web comprovado, negação de origem unknown no host |
| **A04** | P | estado pending approval bloqueado no harness MV3/receipt | cartão de aprovação humano **real** na UI ChatGPT e sem auto-reload |
| **A05** | L/P | ConnectorProof/tunnel/activity, consentimento MCP local | instalar/autenticar plugin na conta e provar cliente/schema/plano, não apenas túnel |
| **A06** | L/P | snapshot e digest de schemas MCP local, namespace | refresh do catálogo **na conta ChatGPT** e cache externo observado |
| **A07** | L/P | tool exposure por namespace/colisão e limites locais | gate/publicação dinâmica no MCPServer instalado |
| **A08** | **B** | `QuickJSWasmAdmission` nega; checks de SHA/SBOM | motor WASM auditado, fuel/IO/CPU/mem, execução real por Operation/grant |
| **A09** | **B/P** | challenge MV3 V2 e extensão observada em *harness* | atestação de instalação/pareamento/login do Edge real e prova de perfil/conta |
| **A10** | L/P | consentimentos read/action com owner authenticator callback | conectar callback à sessão + clique real no Canvas/CLI |
| **A11** | L/P | WebHistoryStore protegido, consulta/índice local | ingestão de histórico ChatGPT real com provenance e ACL, deep link |
| **A12** | L/P | WebAssetDrafts ciphertext/chunks/grant local | upload comprovado, receipt e anexos reais no ChatGPT |
| **A13** | L/P | frames revisados por message ID/epoch em SQLite | streaming real browser observado, virtualização/overflow/restart |
| **A14** | P | observações de uso/quota armazenadas separadas | métricas/frescor e limite **da conta real** independentemente provada |
| **A15** | L/P | redaction/shareable_report e release Doctor | prévia/export anonimizado na UI do app instalado, exclusão/retention |
| **A16** | L/P | Operation receipts/head-tail/status/exit locais | projeção uniforme no Canvas/CLI de todos os tool calls |
| **A17** | L/P | ConPTY close só com handle próprio, ledger Docker ownership e GC não destrutivo | reconciliação física crash, limite de idle, cleanup seguro no host |
| **A18** | L/P | editor/diff, SHA watcher lock/debounce, UI de revisão | fonte git/watcher real via API central, erros de concorrência E2E instalado |
| **A19** | L/P | ZIP/update integrity, doctor/SBOM/CI prévia | updater atômico físico + WebModels/extension/MCPB + rollback/SQLite |
| **A20** | L/P | export local Markdown de sessão/CLI e suporte de histórico | export por mensagem/sessão ChatGPT Web com provenance e redação |
| **A21** | L/P | Git-pinned Skill revisions e ativação local limitada | ciclo completo conectado ao WorkItem/Canvas e revogação em execução |

## Bloqueios P0 observados DIRETAMENTE no código central

1. `sentra_remote/browser_relay.py` constrói `RelayServer(browser_evidence=BrowserEvidenceService(state_dir))` mas **não injeta** `authenticated_control=ControlPlaneService(...)`. Assim o recibo autenticado V2 testado via host-only fixture não pode ser promovido pelo executável instalado; é distinto de ter aceitação de HTTP em teste.
2. `sentra_mcp/server.py::_register_tools` registra `ToolPolicyProxy(request_observer=self._observe_mcp_request)`, **não** instancia/encadeia `WebMCPMessageDispatchGuard.tool_observer`. Sem isso o join requerido por A01/A02/A03 não é assegurado como filtro de todos os efeitos MCP no servidor real.
3. `sentra_canvas/__main__.py` GET `/api/center/project-review` allowlist `list/preview/diff/pdf_text`; `sentra_canvas/service.py::center_project_review` também não tem `pdf_visual`. Renderer Chat 5 é local, sem chamada HTTP real de produção.
4. `sentra_code_mode/QuickJSWasmAdmission.status()` mantém **enabled=False**; não anunciar Code Mode ativo por existir pacote Python.
5. `dist/SENTRA-Setup.exe` e executáveis do pacote estão datados de **01/10/2026**, anteriores ao código e aos seis relatórios; não há Setup/MSI assinado/current nem primeira instalação limpa da revisão atual. Nada neste relatório autoriza rebuild/instalação enquanto outros agentes trabalham.
6. O wizard `mcp_account_switch.py` **não** realiza troca de conta no servidor ChatGPT. É uma UX legítima de reautorização via Plugins que mantém `chatgpt_plan_verified=False`, e exige ação do proprietário na conta Plus; túnel saudável ≠ assinatura de conta.

## Critérios de aceite prioritários (em ordem de dependência)

- **Cadeia Web provada:** extensão Edge real pareada → identity_epoch/doc/worker → x-request-id↔metadata.request_id ↔ worker lease/Run/WorkItem/grant → ToolPolicyProxy guard → fase sending → recibo autenticado → commit A→B, sem duplicate após incerteza ou aprovação pendente. Conta/modelo/effort permanecem unknown quando não autenticados independentemente.
- **MCPB lifecycle:** bundle imutável → sandbox Docker real com imagem pinada e ledger ownership → stdio/HTTP Session, OAuth PKCE loopback aprovado, dependências offline executadas dentro sandbox, health/restart + uninstall seguro + atualização efetiva do catálogo no cliente ChatGPT.
- **Consentimentos e agentes:** dois cliques host-auth com provas single-use/Origin/CSRF, DurableOperationGate em read/action e ConPTY; Code Mode só depois de WASM realmente auditado.
- **Canvas/UX:** rotear PDF visual sob owner-auth, limites/parser fail-closed e dependência pinada no instalador; verificar Chromium/browser e app Windows DPI físico, watcher, acessibilidade.
- **Release:** congelar checkout após conclusão coordenada dos seis, ampliar pytest full suite + Node/Vite/CI actionlint, gerar novos Setup/MSI+SBOM/provenance, verificar Authenticode legítimo, first install/uninstall/upgrade/rollback numa VM isolada, nunca substituir binários dos agentes durante execução.

**Veredito:** valor do CoS foi convertido em componentes reais e parcialmente integrados, mas a promessa de incorporação **integral** dos 34 itens ainda NÃO foi demonstrada. Estimativas numéricas percentuais seriam enganosas sem critérios de aceite individual por requisito; a matriz registra explicitamente provas locais e os gates ausentes. Não foram disparadas novas ordens aos seis chats por esta auditoria.

## Atualização da auditoria após chegada dos relatórios da Rodada 4 (11h28)

A primeira matriz acima foi redigida enquanto Chats 1 e 6 ainda trabalhavam; as novas entregas abaixo **substituem as descrições anteriores de lacunas locais**, mas não alteram o veredito de ausência de homologação externa.

**Chat 1 — avanço posterior:** `mcpb_oauth_callback.py::OAuthLoopbackReceiver` adicionou receiver PKCE loopback com session/state/consent host-only (sem OAuth de provedor externo real); `MCPHttpRegistry.session_action` acrescentou ações GET/eventos e DELETE com grants `mcp:events` e `mcp:session-delete`; `mcpb_offline.verify_offline_dependencies_in_docker` executa preflight/instalação verificada em contêiner de prova; `plugin_host.restart_authorized` relança worker supervisionado com nova Operation/novo grant+consentimento e `MCPBBundleCatalog.purge_uninstalled_extracted` remove fisicamente apenas extração após tombstone e negar ownership pendente, **não** archive imutável. O relatório do próprio Chat 1 registra **62 passed, 1 skipped, 0 failed**. Persistem **composição efetiva** desses contratos em `mcpb_sandbox.py` e Factory host, aprovação humana real, provider OAuth externo, GET contínuo/replay provider, Docker crash cleanup por ID/labels e rollback coordenado. G01/A06/A07/G07/A21 seguem L/P, mas com mais etapas locais concluídas.

**Chat 6 — avanço posterior:** `sentra_remote/install_doctor.py` fornece inspeção read-only e `request_owner_repair` com callbacks owner-auth que **ainda não estão ligados** à operação física central; `sentra_remote/release_migration.py` faz snapshots SQLite, SHA, CAS e rollback **em estado offline**, não migra writers/leases vivos; scripts de pin `pypdfium2==4.30.0` com wheel win_amd64 SHA legítimo `90dbb2ac...` (verificar hash completo no arquivo de pin), inclusão no SBOM/build; actionlint 1.7.12 executado localmente, gate de publicação requer QA VM independente; VM smoke foi PREPARADO mas não executado; `update_helper.py` bloqueia update físico de banco existente até contrato de migração autoritativo. Relatório Chat 6: **102 passed, 1 warning** na seleção anterior à variante final de ProductPaths, sem instalação nem assinatura. G09/A15/A19 ficam L/P mais avançados, ainda sem Setup contemporâneo, MSI, first-install/rollback real, Authenticode ou evidência independente de conta.

**Auditoria reexecutada pelo coordenador:** seleção transversal de **27 módulos pytest**, compreendendo novas fatias MCPB (OAuth receiver, ações de sessão, wheel Docker, restart, purge), Web V2 producer/relay, outbox, Code Mode fail-closed, ActionConsent, ConPTY real, GoalLoop, PDF/Chromium, security doctor/migration/publish do release, Canvas MCP e wizard de conta: **143 passed, 0 failed, 0 skipped em 88,45 s, exit 0**. Essa seleção foi lançada durante alterações concorrentes e **não prova** que toda a suíte nova do Chat 1/6 foi rodada após seu último patch. Validação independente Node `node --test tests/unit/sentra_cos_canvas_ux.cjs`: **6 passed**; `npm test --prefix sentra_electron`: **2 passed**. Não somar 143+6+2 como total de uma mesma linguagem/suíte. Sem suite global integral nem executável novo. `git diff --check` dos arquivos centrais selecionados sem erro.

**Decisão de aceite inalterada:** *sem homologação integral do CoS 34/34*, principalmente pela fábrica real do relay sem `authenticated_control`, guard Web não composto com ToolPolicyProxy central, rota PDF visual ausente, ausência de prova independente da conta/plan/effort, QuickJS WASM desativado e release ainda stale/unsigned.

### Última regressão focal após os relatórios atualizados
O coordenador reexecutou **após** receber os adendos de Chats 1 e 6 a seleção de oito módulos (`test_sentra_cos_mcpb_oauth_callback.py`, `test_sentra_cos_mcpb_session_actions.py`, `test_sentra_cos_mcpb_worker_restart.py`, `test_sentra_cos_mcpb_purge.py`, `test_sentra_cos_release_migration_round4.py`, `test_sentra_cos_install_doctor_round4.py`, `test_sentra_cos_release_publish_round4.py`, `test_sentra_cos_release_doctor.py`): **38 passed, 0 failed, 0 skipped, 14,48s, exit 0**. Este grupo **sobrepõe** os 143 anteriores; não somar contagens como testes únicos. Não comprova autorização externa nem operação de instalador físico. 
