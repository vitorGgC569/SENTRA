# SENTRA OS — Sprint 3×3 Fase 2 (12 novas incorporações delimitadas)

Auditoria de execução em 09/10/2026, aproximadamente 09:26 BRT, via Desktop Commander em C:\Users\vitor\OneDrive\Desktop\SENTRA. Esta entrega NÃO constitui release e não indica que os 37 repositórios terceiros estejam integralmente incorporados.

## Coordenação: mesmas conversas, papéis exclusivos

| Frente | Conversa original | Arquivos exclusivos | Novas 3 fatias |
|---|---|---|---|
| EXEC-001 | https://chatgpt.com/c/6ac83719-1efc-83ea-b448-0763a864bbbe | sentra_executors/ + testes executors | Playwright MCP browser isolado; transporte read-only Guacamole/RustDesk; identidade/fence Windows PID/HWND |
| CRIT-002 | https://chatgpt.com/c/6ac83727-19b4-83ea-8a85-b2096c9faba5 | sentra_interop/ + testes interop | Activepieces loopback; OpenHands SDK/event stream fixture; LangGraph/Temporal workflow subordinate |
| CRIT-003 | https://chatgpt.com/c/6ac83735-217c-83e9-9364-8ab8860f334b | sentra_collab/, novo sentra-collab.js e testes collab | Cabos físicos XYFlow-inspired; crash/ambiguous-commit SQLite recovery; lifecycle workspace/auth |
| COORDENADOR | conversa atual | sentra_runtime/, sentra_quality/, testes próprios, docs/SENTRA_OS_* | OTLP/HTTP local; Grype offline JSON gate; DurableOperationGate fail-closed |

Enviados prompts de implementação às três conversas originais por Edge Browser Bridge.
- EXEC-001: envio confirmado SENT.
- CRIT-002: envio confirmado SENT.
- CRIT-003: envio inicial retornou TimeoutError/UNCERTAIN, mas reconciliação posterior por CHAT_PEEK read-only mostrou o agente trabalhando em physical_cables.mjs; não houve reenvio cego. Uma nova orientação QA foi enviada e confirmada com URL da mesma conversa.
- Os agentes não recebem permissão para editar sentra_runtime/core/auth/Canvas nativo ou arquivos dos outros chats.

## Auditoria das novas entregas no disco

EXEC-001 implementou sentra_executors/browser_lab.py, remote_readonly.py, windows_identity.py, com testes novos de browser e integração. Testes focados na fase: **155 passados, 3 ignorados**. Skips decorrem de ambiente externo opcional. Playwright real e Guacamole/RustDesk remoto de produção não estão comprovados.

CRIT-002 implementou sentra_interop/activepieces_loopback.py, openhands_local.py, workflow_bridge.py, com testes de cliente-servidor loopback, processos fixtures e transições por WorkItem. Testes focados: **119 passados**. SaaS Activepieces real, OpenHands Agent Server real e Temporal server real NÃO foram iniciados/homologados.

CRIT-003 implementou sentra_collab/physical_cables.mjs, novas rotinas de SQLite/recovery, e teste de lifecycle WS. Uma regressão detectada pelo coordenador gerou quatro falhas Node em precommit e desconexão após revogação/erro de DB; orientação QA enviada ao agente. Após correção de precommit pela equipe, nova execução independente **43/43 tests Node aprovados**, incluindo SQLite de 2 processos, rollback pós-crash e proibição de broadcast de atualização não persistida. Isso não liga o Canvas real nem fornece WSS de produção.

## Coordenador: três implementações e provas

### 1. OTLP / OpenTelemetry JSON loopback

Arquivos: sentra_runtime/otlp_sink.py e tests/unit/test_sentra_runtime_otlp_sink.py.
- Strict allowlist de eventos, estados, tamanhos e destino HTTP 127.0.0.1 /v1/traces; operação identificada somente por SHA256.
- POST OTLP/HTTP JSON para receptor real ThreadingHTTPServer controlado pelo teste.
- Erros sem retries automáticos; nenhum prompt, token ou saída bruta de terminal é enviado.
- **15 testes passaram**; não existe OTel Collector externo real ligado.

