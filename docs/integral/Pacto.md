# Pacto — entrega da expansão integral (Code Mode bounded real + MCPB + Skills + superfícies mínimas + consentimento)

Data: 2026-10-11. Fase: implementação integral; **validação ao final, ainda não executada** (sem testes, build, lint, benchmark, QA ou homologação). Nada homologado nesta fase.

Ordem atual (docs/integral/tasks/Pacto.md): A08 exige runtime QuickJS WASM REAL bounded — deny-only não cumpre. Fixar artefato/SBOM; limitar fuel, CPU, memória, wall time, tool calls, source e result; sem IO host/imports WASI, com watchdog/cancel. Toda ferramenta interna passa por OperationRequest/grant/fencing; sem fallback eval/Node VM. MCPB stdio/HTTP/OAuth PKCE, supervisão/restart/sandbox/uninstall e colisão de nomes inclusive disabled; surfaces mínimas autorizadas. Skills/packs Git SHA/review/update/revoke/rollback; ChatTrust/block e read/action consent nunca criam grant. Publicar assinatura de execute/dispatch/status e esquema para composição central.

## 1. Requisitos do domínio (fontes lidas integralmente)

- Nota Maestri `todos-os-projetos-ja-estao-clo` (via docs de implementação): prioridades 5 (Plugins, Skills e interoperabilidade), aprovação humana durável, recibos, isolamento host/executor.
- `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md`: P0 (MCPB/plugin lifecycle, `pluginExposure()`, gates sem-colisão/grant-por-capability/sem-segredos-em-logs/uninstall-idempotente), P1 Skills versionadas, P1 API local de observação/ações opt-in (dois consentimentos), A07 (superfícies MCP por domínio, tool sets mínimos, uma autoridade), A08 (Code Mode QuickJS WASM como compositor sem IO host; cada ferramenta interna exige OperationRequest/grant/fencing), A10 (leitura/ação com duas chaves), A21 (skill packs GitHub fixados em SHA, update/revoke), Fatia 2 (Correlation + ChatTrust/Blocked + ApprovalWait), Fatia 4 (GC de workers, staged update), Fatia 5 (Code Mode restrito com budgets).
- `docs/SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md`: ToolHive somente sob policy por ferramenta.
- `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md` + `docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md` (Pacto não cria endpoint autenticado paralelo nem expõe `owner` ao renderer).
- Entrega anterior deste responsável (seções 2–5 abaixo preservam o que já existia; o deny-only do Code Mode foi removido e substituído por execução bounded real).

## 2. Arquivos alterados/criados (somente domínio Pacto; mudanças alheias preservadas)

