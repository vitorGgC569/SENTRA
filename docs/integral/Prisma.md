# Prisma — shell OpenDots e conversas

Data: 11/10/2026. Implementação de fontes entregue; integração dos serviços opcionais e validação final ainda dependem da composição coordenada. Não declarar homologação a partir deste documento.

## Requisitos e fontes

- Instruções de ownership e fase: `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md` e contrato `docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md`.
- Nota Maestri `todos-os-projetos-ja-estao-clo`, incluindo referência visual explícita CopilotKit/OpenDots e Canvas como vista interna da experiência de conversas.
- Estudo OpenDots em `../SENTRA_RESEARCH_OPENDOTS/SENTRA_OPEN_DOTS_RESEARCH.md`: hierarquia Space/Dot/conversa, revisão/autosave, estado verdadeiro, aprovação, recibos, recuperação e expansão CF15.
- Estudos CoS (34 frentes), ecossistema/reavaliação dos 37, reuse, Gate5 e checkpoint: domínio visual, recuperação de eventos, documentos, UX acessível, histórico, export, modelos e integrações contextuais. Implementações de backend continuam com seus donos.
- Referência de código CopilotKit/OpenDots: objetos `App.tsx`, `style.css` e `Mascot.tsx` em HEAD `625452e06cde74cb25b0ce319e2c1be0488f5a5f`. Diretório sem worktree; não houve checkout, instalação ou execução upstream. Organização/paleta adaptadas; mascotes originais incorporados na expansão posterior autorizada. Sem backend Intelligence ou telemetria upstream. Não copiado código Anil.

## Implementação concreta

- Home com Dots, conversas recentes, Spaces e estado real do Run. Navegação por Home/Conversas/Dots/Spaces; projeto explicitamente selecionado. Preferência local conserva IDs e vista, sempre sujeitos à validação no servidor.
- Canvas existente fica montado dentro do shell; PTYs/xterm e grafo mantêm seus componentes. Atalhos exclusivos do Canvas ficam limitados à vista Canvas. Duplo clique num agente abre conversa do Dot correspondente pelo mesmo `agent_id`.
- Inspector existente é montado por portal no painel contextual. Arquivos/diff/PDF, histórico, permissões, Skills, plugins MCP, browser/máquinas, entrega Web/Compact & Resume e terminais usam as integrações reais já existentes. Nenhum processo é criado ao trocar de vista.
- Dots criados por admissão central com nome/papel/instruções/modelo; atualização com `expected_revision`. Modelos vêm do catálogo existente; não há nomes/efforts inventados. A presença no catálogo não comprova acesso. A UI apresenta estado `CREATED` e oferece intenção estruturada `resume` antes da admissão de Dots; nunca simula `RUNNING`.
- Coordenação em formulário estruturado: criar equipe, delegar, conectar, handoff, pausar/retomar/cancelar projeto e reatribuir WorkItem. Prosa enviada como mensagem nunca é convertida pelo cliente em autorização.
- Conversas paginadas e atualização por `message_id`; busca no texto carregado, salto para histórico global existente, exportação Markdown de uma mensagem ou da conversa paginada completa. Markdown de apresentação escapa HTML e limita links a HTTP(S).
- Rascunhos de chat e payload/chave de envio incerto ficam no `sessionStorage` desta janela; recarga recupera a mesma intenção. Botão de consulta usa a mesma `request_key`. Mutações estruturadas com resposta pendente também têm painel de recuperação, sem replay automático.
- Estados `queued`, `dispatched`, `waiting_approval`, `uncertain` e detalhes Run/WorkItem/Operation/Receipt são projetados. Um envio despachado sem receipt não aparece como entrega concluída.
- `ProjectDocuments` de Tessela é inserido com callbacks estáveis e permanece montado/oculto ao alternar vistas. Dirty/CAS/conflitos/histórico/IndexedDB/Yjs/CodeMirror são responsabilidade do componente de Tessela; o shell também guarda mudanças de projeto/Space.
- CF15: cliente WebRTC real com permissão explícita de microfone, oferta SDP/ICE completa, resposta SDP central, áudio remoto, mute, polling/transcript, heartbeat somente com mídia conectada, stop/revoke e liberação imediata das tracks. Chamada incerta é consultada por `start_request_key`, sem reinício automático. Provedor ausente exibe o motivo real.
- Anexos opcionais: seleção real PNG/JPEG/PDF/texto/código e upload por chunks de 512 KiB; SHA-256 por chunk/arquivo, begin/complete/abort/status idempotentes, pausa e retomada, reseleção do mesmo arquivo após recarga e consulta antes de repetir resposta incerta. Limites do provider: quatro anexos, imagens 8 MiB e documentos 20 MiB. Mensagem envia apenas referências `att-*` confirmadas pelo armazenamento; isso não é recibo de upload no ChatGPT.
- Feedback visual posterior do usuário: quatro mascotes PNG originais (blue/mint/orange/purple) do commit OpenDots fixado. Identidade estável pelo `agent_id`/hash do componente original; usados em Home, cartões/nav de Dots, cabeçalho de chat e introdução da conversa. Imagens não modificadas; componente JSX adaptado, licença MIT/copyright e proveniência preservados. PNGs ausentes dos objetos Git locais foram adquiridos de URLs oficiais fixadas e vinculados aos blob IDs da árvore local.
- InputControl/viewer: painel contextual próprio com inventário e WorkItems reais, status de posse/epoch/TTL e grant separados, handoff human/agent/none com CAS, consulta da mesma intenção em falha, sessões Guacamole list/open/status pelo dispatch central, ticket scoped view/human, WebSocket/token apenas na memória. Teclado só no display focado; mouse condicionado aos canais autorizados e epoch/live/granted. Fechar/ocultar painel ou perder posse encerra transporte próprio, sem apagar sessão do SO remoto. Playback local usa o helper real de Forja, não envia input e recusa lacunas de gravação.
- Teclado/ARIA: nomes visíveis, foco, Radix nos diálogos, `role=log` no transcript, statuses em texto, skip link, Ctrl+K para histórico fora do Canvas, Escape para painel/rail, reduced motion e forced colors. Responsividade implementada em CSS, ainda sem QA.

