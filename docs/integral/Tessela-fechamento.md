# Tessela — entrega de fontes Vitra e CLI shell

Ownership herdado por `REDISTRIBUICAO_CODEX.md`: Vitra além de documentos/Yjs.
Sem testes/build/install/lint/benchmark/QA/re-stamp, sem alteração da preview
PID47408, sem recrutamento nem operações Git destrutivas.

## Contratos compartilhados antes das edições

- `VitraFacadeConfig` receberá owner/installation_id/tenant derivado da autoridade;
  `VitraHostFacade(..., control, authorize, offline, quiesced,
  resolve_parameters, checkpoint, ...)` continua server-only.
- `dispatch(action, request_key=..., params=...)` aceita apenas IDs e opções
  públicas allowlisted. `resolve_parameters(action, params)` resolve no host
  operation_id, stage/backup/release roots, DSN/config e callbacks. Owner,
  principal, tenant, Grant, caminho, SQL/callable e approved não vêm do renderer.
- Reserva e receipt serão persistidos no namespace `shell` da mesma store CP,
  com binding owner/tenant/installation/action/fingerprint e CAS ANTES do efeito.
  Replay PENDING/RUNNING/UNCERTAIN somente consulta; jamais reexecuta.
- C09: delegar a `control.store.backup(directory, quiesced=True,
  file_roots=None,recovery_key=None)` e `.restore(directory,manifest_sha256,
  quiesced=True,file_roots=None,recovery_key=None)`. Snapshot/keys/crypto-file,
  selection e migrations/rollback nativos pertencem Nexo e não serão editados.
- CLI usará `SENTRA_CONTROL_BINDING_FILE` preparado por Nexo e refs `att-*`
  pelo mesmo shell bridge/turno/request_key. Cobalto mantém bytes/upload/
  composer/receipts multimodais e publicará `Cobalto-fechamento.md`.
- Root injeta facade no bridge/center e autoriza callbacks; Tessela não toca
  service.py/__main__.py/graph.py/server.py nem fontes de outros donos.
- Pipeline de release prepara staging isolado e fonte de restamp extension1.7,
  bootstrap/WebModels/hash/proveniência/guest WASM-HCS-RustDesk; nenhuma
  materialização/build/signing executada nesta fase.

As assinaturas prospectivas acima são substituídas pelas APIs finais abaixo.
Entrega de fontes na árvore compartilhada, sem execução de validação ou
materialização. Integração root e ambiente ainda pendentes; este relato não
homologa requisitos. Documentos/Yjs/project review continuam descritos em
`Tessela.md`, sem alterar ownership central.

## Facade e reservas

`sentra_remote.host_facade.VitraFacadeConfig(state_root=..., installation_id=...,
owner=..., install_root=..., exclude_pids=(), product_version="", receipts_path=None)`.
Owner/installation/roots vêm do host. Tenant vem de `control.store`; a facade
não cria autoridade, Grant, WorkItem ou Run.

`VitraHostFacade(config, *, control, authorize, offline, quiesced,
resolve_parameters, checkpoint, conpty_handles, provider_runner=None,
repair_runner=None, migration_handlers=None, reconcile_callback=None, ...)`.
Os kwargs históricos permanecem compatíveis, mas backup/migration não usam
dump SQL/SQLite legados como alternativa à store selecionada.

- `authorize(owner, operation_id, installation_id) -> bool`: política real
  server-only. `offline() -> bool`, `quiesced() -> bool` precisam consultar
  prova atual do host, não flags do renderer. `checkpoint() -> None` revalida
  o fence central imediatamente antes de cada efeito composto.
- `resolve_parameters(action, public_params, *, request_key) -> dict`: resolve
  IDs públicos para Operation, roots, manifesto, recovery key/config e
  callbacks do servidor. Fingerprint precisa incluir revisão de configuração,
  pins e intenção estável; não retornar timestamps transitórios como intenção.
- `dispatch(action, *, request_key, params=None) -> dict`: aceita somente
  `provider,configuration_id,stage_id,backup_id,release_id,migration_id,which,
  expected_revision,request_key,from_version,target_version`. Paths, owner,
  principal/Grant, DSN, SQL, callable e approved enviados pelo cliente negados.
