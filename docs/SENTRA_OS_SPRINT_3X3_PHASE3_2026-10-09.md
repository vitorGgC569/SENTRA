# SENTRA OS — Sprint 3×3 · Fase 3 · coordenação e implementação

Atualizado em 09/10/2026, horário de Brasília, diretamente no Windows OGrandeOxta em C:\Users\vitor\OneDrive\Desktop\SENTRA. O projeto principal está no commit-base 68e3894; novos módulos permanecem UNTRACKED. **NÃO representa release, certificação de terceiros nem integração de produção.**

## Revisão da Fase 2 (auditoria real dos três agentes)

| Agente | Evidência recém-revalidada | Novas fatias Fase 2 | Limitação |
|---|---|---|---|
| EXEC-001 | 162 passed, 3 skipped em toda a suíte executors | browser_lab.py Playwright opt-in; remote_readonly.py socket TCP HMAC local; windows_identity.py Windows PID/HWND/CreateTime/hash/fence | Playwright/WinUIA em VM, Daytona, guacd e RustDesk reais NÃO testados |
| CRIT-002 | 119 passed em toda a suíte interop | activepieces_loopback.py HTTP callback; openhands_local.py eventos/processo fixture; workflow_bridge.py checkpoints e subagentes locais | Sem Activepieces SaaS, OpenHands Agent Server ou Temporal/Graph engine externa |
| CRIT-003 | 46/46 Node passed com Hocuspocus, dois peers e SQLite real local | physical_cables.mjs solver SVG; sqlite_host.mjs recovery/quarantine; workspace session adapter com troca/revoke/logout | Não há Canvas principal montado, auth real WSS ou cluster Hocuspocus multi-host |

Não houve instalação silenciosa, execução em aplicações Windows pessoais, autorização remota implícita ou garantia de que os 37 clones estejam integrados. O E2E dos serviços terceiros permanece bloqueado.

## Novas ordens: 3 IMPLEMENTAÇÕES inéditas para cada agente, Fase 3

Ordens enviadas **e confirmadas SENT** às três conversas ORIGINAIS via SENTRA Edge Browser Bridge; recibos em runs/SENTRA_SPRINT3_PHASE3_DISPATCH_20261009.json:

- EXEC-001 — https://chatgpt.com/c/6ac83719-1efc-83ea-b448-0763a864bbbe : **(1) gVisor/runsc** OCI sandbox lifecycle opt-in com fixture subprocess controlado; **(2) hcsshim/WinHCS** boundary para containers Windows sob autorização explícita; **(3) WindowsAgentArena/OSWorld/WindowsWorld** benchmark determinístico em Tk laboratório. Somente sentra_executors/ e tests/unit/test_sentra_executors_*.py.
- CRIT-002 — https://chatgpt.com/c/6ac83727-19b4-83ea-8a85-b2096c9faba5 : **(1) MCP TypeScript SDK compatibility bridge** com servidor Node fixture; **(2) ACP Registry** catálogo autenticado/pinado sem downloader; **(3) A2A streaming SSE** HTTP loopback com cursor e auth. Somente sentra_interop/ e tests/unit/test_sentra_interop_*.py.
- CRIT-003 — https://chatgpt.com/c/6ac83735-217c-83e9-9364-8ab8860f334b : **(1) xyflow-style accessibility** overlay para nós/links autorizados; **(2) Yjs signed/hash-bound snapshot envelope** para display-only; **(3) Hocuspocus quotas/health** multi-workspace, duas conexões WS e reauth. Somente sentra_collab/, novo sentra_canvas/static/sentra-collab.js e tests/unit/test_sentra_collab_*.py.

Não criar chats novos. Toda fatia exige código próprio, testes positivos/negativos, E2E com fixture local quando ambiente real ausente, controle de identidade, grant, idempotência, e documentação honesta. Não editar core/Canvas nativo/outros domínios.

## As 3 incorporações implementadas pelo COORDENADOR nesta Fase 3

