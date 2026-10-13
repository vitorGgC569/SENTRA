# Vitra — desktop e distribuição (implementação integral, sem validação)

Data: 2026-10-11. Papel: Setup/Doctor/reparo, staged update/migração/rollback,
Windows/Electron/CLI, instalação/distribuição e proveniência.
VIDE `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md` (ordem: implementação
integral primeiro, validação somente no final liberada pelo Codex) e
`docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md` (contrato do shell).

Nenhum teste, build, lint, benchmark ou QA foi executado nesta fase.
Nenhum commit/push/reset/stash. Nenhum arquivo de outro dono foi alterado.
Comunicação com o principal exclusivamente via `maestri ask Codex`.

## Requisitos do domínio (estudos lidos)

- Nota `todos-os-projetos-ja-estao-clo` (465 linhas): Home/Dots/Spaces/conversas
  como experiência principal; Canvas existente como visualização interna; Dot
  Coordenador cria equipes/subagentes pela conversa; chat/Canvas/CLI/Desktop
  consultam os mesmos agentes e o mesmo estado autoritativo; migração
  recuperável de projetos anteriores.
- `SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md` (34 frentes +
  adendo A01–A21): Setup/diagnóstico/reparo por etapa (P1), updater encenado
  aplicado ao encerrar o app sem bloquear startup (A19), diagnóstico
  anonimizado antes de compartilhar (A15), first-use ConnectorProof/
  BrowserProof/PluginRefresh, staged update coordenado.
- `SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md`,
  `SENTRA_DESKTOP_AUTONOMIA_REDE_2026-10-09.md`,
  `SENTRA_WINDOWS_RELEASE_QA_2026-10-09.md`: Setup/MSI contemporâneos,
  clean install, rollback/migrations com crash e ownership, Authenticode,
  proveniência de payload (fingerprint cobre .py/.jsx/.tsx/.patch/docs
  completos), atalhos, Web Models e Electron como displays.
- `SENTRA_TERMINAIS_OPENCODE_2026-10-11.md`: escopo exclusivo Vitra e a regra
  de coordenar a rota `/api/shell/bridge` com o Codex antes de editar seu
  handler (composição é do principal — NÃO editada aqui).

## Arquivos alterados (somente domínio Vitra)

Novos (criação permitida no próprio domínio):

- `sentra_remote/shell_migration.py` — linkage idempotente workspace Canvas →
  Space: `normalize_project_id` (alias legado `ws` → `project_id` canônico),
  `canonical_response`, `plan_space_links` (IDs preservados, sem cópia/rename,
  `already_linked` repetível), `prepare_space_migration` /
  `commit_space_migration` (journal `shell-migration.json`, binding de
  instalação/estado, fase STAGED→COMMITTED, callback central `apply_link`),
  `migration_status` (projeção read-only). Falha explícita sem store opcional.
- `sentra_remote/coordinated_upgrade.py` — upgrade coordenado
  app+extensão+Web Models+schema MCP: `plan_coordinated_upgrade` (a partir do
  release manifest verificado), `stage_coordinated_upgrade`,
  `coordinated_status`. Política: aplicar ao sair do app, nunca interromper
  ConPTY vivo, em falha permanecer na versão funcional com rollback.
- `sentra_cli/shell_bridge.py` — cliente CLI da rota única
  `POST /api/shell/bridge`: allowlist de ações leituras/mutações/documentos,
  `request_key` UUID/dedupe, `project_id` (+`space_id`/`conversation_id`),
  rejeição de `owner/principal/grant/permission/path` no payload, bearer local,
  falha fechada sem broker, envelope de erro sanitizado.
- `scripts/commander/shell_release_probe.py` — sonda read-only de
  empacotamento shell (desktop+shell bundles, contrato bridge, manifest).
- `.github/workflows/shell-packaging.yml` — workflow novo e mínimo (somente
  sonda read-only); `ci.yml`/`release-commander.yml` NÃO alterados.