## Arquivos próprios alterados/criados

- `sentra_canvas/desktop_ui/src/main.jsx`
- `sentra_canvas/desktop_ui/src/desktop.css`
- `sentra_canvas/desktop_ui/package.json`
- `sentra_canvas/desktop_ui/src/shell-app.jsx`
- `sentra_canvas/desktop_ui/src/shell-bridge.js`
- `sentra_canvas/desktop_ui/src/shell-conversation.jsx`
- `sentra_canvas/desktop_ui/src/shell-dialogs.jsx`
- `sentra_canvas/desktop_ui/src/shell-receipts.jsx`
- `sentra_canvas/desktop_ui/src/shell-voice.jsx`
- `sentra_canvas/desktop_ui/src/shell-markdown.jsx`
- `sentra_canvas/desktop_ui/src/shell-mascot.jsx`
- `sentra_canvas/desktop_ui/src/shell-attachments.jsx`
- `sentra_canvas/desktop_ui/src/shell-machines.jsx`
- `sentra_canvas/desktop_ui/src/assets/opendots/{blue,mint,orange,purple}.png`, `LICENSE`, `PROVENANCE.json`.
- `sentra_canvas/desktop_ui/src/assets/guacamole/LICENSE`, `NOTICE`, `PROVENANCE.json`.
- Este documento.

Arquivos `document-*`, `collaboration-*`, painéis existentes de outros donos, backend e gerados em `static/desktop-assets` não foram editados. Nenhum commit/push/reset/stash/recrutamento. Nenhuma skill ou MCP SENTRA.

## Contratos fechados

