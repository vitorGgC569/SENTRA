# SENTRA — Relatório de Homologação P0-IMAGENS/COMPOSIÇÃO (Rodada 3 — 12/10/2026)

## 1. Escopo e Segurança

- **Frente:** P0-IMAGENS / COMPOSIÇÃO (Geração nativa de imagens no ChatGPT Web, ingestão via Edge MV3, Relay HTTP loopback, e Canvas Broker do SENTRA).
- **Checkout:** `C:\Users\vitor\OneDrive\Desktop\SENTRA` (Windows/PowerShell, dispositivo `OGrandeOxta`).
- **Fase executada:** **FASE 1 — Somente código, testes unitários e diagnóstico estritamente leitura**.
- **Controles rígidos obedecidos na Fase 1:**
  - Nenhum processo vivo foi reiniciado durante a Fase 1 (Relay PID 47492, Canvas Broker PID 48400, Microsoft Edge e a extensão permaneceram em seus estados originais).
  - Nenhuma mensagem ou requisição live (`BROWSER_ACTION`, submit de chat, ou geração artificial no ChatGPT Web) foi enviada aos processos vivos durante esta fase.
  - Apenas inspeções estritamente somente-leitura (`GET /health`, endpoints do broker de leitura, verificação de quiescência) foram executadas.
  - Nenhum comando de git mutante (`git reset`, `checkout`, `clean`, `commit`, `push` ou `stash`) foi acionado.
  - Nenhuma credencial ou token de pareamento foi impresso em disco, logs ou relatórios (tokens mantidos estritamente efêmeros em memória).
  - Nenhum arquivo proibido foi alterado (arquivos da VM, `dot_tool_receipts.py`, `shell_dot_canvas.py`, `shell_actor.py`, `control_plane.py` permaneceram intocados).

---

## 2. Diagnóstico Físico Somente Leitura (Estado Observado na Host)

Em 12/10/2026, sondas somente leitura executadas contra a máquina física observaram:

1. **Processos e Portas Vivas:**
   - **Canvas Broker:** PID `48400`, escutando na porta `62862` com `runtime_id` autenticado via segredo central em `.sentra/canvas`.
   - **Standalone Relay:** PID `47492`, escutando na porta `8765`.
   - **Estado de fila e locação:** `relay_queued: 0`, `relay_leased: 0` (sistema completamente quiescente, sem tarefas pendentes).
   - **Extensão Edge:** Conectada (`extension_online: true`), mas com código em memória prévio à Rodada 3.
   - **Sinalizadores de configuração no Relay atual (PID 47492):**
     - `relay_web_send_configured: false`
     - `relay_generated_assets_configured: false`
     - `relay_reason: "binary_relay_not_configured"` em todos os 3 workspaces inspecionados (`96438791c6`, `97c4eb092e`, `680ceb4239`).

2. **Evidência Estruturada de Pré-Voo (`scripts/commander/qa_native_image_e2e.py --dry-run`):**
```json
{
  "mode": "dry_run",
  "broker_verified": true,
  "broker_info": {
    "pid": 48400,
    "port": 62862,
    "runtime_id_verified": true
  },
  "relay_live": true,
  "relay_web_send_configured": false,
  "relay_generated_assets_configured": false,
  "extension_online": true,
  "extension_build_matches_checkout": true,
  "quiescent": true,
  "workers_online": 0,
  "ready_projects_count": 0,
  "planned_action": "WOULD_CREATE_ONE_QA_OPERATION_AND_FETCH_GENERATED_MEDIA",
  "uncertainty_policy": "observe_only_no_resend",
  "admission_ready": false
}
```

---

## 3. Causa Raiz Confirmada

Três fatores conjunturais impediam o funcionamento de ponta a ponta da geração nativa de imagens no SENTRA:

### 3.1. Lacuna de Composição Hospedeira (Host-Owned Composition)
- **Problema:** O servidor de relay inicializado via `main.py --relay` ou standalone era instanciado diretamente sem os atestadores centrais (`authenticated_control=None`, `assistant_observer=None`). Consequentemente, `state.web_send` e `state.generated_assets` permaneciam `None`, rejeitando rotas como `/jobs/generated-asset/chunk` e `/jobs/generated-asset/finalize`.
- **Lado Canvas:** O Canvas Broker nunca chamava `attach_shell_relay_observers()`, e a configuração padrão carregada por `load_shell_configuration()` não continha a seção `web_relay` habilitada, resultando em `model_delivery_reason="binary_relay_not_configured"` para todos os modelos Web aprovados.