- `tests/unit/test_vitra_shell_integral_future.py` — testes exclusivos PARA
  EXECUÇÃO FUTURA (migração idempotente, Doctor/diagnóstico redigido,
  allowlist CLI, upgrade coordenado, onboarding shell). Criados, NÃO executados.

Edições aditivas (compatibilidade preservada, sem mudar comportamento existente):

- `sentra_remote/install_doctor.py` — `SHELL_COMPONENTS` +
  `inspect_shell_surface()` (shell_ready/shell_pending, nunca dano);
  `shareable_doctor` ganha chave aditiva `shell_surface: unchecked`.
  `REQUIRED`/`inspect_installation`/`request_owner_repair` inalterados.
- `sentra_remote/diagnostics.py` — `shareable_report` projeta `shell.status` +
  `missing_count` e `installation.doctor_phase` allowlisted; sem identificadores.
- `sentra_remote/onboarding.py` — nova `build_shell_onboarding()` pura
  (SHELL_READY/SHELL_MIGRATE/SHELL_PENDING, sem afirmar instalação em conta);
  `build_onboarding_snapshot` inalterado.
- `sentra_remote/setup_assistant.py` — novos `shell_migration_status()` e
  `prepare_shell_migration()` delegando a `shell_migration`; `detect_capabilities`
  inalterado.
- `sentra_cli/repl.py` — ajuda + `/shell|/space|/dot|/conversation|/coordinate`
  via `ShellBridge`; comandos anteriores inalterados.
- `sentra_canvas/electron_host.py` — `electron_status` ganha chaves aditivas
  `shell_home`/`bridge`; novo `describe_shell_surface()`; ticket/launch inalterados.
- `sentra_canvas/native_app.py` — novo `resolve_surface()` (shell-home.html >
  desktop.html > native.html) e `surface` opcional em `launch_native`;
  chamada existente `launch_native(server, serve=False)` continua válida.
- `sentra_canvas/__main__.py` — novo `--surface shell-home|desktop|native`
  (default shell-home com fallback); rota `/api/shell/bridge` NÃO tocada
  (composição do Codex).
- `sentra_electron/policy.cjs` — `safeOrigin`/`envelope` aceitam
  shell-home/native mantendo default desktop (teste existente preservado).
- `sentra_electron/main.cjs` — superfície do ticket com fallback desktop;
  bloqueio de navegação/popups/permissões inalterado.
- `scripts/commander/build_canvas.py` — nova `validate_shell_bundle()`
  opcional (shell_pending quando ausente); `validate_desktop_bundle` inalterado.
- `scripts/commander/release_assets.py` — manifest ganha `shell_surface`
  (bridge_contract, canvas_role internal, fallback) + `mcp_schema_version`.
- `scripts/commander/release_doctor.py` — verificação aditiva do contrato shell
  quando `shell_surface` presente; resultado ganha `shell_contract`.

## Contrato de integração (para Codex/Nexo/Prisma/Tessela)

- Rota única `POST /api/shell/bridge` (Codex compõe no handler HTTP com bearer
  existente; Vitra NÃO editou `service.py`/`graph.py`/`server.py`): envelope
  `{action, request_key, project_id[, space_id, conversation_id]}`; `ws` alias
  legado de entrada normalizado a `project_id`; resposta canônica
  `{ok, value{project_id...}, request_key}`; erros `{error}` sanitizados.
- Nexo: persistir `space.project_id` explícito e conferir por chamada; expor
  `apply_link(workspace_id, space_id)` autoritativo para
  `commit_space_migration`; enviar assinatura/esquema final ao Codex.
- Prisma: único cliente UI `shellBridge`; shell-first Home/Dots/Spaces, Canvas
  interno; ao shippar `shell-home.html`+`shell-assets/manifest.json`, o launcher
  Vitra (`resolve_surface`, Electron ticket `surface`) prefere o shell
  automaticamente sem mudar backend.
- Tessela: encaixar `document_*` no mesmo dispatch com ACL/WorkItem/Grant, CAS
  `expected_revision`, `mutation_id`, receipts; sem endpoint paralelo nem `owner`
  ao renderer (CLI já rejeita esses campos).
