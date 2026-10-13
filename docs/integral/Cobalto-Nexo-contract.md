# Contrato Cobalto / Nexo — 2026-10-11

Fase de implementação; nenhuma validação executada ou homologação alegada.
Atualização: `REDISTRIBUICAO_CODEX.md` supersede o repasse de seis frentes:
Cobalto Brisa/Rastro, Forja Selo, Lume Pulso, Tessela Vitra, Prisma Pacto.
As reservas Nexo descritas abaixo continuam. `authorization.py` e guards Selo
estão livres para Forja; não serão editados por Nexo.

## Ownership sem concorrência

Nexo continua editando `sentra_core/*`, `sentra_runtime/*` e os serviços
`control_store.py`, `postgres_store.py`, `authority_migration.py`,
`postgres_rollback.py`, `control_plane.py`, `durable.py`, `governance.py`,
`budget_policy.py`, `context*.py`, `shell_coordinator.py`. Novos helpers de
snapshot/recuperação desses serviços permanecem Nexo. Não estou editando
`authorization.py`, `capabilities.py`, os guards Selo, browser, voice,
attachments, checkpoints, CLI, qualidade ou os módulos transferidos a Cobalto.
`sentra_collab/authority_guard.py` permanece Tessela. Canvas e CodeMachine
permanecem root. Cobalto pode avançar nos seus guards sem aguardar resposta.

## API PostgreSQL nativa vigente

`create_control_plane_store(state_root, backend="configured", dsn=None,
tenant_id=None, principal_id=None)` retorna a autoridade escolhida, sem fallback
SQLite diante de erro/configuração PG incompleta. `store.backend == "postgres"`,
`store.schema(namespace)`, `store.lock_key(namespace)`, `store.connect(namespace)`.
`path_for(namespace)` retorna `None`: não fazer ATTACH nem abrir SQLite por fora.
`db.raw` é conexão psycopg nativa; `db._begin()` inicia a transação e verifica
membership; lock nativo é `SELECT pg_advisory_xact_lock(%s)` com `store.lock_key`.
Guard de múltiplos namespaces adquire locks em ordem de nomes, seguido de
`SELECT FOR UPDATE` nas linhas Run/WorkItem/Grant relevantes e schemas qualified.
`db._locked=True` informa ao wrapper que o lock do seu namespace já foi tomado.
`db.execute` aceita qmarks apenas nas formas SQL explicitamente compiladas;
`db.raw.execute` usa `%s`. Nenhuma conversão implícita de ATTACH, WAL, secure_delete
ou lastrowid. `db.scope_lock()` é reutilizável. Context/durable usam conexão
persistente; outros serviços devem fechar suas conexões. Roles reader negam writes.
RLS owner e membership tenant/principal são obrigatórios; runtime superuser/BYPASSRLS
é rejeitado. Namespaces novos registrados incluem shell, machine_input_control,
interop_projections/interactions/installations/push e channels.

## Crypto e recuperação

Payloads sensíveis usam `sentra_core.conversations._encode/_decode` (proteção
DPAPI/keyring existente); não registrar texto, tokens, DSN ou bytes crus em journal.
Seleção de autoridade e cápsula CLI são protegidas pelo mesmo codec. Backup nativo
v2 usa `authority_snapshot.SnapshotCodec` AESGCM com chave de arquivo wrapped por
OS e opcionalmente recovery_key host-only (32 bytes); guarda ciphertext real,
arquivos/artefatos e valores referenciados no keyring. API:
`store.backup(directory, *, quiesced, file_roots=None, recovery_key=None)`;
`store.restore(directory, *, manifest_sha256, quiesced, file_roots=None,
recovery_key=None)`. Raiz padrão é tenant; artefatos externos exigem raízes
explícitas do host. Restore exige os paths originais, schemas compatíveis e
memberships intactas. Gate persistente `authority-recovery.json` bloqueia
autoridade se o restore de banco/arquivos não acabar; repetir o mesmo manifesto
recupera sem replay. DPAPI interno exige perfil original para preservar bytes e
hashes; não alegar migração entre perfis por causa do wrapping externo.
Novos arquivos `authority_snapshot.py`, `postgres_store.py`, `authority_migration.py`,
`postgres_rollback.py`, `authority_paths.py` e selection são reservados Nexo/C09. Tessela compõe Vitra
nessas APIs e não reimplementa crypto/backup paralelo. Não trocar formatos/keys
de arquivos compartilhados durante essa fase.
Requisito de quiesce, digest do manifesto e recovery sem replay permanece obrigatório.

## Runtime e CLI

`CanvasAuthorityRuntime(state_root, canvas_store, *, control, owner)` reutiliza
control/durable/governance/budgets/store. Não criar TaskRuntime SQLite em hosted.
`prepare_provider_binding(control, *, state_root, owner, principal,
conversation_id, run_id, work_item_id, operation_id, project_id,
ttl_seconds=3600)` em `sentra_runtime.provider_authority` retorna
`{environment:{SENTRA_CONTROL_BINDING_FILE:path}, backend,...}`. O root injeta
somente o path de cápsula protegida no subprocess; nunca DSN plaintext. Fábrica
configured e UsageLedger verificam a cápsula e o binding atual. Higienizar env
herdado antes da injeção. `UsageLedger(...,control=control)` aceita autoridade
existente. Binding shell é `canvas_shell_provider_bindings` no namespace shell.

## Optional authority

`sentra_runtime.shell_optional_authority.execute_optional` cria WorkItem de usuário,
intenção imutável e Operation fenced antes de voice/attachment callback. Grants
persistidos são exigidos em hosted; local-owner apenas CanvasShellRuntime SQLite
autêntico. Cleanup stop/revoke/upload_abort tem intenção de cleanup e fence,
inclusive em Run não RUNNING, sem novo Grant. Callback recebe IDs autoritativos e
conversa canônica. Cada HTTP/filesystem effect composto deve chamar
`current_effect_context.get().checkpoint()` imediatamente antes; não basta um fence
antes de vários efeitos. Callback retorna ack de signaling/storage; não provar
conclusão remota. Falha/revogação após efeito vira UNCERTAIN, nunca reenvio automático.
Não criar autoridade/Grant paralelo nos adapters. Reads que realmente fazem provider
I/O precisam caminho de observação/política explícito; status puramente local não.

## Fechamento

Nexo registrará contrato final e pendências reais em `docs/integral/Nexo.md` e
reportará ao root/Meridiano. Este arquivo é suficiente para coordenação sem
ask-back bloqueante. Testes/build/lint/benchmark/QA continuam proibidos nesta fase.
