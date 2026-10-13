# Contrato de integração do shell OpenDots no SENTRA

Este é o contrato de composição acordado para a implementação coordenada. Ele cria uma rota da aplicação Canvas existente e não uma segunda autoridade. O handler vive na camada HTTP de `sentra_canvas` e chama o serviço já composto por `Canvas`/Control Plane.

## Rota e envelope

- Todas as operações do shell usam `POST /api/shell/bridge`, JSON e o mesmo bearer local obrigatório das demais APIs `/api`. Não existe GET com efeito.
- O envelope admite `action` (string allowlisted), `request_key` (UUID ou chave de deduplicação), `project_id` (id do workspace Canvas atual), `space_id`, `conversation_id` e campos específicos da ação. IDs devem ser validados no workspace e na autoridade. Não aceitar `owner`, principal, Grant, permissão ou caminho fornecidos pelo browser: derivar identidade e escopo da sessão autenticada e do Control Plane.
- `project_id` identifica o workspace autoritativo Canvas. Para a conversão durante a migração, a ponte aceita `ws` como alias legado de entrada e o normaliza a `project_id`. Toda resposta canônica emite `project_id`; qualquer `ws` emitido é alias transitório para compatibilidade.
- Space guarda `project_id` como workspace Canvas associado. A associação é explícita, persistida e conferida em cada chamada. Não inferir identidade do projeto a partir de diretório, nome da conversa, browser, terminal ou estado enviado pelo renderer.
- A UI pode conservar os componentes com payloads em snake_case (`space_id`, `document_id`, `project_id`). `dispatch({action, ...payload})` envia-os pela rota única.

## Ações

Leituras: `home`, `space_list`, `space_get`, `dot_list`, `conversation_list`, `message_list`, `events`.

Criações e mudanças com IDs validados e `request_key`: `space_create`, `dot_create`, `dot_update`, `conversation_create`, `message_send`, `coordinate` e todas as ações `document_*` do contrato Tessela.

`home` devolve Spaces, Dots, conversas recentes, estado do projeto/atividade e capabilities realmente concedidas. Listas preservam paginação e autorização por workspace. Mutações duráveis verificam idempotência no Control Plane.

`dot_create` e `coordinate` somente criam/alteram agentes pelo fluxo de admissão e autoridade do Control Plane. `coordinate` recebe uma intenção **estruturada e allowlisted** (por exemplo criar equipe, relacionar, delegar, pausar); conteúdo em prosa nunca é interpretado como autorização ou comando. A aprovação obrigatória cria estado pendente, não executa o efeito.

`message_send` insere a mensagem na conversa identificada e despacha ao Dot usando o adaptador de runtime existente. Responder `{"ok":true,"value":{"conversation_id":"…","message_id":"…","status":"queued|dispatched|waiting_approval","operation_id":"…","receipt_id":"…"}}`; em falha definitiva retornar erro HTTP com motivo sanitizado. Não reportar entrega concluída antes de existir receipt. Falha ambígua retorna estado `uncertain` e o mesmo `request_key` pode consultar/deduplicar, nunca duplicar o envio.

Resposta de mutação aceita: `{"ok":true,"value":{...},"request_key":"…"}`. Leituras usam o mesmo invólucro. Erros seguem o envelope SENTRA `{"error":"motivo sanitizado"}` com status HTTP apropriado. IDs de Run/WorkItem/Operation/Receipt ficam visíveis para a UI como projeção, sem torná-la fonte de autoridade.

## Documentos e colaboração (Tessela)

O namespace canônico é `canvas_collaboration`, sempre ligado ao workspace Canvas autenticado. Ações do bridge incluem `document_list`, `document_get`, `document_create`, `document_save`, `document_history`, `document_restore`, `document_delete` e ações de sessão Yjs explicitamente enumeradas pelo serviço.

O serviço compõe o host por chamada interna autorizada e autentica identidade/sessão no servidor. Nunca publicar a credencial owner HTTP no browser. A abertura de colaboração exige WorkItem e Grants `canvas.collab.read`/`canvas.collab.write` presos a `workspace_id`, `space_id` e `document_id`; autorização para um documento não se estende ao Space inteiro. Escritas usam `expected_revision` (CAS), `mutation_id` idempotente e receipt. Yjs é estado colaborativo versionado; o host valida e registra snapshots no mesmo histórico autoritativo. Restore cria nova revisão em vez de reescrever história.

O bridge React de documento segue `bridge({action, ...payload})` com `space_id`, `project_id`, `document_id`; props: `spaceId`, `projectId`, `documents`, `onRefresh` e `onError`. O renderer não instancia autoridade, WorkItem ou Grant.

## Integração e ownership

- Nexo: serviço Spaces/Dots/conversas/coordenação na store central e métodos de dispatch autoritativos; enviar assinatura e esquema de retorno final ao Codex.
- Codex principal: registrar a rota POST no handler HTTP, exigir autenticação bearer existente, converter o body sem perder o request key e compor os métodos de `Canvas`/Control Plane; preservar seus limites de tamanho e tratamento de erro.
- Prisma: criar o único cliente UI `shellBridge`, persistir navegação no Space/projeto, usar apenas esse bridge para operações do shell; não converter texto livre em comandos.
- Tessela: encaixar `ProjectDocuments` no mesmo dispatch, manter ACL/WorkItem/Grant, CAS, Yjs e receipts conforme acima; não criar endpoint autenticado paralelo nem expor `owner` ao renderer.
- Migração: workspaces Canvas existentes recebem Space vinculado por ID preservado e migração repetível/idempotente. Não copiar ou renomear projetos para fazer o vínculo.

Esta definição é contrato de implementação, não declaração de que rotas ou integrações já existam. Respeitar a instrução do usuário: não executar validação até todas as implementações e composições terem terminado.