- Migração: `plan_space_links` preserva IDs, repetível/idempotente; Doctor
  reporta `shell_pending` até o bundle existir; `coordinated_upgrade` aplica o
  pacote verificado pelo `updater` ao sair do app sem matar ConPTY.
- Falha explícita quando serviço opcional não configurado (bridge indisponível,
  bundle ausente, store ausente): mensagens sanitizadas, sem simulação.

## Pendências reais (não homologado)

- Aguardar Nexo/Codex: store autoritativo Spaces/Dots/conversas + rota bridge
  composta; então ligar `apply_link` real e `SENTRA_CANVAS_PORT/BEARER` no CLI.
- Aguardar Prisma/Tessela: bundle shell (`shell-home.html`, `shell.js`,
  `shell-assets/manifest.json`) e `document_*` no dispatch; launcher já preparado.
- Rebuild integral de payload/Setup/MSI/SBOM com novo fingerprint + manifest
  shell, assinatura Authenticode com publisher legítimo, clean-install em VM
  descartável, desinstalação limpa — tudo na etapa final liberada pelo Codex.

## Plano de validação futura (NÃO executado)

Após TODAS as frentes implementadas e integradas, e somente com liberação do
Codex: `test_vitra_shell_integral_future.py` + suítes existentes
(`test_sentra_cos_install_doctor_round4`, `test_build_payload_provenance`,
`test_build_canvas`, `test_sentra_electron_surface`, `test_onboarding`,
`test_setup_assistant`, `test_native_app`), `shell_release_probe --static/--release`,
`release_doctor --release/--dist`, payload 13/13 + Setup + MSI/ZIP/SBOM,
instalação isolada `--no-system-registration --no-launch --stop-after-doctor`
com janela WebView2/Electron shell-first, CLI `/shell|/space|/dot|/conversation`
contra broker real, migração repetida idempotente, kill/crash entre renames com
`recover_interrupted_migration`, `git diff --check`, CI required verde e
assinatura. Nenhum sucesso declarado por leitura de arquivos.

---

# Expansão integral — 11/10/2026 (ordem Meridiano; sem validação executada)

Ordem: backup coordenado SQLite/Postgres/config/artefatos/keys +
restore/migrations/rollback; staged update app/extension/MCP schema/gateway/
sidecars preservando ConPTY; providers opcionais install/health/repair/
recovery/remove + transitivos pins/SBOM/NOTICE por arquivo; Setup distingue
local-ready/tunnel-online/account-app-observed/tools-authorized/
version-current e extension installed/paired/login/revoked; diagnóstico export
preview redigido (IP/URL/path/email/título/projeto); preparar clean install /
assinatura real / distribuição entre amigos + QA final SEM executar; receber
manifests Lume/Pulso/Selo; assinatura/signing nunca simulados.

Nenhum teste, build, lint, benchmark, QA ou homologação foi executado.
`sentra_canvas/__main__.py` e `service.py` (Codex) NÃO foram editados.
Nenhum commit/push/reset/stash; nenhuma alteração alheia removida.

## Arquivos novos (domínio Vitra)

- `sentra_remote/coordinated_backup.py` — backup coordenado + restore CAS:
  `plan_coordinated_backup` (escopo sqlite/postgres/config/artifacts/keys),
  `prepare_coordinated_backup` (owner-auth + offline; SQLite via backup API
  read-only; Postgres SOMENTE via runner injetado, indisponível explícito sem
  ele; config recusa segredo desprotegido; keys SOMENTE blobs OS-protegidos,
  nunca plaintext; journal `coordinated-backup.json` BACKED_UP),
  `restore_coordinated_backup` (CAS `expected_current`, sidecars SQLite
  bloqueiam, re-grava journal RESTORED), `backup_status` (read-only).
- `sentra_remote/optional_providers.py` — providers opcionais
  (git/docker/ollama/tunnel-client/pdfium/web-models/electron):
  `describe_provider` (ready/degraded/installable/unavailable),
  `provider_install/health/repair/recovery/remove/revoke` (aprovação explícita
  + runner do host; sem runner = indisponível explícito; cancel = não aprovar),
  `transitive_inventory` (pins/SBOM purl/NOTICE/licença por arquivo).