1. Cliente único `shellBridge(payload, options)` chama `POST /api/shell/bridge` através do cliente `api` que já guarda bearer privadamente. Allowlist local; IDs snake_case; `project_id`; `request_key` por mutação; owner/principal/grant nunca enviados pelo shell. `path` admitido exclusivamente nos oito reads de ProjectReview; servidor confere autorização/raiz. Documentos e demais ações continuam recusando path.
2. Servidor: `ControlPlaneService.shell_dispatch(owner, project_id, action, payload, request_key)` composto por `Canvas.shell_bridge(payload)`, owner derivado no servidor. Resposta `{ok:true,value,request_key?}`, erro HTTP `{error}`. O cliente retorna `value` para Tessela.
3. Home Nexo: `{project_id,space,spaces,dots,conversations,activity:{items,cursor,next_cursor},capabilities,run,teams,documents,voice,attachments?}`. Listas: `{items,page:{offset,limit,returned,total,next_offset},project_id}`. Eventos: `{items,cursor,next_cursor,has_more}` com `after_seq` e dedupe por `event_id`.
4. `ProjectDocuments({bridge,spaceId,projectId,documents,onRefresh,onError,onDirtyChange})`, named export de `document-panel.jsx`. `document_list/get/create/save/history/restore/delete/diff/export/session/session_close` pelo mesmo bridge. `onRefresh(result)` atualiza lista sem roundtrip redundante.
5. `coordinate.intent`: `create_team{name,coordinator_dot_id,worker_dot_ids}`, `delegate{team_id,dot_id,objective}`, `connect{source_dot_id,target_dot_id}`, `handoff{source_dot_id,target_dot_id,content}`, `pause|resume|cancel{kind}` controla Run do projeto; `reassign{work_item_id,dot_id}`.
6. Voz Brisa: `voice_start{offer_sdp,microphone_opt_in:true}` → `{call_id,answer_sdp,status,transcript}`; `voice_status{call_id|start_request_key}`; `voice_signal{kind:'heartbeat',call_id,...}`; `voice_stop/revoke{call_id,start_request_key,request_key}`. IDs/generation/escopo são conferidos no servidor. Disponibilidade por `home.voice`.
7. Anexos Brisa: `attachment_register{attachments:[{kind,name,data_url}]}` → `{attachments:[{attachment_id,kind,name,mime,bytes,sha256}],evidence}`. `message_send.attachments` é lista de IDs string, não objetos. `home.attachments.available/reason/max_attachments` permite habilitar o opcional. Sem callback configurado a UI mostra indisponibilidade.
8. Dependências adicionadas a pedido de Tessela: TipTap `3.31.3` (`react`, `starter-kit`, `extension-table`, `extension-link`, `markdown`); CodeMirror `state 6.5.2`, `view 6.38.8`, `commands 6.8.1`, `language 6.11.3`, `language-data 6.5.1`. Não instaladas nesta etapa.
9. ProjectReview pelo bridge: `project_file_list/preview/diff/pdf_text/pdf_visual` e `project_watch_start/poll/close`; allowlist de leitura admite `path` somente nessas ações. `document-project-files.jsx` de Tessela usa este cliente, sem endpoint paralelo.
10. Chunks Brisa: `attachment_upload_begin{kind,name,total_bytes,total_sha256}` → `{upload_id,chunk_bytes,chunks_expected,state}`; `attachment_upload_chunk{upload_id,index,data_url,chunk_sha256}` → `{received_chunks,received_bytes,complete,idempotent_replay}`; `attachment_upload_complete{upload_id}` → receipts; `attachment_upload_abort{upload_id}` → state aborted; `attachment_upload_status{upload_id|request_key}` somente consulta. Cada mutação tem request key própria, preservada no pending; complete verifica hash total; TTL 1800 s. Nenhum resend automático após resposta ambígua.
11. Forja/Codex: `machine_list` → `{machines,work_items}`; `input_status{machine_id,work_item_id?,capability_id?}`; `input_handoff{machine_id,holder,expected_epoch,ttl_seconds,work_item_id?,capability_id?,arguments?}`; `remote_viewer_open{machine_id,work_item_id,capability_id,session_id,control_mode,expected_epoch?}` → `{viewer_id,ws_url,input_epoch,input_channels,grant_status,...}`; `remote_viewer_close{viewer_id}`; `machine_execute{machine_id,work_item_id,capability_id,arguments}`; `machine_observe{target_operation_id}`. Scope contextual validado no root. Browser nunca fornece operation_id/resource_id/Grant/principal. Agent handoff recebe JSON com ação real anunciada, porque factory valida intenção antes de construir OperationRequest. Holder humano é contexto confiável no servidor, não flag no renderer.
12. Pins posteriores: dependências e overrides `@tiptap/extension-bubble-menu` e `@tiptap/extension-floating-menu` em `3.31.3`. Viewer `guacamole-common-js 1.5.0`, **repack padarom**, Apache-2.0; não alegado como clone Apache atual. SRI `sha512-zxztif3GGhKbg1RgOqwmqot8kXgv2HmHFg1EvWwd4q7UfEKvBcYZ0f+7G8HzvU+FUxF0Psqm9Kl5vCbgfrRgJg==`, source notices e provenance registrados. Tarball lido apenas como fonte/licença, sem instalar ou executar.