### 2. Grype / avaliação de vulnerabilidade de artefatos

Arquivos: sentra_quality/grype_gate.py, atualização da CLI em sentra_quality/__main__.py e tests/unit/test_sentra_quality_grype_gate.py.
- Avalia JSON Grype produzido EXTERNAMENTE com digest SHA256 obrigatoriamente fixado na CLI, limiares criticidade e negação fail-closed para schema inválido, duplicações, números NaN, severidade unknown e CVE bloqueante.
- Comando: python -B -m sentra_quality grype-check --report <arquivo-grype.json> --sha256 <digest-confiavel>.
- **20 testes de parser/CLI passaram** no conjunto; não houve execução do scanner Grype nem geração de SBOM/atualização de base CVE. Fazer o scanner real rodar em CI autorizado é condição adicional antes do release.

### 3. ControlStore: contrato durável de admissão fail-closed

Arquivos: sentra_runtime/durable_admission.py e tests/unit/test_sentra_runtime_durable_admission.py.
- Exige de autoridade confiável reserve_intent(run_id, owner, OperationRequest, sha256) atômico, receipt imutável e fencing_token válido, fence_active, record_result.
- Política antes e após reserva, idempotência; replay existente => UNCERTAIN + reconcile (nenhum novo efeito), erro de DB/fence => nega.
- Usa SQLite REAL como fixture de teste para CAS/dedupe/restart; não cria segundo controlador persistente em produção.
- Testa intencionalmente o sentra_mcp/services/durable.py legado: a API create_operation não possui fingerprint completo, logo **é recusada**, sem dispatch inseguro.
- **10 testes passaram** nesta primeira validação. Sem patch do proprietário do ControlStore, não habilitar execução externa real.

### Validação cruzada

- Testes próprios OTLP + Grype + durable: **45 aprovados**, sem falhas, antes das demais regressões.
- Testes anteriores SQLite audit ledger e source inventory continuam separados e com cobertura.
- Verificação de procedência terceira: **37/37 repos Git**, não implica licenças liberadas ou CVE-free.
- Testes de 33 arquivos em Python e suite Python completa iniciados após correção do Node; registrar números somente depois de concluídos com exit code 0.
- Todos os novos diretórios e testes seguem UNTRACKED no repositório base. Revisão/commit/CI apenas em gate coordenado próprio, sem git reset/clean ou commits globais.

## Gaps remanescentes: não esconder dependências

P0: sentra_mcp/services/durable.py::create_operation precisa reserva transacional persistente por fingerprint completo, lease/fence no ponto do efeito externo e crash recovery real. Não resolver usando ledger paralelo; depende do proprietário do módulo core.
P0: Canvas principal ainda não carrega a colaboração opcional; falta host real de identidade e grants e testes dois dispositivos WSS/TLS.
P0: UI Automation de aplicações pessoais, Daytona autenticado, Playwright browser fora do fixture, Guacamole/RustDesk remotos, Activepieces/ToolHive/OpenHands/Temporal externos exigem ambientes autorizados e testes E2E distintos.
P1: Keycloak/SPIRE/OPA/OpenFGA/NATS/OTel Collector/Tessera/immudb como infra opcional, sem instalação/ligação automática; benchmark WindowsWorld/WindowsAgentArena/OSWorld v2, SBOM e scan CVEs de release, backup/migração e conformidade.
P1: módulos novos não estão no produto/instalador nem no Git principal; incompatibilidades e transparência de licença necessitam revisão de release.

Regra de status: código existente/fixture E2E não equivale a produção homologada. Testes Node foram rerodados e a regressão de precommit corrigida, mas observar soak e integração em dois computadores antes de release.