- `status() -> dict`: callbacks, allowlist e `maintenance_revision` atuais.
- `reconcile(request_key, *, expected_revision) -> dict`: host-only, CAS,
  sem reexecução. `reconcile_callback(prior) -> {operation_id,state,
  receipt_id,result}` exige SUCCEEDED/FAILED e concordância com a Operation
  terminal central; evidence local sozinha não concede sucesso.

Reads exatos: `setup_states,doctor,backup_status,update_status,migration_status,
provider_inventory,provider_states,extension_plan,pending_provenance,receipts`.
Effects exatos: `repair,backup_prepare,backup_restore,sqlite_migrate_prepare,
sqlite_migrate_commit,sqlite_migrate_recover,pg_migrate_prepare,
pg_migrate_commit,pg_migrate_rollback,update_stage,update_commit,
provider_configure,provider_install,provider_health,provider_repair,
provider_renew,provider_recovery,provider_remove,provider_revoke`.
`provider_health` é observação receipted, sem quiesce; exige admissão/checkpoint.
Nomes sqlite/pg antigos são aliases de transporte para handlers nativos
injetados; não selecionam backend por nome.

`maintenance_ledger.py` grava no namespace **shell da mesma store CP**,
owner/tenant/installation/action/key/fingerprint, intenção e resultado
protegidos. Reserva PENDING precede o efeito; CAS PENDING1→RUNNING2 antes de
I/O. SUCCEEDED/FAILED/DEFERRED ou RUNNING3 para helper agendado. Exceção,
timeout ou falha de receipt fica UNCERTAIN; mesmo key consulta, nunca repete.
Outra chave não admite efeito enquanto existir PENDING/RUNNING/UNCERTAIN.
Transações BEGIN IMMEDIATE passam pelo lock/compilador PG do Nexo; nenhuma
conexão SQLite paralela ou ATTACH. `lifecycle_effects.py` propaga checkpoint
e configuração host via ContextVar; fallback é
`current_effect_context.get().checkpoint()`.

## C09 e migrations Nexo

`backup_prepare` delega **store.backup(Path(stage), quiesced=True,
file_roots=..., recovery_key=...)**. `backup_restore` delega
**store.restore(Path(stage), manifest_sha256=..., quiesced=True,
file_roots=..., recovery_key=...)**; manifest_sha256 é keyword na API vigente.
Crypto/AESGCM/DPAPI/keyring/gate authority-recovery continuam exclusivamente
Nexo. Nenhum snapshot paralelo foi adicionado.

`migration_handlers[action](trusted_params) -> dict` deve compor
NativeAuthorityMigration.prepare/commit/activate/rollback. Status nativo usa
`trusted_params.status_reader()`, sem fingir estado a partir de journal legado.
Restore pode substituir registros do próprio banco: root deve reconciliar pelo
gate/manifesto/receipt C09, sem promover resposta perdida a sucesso ou repetir
uma operação incerta pela facade. Portabilidade DPAPI entre perfis não alegada.

## App-exit update e rollback

`app_exit_update.schedule_on_exit(*,control,owner,operation_id,
installation_id,state_root,install_dir,prepared,conpty_handles,checkpoint)`
lança o helper real, protegido/exclusivo, fora da árvore instalada. Inventário
ConPTY desconhecido ou com sessões vivas defere. Nenhum processo é sinalizado
nesse caminho; helper espera o PID pai e observa processos Windows via CIM
antes de Setup. Processo do produto cuja localização não pode ser observada
também defere.

`prepared` host-only exige package_root, installer, version, backup_manifest,
backup_manifest_sha256, components e admission. Components tem extension
(version/build_id/source_hash), gateway (integration-build sha256),
runtime_components (quickjs/hcs/rustdesk). `admission` é projeção protegida do
**receipt e request centrais existentes**, mais grant_id e authorization
{principal_type,principal_id,capability,scope_type?,scope_id?,context?}; não
criar nova Operation. Signer é o publisher legítimo da instalação; sem trust
anchor real, não agenda. Mudança schema exige schema_operation_id SUCCEEDED e
schema_backward_compatible=True revisado para o programa anterior.