- `sentra_remote/setup_states.py` — `describe_setup_states` puro:
  local-ready / tunnel-online (+reauth/credential-storage) /
  account-app-observed (só com prova de tool autenticada, nunca por tunnel
  vivo) / tools-authorized / version-current|stale|unknown /
  extension absent|installed|paired|login|revoked.
- `sentra_remote/sidecar_manifests.py` — recebe manifests Lume(interop) /
  Pulso(workflows) / Selo(quality): `validate_sidecar_manifest` (nome, versão,
  schema, sha256, files[], license, signer OBRIGATÓRIO),
  `verify_sidecar_signature` (verificador do host; sem ele recusa simular),
  `collect_sidecar_manifests` (+combined_sha256), `compose_release_sidecars`.
- `sentra_cli/maintenance.py` — projeções fail-closed p/ CLI:
  `backup_status`/`update_status`/`provider_inventory`/`provider_states`/
  `doctor_preview`/`setup_states`.
- `sentra_electron/staged_update.cjs` — política display-only apply-on-exit +
  `shouldDeferUpdate` (nunca matar ConPTY).
- `scripts/commander/clean_install_plan.py` — plano clean-install em VM
  descartável + distribuição (só emite JSON, nunca executa).
- `scripts/commander/release_signing.py` — contrato de assinatura REAL:
  `require_real_thumbprint` recusa vazio/placeholder; `verify_signed_release`
  (Authenticode Setup+MSI vs publisher confiável + manifest); `seal_after_signing`
  (selo de proveniência pós-assinatura). Nada é simulado.
- `scripts/commander/provider_pins.py` — inventário read-only pins/SBOM/NOTICE.
- `.github/workflows/vitra-release-prep.yml` — workflow novo read-only
  (inventory + clean-install plan + shell probe). `ci.yml` /
  `release-commander.yml` NÃO alterados.
- `tests/unit/test_vitra_expansion_future.py` — testes exclusivos PARA
  EXECUÇÃO FUTURA (10 casos). Criados, NÃO executados.

## Edições aditivas (compat preservada)

- `sentra_remote/coordinated_upgrade.py` — `coordinated_status` ganha
  `extension_version`/`gateway_version`/`conpty_policy`; novos
  `verify_mcp_schema_compatibility` (monotônico, sem downgrade encenado),
  `check_conpty_guard` (defer com ConPTY vivo), `plan_staged_product_update`
  (app+extensão+gateway+sidecars sobre o planner existente).
- `sentra_remote/diagnostics.py` — `shareable_report` inalterado; novos
  `redact_text_preview` (IP/URL/path/email + titles/projects literais, counts,
  limite 64 KiB) e `preview_export` (shareable + previews redigidos, nada transmite).
- `sentra_remote/onboarding.py` — novo `describe_setup_axes` delegando a
  `setup_states`; `build_onboarding_snapshot`/`build_shell_onboarding` inalterados.
- `sentra_remote/setup_assistant.py` — novos `setup_states()`,
  `backup_status()`, `staged_update_status()`; `detect_capabilities` e demais
  métodos inalterados.
- `sentra_remote/install_doctor.py` — novo `inspect_provider_surface`;
  `REQUIRED`/`inspect_installation`/`request_owner_repair` inalterados.
- `sentra_cli/repl.py` — ajuda + `/backup|/restore|/update|/provider|/doctor-export`
  via `maintenance`; comandos `/shell|/space|/dot|...` inalterados.
- `sentra_canvas/electron_host.py` — novo `describe_staged_update_surface()`;
  ticket/launch inalterados.
- `sentra_canvas/native_app.py` — novo `staged_update_note()`; launch inalterado.
- `scripts/commander/release_assets.py` — `finalize_assets` aceita `sidecars` +
  `provider_pins` opcionais no manifest; build existente inalterado.
- `scripts/commander/release_doctor.py` — verificação estrutural aditiva de
  `sidecars` (nome/versão/sha256/signer por kind) + `provider_pins`
  (files[] completos); resultado ganha `sidecars`/`provider_pins`.