### 3.2. Falha de Injeção no Content-Script Edge MV3 (`'content-script returned no result'`)
- **Problema:** No Service Worker do Edge (`edge_extension/service-worker.js`), quando uma aba do ChatGPT já estava aberta antes da extensão ser carregada ou sofria reinicialização do ciclo de vida MV3, o envio de mensagens via `chrome.tabs.sendMessage` falhava com resposta vazia ou erro de comunicação porque o `content-script.js` não havia sido injetado dinamicamente naquela aba adotada.
- **Protocolo:** A constante `BROWSER_ACTIONS` em `native_bridge/protocol.py` não continha as ações de leitura e status (`"approval_status"`, `"stream_snapshot"`, `"attach_info"`, `"model_catalog"`), provocando falhas estritas de validação em payloads emitidos pelo navegador.

### 3.3. Modelo de Posse de Processos e Conflito de Porta 8765
- **Problema:** Quando tanto o `main.py --relay` quanto o Canvas Broker tentavam operar o Relay na porta 8765, ocorria colisão de portas (`OSError: Address already in use`).
- **Definição de Arquitetura:** O **Canvas Broker é o proprietário autoritativo da porta 8765**. Ele hospeda em processo o `ControlPlaneService`, o `ShellWebRuntime` e a instância oficial de `RelayServer` já composta com os atestadores reais. O comando `main.py --relay` passa a adotar política fail-closed e graciosa: se a porta 8765 já estiver ocupada pelo Broker com segredo válido, não força dual-bind.

---

## 4. Arquivos Alterados e Implementação Realizada

| Arquivo | Mudança Realizada |
|---|---|
| `native_bridge/protocol.py` | Adicionadas ações autorizadas em `BROWSER_ACTIONS`: `"approval_status"`, `"stream_snapshot"`, `"attach_info"`, `"model_catalog"`. |
| `edge_extension/service-worker.js` | Implementada função `omaEnsureContentScript(tabId)` usando `chrome.scripting.executeScript` com a cadeia `["recovery-guard.js", "selectors.js", "observer.js", "content-script.js"]`. Atualizado `omaSendToTab` para realizar injeção sob demanda em caso de falha de retorno do content script. Garantida injeção em abas adotadas (`omaEnsureTabWorker`) e abas existentes (`omaEnsureRecoveryGuardOnExistingTabs`). |
| `edge_extension/manifest.json` | Carimbado com `scripts/commander/extension_identity.py` gerando o hash `ac9cfe0d959692bb63c7da3cf61d79abf50459d6780a47acd479f8c30fe8f510`. |
| `native_bridge/host_attestors.py` *(novo)* | Implementada composição hospedeira real (`create_host_attestors`, `make_account_attestor`, `make_assistant_observer`). Valida coletor real contra o banco SQLite do Control Plane (`browser_collectors`, `browser_profile_uncertainty`, `browser_revoked_documents`, `browser_document_epochs`, `StreamingLedger`). Sem nenhum mock. Fail-closed total. |
| `sentra_canvas/shell_optional.py` | Atualizado `load_shell_configuration` para inspecionar `.sentra/shell_config.json`, `shell.json`, e variáveis de ambiente, fornecendo configuração padrão de `web_relay` habilitada com os modelos suportados (`gpt-5`, `gpt-6`, etc.) quando `.sentra` existe. |
| `sentra_canvas/service.py` | Atualizado `Canvas.__init__` para invocar `_compose_web_relay_startup()`: instancia os atestadores centrais com `create_host_attestors` e conecta `self.attach_shell_relay_observers(...)` fail-closed. |
| `native_bridge/relay.py` | Expostos os sinalizadores `"web_send_configured"` e `"generated_assets_configured"` no endpoint `/health`. |
| `main.py` | Atualizado `serve_relay` para compor o `RelayServer` com `ControlPlaneService.from_store(PROJECT_ROOT / ".sentra")` e `create_host_attestors`, tratando graciosamente conflitos de porta caso o Canvas Broker já esteja rodando. |
| `scripts/commander/qa_native_asset_production_probe.py` | Ajustado para exibir `relay_web_send_configured` e `relay_generated_assets_configured`. Garantida inclusão do repositório no `sys.path`. |
| `scripts/commander/qa_native_image_e2e.py` *(novo)* | Sonda de ponta a ponta segura. Opera por padrão em `--dry-run` (somente leitura estruturada). Modo `--execute` restrito a 1 única operação/WorkItem de QA, captura de bytes, cálculo de SHA-256 e comparação estrita com `/api/shell/generated-media`. Política fail-closed: em caso de incerteza (`UNCERTAIN`), somente observa, nunca reenvia. |
| `tests/unit/test_shell_relay_composition.py` *(novo)* | Suite completa de testes unitários para composição: atestadores reais, recusa fail-closed sem atestadores, verificação das rotas `/jobs/generated-asset/chunk` e `/jobs/generated-asset/finalize`, e ciclo de vida do Canvas. |

---

## 5. Resultados dos Testes Automatizados

