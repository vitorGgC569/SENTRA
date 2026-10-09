# SENTRA EXEC-001 — Sprint 3x3 Fase 2 (2026-10-09)

Escopo autorizado: `sentra_executors/`, `tests/unit/test_sentra_executors_*.py`.
NENHUMA alteracao de core, runtime, native Canvas, sentra_interop,
sentra_collab, qualquer perfil pessoal, dados/segredos ou clones upstream.
Todas as interfaces permanecem **opt-in**, sem provisionamento automatico.

## FATIA 1 — Playwright MCP selected / navegador de laboratorio

**Codigo:** `browser_lab.py` (`BrowserLabExecutor`,
`BrowserReadBinding`, `PlaywrightReadOnlyBackend`,
`parse_browser_read_query`, `declare_browser_lab_machine`).

- `browser.read_page`: unico metodo de consulta permitido, convertendo
  query tipada em `OperationRequest` via ExecutorRegistry com PolicyDecision.
- `url` exige `http://127.0.0.1:<porta>/...` ou IPv6 literal `[::1]`;
  hostname `localhost` deliberadamente recusado (possivel remapeamento
  de DNS/hosts); exact URL bound to pre-approved capability.
  Proibidos Edge profile, cookies existentes, storage_state, acesso por
  extensao, CDP, HTTPS externo, file://, credentials em URL, redirect,
  outros metodos MCP, mouse/keyboard.
- Backend Playwright real exige `explicitly_approved=True` na construcao.
  Usa exclusivamente `chromium.launch_persistent_context(user_data_dir=
  TemporaryDirectory('sentra-browser-lab-...'))`, sem channel msedge,
  JS desabilitado, downloads false, service workers block, permissions=[],
  interceptacao de **todas** network requests: so documento principal exato
  e permitido. Closing e remoção do perfil num finally.
- `test_sentra_executors_browser_phase2.py`: servidor HTTP real
  127.0.0.1 porta efemera (thread stdlib), fixture browser controlada
  sem cookies/redirect/proxy; testes contra outbound, URL nao
  allowlisted, query eval/cookie/mouse, policy/revocation, replay.
  Producao `PlaywrightReadOnlyBackend.run` exercitada tambem com
  modulo Playwright *fixture* que prova perfil TEMP unico, exclusao
  apos teardown, bloqueio de request externa e ausencia de MS Edge.
- E2E browser REAL: skip a menos que `SENTRA_BROWSER_LAB_APPROVED=1`
  E `SENTRA_BROWSER_ISOLATED_VM=1`. Playwright Python e Chromium
  no disco foram encontrados, mas **nao executados** por falta de
  autorizacao/VM. Browser nunca instalado automaticamente.
- **Nota importante:** route/browser profiles NAO sao isolamento
  de rede OS ou politica SSRF forte; para alvo de risco, exigir firewall
  OS e browser sandbox verificados, nao liberar outros localhost services.

**Status:** [E2E FIXTURE APROVADO + HTTP LOOPBACK REAL] /
[E2E PLAYWRIGHT REAL BLOQUEADO].

## FATIA 2 — Guacamole/RustDesk selected / gateway read-only

**Codigo:** `remote_readonly.py` (`RemoteReadOnlyExecutor`,
`RemoteReadBinding`, `AuthenticatedLoopbackTransport`,
`declare_remote_readonly_machine`).

- Gateway e **protocolo de sessao SENTRA proposto**; nao implementa
  protocolo RDP, VNC, guacd nem RustDesk. Transport Protocol com
  `socket.create_connection(('127.0.0.1', port))` e timeout, nao permite
  IP remoto, hostname arbitrario, UDP, mouse/teclado, clipboard ou shell.
- Autenticacao mutua de servidor e cliente via HMAC-SHA256,
  challenge com nonce aleatorio fresh, prova do reply assinada;
  assinatura inclui machine peer, nonces e metodo.
  Frame JSON-linha < 2 KiB, apenas `read.status` e
  `read.frame_digest` (SHA-256), respostas com esquema estrito.
  Segredo compartilhado `RemoteReadBinding.shared_secret` com
  `repr=False`, sem dados em logs nem no OperationResult.
- `GuardedExecutor` + `ExecutorRegistry` exigem capability,
  principal, PolicyDecision real antes/depois; timeout vira UNCERTAIN,
  replay de operacao existente nao repete request socket.
- `test_sentra_executors_remote_phase2.py`: cliente e servidor
  loopback TCP reais em thread/sockets stdlib, handshake autenticado
  bidirecional, replies assinadas. Negativas: wrong-server-key,
  reply adulterado, requests mouse/keyboard/shell, host outbound,
  segredo curto, timeout sem reexecucao, revogacao de policy.
- **Nao** adicionada infraestrutura Guacamole nem servidores RustDesk;
  uso remoto real com TLS/gateway especializado, consentimento,
  provisioning e autenticacao deve ser fase independente.

**Status:** [E2E LOOPBACK TCP REAL + SERVIDOR FIXTURE] /
[GUACAMOLE/RUSTDESK REAL BLOQUEADO].

## FATIA 3 — identidade de processo Windows, creation time, hash + lease

**Codigo:** `windows_identity.py` (`ProcessIdentity`,
`FenceLease`, `IdentityUIABinding`, `WindowsIdentityProbe`,
`IdentityGuardedUIAExecutor`, `declare_hardened_windows_machine`).

- Capability explicitamente `windows_uia_hardened` do registry.
  SOMENTE a acao `read_window_title`; titulo
  `SENTRA-UIA-LAB-...`; PID/HWND allowlisted.