- `scripts/commander/shell_release_probe.py` — projeta `release_sidecars` /
  `release_provider_pins` quando presentes.

## Contrato de integração (para Codex compor; assinatura cedo)

```python
# Backup coordenado (host fornece authorize/offline; Postgres via runners)
from sentra_remote.coordinated_backup import (
    plan_coordinated_backup, prepare_coordinated_backup,
    restore_coordinated_backup, backup_status)
# Staged update ConPTY-safe (Pulso detém handles; Vitra só adia/aplica na saída)
from sentra_remote.coordinated_upgrade import (
    plan_staged_product_update, check_conpty_guard,
    verify_mcp_schema_compatibility, coordinated_status)
# Providers opcionais (runner do host; sem runner = indisponível explícito)
from sentra_remote.optional_providers import (
    describe_provider, provider_install, provider_health,
    provider_repair, provider_recovery, provider_remove, transitive_inventory)
# Setup axes (projeção pura p/ Doctor/Setup/Desktop/CLI)
from sentra_remote.setup_states import describe_setup_states
# Sidecars Lume/Pulso/Selo (assinatura real; sem verifier não simular)
from sentra_remote.sidecar_manifests import (
    collect_sidecar_manifests, compose_release_sidecars)
# Diagnóstico (preview redigido p/ revisão local; nada transmite)
from sentra_remote.diagnostics import redact_text_preview, preview_export
```

- Codex (`service.py`/`server.py`/config raiz, NÃO tocados aqui): compor
  endpoints/bridge p/ backup-status, staged-update-status, provider-states,
  setup-states e doctor-preview usando os serviços acima; fundir `sidecars` +
  `provider_pins` no `release-manifest.json` via `compose_release_sidecars`;
  selar proveniência pós-assinatura real via `release_signing`.
- Lume/Pulso/Selo: publicar manifests `{name, version, schema_version,
  sha256, files[{path, sha256}], license|notice, signer|producer_signature}`.
  Vitra valida estrutura+digest e só marca `verified` com verificador do host.
- Pulso: `check_conpty_guard(handles)` consome handles do registry de
  terminais; update físico espera `apply` (sem ConPTY vivo) na saída do app.
- Selo: Grype/pins cruzam `transitive_inventory()` + SBOM do release.
- Brisa/Rastro: `account_app.state` usa prova de tool autenticada observada;
  extension `login` exige observação de login, não só relay ok.
- CLI/Desktop: `/backup|/update|/provider|/doctor-export` e Setup exibem as
  projeções; efeitos (restore/apply/install) exigem o fluxo owner-auth offline
  do host. Rota `/api/shell/bridge` NÃO tocada (composição do Codex).

## Dependências / pendências reais (não homologado)

- Aguardar Lume/Pulso/Selo publicarem os manifests reais p/ compor
  `sidecars_combined_sha256` no release; assinatura pendente de publisher
  Authenticode legítimo (thumbprint real via HSM/CI secreto).
- Aguardar Codex/Nexo comporem endpoints + bridge; ligar runners reais
  (Postgres pg_dump/restore, provider install/health, verifier de sidecars).
- Rebuild integral payload/Setup/MSI/SBOM/NOTICE por arquivo com novo
  fingerprint, clean-install em VM descartável + desinstalação limpa,
  distribuição só do Setup assinado — tudo na etapa final liberada pelo Codex.

## Plano de validação futura (NÃO executado)

Com liberação do Codex, após todas as frentes: `test_vitra_expansion_future.py`
+ suítes existentes, `provider_pins.py`, `clean_install_plan.py`,
`shell_release_probe --static/--release`, `release_doctor --release/--dist`
(+`--trusted-signer` real), `release_signing --trusted-signer ... [--seal]`,
backup/restore CAS em staging descartável, staged update com ConPTY vivo →
defer, migração Postgres via runner real, QA visual/fidelidade, `git diff
--check`, CI verde e assinatura. Nada declarado homologado por leitura.

---

# Rodada 2 — conclusão das pendências concretas (11/10/2026, sem validação)