### 5.1. Regressão Completa Python (Pytest)
Comando executado:
```powershell
python -m pytest -q tests/unit/test_shell_relay_composition.py tests/unit/test_web_native_generated_assets.py tests/unit/test_shell_generated_media.py tests/unit/test_sentra_cos_web_relay_authenticated_routes.py tests/unit/test_sentra_cos_web_v2_http_ingress.py tests/unit/test_sentra_cos_web_r6_full_cycle.py tests/unit/test_shell_web_preview.py
```
**Resultado:**
- **39 passed in 39.59s** (0 failed, 0 errors, 100% de aprovação).

Detalhamento por módulo:
- `tests/unit/test_shell_relay_composition.py`: 6 testes aprovados (falha closed sem atestadores, atestadores reais ativam `generated_assets`, rotas rejeitam sem composição, atestador de contas rejeita coletor não matriculado, atestador aceita com coletor real no SQLite, inicialização com `attach_shell_relay_observers`).
- `tests/unit/test_web_native_generated_assets.py`: 5 testes aprovados.
- `tests/unit/test_shell_generated_media.py`: 8 testes aprovados.
- `tests/unit/test_sentra_cos_web_relay_authenticated_routes.py`: 8 testes aprovados.
- `tests/unit/test_sentra_cos_web_v2_http_ingress.py`: 7 testes aprovados.
- `tests/unit/test_sentra_cos_web_r6_full_cycle.py`: 2 testes aprovados.
- `tests/unit/test_shell_web_preview.py`: 3 testes aprovados.

### 5.2. Testes da Extensão Edge MV3 (Node.js Test Runner)
Comando executado:
```powershell
node --test tests/unit/web_native_evidence.test.cjs
```
**Resultado:**
- **3 passed in 100.3ms** (0 failed, 0 errors).
- Sintaxe de `edge_extension/service-worker.js` validada com sucesso via `node --check edge_extension/service-worker.js`.

---

## 6. Runbook Exato da Fase 2 (Procedimento de Deploy e Homologação)

A Fase 1 está concluída. Para ativar as mudanças no ambiente de produção local durante a Fase 2, seguir a seguinte ordem de execução estrita:

### Passo 1: Verificação de Quiescência Pré-Deploy
Garantir que nenhum trabalho esteja em andamento na máquina host:
```powershell
python scripts/commander/qa_native_image_e2e.py --dry-run
```
Verificar se no JSON impresso:
- `"quiescent": true` (`relay_queued == 0` e `relay_leased == 0`).
- Nenhuma operação ativa em execução nos workspaces.

### Passo 2: Encerramento do Standalone Relay Antigo
Encerrar o processo de relay legado (PID `47492`) para liberar a porta 8765:
```powershell
Stop-Process -Id 47492 -Force
```
*(Confirmar que a porta 8765 foi liberada via `netstat -ano | findstr 8765`).*

### Passo 3: Recarregamento da Extensão no Edge
1. No Microsoft Edge, abrir `edge://extensions`.
2. Localizar a extensão SENTRA (ou recarregar se em Developer Mode).
3. Clicar no botão **Reload** (ícone de recarregar) da extensão.
4. Isso carregará o novo `service-worker.js` contendo o mecanismo de injeção dinâmica e o novo `sw_source_hash` (`ac9cfe0d959692bb63c7da3cf61d79abf50459d6780a47acd479f8c30fe8f510`).

### Passo 4: Reinício do Canvas Broker como Dono da Porta 8765
1. Encerrar o Canvas Broker legado (PID `48400`).
2. Iniciar o Canvas Broker com o código atualizado:
```powershell
python -m sentra_canvas.broker
```
3. O Canvas Broker inicializará internamente o `RelayServer` já composto com os atestadores centrais (`create_host_attestors`), passando a responder na porta `8765` com suporte a `web_send` e `generated_assets`.

### Passo 5: Verificação de Saúde Pós-Deploy
Executar a sonda de pré-voo:
```powershell
python scripts/commander/qa_native_image_e2e.py --dry-run
```
Verificar se o retorno indica:
- `"relay_live": true`
- `"relay_web_send_configured": true`
- `"relay_generated_assets_configured": true`
- `"extension_build_matches_checkout": true`
- `"admission_ready": true`

### Passo 6: Execução do Teste Real de Geração Nativa (Turno Único)
Com uma aba do ChatGPT Web aberta e com sessão autenticada, executar:
```powershell
python scripts/commander/qa_native_image_e2e.py --execute
```
**Regras de Homologação da Fase 2:**
1. Cria exatamente 1 WorkItem / 1 Operação de teste.
2. Solicita geração de 1 imagem no ChatGPT.
3. A extensão captura os chunks e finaliza via `/jobs/generated-asset/chunk` e `/jobs/generated-asset/finalize`.
4. O SENTRA registra o recibo `sentra.generated_asset` com SHA-256 e `file_id`.
5. O script busca os bytes através do endpoint autenticado `/api/shell/generated-media` e compara o hash SHA-256 byte a byte.
6. **Política de Incerteza:** Se o status for `UNCERTAIN` ou houver atraso de ACK, o sistema **SOMENTE OBSERVA** e jamais reenvia o prompt.