| Arquivo | Mudança (expansão atual) |
|---|---|
| `sentra_code_mode/__init__.py` | `ResourceLimits` estendido (`max_tool_calls`, `max_arg_bytes` com tetos); novas exceções `CodeModeUnavailable`/`CodeModeCancelled`/`CodeModeBudgetExceeded`; `QuickJSArtifact` (pin wasm+SBOM SHA256); `QuickJSWasmAdmission.status()` passa a reportar prontidão real via `QuickJSWasmRunner.readiness()`; `execute()` legado virou rampa para `CodeModeDispatcher.dispatch()` (sem eval). |
| `sentra_code_mode/bounded_js.py` (NOVO) | Interpretador bounded do subset JS documentado (stdlib only, sem eval/exec/subprocess): literais, var/let/const, aritmética/comparação/lógica, if/else, while/for, function/return (recursão limitada), arrays/objetos, `call_tool(name,args)` como única ponte host. Fuel por statement/iteração, memória por tamanho serializado, teto de concat/expoente/profundidade, `max_tool_calls`/`max_arg_bytes`/`max_result_bytes`. Sem Date/IO/imports/eval/Function. |
| `sentra_code_mode/quickjs_runtime.py` (NOVO) | Runner QuickJS WASM REAL: verifica pin (magic, tamanhos, sem symlink, SHA duplo, SBOM CycloneDX) a cada run; `wasmtime` com fuel, sem WASI (rejeita qualquer import fora `host.call_tool`), watchdog thread + interrupt, flag de cancel, outbox limitada de tool calls. Sem artefato/`wasmtime`/ABI `sentra_eval` → `CodeModeUnavailable` explícito (nunca deny silencioso, nunca eval). |
| `sentra_code_mode/dispatcher.py` | Reescrito: `propose()` (admissão inerte + `engine`), `execute()` REAL (replay idempotente por operation_id, recibos `code_mode_executions` RUNNING/SUCCEEDED/FAILED/CANCELLED, wall watchdog + cancel, result SHA/bytes), `dispatch()` (propose+execute), `status()` (proposta + execuções + limites + cancel), `cancel()` (flag observada pelo watchdog/interrupt; propostas inertes vão a CANCELLED). Ponte `_FencedToolBridge`: um OperationRequest por `call_tool` via `CentralInteropAdapter` (capability `code-tool:<nome>`, handlers host-selected allowlisted, checkpoint/fencing, re-checagem de grant). Fonte reexigida por digest (sem segunda store de source). Tabelas migradas com `ALTER` defensivo. |
| `sentra_code_mode/schema.py` (NOVO) | `CODE_MODE_SIGNATURE`: motores, métodos, ponte de tools, schemas de limites/artefato, ações de shell (`code_propose`/`code_execute`/`code_status`/`code_cancel`), erros e invariantes — para composição pelo Codex. |
| `sentra_mcp/services/mcpb_lifecycle.py` (NOVO) | Fachada `MCPBLifecycleService` + `MCPB_LIFECYCLE_SIGNATURE`: `transport_status` (registro+HTTP+supervisão, read-only), `dispatch_tool` (stdio via `PluginWorkerHost.call` / HTTP via `MCPBWorkItemLifecycle.call_http_tool`, nunca direto), `restart_ticket` (fail-closed, via `restart_authorized`), `sandbox_spec` (plano inerte + flag de imagem pinada), `uninstall` (tombstone via catalog), `collision_check` (via `conflict_report`, inclui disabled). Nenhuma autoridade paralela, nenhum grant. |
| `sentra_mcp/services/skill_library.py` | `review()` (metadados + frontmatter + inventário com SHA por arquivo, sem divulgar conteúdo a WorkItem, sem executar) e `rollback_activation()` (rollback aprovado para SHA anterior mesma-origem; revogado nunca ressuscita; sem grants). Herança anterior preservada (`versions`/`latest`/`upgrade_activation`/`replace_activation`/`revoke`/`activate`/`deactivate`/`disclose`). |
| `sentra_mcp/tool_policy.py` | `composition_surface()` (colisões incl. disabled + snapshot mínimo por conversa em uma chamada; fail-closed em qualquer negação; sem reserva, sem grants). |
| `sentra_canvas/desktop_ui/src/skill-library-dialog.jsx` | Botões "Revisar" (ação `review`, tolerante) e "Reverter para esta revisão" (ação `rollback`, mesmo nome/origem, aprovado). Degradam para erro do servidor até fiação. |
| `sentra_canvas/desktop_ui/src/plugin-bundles-dialog.jsx` | Seção "Code Mode" (motor/prontidão/limites, tolerante à ausência de `code_mode`); estado `codeMode` alimentado por `refresh()`. |
| Anteriores preservados (sem alteração nesta expansão) | `tool_exposure.py:conflict_report`, `mcpb_supervision.py`, `action_consent_gate.py:pending_intents/intent_status`, `chat_access.py:conversation_consent_summary`, `tool_policy.py:minimal_surface_snapshot`, demais `mcpb_*`/`plugin_*` existentes. |

Nenhum arquivo de outro dono foi editado. Sem commit/push/reset/stash. Sem testes/builds/lint/QA executados.

## 3. Contratos de integração (solicitações aos donos — implementar na composição)