**Premissa arquitetural:** Keycloak prova identidade; OPA fornece decisão contextual; OpenFGA verifica relação. NENHUM deles concede sozinho a permissão SENTRA para executar uma OperationRequest. O código realiza composição como **veto adicional** com AuthorizationService/GovernanceService/BoundWorkItemPolicy e o ExecutorRegistry reais. Não substitui o ControlStore ou o scheduler.

### 1. Keycloak / OIDC RS256

- Fonte pinada: third_party/keycloak → https://github.com/keycloak/keycloak commit c7de391ae4d8a83ad62b8386cab85d37fbb6324c.
- Código: sentra_runtime/keycloak_identity.py (PinnedKeycloakJWTVerifier, KeycloakIdentityVeto).
- Verificação CRIPTOGRÁFICA real RS256 (cryptography) de assinatura JWS com JWKS fixado por autoridade confiável. Confere issuer exato, aud, typ Bearer, sub, iat/nbf/exp, limite de vida de token, kid e RSA >=2048, rejeita alg none, header de key injection, tokens adulterados.
- Não consulta servidor Keycloak, não inventa grant a partir de grupos/roles, não instala Java/Keycloak. Token de produção exige fluxo de sessão autenticada e JWKS rotation auditada sob TLS real.
- Testes: RSA assinado e validado de verdade, falso public key, claims erradas, grant SQLite revogado, identidade spoof e Registry.submit.

### 2. OPA / Policy Decision Point REST

- Fonte pinada: third_party/opa → https://github.com/open-policy-agent/opa commit 4dcda5da919a9cb6174b4998c6304f37783d8f21.
- Código: sentra_runtime/opa_pdp.py e sentra_runtime/_policy_http.py.
- HTTP POST real para protocolo OPA v1/data/sentra/allow com JSON tipo estrito e Bearer; apenas endpoint 127.0.0.1 com porta explícita, sem proxy, redirect ou network public. Permite apenas boolean result verdadeiro após grant SENTRA vivo; erros, timeouts, schema desconhecido e policy ausente negam.
- E2E com ThreadingHTTPServer loopback REAL sob testes. OPA server/Rego/Policy bundle upstream NÃO rodados; produção exige implantar OPA autenticado e monitorado.

### 3. OpenFGA / Relation-based Authorization (ReBAC)

- Fonte pinada: third_party/openfga → https://github.com/openfga/openfga commit 526995eb202464e2cace266fb5be56c212af9ecf.
- Código: sentra_runtime/openfga_rebac.py (+ HTTP comum).
- HTTP POST real para /stores/{store}/check com model ID fixado em config confiável, tuple_key de principal/work item derivada de OperationRequest tipada. OpenFGA pode NEGAR, jamais conceder quando grant SENTRA não existe. Rejeita tuples id forjado, upstream HTTP erros, schema inválido, redirects e qualquer endpoint outbound.
- E2E com servidor HTTP local de laboratório; nenhum OpenFGA daemon/modelo de produção instalado, nem expansão gráfica de relações entre amigos homologada.

### Testes e evidências

- tests/unit/test_sentra_runtime_external_authority_phase3.py valida as 3 fontes no mesmo pipeline de ExecutorRegistry, Keycloak RSA assinado de verdade, OPA e OpenFGA em dois servidores HTTP loopback e autorização AUTÊNTICA via sentra_mcp.services.authorization.AuthorizationService e GovernanceService SQLite. Teste E2E confirma revogação que barra TODAS as fontes sem chamar PDP externo.
- Roda de teste inicial: 22 passed; após acrescentar provas dos grants reais, 25 passed; após o triplo-gate, executar suíte novamente. Teste runtime/authority combinados também passou 39 em execução intermediária.
- Dependência Python cryptography 50.0.1 já disponível no computador; não instalada nesta tarefa. Nenhum package externo, daemon ou conta pessoal foi tocado.
- Todos os eventos externos permanecem **opt-in e desabilitados por padrão** até revisão da configuração. Não há UI/log de token nem autorizações por dados de CRDT/Canvas.

## P0 de produção: sem alegações excessivas

