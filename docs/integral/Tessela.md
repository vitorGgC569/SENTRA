# Tessela — documentos e colaboração integral

Atualização de ownership: documentos/Yjs/project review mantidos; fechamento
Vitra e CLI shell/coordinator entregue em `Tessela-fechamento.md`, com APIs
concretas, C09 Nexo, pipeline futuro e pendências root/ambiente. A redistribuição
vigente pede coordenação por arquivo, sem ask-back síncrono. Nenhuma nova
validação ou materialização foi executada.

Data: 2026-10-11. Implementação entregue na árvore compartilhada; validação final **não executada nem liberada**. Não houve teste, build, lint, benchmark, QA visual, instalação, commit, push, reset ou stash. Mudanças dos outros responsáveis foram preservadas.

## Requisitos e fontes do domínio

Aplicados o plano `SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md`, contrato `SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md`, nota Maestri conectada, pesquisa `SENTRA_RESEARCH_OPENDOTS/SENTRA_OPEN_DOTS_RESEARCH.md` (CF03–06, G10/G13, A18/A20), auditoria/reavaliação/reuse dos 37 projetos (Yjs, y-protocols, Hocuspocus), análise Chat On Steroids (editor/PDF/code/diff/watch), Gate5 e checkpoint 2026-10-09. Referências locais de código: Yjs RelativePosition/UndoManager; y-protocols awareness clocks/TTL; Hocuspocus Database/ClientConnection/Hocuspocus; CoS file-code-editor e arquitetura do preview.

Implementação original de adaptação ao SENTRA, sem copiar código/assets Anil ou importar backend OpenDots. Bibliotecas reais preservam seus avisos/licenças na distribuição pelos manifests e bundles existentes. A família runtime continua Yjs 13/y-protocols 1/Hocuspocus 4.7; não há migração implícita para os clones Yjs 14 RC/@y/protocols.