- **Codex** (`sentra_canvas/service.py`, `server.py`, `graph.py`): instanciar `CodeModeDispatcher(control, engine='bounded-js')` (+ `QuickJSArtifact` quando o artefato auditado existir) e `MCPBLifecycleService(control)` na composição, sem segunda autoridade; expor via endpoints existentes `/api/center/skill-library` (ações `review` → `SkillLibrary.review`, `rollback` → `SkillLibrary.rollback_activation`, além de `upgrade`/`versions` já publicados), `/api/center/plugin-bundles` (incluir `code_mode` via `QuickJSWasmAdmission(...).status()` e `supervision` já publicado); registrar ações de shell `code_propose`/`code_execute`/`code_status`/`code_cancel` → `dispatcher.propose/execute/status/cancel` (schemas em `sentra_code_mode/schema.py:CODE_MODE_SIGNATURE`); registrar nomes `sentra_code_mode`/`pacto`/`mcpb-lifecycle` em `reserve_core_names` se novas tools surgirem. Handlers de tools do Code Mode devem ser callables host-selected (nunca texto JS/modelo).
- **Nexo** (`sentra_core/*`, `control_store.py`): confirmar que `control.durable.run_status` + `control.work_item_info` + `control._agent_from_run` permanecem o contrato de vínculo WorkItem usado por `CodeModeDispatcher` e `SkillLibrary`; tabelas novas usam namespaces `governance`/`chat_access`/`plugin_bundle`/`plugin_worker` existentes.
- **Prisma** (shell/conversa UI): consumir `code_*` e `review`/`rollback` somente via `shellBridge`; nunca converter prosa livre em aprovação/execução — execução exige proposta admitida + operation_id/idempotency; aprovação de efeitos continua exigindo os dois consentimentos (`allow_api`/`approve_action`).
- **Tessela/Vitra/Brisa/Rastro/Pulso/Selo/Forja/Lume**: sem dependência bloqueante; `composition_surface()` e `MCPBLifecycleService.collision_check()` disponíveis para handshake de superfícies e revisão de manifestos.

## 4. Pendências reais e limites honestos (atualizado na rodada de conclusão)

- ✅ Concluído no domínio Pacto: configuração do artefato (`sentra_code_mode/artifact_config.py` — loader via env + `describe_configuration()` + `build_admission()`), helpers drop-in de composição (`sentra_code_mode/composition.py` — `build_code_mode`, `normalize_shell_envelope` com alias `ws`→`project_id` + `request_key`, `dispatch_skill_library_extra`, `dispatch_code_center`, `dispatch_mcpb_extra`), assinatura publicada (`schema.py` + `MCPB_LIFECYCLE_SIGNATURE`).
- ⏳ Fiação nos endpoints de `service.py`/`server.py` e ações de shell `code_*`/`review`/`rollback`/`versions`/`latest`/`upgrade`/`replace`/`deactivate` (dono: Codex registro, Prisma cliente) — verificado por leitura em 11/10/2026: `service.py:center_skill_library` ainda trata só `list/import/git/github/revoke/activate/disclose`; `server.py` sem referências a `code_mode`/`mcpb_lifecycle`/`rollback`/`review`. Pacto não edita esses arquivos; os drop-ins acima reduzem a fiação a poucas linhas.
- ⏳ Runtime QuickJS WASM convidado: guest C real + ABI v1 exata + build.sh +
  runner host reescrito (esta rodada, seção 7). Upstream pinado de verdade
  (quickjs-2026-06-04, SHA + tamanho verificados por download). Falta:
  toolchain WASM neste workspace → binário `.wasm` ainda NÃO construído;
  distribuição (Vitra) deve rodar `guest/build.sh` e embarcar `dist/`;
  `wasmtime` ainda não instalado; fiação central do Codex ainda ausente.
  `engine='quickjs-wasm'` (agora o default) retorna `CodeModeUnavailable`
  explícito até lá. `bounded-js` é interim opt-in (`a08_satisfied: false`
  em todo recibo) e NUNCA a solução A08.