Reportado por arquivo (sem `ask Codex` para não bloquear o principal).
Nenhum teste/build/lint/benchmark/QA executado. Nenhum commit/push/reset/stash.
`sentra_canvas/__main__.py`, `service.py`, `graph.py`, `server.py`, config raiz
e `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md` NÃO tocados. Nenhum arquivo
de outro dono alterado (Lume/Pulso/Selo/Forja/Nexo/Prisma/Tessela/Brisa/Rastro/
Pacto/Meridiano intactos). Implementação integral NÃO declarada: runners
externos (winget/pg_dump/firmas PKI) e manifests assinados dos donos seguem
pendentes do ambiente/composição — registrado abaixo como falta, não como pronto.

## Pendência 1 — guest runners concretos (era: só callables injetados)

- `sentra_remote/guest_runners.py` (NOVO): `winget_runner` real
  (`winget install/uninstall --exact`, sem shell); `probe_git`/`probe_docker`/
  `probe_ollama` (binários reais + loopback Ollama, nunca inferem daemon por
  binário); `provider_runner` (dispatch host-bindable, inclui `renew`);
  `postgres_dump_runner`/`postgres_restore_runner` (`pg_dump --format=custom` /
  `pg_restore --clean --if-exists`, DSN só via chamada do host, nunca logado,
  falha explícita sem binários); `verify_sidecar_files` (re-hash real;
  identidade do publisher verificada só no selo do release, nunca simulada).

## Pendência 2 — migrations Postgres (era: só dump no backup)

- `sentra_remote/postgres_migration.py` (NOVO): `plan_postgres_migration`
  (monotônico + digest do SQL revisado), `prepare_postgres_migration`
  (snapshot pg_dump offline, live nunca migrado aqui),
  `commit_postgres_migration` (CAS da versão viva, digest do SQL conferido,
  fase SWITCHING→COMMITTED, sem repetição silenciosa),
  `rollback_postgres_migration` (snapshot conferido por hash),
  `postgres_migration_status`. Respeita C10: nunca importa módulo Nexo nem
  alega backend existente; sem DSN/runners = indisponível explícito.

## Pendência 3 — NOTICE por arquivo (era: caminhos inexistentes)

- `sentra_remote/provider_notices/` (7 NOVOS .txt reais: git/docker/ollama/
  tunnel-client/pdfium/web-models/electron, com pin/fonte/licença/notas de
  distribuição).
- `sentra_remote/optional_providers.py` (edição no próprio arquivo): `notice`
  aponta para os arquivos reais; novo `provider_renew` (+`renew` no `_admit`,
  cobre o `renew` exigido em contracts L164). `transitive_inventory` passa a
  emitir inventário com NOTICE existente por arquivo.

## Pendência 4 — staged update sem stage/commit do plano estendido (C194)

- `sentra_remote/coordinated_upgrade.py` (aditivo): `plan_extension_update`
  (instalada 1.7.0 vs bloco do release; flag stale sem tocar arquivos),
  `stage_product_update` (journal STAGED do plano app+extensão+gateway+sidecars),
  `commit_product_update` (defer com ConPTY vivo; sela APPLY_ON_EXIT; bytes
  aplicados só pelo helper do host após a saída; falha = permanece STAGED p/
  rollback explícito).

## Pendência 5 — Doctor/diagnóstico sem eixos novos

- `sentra_remote/diagnostics.py` (aditivo, default inalterado):
  `shareable_report` projeta `setup` (6 eixos em vocabulário fechado) e
  `providers` (contagem por estado) quando o chamador fornece; `main` ganha
  `--preview-note/--preview-title/--preview-project` (preview redigido ≤8 KiB,
  recusa combinar com `--internal`). `diagnostics_entry.py` herda sem edição.
- `sentra_remote/install_doctor.py` (aditivo, default inalterado):
  `shareable_doctor(plan, *, shell, providers)` projeta superfície real quando
  fornecida; sem args, saída idêntica à anterior (`shell_surface: unchecked`).