- Processo: GetWindowThreadProcessId(hwnd), OpenProcess com
  PROCESS_QUERY_LIMITED_INFORMATION, GetProcessTimes cria
  `creation_filetime` nativo Windows; QueryFullProcessImageNameW
  do processo **ja autorizado**, SHA256 de executavel, fecha handle.
  **Nenhuma** varredura por processos ou janela pessoal; hash do
  executavel real so no subprocesso proprio do lab se opt-in.
- Fence `FenceLease(lease_id, token:int positivo,
  expires_monotonic)` tipado, comparado com autoritativo
  `lease_reader(lease_id)` injectado (nao claims do agente) e
  `identity_probe(pid,hwnd)` injectado.
  `_execute` revalida ambos imediatamente **antes e depois**
  de `PywinautoUIABackend.run`. Divergencia -> FAILED sem
  divulgar evidencia (read-only nao reverte leitura passada).
  `GuardedExecutor` tambem consulta policy ao despachar.
- `test_sentra_executors_identity_phase2.py`: registry real,
  identity/lease fixtures, drift creation time e SHA, lease epoch,
  expiracao, falso objeto, pid/token forged, mutacao apos leitura,
  negacao invoke/janela pessoal, replay e revogacao.
- Tk processo **OWNED** real: teste condicional
  `SENTRA_UIA_LAB_RUN=1` E
  `SENTRA_UIA_LAB_VM_CONFIRMED=1` + pywinauto + ambiente
  Windows interativo. Teste cria somente seu filho Python Tk,
  encontra seu HWND, mede create-time/hash, executa pelo Registry,
  encerra filho. NAO executado no host pessoal.

**Status:** [E2E FIXTURE APROVADO] / [E2E UIA/TK REAL BLOQUEADO].
**P0:** app user/VM isolada de fato, privilégio reduzido, lease
duravel e fencing transacional no ControlStore; rechecagem usuario
nao torna UIA atomicamente segura e NAO equivale a AppContainer,
hcsshim/Hyper-V, gVisor, VM isolation.

## Matriz de upstream / licencas e razao da absorcao seletiva

| Fonte cloned | Codigo/padrao estudado | Incorporacao EXEC-001 | Licenca/evidencia | Motivo para nao copiar |
|---|---|---|---|---|
| `third_party/playwright-mcp` | README (--isolated, --user-data-dir, --allowed-origins / NOTE redirect) | Fluxo de consulta read-only em perfil temp; nao registra MCP host | Playwright-MCP: verificar LICENCE upstream antes de distribuir; apenas padrao | CLI npx, extensao Edge, generic browser tools ou side effects ampliariam superficie |
| `third_party/guacamole-server` | README guacd, libguac, proxy RDP/VNC | Challenge-response TCP JSON restrito, nao implementa protocolo Guacamole | Apache Guacamole mantem suas notices; apenas referencia | Proxy RDP/VNC instalacao onerosa; transporte nao e autenticacao SENTRA |
| `third_party/guacamole-client` | README HTML5 desktop | Nenhum cliente externo copiado | Apache notices; apenas referencia | Browser viewer remota exporia pixels e input sem governanca |
| `third_party/rustdesk` | README relay/rendezvous desktop | Somente ideia de session layer; sem RustDesk wire protocol | Examinar AGPL/NOTICE/versionamento antes de redistribuir | Permissividade de desktop remoto e dependencias nao justificadas |
| `third_party/ufo` | app scoped UIA e action execution | Explicit PID/HWND and no dynamic reflection | MIT (LICENSE upstream), implementacao independente | Controle global/pyautogui risco no host |
| `third_party/hcsshim` | Windows Host Compute Service | Nenhuma API chamada; VM/contêiner futuro | Revisao de licenca no upstream antes do uso | Nao e isolamento de GUI pessoal interativa |
| `third_party/gvisor` | OCI runsc Linux sandbox | Nenhuma API chamada | Licenca/NOTICE do upstream ao empacotar | Nao isola Windows desktop |

Licencas upstream nao foram incorporadas por copia: **nenhum codigo de
terceiros foi vendorizado**. A matriz identifica referencias, nao a
integracao de bibliotecas inteiras.

## Execucao e evidencias

Comando PowerShell:

```powershell
cd C:\Users\vitor\OneDrive\Desktop\SENTRA
$env:PYTHONDONTWRITEBYTECODE='1'
$files = @(Get-ChildItem tests/unit -Filter 'test_sentra_executors_*.py' -File |
  Sort-Object Name | ForEach-Object { $_.FullName })
python -B -m pytest -p no:cacheprovider -q -rs -rx $files
```

**Resultado FINAL desta sessao:** dez arquivos,
`162 passed, 3 skipped in 4.92s`, exit 0. Smoke de
contratos/auditoria do core (executado antes do ultimo teste de
redirect, sem edicao do core): `21 passed in 0.29s`, exit 0.
Skips: Playwright real e dois E2E UIA reais, por falta de
laboratorio isolado aprovado. O teste de redirect HTTP negado
ja esta incluido entre os 162 passed. Teste TCP real loopback
nao exigiu infra externa.

P0 futuro: rede OS firewall e profile attestacao; integracao
ControlStore de grants e lease fencing autoritativo; provisionar
guacd ou RustDesk so apos decision de produto e consentimento.
P1: browser real isolado e remote service sobre TLS, deteccao
de drift de processo / PID reuse em VM dedicada, tests sob CI Windows.

**Status geral:** 3 implementacoes locais E2E fixtures,
nao 3 projetos externos totalmente incorporados. Sem secrets/credenciais,
nada feito em apps pessoais, servidores terceiros nem Git reset/clean.