- 🤝 Lume (MCP factory): `sentra_interop/provider_machine.py`
  (`InteropProviderMachine`) + `mcp_session.py` (`MCPSDKProcessClient`,
  `MCPProviderSession`) + SDK oficial em `sentra_interop/sdk/` conferidos por
  leitura em 11/10/2026 (aceso; `docs/integral/Lume.md` ainda não publicado).
  Posição Pacto: stdio continua via `PluginWorkerHost` com gate (nunca `_call`
  raw); `MCPProviderSession`/`MCPSDKProcessClient` são ponto de injeção
  host-side com gate real injetado (nota no docstring de
  `MCPBLifecycleService`); `_call` nunca chega ao renderer; descriptor scripts
  nunca são autoridade. Nenhum arquivo de Lume editado.
- ⚠️ DECLARAÇÃO HONESTA: a frente Pacto NÃO está integralmente implementada enquanto faltarem (a) artefato guest QuickJS auditado + `wasmtime` distribuído e (b) fiação central do Codex. Nenhum fechamento por presença de módulo.
- `bounded-js` não cobre todo o JavaScript; fontes fora do subset falham com `SyntaxError` explícito (recibo FAILED), nunca com execução parcial silenciosa.
- `wasmtime` é dependência opcional nova (somente `quickjs-wasm`); `bounded-js` usa só stdlib.

## 6. Rodada de conclusão (pendências concretas do domínio Pacto, 11/10/2026)

| Arquivo | Conclusão |
|---|---|
| `sentra_code_mode/artifact_config.py` (NOVO) | `describe_configuration()` (só presença, sem bytes), `load_artifact_from_env()` (4 vars `SENTRA_QUICKJS_*`; falta qualquer uma → `CodeModeUnavailable` com remediação), `build_admission()` (com pins ou explicitamente desconfigurado). Sem download/fetch/bytes padrão. |
| `sentra_code_mode/composition.py` (NOVO) | `build_code_mode(control, ...)` (auto-carrega pins do env para `quickjs-wasm`); `normalize_shell_envelope()` (allowlist, `request_key` em mutações, `project_id` canônico, alias `ws` removido da saída); `dispatch_skill_library_extra()` (read-only sem scope; mutações com scope WorkItem, `rollback` aprovado na rota owner autenticada); `dispatch_code_center()` (async; `tools` omitido = `call_tool` negado); `dispatch_mcpb_extra()` (read/inertes + `uninstall` com approval; `dispatch_tool` async fica na rota chamadora). Zero autoridade própria. |
| `docs/integral/Pacto.md` | Esta atualização de progresso + declaração de não-integralidade acima. |

Verificação de composição por leitura (sem executar nada): fiação Codex ainda ausente (detalhe na seção 4). Nenhum arquivo de outro dono editado. Sem commit/push/reset/stash. Sem testes/builds/lint/QA executados. Relatório por arquivo (sem `ask` bloqueante enquanto o Codex trabalha).

## 7. Guest QuickJS real — ABI v1, proveniência, assinaturas (11/10/2026)

bounded-js é interim explícito e NUNCA a solução A08 (`a08_satisfied: false`
em todo recibo; default do dispatcher/composition/schema agora
`quickjs-wasm`). Nenhuma ABI inventada: cada entrada abaixo tem implementação
no guest C e marshaler correspondente no runner host.