`load_handoff(path,install_dir)` revalida binding, digest, assinatura, expiração,
offline e Grant/fence na autoridade configured. Helper usa CentralEffectContext
com lock físico/keepalive existentes, claim exclusivo BEFORE Setup,
`--offline-handoff`, verifica componentes instalados e registra resultado
terminal no mesmo central receipt. `read_helper_outcome(path,*,owner,
operation_id,installation_id)` retorna evidence protegida ou UNCERTAIN;
root reconcilia a reserva original. Não relançar helper/Setup após timeout.
Setup offline mantém serviços quiesced: Connect & Verify é diferido para o
restart; não inicia/para processos durante a aplicação coordenada.

`update_helper.py`, `installer.py`, `program_stage.py` integram esse caminho,
preservam installation_id e arquivos desconhecidos; falha de programa usa
backup/quarentena. Schema/C09 recovery/rollback continuam Nexo e requerem
composição root; não alegar rollback completo de autoridade pelo rollback
de arquivos de programa. Fence revogado pode exigir recovery explícito.

## Opcionais reais

`optional_providers.provider_configure/install/health/repair/recovery/remove/
renew/revoke` chamam runners reais. `guest_runners.py` usa winget exact/version
dos pins existentes (Git/Docker/Ollama), probes CLI/daemon reais e timeout
de installer como uncertain. Recovery observa sem repetir installer incerto.
`managed_providers.py` persiste configuração/registro protegido no mesmo CP;
runtime vendored tunnel/pdfium/WebModels/Electron instala bytes de manifesto
host-selected (source_root/version/files[{path,sha256}], quota4GiB), staging
exclusivo, hashes e paths confinados sem links. Não sobrescreve bytes
desconhecidos/modificados. Remove somente arquivos próprios inalterados.
Renew/recovery exigem health_probe(root) real injetado. Configure não declara
ready; ausência de source/live probe/pin é indisponibilidade explícita.
Root precisa ligar os registros/configurações aos consumidores de runtime;
catálogo ou instalação de arquivos não prova daemon/conta/modelo operacional.

## CLI shell, anexos e coordenador

`ShellBridge(config).send_turn(content, *,project_id="",space_id,
conversation_id,request_key,attachments=())` envia UMA `message_send`, refs
att-[a-f0-9]{32} max4. Usa cápsula Nexo SENTRA_CONTROL_BINDING_FILE e bearer
local; não infere projeto por path, não exporta DSN. Journal protegido local
é estado de transporte, não autoridade. Pending/uncertain nunca reenvia;
accepted é ACK, não resposta do modelo. `request_status(key)` consulta esse
journal. Flags: --shell-turn --prompt --project-id --space-id --conversation-id
--request-key --attachment-ref (repetível), --shell-request-status.

Root resolve refs por AttachmentStore e compõe o dispatch_shell_turn do
Cobalto-fechamento.md. PNG/JPEG8MiB/PDF-text20MiB/max4 e chunks/receipt conjunto
continuam no domínio Cobalto; CLI não reenvia bytes nem degrada para texto.
`authority_environment.py` higieniza CP env dos subprocessos de modelo e
remove os bearer/tokens de agent_control do Canvas, mantendo o path da cápsula
CP validada. client.py usa esse helper; token shell do Dot é injetado por root,
nunca propagado por bootstrap de gateway/browser.

Contrato Codex-coordinator-contract.md composto: CanvasBridge lê
SENTRA_CANVAS_AGENT_SCOPE=shell, `execute(raw_args,request_key)` aceita
`coordinator_intent` JSON-value canônico bounded4000 com kind
create_dot/create_team/connect/delegate/handoff/pause/resume/cancel/reassign/
pause_dot/resume_dot e exige chave atual. Nesse scope recusa criação/dispatch
legados; agent.py usa contexto shell, Dot/conversation/Space/agent/conexões,
nenhuma instrução de bootstrap. Directives locais com efeito não contornam
as máquinas/coordenador admitidos. Goal/control mutation legado também negado
nesse scope. Reads/metadados não concedem execução a children.

Allowlist CLI adiciona turn_permission_list/grant/revoke como comandos
**operador** /shell, com Space/conversa/WorkItem canônicos; mutations usam o
journal antes de POST. `work_item_id` só é aceito nesse conjunto específico;
nenhum owner/principal/Grant/opID é passado. agent model não tem directive de
grant. História/goal/continuation reabrem CP configured, sem bootstrap SQLite
na sessão hosted. Root continua dono de token shell:<parent_op>, agent_control,
compose, permissions e validação de processo/parent; Nexo exige requiredcap
explícita no parent. Schema completo dos intents/Grants fica no servidor.