## Pendências reais e dependências

- Codex está compondo runtime, callbacks de voz/anexos e respectivas disponibilidades no Home. Endpoints/bearer/configuração do provedor permanecem exclusivamente no servidor. Sem provider configurado não existe áudio remoto funcional por inferência da UI.
- Solicitação enviada a Brisa: disponibilizar texto protegido do transcript (versão inicial retornava apenas `content_chars`), RTCIceServer URLs válidas, rebind com negociação/answer real, idempotência do registro de anexos e vínculo projeto/Space/conversa. A UI não anuncia rebind de mídia sem a negociação real.
- Limite HTTP shell 800.000 bytes preservado; transporte chunk já implementado nas fontes UI conforme contrato final Brisa/Nexo. Composição backend/root em andamento/entregue por seus donos, sem comprovação desta rodada. A seleção nunca promete upload Web confirmado sem receipt do adapter.
- O Codex materializou e abriu **apenas o preview visual especificamente autorizado**, PID 47408, state isolado `.tmp/integral-ui-preview/state/canvas`. Prisma não tocou processo, estado, lock ou bundle dessa preview. Mascotes, pins corrigidos, chunks e viewer novos permanecem em fontes, sem novo install/build nesta expansão. Instalação do novo pin Guacamole, lock/release/assets/notices e aceitação funcional ainda aguardam liberação/instrução posterior.
- Release deve incluir as licenças/proveniências dos assets OpenDots e viewer. Vitra/Codex foram avisados de que o materializador anterior só agregava notices de node_modules. Nenhum patch em scripts de shipping de outro dono foi feito por Prisma.
- Viewer depende de guacd/desktop, sessão ativa, WorkItem e Grant real, listener scoped/CSP e pacote pinado instalado. Ausências ficam explícitas; inventário/lease/retorno status local não provam desktop remoto vivo. Tickets readonly negam input; canais de ticket human vêm do `allowed_input` real. Sem conexão automática na montagem do painel ou replay automático depois de falha.
- Não há evidência desta rodada de microfone/provider real, conta Web, WebView2, handoff, CAS/Yjs multiusuário, reconexão ou entrega externa. Isso permanece para validação liberada pelo Codex.

## Validação futura — não executada

Após TODAS as implementações integradas e liberação explícita: resolver lock e materializar bundle; executar checks JS/React e suites adequadas; abrir shell com bearer real; conferir migração idempotente do projeto, navegação reiniciada, criação de Dot após resume, mesma identidade no chat/Canvas/CLI, conversas >50 mensagens, receipts/approval/uncertainty/reload; conflitos/drafts/documentos/colaboração; microfone opt-in, provider SDP real, áudio/stop/revoke/TTL; chunks fora de ordem/replay/hash/expiração/retomada e recibo de upload Web; viewer real readonly/control, mudança de epoch/grant, pacote Guacamole/handshake, ticket single-use/close/expiração e playback sem inputs; teclado/ARIA/DPI/responsividade/fidelidade com mascotes CopilotKit/OpenDots; PTY vivo entre vistas e inspector contextual com dados reais.

Não foram executados testes, build, lint, benchmark, auditoria ou QA nesta entrega. Comunicação de contratos e entrega por `maestri ask Codex`, `Nexo`, `Tessela`, `Brisa` e `Meridiano`, usando a skill de comunicação `C:/Users/vitor/.agents/skills/maestri/SKILL.md`.