| Arquivo | Conteúdo |
|---|---|
| `sentra_code_mode/guest/sentra_quickjs_guest.c` | Guest C real: `configure` (recria runtime, `JS_SetMemoryLimit`, `JS_SetMaxStackSize`, fuel por interrupt quanta ~10000 bytecodes, neutraliza `Math.random`/`Date.now`, instala `call_tool`), `eval_source` (GLOBAL+STRICT, resultado via `JSON.stringify`, erro via `String(err.stack\|\|err)`), `call_tool` (charset+limites em C, req JSON, `RangeError` em códigos negativos), `classify_exception`, `result/error_ptr+len`, `tool_count`, `fuel_used`, `alloc`, `reset_heap`, `shutdown`. Só usa APIs confirmadas por grep no `quickjs.h` do tarball pinado. |
| `sentra_code_mode/guest/ABI.md` | ABI v1 exata: 1 import host (`env.sentra_host_call(req,req_len,res,res_cap)->res_len|-1..-4`), 14 exports (memory, configure, eval_source, classify_exception, result/error ptr+len, tool_count, fuel_used, alloc, reset_heap, shutdown), códigos eval `0/1/-10..-15/-20`, req `{"v":1,"tool","args"}`, superfície JS (`call_tool`→string, sem módulos/async/IO), mapa ResourceLimits→guest. |
| `sentra_code_mode/guest/build.sh` | Build real (NÃO executado aqui — sem toolchain WASM): tarball pinado por SHA+tamanho, wasi-sdk clang wasm32-wasi, alloc wrapped, link `--no-entry` com exports explícitos, check pós-link falha se qualquer import ≠ `env.sentra_host_call`, gera `dist/` (wasm + `sbom.cdx.json` CycloneDX 1.5 + `provenance.json` com `validated: false`). |
| `sentra_code_mode/guest/PROVENANCE.md` | Pins verificados 2026-10-11: upstream quickjs-2026-06-04 (`https://bellard.org/quickjs/quickjs-2026-06-04.tar.xz`, sha256 `b376e839…2fa70ad2a`, 621500 bytes, MIT, 67 entradas) + hashes dos 3 arquivos guest; o que Vitra deve embarcar; o que NÃO é alegado (sem binário, sem execução). |
| `sentra_code_mode/quickjs_runtime.py` | Reescrito para ABI v1: pin SHA a cada run, 1 import host, rejeita qualquer outro import (WASI falha), `configure()` com limites, `eval_source`, códigos mapeados (`-10/-11/-12`→Budget, `-13`→Permission, `-14/-15`→Budget), resultado re-checado, `tool_count` vs bridge cross-check, host func valida envelope e chama `bridge.call_sync` (OperationRequest/grant/fencing central por tool), wall via epoch deadline (quando o binding oferece) + watchdog com poison de store, cancel via epoch bump. Versão-tolerante: mismatch de API → `CodeModeUnavailable` explícito. |
| `sentra_code_mode/artifact_config.py` | (inalterado) loader env + `describe_configuration()` + `build_admission()`. |

Assinatura registrada para Codex/Vitra: `CODE_MODE_SIGNATURE` (+`a08_statement`)
em `schema.py`; `MCPB_LIFECYCLE_SIGNATURE` em `mcpb_lifecycle.py`; drop-ins em
`composition.py`. Distribuição deve incluir o guest executável real
(`dist/sentra_quickjs_guest.wasm` + SBOM + provenance) — sem isso, e sem a
fiação central, a frente segue NÃO-integral (seção 4).

## 8. Helpers de composição central — quickjs-wasm aprovado + tool map fenced + Machine (11/10/2026)

Fiação root confirmada por leitura (sem executar nada): `center_skill_library`
com `versions/latest/review/upgrade/rollback` sob scope WorkItem+agente;
`center_plugin_bundles` com `bundle_list` + `supervision.status` e ação
`supervision_sweep` (callback host aprovado na rota bearer; tickets não
removem contêiner); `center_chat` com `conversation_consent_summary`.
Nenhum arquivo root editado.