1. Serviços Keycloak, OPA e OpenFGA reais, com TLS/WSS e credenciais administradas, NÃO estão conectados. E2E local valida protocolos e regras, não produção.
2. A auth SENTRA autoritativa ainda necessita de uma transação única com persistência de operação/intent hash, grants, lease/fence no instante do efeito; DurableOperationGate de Fase 2 NEGOU a API legada insegura.
3. Browser/WinUIA/Daytona remotos, Linux gVisor e WinHCS reais exigem sandboxes/VM/host autorizados; benchmarks do laboratório não certificam OSWorld.
4. Sidecar de colaboração ainda não foi montado no Canvas principal nem testado entre dois dispositivos com identidade real.
5. Licenças, NOTICE, CVE/SBOM (Grype scanner real) e empacotamento/release CI são gates posteriores. Verificação 37/37 clones **não** equivale a incorporar os 37 inteiros.
6. Novos arquivos seguem untracked, sem git reset, clean ou commit global de concorrentes.

Próximo passo: conferir três entregas novas por equipe, rodar suites isoladas e cruzadas após estabilização, registrar falhas reais, enviar QA pontual às mesmas conversas, sem ultrapassar a propriedade de arquivos.

## Verificação independente posterior (09/10/2026 ~10:03 BRT)

- As três ordens Fase 3 foram confirmadas como SENT para as mesmas conversas: runs/SENTRA_SPRINT3_PHASE3_DISPATCH_20261009.json.
- Os módulos próprios Keycloak RS256, OPA/HTTP e OpenFGA/Check são testados em conjunto com grants SQLite reais do SENTRA. test_sentra_runtime_external_authority_phase3.py foi reexecutado; regressão com runtime contracts/authority: **56 passed**, sem falhas.
- A suíte Python nova de Fase 3 (7 arquivos executors, interop, coordinator) terminou **79 passed, 1 skipped**, exit 0. O skip é dependência/ambiente opcional, não validação de host remoto.
- Node testes novos isolados: graph_a11y + verified_snapshot **5 passed**; local quota_health **3 passed**, todos com testes reais WS de laboratório onde descrito.
- Uma rodada completa paralela pytest+Node gerou processos de teste que não encerraram oportunamente; foram terminadas SOMENTE as duas árvores de testes próprias PIDs 6040 e 35416, não os agentes. Reexecução Node **SEQUENCIAL**: **54 passed, 0 failed, 0 skipped** em ~3 s.
- Regressão Python ampla test_sentra_*.py iniciada SEQUENCIALMENTE após Node; registrar resultado final somente depois de exit code observado.
- As três equipes Fase 3 criaram código real em sentra_executors/gvisor_runsc.py,winhcs_boundary.py,tk_benchmark.py; sentra_interop/mcp_sdk_compat.py,acp_verified.py,a2a_sse.py; sentra_collab/graph_a11y.mjs,verified_snapshot.mjs,local_admission.mjs e testes dedicados. A Fase 3 está implementada LOCALMENTE e observada no disco; **não** certifica runsc, WinHCS, MCP TS SDK/ACP Registry/A2A remoto e identidade WSS de produção.

## Marco final de regressão sequencial (~10:08 BRT)

Após finalizar a suíte Node e então executar apenas a suíte Python (SEM concorrência de Node):
- `npm test --prefix sentra_collab`: **54 passed, 0 failed, 0 skipped**, exit 0, 2.95s de testes Node.
- `python -B -m pytest -q -p no:cacheprovider` em todos os **49 arquivos `tests/unit/test_sentra_*.py`**: **634 passed, 4 skipped**, sem falhas, exit code 0, 125.03s.
- Suites exclusivas da Fase 3: **79 passed, 1 skipped** (7 arquivos, executors/interop/coordinator).
- Contratos de identidade+OPA+OpenFGA com autorização SENTRA real: **56 passed** combinados com runtime core/authority tests. Keycloak JWT RS256 com cryptography real; OPA/OpenFGA servidores HTTP LOCAL FIXTURE, não daemons upstream.
- Sprint Fase 3 completa até o escopo local; E2E de produção dos terceiros/Canvas/ControlStore ainda NÃO habilitado. Os novos arquivos ainda carecem de revisão, git add seletivo/CI/empacotamento antes de release.