APIs editoriais conferidas em documentação primária: [TipTap Markdown](https://tiptap.dev/docs/editor/markdown/getting-started/basic-usage), [TableKit](https://tiptap.dev/docs/editor/extensions/functionality/table-kit), [CodeMirror configuração](https://codemirror.net/examples/basic/), [CodeMirror API](https://codemirror.net/docs/ref/). Isso foi consulta de contrato de API, não execução de validação.

## Entrega implementada

- Documentos Space/projeto no namespace central `canvas_collaboration`, com identidade do servidor, ACL vinculada a WorkItem/Grants de documento e rechecagem na transação de leitura/escrita.
- CRUD, hierarquia acíclica, paginação, Markdown/texto/código, limites de conteúdo, hashes, CAS `expected_revision`, `mutation_id` vinculado ao conteúdo, deduplicação e receipt na mesma transação da revisão. Operations centrais ficam correlacionadas a Run/WorkItem/receipt e são cercadas contra cancelamento antes do commit.
- Revisões imutáveis; restore acrescenta revisão e revalida hierarquia atual; exclusão mantém tombstone e histórico e não permite recriação silenciosa. Pai com filhos ativos não é excluído implicitamente.
- Editor TipTap real com Markdown, títulos, listas, citações, código, tabelas e operações de tabela, undo/redo, fonte e export. CodeMirror real com gutters, sintaxe, folding, histórico local e seleção.
- Menu de comandos `/` do editor rico com teclado (setas/Enter/Escape), paginação do histórico e recuperação de comandos create/restore/delete pendentes em IndexedDB: resposta perdida consulta a mesma mutation_id, sem iniciar outra alteração silenciosamente.
- Estilos documentais herdam a paleta clara `--shell-ink`/`--shell-line` do shell OpenDots dentro de `.opendots-shell`; fallback do domínio preserva uso fora do shell. Nenhuma inspeção visual foi executada.
- Autosave dirty/saving/saved/error/conflict, preservação de rascunhos IndexedDB, recuperação explícita, chave da tentativa preservada em falha ambígua, proteção contra resposta de documento anterior, beforeunload e `onDirtyChange` para o shell guardar navegação.
- Documentos Yjs com Y.Text `content` e Y.Map `metadata`; schema documental estrito separado de layout/notes/nodes; snapshots derivam do sidecar e são gravados no mesmo histórico autoritativo. Credencial owner permanece no host. Tickets de uso único, escopo projeto/Space/documento, revogação reconsultada, emissão/close deduplicados com recibos; replay do ticket cifrado por DPAPI/keyring.
- Gate precommit valida shadow Y.Doc, espera persistência/CAS e só então autoriza publicação. Commit incerto mantém quarantine; reconexão recusa cache com revisão divergente e nova carga reconstrói um documento do snapshot central. Uma edição CAS externa invalida tickets Yjs antigos.
- Undo Yjs acompanha somente origem local; posições relativas de seleção/cursor; awareness do servidor carimba identidade e mantém clocks/TTL de y-protocols, propriedade de client ID e remoção autenticada de presença.
- Interface colaborativa não chama salvo por uma atualização local: consulta document_get e exige conteúdo/receipt da revisão central para remover pendência e rascunho. Desconexão deixa editor indisponível para novas escritas até reautenticação/sync.
- Arquivos reais do workspace, código, diff Git e PDF visual passivo/textual no mesmo bridge. O preview não executa código nem entrega PDF ativo ao browser; limites e isolamento PDFium anteriores foram preservados.
- Watchers bounded, debounce .35 s, handles por projeto, quota 128, TTL 300 s e detecção de rename por dev/inode único na mesma pasta limitada a 300 entradas. Links/junctions/protegidos não são seguidos. Watch nunca concede escrita.
- Guard SQLite usa ATTACH das autoridades + BEGIN IMMEDIATE. Guard PostgreSQL usa schemas do mesmo tenant, ordem global sorted dos locks advisory authorization/canvas_collaboration/durable/governance e SELECT FOR UPDATE em membership, Grant, WorkItem, Run e Operation. Papel reader recusa commits. Sem fallback SQLite ao configurar Postgres.

## Arquivos deste ownership

- `sentra_canvas/project_documents.py` — serviço documental central e callbacks host.
- `sentra_canvas/project_review.py` — rename watcher, registry de handles, adapter de leitura para shell; mecanismos existentes de edição owner-reviewed/PDF preservados.
- `sentra_collab/authority_guard.py` — transação de autorização SQLite/PostgreSQL.
- `sentra_collab/authority.py` — issue documental composto e guard portável.
- `sentra_collab/policy.mjs`, `precommit.mjs`, `server.mjs`, `central_bridge.mjs` — wire/schema/precommit documentais junto do serviço existente.
- `sentra_canvas/desktop_ui/src/document-panel.jsx`, `document-panel.css`, `document-rich-editor.jsx`, `document-code-editor.jsx`, `document-drafts.js`, `document-project-files.jsx`, `collaboration-document.js` — interface, persistência local e conexão real ao sidecar.
- `sentra_collab/test/test_project_documents.py`, `sentra_collab/test/document_precommit.test.mjs` — casos preparados para execução futura.

O `sentra_collab/document_policy.mjs` já estava untracked ao iniciar e foi reutilizado/preservado. Não houve alteração em `service.py`, `__main__.py`, arquivos de shell nem manifests da UI por Tessela. Prisma inseriu componente e dependências; Codex compôs HTTP/Canvas; Nexo forneceu resolvedores e contrato PostgreSQL.

## Contratos exatos de integração

```python
ProjectDocuments(control, *, owner, resolve_space, resolve_run=None, clock=time.time)
# resolve_space=lambda sid,pid: control.shell.get_space(sid, owner, project_id=pid)
# resolve_run=lambda pid: control.shell.resolve_run(pid, owner)
documents.dispatch(action, payload, *, project_id, principal_id,
                   principal_type="user", work_item_id=None)
documents.host_call(method, params)
CollaborationAuthority(control, *, owner, clock=time.time, documents=None)
authority.issue(workspace_id=..., project_id=..., space_id=..., document_id=...,
                principal_id=..., work_item_id=..., permission="read|write", ...)
ProjectReviewService(resolve_root)
# resolve_root=lambda pid: canvas.store.workspace(pid)["path"]
project_review.dispatch(action, payload, *, project_id)
```

Allowlist documental: `document_list`, `document_get`, `document_create`, `document_save`, `document_history`, `document_restore`, `document_delete`, `document_diff`, `document_export`, `document_session`, `document_session_close`.

Allowlist de leitura de arquivos: `project_file_list`, `project_file_preview`, `project_file_diff`, `project_file_pdf_text`, `project_file_pdf_visual`, `project_watch_start`, `project_watch_poll`, `project_watch_close`.

Callbacks privados `/api/collab/host`: `documentResolveGrant({token,workspaceId,documentId})`, `documentCheckGrant(context+action)`, `documentConsumeNonce(context+fingerprint)`, `documentLoadSnapshot({workspaceId,documentId,context})`, `documentCommitSnapshot({workspaceId,documentId,principalId,epoch,context,expectedRevision,snapshot,presentation,mutation_id})`. Snapshot é base64 no RPC e Uint8Array no sidecar; presentation é `{content,metadata:{title,format,language}}` derivada pelo sidecar. Context contém `workspaceId`, `spaceId`, `documentId`, `principalId`, `permission`, `epoch`, `expiresAt`; inteiro epoch é buscado por fingerprint único sob o lock da transação (compatível SQLite/PG).

O shell deriva `project_id` e identidade autenticada; nunca aceita owner/principal/Grant/permissão/WorkItem/Run/caminho de arquivo nas ações documentais. Para `project_file_*` somente caminho **relativo de leitura** é aceito; root é derivado de Canvas. Codex confirmou composição das duas allowlists e callbacks. Prisma confirmou path permitido somente nas oito ações de leitura e allowlist no cliente.

`document_list` retorna `{items:[{document_id,project_id,space_id,parent_id,title,format,language,revision,updated_at,deleted,sha256}],next_cursor:null|string}`. Document_get acrescenta content, committed e receipt_id. Saves acrescentam receipt_id, operation_id, run_id, work_item_id, mutation_id e committed. Session retorna documentName, token scoped, permission derivada, epoch, expiresAt, receipt_id; **Canvas acrescenta url WebSocket do processo já supervisionado**. Reconnect pede novo request_key/ticket; ticket consumido não é reaproveitado.

```jsx
<ProjectDocuments bridge={payload => shellBridge(payload)}
  spaceId={spaceId} projectId={projectId} documents={documents}
  onRefresh={result => ...} onError={error => ...}
  onDirtyChange={({dirty,status,documentId,spaceId,projectId}) => ...}/>
```

Bridge envia POST `/api/shell/bridge`; documentos usam somente esse dispatch. Host do painel permanece montado/hidden ao alternar Canvas/conversa. Callback onDirtyChange delega guard de Space/projeto ao shell; troca de documento mantém guard interno. Rascunho local não concede direitos nem altera revisão central.

Prisma adicionou TipTap **3.31.3** (`react`, `starter-kit`, `extension-table`, `extension-link`, `markdown`) e CodeMirror (`state 6.5.2`, `view 6.38.8`, `commands 6.8.1`, `language 6.11.3`, `language-data 6.5.1`). Imports canônicos: `{Markdown}` de `@tiptap/markdown`, `{TableKit}` de `@tiptap/extension-table`.

## Pendências reais e validação futura

A implementação desta frente e as composições informadas por Codex/Prisma/Nexo estão entregues. **Não se declara homologada por leitura de código.** Dependências novas ainda não foram instaladas/resolvidas em lock nem bundles reconstruídos, por ordem do usuário. PDFium, Node/Hocuspocus/Yjs, PostgreSQL/psycopg e DPAPI/keyring dependem de configuração/instalação real; ausência gera erro explícito e nenhum sucesso simulado.

Depois da liberação global pelo Codex: executar casos Python/Node preparados e suites anteriores de colaboração; adicionar/rodar integração HTTP do shell com bearer e callbacks; dois clientes reais editar Markdown/código e confirmar receipts; crash antes/depois do commit, restart/reconnect, nonce replay, revoke no barrier, read-only e troca de Run/Space/projeto; conflito CAS com draft recovery; hierarquia/restore/delete; presença clock/TTL/cursores relativos e undo local; watchers debounce/rename/link/TTL; PDFium real/ausente e arquivos grandes; tiptap/CodeMirror WebView2, teclado, foco, DPI 100/125/150% e contexto oculto sem perda de rascunho. Para PostgreSQL configurado: concorrência multi-processo, RLS/membership revoke e backup locks, sem usar resultado SQLite como evidência PG.

Lockfile, bundles e evidências de runtime/visual pertencem à etapa final integrada. Não foram executados comandos de validação nesta frente.
