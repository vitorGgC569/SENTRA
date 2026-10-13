# Expansao integral ? Tessela

Responsavel: Tessela. Emitido por Meridiano em 11/10/2026 com autorizacao explicita do usuario.

## Ordem atual

Implementar ACL/WorkItem/grants vinculados a project_id/space_id/document_id; permissao de documento nao autoriza Space. Atual CollaborationAuthority.issue so workspace precisa ampliacao. Rich/Markdown/source/tables/hierarchy/autosave dirty-saving-saved-error-conflict/draft recovery, CAS expected_revision e mutation_id+receipt, history/restore cria revisao/delete. Yjs version/wire/persist/undo por origem/relative cursors, awareness clock TTL authenticated session, host reauth/precommit/reconnect. PDF/code/diff/watch/debounce/rename/limites sem executar preview. Publicar allowlist document_* e sessao Yjs exata a Codex/Prisma e ProjectDocuments props/dispatch.

## Regras e contrato de entrega

- Implementacao integral primeiro. NAO executar testes, builds, lint, benchmarks, QA ou homologacao.
- Preservar ownership de docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md; arquivos centrais pertencem ao Codex. Enviar assinatura/solicitacao ao dono para composicao.
- Opcionais permanecem requisitos completos: configuracao, fluxo real, estado indisponivel explicito, cancel/revoke/recovery e distribuicao. Deny-only, stub e fixture nao substituem implementacao.
- Nao recrutar, commit/push/reset/stash nem remover alteracoes alheias.
- Ler integralmente estudo de dominio, nota e docs/integral/requirements.md / contracts.md.
- Registrar resultado/arquivos/assinatura/esquemas/dependencias/pendencias/plano futuro em docs/integral/Tessela.md; assinatura cedo para Codex.
- Regra ATUAL: OpenCode esta em TUI interativa persistente com --session existente e --auto, sem run. NAO relancar via raw agora. Este arquivo e referencia de escopo; progresso por docs, sem ask sincrono; prompts simples somente com UI do agente confirmada.

## Criterio de cobertura

Codigo concreto + composicao HTTP/Canvas/CLI/Desktop/Control Plane pertinente + evidencia runtime futura. Nada homologado nesta fase. Reportar fatos e limites; nao fechar requisito por presenca de modulo.


## Comunicacao atual (supera run/relaunch anteriores)

Seis OpenCode em TUI persistente --session existente --auto. Nao relancar por raw agora; progresso por docs/integral/Nome.md, evitar ask sincrono. Prompts simples so com UI agente confirmada. Nada homologado; todas expansoes permanecem escopo.


## Dependencia de composicao nativa Postgres/documentos

Inventario atual: ProjectDocuments._guard usa ATTACH DATABASE auth/gov/core; PostgresControlPlaneStore.path_for retorna None e native_sql rejeita ATTACH. Coordenar Nexo/Tessela/Codex guarda transacional nativa de scope/revoke/CAS na mesma autoridade. Nenhum teste agora; nao reduzir multiusuario/documentos ao modo SQLite. Permission do cliente Tessela ja corrigida, nao repetir essa lacuna historica.


## Correcao do inventario anterior

Tessela entregou authority_guard Postgres nativo/guards; antiga incompatibilidade documental ATTACH-only esta superada em fonte. Nexo entregou binding shell provider_usage local. Manter apenas composicao/consumer compatibilidade restante e provas runtime futuras; nao reabrir implementacoes ja entregues por busca historica. Nenhuma homologacao.


## Backlog vigente de fechamento - Meridiano

Dono ATUAL desta frente: Tessela; autoria original Tessela preservada. Redistribuicao supera takeover anterior; nao relan?ar OpenCode. [Backlog integral](../fechamento-backlog.md) e [dados por clausula/corpo](../fechamento-backlog-data.json): FB-20, FB-23, FB-25, FB-33, FB-35, FB-40, FB-45, FB-52, FB-53, FB-55, FB-56, FB-57, FB-58, FB-59, FB-60, FB-61, FB-62, FB-63, FB-64, FB-65, FB-66, FB-68, FB-69.

Os IDs incluem dependencias de composicao, nao autorizacao para editar outros donos. Ler required_change/constatacao e source_clause_audit antes de reduzir qualquer opcional. Root/Nexo mantem pontos centrais; relatos por arquivo, sem ask-back. Nenhum teste/build/install/lint/benchmark/QA agora; PID47408 preservado.