## Pendência 6 — manifests Lume/Pulso/Selo (era: nenhum recebido)

- `sentra_remote/sidecar_registry.json` (NOVO, dado de ingestão): digests SHA-256
  reais lidos da árvore (workflows Pulso 6 arquivos; quality Selo 6 arquivos +
  memory 2 arquivos); `interop` registrado `absent-awaiting-owner` (sem
  `docs/integral/Lume.md`; nada fabricado); assinatura
  `unverified-pending-host` em todos — `collect_sidecar_manifests()` continua
  recusando compor sem manifest assinado do dono. Registro ≠ manifest do dono.

## Pendência 7 — distribuição entre amigos + QA final (prep, sem executar)

- `scripts/commander/qa_checklist.py` (NOVO): emite checklist JSON
  (distribuição só assinada + 9 gates); nada executa; unsigned = NOT FOR
  DISTRIBUTION explícito. Complementa `clean_install_plan.py`.

## Testes futuros (criados, NÃO executados)

- `tests/unit/test_vitra_expansion_future.py` (+7 casos: renew exige aprovação,
  NOTICEs existem por arquivo, PG monotônico/runners, extension stale 1.6.52→
  1.7.0, registry marca unsigned, shareable_doctor default inalterado).

## Contrato atualizado p/ Codex (composição, sem tocar centrais)

```python
from sentra_remote.guest_runners import (provider_runner, postgres_dump_runner,
    postgres_restore_runner, verify_sidecar_files)
from sentra_remote.postgres_migration import (prepare_postgres_migration,
    commit_postgres_migration, rollback_postgres_migration)
from sentra_remote.coordinated_upgrade import (stage_product_update,
    commit_product_update, plan_extension_update)
```

- Ligar `provider_runner` (winget+probes reais), dump/restore PG com DSN do
  host, `verify_sidecar_files(root=...)` + selo PKI via `release_signing`.
- Fundir `sidecar_registry.json` (ingestão) somente após manifests assinados
  reais via `collect_sidecar_manifests(..., verify=...)`.
- Fiação de `--preview-note`, eixos `setup`/`providers` e `shareable_doctor`
  com shell/providers reais permanece com o Codex (endpoints/bridge).

## Faltas honestas restantes (não fecham requisito)

1. Manifests assinados Lume/Pulso/Selo + verificador PKI do host.
2. Thumbprint Authenticode real (HSM/CI) p/ `release_signing --seal`.
3. Runners no ambiente final (winget/pg_dump no PATH da VM de QA).
4. Composição Codex/Nexo (endpoints/bridge/store) e bundle shell Prisma/Tessela.
5. Etapa final liberada pelo Codex: validação requisito-por-requisito.

---

# Rodada 3 — artwork OpenDots no release (11/10/2026, sem validação)

Aviso recebido da Prisma: mascotes originais CopilotKit/OpenDots pin
`625452e`, `src/assets/opendots/{blue,mint,orange,purple}.png` + LICENSE MIT
Copyright Atai Barkai + PROVENANCE.json; bytes obtidos da URL oficial do pin e
iguais aos blob IDs; JSX adaptado (hash31); `materialize.mjs` só cobre
node_modules (fora do meu ownership — NÃO alterado); pins+overrides
bubble/floating-menu 3.31.3 (package UI da Prisma — NÃO alterado, sem
install/lock/build).

## O que a Vitra fez (só domínio próprio)

- `scripts/commander/release_assets.py` (aditivo): novo
  `_stage_opendots_artwork()` — transporta LICENSE + PROVENANCE.json (+ NOTICE
  Vitra, se existir) para `docs/opendots/` no staging; re-verifica os 4 SHA-256
  dos PNGs contra PROVENANCE.json (divergência recusa o staging); dir ausente
  mantém árvores antigas (None), dir incompleto falha fechado; grava
  `staging/artwork-provenance.json`. `create_assets` repassa a
  `finalize_assets(..., artwork=...)`; `--finalize-only` preserva
  `artwork_provenance` prévia. Instalação herda automaticamente (installer copia
  a árvore `docs/`).