| Helper (domínio Pacto) | Assinatura / efeito |
|---|---|
| `composition.approve_artifact(*, wasm_path, sbom_path, wasm_sha256, sbom_sha256)` | Pins aprovados pelo host (rota owner, nunca chat/modelo) → `QuickJSArtifact`; bytes verificados na admission/readiness/cada run, nunca neste construtor. |
| `composition.build_fenced_tool_map(tool_handlers)` | Mapa nome→callable host-selected (máx 32, charset `[A-Za-z0-9_.-]{1,64}`); vazio = `call_tool` negado; cada inner call vira seu PRÓPRIO OperationRequest no gate central; cria zero grants. |
| `composition.compose_quickjs_dispatcher(control, *, artifact=None, limits=None)` | `CodeModeDispatcher(engine='quickjs-wasm')` com artefato aprovado ou pins env (indisponível explícito se desconfigurado). Sem parâmetro de engine por construção — nenhuma fachada deny-only/subset contada como A08 aqui. |
| `composition.declare_code_machine(owner, tool_names)` | `Machine(code-mode-<hash>, kind=code-mode)` com capabilities `code:configure/restore/inventory/discovery` + `code-tool:<nome>`; mesma autoridade central, zero grants. Para Nexo/root. |
| `composition.machine_adapter(control, *, owner, run_id, tool_names)` | `(machine, CentralInteropAdapter)` na mesma autoridade. Mapeamento: configure→`propose` (+admission do artefato); restore→`cancel` + replay idempotente de `execute` (recibos armazenados, nunca re-executa o guest às cegas); inventory→`dispatcher.inventory` (só leitura); discovery→`dispatcher.discovery` (só leitura, sem dados de owner). |
| `dispatcher.inventory(owner, *, limit=50)` | Propostas + engine + estado + último execution + `a08_satisfied`; digests, nunca source bytes; sem grants. |
| `dispatcher.discovery()` | `CODE_MODE_SIGNATURE` + engine + `artifact_configured` + admission viva; sem dados de owner; sem grants. |
| `mcpb_supervision.sweep` | Agora tolera callback host 0-arg (closure da rota bearer) além de `(owner, workspace)`; não-callable ou retorno ≠ `True` continua negando — fail-closed preservado. |

Divergências root (dono Codex, 1 linha cada — Pacto não toca):
- `center_skill_library` chama `library.rollback_activation(owner,root,**p)` sem
  `approved=True` → nega fail-closed até o root passar `approved=True`
  (standing da rota owner autenticada, mesmo padrão de
  `control.mcp_http_register(..., approved=True)`).
- `dispatch_skill_library_extra` em `composition.py` já passa `approved=True`
  quando o root adotar o drop-in.

Pendências honestas restantes: ship do artefato/build (binário `.wasm` +
SBOM + provenance via `guest/build.sh` — distribuição nativa final, Vitra);
`wasmtime` não instalado; QA/build geral NÃO executados; preview (dialogs)
NÃO tocado nesta rodada. Sem `ask` de volta ao root — relatório por arquivo.

## 5. Plano de validação futura (NÃO executado nesta fase)

- Interpretador: aritmética/controle/funções/recursão, fuel esgotado, teto de memória, wall-time, cancel no meio de loop, `max_tool_calls`/`max_arg_bytes`/`max_result_bytes`, fonte fora do subset, replay idempotente de `execute`, `cancel` antes/durante execução.
- Fencing: tool allowlisted com grant concedido/negado/revogado entre decision e effect; handler host-only (JS não injeta handler); ChatTrust/block e consentimentos nunca criam grant.
- QuickJS: `readiness()` sem/com artefato (SHA errado, symlink, SBOM não-CycloneDX, import WASI rejeitado), indisponível sem `wasmtime`, cancel via interrupt.
- Skills/MCPB: `review` sem divulgação, `rollback` aprovado/não-aprovado e com revisão revogada, `collision_check` com provider disabled, `restart_ticket` sem worker vivo/FAILED, `uninstall` sem aprovação, concorrência (duplo `upgrade_activation`, sweep vs `reconcile_stopped_owned`).
- Fidelidade UI: dialogs com/sem campos novos (`review`/`rollback`/`code_mode`); nenhuma validação visual executada.