## Pipeline preparado, NÃO executado

- extension_identity.stage_extension_source(source,destination) copia para
  staging isolado, exclui bootstrap HMAC antigo, calcula identity1.7 na cópia
  e escreve sentra-distribution.json. build_windows deixou de restampar a
  fonte/preview. Bootstrap local real continua native_bridge/bootstrap.py,
  domínio Cobalto; não distribuir HMAC de outra instalação.
- build_windows/release_assets exigem metadata WebModels cujo patch_sha256
  corresponde à fonte atual sentra-upstream.patch (snapshots/conta Cobalto).
  Nenhum patch foi aplicado ao runtime nesta rodada.
- release_components.stage_runtime_components(staging,sources) exige fontes
  materializadas quickjs/hcs/rustdesk: WASM+SBOM+provenance+LICENSE-QuickJS,
  manifests nativos compiled:true/files com SHA reais e RustDesk
  control_extension=sentra-desktop-control-v1. Sem hash de binário inventado.
  Source trees/source patch não equivalem a artefatos compilados.
- materialize_release_components.py exige --final-phase-authorized. Workflow
  novo integral-release-components.yml é manual, opt-in explícito e transporta
  artifacts source-pipeline outputs; não foi disparado. Setup/MSI/release
  incluem runtime/ e runtime-components.json.
- runtime_dependencies.py lê SENTRA_BUILD_RUNTIME_PINS_FILE (JSON host-only:
  wasmtime.version exata, files mapa de TODOS os DLL/SO/dylib da distribuição,
  license e license_files SHA reais). Compara pacote instalado com pins,
  collect-all wasmtime no futuro build e transporta licenças/proveniência.
  Nenhuma versão/hashes desse SDK foi inventada ou instalada.
- Setup/release transportam OpenDots MIT/copyright/provenance, Guacamole
  common-js1.5.0 repack Apache LICENSE/NOTICE/SRI, provider notices e Wasmtime.
  Release gera package-components.json/package-artwork.json, CycloneDX com
  runtime files/dependency pins/licenças e checksums. `pending_provenance.json`
  separa source pins conhecidos de artifact_sha256:null.

## Pendências concretas para Codex/Meridiano e donos

1. Root: instanciar/injetar facade nas rotas bridge/center autenticadas,
   resolver IDs/paths/config no host, gates admin/offline reais, checkpoint,
   ConPTY registry Pulso, repair plano/runner e reconcile_callback. Manter
   intenção/configuração estáveis por key; não aceitar authority fields.
2. Root/Nexo: adapters migration/status/C09 nativos, actual backup receipt,
   schema compatibility/recovery, handoff da admission existente e lease até
   saída do app. Parent não sela SUCCEEDED ao agendar helper; sucesso vem
   do receipt terminal. Mudança de seleção/revogação/expiração bloqueia apply.
3. Root/Cobalto: compor uma submissão CLI+anexos, protected bytes e receipt;
   root coordinator token/context/permissions conforme contrato publicado.
   Prisma mantém UI de Grants. Ajustes CLI desta rodada estão disponíveis.
4. Prisma/Forja: produzir WASM/SBOM/licenças e artefatos HCS/RustDesk nativos
   na fase futura, com manifest compiled:true/files/proveniência. Forja
   preserva fonte AGPL e control extension; source patch não é binário pronto.
5. Host de release: selecionar/pinar Wasmtime e wasi-sdk/toolchains legítimos,
   materializar payloads e WebModels da fonte atual, publisher Authenticode
   legítimo, signing/release final. A seleção SDK ainda não está provisionada;
   o pipeline recusa empacotar sem pins/arquivos reais.
6. Integração de registros opcionais aos consumers e evidência de ambiente;
   validação geral PG/CAS/revogações/crash/restore/ConPTY/duas máquinas/release
   somente após TODAS as frentes integradas e autorização da fase final.

Nenhum teste, build, install, lint, benchmark, QA, re-stamp ou interação de
preview foi executado. Sem commit/push/reset/stash/recrutamento e sem edição
dos arquivos centrais root/Nexo/Cobalto/Prisma/Forja/Lume. Relato por arquivo
para Codex/Meridiano, conforme redistribuição; sem ask-back síncrono.