- `scripts/commander/release_doctor.py` (aditivo): verifica estrutura de
  `artwork_provenance` (MIT/Atai Barkai/commit/files); resultado ganha
  `artwork_provenance`.
- `scripts/commander/shell_release_probe.py` (aditivo): projeta
  `release_artwork_provenance` quando presente.
- `sentra_remote/provider_notices/opendots-mascots-NOTICE.txt` (NOVO): NOTICE
  por arquivo/modificação (bytes UNMODIFIED + adaptação JSX documentada +
  transporte docs/opendots/ + pins bubble/floating-menu observados).
- `scripts/commander/qa_checklist.py` (aditivo): gate
  `artwork_license_provenance`.
- `tests/unit/test_vitra_expansion_future.py` (+1 caso futuro, NÃO executado).

## Limites honestos

- Bytes PNG viajam no bundle desktop (domínio Prisma/materialize); Vitra
  transporta licença+proveniência no payload e registra no manifest — sem
  segunda cópia de autoridade sobre os assets.
- Nenhum install/lock/build/geração de assets executado; nenhuma validação.

---

# Rodada 4 — guacamole-common-js no release (11/10/2026, sem validação)

Adendo Prisma: `package.json` com pin exato guacamole-common-js 1.5.0 (repack
padarom, NÃO clone ASF atual); SRI/provenance e LICENSE extraídos do tarball
pinado em `src/assets/guacamole` (LICENSE + NOTICE ASF + PROVENANCE.json);
OpenDots segue com 4 PNGs + MIT + PROVENANCE em `src/assets/opendots`.
Release deve incluir ambos os conjuntos; `materialize.mjs` (só node_modules,
fora do ownership — NÃO alterado) precisa de composição minha/Codex.
Nenhuma instalação/build; package-lock e preview intocados.

## O que a Vitra fez (só domínio próprio)

- `scripts/commander/release_assets.py` (aditivo): novo
  `_stage_guacamole_legal()` — transporta LICENSE + NOTICE + PROVENANCE.json
  para `docs/guacamole/`; confere identidade (package/1.5.0/Apache-2.0/
  is_apache_clone false), SRI `sha512-` e URL HTTPS do tarball; dir ausente =
  None (compat), incompleto = falha fechada. Novo `_write_staged_artwork_record`
  combina `opendots-record.json` + `guacamole-record.json` em
  `artwork-provenance.json` (chaveado por conjunto). `finalize_assets` normaliza
  registro flat legado → `{"opendots": ...}`.
- `scripts/commander/release_doctor.py` (aditivo): `artwork_provenance` aceita
  forma chaveada (`opendots` + `guacamole`) ou flat legado; valida cada conjunto
  (guacamole: 1.5.0/Apache-2.0/non-clone/SRI); estado
  `verified-structure:guacamole+opendots`.
- `sentra_remote/provider_notices/guacamole-common-js-NOTICE.txt` (NOVO):
  NOTICE por arquivo/modificação (repack≠clone ASF, propósito viewer, transporte
  docs/guacamole/, sem install/build).
- `scripts/commander/qa_checklist.py` (aditivo): gate cobre ambos os conjuntos.
- `tests/unit/test_vitra_expansion_future.py` (+1 caso futuro, NÃO executado).

## Limites honestos

- JS bytes via tarball npm pinado no build da UI (Prisma/materialize); Vitra
  transporta licença+NOTICE+proveniência no payload. Composição do materialize
  além de node_modules com Codex/Prisma. Nenhuma validação executada.
# Fechamento atual herdado por Tessela

`REDISTRIBUICAO_CODEX.md` e `Tessela-fechamento.md` prevalecem para contratos
atuais. Reserva central BEFORE efeito, paths/config host-only, C09 store
backup/restore Nexo, migrations nativas injetadas, helper real com mesmo
receipt/Grant/fence, CLI scope shell/coordinator e transportes de release
foram implementados em fonte por Tessela. Pendências de composição, SDKs,
artefatos/PKI/ambiente e validação final estão explicitamente separadas.
O histórico abaixo permanece como autoria e contexto, sem homologação nova.

