# Expansao integral ? Nexo

Responsavel: Nexo. Emitido por Meridiano em 11/10/2026 com autorizacao explicita do usuario.

## Ordem atual

Implementar backend Postgres nativo com migrations de namespaces, isolamento por tenant/principal, SQL/transacoes/locks/fencing equivalentes, recovery, backup/restore e rollback; manter SQLite local. Nao emular Postgres com SQL SQLite. Publicar IMEDIATAMENTE assinatura de Spaces/Dots/conversas/coordinate/message_send para Codex e Prisma: project_id, request_key, identidade servidor, Operation e receipt/uncertain. Migrar projetos existentes idempotentemente; equipe/delegacao/pause/reorganize por intencao estruturada aprovada, mesma autoridade.

## Regras e contrato de entrega

- Implementacao integral primeiro. NAO executar testes, builds, lint, benchmarks, QA ou homologacao.
- Preservar ownership de docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md; arquivos centrais pertencem ao Codex. Enviar assinatura/solicitacao ao dono para composicao.
- Opcionais permanecem requisitos completos: configuracao, fluxo real, estado indisponivel explicito, cancel/revoke/recovery e distribuicao. Deny-only, stub e fixture nao substituem implementacao.
- Nao recrutar, commit/push/reset/stash nem remover alteracoes alheias.
- Ler integralmente estudo de dominio, nota e docs/integral/requirements.md / contracts.md.
- Registrar resultado/arquivos/assinatura/esquemas/dependencias/pendencias/plano futuro em docs/integral/Nexo.md; assinatura cedo para Codex.
- Regra ATUAL: OpenCode esta em TUI interativa persistente com --session existente e --auto, sem run. NAO relancar via raw agora. Este arquivo e referencia de escopo; progresso por docs, sem ask sincrono; prompts simples somente com UI do agente confirmada.

## Criterio de cobertura

Codigo concreto + composicao HTTP/Canvas/CLI/Desktop/Control Plane pertinente + evidencia runtime futura. Nada homologado nesta fase. Reportar fatos e limites; nao fechar requisito por presenca de modulo.


## Comunicacao atual (supera run/relaunch anteriores)

Seis OpenCode em TUI persistente --session existente --auto. Nao relancar por raw agora; progresso por docs/integral/Nome.md, evitar ask sincrono. Prompts simples so com UI agente confirmada. Nada homologado; todas expansoes permanecem escopo.

Dependencia do principal: compor provider_usage no ControlPlaneService consumido por CanvasShellRuntime CLI ja criado, mantendo budgets/quota/custo desconhecido autoritativos. Registrar assinatura/binding em Nexo.md; nenhuma validacao agora.


## Dependencia de composicao nativa Postgres/documentos

Inventario atual: ProjectDocuments._guard usa ATTACH DATABASE auth/gov/core; PostgresControlPlaneStore.path_for retorna None e native_sql rejeita ATTACH. Coordenar Nexo/Tessela/Codex guarda transacional nativa de scope/revoke/CAS na mesma autoridade. Nenhum teste agora; nao reduzir multiusuario/documentos ao modo SQLite. Permission do cliente Tessela ja corrigida, nao repetir essa lacuna historica.


## Correcao do inventario anterior

Tessela entregou authority_guard Postgres nativo/guards; antiga incompatibilidade documental ATTACH-only esta superada em fonte. Nexo entregou binding shell provider_usage local. Manter apenas composicao/consumer compatibilidade restante e provas runtime futuras; nao reabrir implementacoes ja entregues por busca historica. Nenhuma homologacao.


## Backlog vigente de fechamento - Meridiano

Dono ATUAL desta frente: Nexo; autoria original Nexo preservada. Redistribuicao supera takeover anterior; nao relan?ar OpenCode. [Backlog integral](../fechamento-backlog.md) e [dados por clausula/corpo](../fechamento-backlog-data.json): FB-01, FB-02, FB-03, FB-07, FB-08, FB-10, FB-11, FB-13, FB-14, FB-18, FB-24, FB-25, FB-26, FB-30, FB-32, FB-33, FB-37, FB-38, FB-39, FB-40, FB-41, FB-43, FB-44, FB-46, FB-47, FB-48, FB-51, FB-53, FB-54, FB-56, FB-57, FB-58, FB-60, FB-61, FB-62, FB-65, FB-67, FB-68.

Os IDs incluem dependencias de composicao, nao autorizacao para editar outros donos. Ler required_change/constatacao e source_clause_audit antes de reduzir qualquer opcional. Root/Nexo mantem pontos centrais; relatos por arquivo, sem ask-back. Nenhum teste/build/install/lint/benchmark/QA agora; PID47408 preservado.
