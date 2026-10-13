# Requisitos integrais ? Meridiano

> Ownership ATUAL: Cobalto=Brisa/Rastro; Prisma=Pacto; Lume=Pulso; Forja=Selo; Tessela=Vitra. REDISTRIBUICAO_CODEX.md supera transferencia anterior. Autoria historica preservada; root/Nexo e demais donos mantidos. Nenhuma homologacao.


Data: 11/10/2026. Base informada: `3639a2e296428db8e3bb0839fac87d9237ec8592` em origin/main. Nenhum teste/build/lint/benchmark/QA executado. Nada homologado.

## Escopo e regra de fechamento

Consolidacao integral da nota (465 linhas), dos tres levantamentos (OpenDots, Chat On Steroids, ecossistema 37) e documentos referenciados. A reavaliacao dos 37 e incluida integralmente, nao apenas a auditoria inicial. Prioridade/adiamento historicos nao reduzem o escopo atual. Opcionais precisam implementacao real configuravel e indisponibilidade explicita; deny-only nao fecha capacidade. Excecoes inseguras rejeitadas nos estudos (cookies, evasao, segundo Control Plane, classificacao shell como grant, autoridade renderer) sao preservadas como restricoes.

Codigo concreto + composicao produto/Control Plane + evidencia contemporanea futura fecham cada requisito. Contrato, fixture, ACK, clone, modulo ou teste historico nao fecham requisito. Efeitos pertencem exclusivamente a ControlPlaneService/Run/WorkItem/Operation/Grant.

## Entrega Meridiano e comunicacao

- Dono dos requisitos, coverage e contratos; nenhum codigo editado.
- `contracts.md` registra assinaturas reais lidas/recebidas, propostas explicitamente separadas e dependencias.
- `coverage.json` preserva fontes completas/hashes/linhas, catalogo, cada linha nao vazia das fontes, snapshots de declaracoes, matrizes historicas e lacunas atuais.
- `tasks/Nome.md` entrega expansoes aos onze donos autorizadas pelo usuario; OpenCode deve ser relancado pelo principal no mesmo terminal com --file, sem prompt simples ao PowerShell.
- Finalizacao desta consolidacao nao libera validacao do produto nem declara implementacao integral concluida.

## Inventario de fontes

| ID | Fonte | Linhas | SHA-256 |
|---|---|---:|---|
| NOTE | `maestri://note/todos-os-projetos-ja-estao-clo` | 465 | `351d9e56ed380be8a6009b4c420f75bbacdabff28b69205f6c41f3e1db57ee48` |
| ORDER | `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md` | 58 | `f325ef23e27d206668d406191bf7ad51642117c54fa35808e7d884bd23f1f732` |
| SHELL | `docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md` | 43 | `fab156fcd74a618a2ca72a9a62acb59ecc5879901fb134dce7c17849af53a3df` |
| OD | `C:/Users/vitor/OneDrive/Desktop/SENTRA_RESEARCH_OPENDOTS/SENTRA_OPEN_DOTS_RESEARCH.md` | 793 | `855d5a33af043edcc4c1cd97dc74e1894279186afa2b9d2af2653fd38e2678e2` |
| ECO | `docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md` | 703 | `f55bb2896c2092f18327d5f28c7d2f4197ab016408c3a80f8f0ff6bc41411552` |
| REE | `docs/SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md` | 614 | `7e29aba02a7b698875f551fe51dd1d15c7ab1e873cfd37075bc752e529d29964` |
| COS | `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md` | 185 | `e2286dd00c9eade7749747c3135b844e2bcfbaf8d04813dc90e5481f7cf4cf26` |
| REUSE | `docs/SENTRA_THIRD_PARTY_REUSE_2026-10-08.md` | 260 | `f01759459b433eed0fc62c9bcf8a8f1f93ec8eb3156070dd4417043d6689cd57` |
| GATE | `docs/SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md` | 81 | `506ae35b3fac8dd4517d1e9ff7c003ef24ff731bf698a8b76035653c7137bca9` |
| CHECKPOINT | `docs/SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md` | 185 | `b13303c90d5577ebe24e0933573b60d4893ef2cc71b73c641d08320c100a591f` |

Nota exportada de CLI normalizada; hash identifica esta exportacao, nao serializacao interna da nota. Documentos locais usam hash dos bytes originais.

## Catalogo rastreavel

| Familia | Quantidade extraida | Estado |
|---|---:|---|
| OpenDots_55 | 55 | Sem homologacao; validacao adiada |
| OpenDots_GA_crosswalk_34 | 34 | Sem homologacao; validacao adiada |
| CoS_34 | 34 | Sem homologacao; validacao adiada |
| Ecosystem_initial_37 | 37 | Sem homologacao; validacao adiada |
| Ecosystem_additional_37 | 37 | Sem homologacao; validacao adiada |
| Cross_domain_gaps_18 | 18 | Sem homologacao; validacao adiada |
| Connected_note_clauses | 234 | Sem homologacao; validacao adiada |

55 achados CF22/AF15/FF18; 34 frentes CoS G13/A21; crosswalk OpenDots G/A e rastreio adicional, nao soma de funcionalidades distintas. Os 37 projetos possuem requisito inicial e ampliacao individual com limites/evidencia/aceite preservados. Contagens sao registro de extracao documental, nao resultados de teste.

## Lacunas atuais e expansoes

| ID | Donos | Requisito/contrato ainda aberto | Base |
|---|---|---|---|
| GAP-01 | Pacto | QuickJS/A08 real missing: sentra_code_mode/__init__.py: QuickJSWasmAdmission.execute raises CodeModeDisabled; Pacto.md reports deny-only Dispatcher. User rejected deny-only and will reopen Pacto. | code_read+owner_report+user_directive |
| GAP-02 | Nexo | Postgres native migrations multiuser missing: control_store.py only creates SQLite and raises UnsupportedControlPlaneBackend for other backends; interface and ATTACH/BEGIN IMMEDIATE consumers remain SQLite-specific. | code_read |
| GAP-03 | Pulso | External Temporal and LangGraph adapters require implementation: Read workflow_worker.py / workflow_bridge.py local worker and SQLite checkpoint integration; scoped text search found no temporalio/langgraph runtime integration. Need real SDK/worker bindings, not local semantic analogy. | bounded_static_search; not repository-wide absence proof |
| GAP-04 | Brisa, Prisma, Codex | Voice WebRTC provider and composition open: Prisma reports real client opt-in work and proposed offer/answer actions; final provider/capability/signaling/session/receipt contract still needed. | received_user_contract; implementation in progress |
| GAP-05 | Lume, Pulso | Slack/Telegram/WhatsApp optional connectors missing confirmation: Scoped product source search found no selected channel adapters; owner must implement authenticated inbound/outbound receipts, lifecycle and distribution. | bounded_static_search |
| GAP-06 | Selo, Pacto | Reviewed learning + Langfuse datasets/prompts/evals open: Scoped product source search found no Langfuse/learning runtime; OTel pipeline is different. Must implement reviewed suggestion and dataset/prompt/trace linkage with central QualityGate. | bounded_static_search |
| GAP-07 | Tessela, Nexo, Codex | Document-scoped collaboration integration open: CollaborationAuthority.issue currently workspace-scoped; new shell requires project/space/document scoping, CAS/receipt/history and document allowlist. Prisma reports ProjectDocuments draft guards; no QA. | code_read+received_contract |
| GAP-08 | Nexo, Codex, Prisma, Vitra | Canonical shell HTTP/Canvas composition open: Received ControlPlaneService.shell_dispatch(owner,project_id,action,payload,request_key) and Canvas.shell_bridge names. Final Canvas signature/action schemas/auth/error mapping need concrete composition evidence. | received_user_contract |
| GAP-09 | Forja, Prisma, Codex | Guacamole viewer/playback/stream product composition open: Forja reports existing viewer/tunnel provider needing Prisma/Codex mount. Playback must never emit recorded inputs; view/control/channel capabilities remain separate. | received_user_contract |
| GAP-10 | Forja, Nexo | InputLease + hybrid observation + Playwright recovery + AT-SPI scheduled: integral.configure_executor read and Forja signature received; InputLease CAS/epoch/TTL/handoff, hybrid screenshot/UIA, persisted browser recovery and SDK Computer Use are future additions, not homologated. | code_read+received_user_contract |
| GAP-11 | Vitra, Nexo, Selo | Distribution/recovery beyond shell helpers open: Vitra report supplies Space journal/staged manifests/CLI changes; complete multi-store DB+artifact+key backup/restore, native provider packages, signatures/SBOM/notices and clean installation acceptance remain required. | owner_report+study_requirements |
| GAP-12 | Brisa, Rastro, Lume, Forja, Pulso, Selo, Vitra, Codex | Installed account and external runtimes require final evidence: No requirement may be closed by code existence, fixture, metadata/ACK or historical tests. Actual authorized account/model/effort/plugin/schema/approval/attachment/usage and optional services/VMs/peers require contemporary evidence after final release of validation. | user_validation_gate |

## Dependencias e contratos

C01 shell; C02 coordenacao/continuidade; C03 documentos/CRDT; C04 maquinas/efeitos; C05 protocolos/canais; C06 workflows/agenda; C07 voz; C08 plugins/Skills/Code Mode; C09 identidade/audit/learning/eval; C10 Postgres/distribuicao. Assinaturas e schemas concretos/pendentes em [contracts.md](contracts.md).

Nexo?Codex?Prisma/Vitra para shell; Tessela?Codex/Prisma para documento; Brisa?Rastro?Nexo/Codex/Prisma para Web/voz; Lume?Pulso?Forja/Codex para canais/runtime; Selo?Pacto/Codex para learning/evals/autoridade; todos?Vitra para migracoes/pacotes/proveniencia. Nenhum dono edita composicao de outro.

## Requisitos por familia (texto original preservado)

### OpenDots_55

#### OD-CF01 ? Composição de servidor e provider; aplicação utilizável em partes sem provider

Donos: Codex, Vitra; composicao: Codex. Fonte OD L142?142. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF01 | Composição de servidor e provider; aplicação utilizável em partes sem provider | src/server/index.ts; src/server/platform.ts | V | Aproveitar degradação explícita; média; P1 |

#### OD-CF02 ? Spaces, organização de Dots e contexto de workspace

Donos: Nexo, Prisma; composicao: Codex. Fonte OD L143?143. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF02 | Spaces, organização de Dots e contexto de workspace | src/server/workspace.ts; src/client/App.tsx | V/recorte | Adaptar organização visual ao Canvas; alta; P1 |

#### OD-CF03 ? Páginas hierárquicas, revisão, versões e exclusão

Donos: Tessela; composicao: Codex. Fonte OD L144?144. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF03 | Páginas hierárquicas, revisão, versões e exclusão | src/server/pages.ts; src/server/page-service.ts | V | Adaptar revisão com conflito; alta; P1 |

#### OD-CF04 ? Editor Markdown/rich text, listas, tabelas e comandos

Donos: Tessela, Prisma; composicao: Codex. Fonte OD L145?145. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF04 | Editor Markdown/rich text, listas, tabelas e comandos | src/client/editor/RichEditor.tsx | V | Aproveitar UX; não supre editor de código/PDF; alta; P1 |

#### OD-CF05 ? Autosave, erro/conflito, preservação de draft em memória

Donos: Tessela, Prisma; composicao: Codex. Fonte OD L146?146. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF05 | Autosave, erro/conflito, preservação de draft em memória | src/client/editor/autosave.ts | V | Adaptar estados e recuperação; alta; P1 |

#### OD-CF06 ? Fallback de source, export Markdown, atalhos e aviso de saída

Donos: Tessela, Rastro; composicao: Codex. Fonte OD L147?147. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF06 | Fallback de source, export Markdown, atalhos e aviso de saída | src/client/PageDocument.tsx | V | Adaptar ao project_review; alta; P1 |

#### OD-CF07 ? Agente com contexto, tools e streaming AG-UI

Donos: Nexo, Lume, Prisma; composicao: Codex. Fonte OD L148?148. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF07 | Agente com contexto, tools e streaming AG-UI | src/server/dot-agent.ts | V | Usar apresentação do progresso; baixa para importar executor; P2 |

#### OD-CF08 ? Pesquisa Web via Parallel MCP, browser ou modo desabilitado

Donos: Forja, Lume; composicao: Codex. Fonte OD L149?149. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF08 | Pesquisa Web via Parallel MCP, browser ou modo desabilitado | src/server/parallel.ts | V | Adaptar provenance e falha explícita; média; P2 |

#### OD-CF09 ? Browser read-only separado e transporte com limites

Donos: Forja, Brisa; composicao: Codex. Fonte OD L150?150. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF09 | Browser read-only separado e transporte com limites | src/browser/index.ts; src/browser/transport.ts | V parcial | Estudar limites de consulta; não equivale à extensão MV3; P0 |

#### OD-CF10 ? Conexões MCP HTTP, catálogo de ferramentas e namespaces

Donos: Pacto, Lume; composicao: Codex. Fonte OD L151?151. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF10 | Conexões MCP HTTP, catálogo de ferramentas e namespaces | src/server/connections.ts; docs/CONNECTIONS.md | V/D | Adaptar descoberta através de MCPB existente; média; P1 |

#### OD-CF11 ? Aprovação vinculada a thread, tool e argumentos persistidos

Donos: Pacto, Nexo; composicao: Codex. Fonte OD L152?152. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF11 | Aprovação vinculada a thread, tool e argumentos persistidos | src/server/connection-routes.ts; src/server/connection-store.ts | V | Estudar recibos; endurecer vínculo Operation/Grant; P0 |

#### OD-CF12 ? Computador por Dot com browser/files/shell e auditoria

Donos: Forja; composicao: Codex. Fonte OD L153?153. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF12 | Computador por Dot com browser/files/shell e auditoria | src/server/computer-service.ts | V | Referência de status/recibos; executor novo somente futuro; P2 |

#### OD-CF13 ? Deployment OpenBot isolado, pin upstream e credenciais por Dot

Donos: Forja, Vitra; composicao: Codex. Fonte OD L154?154. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF13 | Deployment OpenBot isolado, pin upstream e credenciais por Dot | deployment/computers/README.md; LICENSE.openbot | D/V licença | Avaliar custo e pin; não instalar; P2 |

#### OD-CF14 ? Tarefas persistidas, claim/lease e recuperação

Donos: Pulso, Nexo; composicao: Codex. Fonte OD L155?155. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF14 | Tarefas persistidas, claim/lease e recuperação | src/server/store.ts; src/server/runner.ts | V | Adaptar semântica a DurableRunService; média; P1 |

#### OD-CF15 ? Chamadas de voz WebRTC, transcript e ferramentas delimitadas

Donos: Brisa, Prisma, Codex; composicao: Codex. Fonte OD L156?156. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF15 | Chamadas de voz WebRTC, transcript e ferramentas delimitadas | src/server/voice.ts | V | Adiar após autorização e receipts; média; P2 |

#### OD-CF16 ? Slack via Channels, allowlist de workspace/usuário

Donos: Lume, Pulso; composicao: Codex. Fonte OD L157?157. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF16 | Slack via Channels, allowlist de workspace/usuário | src/server/slack-channel.ts | V | Canal opcional futuro; baixa necessidade atual; P2 |

#### OD-CF17 ? Automatic Learning/containers por Dot

Donos: Selo, Pacto; composicao: Codex. Fonte OD L158?158. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF17 | Automatic Learning/containers por Dot | src/server/learning.ts | V chamada SDK/D backend | Não importar publicação automática de Skills; P2 |

#### OD-CF18 ? Escopo agent/thread separado do principal proprietário

Donos: Nexo, Brisa; composicao: Codex. Fonte OD L159?159. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF18 | Escopo agent/thread separado do principal proprietário | src/server/runtime-scope.ts; src/server/platform.ts | V | Aproveitar isolamento lógico; insuficiente para prova Web; P0 |

#### OD-CF19 ? Guardas HTTP, CSP e restrição de exposição

Donos: Codex, Vitra; composicao: Codex. Fonte OD L160?160. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF19 | Guardas HTTP, CSP e restrição de exposição | src/server/app.ts; src/server/index.ts | V | Comparar com auth local existente; média; P0 |

#### OD-CF20 ? Tema escuro, biblioteca, sidebar e feedback de polling

Donos: Prisma; composicao: Codex. Fonte OD L161?161. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF20 | Tema escuro, biblioteca, sidebar e feedback de polling | src/client/App.tsx; tests/dark-theme.test.ts; tests/library.test.ts | V recorte/inventário | Referência minimalista; validar ARIA/DPI no SENTRA; P1 |

#### OD-CF21 ? CI de testes, formato, lint, tipos e build

Donos: Vitra, Codex; composicao: Codex. Fonte OD L162?162. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF21 | CI de testes, formato, lint, tipos e build | .github/workflows/ci.yml | V configuração | Referência de gates, sem alegar execução; P1 |

#### OD-CF22 ? Telemetria SDK/setup e opções de opt-out

Donos: Selo, Vitra; composicao: Codex. Fonte OD L163?163. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| CF22 | Telemetria SDK/setup e opções de opt-out | docs/SETUP.md; package.json; arquivos de telemetry inventariados | D/parcial | Consentimento e diagnóstico redigido antes de publicar; P0 |

#### OD-AF01 ? REST e bot compartilham backend

Donos: Lume, Pulso; composicao: Codex. Fonte OD L212?212. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF01 | REST e bot compartilham backend | backend/app/main.py; routers/router.py | V | Ideia de canal único; não importar backend; média; P2 |

#### OD-AF02 ? Identidade guest/Telegram no navegador

Donos: Nexo, Brisa; composicao: Codex. Fonte OD L213?213. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF02 | Identidade guest/Telegram no navegador | frontend/app/page.tsx; frontend/lib/api.ts | V | Rejeitar localStorage como autoridade; baixa; P0 |

#### OD-AF03 ? Provisionamento, stop/resume e diagnóstico de sandbox

Donos: Forja; composicao: Codex. Fonte OD L214?214. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF03 | Provisionamento, stop/resume e diagnóstico de sandbox | backend/app/routers/sandbox.py | V | Só referência de estados; ações exigem Grant; baixa; P2 |

#### OD-AF04 ? Login Claude OAuth e GitHub device flow

Donos: Brisa, Vitra; composicao: Codex. Fonte OD L215?215. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF04 | Login Claude OAuth e GitHub device flow | routers/sandbox.py; README.md | V parcial/D | Não confundir com prova da conta ChatGPT; P0 |

#### OD-AF05 ? Credenciais cifradas com rotação MultiFernet

Donos: Selo, Vitra; composicao: Codex. Fonte OD L216?216. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF05 | Credenciais cifradas com rotação MultiFernet | backend/app/core/crypto.py; core/config.py | V | Avaliar fluxo, manter vault próprio SENTRA; média; P0 |

#### OD-AF06 ? Tarefa CLI, continuação de session e resultado completo

Donos: Rastro, Lume; composicao: Codex. Fonte OD L217?217. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF06 | Tarefa CLI, continuação de session e resultado completo | services/task_execution_service.py; routers/task.py | V | Adaptar semântica de resume/resultados; média; P1 |

#### OD-AF07 ? Claim e recuperação de queued/starting

Donos: Pulso, Nexo; composicao: Codex. Fonte OD L218?218. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF07 | Claim e recuperação de queued/starting | services/task_execution_service.py | V | Diferenciar falha de efeito incerto; P0 |

#### OD-AF08 ? Regras allow/deny/ask e escopo

Donos: Pacto, Selo; composicao: Codex. Fonte OD L219?219. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF08 | Regras allow/deny/ask e escopo | services/permission_service.py | V | UI de consentimento útil; política não é Grant; P0 |

#### OD-AF09 ? Aprovação inline, resposta e deadline

Donos: Pacto, Prisma; composicao: Codex. Fonte OD L220?220. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF09 | Aprovação inline, resposta e deadline | services/permission_ask_service.py; routers/permission.py | V | Adaptar apresentação, rejeitar owner gate ausente; P0 |

#### OD-AF10 ? Classificação de git em comandos shell

Donos: Forja, Pacto; composicao: Codex. Fonte OD L221?221. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF10 | Classificação de git em comandos shell | services/github_classifier.py | V | Apenas rótulo informativo; rejeitar autorização; P0 |

#### OD-AF11 ? Cron/timezone, ocorrência única e não sobreposição

Donos: Pulso; composicao: Codex. Fonte OD L222?222. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF11 | Cron/timezone, ocorrência única e não sobreposição | services/schedule_service.py | V | Ideias para Goal/WorkItem existentes; média/alta; P1 |

#### OD-AF12 ? Resultado agendado em Telegram, pausa por falhas

Donos: Pulso, Lume; composicao: Codex. Fonte OD L223?223. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF12 | Resultado agendado em Telegram, pausa por falhas | schedule_service.py; notification_service.py | V | Adaptar política de pausa; entrega precisa de receipt; P1 |

#### OD-AF13 ? Histórico simples de tasks, polling e continuação

Donos: Rastro, Prisma; composicao: Codex. Fonte OD L224?224. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF13 | Histórico simples de tasks, polling e continuação | frontend/app/page.tsx; frontend/lib/api.ts | V | Referência de interação; não é histórico Web completo; P1 |

#### OD-AF14 ? Ambiente de desenvolvimento, Postgres e migrações

Donos: Nexo, Vitra; composicao: Codex. Fonte OD L225?225. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF14 | Ambiente de desenvolvimento, Postgres e migrações | README.md; backend/README.md; scripts/dev.sh inventariado | D/inventário | Descrever somente; não equivale a Setup/Doctor; P2 |

#### OD-AF15 ? Testes de permissões, agenda, recuperação e bot

Donos: Codex, Vitra; composicao: Codex. Fonte OD L226?226. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| AF15 | Testes de permissões, agenda, recuperação e bot | backend/tests/ — 11 módulos inventariados | V inventário | Melhorar disciplina de evidência; nenhuma suite executada |

#### OD-FF01 ? Host API e projeções de estado

Donos: Codex, Nexo; composicao: Codex. Fonte OD L286?286. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF01 | Host API e projeções de estado | apps/api/src/server.ts | V público | Adaptar contratos/receipts; não criar outro control plane; P1 |

#### OD-FF02 ? CLI e SDK de acesso ao host

Donos: Vitra, Lume; composicao: Codex. Fonte OD L287?287. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF02 | CLI e SDK de acesso ao host | apps/cli; packages/sdk; docs/guide.md | D | Exigir adaptação ao contrato CLI SENTRA; P2 |

#### OD-FF03 ? VM por Dot e runtime separado da imagem

Donos: Forja, Vitra; composicao: Codex. Fonte OD L288?288. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF03 | VM por Dot e runtime separado da imagem | apps/vm-manager/src/qemu-args.ts; docs/architecture.md | V/D | Executor opcional de alto custo; P2 |

#### OD-FF04 ? Daemon privilegiado e contas guest separadas

Donos: Forja, Selo; composicao: Codex. Fonte OD L289?289. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF04 | Daemon privilegiado e contas guest separadas | guest/dot-agentd; docs/architecture.md | D, código incompleto | Exige auditoria própria, não presumir isolamento absoluto; P0 |

#### OD-FF05 ? Política única de tools e fallback restritivo

Donos: Pacto; composicao: Codex. Fonte OD L290?290. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF05 | Política única de tools e fallback restritivo | invisible_engine_dots/nanobot/dots/permissions.py | V público | Referência para exposição mínima; média/alta; P1 |

#### OD-FF06 ? Approval durável e argumentos canônicos

Donos: Pacto, Nexo; composicao: Codex. Fonte OD L291?291. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF06 | Approval durável e argumentos canônicos | invisible_engine_dots/nanobot/dots/gate.py | V público | Adaptar vínculo à Operation/Grant; alta conceitual; P0 |

#### OD-FF07 ? Transcript + outbox na mesma transação

Donos: Rastro, Nexo; composicao: Codex. Fonte OD L292?292. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF07 | Transcript + outbox na mesma transação | invisible_engine_dots/nanobot/dots/transcript_outbox.py | V público | Adaptar contrato de receipts; alta conceitual; P0 |

#### OD-FF08 ? Persistência host, eventos e scheduler

Donos: Nexo, Pulso; composicao: Codex. Fonte OD L293?293. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF08 | Persistência host, eventos e scheduler | packages/database; apps/scheduler; docs/architecture.md | D | Investigar protocolo; não importar DB autoritativo; P0 |

#### OD-FF09 ? Tools de arquivo, execução e browser delimitados

Donos: Forja; composicao: Codex. Fonte OD L294?294. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF09 | Tools de arquivo, execução e browser delimitados | permissions.py | V público | Compatibilizar capacidade e Grant exatos; P1 |

#### OD-FF10 ? Memória e Skills no guest

Donos: Selo, Pacto; composicao: Codex. Fonte OD L295?295. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF10 | Memória e Skills no guest | invisible_engine_dots/UPSTREAM.md; docs/guide.md | D | Não equiparar a SkillPack pinado/revisado; P2 |

#### OD-FF11 ? Browser persistente por identidade

Donos: Forja, Brisa; composicao: Codex. Fonte OD L296?296. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF11 | Browser persistente por identidade | SECURITY.md; docs/guide.md | D | Privacidade e limpeza explícitas; não prova conta Web SENTRA; P0 |

#### OD-FF12 ? Cron e retomada de automações

Donos: Pulso; composicao: Codex. Fonte OD L297?297. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF12 | Cron e retomada de automações | docs/guide.md; arquitetura em recorte | D | Comparar política com Goal/WorkItem; P1 |

#### OD-FF13 ? Telegram e WhatsApp opcional no host

Donos: Lume, Pulso; composicao: Codex. Fonte OD L298?298. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF13 | Telegram e WhatsApp opcional no host | docs/guide.md; THIRD_PARTY_NOTICES.md | D | Adiar; canais e licença ampliam custo; P2 |

#### OD-FF14 ? HTTP assíncrono, cancelamento e SSE

Donos: Codex, Lume; composicao: Codex. Fonte OD L299?299. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF14 | HTTP assíncrono, cancelamento e SSE | apps/api/src/server.ts | V público | Adaptar estados claros de aceitação/conclusão; P1 |

#### OD-FF15 ? UI, tool labels e aprovação

Donos: Prisma; composicao: Codex. Fonte OD L300?300. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF15 | UI, tool labels e aprovação | THIRD_PARTY_NOTICES.md; apps/web/package.json | D proveniência/V manifesto | Selecionar componente e licença por arquivo; P1 |

#### OD-FF16 ? Golden image, runtime e atualização manual

Donos: Vitra, Forja; composicao: Codex. Fonte OD L301?301. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF16 | Golden image, runtime e atualização manual | docs/guide.md | D | Não atende release Windows SENTRA sozinho; P2 |

#### OD-FF17 ? Gates CI multi-stack e execução opt-in

Donos: Vitra, Codex; composicao: Codex. Fonte OD L302?302. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF17 | Gates CI multi-stack e execução opt-in | .github/workflows/tests.yml | V configuração | Referência de gate; não prova VM Windows instalada; P1 |

#### OD-FF18 ? Hard fork e inventário de terceiros

Donos: Vitra, Selo; composicao: Codex. Fonte OD L303?303. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| FF18 | Hard fork e inventário de terceiros | invisible_engine_dots/UPSTREAM.md; THIRD_PARTY_NOTICES.md | V documental | Orçamento de manutenção/legal antes de copiar; P0 |

### CoS_34

#### COS-G01 ? **MCPB/plugin lifecycle:** `src/main/plugins/installer.ts`, `manager.ts`, `oauth.ts`, `exposure.ts`

Donos: Pacto, Vitra, Codex; composicao: Codex. Fonte COS L24?24. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P0** | **MCPB/plugin lifecycle:** `src/main/plugins/installer.ts`, `manager.ts`, `oauth.ts`, `exposure.ts` | SENTRA possui `sentra_interop/mcp.py`, `tool_catalog.py`, `sentra_mcp/tool_policy.py`, onboarding; falta evidência de instalação MCPB integrada ao Canvas | Adaptar parsing MCPB seguro (arquivo, path, limite, manifest, source), stdio/HTTP/OAuth, health/restart, inventário e revogação. Encaixar no catálogo autoritativo e no instalador/Quick Start. `pluginExposure()` (62 linhas) é candidata específica a porte para checagem de conflitos e limites, sem substituir policy | Duas ferramentas homônimas **não** colidem nem redirecionam uma chamada; grant obrigatório por capability; sem segredos em logs; uninstall idempotente |

#### COS-G02 ? **Modelo real da conta:** `src/main/chat-models.ts`, `src/renderer/chat-models.ts`, `test/model-picker-state.test.ts`

Donos: Brisa, Rastro, Prisma, Vitra; composicao: Codex. Fonte COS L25?25. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P0** | **Modelo real da conta:** `src/main/chat-models.ts`, `src/renderer/chat-models.ts`, `test/model-picker-state.test.ts` | SENTRA tem `/model` numerado em `sentra_cli/repl.py` e `sentra_canvas/service.py::model_catalog`; pode depender da prontidão do Gateway | Adaptar estados `unknown/pending/ready/unavailable`, observação vinculada a nonce, modelo/effort efetivamente oferecidos e escolha **Automatic** para conta sem picker. Exibir observação de conta/modelo no Canvas e CLI, sem inferir direitos de GPT-6 High por nome | Não escolher modelo não anunciado; conta Free/Go sem picker não congela 120 s; cancelamento e troca durante geração não alteram sessão ativa; seleção reconciliada |

#### COS-G03 ? **Compact & Resume transacional:** `src/main/session/continuation.ts`, `handoff.ts`, `resume-gate.ts`, `test/continuation.test.ts`

Donos: Rastro, Nexo; composicao: Codex. Fonte COS L26?26. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P0** | **Compact & Resume transacional:** `src/main/session/continuation.ts`, `handoff.ts`, `resume-gate.ts`, `test/continuation.test.ts` | CLI tem `/resume` e `/continue`, runtime guarda work/contexto; não há prova da troca **de uma conversa Web A para B mantendo o mesmo agente/Run/WorkItem** | Portar **o protocolo de fases**, não o módulo 1.807 linhas: open → summary → exclusive claim → preflight → durable commit → publish/abort; rebind de conversation_id dentro do mesmo agente, mantendo leases, grants e proveniência, sem reprodução de efeitos incertos | Crash/reload em cada fase, dois chats concorrendo ao mesmo handoff, abort preserva origem; workers filhos não perdem contexto ou execução |

#### COS-G04 ? **Outbox e prova de entrega:** `src/main/session/input.ts`, `recorder.ts`, `store.ts`, `test/input-delivery-integration.test.ts`

Donos: Rastro, Brisa; composicao: Codex. Fonte COS L27?27. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P0** | **Outbox e prova de entrega:** `src/main/session/input.ts`, `recorder.ts`, `store.ts`, `test/input-delivery-integration.test.ts` | SENTRA já tem journals SQLite/outbox de Tasks/Operations, mas entrega de **mensagem ao ChatGPT Web** não deve ser confundida com sucesso do WorkItem | Adaptar estados `not_sent/pending/unconfirmed/sent`, generation/receipt, um envio por chat; correlacionar BrowserRequest/Conversation com Control Plane usando identidade local e revisão, não DOM sozinho | Perda de resposta HTTP, reload, reenvio tardio e interrupção não duplicam mensagens; `unconfirmed` exige reconciliação |

#### COS-G05 ? **Workers, equipes e Goal/Loop:** `src/main/agents.ts`, `goal.ts`, `session/request-plans.ts`

Donos: Pulso, Nexo; composicao: Codex. Fonte COS L28?28. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P1** | **Workers, equipes e Goal/Loop:** `src/main/agents.ts`, `goal.ts`, `session/request-plans.ts` | SENTRA possui agentes/filhos e `sentra_canvas/task_runtime.py` vinculado a governance; tem planos revisionados `sentra_runtime/plan_history.py` | Reaproveitar tratamento de fila, worker health, retorno de contexto, limites e decisões de conclusão *após* recibos. Opcional `Goal/Loop` com modelo autorizado já configurado; nunca ligar um provedor pago/externo por padrão | Stop/cancel, duplicidade e progresso vinculados a Run; sem execução infinita, sem burlar quota ou refusals |

#### COS-G06 ? **Ferramentas de terminal persistente:** `src/main/codex/unified-exec.ts`, `head-tail-buffer.ts`, `truncate.ts`, `test/exec*.test.ts`

Donos: Pulso; composicao: Codex. Fonte COS L29?29. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P1** | **Ferramentas de terminal persistente:** `src/main/codex/unified-exec.ts`, `head-tail-buffer.ts`, `truncate.ts`, `test/exec*.test.ts` | SENTRA já possui ConPTY, xterm, CLI e executor/registry | Portar semântica testável de `exec_command/write_stdin`, streaming drenável, head/tail com limite, árvore de processos e output por operation ID, **sobre o terminal do SENTRA**, não novo shell paralelo | Fencing no ponto de efeito; no-repeat; cancelamento mata apenas subprocesso autorizado; saída truncada marcada; Windows quoting |

#### COS-G07 ? **Skills versionadas:** `src/main/skill-library.ts`, `skills.ts`, `skill-metadata.ts`, `skill-package.ts`, `test/skills.test.ts`

Donos: Pacto; composicao: Codex. Fonte COS L30?30. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P1** | **Skills versionadas:** `src/main/skill-library.ts`, `skills.ts`, `skill-metadata.ts`, `skill-package.ts`, `test/skills.test.ts` | SENTRA dispõe de ferramentas/provedores e contexto, mas skill registry versionado requer auditoria específica | Catálogo de `SKILL.md` com importação controlada, checksum/revisão, leitura sob escopo, progressive disclosure, ativação explícita e vínculo ao WorkItem | Uma skill nunca acrescenta grant, cwd fora de workspace nem acesso a secrets; revisão imutável por operação |

#### COS-G08 ? **API local de observação e ações opt-in:** `src/main/control-api.ts`, `control-reads.ts`, `control-actions.ts`

Donos: Pacto, Codex; composicao: Codex. Fonte COS L31?31. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P1** | **API local de observação e ações opt-in:** `src/main/control-api.ts`, `control-reads.ts`, `control-actions.ts` | SENTRA já tem broker/HTTP Canvas e Control Plane | Aproveitar dois níveis de consentimento (leitura e envio de mensagens separadamente), endpoint/token local, host/origin guards, limite de corpo, rate/deadline, outbox e paginação; sem segunda autoridade | Desligado ou leitura por padrão; ações 403 sem segundo consentimento; não vazar URLs MCP, tokens e path de segredo |

#### COS-G09 ? **Setup/diagnósticos e reparo:** `src/main/connection.ts`, `tunnel/health.ts`, `setup-profiles.ts`, `docs/setup.md`

Donos: Vitra; composicao: Codex. Fonte COS L32?32. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P1** | **Setup/diagnósticos e reparo:** `src/main/connection.ts`, `tunnel/health.ts`, `setup-profiles.ts`, `docs/setup.md` | SENTRA possui Quick Start, Secure MCP Tunnel, app/plugin manual, Setup/MSI e Doctor | Portar UX de estado `local MCP ready / tunnel healthy / ChatGPT app authorized / extension paired / model verified`, repair por etapa, instruções de reload da extensão e refresh do app MCP após update | Setup não afirma app instalado em conta sem prova externa; telas mostram falhas e ações claras; nenhum segredo copiado |

#### COS-G10 ? **Editor e visualizadores de projeto:** `src/renderer/file-panel.ts`, `file-code-editor.ts`, `file-pdf-viewer.ts`, `unified-diff.ts`, `src/main/project-files.ts`

Donos: Tessela, Prisma; composicao: Codex. Fonte COS L33?33. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P1** | **Editor e visualizadores de projeto:** `src/renderer/file-panel.ts`, `file-code-editor.ts`, `file-pdf-viewer.ts`, `unified-diff.ts`, `src/main/project-files.ts` | SENTRA Canvas tem nós, notas e terminais; dispõe de workflows/documentos, mas editor visual rico necessita validação E2E | Adaptar painéis laterais discretos CodeMirror/merge e PDF com diffs de arquivos efetivamente autorizados, sem poluir a estética minimalista | Escritas seguem Operation/grant/review; preview jamais executa código; arquivos grandes e path traversal limitados |

#### COS-G11 ? **Política de comandos baseada em allowlist:** `src/shared/command-allowlist.ts`, `src/main/sandbox.ts`

Donos: Forja, Pacto; composicao: Codex. Fonte COS L34?34. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P2** | **Política de comandos baseada em allowlist:** `src/shared/command-allowlist.ts`, `src/main/sandbox.ts` | SENTRA tem policy+grants centrais e paths escopados | Reaproveitar somente parser de invocações simples/fail-closed e casos de teste, subordinados à policy central. Não copiar a suposição de que cwd aprovado sandboxa um processo | Todo comando precisa de capability+effect gate; binário permitido pode executar filhos/IO e continua exigindo isolamento verdadeiro |

#### COS-G12 ? **Extensão/browser observability:** `extension/chatgpt-dom.js`, `content.js`, `fiber.js`, `background.js`; `src/main/browser-proof.ts`

Donos: Brisa, Rastro; composicao: Codex. Fonte COS L35?35. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P2** | **Extensão/browser observability:** `extension/chatgpt-dom.js`, `content.js`, `fiber.js`, `background.js`; `src/main/browser-proof.ts` | SENTRA tem Edge/Web Models, extensão e Playwright, com contrato próprio | Extrair conceitos de estado da página, tab lifecycle, detecção de geração, rebind e health, com testes de compatibilidade; **não** substituir extensão inteira nem copiar seletores sem avaliação de termos, privacidade e atualização | Browser UI não é API pública; políticas do provedor, usuário e Chrome respeitadas; sem importação silenciosa de cookies |

#### COS-G13 ? **UX, acessibilidade, testes:** `src/renderer/settings-search.ts`, `workspace-docks.ts`, `panel-motion.ts`; `scripts/verify-*.cjs`; `test/*`

Donos: Prisma, Vitra; composicao: Codex. Fonte COS L36?36. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **P2** | **UX, acessibilidade, testes:** `src/renderer/settings-search.ts`, `workspace-docks.ts`, `panel-motion.ts`; `scripts/verify-*.cjs`; `test/*` | Canvas React/Lucide/Radix/React Flow atualizado, design corporativo minimalista | Adotar pesquisa nas configurações, acessibilidade de teclado, persistência de docks, reduced motion e cenários Playwright; não copiar o visual inteiro | Screenshot/dpi 100/125/150%, foco, teclado, performance e teste da janela WebView2 |

#### COS-A01 ? **Join exato de origem MCP**: src/main/session/correlation.ts e recorder.ts unem o x-request-id do MCP ao message.metadata.request_id do browser e ao conversationId. Identidade com

Donos: Brisa, Rastro, Pacto, Codex; composicao: Codex. Fonte COS L101?101. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A01 / **P0** | **Join exato de origem MCP**: src/main/session/correlation.ts e recorder.ts unem o x-request-id do MCP ao message.metadata.request_id do browser e ao conversationId. Identidade comprovada nao expira por TTL nem troca de dono sob observacao conflitante | sentra_mcp/identity.py autentica principal e sessao de transporte; sentra_mcp/services/context_projection.py armazena conversation_id. Isto nao prova sozinho um join completo request-ID-da-pagina para a chamada MCP | Projetar RequestCorrelation no Control Plane como **prova de origem, nunca grant**. Testar duas abas concorrentes, refresh, troca de conta, colisao e chamada tardia sem atribuicao por horario/chat ativo |

#### COS-A02 ? **Bloqueio imediato por chat especifico**: src/main/session/blocked-chats.ts impede novas ferramentas numa conversa travada; test/blocked-chats.test.ts

Donos: Pacto; composicao: Codex. Fonte COS L102?102. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A02 / **P0** | **Bloqueio imediato por chat especifico**: src/main/session/blocked-chats.ts impede novas ferramentas numa conversa travada; test/blocked-chats.test.ts | Control Plane ja revoga grants e operacoes; busca no pacote sentra_canvas nao encontrou politica equivalente com chaves de conversa Web | Botao Bloquear ferramentas deste chat, filtro antes do dispatcher, sem derrubar outros agentes e sem executar chamadas tardias |

#### COS-A03 ? **Confiança/default deny por conversa**: src/main/session/trusted-chats.ts e conversation-access.ts fazem autorizacao adicional por conversation ID e sucessor comprovado

Donos: Pacto, Rastro; composicao: Codex. Fonte COS L103?103. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A03 / **P0** | **Confiança/default deny por conversa**: src/main/session/trusted-chats.ts e conversation-access.ts fazem autorizacao adicional por conversation ID e sucessor comprovado | Grants SENTRA por principal, workspace, agente e WorkItem nao substituem o criterio de qual chat web e confiavel | Permissao adicional opcional ChatTrust: trust nao cria grant, block prevalece, unknown owner nega no modo estrito, handoff so herda apos commit comprovado |

#### COS-A04 ? **Espera pela aprovacao humana no proprio ChatGPT**: src/main/approval-wait.ts e renderer/tool-approval.ts; espera nao e resolvida por auto-reload

Donos: Brisa, Rastro, Prisma; composicao: Codex. Fonte COS L104?104. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A04 / **P0** | **Espera pela aprovacao humana no proprio ChatGPT**: src/main/approval-wait.ts e renderer/tool-approval.ts; espera nao e resolvida por auto-reload | SENTRA ja tem seu proprio fluxo de aprovacao, mas nao ha prova de tratamento do cartao de aprovacao que a pagina ChatGPT apresenta | Estado WAITING_CHATGPT_USER_APPROVAL no Canvas/CLI; nao repetir envio nem reiniciar chat durante cartao pendente |

#### COS-A05 ? **Comprovacao duravel de app/plugin na conta e uso real por tunel**: src/main/connector-proof.ts; preserva a ultima prova e invalida se o tunel ou perfil mudar

Donos: Brisa, Vitra; composicao: Codex. Fonte COS L105?105. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A05 / **P0** | **Comprovacao duravel de app/plugin na conta e uso real por tunel**: src/main/connector-proof.ts; preserva a ultima prova e invalida se o tunel ou perfil mudar | sentra_remote/onboarding.py tem ready_to_install e requires_account_authorization; readiness local nao comprova instalacao na conta ChatGPT | Separar LOCAL_MCP_READY, TUNNEL_ONLINE, CHATGPT_APP_OBSERVED, TOOLS_AUTHORIZED e VERSION_CURRENT; sem gravar credenciais na prova |

#### COS-A06 ? **Refresh de schemas MCP no ChatGPT apos update**, grace period, debounce, respostas tardias e falha limitada: src/main/plugin-refresh.ts, test/plugin-refresh-workflow.test.ts

Donos: Pacto, Brisa, Vitra; composicao: Codex. Fonte COS L106?106. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A06 / **P0** | **Refresh de schemas MCP no ChatGPT apos update**, grace period, debounce, respostas tardias e falha limitada: src/main/plugin-refresh.ts, test/plugin-refresh-workflow.test.ts | SENTRA recompila e verifica o MCP local, mas nao ha prova E2E de re-publicacao de tool schema **cacheado no lado da conta** | Confrontar tools/list e version/fingerprint com o publicado, avisar usuario quando refresh manual for necessario e testar schema antigo |

#### COS-A07 ? **Superficies MCP separadas por dominio**, Core/Desktop/Plugins: src/main/mcp/surfaces.ts e kernel.ts

Donos: Pacto, Lume; composicao: Codex. Fonte COS L107?107. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A07 / **P0-P1** | **Superficies MCP separadas por dominio**, Core/Desktop/Plugins: src/main/mcp/surfaces.ts e kernel.ts | SENTRA tem ToolPolicyProxy, ToolCatalog e diversos provedores; expor 37+ integracoes no mesmo namespace aumenta disclosure e revisao de permissao | Uma unica autoridade com projecoes MCP distintas e tool sets minimos. Nao criar tres control planes nem exigir tres tunéis sem justificar o custo |

#### COS-A08 ? **Code Mode com JavaScript dentro de QuickJS WASM** e limites CPU/memoria/tempo/chamadas/tamanho: src/main/mcp/code-mode-runtime.ts e code-mode-worker.ts

Donos: Pacto; composicao: Codex. Fonte COS L108?108. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A08 / **P1** | **Code Mode com JavaScript dentro de QuickJS WASM** e limites CPU/memoria/tempo/chamadas/tamanho: src/main/mcp/code-mode-runtime.ts e code-mode-worker.ts | sentra_interop/tool_catalog.py ja oferece descoberta seletiva; nao ha prova de composicao sandboxed dessas chamadas em um unico orquestrador | Adaptar como **compositor** sem IO host proprio; cada ferramenta interna ainda precisa de OperationRequest/grant/fencing do SENTRA. Nunca tratar QuickJS como isolamento de efeito fisico |

#### COS-A09 ? **Prova de extensao instalada, pareada e login anterior**, mesmo entre reinicios: src/main/browser-proof.ts

Donos: Brisa, Vitra; composicao: Codex. Fonte COS L109?109. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A09 / **P1** | **Prova de extensao instalada, pareada e login anterior**, mesmo entre reinicios: src/main/browser-proof.ts | sentra_remote/openai_browser_enrollment.py cobre captura guiada, mas o wizard precisa distinguir instalada, pareada, autenticada, revogada e perfil/browser-ID | Evidencia somente de status sem copia de cookies. Tela de reparo por etapa e teste de logout/troca do Edge |

#### COS-A10 ? **API local de leitura e acao com duas chaves de consentimento**, action opt-in, limite de corpo, Origin/Host guard e paginação: src/main/control-api.ts e control-actions.ts

Donos: Pacto, Codex; composicao: Codex. Fonte COS L110?110. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A10 / **P1** | **API local de leitura e acao com duas chaves de consentimento**, action opt-in, limite de corpo, Origin/Host guard e paginação: src/main/control-api.ts e control-actions.ts | Broker/HTTP do Canvas e Control Plane ja existem; nao introduzir listener privilegiado concorrente | Apenas projecao autorizada do servidor central, default read-only; POST com politica propria e budget. Este e um refinamento da P1 da matriz anterior, nao uma nova autoridade |

#### COS-A11 ? **Busca textual entre conversas em indice incremental**: src/main/session/search.ts e renderer/chat-search.ts criam search.txt pequeno por sessao sem reler journals enormes

Donos: Rastro, Nexo, Prisma; composicao: Codex. Fonte COS L116?116. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A11 / **P1** | **Busca textual entre conversas em indice incremental**: src/main/session/search.ts e renderer/chat-search.ts criam search.txt pequeno por sessao sem reler journals enormes | sentra_mcp/services/search_sessions.py faz pesquisa persistente de **arquivos dos workspaces**, diferente de busca em texto de chat. sentra_core/conversations.py ja persiste conversas com protecao OS | Indice local opt-in por principal/workspace, acesso limitado, snippets e saltos para mensagem. Deletar indice com sessao, nao indexar secrets por padrao |

#### COS-A12 ? **Anexos de mensagem por armazenamento independente e chunks**: src/main/session/input-attachments.ts, input-images.ts, input-history.ts, com limites por formato, tamanho e quota

Donos: Rastro, Brisa, Prisma; composicao: Codex. Fonte COS L117?117. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A12 / **P1** | **Anexos de mensagem por armazenamento independente e chunks**: src/main/session/input-attachments.ts, input-images.ts, input-history.ts, com limites por formato, tamanho e quota | SENTRA tem artefatos, documentos e journals; precisa prova de envio de imagens/arquivos **no composer Web** com recibo e identidade de conversa | Proteger refs de artefato por WorkItem/grant e prova de envio, sem inflar outbox e sem mandar automaticamente arquivos a peers |

#### COS-A13 ? **Historico de streaming por message ID, nao cada frame**: src/main/session/store.ts e recorder.ts, com asset quotas e overflow referenciado

Donos: Rastro, Brisa; composicao: Codex. Fonte COS L118?118. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A13 / **P1** | **Historico de streaming por message ID, nao cada frame**: src/main/session/store.ts e recorder.ts, com asset quotas e overflow referenciado | sentra_core/conversations.py tem SQLite e journal idempotente, mas a equivalencia para mensagem Web parcial/virtualizada nao foi demonstrada | Portar contrato de identidade e revisao da mensagem para persistencia SENTRA, nao copiar storage JSONL concorrente |

#### COS-A14 ? **Limites e consumo observados na conta ChatGPT Web**: src/main/session/usage.ts distingue percentuais restantes, janela de reset e observacao recente

Donos: Brisa, Rastro, Selo; composicao: Codex. Fonte COS L119?119. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A14 / **P1** | **Limites e consumo observados na conta ChatGPT Web**: src/main/session/usage.ts distingue percentuais restantes, janela de reset e observacao recente | sentra_core/provider_usage.py registra tokens reportados e budgets; isso nao prova cota ou disponibilidade mostrada na conta Web | Exibir lado a lado SENTRA-accounted usage e ChatGPT-observed limits, com frescor/conta/estimativa identificados; nao usar um como verdade do outro |

#### COS-A15 ? **Relatorio de diagnostico anonimizado antes de compartilhar**: src/main/diagnostics-report.ts e report-scrub.ts removem nomes de usuario, pastas, chat titles e segredos

Donos: Vitra, Selo; composicao: Codex. Fonte COS L120?120. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A15 / **P1-seguranca** | **Relatorio de diagnostico anonimizado antes de compartilhar**: src/main/diagnostics-report.ts e report-scrub.ts removem nomes de usuario, pastas, chat titles e segredos | sentra_remote/diagnostics.py::collect inclui hostname, device_id, relay_url, allowed_roots e caminho do audit log no JSON atual. Sao metadados identificadores, mesmo sem tokens explicitos | Separar diagnostico interno de export redigido com preview, tags estaveis e testes de nao vazamento de IP, URL, path, e-mail, titulo, chave e nomes de projeto |

#### COS-A16 ? **Resumo humano de chamadas de ferramenta com evidencias**: src/main/mcp/call-context.ts e session/summarize.ts produzem detalhes por tipo (exit code, linhas alteradas, hits) e own

Donos: Pulso, Prisma, Vitra; composicao: Codex. Fonte COS L121?121. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A16 / **P1** | **Resumo humano de chamadas de ferramenta com evidencias**: src/main/mcp/call-context.ts e session/summarize.ts produzem detalhes por tipo (exit code, linhas alteradas, hits) e ownership isolado por async call | SENTRA tem Operation/Artifact e timeline, mas a renderizacao uniforme desse recibo por provedor nao foi provada | Derivar linha curta do evento real, nunca inferir de texto do modelo. Ligar ao painel do Canvas e CLI sem expor secrets |

#### COS-A17 ? **GC controlado de workers, processos e terminais**: src/main/runtime-gc.ts e codex/ownership.ts distinguem a retencao de recursos do deadline da tarefa

Donos: Pulso, Forja; composicao: Codex. Fonte COS L126?126. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A17 / **P1** | **GC controlado de workers, processos e terminais**: src/main/runtime-gc.ts e codex/ownership.ts distinguem a retencao de recursos do deadline da tarefa | SENTRA ja tem leases, ConPTY e reconciliacao, mas o ciclo de vida de terminal, Run, worker e processo nao e necessariamente o mesmo | Limpeza so por ownership e prova de idle; nunca encerrar ConPTY do usuario ou processo de outro WorkItem. Testar crash/restart/UNCERTAIN |

#### COS-A18 ? **Git/diff integrado, revisionamento de vista e watchers de arquivos limitados**: src/main/project-git.ts, project-file-watcher.ts; debounce e check contra mudanca externa

Donos: Tessela, Prisma; composicao: Codex. Fonte COS L127?127. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A18 / **P1** | **Git/diff integrado, revisionamento de vista e watchers de arquivos limitados**: src/main/project-git.ts, project-file-watcher.ts; debounce e check contra mudanca externa | SENTRA tem RepositoryService, PatchManager e workspace sandbox; o Canvas nao tem aceite de paridade de revisao visual de diff/watch | Painel minimalista opcional, revisao por documento, detecao de alteracao externa e arquivo renomeado, sem permitir write por watcher |

#### COS-A19 ? **Updater sem bloquear startup, pacote encenado e aplicado quando usuario encerra app**: src/main/update.ts, test/update.test.ts

Donos: Vitra; composicao: Codex. Fonte COS L128?128. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A19 / **P1** | **Updater sem bloquear startup, pacote encenado e aplicado quando usuario encerra app**: src/main/update.ts, test/update.test.ts | sentra_remote/updater.py JA valida manifest SHA256 e Authenticode. A lacuna e UX/restart/compatibilidade com extensao e plugin, nao download seguro basico | Upgrade coordenado do aplicativo, extensao, Web Models e schema MCP, sem interromper ConPTY. Em falha, permanecer na versao funcional e permitir rollback |

#### COS-A20 ? **Export Markdown por resposta ou sessao completa**, incluindo trechos longos em overflow: src/main/session/markdown-export.ts, shared/markdown-export.ts

Donos: Rastro, Prisma; composicao: Codex. Fonte COS L129?129. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A20 / **P2** | **Export Markdown por resposta ou sessao completa**, incluindo trechos longos em overflow: src/main/session/markdown-export.ts, shared/markdown-export.ts | SENTRA tem documentos e historico protegido, mas nao foi verificado um atalho simples de export da conversa com proveniencia | Exportar apenas conversa selecionada, com redacao opcional, sem expor evidencias secretas. UI compacta sem novo backend de documentos |

#### COS-A21 ? **Skill packs vindos do GitHub fixados em SHA, atualizacao e skills recomendadas**: src/main/skill-github.ts, recommended-skills.ts, test/skill-github.test.ts

Donos: Pacto, Vitra; composicao: Codex. Fonte COS L130?130. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| A21 / **P2** | **Skill packs vindos do GitHub fixados em SHA, atualizacao e skills recomendadas**: src/main/skill-github.ts, recommended-skills.ts, test/skill-github.test.ts | Complementa a frente Skills da primeira matriz, em vez de criar outro framework de agentes | Import com teto de tamanho/arquivos, hash e aprovacao de usuario, acao de atualizar/revogar; skill nao cria grants |

### OpenDots_GA_crosswalk_34

#### OD-G01 ? **G01 — MCPB lifecycle / L/P**

Donos: Pacto, Vitra, Codex; composicao: Codex. Fonte OD L398?398. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G01 — MCPB lifecycle / L/P** | CF10: MCP HTTP, sem lifecycle MCPB completo | N | FF09: browser restrito, não catálogo MCPB genérico | Média só para discovery/status; manter ZIP/stdio/OAuth PKCE/vault/supervisor central e provar uninstall/restart real | P0 |

#### OD-G02 ? **G02 — conta/modelo/effort/Automatic / P**

Donos: Brisa, Rastro, Prisma, Vitra; composicao: Codex. Fonte OD L399?399. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G02 — conta/modelo/effort/Automatic / P** | CF01: provider configurado | AF04: login Claude, diferente conta | FF01: provider OpenRouter descrito | Baixa; nenhum atesta picker/conta ChatGPT. Não inferir plano ou trocar modelo silenciosamente | P0 |

#### OD-G03 ? **G03 — Compact & Resume / L/P**

Donos: Rastro, Nexo; composicao: Codex. Fonte OD L400?400. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G03 — Compact & Resume / L/P** | CF07: Threads/contexto | AF06: session-id/resume | FF10: engine fork/compaction | Média semântica; continuidade Web A→B só após receipt, mesma Run/WorkItem, sem atribuição por horário | P0 |

#### OD-G04 ? **G04 — entrega Web/outbox / L/P**

Donos: Rastro, Brisa; composicao: Codex. Fonte OD L401?401. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G04 — entrega Web/outbox / L/P** | CF11: claim/receipt MCP, distinto | AF12: janela de perda de report | FF07: outbox transacional | Alta ideia feder; conservar ciphertext/IDs/epoch, produtor/relay/host reais e UNCERTAIN sem retry | P0 |

#### OD-G05 ? **G05 — Goal/Loop/workers / L/P**

Donos: Pulso, Nexo; composicao: Codex. Fonte OD L402?402. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G05 — Goal/Loop/workers / L/P** | CF14: runner/lease | AF07/11: recuperação/agenda | FF03/08/12: VM/fila documentadas | Média; aproveitar pausa/ownership, não importar scheduler. Validar orçamento, cancelamento e GC físico | P0 |

#### OD-G06 ? **G06 — terminal persistente / L/P**

Donos: Pulso; composicao: Codex. Fonte OD L403?403. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G06 — terminal persistente / L/P** | CF12: shell de serviço | AF06: comando remoto | FF09: exec guest | Baixa como substituto; ConPTY Start/Write/Close com handle owned e API owner-auth continua obrigatório | P0 |

#### OD-G07 ? **G07 — Skills versionadas / L/P**

Donos: Pacto; composicao: Codex. Fonte OD L404?404. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G07 — Skills versionadas / L/P** | CF17: learning/containers | N | FF10: Skills guest | Média para discovery; rejeitar ativação aprendida sem revisão SHA, ACL, update/revoke e rollback | P1 |

#### OD-G08 ? **G08 — API read/action opt-in / L/P**

Donos: Pacto, Codex; composicao: Codex. Fonte OD L405?405. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G08 — API read/action opt-in / L/P** | CF19/11: bearer/aprovação | AF02/09: autenticação insuficiente | FF01/06: bearer/policy | Média; ação exige duas provas e clique owner real, limits/rate/deadline por endpoint | P0 |

#### OD-G09 ? **G09 — Setup/Doctor/repair / L/P**

Donos: Vitra; composicao: Codex. Fonte OD L406?406. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G09 — Setup/Doctor/repair / L/P** | CF01/22: setup de template | AF14: script dev | FF02/16: Doctor/instalação manual | Baixa para release; preservar Doctor SENTRA, reparar por etapa e homologar Setup/MSI contemporâneo | P0 |

#### OD-G10 ? **G10 — editor/diff/PDF / L/P**

Donos: Tessela, Prisma; composicao: Codex. Fonte OD L407?407. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G10 — editor/diff/PDF / L/P** | CF03–06: melhor referência de página | N | FF15: UI/diff com terceiros | Alta para UX; PDF central local já declarado integrado, ainda precisa prova instalada e dependência renderer | P1 |

#### OD-G11 ? **G11 — allowlist de comandos / P**

Donos: Forja, Pacto; composicao: Codex. Fonte OD L408?408. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G11 — allowlist de comandos / P** | CF12: permissões amplas | AF10: parser não seguro | FF05/09: tool map | Média para catálogo, baixa para shell livre. Rejeitar classificação textual como autorização; validar quoting/filhos/limites | P0 |

#### OD-G12 ? **G12 — observabilidade browser / L/P**

Donos: Brisa, Rastro; composicao: Codex. Fonte OD L409?409. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G12 — observabilidade browser / L/P** | CF09: consulta/computer | N | FF11: browser guest | Baixa para objetivo; screenshot/URL não prova request/message/epoch/conta do Edge. Preservar BrowserEvidence | P0 |

#### OD-G13 ? **G13 — UX acessível / L/P**

Donos: Prisma, Vitra; composicao: Codex. Fonte OD L410?410. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **G13 — UX acessível / L/P** | CF04/06/20: atalhos/status/tema | AF09/13: cards/polling | FF15: componentes web | Alta como referência; validar leitor de tela, WebView2, DPI físico, foco e performance real | P1 |

#### OD-A01 ? **A01 — join MCP↔mensagem↔epoch/doc / L/P**

Donos: Brisa, Rastro, Pacto, Codex; composicao: Codex. Fonte OD L411?411. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A01 — join MCP↔mensagem↔epoch/doc / L/P** | CF18: escopo thread, insuficiente | N | FF07: IDs de transcript, outra origem | Baixa; nenhuma fonte resolve join Web. Guard deve cobrir toda chamada MCP instalada | P0 |

#### OD-A02 ? **A02 — bloquear chat específico / L/P**

Donos: Pacto; composicao: Codex. Fonte OD L412?412. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A02 — bloquear chat específico / L/P** | CF18: escopo lógico | AF08: regra de usuário | FF06: gate do Dot | Média ideia; chat block central prevalece, sem bloquear outros chats/WorkItems ou aceitar chamada tardia | P0 |

#### OD-A03 ? **A03 — ChatTrust/default deny / L/P**

Donos: Pacto, Rastro; composicao: Codex. Fonte OD L413?413. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A03 — ChatTrust/default deny / L/P** | CF18/10: scope; annotation não é trust | AF02: identidade cliente inadequada | FF05: deny no tool map | Média; exigir proveniência, unknown nega, sucessor só herda após prova e trust nunca cria Grant | P0 |

#### OD-A04 ? **A04 — esperar aprovação humana ChatGPT / P**

Donos: Brisa, Rastro, Prisma; composicao: Codex. Fonte OD L414?414. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A04 — esperar aprovação humana ChatGPT / P** | CF11: card da aplicação | AF09: prompt web/Telegram | FF06: aprovação própria durável | Média para WAITING, baixa para integração Web. Não resolver com reload/envio repetido | P0 |

#### OD-A05 ? **A05 — app/plugin comprovado na conta / L/P**

Donos: Brisa, Vitra; composicao: Codex. Fonte OD L415?415. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A05 — app/plugin comprovado na conta / L/P** | CF10: conexão registrada | AF04: outro OAuth | FF01: token de API própria | Baixa; separar ready/tunnel/app-observed/tools-authorized/version-current com prova independente | P0 |

#### OD-A06 ? **A06 — refresh schemas na conta / L/P**

Donos: Pacto, Brisa, Vitra; composicao: Codex. Fonte OD L416?416. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A06 — refresh schemas na conta / L/P** | CF10: discovery MCP | N | FF05: tools estáticas | Média catálogo local; validar cache/refresh no cliente ChatGPT instalado, versão e respostas tardias | P0 |

#### OD-A07 ? **A07 — superfícies mínimas por domínio / L/P**

Donos: Pacto, Lume; composicao: Codex. Fonte OD L417?417. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A07 — superfícies mínimas por domínio / L/P** | CF10: namespaces/limites | AF01: routers por serviço | FF05: mapa restrito | Alta conceitual; projetar subsets na mesma autoridade, sem novos control planes/túneis desnecessários | P1 |

#### OD-A08 ? **A08 — QuickJS WASM limitado / B**

Donos: Pacto; composicao: Codex. Fonte OD L418?418. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A08 — QuickJS WASM limitado / B** | N; Node/agent não serve de prova | N; CLI não serve | N; guest engine não serve | Baixa; manter desabilitado até SHA/SBOM, fuel/CPU/mem/IO e cada tool sob Operation/Grant | P0 gate |

#### OD-A09 ? **A09 — extensão instalada/pareada/login / B/P**

Donos: Brisa, Vitra; composicao: Codex. Fonte OD L419?419. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A09 — extensão instalada/pareada/login / B/P** | CF09 não é MV3 | N | FF11 não é Edge pareado | Baixa; observação real por perfil/conta, logout/revogação/restart, sem cookies | P0 |

#### OD-A10 ? **A10 — consentimentos read/action / L/P**

Donos: Pacto, Codex; composicao: Codex. Fonte OD L420?420. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A10 — consentimentos read/action / L/P** | CF11/12: booleans e cards | AF08/09: regras sem owner gate | FF05/06: allow/ask/deny | Média; callback ligado à sessão e clique real, alvo/escopo exatos e revogação em execução | P0 |

#### OD-A11 ? **A11 — busca textual de conversas / L/P**

Donos: Rastro, Nexo, Prisma; composicao: Codex. Fonte OD L421?421. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A11 — busca textual de conversas / L/P** | CF02: biblioteca de páginas, diferente | AF13: lista de tasks | FF07: transcript, busca não verificada | Média só para UX; índice opt-in com ACL/provenance e deep link, não indexar segredos | P1 |

#### OD-A12 ? **A12 — anexos/chunks/upload receipt / L/P**

Donos: Rastro, Brisa, Prisma; composicao: Codex. Fonte OD L422?422. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A12 — anexos/chunks/upload receipt / L/P** | N no fluxo Web alvo | N | FF09: arquivos guest, não upload Web | Baixa; ref por WorkItem/Grant e receipt de anexo na conversa real, limites/formato/quota | P1 |

#### OD-A13 ? **A13 — streaming por message ID / L/P**

Donos: Rastro, Brisa; composicao: Codex. Fonte OD L423?423. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A13 — streaming por message ID / L/P** | CF07/15: AG-UI/transcript | AF13: polling de task, não streaming Web | FF07: eventos/transcript transacional | Alta ideia; identidade e revisão por mensagem Web, overflow referenciado e restart observado | P1 |

#### OD-A14 ? **A14 — quota observada na conta / P**

Donos: Brisa, Rastro, Selo; composicao: Codex. Fonte OD L424?424. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A14 — quota observada na conta / P** | CF01: uso provider, outra métrica | N | FF01: custo API, outra métrica | Baixa; separar accounted de observed, frescor e conta independente; não inferir quota Web | P1 |

#### OD-A15 ? **A15 — diagnóstico anonimizado / L/P**

Donos: Vitra, Selo; composicao: Codex. Fonte OD L425?425. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A15 — diagnóstico anonimizado / L/P** | CF22: opt-out não é anonimização | Logs não demonstram export redigido | FF01: Doctor não prova anonimização | Média; preview/export com remoção de paths/hosts/URLs/nomes, retention/exclusão no instalado | P1 |

#### OD-A16 ? **A16 — recibos humanos uniformes / L/P**

Donos: Pulso, Prisma, Vitra; composicao: Codex. Fonte OD L426?426. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A16 — recibos humanos uniformes / L/P** | CF11/12/15: cards e registros | AF06/12: status/output | FF07/14/15: eventos/tool labels | Alta; derivar do receipt real: alvo, duração, status, exit, alterações, sem segredo ou inferência do modelo | P1 |

#### OD-A17 ? **A17 — GC de recursos próprios / L/P**

Donos: Pulso, Forja; composicao: Codex. Fonte OD L427?427. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A17 — GC de recursos próprios / L/P** | CF14: lease/cancel | AF03: cleanup ausente documentado | FF03/04: gestão VM, auditoria pendente | Média semântica; cleanup por ownership/handle, crash/restart e UNCERTAIN, nunca PID-only | P0 |

#### OD-A18 ? **A18 — Git/diff/watch revisions / L/P**

Donos: Tessela, Prisma; composicao: Codex. Fonte OD L428?428. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A18 — Git/diff/watch revisions / L/P** | CF03/05: revisão de página | AF10: classificação não é diff | FF15: diff derivado de outro repo | Alta para estados; API Git/watcher real, CAS/debounce/rename, watcher nunca concede write | P1 |

#### OD-A19 ? **A19 — updater staged / L/P**

Donos: Vitra; composicao: Codex. Fonte OD L429?429. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A19 — updater staged / L/P** | CF13: pin de serviço, sem desktop updater | AF14: dev script | FF16: atualização manual | Baixa; updater SENTRA mantém integridade/assinatura, coordena schema/MCPB/extension e rollback sem interromper terminal | P0 gate/P1 UX |

#### OD-A20 ? **A20 — export Markdown / L/P**

Donos: Rastro, Prisma; composicao: Codex. Fonte OD L430?430. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A20 — export Markdown / L/P** | CF06: export de página, diferente sessão | AF06: output, export não demonstrado | N para export Web selecionado | Alta para affordance; exportar conversa/mensagem comprovada, overflow e redaction opcional | P2 |

#### OD-A21 ? **A21 — SkillPack Git-pinned / L/P**

Donos: Pacto, Vitra; composicao: Codex. Fonte OD L431?431. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| **A21 — SkillPack Git-pinned / L/P** | CF17: learning, não pin | N | FF10: SKILL.md, não prova pin | Média discovery; SHA completo, teto de arquivos/tamanho, review e update/revoke no WorkItem | P2 |

### Ecosystem_initial_37

#### ECO-01 ? ufo

Donos: Forja, Selo, Nexo; composicao: Codex. Fonte ECO L74?87. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### ufo — P0, extrair/adaptar

**Resolve.** AgentOS Windows UFO2 e coordenador Galaxy/Constellation para agentes que executam ações em aplicativos e máquinas distribuídas.

**Aproveitamento de código.** Adaptar módulos de ações em apps Windows, critérios de descoberta de capacidades, decomposição de objetivos e estratégias de recuperação.

**Encaixe arquitetural.** MachineRuntime seleciona um Windows executor, cada ação vira Operation idempotente e cada resultado vira Evidence; aproveitar Galaxy como inspiração de DAG.

**Sobreposições e limitações.** SENTRA já possui Goals/WorkItems e Remote Agent; não criar um segundo orquestrador soberano, especialmente baseado só em decisão de LLM.

**Aceite obrigatório.** Abrir app de teste, operar elemento UIA, negar ação fora do PID/escopo, reconectar e auditar resultado.

**Evidências concretas.** `third_party/ufo/galaxy/agents/constellation_agent.py`, `third_party/ufo/galaxy/agents/constellation_agent_states.py`, `third_party/ufo/documents/docs/galaxy/constellation_agent/state.md`, `third_party/ufo/documents/docs/galaxy/constellation_agent/command.md`, `third_party/ufo/documents/docs/galaxy/constellation_agent/overview.md`; `third_party/ufo/README.md`. Revisão `a795552d976c`; 931 arquivos versionados; principais extensões: .py: 496, .md: 226, .png: 92, .yaml: 33.

#### ECO-02 ? openhands

Donos: Lume, Prisma, Nexo; composicao: Codex. Fonte ECO L88?101. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### openhands — P1, extrair UI

**Resolve.** Agent Canvas visual especializado em conversas, execução de agents, terminal, browser, arquivos, seleção de backend e observabilidade.

**Aproveitamento de código.** Comparar componentes de interface, seleção de agentes, estados de conversa, visibilidade de ações e UX de permissões.

**Encaixe arquitetural.** Extrair padrões ou widgets úteis para o Canvas SENTRA sem mudar sua identidade visual nem substituir o grafo de terminais.

**Sobreposições e limitações.** Seu frontend depende de Agent Server; importar a aplicação inteira recriaria estados e telas que já existem.

**Aceite obrigatório.** Duas sessões de agentes em backends diferentes, feedback real, cancelamento e reabertura da UI.

**Evidências concretas.** `third_party/openhands/src/services/canvas-ui.ts`, `third_party/openhands/src/fixtures/canvas-demo-conversation.ts`, `third_party/openhands/src/services/child-conversation-launch.ts`, `third_party/openhands/src/contexts/conversation-websocket-context.tsx`, `third_party/openhands/src/api/backend-registry/last-conversation-store.ts`; `third_party/openhands/README.md`. Revisão `76398bb5c5b9`; 2564 arquivos versionados; principais extensões: .ts: 1094, .tsx: 1059, .svg: 146, .md: 78.

#### ECO-03 ? openhands-agent-sdk

Donos: Lume, Rastro, Nexo; composicao: Codex. Fonte ECO L102?115. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### openhands-agent-sdk — P1, provider adapter

**Resolve.** Servidor REST/WebSocket, SDK Python, lifecycle de agentes e workspace, stream de eventos e integração ACP.

**Aproveitamento de código.** Extrair contratos tipados de eventos, streams, adaptação de agentes, ferramentas e ciclo de vida de sessões.

**Encaixe arquitetural.** OpenHandsProviderAdapter opcional usando Run/Agent/Chat do SENTRA como identidades duráveis.

**Sobreposições e limitações.** Não delegar credenciais nem decisão de promoção ao Agent Server externo.

**Aceite obrigatório.** Teste com 2 agentes, restart, eventos repetidos, política de workspace e rastreio de tool call.

**Evidências concretas.** `third_party/openhands-agent-sdk/clients/typescript/src/events/websocket-client.ts`, `third_party/openhands-agent-sdk/clients/typescript/src/events/bash-websocket-client.ts`, `third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/conversation/events_list_base.py`, `third_party/openhands-agent-sdk/openhands-workspace/openhands/workspace/agent_sandbox/README.md`, `third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/workspace_router.py`; `third_party/openhands-agent-sdk/README.md`. Revisão `2804c1273b40`; 1855 arquivos versionados; principais extensões: .py: 1401, .ts: 117, .md: 88, .json: 83.

#### ECO-04 ? agent-client-protocol

Donos: Lume; composicao: Codex. Fonte ECO L116?129. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### agent-client-protocol — P0, adapter de protocolo

**Resolve.** Padrão de sessões, capabilities e comunicação entre clientes e agentes CLI.

**Aproveitamento de código.** Implementar JSON-RPC stdio, session/new, prompt, progress, tool updates, solicitações de consentimento e cancelamento.

**Encaixe arquitetural.** ACPAdapter por agente, plugável no Canvas e no SENTRA CLI; mensagens podem usar contexto tipado interno.

**Sobreposições e limitações.** As diretivas internas do Canvas não substituem o protocolo ACP.

**Aceite obrigatório.** Testes de contrato, dois CLI ACP, recusa de permissão, encerramento incerto e reconexão.

**Evidências concretas.** `third_party/agent-client-protocol/agent-client-protocol-schema/src/v1/tool_call.rs`, `third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/tool_call.rs`, `third_party/agent-client-protocol/schema/v1/src/lib.rs`, `third_party/agent-client-protocol/schema/v2/src/lib.rs`, `third_party/agent-client-protocol/schema/v1/CHANGELOG.md`; `third_party/agent-client-protocol/README.md`. Revisão `8c4b8faff610`; 273 arquivos versionados; principais extensões: .mdx: 168, .rs: 33, .md: 11, .json: 11.

#### ECO-05 ? acp-registry

Donos: Lume, Vitra; composicao: Codex. Fonte ECO L130?143. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### acp-registry — P2, catalogo

**Resolve.** Catálogo interoperável de agentes compatíveis com ACP.

**Aproveitamento de código.** Ler descritores, versões, capacidades declaradas, compatibilidade e instruções de instalação.

**Encaixe arquitetural.** Catálogo de agentes do Canvas com version pin e importação autorizada.

**Sobreposições e limitações.** Registry não é fonte confiável de executáveis; exigir aprovação/pin/verificação.

**Aceite obrigatório.** Bloquear agente incompatível, link malicioso, downgrade e instalações sem consentimento.

**Evidências concretas.** `third_party/acp-registry/.github/workflows/build_registry.py`, `third_party/acp-registry/.github/workflows/registry_utils.py`, `third_party/acp-registry/.github/workflows/build-registry.yml`; `third_party/acp-registry/README.md`. Revisão `f44424b681c1`; 551 arquivos versionados; principais extensões: .json: 256, .md: 218, .svg: 42, .py: 20.

#### ECO-06 ? a2a

Donos: Lume; composicao: Codex. Fonte ECO L144?157. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### a2a — P0, gateway interagente

**Resolve.** Protocolo de interoperabilidade entre agentes, tasks, Agent Cards, artefatos e atualizações.

**Aproveitamento de código.** Aproveitar schemas e patterns de agent discovery, handoff, task progress e artefatos.

**Encaixe arquitetural.** A2A gateway externo que converte task em WorkItem, preservando owner e source identity.

**Sobreposições e limitações.** A2A é transporte e semântica de troca, não autoridade de custo, lease ou aprovação.

**Aceite obrigatório.** Duas instâncias SENTRA trocam tarefa, duplicata bloqueada, artifact validado e revogação.

**Evidências concretas.** `third_party/a2a/docs/topics/streaming-and-async.md`, `third_party/a2a/docs/tutorials/python/7-streaming-and-multiturn.md`; `third_party/a2a/README.md`. Revisão `12e9d2fbb9ba`; 142 arquivos versionados; principais extensões: .md: 48, .yml: 12, .png: 11, .yaml: 10.

#### ECO-07 ? mcp-typescript-sdk

Donos: Lume, Pacto; composicao: Codex. Fonte ECO L158?171. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### mcp-typescript-sdk — P1, cliente de ferramentas

**Resolve.** SDK oficial TypeScript para clients/servers MCP e transports de tools, resources e prompts.

**Aproveitamento de código.** Reaproveitar cliente MCP tipado e contracts, tools schemas, transport safety e testes cruzados.

**Encaixe arquitetural.** Expor API do SENTRA para frontends/plug-ins TypeScript sem criar outra implementação de autorização.

**Sobreposições e limitações.** SENTRA já tem sentra_mcp Python; ambos devem negociar contratos idênticos.

**Aceite obrigatório.** Contract tests Python/TS, permissões, paginação, erros semânticos e versão.

**Evidências concretas.** `third_party/mcp-typescript-sdk/packages/server-legacy/src/auth/clients.ts`, `third_party/mcp-typescript-sdk/packages/server-legacy/src/auth/middleware/clientAuth.ts`, `third_party/mcp-typescript-sdk/docs/servers/resources.md`, `third_party/mcp-typescript-sdk/docs/clients/server-requests.md`, `third_party/mcp-typescript-sdk/packages/server/src/server/perRequestTransport.ts`; `third_party/mcp-typescript-sdk/README.md`. Revisão `b022522089a0`; 1143 arquivos versionados; principais extensões: .ts: 667, .json: 279, .md: 124, .mjs: 20.

#### ECO-08 ? daytona

Donos: Forja, Pulso; composicao: Codex. Fonte ECO L174?187. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### daytona — P0, adapter e serviço

**Resolve.** Compute/control plane de sandboxes, runners, daemon, snapshots, tools, files, processos, SSH e computer-use.

**Aproveitamento de código.** Adaptar SDK Python, processo de sandbox, snapshots, endpoints de ComputerUse e acessibilidade AT-SPI para Linux.

**Encaixe arquitetural.** DaytonaExecutor opcional gerenciado por WorkItem/Run/Operation SENTRA; sandbox é um recurso de máquina e não uma autoridade de projeto.

**Sobreposições e limitações.** Operar a infraestrutura inteira é mais custoso que instalar uma lib; ambiente Linux não restaura ConPTY Windows.

**Aceite obrigatório.** Criar sandbox, limitar FS e rede, executar, snapshot/recover, encerrar/revogar e confirmar cleanup.

**Evidências concretas.** `third_party/daytona/apps/daemon/pkg/toolbox/process/types.go`, `third_party/daytona/apps/daemon/pkg/toolbox/process/execute.go`, `third_party/daytona/apps/runner/pkg/docker/snapshot_sandbox.go`, `third_party/daytona/apps/daemon/pkg/toolbox/process/pty/types.go`, `third_party/daytona/apps/daemon/pkg/toolbox/process/pty/manager.go`; `third_party/daytona/README.md`. Revisão `fc98a5032c04`; 5702 arquivos versionados; principais extensões: .ts: 1367, .go: 818, .py: 803, .java: 733.

#### ECO-09 ? pywinauto

Donos: Forja; composicao: Codex. Fonte ECO L188?201. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### pywinauto — P0, biblioteca direta

**Resolve.** Automação de aplicativos Windows por elementos UI Automation e Win32.

**Aproveitamento de código.** Usar wrappers de controles, investigação de janelas/elementos, estado e esperas semânticas.

**Encaixe arquitetural.** WindowsUIAExecutor com PID, janela, selector, capability e approval; preferir UIA a cliques cegos.

**Sobreposições e limitações.** Pode não funcionar em apps com UI customizada, privilégios elevados ou sem árvore de acessibilidade.

**Aceite obrigatório.** Executar fluxo em Notepad/Calculator de teste, negar janela errada, tratar timeout e foco.

**Evidências concretas.** `third_party/pywinauto/pywinauto/controls/uiawrapper.py`, `third_party/pywinauto/pywinauto/controls/uia_controls.py`, `third_party/pywinauto/pywinauto/controls/win32_controls.py`, `third_party/pywinauto/pywinauto/windows/uia_element_info.py`, `third_party/pywinauto/pywinauto/windows/win32_element_info.py`; `third_party/pywinauto/README.md`. Revisão `18d2a95cebed`; 293 arquivos versionados; principais extensões: .py: 123, .exe: 77, .txt: 67, .yml: 5.

#### ECO-10 ? hcsshim

Donos: Forja, Vitra; composicao: Codex. Fonte ECO L202?215. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### hcsshim — P1, container Windows opcional

**Resolve.** Interface com Windows Host Compute Service e containers Windows, integração com HCS/OCI.

**Aproveitamento de código.** Estudar lifecycle de instâncias Windows e execução confinada de processos/containers, com integração opcional ao sistema.

**Encaixe arquitetural.** WindowsContainerExecutor para workloads headless, sob o mesmo ExecutorAdapter e policy engine.

**Sobreposições e limitações.** Windows containers não são desktop interativo genérico; exigem versão/recursos específicos do host.

**Aceite obrigatório.** Provisionar e destruir container isolado, testar filesystem, privilégios e filhos.

**Evidências concretas.** `third_party/hcsshim/cmd/runhcs/container.go`, `third_party/hcsshim/internal/runhcs/container.go`, `third_party/hcsshim/internal/jobcontainers/doc.go`, `third_party/hcsshim/internal/jobcontainers/env.go`, `third_party/hcsshim/internal/jobcontainers/oci.go`; `third_party/hcsshim/README.md`. Revisão `ab8249e8a111`; 5443 arquivos versionados; principais extensões: .go: 4486, (sem extensão): 270, .md: 199, .json: 167.

#### ECO-11 ? gvisor

Donos: Forja, Vitra; composicao: Codex. Fonte ECO L216?229. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### gvisor — P1, sandbox Linux

**Resolve.** User-space kernel para aumentar isolamento de contêineres Linux não confiáveis.

**Aproveitamento de código.** Reaproveitar runsc como runtime de sandboxes de código e ferramenta em executores Linux.

**Encaixe arquitetural.** SandboxProfile gVisor no Daytona/Docker quando compatível; recurso opcional.

**Sobreposições e limitações.** Não resolve privilégios de um terminal ConPTY host Windows; compatibilidade de syscalls precisa teste.

**Aceite obrigatório.** Testes adversariais de filesystem, networking, syscall e impacto no desempenho.

**Evidências concretas.** `third_party/gvisor/pkg/sentry/platform/context.go`, `third_party/gvisor/pkg/sentry/platform/kvm/kvm.go`, `third_party/gvisor/pkg/sentry/platform/platform.go`, `third_party/gvisor/pkg/sentry/platform/kvm/config.go`, `third_party/gvisor/pkg/sentry/platform/cpuid_amd64.go`; `third_party/gvisor/README.md`. Revisão `25e4d4778b06`; 4413 arquivos versionados; principais extensões: .go: 2526, (sem extensão): 658, .cc: 370, .md: 137.

#### ECO-12 ? playwright-mcp

Donos: Forja, Brisa; composicao: Codex. Fonte ECO L230?243. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### playwright-mcp — P1, executor browser

**Resolve.** Serviço MCP de operação de navegador, snapshots de acessibilidade e ações contextuais.

**Aproveitamento de código.** Adaptar ferramentas de browser de alto nível e mapeamento de ações DOM/ARIA.

**Encaixe arquitetural.** BrowserExecutor separado e consentido para tarefas web, dentro de scope SENTRA.

**Sobreposições e limitações.** Não pode tomar controle do Edge principal protegido nem herdar cookies sem autorização.

**Aceite obrigatório.** Teste isolamento entre sessões, navegação restrita, tentativas de exfiltração e timeout.

**Evidências concretas.** Nenhum arquivo candidato indexado; `third_party/playwright-mcp/README.md`. Revisão `b8b4183e099f`; 39 arquivos versionados; principais extensões: .ts: 10, .md: 6, .yml: 5, (sem extensão): 5.

#### ECO-13 ? guacamole-client

Donos: Forja, Prisma, Codex; composicao: Codex. Fonte ECO L244?257. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### guacamole-client — P1, viewer web

**Resolve.** Frontend HTML5 para desktops remotos RDP/VNC/SSH.

**Aproveitamento de código.** Reaproveitar interface de stream remoto, teclado, mouse, clipboard restrito e sessão visual.

**Encaixe arquitetural.** Nó Machine no Canvas abre view Guacamole limitada pelo grant da máquina.

**Sobreposições e limitações.** Somente renderiza e transmite interação; não é controlador de privilégio nem tool semântico.

**Aceite obrigatório.** Abrir e fechar sessão remota, revogar ao vivo e registrar evidências de operação.

**Evidências concretas.** `third_party/guacamole-client/guacamole/src/main/frontend/src/app/client/types/ManagedDisplay.js`, `third_party/guacamole-client/extensions/guacamole-display-statistics/src/main/resources/directives/guacClientStatistics.js`, `third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Client.js`, `third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Display.js`, `third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Keyboard.js`. Revisão `38e8cb8ff5cd`; 2033 arquivos versionados; principais extensões: .java: 853, .js: 293, .json: 153, (sem extensão): 149.

#### ECO-14 ? guacamole-server

Donos: Forja, Vitra; composicao: Codex. Fonte ECO L258?271. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### guacamole-server — P1, proxy remoto

**Resolve.** Gateway guacd e suporte de protocolos de desktop remoto.

**Aproveitamento de código.** Executar proxy RDP/VNC/SSH, gerenciamento de conexões e separação de frontend/servidor.

**Encaixe arquitetural.** RemoteDesktopTransport para Máquina existente com credenciais efêmeras SENTRA.

**Sobreposições e limitações.** Não expor RDP/VNC público; proxy precisa isolamento e atualizações.

**Aceite obrigatório.** Testar duas conexões, queda de rede, revogação e recursos de clipboard transfer.

**Evidências concretas.** `third_party/guacamole-server/src/protocols/rdp/doc/svc-example/README.md`. Revisão `ae12b8e51aa6`; 602 arquivos versionados; principais extensões: .c: 282, .h: 234, .keymap: 25, (sem extensão): 21.

#### ECO-15 ? rustdesk

Donos: Forja, Vitra; composicao: Codex. Fonte ECO L272?285. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### rustdesk — P2, controle remoto alternativo

**Resolve.** Sistema de desktop remoto multiplataforma, rede e relay para suportar máquinas existentes.

**Aproveitamento de código.** Estudar comunicação P2P/relay e, opcionalmente, incorporar cliente/serviço separado.

**Encaixe arquitetural.** Alternativa a Guacamole para máquinas de amigos, gerenciada por aprovações SENTRA.

**Sobreposições e limitações.** Remote desktop visual não equivale a automação semântica; superfície de rede e consentimento elevados.

**Aceite obrigatório.** Parear duas máquinas, negar comando sem consentimento, medir reconexão e revogação.

**Evidências concretas.** `third_party/rustdesk/src/client.rs`, `third_party/rustdesk/src/server.rs`, `third_party/rustdesk/src/server/dbus.rs`, `third_party/rustdesk/src/client/helper.rs`, `third_party/rustdesk/src/custom_server.rs`; `third_party/rustdesk/README.md`. Revisão `1d4abd0258bb`; 1000 arquivos versionados; principais extensões: .rs: 289, .dart: 140, .md: 81, .png: 61.

#### ECO-16 ? langgraph

Donos: Pulso; composicao: Codex. Fonte ECO L288?301. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### langgraph — P2, subfluxo opcional

**Resolve.** Grafos de estado para agentes com checkpoints e interrupções.

**Aproveitamento de código.** Reaproveitar subflows LLM com state persistence, interrupt/resume e human-in-loop.

**Encaixe arquitetural.** LangGraphTaskAdapter opcional operando dentro de WorkItem e relatando progressos.

**Sobreposições e limitações.** Não substituir Durable Run, lease, Quality Gate nem política de promoção.

**Aceite obrigatório.** Crash entre etapas, checkpoint reaberto e side effects sem repetição.

**Evidências concretas.** `third_party/langgraph/libs/checkpoint/langgraph/store/base/batch.py`, `third_party/langgraph/libs/checkpoint/langgraph/store/base/embed.py`, `third_party/langgraph/libs/prebuilt/langgraph/prebuilt/interrupt.py`, `third_party/langgraph/libs/langgraph/langgraph/pregel/_checkpoint.py`, `third_party/langgraph/libs/checkpoint/langgraph/checkpoint/base/id.py`; `third_party/langgraph/README.md`. Revisão `bfcfea554ed5`; 684 arquivos versionados; principais extensões: .py: 465, .ipynb: 35, .json: 30, .yml: 28.

#### ECO-17 ? temporal

Donos: Pulso; composicao: Codex. Fonte ECO L302?315. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### temporal — P2, referência worker

**Resolve.** Engine durável distribuída para workflows, activities, histories, timers e retries.

**Aproveitamento de código.** Utilizar padrões de worker queues, liveness, reconciliation e retries como referência/adapter futuro.

**Encaixe arquitetural.** TemporalWorkerAdapter opcional se benchmarks provarem ganho sobre scheduler atual.

**Sobreposições e limitações.** Segundo workflow authority aumenta complexidade e split-brain se não houver limites claros.

**Aceite obrigatório.** Failover de dois workers, evento incerto, recuperação, idempotência e compensação.

**Evidências concretas.** `third_party/temporal/service/history/workflow/activity.go`, `third_party/temporal/service/history/workflow/matcher/activity_matcher.go`, `third_party/temporal/service/history/workflow/matcher/activity_evaluator.go`, `third_party/temporal/service/history/workflow/retry.go`, `third_party/temporal/service/history/tasks/activity_retry_timer.go`; `third_party/temporal/README.md`. Revisão `bae8771853cf`; 3971 arquivos versionados; principais extensões: .go: 3006, .gz: 370, .json: 118, .sql: 111.

#### ECO-18 ? nats-server

Donos: Pulso, Selo, Codex; composicao: Codex. Fonte ECO L316?329. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### nats-server — P1, barramento

**Resolve.** Broker pubsub e JetStream para filas e consumo persistente distribuído.

**Aproveitamento de código.** Reaproveitar streams, consumers, ack, redelivery, retenção e observabilidade de eventos.

**Encaixe arquitetural.** Barramento entre SENTRA Gateway, remote agents e executor; envelope idempotente SENTRA permanece autoridade.

**Sobreposições e limitações.** Ack de mensagem não é prova de efeito concluído, e consumers podem reenviar.

**Aceite obrigatório.** Teste queda de rede, message duplicate, ordem, backpressure e revogação.

**Evidências concretas.** `third_party/nats-server/server/jetstream.go`, `third_party/nats-server/server/jetstream_api.go`, `third_party/nats-server/server/jetstream_errors.go`, `third_party/nats-server/server/jetstream_events.go`, `third_party/nats-server/server/jetstream_cluster.go`; `third_party/nats-server/README.md`. Revisão `6af2d22525d5`; 598 arquivos versionados; principais extensões: .go: 258, .pem: 144, .conf: 107, .key: 15.

#### ECO-19 ? toolhive

Donos: Lume, Pacto; composicao: Codex. Fonte ECO L332?345. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### toolhive — P0, integrar host opcional

**Resolve.** Registro, proxy e isolamento de servidores MCP com policy gates, auth e telemetria.

**Aproveitamento de código.** Incorporar ToolHost/runner MCP, catálogo de servidores, interceptação de tools e isolamento por instância.

**Encaixe arquitetural.** ToolHiveExecutor opcional executa ferramentas após autorização no SENTRA Policy Gate.

**Sobreposições e limitações.** Não permitir tool registry independente expondo ferramentas além de grants.

**Aceite obrigatório.** Testes tool injection, registro indevido, policy deny, sandbox FS/rede, shutdown e rastreabilidade.

**Evidências concretas.** `third_party/toolhive/pkg/runner/policy_gate.go`, `third_party/toolhive/pkg/telemetry/registry.go`, `third_party/toolhive/pkg/registry/policy_gate.go`, `third_party/toolhive/pkg/runner/telemetry_config.go`, `third_party/toolhive/pkg/vmcp/auth/outgoing_registry.go`; `third_party/toolhive/README.md`. Revisão `33ba170aad63`; 2877 arquivos versionados; principais extensões: .go: 2229, .yaml: 287, .md: 250, .yml: 38.

#### ECO-20 ? spire

Donos: Selo; composicao: Codex. Fonte ECO L346?359. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### spire — P1, identidade de dispositivos

**Resolve.** Identidade de workloads SPIFFE com SVID, attestation, mTLS e rotação.

**Aproveitamento de código.** Reaproveitar identidade criptográfica por máquina, agent/daemon e serviços conectados.

**Encaixe arquitetural.** DeviceIdentityProvider mapeia SPIFFE ID à identidade de principal SEN​TRA e autorização.

**Sobreposições e limitações.** É infraestrutura de confiança para multidevice; desnecessário impor ao uso local simples.

**Aceite obrigatório.** Rotação, clone de agente, certificado vencido, revogação e falha de attest.

**Evidências concretas.** `third_party/spire/cmd/spire-server/cli/federation/list.go`, `third_party/spire/cmd/spire-server/cli/federation/show.go`, `third_party/spire/cmd/spire-server/cli/federation/common.go`, `third_party/spire/cmd/spire-server/cli/federation/create.go`, `third_party/spire/cmd/spire-server/cli/federation/delete.go`; `third_party/spire/README.md`. Revisão `9dbd864e8923`; 2210 arquivos versionados; principais extensões: .go: 1230, (sem extensão): 371, .conf: 144, .md: 136.

#### ECO-21 ? keycloak

Donos: Selo; composicao: Codex. Fonte ECO L360?373. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### keycloak — P2, serviço opcional

**Resolve.** Identity server com OIDC, SAML, SSO, MFA, realms e federação.

**Aproveitamento de código.** Reaproveitar login de humanos, acesso de amigos e integração OIDC/MFA.

**Encaixe arquitetural.** OIDCIdentityProvider autenticando humanos; autorizações granulares continuam no SENTRA.

**Sobreposições e limitações.** Serviço Java pesado para uso casual; opcional/hosted e não obrigatório no desktop.

**Aceite obrigatório.** Convidar amigo, multiworkspace, logout/revoke, MFA e troca de identidade.

**Evidências concretas.** `third_party/keycloak/js/apps/admin-ui/src/identity-providers/add/OIDCAuthentication.tsx`, `third_party/keycloak/federation/ldap/src/main/java/org/keycloak/storage/ldap/idm/store/IdentityStore.java`, `third_party/keycloak/federation/ldap/src/main/java/org/keycloak/storage/ldap/LDAPIdentityStoreRegistry.java`, `third_party/keycloak/federation/ldap/src/main/java/org/keycloak/storage/ldap/idm/store/ldap/LDAPIdentityStore.java`, `third_party/keycloak/server-spi-private/src/main/java/org/keycloak/broker/provider/UserAuthenticationIdentityProvider.java`; `third_party/keycloak/README.md`. Revisão `c7de391ae4d8`; 13514 arquivos versionados; principais extensões: .java: 8580, .png: 686, .adoc: 680, .tsx: 630.

#### ECO-22 ? openfga

Donos: Selo; composicao: Codex. Fonte ECO L374?387. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### openfga — P2, policy backend

**Resolve.** ReBAC de relacionamentos, tuplas e avaliação de permissões.

**Aproveitamento de código.** Modelar relações user/team/agent/workspace/machine e compartilhamento de recursos.

**Encaixe arquitetural.** ReBACPolicyBackend consultado pela autoridade única AuthorizationService.

**Sobreposições e limitações.** Evitar duas bases de grants com estados diferentes e cache incorreto.

**Aceite obrigatório.** Acesso transitivo, revogação, concorrência, negação fora de workspace.

**Evidências concretas.** `third_party/openfga/pkg/server/authorization_models.go`, `third_party/openfga/pkg/storage/storagewrappers/cached_datastore.go`, `third_party/openfga/pkg/storage/storagewrappers/bounded_datastore.go`, `third_party/openfga/pkg/storage/storagewrappers/sharediterator/shared_iterator_datastore.go`; `third_party/openfga/README.md`. Revisão `526995eb2024`; 578 arquivos versionados; principais extensões: .go: 476, .md: 22, .yaml: 19, .sql: 16.

#### ECO-23 ? opa

Donos: Selo; composicao: Codex. Fonte ECO L388?401. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### opa — P2, motor de política opcional

**Resolve.** Policy Decision Point com Rego, bundles e condições de contexto.

**Aproveitamento de código.** Reaproveitar regras versionadas para risco de operação, contexto de app, rede e escopo.

**Encaixe arquitetural.** PDP externo consultado pelo SENTRA para regras complexas, com fail-closed.

**Sobreposições e limitações.** OPA não cria identidade e não deve administrar grants em paralelo.

**Aceite obrigatório.** Rego test, negative policy, timeout, atualização e rollback de bundle.

**Evidências concretas.** `third_party/opa/docs/blog/2025-05-14-introducing-swift-opa-native-policy-evaluation-for-swift-d5136c8a662e.md`, `third_party/opa/bundle/bundle.go`, `third_party/opa/v1/ast/policy.go`, `third_party/opa/v1/bundle/file.go`, `third_party/opa/v1/bundle/hash.go`; `third_party/opa/README.md`. Revisão `4dcda5da919a`; 7910 arquivos versionados; principais extensões: .yaml: 2398, .stmt: 1914, .go: 1030, .json: 703.

#### ECO-24 ? tessera

Donos: Selo; composicao: Codex. Fonte ECO L404?417. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### tessera — P0, log de transparência

**Resolve.** Infrastructure de transparency log append-only e checkpoints/witness verificáveis.

**Aproveitamento de código.** Reaproveitar logs Merkle, provas de inclusão, checkpoints assinados e mecanismos de witness.

**Encaixe arquitetural.** AuditWitness externaliza hashes canônicos dos eventos SENTRA; guardar provas por Operation.

**Sobreposições e limitações.** Registro verificável não garante que todas as ações foram registradas ou que não houve side effects fora da plataforma.

**Aceite obrigatório.** Alterar/apagar evento e verificar prova offline; retenção e falha segura.

**Evidências concretas.** `third_party/tessera/witness.go`, `third_party/tessera/append_lifecycle.go`, `third_party/tessera/internal/witness/otel.go`, `third_party/tessera/internal/witness/client.go`, `third_party/tessera/cmd/mtc/log/internal/checkpoint/reader.go`; `third_party/tessera/README.md`. Revisão `0489e17418aa`; 295 arquivos versionados; principais extensões: .go: 152, (sem extensão): 43, .md: 34, .tf: 18.

#### ECO-25 ? immudb

Donos: Selo; composicao: Codex. Fonte ECO L418?431. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### immudb — P2, storage alternativo

**Resolve.** Banco verificável com provas criptográficas de registros e consistência.

**Aproveitamento de código.** Usar como backend opcional para event ledgers e checagem de integridade.

**Encaixe arquitetural.** AuditStorageAdapter opcional para trilha externa, com somente hashes/metadados sensíveis redigidos.

**Sobreposições e limitações.** Mais complexo que log merkle leve; verificar implicações de licença BSL se compartilhado.

**Aceite obrigatório.** Prova de escrita/leitura, prova inválida, interrupção e restauração.

**Evidências concretas.** `third_party/immudb/pkg/server/remote_storage.go`, `third_party/immudb/embedded/store/verification.go`, `third_party/immudb/embedded/ahtree/verification.go`, `third_party/immudb/pkg/verification/verification.go`, `third_party/immudb/embedded/appendable/remoteapp/remote_storage_reader.go`; `third_party/immudb/README.md`. Revisão `bfdce03649f5`; 1203 arquivos versionados; principais extensões: .go: 970, (sem extensão): 38, .md: 26, .sh: 18.

#### ECO-26 ? opentelemetry-collector

Donos: Selo; composicao: Codex. Fonte ECO L432?445. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### opentelemetry-collector — P1, telemetria

**Resolve.** Pipelines de traces, logs e métricas com receivers, processors e exporters.

**Aproveitamento de código.** Exportar sinais de brokers, machine runtimes, agentes e gateways; padronizar OTLP.

**Encaixe arquitetural.** TelemetryExporter SENTRA -> Collector com run_id/operation_id/device_id.

**Sobreposições e limitações.** Tracing operacional não é trilha auditável criptográfica; proteger conteúdos dos usuários.

**Aceite obrigatório.** Rastreio distribuído completo, redaction, quotas de logs e perda de collector.

**Evidências concretas.** `third_party/opentelemetry-collector/processor/memorylimiterprocessor/internal/mock_exporter.go`, `third_party/opentelemetry-collector/processor/memorylimiterprocessor/internal/mock_receiver.go`, `third_party/opentelemetry-collector/receiver/doc.go`, `third_party/opentelemetry-collector/exporter/README.md`, `third_party/opentelemetry-collector/pipeline/signal.go`; `third_party/opentelemetry-collector/README.md`. Revisão `cee245c32ca5`; 2860 arquivos versionados; principais extensões: .go: 1802, .yaml: 419, .md: 131, (sem extensão): 119.

#### ECO-27 ? langfuse

Donos: Selo; composicao: Codex. Fonte ECO L446?459. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### langfuse — P2, tracing opcional

**Resolve.** Tracing e avaliação de aplicações LLM, scores, custo e experimentos.

**Aproveitamento de código.** Dashboards por tarefa/modelo, spans de inferência e comparação de agentes.

**Encaixe arquitetural.** LLMTraceSink opcional correlacionando WorkItem ao provider turn.

**Sobreposições e limitações.** Custo efetivo, quota e hard stop pertencem ao SENTRA, não ao dashboard.

**Aceite obrigatório.** Observar falhas/custo sem registrar prompt secreto nem duplicar orçamento.

**Evidências concretas.** `third_party/langfuse/packages/shared/src/features/scores/interfaces/ingestion/validation.ts`, `third_party/langfuse/web/src/features/traces/fns/nodeScores.ts`, `third_party/langfuse/web/src/features/scores/lib/prepareTraceAnnotation.ts`, `third_party/langfuse/web/src/features/traces/hooks/useParsedObservation.ts`, `third_party/langfuse/web/src/features/traces/hooks/usePrefetchObservation.ts`; `third_party/langfuse/README.md`. Revisão `c106bb3d9453`; 6811 arquivos versionados; principais extensões: .ts: 3641, .tsx: 1849, .sql: 552, .md: 305.

#### ECO-28 ? grype

Donos: Selo, Vitra; composicao: Codex. Fonte ECO L460?473. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### grype — P1, scanner CI

**Resolve.** Varredura de CVEs em código, dependências, containers e SBOMs.

**Aproveitamento de código.** Integrar scan em CI e avaliação de snapshots de terceiros instaláveis.

**Encaixe arquitetural.** Release Gate analisa SBOM/artefato antes de instalar ferramenta externa.

**Sobreposições e limitações.** Não substitui threat modeling, análise de código nem execução isolada.

**Aceite obrigatório.** Scan executável/imagen Docker de teste, CVE threshold, relatório e exceções.

**Evidências concretas.** `third_party/grype/grype/vulnerability_matcher.go`, `third_party/grype/cmd/grype/cli/ui/handle_update_vulnerability_database.go`, `third_party/grype/grype/match/matcher.go`, `third_party/grype/grype/matcher/matchers.go`, `third_party/grype/grype/vulnerability/fix.go`; `third_party/grype/README.md`. Revisão `5dbdab183e88`; 1624 arquivos versionados; principais extensões: .go: 753, .json: 574, (sem extensão): 106, .yaml: 53.

#### ECO-29 ? xyflow

Donos: Prisma, Codex; composicao: Codex. Fonte ECO L476?489. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### xyflow — P2, referência UI

**Resolve.** Engine React Flow de nodes, edges, handles, zoom e ergonomia de grafos.

**Aproveitamento de código.** Extrair padrões de seleção, acessibilidade e performance para canvases grandes.

**Encaixe arquitetural.** Benchmark de interação UI versus renderer próprio; integrar apenas se melhorar e preservar física.

**Sobreposições e limitações.** Uma migração React inteira duplicaria interface e arriscaria estética e ConPTY/xterm.

**Aceite obrigatório.** 100 nós, 200 cabos, FPS, resize, zoom e keyboard a11y.

**Evidências concretas.** `third_party/xyflow/packages/svelte/src/lib/hooks/useNodesEdgesViewport.svelte.ts`, `third_party/xyflow/packages/react/src/hooks/useViewport.ts`, `third_party/xyflow/packages/react/src/hooks/useViewportSync.ts`, `third_party/xyflow/packages/react/src/hooks/useViewportHelper.ts`, `third_party/xyflow/packages/react/src/container/Viewport/index.tsx`; `third_party/xyflow/README.md`. Revisão `3d35b5731757`; 697 arquivos versionados; principais extensões: .ts: 253, .tsx: 198, .svelte: 128, .css: 27.

#### ECO-30 ? yjs

Donos: Tessela; composicao: Codex. Fonte ECO L490?503. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### yjs — P1, biblioteca CRDT

**Resolve.** CRDT para sincronizar alterações concorrentes entre clientes.

**Aproveitamento de código.** Replicar layout, notas, tamanho/posição de nós e cursores offline/online.

**Encaixe arquitetural.** CanvasSharedDocument recebe atualizações por workspace autorizado.

**Sobreposições e limitações.** CRDT não guarda grants, locks, WorkItems nem quotas.

**Aceite obrigatório.** Dois clientes, desconexão, merge, revogação e limites de payload.

**Evidências concretas.** `third_party/yjs/src/utils/updates.js`, `third_party/yjs/src/utils/encoding.js`, `third_party/yjs/src/utils/Transaction.js`, `third_party/yjs/src/utils/UpdateDecoder.js`, `third_party/yjs/src/utils/UpdateEncoder.js`; `third_party/yjs/README.md`. Revisão `d01eefc997cf`; 75 arquivos versionados; principais extensões: .js: 51, .md: 9, .json: 6, .yml: 4.

#### ECO-31 ? y-protocols

Donos: Tessela; composicao: Codex. Fonte ECO L504?517. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### y-protocols — P1, protocolo de presença

**Resolve.** Protocolos Yjs de sync, awareness e mensagem de autorização.

**Aproveitamento de código.** Usar presença/cursores, encode de updates e handshake eficiente.

**Encaixe arquitetural.** Módulo de presença de amigos/agentes no Canvas Web com servidor Hocuspocus.

**Sobreposições e limitações.** Awareness é sinalização efêmera e não política de autorização.

**Aceite obrigatório.** Stale clients, heartbeat, reconexão, erro de permissão e dados malformados.

**Evidências concretas.** `third_party/y-protocols/src/awareness.js`; `third_party/y-protocols/README.md`. Revisão `73b2ff75486c`; 13 arquivos versionados; principais extensões: .js: 5, .json: 4, (sem extensão): 2, .md: 2.

#### ECO-32 ? hocuspocus

Donos: Tessela; composicao: Codex. Fonte ECO L518?531. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### hocuspocus — P1, serviço colaborativo

**Resolve.** Servidor WebSocket Yjs com auth hooks, colaboração e provider.

**Aproveitamento de código.** Sincronização e persistência em tempo real do layout do Canvas sem reimplementar CRDT protocol.

**Encaixe arquitetural.** CanvasCollaborationService verifica principal/workspace em cada sessão e recebe atualizações Yjs.

**Sobreposições e limitações.** Não expor direto o estado autoritativo SENTRA em documentos CRDT.

**Aceite obrigatório.** E2E com dois amigos, colaboração simultânea, token revogado e offline sync.

**Evidências concretas.** `third_party/hocuspocus/packages/provider/src/HocuspocusProviderWebsocket.ts`, `third_party/hocuspocus/packages/provider/src/OutgoingMessages/AuthenticationMessage.ts`, `third_party/hocuspocus/packages/provider-react/src/HocuspocusProviderWebsocketComponent.tsx`, `third_party/hocuspocus/packages/server/README.md`, `third_party/hocuspocus/packages/provider/README.md`; `third_party/hocuspocus/README.md`. Revisão `ee7c6e123c3a`; 266 arquivos versionados; principais extensões: .ts: 163, .md: 39, .json: 24, .tsx: 15.

#### ECO-33 ? activepieces

Donos: Pulso, Lume; composicao: Codex. Fonte ECO L534?547. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### activepieces — P2, conector externo

**Resolve.** Motor de automações com peças para SaaS/APIs, trigger/ação, OAuth e webhook.

**Aproveitamento de código.** Adaptar conectores e catálogos de receitas para automações de trabalho pessoal.

**Encaixe arquitetural.** ConnectorExecutor aciona fluxo em serviço externo governado por WorkItem e approvals.

**Sobreposições e limitações.** Não duplicar scheduler/retry e controle de segredos em dois sistemas.

**Aceite obrigatório.** E2E webhook assinado, OAuth por usuário, aprovação para ação irreversível e dedupe.

**Evidências concretas.** `third_party/activepieces/packages/pieces/community/microsoft-copilot/src/lib/triggers/copilot-interaction-webhook.ts`, `third_party/activepieces/packages/pieces/community/knock/src/lib/actions/trigger-workflow.ts`, `third_party/activepieces/packages/pieces/community/feedhive/src/lib/actions/fire-workflow-trigger.ts`, `third_party/activepieces/packages/pieces/community/github/src/lib/actions/trigger-workflow-dispatch.ts`, `third_party/activepieces/packages/pieces/community/savvycal/src/lib/triggers/workflow-action-triggered.ts`; `third_party/activepieces/README.md`. Revisão `a9b86f6ed9e5`; 30020 arquivos versionados; principais extensões: .ts: 17001, .json: 10309, .md: 967, .tsx: 943.

#### ECO-34 ? rpaframework

Donos: Forja, Tessela; composicao: Codex. Fonte ECO L548?561. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### rpaframework — P2, extrair libs

**Resolve.** Bibliotecas Python de RPA para GUI, sites, documentos, Excel e automações repetitivas.

**Aproveitamento de código.** Reaproveitar tarefas específicas e bibliotecas Robot Framework/Python para fluxos determinísticos.

**Encaixe arquitetural.** RPAExecutor para sequências aprovadas dentro do sandbox Windows/Linux.

**Sobreposições e limitações.** Seletores frágeis e riscos de credencial; RPA não é arquitetura de agente.

**Aceite obrigatório.** Preencher formulário de teste, Excel/PDF mock, falha de UI, evidência e cancelamento.

**Evidências concretas.** `third_party/rpaframework/packages/main/src/RPA/Desktop/utils.py`, `third_party/rpaframework/packages/main/src/RPA/Browser/common.py`, `third_party/rpaframework/packages/windows/src/RPA/Windows/main.py`, `third_party/rpaframework/packages/main/src/RPA/Browser/Selenium.py`, `third_party/rpaframework/packages/main/src/RPA/Browser/__init__.py`; `third_party/rpaframework/README.rst`. Revisão `7a419fb7a7bd`; 704 arquivos versionados; principais extensões: .py: 250, .rst: 110, .jpg: 65, .robot: 39.

#### ECO-35 ? windows-agent-arena

Donos: Selo, Forja; composicao: Codex. Fonte ECO L564?577. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### windows-agent-arena — P1, benchmark

**Resolve.** Benchmark de execução de tarefas no Windows com aplicativos reais.

**Aproveitamento de código.** Criar suíte de aferição de agente e ambiente reproduzível para Machine Runtime.

**Encaixe arquitetural.** SENTRA BenchRunner executa tarefas em VM e reporta sucesso/latência/custo.

**Sobreposições e limitações.** Passar benchmark não certifica permissão, segurança ou robustez em ambiente não controlado.

**Aceite obrigatório.** Baseline repetível com 3 execuções, avaliações e evidência anexada.

**Evidências concretas.** `third_party/windows-agent-arena/src/win-arena-container/client/evaluation_examples_windows/create_json.py`, `third_party/windows-agent-arena/src/win-arena-container/client/desktop_env/evaluators/getters/windows_clock.py`; `third_party/windows-agent-arena/README.md`. Revisão `6d39ed88c545`; 514 arquivos versionados; principais extensões: .json: 314, .py: 127, .png: 19, .md: 11.

#### ECO-36 ? osworld-v2

Donos: Selo, Forja; composicao: Codex. Fonte ECO L578?591. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### osworld-v2 — P2, benchmark

**Resolve.** Benchmark de tarefas de computador multietapas em ambientes padronizados.

**Aproveitamento de código.** Medir eficácia de ações de interface, recuperação e impacto do contexto longo.

**Encaixe arquitetural.** Harness de benchmark externo para comparar WindowsUIA/Playwright/RPA e agent providers.

**Sobreposições e limitações.** Infraestrutura/VM grande; não testar em estação pessoal com dados reais.

**Aceite obrigatório.** Execuções isoladas com métricas e comparações por tarefa.

**Evidências concretas.** `third_party/osworld-v2/benchmark_releases/README.md`, `third_party/osworld-v2/docs/PUBLIC_EVALUATION_GUIDELINE.md`, `third_party/osworld-v2/mm_agents/anthropic/tools/computer.py`, `third_party/osworld-v2/docs/PUBLIC_EVALUATION_GUIDELINE_v2.1.md`, `third_party/osworld-v2/hybrid_agents/codex/evaluation_transport.py`; `third_party/osworld-v2/README.md`. Revisão `acdd3493808e`; 1256 arquivos versionados; principais extensões: .py: 642, .json: 407, .md: 75, .png: 46.

#### ECO-37 ? windowsworld

Donos: Selo, Forja; composicao: Codex. Fonte ECO L592?605. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

#### windowsworld — P1, benchmark

**Resolve.** Benchmark Windows multiaplicativo com tarefas empresariais e checkpoints.

**Aproveitamento de código.** Avaliação por etapas e objetivos finais, útil para agentes que trabalham entre aplicativos.

**Encaixe arquitetural.** Adaptador de AcceptanceSuite por WorkItem e operações de interface real.

**Sobreposições e limitações.** Depende de apps e imagens com configuração própria; pontuação não substitui auditoria.

**Aceite obrigatório.** Avaliar etapas intermediárias, falhas, retry seguro e resultados finais.

**Evidências concretas.** `third_party/windowsworld/desktop_env/evaluators/metrics/libreoffice.py`, `third_party/windowsworld/desktop_env/evaluators/README.md`, `third_party/windowsworld/desktop_env/evaluators/__init__.py`, `third_party/windowsworld/desktop_env/evaluators/getters/vlc.py`, `third_party/windowsworld/desktop_env/evaluators/metrics/pdf.py`; `third_party/windowsworld/README.md`. Revisão `fbccd464f94f`; 547 arquivos versionados; principais extensões: .py: 457, .md: 24, .txt: 21, .json: 17.

### Ecosystem_additional_37

#### REE-01 ? ufo

Donos: Forja, Selo, Nexo; composicao: Codex. Fonte REE L92?103. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 01. ufo

**Alinhamento anterior:** automação Windows e padrões Galaxy/Constellation continuam úteis. A decomposição em DAG se sobrepõe ao OMA; seu valor adicional deve estar na operação de aplicativos e na qualidade dos planos.

**Ampliar:** transformar execuções bem-sucedidas e malsucedidas em experiências recuperáveis; usar edição com histórico para revisar planos; aproveitar critérios de escolha de dispositivo por capacidade e carga como sugestões para o controlador SENTRA.

**Evidência:** [ExperienceSummarizer](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/ufo/ufo/experience/summarizer.py:165) cria documentos com metadados e índice vetorial; [CommandHistory](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/ufo/galaxy/constellation/editor/command_history.py:15) mantém undo/redo; [ConstellationManager](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/ufo/galaxy/constellation/orchestrator/constellation_manager.py:132) oferece estratégias de atribuição.

**Encaixe e limite:** acrescentar experiências à memória existente do SENTRA, com origem, escopo, resultado e validade. O carregamento FAISS do clone usa `allow_dangerous_deserialization=True`; esse trecho não deve ser transplantado como importador de memória externa. Undo de plano não desfaz ações já executadas em aplicativos.

**Entrega verificável:** uma segunda tarefa recupera uma experiência pertinente e mostra sua origem; uma experiência obsoleta não é usada; edição do plano gera revisão sem repetir efeitos anteriores.

#### REE-02 ? openhands

Donos: Lume, Prisma, Nexo; composicao: Codex. Fonte REE L104?115. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 02. openhands

**Alinhamento anterior:** aproveitar UX de agentes, conversas, arquivos e ações continua adequado. A aplicação inteira exigiria outra pilha de frontend e estados paralelos.

**Ampliar:** recuperação de eventos após reconexão, representação de relações entre conversas e indicação de backends que falham repetidamente. Isso melhora o Canvas e as sessões existentes sem exigir sua substituição.

**Evidência:** [session-seq-cursor.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands/src/utils/session-seq-cursor.ts:1) trata gaps e replay de sequências; [health-store.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands/src/api/backend-registry/health-store.ts:46) conta falhas e desabilita probes; [child-conversation-launch.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands/src/services/child-conversation-launch.ts) mantém metadados de lançamento e relação com conversas.

**Encaixe e limite:** adaptar cursor e deduplicação ao journal do SENTRA; relações pai/filho precisam continuar em Run/WorkItem/Chat no backend. `localStorage` pode guardar preferências de UI, mas não ser o registro durável de lançamentos.

**Entrega verificável:** derrubar a conexão durante eventos fora de ordem; reabrir o Canvas e recuperar todos os eventos persistidos sem duplicar mensagem nem lançar outro agente.

#### REE-03 ? openhands-agent-sdk

Donos: Lume, Rastro, Nexo; composicao: Codex. Fonte REE L116?127. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 03. openhands-agent-sdk

**Alinhamento anterior:** usar provider e eventos tipados é correto, mas o SDK oferece mais do que uma conexão com Agent Server. Os adapters SENTRA atuais ainda não comprovam uma sessão no servidor externo.

**Ampliar:** compactação de contexto que preserva o system prompt e eventos iniciais; analisadores estruturados de comandos; política de confirmação por risco; recuperação da posse de sessão com geração e expiração.

**Evidência:** [LLMSummarizingCondenser](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py:54), [policy_rails.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/security/defense_in_depth/policy_rails.py:68) e [conversation_lease.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/conversation_lease.py:24).

**Encaixe e limite:** adotar esses padrões no gerenciamento de contexto e no provider. Manter transcrição original e referências às operações fora do resumo. A classificação de risco ajuda a decidir o fluxo; não concede capability. O lease do Agent Server é posse interna do processo externo, subordinada à admissão do SENTRA.

**Entrega verificável:** conversa longa resume contexto sem perder instruções ou pendências; servidor reinicia e reanexa à mesma sessão; uma tool call aponta para a Operation correspondente.

#### REE-04 ? agent-client-protocol

Donos: Lume; composicao: Codex. Fonte REE L128?139. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 04. agent-client-protocol

**Alinhamento anterior:** o subconjunto `session/new`, prompt, updates e cancel constitui um primeiro adapter, não a cobertura completa de um cliente de agentes.

**Ampliar:** resume, close, list e delete quando anunciados pelo agente; configuração de sessão/modelo; uso/custos reportados; conteúdo estruturado, terminais e arquivos; interação para coletar dados ou decisões do usuário.

**Evidência:** [agent.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/agent.rs:1228) contém lifecycle de sessão; [tool_call.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/tool_call.rs:18) explicita a diferença entre campo ausente, `null` e valor; [elicitation.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/elicitation.rs) contém os tipos de interação.

**Encaixe e limite:** negociar versão e capabilities antes de oferecer controles na UI. Não apagar dados recebidos ao aplicar um update parcial. Recursos experimentais do schema precisam continuar condicionados à revisão e à implementação do agente escolhido.

**Entrega verificável:** conectar um agente ACP externo, retomar sua sessão e configurar um recurso suportado; updates parciais preservam os campos antigos; recurso não anunciado não aparece como disponível.

#### REE-05 ? acp-registry

Donos: Lume, Vitra; composicao: Codex. Fonte REE L140?151. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 05. acp-registry

**Alinhamento anterior:** o catálogo deve continuar separado de instalação e execução. O descriptor local existente cobre somente parte do problema de entregar um agente utilizável.

**Ampliar:** seleção de distribuição por sistema/arquitetura, diferenças entre binary/npx/uvx, ambiente reservado, diagnóstico de instalação e encerramento da árvore de processos.

**Evidência:** [agent.schema.json](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/acp-registry/agent.schema.json:68) descreve variantes de distribuição; [registry_utils.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/acp-registry/.github/workflows/registry_utils.py:116) filtra variáveis reservadas e oferece helpers de grupos de subprocessos.

**Encaixe e limite:** evoluir o catálogo para responder “qual distribuição roda aqui e quais dependências faltam?”. O hash do clone não autentica automaticamente cada pacote ou binário baixado. Aproveitar verificação de artefatos e um plano de instalação com versão fixada. Não transformar atualização de catálogo em execução automática.

**Entrega verificável:** escolher a variante Windows correta, rejeitar descriptor incompatível e manter a configuração conhecida quando a nova instalação falhar.

#### REE-06 ? a2a

Donos: Lume; composicao: Codex. Fonte REE L152?163. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 06. a2a

**Alinhamento anterior:** converter tasks e artifacts para WorkItem e Artifact é adequado. O código local evoluiu para fixtures de transporte e SSE; continua faltando um par de agentes externos reais.

**Ampliar:** continuidade de tarefas que aguardam entrada, artefatos em chunks, Agent Card autenticado/estendido, capacidades opcionais e push notifications para tarefas demoradas.

**Evidência:** [a2a.proto](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/a2a/specification/a2a.proto:167) define Task/context; [TaskArtifactUpdateEvent](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/a2a/specification/a2a.proto:308) diferencia append e último chunk; [AgentCapabilities](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/a2a/specification/a2a.proto:412) anuncia streaming, push e extensões.

**Encaixe e limite:** persistir a correspondência entre IDs externos e internos. Chunks precisam formar um artefato completo verificável, com limites e proveniência. O protocolo e o schema não fornecem, sozinhos, um runtime A2A nem a autoridade de execução.

**Entrega verificável:** tarefa externa pausa por entrada e retoma; reconexão recupera o artefato completo sem duplicar chunks; callback de outra identidade não altera a tarefa.

#### REE-07 ? mcp-typescript-sdk

Donos: Lume, Pacto; composicao: Codex. Fonte REE L164?175. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 07. mcp-typescript-sdk

**Alinhamento anterior:** usar o SDK como cliente de tools/resources/prompts é correto. O `MCPTypescriptCompatClient` SENTRA é uma implementação Python para fixtures; isso não prova compatibilidade com o SDK TypeScript real.

**Ampliar:** negociação de revisão do protocolo, subscriptions de mudança de catálogo, interações `input_required`, validação de respostas e streams com reconexão. São recursos particularmente úteis para ferramentas dinâmicas e solicitações de dados durante uma chamada.

**Evidência:** [client.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/mcp-typescript-sdk/packages/client/src/client/client.ts:237), [protocol.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/mcp-typescript-sdk/packages/core-internal/src/shared/protocol.ts:1012) e [subscriptions.md](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/mcp-typescript-sdk/docs/clients/subscriptions.md:7).

**Encaixe e limite:** o snapshot distingue conexões de 2025 e a revisão 2026-07-28; também documenta depreciação de roots/sampling e Tasks como extensão em determinados caminhos. Implementar por revisão negociada, não por uma lista genérica de métodos. Auto-fulfilment e retry interno do cliente precisam respeitar a identidade da Operation e a admissão de efeitos.

**Entrega verificável:** cliente TS real conversa com servidor SENTRA, anuncia apenas recursos compatíveis e trata uma interação sem executar a mesma ação externa duas vezes.

#### REE-08 ? daytona

Donos: Forja, Pulso; composicao: Codex. Fonte REE L176?187. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 08. daytona

**Alinhamento anterior:** sandbox Linux, Computer Use e snapshots continuam valiosos. O adapter atual e o lifecycle separado são uma base, não prova de provisionamento operacional completo.

**Ampliar:** PTYs persistentes com conexão/resize/kill; sessões de comandos, entrada stdin e logs separados; previews de serviços; rede e políticas de auto-stop/archive/delete; volumes e metadados de ambiente.

**Evidência:** [process.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/daytona/libs/sdk-python/src/daytona/_sync/process.py:562) oferece lifecycle de PTY; [sandbox.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/daytona/libs/sdk-python/src/daytona/_sync/sandbox.py:79) modela volumes, intervalos e rede; [PTYManager](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/daytona/apps/daemon/pkg/toolbox/process/pty/manager.go:18) mantém sessões.

**Encaixe e limite:** tratar o terminal remoto como ProcessSession exibida pelo Canvas existente. Provisionamento, escrita stdin, preview e destruição são capacidades distintas. Snapshot de disco, backup de ambiente e estado de processo precisam ter garantias separadas; restore não autoriza repetir uma Operation incerta.

**Entrega verificável:** terminal persiste após desconexão da UI, logs retomam, rede segue o perfil escolhido e o encerramento remove apenas os recursos daquela execução.

#### REE-09 ? pywinauto

Donos: Forja; composicao: Codex. Fonte REE L188?199. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 09. pywinauto

**Alinhamento anterior:** UIA/Win32 e esperas semânticas são a opção mais direta para aplicativos Windows acessíveis. Os bindings SENTRA existentes ainda precisam de comprovação nos aplicativos alvo.

**Ampliar:** construir um repertório de seletores por aplicativo, esperar estado do controle em vez de tempos fixos, aproveitar cache de propriedades em observações grandes e combinar backend UIA/Win32 quando necessário.

**Evidência:** [timings.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/pywinauto/pywinauto/timings.py:309), [UIAElementInfo](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/pywinauto/pywinauto/windows/uia_element_info.py:104) e [Application.connect](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/pywinauto/pywinauto/windows/application.py:299).

**Encaixe e limite:** cache melhora observação, mas uma ação precisa revalidar elemento e processo. Retry de localizar/observar não equivale a retry de clique ou envio. PID restringe o alvo; não cria isolamento do sistema operacional. Interfaces sem árvore exigem outro método de observação.

**Entrega verificável:** fluxo de aplicativo com carregamento variável funciona com timeout limitado; controle recriado não recebe ação por referência antiga; resultado é confirmado semanticamente.

#### REE-10 ? hcsshim

Donos: Forja, Vitra; composicao: Codex. Fonte REE L200?211. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 10. hcsshim

**Alinhamento anterior:** manter como backend opcional para workloads Windows headless. Sua existência não fecha a necessidade de um desktop interativo isolado.

**Ampliar:** padrões de JobContainer, limites de recursos, associação de processos, obtenção de token de usuário, lifecycle HCS/uVM, mounts e limpeza de processos descendentes.

**Evidência:** [jobcontainer.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hcsshim/internal/jobcontainers/jobcontainer.go), [logon.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hcsshim/internal/jobcontainers/logon.go:98) e [create_wcow.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hcsshim/internal/uvm/create_wcow.go:63).

**Encaixe e limite:** o [binding SENTRA](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_executors/winhcs_boundary.py) tem create/status/terminate condicionados ao provider. Falta um provider real e diagnóstico de suporte do host. Grande parte do código upstream está em pacotes Go `internal`; o caminho prático é um serviço/shim com API estreita, não importar esses arquivos diretamente para Python.

**Entrega verificável:** workload headless inicia no host suportado, respeita limites e termina com seus filhos; uma VM com sessão GUI deve ser uma prova separada.

#### REE-11 ? gvisor

Donos: Forja, Vitra; composicao: Codex. Fonte REE L212?223. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 11. gvisor

**Alinhamento anterior:** reforço de sandbox Linux por runsc continua válido. Há agora uma fronteira local SENTRA para runsc, sem equivaler a uma implantação demonstrada.

**Ampliar:** perfis de acesso a filesystem, rede e capabilities; diagnóstico de syscalls/workloads incompatíveis; checkpoint/restore de processos quando aplicável.

**Evidência:** [config.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/gvisor/runsc/config/config.go:93), [checkpoint.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/gvisor/runsc/cmd/checkpoint.go:64) e [restore.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/gvisor/runsc/cmd/restore.go:69). O próprio clone descreve checkpoint/restore como experimental.

**Encaixe e limite:** perfil de runsc deve ser uma propriedade de execução, registrada com o ambiente e a imagem. Não transforma o Windows host em sandbox Linux nem garante recuperação transparente de sockets e efeitos externos. O arquivo de checkpoint é um artefato de ambiente com compatibilidade própria.

**Entrega verificável:** um workload Linux representativo passa com o perfil escolhido; tentativa fora do mount/rede é recusada; teste de restore declara exatamente quais estados foram recuperados.

#### REE-12 ? playwright-mcp

Donos: Forja, Brisa; composicao: Codex. Fonte REE L224?235. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 12. playwright-mcp

**Alinhamento anterior:** browser isolado e operações estruturadas continuam prioridade alta. O browser lab somente leitura do SENTRA não constitui ainda esse executor completo.

**Ampliar:** contextos isolados, configuração explícita de perfil, traces de sessão, evidência de rede/console e capacidades opcionais para PDF/visão/devtools; vincular referências de elementos à observação atual.

**Evidência:** [config.d.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/config.d.ts:130) anuncia capabilities e opções de evidência; [network config](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/config.d.ts:181) contém allow/block de origins. [index.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/index.js:18) e [package.json](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/package.json:39) mostram a dependência efetiva em Playwright.

**Encaixe e limite:** obter e validar o pacote exato que implementa as tools. Configuração de origem é uma camada de controle do browser, não prova de confinamento completo da rede. Trace é evidência de browser e pode conter conteúdo; requer armazenamento e escopo definidos pelo SENTRA.

**Entrega verificável:** navegar, interagir e gerar resultado em um contexto dedicado; coletar diagnóstico quando falha; descartar contexto sem afetar o perfil principal do usuário.

#### REE-13 ? guacamole-client

Donos: Forja, Prisma, Codex; composicao: Codex. Fonte REE L236?247. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 13. guacamole-client

**Alinhamento anterior:** viewer web de desktop remoto é adequado, mas o maior ganho adicional é uma interface de revisão do que aconteceu na sessão.

**Ampliar:** gravação reproduzível com play/pause/seek, estados de conexão, renderização de display e suporte a diferentes canais de entrada/saída. Uma timeline de sessão pode ligar imagem observada, ação e resultado ao journal do SENTRA.

**Evidência:** [SessionRecording.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/SessionRecording.js:1128) implementa controles de reprodução e keyframes; [Client.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Client.js:366) envia eventos de entrada e recebe streams.

**Encaixe e limite:** separar `session.view` de `session.control`, inclusive na UI. Reprodução de gravação deve ser somente visual; nunca reenviar as ações gravadas à máquina. O cliente precisa de um tunnel/proxy operacional; importar o JS não cria a sessão remota.

**Entrega verificável:** acompanhar uma sessão real e depois revisar um intervalo gravado, sem qualquer entrada ser enviada durante o playback.

#### REE-14 ? guacamole-server

Donos: Forja, Vitra; composicao: Codex. Fonte REE L248?259. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 14. guacamole-server

**Alinhamento anterior:** guacd como tradução RDP/VNC/SSH continua complementar aos executores e ao viewer.

**Ampliar:** gravação com escolha explícita de output/mouse/touch/teclado/clipboard; canais de filesystem, clipboard e áudio separados; lifecycle e metadados de conexão para diagnóstico.

**Evidência:** [recording.c](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-server/src/libguac/recording.c:42) permite selecionar o que registrar; [rdp.c](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-server/src/protocols/rdp/rdp.c:84) prepara redirecionamentos e plugins da sessão.

**Encaixe e limite:** projetar cada canal como capability do MachineSession. Uma conexão autorizada para visualizar não deve habilitar implicitamente upload, clipboard ou teclado. O proxy de tunnel precisa integrar o principal do SENTRA e não expor credenciais remotas ao frontend.

**Entrega verificável:** sessão somente visual rejeita entrada e transferência; gravação respeita os canais escolhidos; revogação encerra o tunnel e deixa recibo no journal.

#### REE-15 ? rustdesk

Donos: Forja, Vitra; composicao: Codex. Fonte REE L260?271. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 15. rustdesk

**Alinhamento anterior:** manter como provedor alternativo de controle remoto. Seu encaixe deve depender de um cenário que Guacamole ou o agente remoto existente não resolvam.

**Ampliar:** considerar caminhos de conexão para máquinas fora da rede local, permissões por sessão/canal, clipboard de arquivos, controle de privacidade e gravação. São possibilidades de provider, não motivos para incorporar o cliente inteiro.

**Evidência:** [connection.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rustdesk/src/server/connection.rs) contém login/permissões e canais; [clipboard_file.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rustdesk/src/clipboard_file.rs:4) traduz mensagens de clipboard; [record_upload.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rustdesk/src/hbbs_http/record_upload.rs:27) processa gravações.

**Encaixe e limite:** não presumir uma API pública e estável de embedding a partir desses módulos internos. Começar por um contrato de provider e uma prova de controle/revogação. Pareamento SENTRA deve continuar identificando a máquina e sua sessão.

**Entrega verificável:** mesma máquina é endereçada pelos IDs internos, sessão pode ser revogada pelo SENTRA e os canais permitidos são demonstrados. Se não houver esse cenário, adiar.

#### REE-16 ? langgraph

Donos: Pulso; composicao: Codex. Fonte REE L272?283. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 16. langgraph

**Alinhamento anterior:** subfluxo subordinado a WorkItem continua apropriado. Evitar outro scheduler global não exige descartar suas bibliotecas e padrões de estado.

**Ampliar:** checkpoints com parent e pending writes, etapas interrompíveis, recuperação seletiva, timeout por ausência de progresso e memória pesquisável por namespace com TTL.

**Evidência:** [checkpoint/base](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langgraph/libs/checkpoint/langgraph/checkpoint/base/__init__.py:140), [pregel/_retry.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langgraph/libs/langgraph/langgraph/pregel/_retry.py:215) e [store/base](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langgraph/libs/checkpoint/langgraph/store/base/__init__.py:203).

**Encaixe e limite:** memória e checkpoint podem complementar o contexto existente. Cada nó com efeito deve invocar o gateway SENTRA; um retry do grafo não pode repetir escrita externa por conta própria. Time travel/fork de estado computacional não desfaz efeitos no mundo.

**Entrega verificável:** subfluxo interrompe por entrada, retoma de checkpoint e preserva etapas concluídas; consulta de memória fica no namespace autorizado. Biblioteca é P1 quando resolve um subfluxo concreto; runtime adicional é P2.

#### REE-17 ? temporal

Donos: Pulso; composicao: Codex. Fonte REE L284?295. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 17. temporal

**Alinhamento anterior:** extrair semântica de execução durável antes de instalar o servidor é uma boa decisão para o modo individual.

**Ampliar:** distinguir falha transitória de não repetível, impor expiração e máximo de tentativas, representar atualizações admitidas versus concluídas e estudar evolução de workers de fluxos longos.

**Evidência:** [retry.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/temporal/service/history/workflow/retry.go:43) calcula retry a partir do tipo de falha e da política; [update/registry.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/temporal/service/history/workflow/update/registry.go:26) mantém updates admitidos e sua recuperação.

**Encaixe e limite:** o clone é principalmente o servidor Temporal; uma integração de aplicação também exige SDK/worker compatíveis. O SENTRA já tem Runs, leases e recuperação. Usar Temporal somente para subworkloads em que histórico determinístico e timers duráveis justifiquem a operação adicional.

**Entrega verificável:** falha não repetível termina sem retry; atividade com resposta incerta reconcilia antes de tentar outra vez; atualização de worker não altera o resultado de um fluxo em andamento.

#### REE-18 ? nats-server

Donos: Pulso, Selo, Codex; composicao: Codex. Fonte REE L296?307. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 18. nats-server

**Alinhamento anterior:** JetStream é adequado para transporte entre nós. No uso individual em uma máquina, um broker adicional precisa de uma razão operacional.

**Ampliar:** consumers duráveis com ack explícito, MaxAckPending, backoff e limite de redelivery; replay por posição/tempo; retenção e janela de deduplicação configuradas por classe de evento.

**Evidência:** [ConsumerConfig](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/nats-server/server/consumer.go:93) e [StreamConfig](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/nats-server/server/stream.go:56).

**Encaixe e limite:** publicar pela outbox e reconhecer consumo somente depois da persistência necessária no SENTRA. Deduplicação do broker tem janela finita; não substitui idempotência de Operation. Não transportar streams de terminal e comandos de execução com a mesma política de retenção indiscriminadamente.

**Entrega verificável:** consumer cai depois de receber uma mensagem, recupera e não repete o efeito; backlog permanece limitado e observável. Fila de falhas e reconciliação são decisões da aplicação.

#### REE-19 ? toolhive

Donos: Lume, Pacto; composicao: Codex. Fonte REE L308?319. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 19. toolhive

**Alinhamento anterior:** ToolHost, isolamento e autenticação são úteis. Há uma oportunidade adicional de reduzir o catálogo de ferramentas enviado ao modelo.

**Ampliar:** descoberta seletiva por descrição/keywords, métricas de economia de tokens, autenticação específica por backend e token exchange com audience/scope. Isso pode evoluir o catálogo MCP do SENTRA com menos consumo de contexto.

**Evidência:** [optimizer.FindTool](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/vmcp/optimizer/optimizer.go:379), [TokenExchangeStrategy](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/vmcp/auth/strategies/tokenexchange.go:99) e [OutgoingAuthRegistry](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/vmcp/auth/outgoing_registry.go:30).

**Encaixe e limite:** buscar dentro do conjunto de ferramentas já autorizado ao agente; similaridade não concede acesso. [PolicyGate](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/runner/policy_gate.go:11) controla criação de servidor e usa allow-all por padrão, portanto não comprova autorização por tool call. Parte da auditoria está delegada a `toolhive-core`, outra dependência a fixar.

**Entrega verificável:** agente encontra ferramentas pertinentes sem receber as não autorizadas; chamada e credencial ficam vinculadas à Operation; parar o host não perde o diagnóstico.

#### REE-20 ? spire

Donos: Selo; composicao: Codex. Fonte REE L320?331. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 20. spire

**Alinhamento anterior:** identidade de daemons/dispositivos é coerente. O ganho principal é identidade verificável de workloads, além de um identificador de máquina.

**Ampliar:** atestação de processo por seletores, SVID X.509/JWT de curta duração, renovação por subscriptions e bundles de confiança/federação quando houver mais de um domínio.

**Evidência:** [Workload API handler](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/spire/pkg/agent/endpoints/workload/handler.go:54), [workload attestor](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/spire/pkg/agent/attestor/workload/workload.go:27) e [X509 cache](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/spire/pkg/agent/manager/cache/x509_lru_cache.go:45).

**Encaixe e limite:** identidade autenticada se converte em Principal; a capability continua sendo uma decisão SENTRA. Validar atestador adequado ao Windows e ao ambiente real escolhido. Uma instalação local simples pode manter pareamento existente até ter múltiplos workers ou relays que justifiquem SPIRE.

**Entrega verificável:** worker renova credencial sem identidade instável; processo de outro escopo não obtém o SVID; certificado vencido não permite uma nova operação.

#### REE-21 ? keycloak

Donos: Selo; composicao: Codex. Fonte REE L332?343. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 21. keycloak

**Alinhamento anterior:** login OIDC opcional é apropriado para uso com outras pessoas. Para uma única identidade local, não é requisito para evoluir agentes e executores.

**Ampliar:** ciclo de sessão e logout, revogação de tokens, consentimentos e token exchange para uma audience específica. Isso resolve mais do que apenas verificar a assinatura de um JWT.

**Evidência:** [TokenRevocationEndpoint](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/keycloak/services/src/main/java/org/keycloak/protocol/oidc/endpoints/TokenRevocationEndpoint.java:62) e [StandardTokenExchangeProvider](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/keycloak/services/src/main/java/org/keycloak/protocol/oidc/tokenexchange/StandardTokenExchangeProvider.java:232).

**Encaixe e limite:** o verificador JWT local SENTRA não constitui ainda login/logout OIDC completo. Um token com assinatura válida pode continuar tecnicamente válido após uma mudança de sessão, conforme a estratégia escolhida; definir como revogação externa altera novas admissões internas e conexões abertas.

**Entrega verificável:** login cria Principal coerente; logout/revogação impede novas operações e trata sessões existentes; token de outra audience não é aceito como identidade SENTRA.

#### REE-22 ? openfga

Donos: Selo; composicao: Codex. Fonte REE L344?355. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 22. openfga

**Alinhamento anterior:** ReBAC como decisão consultada é útil quando surgem relações entre pessoas, projetos, máquinas e documentos. O veto local existente não é implantação OpenFGA.

**Ampliar:** `ListObjects` para montar um catálogo de recursos acessíveis, `ReadChanges` para invalidar projeções/caches, assertions para testar o modelo e consistência diferenciada para operações sensíveis.

**Evidência:** [list_objects.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openfga/pkg/server/commands/list_objects.go:86), [read_changes.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openfga/pkg/server/commands/read_changes.go:19) e [check_command.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openfga/pkg/server/commands/check_command.go:44).

**Encaixe e limite:** navegar recursos permitidos melhora a UX, mas listagem não substitui autorização da ação. Fixar versão do modelo de relações e registrar a decisão consultada. Não usar contextual tuples fornecidas pelo próprio agente como fonte independente de privilégios.

**Entrega verificável:** alteração de relação remove o recurso da descoberta e bloqueia a próxima ação; cache antigo não permite escrita. Adiar o serviço enquanto a autorização individual existente resolver o cenário.

#### REE-23 ? opa

Donos: Selo; composicao: Codex. Fonte REE L356?367. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 23. opa

**Alinhamento anterior:** PDP contextual opcional é adequado; o módulo local SENTRA já oferece uma fronteira de veto, sem equivaler a um OPA externo integrado.

**Ampliar:** políticas versionadas em bundles, ativação controlada, logs de decisão com revision/decision ID e mascaramento de campos. Regras contextualizadas podem ficar auditáveis e testáveis fora de condicionais espalhadas pelo código.

**Evidência:** [bundle/plugin.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opa/v1/plugins/bundle/plugin.go:444), [EventV1](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opa/v1/plugins/logs/plugin.go:49) e [sdk/opa.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opa/v1/sdk/opa.go:145).

**Encaixe e limite:** iniciar por políticas de rede, ambiente e classes de ação, subordinadas aos grants. Definir semântica para decisão indefinida, indisponibilidade e mudança de versão durante uma operação. Bundle/versionamento é aproveitável mesmo quando o motor completo permanecer opcional.

**Entrega verificável:** mesma entrada e mesma versão produzem a mesma decisão; troca inválida preserva a última política válida; log explica a regra aplicada sem conteúdo sensível desnecessário.

#### REE-24 ? tessera

Donos: Selo; composicao: Codex. Fonte REE L368?379. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 24. tessera

**Alinhamento anterior:** testemunhar heads de auditoria é uma boa opção de transparência. Para uso individual, eu reduziria sua prioridade de implantação frente a agentes, executores e recuperação operacional.

**Ampliar:** cliente verificador independente, provas de inclusão/consistência, checkpoints assinados, quorum explícito de witnesses e conservação de evidência de divergência.

**Evidência:** [witness.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/tessera/witness.go:29), [client/client.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/tessera/client/client.go:44) e [append_lifecycle.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/tessera/append_lifecycle.go).

**Encaixe e limite:** exportar digests/checkpoints pela outbox do ledger. Hash chain local e witness independente têm garantias diferentes. Quorum configurado como nenhum não entrega testemunho externo. Prova de inclusão demonstra que um registro foi incluído; não demonstra que todo efeito real foi registrado.

**Entrega verificável:** verificador com estado anterior detecta checkpoint incompatível; receipt aponta ao evento correto. A cobertura de efeitos precisa ser demonstrada pela instrumentação SENTRA.

#### REE-25 ? immudb

Donos: Selo; composicao: Codex. Fonte REE L380?391. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 25. immudb

**Alinhamento anterior:** storage verificável alternativo continua possível, mas sua adoção integral concorre com bancos e journals já existentes.

**Ampliar:** provas de inclusão e avanço linear, conservação de estado confiável no cliente/verificador e exportação de transações para recuperação/replicação.

**Evidência:** [verification.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/immudb/embedded/store/verification.go:28), [StateService](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/immudb/pkg/client/state/state_service.go:28) e [stream_replication.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/immudb/pkg/server/stream_replication.go:29).

**Encaixe e limite:** aproveitar o modelo de cliente que guarda o último estado confiável, inclusive para o audit local. Se a necessidade for apenas provar a cadeia existente, começar por um verificador/arquivo de checkpoints é mais simples. Replicar registros não prova que a restauração de todos os artefatos do SENTRA funciona.

**Entrega verificável:** cliente com checkpoint antigo detecta histórico incompatível; restauração recupera os registros previstos e compara o head. Escolher uma necessidade distinta antes de implantar immudb junto de Tessera.

#### REE-26 ? opentelemetry-collector

Donos: Selo; composicao: Codex. Fonte REE L392?403. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 26. opentelemetry-collector

**Alinhamento anterior:** exportação OTLP redigida continua adequada. O sink local atual é um ponto de integração inicial, não um pipeline operacional completo.

**Ampliar:** batching por tamanho/tempo, limite de cardinalidade, memory limiter, filas limitadas, retries e exportação desacoplada. Isso pode tornar o diagnóstico resistente a indisponibilidade sem bloquear a execução principal.

**Evidência:** [batchprocessor/config.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opentelemetry-collector/processor/batchprocessor/config.go:16), [queuebatch/config.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opentelemetry-collector/exporter/exporterhelper/internal/queuebatch/config.go:18) e [memorylimiter config](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opentelemetry-collector/processor/memorylimiterprocessor/config.go).

**Encaixe e limite:** correlacionar Run/WorkItem/Operation/Provider/Machine nos spans, sem transformar traces em ledger de autoridade. Fila persistente depende da storage extension configurada; o campo `StorageID` não garante persistência por si. Redação adicional e determinados exporters podem exigir componentes fora do clone core.

**Entrega verificável:** sink fica indisponível, o pipeline respeita limites e depois exporta conforme a retenção definida; diagnóstico mostra perda/fila sem fingir completude de auditoria.

#### REE-27 ? langfuse

Donos: Selo; composicao: Codex. Fonte REE L404?415. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 27. langfuse

**Alinhamento anterior:** tracing LLM e custos são úteis, mas limitar o projeto a esse papel deixa um dos seus maiores ganhos de fora: aprendizado por avaliação.

**Ampliar:** prompts com versão/labels/config, datasets com entrada e saída esperada, ligação entre dataset run e trace, scores numéricos/categóricos/booleanos/textuais e correções humanas.

**Evidência:** [prompts.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langfuse/packages/shared/src/domain/prompts.ts:5), [dataset-run-items.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langfuse/packages/shared/src/domain/dataset-run-items.ts:5) e [score validation](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langfuse/packages/shared/src/features/scores/interfaces/ingestion/validation.ts:8).

**Encaixe e limite:** converter tarefas pessoais repetidas em regressões do SENTRA, fixando prompt, modelo, ferramentas, ambiente e critério de resultado. Pode-se adotar primeiro o formato e um runner local; a implantação completa é uma decisão posterior. Scores externos auxiliam comparação, sem substituir o QualityGate nem contabilização autoritativa de orçamento.

**Entrega verificável:** comparar duas versões de prompt/provider no mesmo conjunto de casos, mostrando sucesso objetivo, custo, latência e regressões por tarefa.

#### REE-28 ? grype

Donos: Selo, Vitra; composicao: Codex. Fonte REE L416?427. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 28. grype

**Alinhamento anterior:** scanner de dependências/artefatos continua útil mesmo para uso pessoal. Corrigir a descrição: o objetivo é identificar pacotes e vulnerabilidades conhecidas; não é análise estática geral de cada linha do código.

**Ampliar:** registrar versões com correção disponível, motivo do match, validade da base e diferenças entre scans para orientar atualização de dependências.

**Evidência:** [Fix](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/grype/grype/vulnerability/fix.go:23), [Matcher](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/grype/grype/match/matcher.go:13) e [DBCheck](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/grype/cmd/grype/cli/commands/db_check.go:59).

**Encaixe e limite:** conectar execução real do binário ao parser SENTRA. A identificação de pacotes envolve Syft e formatos de inventário; essas dependências também precisam de versão e procedência registradas. Varredura do checkout não equivale à varredura do pacote/instalador final.

**Entrega verificável:** scan de um artefato conhecido produz relatório correlacionado ao seu digest; base ausente/obsoleta é diagnosticada; recomendação de atualização distingue vulnerabilidade corrigível de sem correção.

#### REE-29 ? xyflow

Donos: Prisma, Codex; composicao: Codex. Fonte REE L428?439. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 29. xyflow

**Alinhamento anterior:** extrair ergonomia/performance sem migrar todo o Canvas continua a melhor escolha. Existem algoritmos e padrões concretos para além do aspecto visual de nodes/edges.

**Ampliar:** renderizar somente nós visíveis, seleção e bounds de grafo, descoberta de vizinhos/arestas e descrição acessível com aria-live. Adaptar os princípios ao renderer e à física de cabos existentes.

**Evidência:** [useVisibleNodeIds.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/xyflow/packages/react/src/hooks/useVisibleNodeIds.ts:8), [graph.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/xyflow/packages/system/src/utils/graph.ts) e [A11yDescriptions](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/xyflow/packages/react/src/components/A11yDescriptions/index.tsx:26).

**Encaixe e limite:** o SENTRA já tem módulos locais de acessibilidade e cabos; verificar a ligação ao Canvas antes de reimplementá-los. Desmontar nó fora da viewport não deve destruir a ProcessSession nem perder estado de terminal. Desenho, física e sessão precisam ter lifecycles separados.

**Entrega verificável:** medir pan/zoom/seleção com 100 e 500 nós; esconder nó não encerra o processo; navegação por teclado encontra nós e anuncia mudanças relevantes.

#### REE-30 ? yjs

Donos: Tessela; composicao: Codex. Fonte REE L440?451. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 30. yjs

**Alinhamento anterior:** CRDT limitado à apresentação permanece correto. Há ganhos além de sincronizar coordenadas e notas.

**Ampliar:** undo/redo limitado à origem do usuário, posições relativas em texto colaborativo e sincronização por state vectors/diffs. Isso permite edição concorrente com histórico local e tráfego incremental.

**Evidência:** [UndoManager](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/yjs/src/utils/UndoManager.js:164), [RelativePosition](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/yjs/src/utils/RelativePosition.js:154) e [updates.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/yjs/src/utils/updates.js:178).

**Encaixe e limite:** o clone é `@y/y` 14 RC; a biblioteca atualmente usada pelo sidecar é `yjs` 13. Adotar primeiro o recurso equivalente na família já integrada, ou estudar uma migração explícita. Undo colaborativo não pode reverter grants, iniciar/encerrar Runs ou repetir execução.

**Entrega verificável:** dois clientes editam notas; desfazer a alteração de um não remove o trabalho do outro; reconexão transmite diferenças; snapshots existentes continuam legíveis na versão escolhida.

#### REE-31 ? y-protocols

Donos: Tessela; composicao: Codex. Fonte REE L452?463. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 31. y-protocols

**Alinhamento anterior:** sync e awareness devem permanecer separados de autorização. Presença não precisa virar estado durável do controlador.

**Ampliar:** expiração de presença, clocks de atualização, remoção de clientes desconectados e vínculos entre awareness client ID e sessão autenticada.

**Evidência:** [awareness.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/y-protocols/src/awareness.js:13) usa timeout e clocks; [sync.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/y-protocols/src/sync.js:38) define sync step 1/2 e updates.

**Encaixe e limite:** o clone usa `@y/protocols` e importa `@y/y`, diferente dos pacotes atuais do SENTRA. Awareness pode representar cursor/nome/status visual, mas “online” não demonstra que um agente está executando ou possui o lease. O módulo local `awareness_guard.mjs` já cobre parte do vínculo e da filtragem; falta comprovar isso no Canvas conectado.

**Entrega verificável:** presença expira e reaparece corretamente; cliente não publica estado de outro usuário; uma sessão revogada não permanece enviando awareness.

#### REE-32 ? hocuspocus

Donos: Tessela; composicao: Codex. Fonte REE L464?475. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 32. hocuspocus

**Alinhamento anterior:** sidecar colaborativo com callbacks de host continua adequado e já usa a biblioteca real em laboratório.

**Ampliar:** persistência por extensão Database, limites de conexão, reconexão e, somente quando houver múltiplas instâncias, propagação por Redis com coordenação de documentos.

**Evidência:** [Database.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hocuspocus/packages/extension-database/src/Database.ts:45), [Throttle](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hocuspocus/packages/extension-throttle/src/index.ts:3) e [Redis.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hocuspocus/packages/extension-redis/src/Redis.ts:78).

**Encaixe e limite:** persistência genérica upstream não substitui o precommit/CAS já construído no SENTRA. Redis locks de documentos não são leases de execução. O passo prioritário é ligar callbacks ao host e edição ao Canvas; adicionar Redis antes disso não fecha o fluxo.

**Entrega verificável:** dois clientes reais editam o Canvas, host recusa update inválido antes de publicar, reinício restaura documento e revogação é aplicada às conexões abertas.

#### REE-33 ? activepieces

Donos: Pulso, Lume; composicao: Codex. Fonte REE L476?487. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 33. activepieces

**Alinhamento anterior:** catálogo de conectores SaaS e automações é útil. Importar somente workflows completos de um servidor externo não é a única forma de aproveitamento.

**Ampliar:** reaproveitar o SDK de peças e conectores específicos; propriedades tipadas para gerar formulários; output schemas; hooks de enable/disable, renovação de webhook e dedupe de triggers.

**Evidência:** [action.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/activepieces/packages/pieces/framework/src/lib/action/action.ts:23), [trigger.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/activepieces/packages/pieces/framework/src/lib/trigger/trigger.ts:11) e [oauth2-prop.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/activepieces/packages/pieces/framework/src/lib/property/authentication/oauth2-prop.ts:38).

**Encaixe e limite:** escolher conectores usados de fato e hospedá-los por um executor Node subordinado, ou acionar serviço externo quando necessário. Contexto, storage e helpers do framework são dependências dos conectores; copiar só um arquivo de ação pode não bastar. Retry interno da peça precisa se alinhar à idempotência externa e ao SENTRA.

**Entrega verificável:** um trigger real cria apenas um WorkItem para eventos duplicados; uma ação usa credencial vinculada à conexão escolhida; desligar o trigger remove sua assinatura externa.

#### REE-34 ? rpaframework

Donos: Forja, Tessela; composicao: Codex. Fonte REE L488?499. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 34. rpaframework

**Alinhamento anterior:** bibliotecas pontuais Python são um ganho direto. A análise anterior deu mais destaque à GUI/browser do que às capacidades determinísticas de documentos.

**Ampliar:** leitura/escrita de Excel sem GUI, tabelas com filtros/agrupamento/conversão, extração/manipulação de PDFs e workflows que verificam seus próprios resultados. Priorizar isso antes de macros baseadas em coordenadas.

**Evidência:** [Excel/Files.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rpaframework/packages/main/src/RPA/Excel/Files.py:194), [Tables.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rpaframework/packages/main/src/RPA/Tables.py:772) e [PDF document.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rpaframework/packages/pdf/src/RPA/PDF/keywords/document.py:588).

**Encaixe e limite:** disponibilizar capacidades explícitas de transformação de arquivos, com escrita temporária e promoção do resultado validado. Excel Files distingue fórmula de valor armazenado; não presumir que editar uma fórmula recalcula o workbook. Extração de texto PDF também não garante OCR ou fidelidade visual.

**Entrega verificável:** tarefa transforma planilha/PDF conhecido e compara conteúdo esperado; falha preserva original; necessidade de recalcular ou renderizar aciona o backend apropriado.

#### REE-35 ? windows-agent-arena

Donos: Selo, Forja; composicao: Codex. Fonte REE L500?511. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 35. windows-agent-arena

**Alinhamento anterior:** benchmark Windows em VM continua útil, mas o clone também oferece um laboratório de observação para melhorar o executor.

**Ampliar:** comparação entre UIA, visão e observação mista; representação de elementos numerados na imagem; escolha entre janela e tela; harness de VM e captura de trajetória.

**Evidência:** [Navi agent](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windows-agent-arena/src/win-arena-container/client/mm_agents/navi/agent.py:74) anuncia origens de observação a11y/visão/mistas; [vm.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windows-agent-arena/src/win-arena-container/client/desktop_env/controllers/vm.py:8) gerencia conexão QMP.

**Encaixe e limite:** usar isso para comparar métodos e definir fallback do WindowsUIAExecutor. O adapter do SENTRA continua recebendo ações tipadas; não expor diretamente o executor de código arbitrário de benchmark ao produto. Modelos de visão/OCR e imagens de VM são dependências adicionais.

**Entrega verificável:** mesmo conjunto pequeno de tarefas é repetido com UIA e modo híbrido; diferenças de sucesso/latência são acompanhadas de evidência, versão do ambiente e reset reproduzível.

#### REE-36 ? osworld-v2

Donos: Selo, Forja; composicao: Codex. Fonte REE L512?523. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 36. osworld-v2

**Alinhamento anterior:** benchmark multietapas continua adequado. O maior reaproveitamento para o SENTRA pode estar no avaliador, sem importar todos os agentes da suíte.

**Ampliar:** composição de métricas com conjunção/short-circuit, resultado estruturado além do score, avaliação intermediária e backend de avaliador separado do agente executante.

**Evidência:** [generated_task_utils.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/osworld-v2/evaluation_examples/task_class/generated_task_utils.py:57), [backend/base.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/osworld-v2/desktop_env/evaluators/backends/base.py:66) e [lib_run_single.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/osworld-v2/lib_run_single.py:27).

**Encaixe e limite:** enriquecer AcceptanceSuite com verificadores objetivos e explicação do resultado. Avaliação por LLM pode ajudar quando necessária, mas é probabilística e deve ser marcada como tal. `postconfig` de avaliador pode alterar ambiente; medir em clone/snapshot ou registrar essa mutação separadamente.

**Entrega verificável:** tarefa apresenta score e evidência de cada critério; checkpoints de avaliação não alteram a conclusão por efeito colateral oculto; resultados se mantêm comparáveis entre providers.

#### REE-37 ? windowsworld

Donos: Selo, Forja; composicao: Codex. Fonte REE L524?535. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

### 37. windowsworld

**Alinhamento anterior:** tarefas Windows entre aplicativos e avaliação por etapas continuam valiosas. Também há verificadores diretamente reutilizáveis para artefatos de trabalho.

**Ampliar:** comparar tabelas/CSV e propriedades de documentos, conferir resultado final em arquivo, reset/snapshot do ambiente e explicar quais critérios foram satisfeitos.

**Evidência:** [metrics/table.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windowsworld/desktop_env/evaluators/metrics/table.py:239), [desktop_env.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windowsworld/desktop_env/desktop_env.py:469) e [getters/replay.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windowsworld/desktop_env/evaluators/getters/replay.py:4).

**Encaixe e limite:** adaptar os verificadores como funções puras sobre artefatos autorizados. O replay do clone constrói comandos pyautogui a partir de strings e inclui um TODO sobre selecionar a janela correta; não é um mecanismo pronto para repetir ações no host. Checkpoint de avaliação, snapshot de VM e recuperação de execução são conceitos diferentes.

**Entrega verificável:** workflow entre aplicativos termina com documento/planilha verificável, critérios por etapa e evidência final; falha no aplicativo é distinguida de falha no avaliador.

### Cross_domain_gaps_18

#### REE-GAP-01 ? Admissão e efeito externo ligados ponta a ponta

Donos: Lume; composicao: Codex. Fonte REE L542?542. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Admissão e efeito externo ligados ponta a ponta | ACP, A2A, MCP, ToolHive, SDK OpenHands | Ligar CentralDurableIntentAuthority, provider e verificação na fronteira do efeito; observar/reconciliar a mesma Operation |

#### REE-GAP-02 ? Sessão persistente de agente/terminal

Donos: Forja, Lume; composicao: Codex. Fonte REE L543?543. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Sessão persistente de agente/terminal | ACP, OpenHands SDK/UI, Daytona | Mapa durável de IDs, cursor, reattach e estados após perda de conexão; não recriar sessão por heurística de terminal |

#### REE-GAP-03 ? Desktop Windows isolado e interativo

Donos: Forja; composicao: Codex. Fonte REE L544?544. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Desktop Windows isolado e interativo | pywinauto, UFO, Arena, hcsshim | Provedor de VM/sessão compatível, ciclo de vida, arquivos, observação e execução reais; headless HCS não fecha essa entrega |

#### REE-GAP-04 ? Posse de foco/teclado/clipboard

Donos: Forja, Rastro; composicao: Codex. Fonte REE L545?545. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Posse de foco/teclado/clipboard | pywinauto, Guacamole, RustDesk | Serializar o recurso compartilhado e definir handoff humano/agente; validar alvo antes de cada ação |

#### REE-GAP-05 ? Recuperação de efeito incerto

Donos: Pulso, Forja; composicao: Codex. Fonte REE L546?546. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Recuperação de efeito incerto | Temporal, LangGraph, Daytona, NATS | Consultar estado externo, usar IDs idempotentes quando disponíveis e representar impossibilidade de saber; snapshot não resolve sozinho |

#### REE-GAP-06 ? Evidência e artefatos recuperáveis

Donos: Selo, Forja, Lume; composicao: Codex. Fonte REE L547?547. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Evidência e artefatos recuperáveis | A2A, Guacamole, benchmarks, immudb | Guardar bytes/referências/digests e proveniência; digest sem conteúdo não permite inspeção nem restauração |

#### REE-GAP-07 ? Memória útil sem perder instruções

Donos: Pulso, Forja, Lume, Rastro; composicao: Codex. Fonte REE L548?548. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Memória útil sem perder instruções | UFO, OpenHands SDK, LangGraph | Memória por escopo, origem, validade e resultado; compactação com transcrição preservada e avaliação de qualidade |

#### REE-GAP-08 ? Descoberta e compatibilidade de ferramentas

Donos: Lume, Vitra; composicao: Codex. Fonte REE L549?549. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Descoberta e compatibilidade de ferramentas | Registry, MCP SDK, ToolHive | Negociar versão/capability, validar schema e instalar distribuição correta; catálogo filtra o conjunto autorizado |

#### REE-GAP-09 ? Credenciais e revogação transversal

Donos: Selo; composicao: Codex. Fonte REE L550?550. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Credenciais e revogação transversal | Activepieces, Keycloak, SPIRE, ToolHive | Vincular conexão/segredo ao principal e operação, invalidar sessões e definir renovação; identidade não é grant |

#### REE-GAP-10 ? Eventos recuperáveis sem duplicar efeitos

Donos: Lume, Rastro; composicao: Codex. Fonte REE L551?551. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Eventos recuperáveis sem duplicar efeitos | OpenHands UI, NATS, MCP | Cursor/outbox/inbox, dedupe durável, limites de fila e revisão do estado projetado |

#### REE-GAP-11 ? Colaboração no Canvas real

Donos: Tessela, Prisma; composicao: Codex. Fonte REE L552?552. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Colaboração no Canvas real | Yjs, y-protocols, Hocuspocus | Compatibilidade de pacotes, callbacks do host, edição real, precommit, reautorização e recuperação |

#### REE-GAP-12 ? Canvas com muitos nós

Donos: Prisma; composicao: Codex. Fonte REE L553?553. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Canvas com muitos nós | xyflow | Viewport culling sem destruir terminais, limites da física e medição com carga real |

#### REE-GAP-13 ? Qualidade objetiva de tarefas

Donos: Selo, Forja; composicao: Codex. Fonte REE L554?554. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Qualidade objetiva de tarefas | Arena, OSWorld V2, WindowsWorld, Langfuse | Dataset pessoal, verificadores por artefato, reset e comparação de providers/prompts; incorporar ao QualityGate |

#### REE-GAP-14 ? Diagnóstico atravessando serviços

Donos: Selo; composicao: Codex. Fonte REE L555?555. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Diagnóstico atravessando serviços | OTel, Langfuse, ToolHive | Correlação de IDs, redação, política de filas e separação entre resultado operacional e sucesso de exportação |

#### REE-GAP-15 ? Backup e atualização recuperáveis

Donos: Selo, Pulso, Forja, Vitra; composicao: Codex. Fonte REE L556?556. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Backup e atualização recuperáveis | Daytona, immudb, Temporal como referências | Backup coordenado de SQLite, artefatos e configuração; migrações e teste de restauração do SENTRA inteiro |

#### REE-GAP-16 ? Entrega e instalação das integrações

Donos: Selo, Lume, Vitra; composicao: Codex. Fonte REE L557?557. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Entrega e instalação das integrações | Registry, Grype, ToolHive | Dependências transitivas fixadas, diagnóstico, serviços opcionais, instalação/remoção e teste de pacote final |

#### REE-GAP-17 ? Vários usuários/hosts, quando necessário

Donos: Nexo, Selo, Brisa; composicao: Codex. Fonte REE L558?558. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Vários usuários/hosts, quando necessário | NATS, SPIRE, Keycloak, OpenFGA, OPA | Modelo transacional e migrações para esse modo; o ControlStore atual aceita SQLite, não entrega backend Postgres |

#### REE-GAP-18 ? Independência da prova de auditoria

Donos: Selo; composicao: Codex. Fonte REE L559?559. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

| Independência da prova de auditoria | Tessera, immudb | Verificador com estado confiável e witnesses independentes; demonstrar a cobertura dos efeitos instrumentados |

### Connected_note_clauses

#### NOTE-L001 ? Todos os projetos já estão clonados, preciso que você organize varios agentes codex e OpenCode com muse spark 1.3 gratis xHigh, para implementarmos integralmente todas essas propos

Donos: Codex; composicao: Codex. Fonte NOTE L1?1. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Todos os projetos já estão clonados, preciso que você organize varios agentes codex e OpenCode com muse spark 1.3 gratis xHigh, para implementarmos integralmente todas essas propostas fique como orquestrador desses terminais, gere mais um para te ajudar na orquestração e divida todas as tarefas entre varios terminais, você está dentro do maestri: Já inicie os outros terminais com full permissions, para começarem de imediato o trabalho

#### NOTE-L003 ?  Foram três grandes levantamentos:

Donos: Codex; composicao: Codex. Fonte NOTE L3?3. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

 Foram três grandes levantamentos:

#### NOTE-L004 ? - OpenDots e Invisible Dots: 55 achados funcionais, comparados com 34 requisitos do SENTRA.

Donos: Codex; composicao: Codex. Fonte NOTE L4?4. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

- OpenDots e Invisible Dots: 55 achados funcionais, comparados com 34 requisitos do SENTRA.

#### NOTE-L005 ? - Chat On Steroids: 34 frentes e subfrentes de aproveitamento.

Donos: Codex; composicao: Codex. Fonte NOTE L5?5. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

- Chat On Steroids: 34 frentes e subfrentes de aproveitamento.

#### NOTE-L006 ? - Ecossistema open source: auditoria de 37 repositórios, incluindo OpenHands, UFO, Daytona, Temporal, XYFlow e outros.

Donos: Pulso, Forja, Lume; composicao: Codex. Fonte NOTE L6?6. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

- Ecossistema open source: auditoria de 37 repositórios, incluindo OpenHands, UFO, Daytona, Temporal, XYFlow e outros.

#### NOTE-L007 ? Vou separar os achados por projeto e explicar o benefício prático.

Donos: Codex; composicao: Codex. Fonte NOTE L7?7. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Vou separar os achados por projeto e explicar o benefício prático.

#### NOTE-L008 ? 1. OpenDots — três projetos pesquisados

Donos: Codex; composicao: Codex. Fonte NOTE L8?8. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

1. OpenDots — três projetos pesquisados

#### NOTE-L018 ? CopilotKit/OpenDots

Donos: Codex; composicao: Codex. Fonte NOTE L18?18. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

CopilotKit/OpenDots

#### NOTE-L019 ? Foco: experiência de trabalho, documentos e colaboração com agentes.

Donos: Tessela; composicao: Codex. Fonte NOTE L19?19. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Foco: experiência de trabalho, documentos e colaboração com agentes.

#### NOTE-L020 ? Funcionalidades identificadas: editor rico, salvamento automático, tratamento de conflitos, páginas versionadas, espaços de trabalho e feedback visual de ferramentas e tarefas.

Donos: Prisma; composicao: Codex. Fonte NOTE L20?20. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Funcionalidades identificadas: editor rico, salvamento automático, tratamento de conflitos, páginas versionadas, espaços de trabalho e feedback visual de ferramentas e tarefas.

#### NOTE-L021 ? No SENTRA: permitir que agentes editem documentos, mantenham versões e apresentem o progresso diretamente no Canvas.

Donos: Tessela, Prisma; composicao: Codex. Fonte NOTE L21?21. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

No SENTRA: permitir que agentes editem documentos, mantenham versões e apresentem o progresso diretamente no Canvas.

#### NOTE-L034 ? Anil-matcha/open-dots

Donos: Codex; composicao: Codex. Fonte NOTE L34?34. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Anil-matcha/open-dots

#### NOTE-L035 ? Foco: continuidade e execução de tarefas com agentes.

Donos: Rastro; composicao: Codex. Fonte NOTE L35?35. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Foco: continuidade e execução de tarefas com agentes.

#### NOTE-L036 ? Funcionalidades identificadas: agendamento persistente, recuperação de conversas, retomada de tarefas, supervisão humana e aprovações durante a execução.

Donos: Pulso; composicao: Codex. Fonte NOTE L36?36. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Funcionalidades identificadas: agendamento persistente, recuperação de conversas, retomada de tarefas, supervisão humana e aprovações durante a execução.

#### NOTE-L037 ? No SENTRA: fazer com que um agente consiga interromper uma tarefa, aguardar autorização e retomá-la posteriormente sem começar do zero.

Donos: Codex; composicao: Codex. Fonte NOTE L37?37. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

No SENTRA: fazer com que um agente consiga interromper uma tarefa, aguardar autorização e retomá-la posteriormente sem começar do zero.

#### NOTE-L050 ? feder-cr/invisible_dots

Donos: Codex; composicao: Codex. Fonte NOTE L50?50. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

feder-cr/invisible_dots

#### NOTE-L051 ? Foco: confiabilidade de execução e recuperação.

Donos: Codex; composicao: Codex. Fonte NOTE L51?51. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Foco: confiabilidade de execução e recuperação.

#### NOTE-L052 ? Funcionalidades identificadas: aprovações duráveis, outbox transacional, recibos de execução, isolamento entre host e executor e recuperação após interrupções.

Donos: Forja, Rastro; composicao: Codex. Fonte NOTE L52?52. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Funcionalidades identificadas: aprovações duráveis, outbox transacional, recibos de execução, isolamento entre host e executor e recuperação após interrupções.

#### NOTE-L053 ? No SENTRA: evitar mensagens ou ações duplicadas quando a conexão cai, preservando o estado verdadeiro da operação.

Donos: Codex; composicao: Codex. Fonte NOTE L53?53. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

No SENTRA: evitar mensagens ou ações duplicadas quando a conexão cai, preservando o estado verdadeiro da operação.

#### NOTE-L057 ? Observação: o relatório original foi um estudo de arquitetura. Os clones completos não ficaram disponíveis naquela sessão, portanto parte da avaliação utilizou fontes remotas. Os a

Donos: Codex; composicao: Codex. Fonte NOTE L57?57. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Observação: o relatório original foi um estudo de arquitetura. Os clones completos não ficaram disponíveis naquela sessão, portanto parte da avaliação utilizou fontes remotas. Os achados não equivalem a código já incorporado.

#### NOTE-L058 ? 2. Os achados mais úteis dos OpenDots

Donos: Codex; composicao: Codex. Fonte NOTE L58?58. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

2. Os achados mais úteis dos OpenDots

#### NOTE-L059 ? Funcionalidade	Benefício para o SENTRA	Prioridade sugerida

Donos: Codex; composicao: Codex. Fonte NOTE L59?59. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Funcionalidade	Benefício para o SENTRA	Prioridade sugerida

#### NOTE-L060 ? Editor de documentos integrado	Agentes trabalhando no mesmo documento	Alta

Donos: Tessela; composicao: Codex. Fonte NOTE L60?60. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Editor de documentos integrado	Agentes trabalhando no mesmo documento	Alta

#### NOTE-L061 ? Autosave com detecção de conflitos	Evita sobrescrita entre agentes	Alta

Donos: Tessela; composicao: Codex. Fonte NOTE L61?61. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Autosave com detecção de conflitos	Evita sobrescrita entre agentes	Alta

#### NOTE-L062 ? Histórico e versionamento de páginas	Recuperar versões anteriores	Média

Donos: Codex; composicao: Codex. Fonte NOTE L62?62. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Histórico e versionamento de páginas	Recuperar versões anteriores	Média

#### NOTE-L063 ? Workspaces persistentes	Organizar projetos, equipes e arquivos	Alta

Donos: Nexo; composicao: Codex. Fonte NOTE L63?63. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Workspaces persistentes	Organizar projetos, equipes e arquivos	Alta

#### NOTE-L064 ? Feedback de ferramentas em tempo real	Mostrar o que cada agente está fazendo	Alta

Donos: Codex; composicao: Codex. Fonte NOTE L64?64. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Feedback de ferramentas em tempo real	Mostrar o que cada agente está fazendo	Alta

#### NOTE-L065 ? Agendamento persistente	Executar tarefas futuras sem perder estado	Alta

Donos: Pulso; composicao: Codex. Fonte NOTE L65?65. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Agendamento persistente	Executar tarefas futuras sem perder estado	Alta

#### NOTE-L066 ? Retomada de conversas	Continuar trabalhos longos	Crítica

Donos: Codex; composicao: Codex. Fonte NOTE L66?66. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Retomada de conversas	Continuar trabalhos longos	Crítica

#### NOTE-L067 ? Aprovação humana durável	Aguardar consentimento mesmo após reinício	Crítica

Donos: Pacto; composicao: Codex. Fonte NOTE L67?67. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Aprovação humana durável	Aguardar consentimento mesmo após reinício	Crítica

#### NOTE-L068 ? Outbox transacional	Controlar o envio real das mensagens	Crítica

Donos: Rastro; composicao: Codex. Fonte NOTE L68?68. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Outbox transacional	Controlar o envio real das mensagens	Crítica

#### NOTE-L069 ? Recibos de execução	Comprovar se uma ação aconteceu	Crítica

Donos: Codex; composicao: Codex. Fonte NOTE L69?69. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Recibos de execução	Comprovar se uma ação aconteceu	Crítica

#### NOTE-L070 ? Isolamento host/executor	Impedir execução fora das permissões	Crítica

Donos: Forja; composicao: Codex. Fonte NOTE L70?70. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Isolamento host/executor	Impedir execução fora das permissões	Crítica

#### NOTE-L071 ? Recuperação de interrupções	Continuar após falhas sem repetir ações	Crítica

Donos: Codex; composicao: Codex. Fonte NOTE L71?71. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Recuperação de interrupções	Continuar após falhas sem repetir ações	Crítica

#### NOTE-L072 ? Essas funcionalidades seriam especialmente valiosas porque o SENTRA trabalha com múltiplos agentes, modelos Web, terminais e serviços simultaneamente.

Donos: Brisa; composicao: Codex. Fonte NOTE L72?72. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Essas funcionalidades seriam especialmente valiosas porque o SENTRA trabalha com múltiplos agentes, modelos Web, terminais e serviços simultaneamente.

#### NOTE-L073 ? 3. Outros projetos que encontramos e o que aproveitar

Donos: Codex; composicao: Codex. Fonte NOTE L73?73. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

3. Outros projetos que encontramos e o que aproveitar

#### NOTE-L074 ? A auditoria anterior foi mais ampla que os OpenDots. Estes foram alguns dos principais projetos e componentes avaliados:

Donos: Codex; composicao: Codex. Fonte NOTE L74?74. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

A auditoria anterior foi mais ampla que os OpenDots. Estes foram alguns dos principais projetos e componentes avaliados:

#### NOTE-L075 ? Projeto	O que encontramos de útil

Donos: Codex; composicao: Codex. Fonte NOTE L75?75. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Projeto	O que encontramos de útil

#### NOTE-L076 ? OpenHands	Interface de agentes com terminal, arquivos, navegador, conversas e execução visual

Donos: Lume, Prisma; composicao: Codex. Fonte NOTE L76?76. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

OpenHands	Interface de agentes com terminal, arquivos, navegador, conversas e execução visual

#### NOTE-L077 ? Microsoft UFO	Agentes capazes de operar aplicações Windows e coordenar ações em máquinas

Donos: Forja; composicao: Codex. Fonte NOTE L77?77. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Microsoft UFO	Agentes capazes de operar aplicações Windows e coordenar ações em máquinas

#### NOTE-L078 ? ACP	Comunicação padronizada entre clientes e agentes de diferentes fornecedores

Donos: Lume; composicao: Codex. Fonte NOTE L78?78. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

ACP	Comunicação padronizada entre clientes e agentes de diferentes fornecedores

#### NOTE-L079 ? A2A	Comunicação, delegação e troca de tarefas entre agentes

Donos: Lume; composicao: Codex. Fonte NOTE L79?79. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

A2A	Comunicação, delegação e troca de tarefas entre agentes

#### NOTE-L080 ? Daytona	Sandboxes, ambientes de execução isolados, snapshots e sessões recuperáveis

Donos: Forja; composicao: Codex. Fonte NOTE L80?80. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Daytona	Sandboxes, ambientes de execução isolados, snapshots e sessões recuperáveis

#### NOTE-L081 ? pywinauto	Automação de interfaces nativas do Windows

Donos: Forja; composicao: Codex. Fonte NOTE L81?81. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

pywinauto	Automação de interfaces nativas do Windows

#### NOTE-L082 ? Playwright MCP	Navegação e automação de interfaces Web

Donos: Codex; composicao: Codex. Fonte NOTE L82?82. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Playwright MCP	Navegação e automação de interfaces Web

#### NOTE-L083 ? XYFlow	Nós, conexões, zoom, viewport e interações visuais no Canvas

Donos: Prisma; composicao: Codex. Fonte NOTE L83?83. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

XYFlow	Nós, conexões, zoom, viewport e interações visuais no Canvas

#### NOTE-L084 ? Yjs e Hocuspocus	Colaboração em tempo real com sincronização e resolução de conflitos

Donos: Pulso, Tessela; composicao: Codex. Fonte NOTE L84?84. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Yjs e Hocuspocus	Colaboração em tempo real com sincronização e resolução de conflitos

#### NOTE-L085 ? Temporal	Workflows duráveis, retries controlados, recuperação e execução prolongada

Donos: Pulso; composicao: Codex. Fonte NOTE L85?85. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Temporal	Workflows duráveis, retries controlados, recuperação e execução prolongada

#### NOTE-L086 ? LangGraph	Fluxos com agentes, estados, checkpoints e intervenção humana

Donos: Pulso, Prisma; composicao: Codex. Fonte NOTE L86?86. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

LangGraph	Fluxos com agentes, estados, checkpoints e intervenção humana

#### NOTE-L087 ? NATS	Comunicação assíncrona e eventos entre serviços distribuídos

Donos: Pulso; composicao: Codex. Fonte NOTE L87?87. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

NATS	Comunicação assíncrona e eventos entre serviços distribuídos

#### NOTE-L088 ? ToolHive	Gerenciamento, execução e isolamento de servidores MCP

Donos: Codex; composicao: Codex. Fonte NOTE L88?88. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

ToolHive	Gerenciamento, execução e isolamento de servidores MCP

#### NOTE-L089 ? OPA e OpenFGA	Políticas centralizadas e controle granular de permissões

Donos: Selo, Tessela; composicao: Codex. Fonte NOTE L89?89. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

OPA e OpenFGA	Políticas centralizadas e controle granular de permissões

#### NOTE-L090 ? OpenTelemetry e Langfuse	Telemetria, rastreamento e diagnóstico de operações dos agentes

Donos: Selo; composicao: Codex. Fonte NOTE L90?90. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

OpenTelemetry e Langfuse	Telemetria, rastreamento e diagnóstico de operações dos agentes

#### NOTE-L091 ? Activepieces	Automações, conectores externos e workflows empresariais

Donos: Codex; composicao: Codex. Fonte NOTE L91?91. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Activepieces	Automações, conectores externos e workflows empresariais

#### NOTE-L092 ? RPA Framework	Automação de arquivos, planilhas, navegadores e processos corporativos

Donos: Codex; composicao: Codex. Fonte NOTE L92?92. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

RPA Framework	Automação de arquivos, planilhas, navegadores e processos corporativos

#### NOTE-L093 ? A auditoria considerou 37 repositórios, e não recomendou instalar todos como dependências obrigatórias. A ideia era selecionar componentes e padrões que realmente ampliassem o SENT

Donos: Vitra; composicao: Codex. Fonte NOTE L93?93. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

A auditoria considerou 37 repositórios, e não recomendou instalar todos como dependências obrigatórias. A ideia era selecionar componentes e padrões que realmente ampliassem o SENTRA.

#### NOTE-L094 ? 4. Chat On Steroids — descobertas especialmente importantes

Donos: Codex; composicao: Codex. Fonte NOTE L94?94. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

4. Chat On Steroids — descobertas especialmente importantes

#### NOTE-L095 ? Esse foi outro projeto estudado separadamente, e vários dos seus mecanismos se relacionam diretamente com os problemas que estamos resolvendo agora.

Donos: Codex; composicao: Codex. Fonte NOTE L95?95. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Esse foi outro projeto estudado separadamente, e vários dos seus mecanismos se relacionam diretamente com os problemas que estamos resolvendo agora.

#### NOTE-L096 ? Achado	O que representaria no SENTRA

Donos: Codex; composicao: Codex. Fonte NOTE L96?96. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Achado	O que representaria no SENTRA

#### NOTE-L097 ? Continuidade entre chats A → B	Transferir uma conversa sem perder a tarefa e a identidade do agente

Donos: Rastro; composicao: Codex. Fonte NOTE L97?97. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Continuidade entre chats A → B	Transferir uma conversa sem perder a tarefa e a identidade do agente

#### NOTE-L098 ? Compact & Resume	Resumir o contexto e continuar sem repetir operações

Donos: Rastro; composicao: Codex. Fonte NOTE L98?98. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Compact & Resume	Resumir o contexto e continuar sem repetir operações

#### NOTE-L099 ? Outbox com confirmação	Saber se a mensagem foi enviada, recebida ou ficou incerta

Donos: Rastro; composicao: Codex. Fonte NOTE L99?99. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Outbox com confirmação	Saber se a mensagem foi enviada, recebida ou ficou incerta

#### NOTE-L100 ? Identidade MCP por conversa	Cada chamada de ferramenta vinculada ao chat de origem

Donos: Codex; composicao: Codex. Fonte NOTE L100?100. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Identidade MCP por conversa	Cada chamada de ferramenta vinculada ao chat de origem

#### NOTE-L101 ? Aprovação e bloqueio por chat	Autorizar ou negar ferramentas individualmente

Donos: Codex; composicao: Codex. Fonte NOTE L101?101. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Aprovação e bloqueio por chat	Autorizar ou negar ferramentas individualmente

#### NOTE-L102 ? Goal/Loop supervisionado	Agentes trabalhando por etapas até concluir um objetivo

Donos: Pulso; composicao: Codex. Fonte NOTE L102?102. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Goal/Loop supervisionado	Agentes trabalhando por etapas até concluir um objetivo

#### NOTE-L103 ? Catálogo real de modelos	Mostrar somente modelos e esforços disponíveis na conta autenticada

Donos: Brisa; composicao: Codex. Fonte NOTE L103?103. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Catálogo real de modelos	Mostrar somente modelos e esforços disponíveis na conta autenticada

#### NOTE-L104 ? Gerenciamento MCPB	Instalar, atualizar, auditar e remover plugins

Donos: Pacto, Vitra; composicao: Codex. Fonte NOTE L104?104. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Gerenciamento MCPB	Instalar, atualizar, auditar e remover plugins

#### NOTE-L105 ? Catálogo de Skills versionadas	Distribuir capacidades reutilizáveis com revisão e autorização

Donos: Pacto, Vitra; composicao: Codex. Fonte NOTE L105?105. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Catálogo de Skills versionadas	Distribuir capacidades reutilizáveis com revisão e autorização

#### NOTE-L106 ? Terminal persistente	Manter sessões e recuperar saídas sem perder o processo

Donos: Pulso; composicao: Codex. Fonte NOTE L106?106. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Terminal persistente	Manter sessões e recuperar saídas sem perder o processo

#### NOTE-L107 ? Histórico pesquisável	Recuperar mensagens e decisões anteriores

Donos: Codex; composicao: Codex. Fonte NOTE L107?107. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Histórico pesquisável	Recuperar mensagens e decisões anteriores

#### NOTE-L108 ? Anexos e visualizadores	Inspecionar PDFs, imagens, código e diferenças entre arquivos

Donos: Tessela, Rastro, Prisma; composicao: Codex. Fonte NOTE L108?108. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Anexos e visualizadores	Inspecionar PDFs, imagens, código e diferenças entre arquivos

#### NOTE-L109 ? Diagnósticos seguros	Gerar relatórios sem expor credenciais

Donos: Codex; composicao: Codex. Fonte NOTE L109?109. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Diagnósticos seguros	Gerar relatórios sem expor credenciais

#### NOTE-L110 ? Setup com reparo por etapa	Identificar problemas específicos da instalação e conexão

Donos: Vitra; composicao: Codex. Fonte NOTE L110?110. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Setup com reparo por etapa	Identificar problemas específicos da instalação e conexão

#### NOTE-L111 ? O estudo de Chat On Steroids resultou em 34 frentes e subfrentes. Algumas já possuem código correspondente no SENTRA, mas a integração e homologação não estavam completas no último

Donos: Codex; composicao: Codex. Fonte NOTE L111?111. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O estudo de Chat On Steroids resultou em 34 frentes e subfrentes. Algumas já possuem código correspondente no SENTRA, mas a integração e homologação não estavam completas no último checkpoint verificado.

#### NOTE-L112 ? 5. O que eu priorizaria agora no SENTRA

Donos: Codex; composicao: Codex. Fonte NOTE L112?112. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

5. O que eu priorizaria agora no SENTRA

#### NOTE-L113 ? Considerando todo esse material, esta seria minha ordem de valor para o produto:

Donos: Codex; composicao: Codex. Fonte NOTE L113?113. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Considerando todo esse material, esta seria minha ordem de valor para o produto:

#### NOTE-L115 ? 1. Confiabilidade absoluta das operações

Donos: Codex; composicao: Codex. Fonte NOTE L115?115. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

1. Confiabilidade absoluta das operações

#### NOTE-L116 ? Outbox, recibos, aprovação durável, recuperação de falhas e prevenção de efeitos duplicados. É a base para agentes realmente autônomos.

Donos: Rastro; composicao: Codex. Fonte NOTE L116?116. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Outbox, recibos, aprovação durável, recuperação de falhas e prevenção de efeitos duplicados. É a base para agentes realmente autônomos.

#### NOTE-L120 ? 2. Continuidade entre modelos e agentes

Donos: Rastro, Brisa; composicao: Codex. Fonte NOTE L120?120. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

2. Continuidade entre modelos e agentes

#### NOTE-L121 ? Um agente poder delegar, trocar de conversa, compactar contexto e continuar uma tarefa preservando Run, WorkItem e permissões.

Donos: Rastro; composicao: Codex. Fonte NOTE L121?121. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Um agente poder delegar, trocar de conversa, compactar contexto e continuar uma tarefa preservando Run, WorkItem e permissões.

#### NOTE-L125 ? 3. Canvas como ambiente completo de trabalho

Donos: Prisma; composicao: Codex. Fonte NOTE L125?125. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

3. Canvas como ambiente completo de trabalho

#### NOTE-L126 ? Documentos, código, PDFs, agentes, terminais e histórico na mesma interface, com edição e colaboração — mantendo o visual corporativo minimalista.

Donos: Tessela, Prisma; composicao: Codex. Fonte NOTE L126?126. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Documentos, código, PDFs, agentes, terminais e histórico na mesma interface, com edição e colaboração — mantendo o visual corporativo minimalista.

#### NOTE-L130 ? 4. Computer Use e máquinas supervisionadas

Donos: Forja; composicao: Codex. Fonte NOTE L130?130. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

4. Computer Use e máquinas supervisionadas

#### NOTE-L131 ? Integração de UFO, Daytona, Playwright e automação Windows para controlar aplicações reais sob permissões verificáveis.

Donos: Forja; composicao: Codex. Fonte NOTE L131?131. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Integração de UFO, Daytona, Playwright e automação Windows para controlar aplicações reais sob permissões verificáveis.

#### NOTE-L135 ? 5. Plugins, Skills e interoperabilidade

Donos: Pacto, Lume; composicao: Codex. Fonte NOTE L135?135. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

5. Plugins, Skills e interoperabilidade

#### NOTE-L136 ? MCPB, ACP, A2A e serviços externos com descoberta automática, isolamento e concessão explícita de capacidades.

Donos: Pacto, Lume; composicao: Codex. Fonte NOTE L136?136. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

MCPB, ACP, A2A e serviços externos com descoberta automática, isolamento e concessão explícita de capacidades.

#### NOTE-L140 ? 6. Automações e tarefas de longa duração

Donos: Codex; composicao: Codex. Fonte NOTE L140?140. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

6. Automações e tarefas de longa duração

#### NOTE-L141 ? Agendamento, workflows empresariais, retomada após reinício, supervisão e execução distribuída entre máquinas.

Donos: Pulso; composicao: Codex. Fonte NOTE L141?141. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Agendamento, workflows empresariais, retomada após reinício, supervisão e execução distribuída entre máquinas.

#### NOTE-L145 ? Onde está o relatório original do OpenDots?

Donos: Codex; composicao: Codex. Fonte NOTE L145?145. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Onde está o relatório original do OpenDots?

#### NOTE-L146 ? O Codex informou que entregou um documento de aproximadamente 105,9 KB, com 55 achados, neste caminho:

Donos: Tessela; composicao: Codex. Fonte NOTE L146?146. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O Codex informou que entregou um documento de aproximadamente 105,9 KB, com 55 achados, neste caminho:

#### NOTE-L147 ? C:\Users\vitor\OneDrive\Desktop\SENTRA_RESEARCH_OPENDOTS\SENTRA_OPEN_DOTS_RESEARCH.md

Donos: Codex; composicao: Codex. Fonte NOTE L147?147. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

C:\Users\vitor\OneDrive\Desktop\SENTRA_RESEARCH_OPENDOTS\SENTRA_OPEN_DOTS_RESEARCH.md

#### NOTE-L150 ? Não consegui ler esse arquivo separado integralmente nesta consulta; por isso a relação acima reúne os principais resultados recuperados da pesquisa e dos documentos do SENTRA, e n

Donos: Tessela; composicao: Codex. Fonte NOTE L150?150. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Não consegui ler esse arquivo separado integralmente nesta consulta; por isso a relação acima reúne os principais resultados recuperados da pesquisa e dos documentos do SENTRA, e não uma transcrição literal dos 55 itens.

#### NOTE-L151 ? Minha conclusão: o melhor aproveitamento não seria transformar o SENTRA em uma cópia do OpenDots, do OpenHands ou do Chat On Steroids. Seria incorporar seus melhores mecanismos ao 

Donos: Lume, Rastro, Prisma; composicao: Codex. Fonte NOTE L151?151. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Minha conclusão: o melhor aproveitamento não seria transformar o SENTRA em uma cópia do OpenDots, do OpenHands ou do Chat On Steroids. Seria incorporar seus melhores mecanismos ao Control Plane único do SENTRA, preservando seu Canvas próprio, a autorização centralizada e a continuidade entre agentes.

#### NOTE-L152 ? Esse é o caminho para termos um aplicativo que não apenas conecta modelos de IA, mas organiza, supervisiona e executa trabalhos complexos de forma persistente e verificável. 

Donos: Brisa; composicao: Codex. Fonte NOTE L152?152. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Esse é o caminho para termos um aplicativo que não apenas conecta modelos de IA, mas organiza, supervisiona e executa trabalhos complexos de forma persistente e verificável. 

#### NOTE-L169 ? Onde estão e quais são os documentos desses estudos que você usou para me listar todos esses achados, depois da implementação integral de todas as melhorias que listou o SENTRA vir

Donos: Tessela; composicao: Codex. Fonte NOTE L169?169. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Onde estão e quais são os documentos desses estudos que você usou para me listar todos esses achados, depois da implementação integral de todas as melhorias que listou o SENTRA vira o que?

#### NOTE-L182 ? Pensou por 2m 39s

Donos: Codex; composicao: Codex. Fonte NOTE L182?182. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Pensou por 2m 39s

#### NOTE-L189 ? Os estudos estão principalmente em duas pastas do seu computador: SENTRA\docs, onde ficam as auditorias de arquitetura e implementação, e SENTRA_RESEARCH_OPENDOTS, destinada à pesq

Donos: Codex; composicao: Codex. Fonte NOTE L189?189. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Os estudos estão principalmente em duas pastas do seu computador: SENTRA\docs, onde ficam as auditorias de arquitetura e implementação, e SENTRA_RESEARCH_OPENDOTS, destinada à pesquisa específica dos OpenDots.

#### NOTE-L190 ? Depois da implementação completa, integrada e homologada dessas melhorias, o SENTRA teria potencial para se tornar algo significativamente maior que um Canvas de agentes: uma plata

Donos: Prisma; composicao: Codex. Fonte NOTE L190?190. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Depois da implementação completa, integrada e homologada dessas melhorias, o SENTRA teria potencial para se tornar algo significativamente maior que um Canvas de agentes: uma plataforma operacional de inteligência artificial, automação e desenvolvimento autônomo, com uma interface central e diferentes agentes, computadores e serviços trabalhando de forma coordenada.

#### NOTE-L191 ? 1. Documentos originais dos estudos

Donos: Tessela; composicao: Codex. Fonte NOTE L191?191. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

1. Documentos originais dos estudos

#### NOTE-L192 ? Pasta principal dos relatórios

Donos: Codex; composicao: Codex. Fonte NOTE L192?192. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Pasta principal dos relatórios

#### NOTE-L194 ? Localização no Windows

Donos: Forja; composicao: Codex. Fonte NOTE L194?194. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Localização no Windows

#### NOTE-L195 ? C:\Users\vitor\OneDrive\Desktop\SENTRA\docs

Donos: Codex; composicao: Codex. Fonte NOTE L195?195. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

C:\Users\vitor\OneDrive\Desktop\SENTRA\docs

#### NOTE-L196 ?  Copiar caminho

Donos: Codex; composicao: Codex. Fonte NOTE L196?196. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

 Copiar caminho

#### NOTE-L199 ? Estes são os documentos mais importantes que identifiquei no repositório:

Donos: Tessela; composicao: Codex. Fonte NOTE L199?199. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Estes são os documentos mais importantes que identifiquei no repositório:

#### NOTE-L200 ? Documento	Conteúdo

Donos: Tessela; composicao: Codex. Fonte NOTE L200?200. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Documento	Conteúdo

#### NOTE-L201 ? SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md	Auditoria dos 37 repositórios: comparação de funcionalidades, arquivos de código, riscos, prioridades e integrações propostas

Donos: Codex; composicao: Codex. Fonte NOTE L201?201. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md	Auditoria dos 37 repositórios: comparação de funcionalidades, arquivos de código, riscos, prioridades e integrações propostas

#### NOTE-L202 ? SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md	Segunda análise dos 37 projetos, identificando oportunidades adicionais e lacunas de integração

Donos: Codex; composicao: Codex. Fonte NOTE L202?202. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md	Segunda análise dos 37 projetos, identificando oportunidades adicionais e lacunas de integração

#### NOTE-L203 ? SENTRA_THIRD_PARTY_REUSE_2026-10-08.md	Estudo inicial de reaproveitamento de bibliotecas, protocolos e serviços

Donos: Tessela; composicao: Codex. Fonte NOTE L203?203. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA_THIRD_PARTY_REUSE_2026-10-08.md	Estudo inicial de reaproveitamento de bibliotecas, protocolos e serviços

#### NOTE-L204 ? SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md	34 frentes e subfrentes: MCPB, Compact & Resume, outbox, modelos Web, Goal/Loop, Skills, editor e diagnósticos

Donos: Pulso, Pacto, Rastro, Brisa; composicao: Codex. Fonte NOTE L204?204. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md	34 frentes e subfrentes: MCPB, Compact & Resume, outbox, modelos Web, Goal/Loop, Skills, editor e diagnósticos

#### NOTE-L205 ? SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md	Matriz de absorção de componentes externos e critérios de integração

Donos: Codex; composicao: Codex. Fonte NOTE L205?205. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md	Matriz de absorção de componentes externos e critérios de integração

#### NOTE-L206 ? SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md	Situação das implementações, integrações ainda incompletas e testes pendentes

Donos: Codex; composicao: Codex. Fonte NOTE L206?206. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md	Situação das implementações, integrações ainda incompletas e testes pendentes

#### NOTE-L207 ? O relatório dos 37 repositórios é especialmente importante: reúne referências para UFO, OpenHands, Daytona, ACP, A2A, Temporal, LangGraph, XYFlow, Yjs, ToolHive, Activepieces, OPA,

Donos: Selo, Pulso, Tessela, Forja, Lume; composicao: Codex. Fonte NOTE L207?207. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O relatório dos 37 repositórios é especialmente importante: reúne referências para UFO, OpenHands, Daytona, ACP, A2A, Temporal, LangGraph, XYFlow, Yjs, ToolHive, Activepieces, OPA, OpenFGA e outros.

#### NOTE-L208 ? O documento de reavaliação também contém referências aos arquivos e trechos examinados no código-fonte original, além de registrar os pontos em que o SENTRA ainda não estava integr

Donos: Tessela; composicao: Codex. Fonte NOTE L208?208. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O documento de reavaliação também contém referências aos arquivos e trechos examinados no código-fonte original, além de registrar os pontos em que o SENTRA ainda não estava integrado.

#### NOTE-L209 ? 2. Documentos específicos dos OpenDots

Donos: Tessela; composicao: Codex. Fonte NOTE L209?209. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

2. Documentos específicos dos OpenDots

#### NOTE-L210 ? Pesquisa independente OpenDots

Donos: Codex; composicao: Codex. Fonte NOTE L210?210. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Pesquisa independente OpenDots

#### NOTE-L212 ? Relatório indicado pelo coordenador

Donos: Codex; composicao: Codex. Fonte NOTE L212?212. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Relatório indicado pelo coordenador

#### NOTE-L213 ? C:\Users\vitor\OneDrive\Desktop\SENTRA_RESEARCH_OPENDOTS\SENTRA_OPEN_DOTS_RESEARCH.md

Donos: Codex; composicao: Codex. Fonte NOTE L213?213. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

C:\Users\vitor\OneDrive\Desktop\SENTRA_RESEARCH_OPENDOTS\SENTRA_OPEN_DOTS_RESEARCH.md

#### NOTE-L214 ?  Copiar caminho

Donos: Codex; composicao: Codex. Fonte NOTE L214?214. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

 Copiar caminho

#### NOTE-L217 ? O Codex foi designado para investigar três repositórios:

Donos: Codex; composicao: Codex. Fonte NOTE L217?217. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O Codex foi designado para investigar três repositórios:

#### NOTE-L218 ? - CopilotKit/OpenDots

Donos: Codex; composicao: Codex. Fonte NOTE L218?218. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

- CopilotKit/OpenDots

#### NOTE-L219 ? - Anil-matcha/open-dots

Donos: Codex; composicao: Codex. Fonte NOTE L219?219. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

- Anil-matcha/open-dots

#### NOTE-L220 ? - feder-cr/invisible_dots

Donos: Codex; composicao: Codex. Fonte NOTE L220?220. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

- feder-cr/invisible_dots

#### NOTE-L221 ? Os documentos do SENTRA que registram e acompanham essa pesquisa são:

Donos: Tessela; composicao: Codex. Fonte NOTE L221?221. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Os documentos do SENTRA que registram e acompanham essa pesquisa são:

#### NOTE-L222 ? docs\SENTRA_COS_RETOMADA_7_FRENTES_OPEN_DOTS_2026-10-10.md

Donos: Codex; composicao: Codex. Fonte NOTE L222?222. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

docs\SENTRA_COS_RETOMADA_7_FRENTES_OPEN_DOTS_2026-10-10.md

#### NOTE-L223 ? docs\SENTRA_AUDITORIA_RETORNOS_R5_CODEX_2026-10-10.md

Donos: Codex; composicao: Codex. Fonte NOTE L223?223. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

docs\SENTRA_AUDITORIA_RETORNOS_R5_CODEX_2026-10-10.md

#### NOTE-L224 ? docs\SENTRA_COS_RODADA_6_FECHAMENTO_E_HOMOLOGACAO_2026-10-10.md

Donos: Codex; composicao: Codex. Fonte NOTE L224?224. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

docs\SENTRA_COS_RODADA_6_FECHAMENTO_E_HOMOLOGACAO_2026-10-10.md

#### NOTE-L225 ? Uma ressalva importante: consegui ler esses registros de coordenação, mas não o relatório independente SENTRA_OPEN_DOTS_RESEARCH.md diretamente. Portanto, a referência anterior a 5

Donos: Pulso, Tessela, Rastro; composicao: Codex. Fonte NOTE L225?225. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Uma ressalva importante: consegui ler esses registros de coordenação, mas não o relatório independente SENTRA_OPEN_DOTS_RESEARCH.md diretamente. Portanto, a referência anterior a 55 achados e a atribuição de funcionalidades específicas a cada um dos três OpenDots ainda precisam ser conferidas no relatório original. Os registros consultados confirmam hipóteses úteis sobre editor, salvamento automático, recibos, outbox, agendamento e recuperação de interrupções, mas não demonstram que tudo isso foi implementado.

#### NOTE-L226 ? Também encontrei duas cópias de conversas/relatórios anteriores disponíveis nesta conta:

Donos: Brisa; composicao: Codex. Fonte NOTE L226?226. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Também encontrei duas cópias de conversas/relatórios anteriores disponíveis nesta conta:

#### NOTE-L227 ? Markdown colado.mdResumo da clonagem e auditoria dos 37 repositórios do ecossistema SENTRA, com matriz de componentes aproveitáveis.Texto colado(6).txtHistórico da análise do Chat 

Donos: Codex; composicao: Codex. Fonte NOTE L227?227. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Markdown colado.mdResumo da clonagem e auditoria dos 37 repositórios do ecossistema SENTRA, com matriz de componentes aproveitáveis.Texto colado(6).txtHistórico da análise do Chat On Steroids, incluindo as 13 frentes iniciais e a ampliação para 34 frentes e subfrentes.

#### NOTE-L229 ? 3. Depois de implementar tudo, no que o SENTRA se transforma?

Donos: Codex; composicao: Codex. Fonte NOTE L229?229. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

3. Depois de implementar tudo, no que o SENTRA se transforma?

#### NOTE-L230 ? VISÃO DO PRODUTO

Donos: Codex; composicao: Codex. Fonte NOTE L230?230. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

VISÃO DO PRODUTO

#### NOTE-L231 ? SENTRA OS

Donos: Codex; composicao: Codex. Fonte NOTE L231?231. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA OS

#### NOTE-L232 ? Um ambiente operacional unificado para agentes de IA e automação.

Donos: Codex; composicao: Codex. Fonte NOTE L232?232. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Um ambiente operacional unificado para agentes de IA e automação.

#### NOTE-L234 ? A grande transformação seria passar de um aplicativo que conecta agentes e terminais para um sistema que recebe objetivos, organiza o trabalho, distribui tarefas, executa ações em 

Donos: Vitra; composicao: Codex. Fonte NOTE L234?234. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

A grande transformação seria passar de um aplicativo que conecta agentes e terminais para um sistema que recebe objetivos, organiza o trabalho, distribui tarefas, executa ações em ambientes autorizados e preserva o progresso até a conclusão.

#### NOTE-L235 ? A arquitetura resultante

Donos: Codex; composicao: Codex. Fonte NOTE L235?235. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

A arquitetura resultante

#### NOTE-L236 ? SENTRA Canvas + Desktop + CLI

Donos: Prisma; composicao: Codex. Fonte NOTE L236?236. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA Canvas + Desktop + CLI

#### NOTE-L237 ? Uma interface central para projetos, agentes, arquivos, terminais e aprovações

Donos: Codex; composicao: Codex. Fonte NOTE L237?237. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Uma interface central para projetos, agentes, arquivos, terminais e aprovações

#### NOTE-L240 ? SENTRA Control Plane

Donos: Codex; composicao: Codex. Fonte NOTE L240?240. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA Control Plane

#### NOTE-L241 ? Autoridade única de Runs, WorkItems, permissões, operações, recibos e recuperação

Donos: Codex; composicao: Codex. Fonte NOTE L241?241. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Autoridade única de Runs, WorkItems, permissões, operações, recibos e recuperação

#### NOTE-L244 ? Modelos e agentes

Donos: Brisa; composicao: Codex. Fonte NOTE L244?244. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Modelos e agentes

#### NOTE-L245 ? Codex, ChatGPT Web, Gemini e outros provedores integrados

Donos: Codex; composicao: Codex. Fonte NOTE L245?245. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Codex, ChatGPT Web, Gemini e outros provedores integrados

#### NOTE-L248 ? Execução

Donos: Codex; composicao: Codex. Fonte NOTE L248?248. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Execução

#### NOTE-L249 ? Windows, navegador, terminais, máquinas remotas e sandboxes

Donos: Forja; composicao: Codex. Fonte NOTE L249?249. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Windows, navegador, terminais, máquinas remotas e sandboxes

#### NOTE-L252 ? Automação

Donos: Codex; composicao: Codex. Fonte NOTE L252?252. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Automação

#### NOTE-L253 ? Workflows, RPA, agendamento e integração entre serviços

Donos: Pulso; composicao: Codex. Fonte NOTE L253?253. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Workflows, RPA, agendamento e integração entre serviços

#### NOTE-L256 ? Persistência

Donos: Codex; composicao: Codex. Fonte NOTE L256?256. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Persistência

#### NOTE-L257 ? Memória, histórico, versionamento, estado durável e auditoria

Donos: Codex; composicao: Codex. Fonte NOTE L257?257. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Memória, histórico, versionamento, estado durável e auditoria

#### NOTE-L262 ? Essa arquitetura permitiria desenvolver quatro capacidades principais:

Donos: Codex; composicao: Codex. Fonte NOTE L262?262. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Essa arquitetura permitiria desenvolver quatro capacidades principais:

#### NOTE-L272 ? Um ambiente de desenvolvimento com múltiplos agentes

Donos: Codex; composicao: Codex. Fonte NOTE L272?272. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Um ambiente de desenvolvimento com múltiplos agentes

#### NOTE-L273 ? Você descreve um sistema e o SENTRA coordena agentes para analisar requisitos, escrever código, executar testes, revisar alterações e preparar uma entrega. Cada agente trabalha em 

Donos: Codex; composicao: Codex. Fonte NOTE L273?273. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Você descreve um sistema e o SENTRA coordena agentes para analisar requisitos, escrever código, executar testes, revisar alterações e preparar uma entrega. Cada agente trabalha em seu escopo, com supervisão central e histórico de decisões.

#### NOTE-L286 ? Uma plataforma de automação de processos

Donos: Codex; composicao: Codex. Fonte NOTE L286?286. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Uma plataforma de automação de processos

#### NOTE-L287 ? Agentes poderiam operar aplicações Windows, preencher sistemas, tratar documentos, navegar em páginas e coordenar tarefas empresariais. Ações sensíveis exigiriam permissões e contr

Donos: Tessela, Forja; composicao: Codex. Fonte NOTE L287?287. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Agentes poderiam operar aplicações Windows, preencher sistemas, tratar documentos, navegar em páginas e coordenar tarefas empresariais. Ações sensíveis exigiriam permissões e controles adequados.

#### NOTE-L300 ? Um espaço de trabalho persistente e colaborativo

Donos: Codex; composicao: Codex. Fonte NOTE L300?300. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Um espaço de trabalho persistente e colaborativo

#### NOTE-L301 ? Documentos, código, PDFs, anexos, decisões e conversas permaneceriam associados ao mesmo projeto. Agentes poderiam continuar tarefas em sessões diferentes sem perder a identidade e

Donos: Tessela, Rastro; composicao: Codex. Fonte NOTE L301?301. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Documentos, código, PDFs, anexos, decisões e conversas permaneceriam associados ao mesmo projeto. Agentes poderiam continuar tarefas em sessões diferentes sem perder a identidade e o contexto essencial.

#### NOTE-L314 ? Um centro de comando para execução supervisionada

Donos: Codex; composicao: Codex. Fonte NOTE L314?314. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Um centro de comando para execução supervisionada

#### NOTE-L315 ? O SENTRA acompanharia tarefas em andamento, responsáveis, custos e limites, aprovações, falhas e resultados. Seria possível identificar o que foi concluído, o que está pendente e o

Donos: Codex; composicao: Codex. Fonte NOTE L315?315. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O SENTRA acompanharia tarefas em andamento, responsáveis, custos e limites, aprovações, falhas e resultados. Seria possível identificar o que foi concluído, o que está pendente e o que precisa de intervenção humana.

#### NOTE-L319 ? 4. Qual seria a diferença prática?

Donos: Codex; composicao: Codex. Fonte NOTE L319?319. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

4. Qual seria a diferença prática?

#### NOTE-L320 ? Imagine que você solicite:

Donos: Codex; composicao: Codex. Fonte NOTE L320?320. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Imagine que você solicite:

#### NOTE-L321 ? Desenvolva um sistema completo de RPA para uma empresa, com integração fiscal, interface de usuário, testes, segurança e documentação.

Donos: Tessela; composicao: Codex. Fonte NOTE L321?321. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Desenvolva um sistema completo de RPA para uma empresa, com integração fiscal, interface de usuário, testes, segurança e documentação.

#### NOTE-L323 ? Um SENTRA plenamente implementado poderia estruturar o projeto, distribuir módulos entre agentes especializados, provisionar ambientes de execução, acompanhar as integrações, contr

Donos: Vitra; composicao: Codex. Fonte NOTE L323?323. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Um SENTRA plenamente implementado poderia estruturar o projeto, distribuir módulos entre agentes especializados, provisionar ambientes de execução, acompanhar as integrações, controlar permissões, consolidar resultados e preservar o estado da operação mesmo diante de interrupções.

#### NOTE-L324 ? O operador acompanharia o trabalho pelo Canvas, aprovando decisões relevantes e verificando evidências concretas de conclusão.

Donos: Prisma; composicao: Codex. Fonte NOTE L324?324. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O operador acompanharia o trabalho pelo Canvas, aprovando decisões relevantes e verificando evidências concretas de conclusão.

#### NOTE-L325 ? O ponto central não seria apenas ter muitos agentes conectados. Seria conseguir coordená-los de maneira confiável, com controle sobre o que cada um pode fazer e comprovação do que 

Donos: Codex; composicao: Codex. Fonte NOTE L325?325. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O ponto central não seria apenas ter muitos agentes conectados. Seria conseguir coordená-los de maneira confiável, com controle sobre o que cada um pode fazer e comprovação do que realmente fizeram.

#### NOTE-L326 ? 5. O que ainda separa essa visão de um produto terminado?

Donos: Codex; composicao: Codex. Fonte NOTE L326?326. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

5. O que ainda separa essa visão de um produto terminado?

#### NOTE-L327 ? Existe uma diferença fundamental entre:

Donos: Codex; composicao: Codex. Fonte NOTE L327?327. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Existe uma diferença fundamental entre:

#### NOTE-L328 ? Etapa	Significado

Donos: Codex; composicao: Codex. Fonte NOTE L328?328. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Etapa	Significado

#### NOTE-L329 ? Pesquisado	Foi identificada uma funcionalidade útil

Donos: Codex; composicao: Codex. Fonte NOTE L329?329. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Pesquisado	Foi identificada uma funcionalidade útil

#### NOTE-L330 ? Implementado	Existe código correspondente no SENTRA

Donos: Codex; composicao: Codex. Fonte NOTE L330?330. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Implementado	Existe código correspondente no SENTRA

#### NOTE-L331 ? Integrado	O código participa dos fluxos reais do produto

Donos: Prisma; composicao: Codex. Fonte NOTE L331?331. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Integrado	O código participa dos fluxos reais do produto

#### NOTE-L332 ? Homologado	Há testes e evidências de funcionamento confiável

Donos: Codex; composicao: Codex. Fonte NOTE L332?332. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Homologado	Há testes e evidências de funcionamento confiável

#### NOTE-L333 ? Pronto para distribuição	Instalador, segurança, recuperação e operação foram validados

Donos: Vitra; composicao: Codex. Fonte NOTE L333?333. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Pronto para distribuição	Instalador, segurança, recuperação e operação foram validados

#### NOTE-L334 ? Os relatórios mostram um volume considerável de funcionalidades e código desenvolvido. Entretanto, a integração integral de todas elas não foi comprovada, e a reconstrução bem-suce

Donos: Codex; composicao: Codex. Fonte NOTE L334?334. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Os relatórios mostram um volume considerável de funcionalidades e código desenvolvido. Entretanto, a integração integral de todas elas não foi comprovada, e a reconstrução bem-sucedida do Web Models, por exemplo, não equivale à homologação do SENTRA como um todo.

#### NOTE-L335 ? Para atingir a visão descrita, ainda seriam necessários testes ponta a ponta, segurança, recuperação de falhas, instalações limpas, compatibilidade com provedores, revisão de licen

Donos: Vitra; composicao: Codex. Fonte NOTE L335?335. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Para atingir a visão descrita, ainda seriam necessários testes ponta a ponta, segurança, recuperação de falhas, instalações limpas, compatibilidade com provedores, revisão de licenças e validação das capacidades distribuídas.

#### NOTE-L337 ? Minha avaliação: concluídas essas etapas, o SENTRA poderia ser apresentado como um Agentic Operating Environment — um ambiente operacional de agentes de IA — reunindo desenvolvimen

Donos: Codex; composicao: Codex. Fonte NOTE L337?337. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Minha avaliação: concluídas essas etapas, o SENTRA poderia ser apresentado como um Agentic Operating Environment — um ambiente operacional de agentes de IA — reunindo desenvolvimento de software, automação de computadores, orquestração, colaboração e execução persistente em uma única plataforma.

#### NOTE-L338 ? Não seria um sistema operacional que substitui o Windows, nem um produto que garante autonomia ilimitada. Seria uma camada operacional acima dele, capaz de coordenar diferentes tec

Donos: Forja; composicao: Codex. Fonte NOTE L338?338. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Não seria um sistema operacional que substitui o Windows, nem um produto que garante autonomia ilimitada. Seria uma camada operacional acima dele, capaz de coordenar diferentes tecnologias e agentes.

#### NOTE-L339 ? A maior oportunidade competitiva do SENTRA seria oferecer tudo isso sem transformar a experiência do usuário em dezenas de painéis técnicos: uma interface minimalista, sofisticada 

Donos: Codex; composicao: Codex. Fonte NOTE L339?339. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

A maior oportunidade competitiva do SENTRA seria oferecer tudo isso sem transformar a experiência do usuário em dezenas de painéis técnicos: uma interface minimalista, sofisticada e simples de operar, sustentada por uma arquitetura robusta por trás.

#### NOTE-L356 ? Eu gostei muito do visual do OpenDots, acredito que eu gostaria de implementar na verdade o nosso Canvas atual como uma seleção interna do OpenDots que pode ser gerenciada em uma c

Donos: Prisma; composicao: Codex. Fonte NOTE L356?356. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Eu gostei muito do visual do OpenDots, acredito que eu gostaria de implementar na verdade o nosso Canvas atual como uma seleção interna do OpenDots que pode ser gerenciada em uma conversa com um dots que cria e se liga a subagentes e ser algo visual como uma opção interna do proprio OpenDots, pois visualmente ele está muito bonito

#### NOTE-L369 ? Pensou por 1m 29s

Donos: Codex; composicao: Codex. Fonte NOTE L369?369. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Pensou por 1m 29s

#### NOTE-L376 ? Essa mudança de direção pode deixar o SENTRA muito mais interessante como produto. Em vez de o Canvas ser a interface principal de tudo, o SENTRA passaria a ter uma experiência cen

Donos: Prisma; composicao: Codex. Fonte NOTE L376?376. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Essa mudança de direção pode deixar o SENTRA muito mais interessante como produto. Em vez de o Canvas ser a interface principal de tudo, o SENTRA passaria a ter uma experiência centrada em conversas com Dots, e o Canvas se tornaria uma visualização avançada integrada a essa experiência.

#### NOTE-L377 ? Eu preservaria toda a engenharia que já construímos. O que mudaria radicalmente seria a maneira como o usuário interage com ela.

Donos: Codex; composicao: Codex. Fonte NOTE L377?377. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Eu preservaria toda a engenharia que já construímos. O que mudaria radicalmente seria a maneira como o usuário interage com ela.

#### NOTE-L378 ? O CopilotKit OpenDots já utiliza conceitos que combinam bastante com essa proposta: Spaces, Dots especializados, conversas contínuas, documentos, computadores e ferramentas incorpo

Donos: Nexo, Tessela; composicao: Codex. Fonte NOTE L378?378. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O CopilotKit OpenDots já utiliza conceitos que combinam bastante com essa proposta: Spaces, Dots especializados, conversas contínuas, documentos, computadores e ferramentas incorporadas à interface. 

#### NOTE-L380 ? GitHub

Donos: Codex; composicao: Codex. Fonte NOTE L380?380. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

GitHub

#### NOTE-L381 ? +1

Donos: Codex; composicao: Codex. Fonte NOTE L381?381. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

+1

#### NOTE-L385 ? Como eu estruturaria o novo SENTRA

Donos: Codex; composicao: Codex. Fonte NOTE L385?385. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Como eu estruturaria o novo SENTRA

#### NOTE-L386 ? SENTRA

Donos: Codex; composicao: Codex. Fonte NOTE L386?386. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

SENTRA

#### NOTE-L388 ? Conceito de navegação

Donos: Codex; composicao: Codex. Fonte NOTE L388?388. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Conceito de navegação

#### NOTE-L391 ? ESPAÇO DE TRABALHO

Donos: Codex; composicao: Codex. Fonte NOTE L391?391. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

ESPAÇO DE TRABALHO

#### NOTE-L392 ? Conversas

Donos: Codex; composicao: Codex. Fonte NOTE L392?392. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Conversas

#### NOTE-L394 ? Dots

Donos: Codex; composicao: Codex. Fonte NOTE L394?394. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Dots

#### NOTE-L396 ? Spaces

Donos: Nexo; composicao: Codex. Fonte NOTE L396?396. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Spaces

#### NOTE-L398 ? Canvas

Donos: Prisma; composicao: Codex. Fonte NOTE L398?398. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Canvas

#### NOTE-L400 ? Arquivos

Donos: Codex; composicao: Codex. Fonte NOTE L400?400. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Arquivos

#### NOTE-L404 ? Dot Coordenador

Donos: Nexo; composicao: Codex. Fonte NOTE L404?404. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Dot Coordenador

#### NOTE-L406 ? Conversa principal do projeto

Donos: Codex; composicao: Codex. Fonte NOTE L406?406. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Conversa principal do projeto

#### NOTE-L407 ? Crie uma equipe para desenvolver meu aplicativo.

Donos: Codex; composicao: Codex. Fonte NOTE L407?407. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Crie uma equipe para desenvolver meu aplicativo.

#### NOTE-L409 ? Frontend

Donos: Codex; composicao: Codex. Fonte NOTE L409?409. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Frontend

#### NOTE-L410 ? Backend

Donos: Codex; composicao: Codex. Fonte NOTE L410?410. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Backend

#### NOTE-L411 ? QA

Donos: Codex; composicao: Codex. Fonte NOTE L411?411. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

QA

#### NOTE-L414 ? Visualização Canvas

Donos: Prisma; composicao: Codex. Fonte NOTE L414?414. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Visualização Canvas

#### NOTE-L416 ? Equipe conectada visualmente, tarefas e progresso

Donos: Prisma; composicao: Codex. Fonte NOTE L416?416. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Equipe conectada visualmente, tarefas e progresso

#### NOTE-L422 ? Representação conceitual da organização, não uma captura ou implementação concluída.

Donos: Codex; composicao: Codex. Fonte NOTE L422?422. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Representação conceitual da organização, não uma captura ou implementação concluída.

#### NOTE-L423 ? O papel de cada parte

Donos: Codex; composicao: Codex. Fonte NOTE L423?423. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O papel de cada parte

#### NOTE-L424 ? Componente	Experiência desejada

Donos: Codex; composicao: Codex. Fonte NOTE L424?424. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Componente	Experiência desejada

#### NOTE-L425 ? Home	Uma página inicial elegante, com conversas, projetos e Dots recentes

Donos: Prisma; composicao: Codex. Fonte NOTE L425?425. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Home	Uma página inicial elegante, com conversas, projetos e Dots recentes

#### NOTE-L426 ? Dot Coordenador	Interface conversacional que planeja, cria equipes e supervisiona objetivos

Donos: Nexo; composicao: Codex. Fonte NOTE L426?426. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Dot Coordenador	Interface conversacional que planeja, cria equipes e supervisiona objetivos

#### NOTE-L427 ? Dots especializados	Agentes com seus próprios modelos, instruções, ferramentas, histórico e limites

Donos: Brisa; composicao: Codex. Fonte NOTE L427?427. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Dots especializados	Agentes com seus próprios modelos, instruções, ferramentas, histórico e limites

#### NOTE-L428 ? Spaces	Projetos, documentos, arquivos e contexto persistente

Donos: Nexo, Tessela; composicao: Codex. Fonte NOTE L428?428. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Spaces	Projetos, documentos, arquivos e contexto persistente

#### NOTE-L429 ? Canvas	Representação visual das relações entre agentes, máquinas, terminais e tarefas

Donos: Prisma; composicao: Codex. Fonte NOTE L429?429. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Canvas	Representação visual das relações entre agentes, máquinas, terminais e tarefas

#### NOTE-L430 ? Painel contextual	Arquivos, terminal, navegador, atividade e resultados sem sair da conversa

Donos: Codex; composicao: Codex. Fonte NOTE L430?430. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Painel contextual	Arquivos, terminal, navegador, atividade e resultados sem sair da conversa

#### NOTE-L431 ? A mudança mais importante: controlar o Canvas conversando

Donos: Prisma; composicao: Codex. Fonte NOTE L431?431. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

A mudança mais importante: controlar o Canvas conversando

#### NOTE-L432 ? Imagine escrever para um Dot:

Donos: Codex; composicao: Codex. Fonte NOTE L432?432. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Imagine escrever para um Dot:

#### NOTE-L433 ? Crie uma equipe de cinco agentes. Quero dois desenvolvedores, um arquiteto, um pesquisador e um responsável por testes. Organize as dependências entre eles e abra o Canvas para aco

Donos: Prisma; composicao: Codex. Fonte NOTE L433?433. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Crie uma equipe de cinco agentes. Quero dois desenvolvedores, um arquiteto, um pesquisador e um responsável por testes. Organize as dependências entre eles e abra o Canvas para acompanhar a execução.

#### NOTE-L435 ? O SENTRA executaria um fluxo supervisionado: o coordenador propõe a equipe, cria os agentes autorizados, atribui responsabilidades, registra as relações e apresenta o Canvas corres

Donos: Prisma; composicao: Codex. Fonte NOTE L435?435. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O SENTRA executaria um fluxo supervisionado: o coordenador propõe a equipe, cria os agentes autorizados, atribui responsabilidades, registra as relações e apresenta o Canvas correspondente.

#### NOTE-L436 ? Ao abrir a visualização, você veria os cinco Dots conectados, os trabalhos em andamento e os resultados em tempo real.

Donos: Prisma; composicao: Codex. Fonte NOTE L436?436. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Ao abrir a visualização, você veria os cinco Dots conectados, os trabalhos em andamento e os resultados em tempo real.

#### NOTE-L437 ? Poderia clicar em um Dot e conversar diretamente com ele. Ou voltar à conversa principal e pedir:

Donos: Codex; composicao: Codex. Fonte NOTE L437?437. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Poderia clicar em um Dot e conversar diretamente com ele. Ou voltar à conversa principal e pedir:

#### NOTE-L438 ? Pause o agente Backend, envie o resultado do pesquisador para o arquiteto e reorganize as próximas tarefas.

Donos: Codex; composicao: Codex. Fonte NOTE L438?438. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Pause o agente Backend, envie o resultado do pesquisador para o arquiteto e reorganize as próximas tarefas.

#### NOTE-L440 ? A interface conversacional e o Canvas exibiriam o mesmo estado verdadeiro, sem duplicação de agentes.

Donos: Prisma; composicao: Codex. Fonte NOTE L440?440. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

A interface conversacional e o Canvas exibiriam o mesmo estado verdadeiro, sem duplicação de agentes.

#### NOTE-L441 ? Como implementar sem destruir o SENTRA atual

Donos: Codex; composicao: Codex. Fonte NOTE L441?441. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Como implementar sem destruir o SENTRA atual

#### NOTE-L442 ? Já confirmei no código que o Canvas usa React Flow/XYFlow em sentra_canvas/desktop_ui/src/main.jsx, enquanto o runtime e a autoridade principal continuam nas classes Canvas, TaskRu

Donos: Prisma; composicao: Codex. Fonte NOTE L442?442. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Já confirmei no código que o Canvas usa React Flow/XYFlow em sentra_canvas/desktop_ui/src/main.jsx, enquanto o runtime e a autoridade principal continuam nas classes Canvas, TaskRuntime e ControlPlaneService.

#### NOTE-L443 ? Eu faria a migração em quatro etapas:

Donos: Codex; composicao: Codex. Fonte NOTE L443?443. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Eu faria a migração em quatro etapas:

#### NOTE-L444 ? 1. Nova interface principal: adaptar o design e os componentes adequados do OpenDots, com navegação por Dots, conversas e Spaces.

Donos: Nexo; composicao: Codex. Fonte NOTE L444?444. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

1. Nova interface principal: adaptar o design e os componentes adequados do OpenDots, com navegação por Dots, conversas e Spaces.

#### NOTE-L445 ? 2. Canvas como visualização interna: transformar o Canvas existente em um componente acessível por navegação, painel lateral ou expansão para tela inteira, preservando seus nós, co

Donos: Prisma; composicao: Codex. Fonte NOTE L445?445. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

2. Canvas como visualização interna: transformar o Canvas existente em um componente acessível por navegação, painel lateral ou expansão para tela inteira, preservando seus nós, conexões e terminais.

#### NOTE-L446 ? 3. Dot Coordenador real: conectar comandos conversacionais ao Control Plane para criar agentes, equipes, WorkItems, operações e relações, com permissões e confirmações.

Donos: Nexo; composicao: Codex. Fonte NOTE L446?446. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

3. Dot Coordenador real: conectar comandos conversacionais ao Control Plane para criar agentes, equipes, WorkItems, operações e relações, com permissões e confirmações.

#### NOTE-L447 ? 4. Integração e homologação: sincronizar chat e Canvas, preservar projetos existentes e validar reinicialização, cancelamento, concorrência, permissões e recuperação de falhas.

Donos: Pulso, Prisma; composicao: Codex. Fonte NOTE L447?447. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

4. Integração e homologação: sincronizar chat e Canvas, preservar projetos existentes e validar reinicialização, cancelamento, concorrência, permissões e recuperação de falhas.

#### NOTE-L448 ? Eu não executaria o backend do OpenDots como uma segunda autoridade dentro do SENTRA. Isso duplicaria estados e criaria conflitos. O SENTRA continuaria controlando as operações, en

Donos: Codex; composicao: Codex. Fonte NOTE L448?448. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Eu não executaria o backend do OpenDots como uma segunda autoridade dentro do SENTRA. Isso duplicaria estados e criaria conflitos. O SENTRA continuaria controlando as operações, enquanto a nova interface utilizaria seus serviços.

#### NOTE-L449 ? Há também uma questão de dependências: o CopilotKit/OpenDots é MIT, mas seu funcionamento conversacional utiliza CopilotKit Intelligence, com modalidades hospedada, avaliação local

Donos: Vitra, Prisma; composicao: Codex. Fonte NOTE L449?449. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Há também uma questão de dependências: o CopilotKit/OpenDots é MIT, mas seu funcionamento conversacional utiliza CopilotKit Intelligence, com modalidades hospedada, avaliação local e implantação própria licenciada. Para o SENTRA, prefiro aproveitar a experiência visual e os componentes compatíveis, sem tornar obrigatório um serviço externo adicional. E a delegação automática entre vários Dots precisaria ser implementada no SENTRA: o próprio OpenDots ainda a descreve como trabalho futuro. 

#### NOTE-L451 ? GitHub

Donos: Codex; composicao: Codex. Fonte NOTE L451?451. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

GitHub

#### NOTE-L452 ? +1

Donos: Codex; composicao: Codex. Fonte NOTE L452?452. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

+1

#### NOTE-L456 ? Minha proposta de identidade

Donos: Codex; composicao: Codex. Fonte NOTE L456?456. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Minha proposta de identidade

#### NOTE-L457 ? O nome continuaria SENTRA, e o usuário teria uma interface inicial extremamente refinada, parecida com o conceito do OpenDots, com elementos que aparecem apenas quando necessários.

Donos: Codex; composicao: Codex. Fonte NOTE L457?457. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O nome continuaria SENTRA, e o usuário teria uma interface inicial extremamente refinada, parecida com o conceito do OpenDots, com elementos que aparecem apenas quando necessários.

#### NOTE-L458 ? O Canvas deixaria de competir visualmente com a conversa. Ele seria o modo de orquestração visual: uma capacidade poderosa, disponível quando o usuário quisesse explorar ou control

Donos: Prisma; composicao: Codex. Fonte NOTE L458?458. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

O Canvas deixaria de competir visualmente com a conversa. Ele seria o modo de orquestração visual: uma capacidade poderosa, disponível quando o usuário quisesse explorar ou controlar a estrutura dos agentes.

#### NOTE-L459 ? Essa abordagem combina a experiência simples e bonita que você gostou com a engenharia mais profunda que o SENTRA já possui.

Donos: Codex; composicao: Codex. Fonte NOTE L459?459. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Essa abordagem combina a experiência simples e bonita que você gostou com a engenharia mais profunda que o SENTRA já possui.

#### NOTE-L461 ? Só preciso confirmar uma coisa antes de definir a migração visual: você está se referindo ao visual do [CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots) — aquele organi

Donos: Nexo, Prisma; composicao: Codex. Fonte NOTE L461?461. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Só preciso confirmar uma coisa antes de definir a migração visual: você está se referindo ao visual do [CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots) — aquele organizado em Spaces, Dots e conversas — ou ao [Open Dots de Anil-matcha](https://github.com/Anil-matcha/open-dots)? Como a fidelidade ao design é importante para você, quero usar exatamente a interface correta como referência.  

#### NOTE-L463 ? Referencia visual:

Donos: Prisma; composicao: Codex. Fonte NOTE L463?463. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

Referencia visual:

#### NOTE-L465 ? [CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots) 

Donos: Codex; composicao: Codex. Fonte NOTE L465?465. Estado: implementacao/integracao a confirmar; validacao adiada; nenhuma evidencia de homologacao.

[CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots) 

## Clausulas transversais, restricoes, criterios e contexto completos

As fontes abaixo sao preservadas integralmente para nao perder itens fora das matrizes: arquitetura, instalacao, licencas/proveniencia, limites, backup, multiusuario, criterios futuros e exclusoes. Cada linha nao vazia tem ID source:Lnumero em coverage.json. Texto historico permanece fonte, nao ordem para executar validacao agora. Ownership historico e substituido pela distribuicao atual em contracts.md.

### Fonte NOTE ? maestri://note/todos-os-projetos-ja-estao-clo

Todos os projetos já estão clonados, preciso que você organize varios agentes codex e OpenCode com muse spark 1.3 gratis xHigh, para implementarmos integralmente todas essas propostas fique como orquestrador desses terminais, gere mais um para te ajudar na orquestração e divida todas as tarefas entre varios terminais, você está dentro do maestri: Já inicie os outros terminais com full permissions, para começarem de imediato o trabalho

 Foram três grandes levantamentos:
- OpenDots e Invisible Dots: 55 achados funcionais, comparados com 34 requisitos do SENTRA.
- Chat On Steroids: 34 frentes e subfrentes de aproveitamento.
- Ecossistema open source: auditoria de 37 repositórios, incluindo OpenHands, UFO, Daytona, Temporal, XYFlow e outros.
Vou separar os achados por projeto e explicar o benefício prático.
1. OpenDots — três projetos pesquisados









CopilotKit/OpenDots
Foco: experiência de trabalho, documentos e colaboração com agentes.
Funcionalidades identificadas: editor rico, salvamento automático, tratamento de conflitos, páginas versionadas, espaços de trabalho e feedback visual de ferramentas e tarefas.
No SENTRA: permitir que agentes editem documentos, mantenham versões e apresentem o progresso diretamente no Canvas.












Anil-matcha/open-dots
Foco: continuidade e execução de tarefas com agentes.
Funcionalidades identificadas: agendamento persistente, recuperação de conversas, retomada de tarefas, supervisão humana e aprovações durante a execução.
No SENTRA: fazer com que um agente consiga interromper uma tarefa, aguardar autorização e retomá-la posteriormente sem começar do zero.












feder-cr/invisible_dots
Foco: confiabilidade de execução e recuperação.
Funcionalidades identificadas: aprovações duráveis, outbox transacional, recibos de execução, isolamento entre host e executor e recuperação após interrupções.
No SENTRA: evitar mensagens ou ações duplicadas quando a conexão cai, preservando o estado verdadeiro da operação.



Observação: o relatório original foi um estudo de arquitetura. Os clones completos não ficaram disponíveis naquela sessão, portanto parte da avaliação utilizou fontes remotas. Os achados não equivalem a código já incorporado.
2. Os achados mais úteis dos OpenDots
Funcionalidade	Benefício para o SENTRA	Prioridade sugerida
Editor de documentos integrado	Agentes trabalhando no mesmo documento	Alta
Autosave com detecção de conflitos	Evita sobrescrita entre agentes	Alta
Histórico e versionamento de páginas	Recuperar versões anteriores	Média
Workspaces persistentes	Organizar projetos, equipes e arquivos	Alta
Feedback de ferramentas em tempo real	Mostrar o que cada agente está fazendo	Alta
Agendamento persistente	Executar tarefas futuras sem perder estado	Alta
Retomada de conversas	Continuar trabalhos longos	Crítica
Aprovação humana durável	Aguardar consentimento mesmo após reinício	Crítica
Outbox transacional	Controlar o envio real das mensagens	Crítica
Recibos de execução	Comprovar se uma ação aconteceu	Crítica
Isolamento host/executor	Impedir execução fora das permissões	Crítica
Recuperação de interrupções	Continuar após falhas sem repetir ações	Crítica
Essas funcionalidades seriam especialmente valiosas porque o SENTRA trabalha com múltiplos agentes, modelos Web, terminais e serviços simultaneamente.
3. Outros projetos que encontramos e o que aproveitar
A auditoria anterior foi mais ampla que os OpenDots. Estes foram alguns dos principais projetos e componentes avaliados:
Projeto	O que encontramos de útil
OpenHands	Interface de agentes com terminal, arquivos, navegador, conversas e execução visual
Microsoft UFO	Agentes capazes de operar aplicações Windows e coordenar ações em máquinas
ACP	Comunicação padronizada entre clientes e agentes de diferentes fornecedores
A2A	Comunicação, delegação e troca de tarefas entre agentes
Daytona	Sandboxes, ambientes de execução isolados, snapshots e sessões recuperáveis
pywinauto	Automação de interfaces nativas do Windows
Playwright MCP	Navegação e automação de interfaces Web
XYFlow	Nós, conexões, zoom, viewport e interações visuais no Canvas
Yjs e Hocuspocus	Colaboração em tempo real com sincronização e resolução de conflitos
Temporal	Workflows duráveis, retries controlados, recuperação e execução prolongada
LangGraph	Fluxos com agentes, estados, checkpoints e intervenção humana
NATS	Comunicação assíncrona e eventos entre serviços distribuídos
ToolHive	Gerenciamento, execução e isolamento de servidores MCP
OPA e OpenFGA	Políticas centralizadas e controle granular de permissões
OpenTelemetry e Langfuse	Telemetria, rastreamento e diagnóstico de operações dos agentes
Activepieces	Automações, conectores externos e workflows empresariais
RPA Framework	Automação de arquivos, planilhas, navegadores e processos corporativos
A auditoria considerou 37 repositórios, e não recomendou instalar todos como dependências obrigatórias. A ideia era selecionar componentes e padrões que realmente ampliassem o SENTRA.
4. Chat On Steroids — descobertas especialmente importantes
Esse foi outro projeto estudado separadamente, e vários dos seus mecanismos se relacionam diretamente com os problemas que estamos resolvendo agora.
Achado	O que representaria no SENTRA
Continuidade entre chats A → B	Transferir uma conversa sem perder a tarefa e a identidade do agente
Compact & Resume	Resumir o contexto e continuar sem repetir operações
Outbox com confirmação	Saber se a mensagem foi enviada, recebida ou ficou incerta
Identidade MCP por conversa	Cada chamada de ferramenta vinculada ao chat de origem
Aprovação e bloqueio por chat	Autorizar ou negar ferramentas individualmente
Goal/Loop supervisionado	Agentes trabalhando por etapas até concluir um objetivo
Catálogo real de modelos	Mostrar somente modelos e esforços disponíveis na conta autenticada
Gerenciamento MCPB	Instalar, atualizar, auditar e remover plugins
Catálogo de Skills versionadas	Distribuir capacidades reutilizáveis com revisão e autorização
Terminal persistente	Manter sessões e recuperar saídas sem perder o processo
Histórico pesquisável	Recuperar mensagens e decisões anteriores
Anexos e visualizadores	Inspecionar PDFs, imagens, código e diferenças entre arquivos
Diagnósticos seguros	Gerar relatórios sem expor credenciais
Setup com reparo por etapa	Identificar problemas específicos da instalação e conexão
O estudo de Chat On Steroids resultou em 34 frentes e subfrentes. Algumas já possuem código correspondente no SENTRA, mas a integração e homologação não estavam completas no último checkpoint verificado.
5. O que eu priorizaria agora no SENTRA
Considerando todo esse material, esta seria minha ordem de valor para o produto:

1. Confiabilidade absoluta das operações
Outbox, recibos, aprovação durável, recuperação de falhas e prevenção de efeitos duplicados. É a base para agentes realmente autônomos.



2. Continuidade entre modelos e agentes
Um agente poder delegar, trocar de conversa, compactar contexto e continuar uma tarefa preservando Run, WorkItem e permissões.



3. Canvas como ambiente completo de trabalho
Documentos, código, PDFs, agentes, terminais e histórico na mesma interface, com edição e colaboração — mantendo o visual corporativo minimalista.



4. Computer Use e máquinas supervisionadas
Integração de UFO, Daytona, Playwright e automação Windows para controlar aplicações reais sob permissões verificáveis.



5. Plugins, Skills e interoperabilidade
MCPB, ACP, A2A e serviços externos com descoberta automática, isolamento e concessão explícita de capacidades.



6. Automações e tarefas de longa duração
Agendamento, workflows empresariais, retomada após reinício, supervisão e execução distribuída entre máquinas.



Onde está o relatório original do OpenDots?
O Codex informou que entregou um documento de aproximadamente 105,9 KB, com 55 achados, neste caminho:
C:\Users\vitor\OneDrive\Desktop\SENTRA_RESEARCH_OPENDOTS\SENTRA_OPEN_DOTS_RESEARCH.md


Não consegui ler esse arquivo separado integralmente nesta consulta; por isso a relação acima reúne os principais resultados recuperados da pesquisa e dos documentos do SENTRA, e não uma transcrição literal dos 55 itens.
Minha conclusão: o melhor aproveitamento não seria transformar o SENTRA em uma cópia do OpenDots, do OpenHands ou do Chat On Steroids. Seria incorporar seus melhores mecanismos ao Control Plane único do SENTRA, preservando seu Canvas próprio, a autorização centralizada e a continuidade entre agentes.
Esse é o caminho para termos um aplicativo que não apenas conecta modelos de IA, mas organiza, supervisiona e executa trabalhos complexos de forma persistente e verificável. 
















Onde estão e quais são os documentos desses estudos que você usou para me listar todos esses achados, depois da implementação integral de todas as melhorias que listou o SENTRA vira o que?












Pensou por 2m 39s






Os estudos estão principalmente em duas pastas do seu computador: SENTRA\docs, onde ficam as auditorias de arquitetura e implementação, e SENTRA_RESEARCH_OPENDOTS, destinada à pesquisa específica dos OpenDots.
Depois da implementação completa, integrada e homologada dessas melhorias, o SENTRA teria potencial para se tornar algo significativamente maior que um Canvas de agentes: uma plataforma operacional de inteligência artificial, automação e desenvolvimento autônomo, com uma interface central e diferentes agentes, computadores e serviços trabalhando de forma coordenada.
1. Documentos originais dos estudos
Pasta principal dos relatórios

Localização no Windows
C:\Users\vitor\OneDrive\Desktop\SENTRA\docs
 Copiar caminho


Estes são os documentos mais importantes que identifiquei no repositório:
Documento	Conteúdo
SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md	Auditoria dos 37 repositórios: comparação de funcionalidades, arquivos de código, riscos, prioridades e integrações propostas
SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md	Segunda análise dos 37 projetos, identificando oportunidades adicionais e lacunas de integração
SENTRA_THIRD_PARTY_REUSE_2026-10-08.md	Estudo inicial de reaproveitamento de bibliotecas, protocolos e serviços
SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md	34 frentes e subfrentes: MCPB, Compact & Resume, outbox, modelos Web, Goal/Loop, Skills, editor e diagnósticos
SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md	Matriz de absorção de componentes externos e critérios de integração
SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md	Situação das implementações, integrações ainda incompletas e testes pendentes
O relatório dos 37 repositórios é especialmente importante: reúne referências para UFO, OpenHands, Daytona, ACP, A2A, Temporal, LangGraph, XYFlow, Yjs, ToolHive, Activepieces, OPA, OpenFGA e outros.
O documento de reavaliação também contém referências aos arquivos e trechos examinados no código-fonte original, além de registrar os pontos em que o SENTRA ainda não estava integrado.
2. Documentos específicos dos OpenDots
Pesquisa independente OpenDots

Relatório indicado pelo coordenador
C:\Users\vitor\OneDrive\Desktop\SENTRA_RESEARCH_OPENDOTS\SENTRA_OPEN_DOTS_RESEARCH.md
 Copiar caminho


O Codex foi designado para investigar três repositórios:
- CopilotKit/OpenDots
- Anil-matcha/open-dots
- feder-cr/invisible_dots
Os documentos do SENTRA que registram e acompanham essa pesquisa são:
docs\SENTRA_COS_RETOMADA_7_FRENTES_OPEN_DOTS_2026-10-10.md
docs\SENTRA_AUDITORIA_RETORNOS_R5_CODEX_2026-10-10.md
docs\SENTRA_COS_RODADA_6_FECHAMENTO_E_HOMOLOGACAO_2026-10-10.md
Uma ressalva importante: consegui ler esses registros de coordenação, mas não o relatório independente SENTRA_OPEN_DOTS_RESEARCH.md diretamente. Portanto, a referência anterior a 55 achados e a atribuição de funcionalidades específicas a cada um dos três OpenDots ainda precisam ser conferidas no relatório original. Os registros consultados confirmam hipóteses úteis sobre editor, salvamento automático, recibos, outbox, agendamento e recuperação de interrupções, mas não demonstram que tudo isso foi implementado.
Também encontrei duas cópias de conversas/relatórios anteriores disponíveis nesta conta:
Markdown colado.mdResumo da clonagem e auditoria dos 37 repositórios do ecossistema SENTRA, com matriz de componentes aproveitáveis.Texto colado(6).txtHistórico da análise do Chat On Steroids, incluindo as 13 frentes iniciais e a ampliação para 34 frentes e subfrentes.

3. Depois de implementar tudo, no que o SENTRA se transforma?
VISÃO DO PRODUTO
SENTRA OS
Um ambiente operacional unificado para agentes de IA e automação.

A grande transformação seria passar de um aplicativo que conecta agentes e terminais para um sistema que recebe objetivos, organiza o trabalho, distribui tarefas, executa ações em ambientes autorizados e preserva o progresso até a conclusão.
A arquitetura resultante
SENTRA Canvas + Desktop + CLI
Uma interface central para projetos, agentes, arquivos, terminais e aprovações


SENTRA Control Plane
Autoridade única de Runs, WorkItems, permissões, operações, recibos e recuperação


Modelos e agentes
Codex, ChatGPT Web, Gemini e outros provedores integrados


Execução
Windows, navegador, terminais, máquinas remotas e sandboxes


Automação
Workflows, RPA, agendamento e integração entre serviços


Persistência
Memória, histórico, versionamento, estado durável e auditoria




Essa arquitetura permitiria desenvolver quatro capacidades principais:









Um ambiente de desenvolvimento com múltiplos agentes
Você descreve um sistema e o SENTRA coordena agentes para analisar requisitos, escrever código, executar testes, revisar alterações e preparar uma entrega. Cada agente trabalha em seu escopo, com supervisão central e histórico de decisões.












Uma plataforma de automação de processos
Agentes poderiam operar aplicações Windows, preencher sistemas, tratar documentos, navegar em páginas e coordenar tarefas empresariais. Ações sensíveis exigiriam permissões e controles adequados.












Um espaço de trabalho persistente e colaborativo
Documentos, código, PDFs, anexos, decisões e conversas permaneceriam associados ao mesmo projeto. Agentes poderiam continuar tarefas em sessões diferentes sem perder a identidade e o contexto essencial.












Um centro de comando para execução supervisionada
O SENTRA acompanharia tarefas em andamento, responsáveis, custos e limites, aprovações, falhas e resultados. Seria possível identificar o que foi concluído, o que está pendente e o que precisa de intervenção humana.



4. Qual seria a diferença prática?
Imagine que você solicite:
Desenvolva um sistema completo de RPA para uma empresa, com integração fiscal, interface de usuário, testes, segurança e documentação.

Um SENTRA plenamente implementado poderia estruturar o projeto, distribuir módulos entre agentes especializados, provisionar ambientes de execução, acompanhar as integrações, controlar permissões, consolidar resultados e preservar o estado da operação mesmo diante de interrupções.
O operador acompanharia o trabalho pelo Canvas, aprovando decisões relevantes e verificando evidências concretas de conclusão.
O ponto central não seria apenas ter muitos agentes conectados. Seria conseguir coordená-los de maneira confiável, com controle sobre o que cada um pode fazer e comprovação do que realmente fizeram.
5. O que ainda separa essa visão de um produto terminado?
Existe uma diferença fundamental entre:
Etapa	Significado
Pesquisado	Foi identificada uma funcionalidade útil
Implementado	Existe código correspondente no SENTRA
Integrado	O código participa dos fluxos reais do produto
Homologado	Há testes e evidências de funcionamento confiável
Pronto para distribuição	Instalador, segurança, recuperação e operação foram validados
Os relatórios mostram um volume considerável de funcionalidades e código desenvolvido. Entretanto, a integração integral de todas elas não foi comprovada, e a reconstrução bem-sucedida do Web Models, por exemplo, não equivale à homologação do SENTRA como um todo.
Para atingir a visão descrita, ainda seriam necessários testes ponta a ponta, segurança, recuperação de falhas, instalações limpas, compatibilidade com provedores, revisão de licenças e validação das capacidades distribuídas.

Minha avaliação: concluídas essas etapas, o SENTRA poderia ser apresentado como um Agentic Operating Environment — um ambiente operacional de agentes de IA — reunindo desenvolvimento de software, automação de computadores, orquestração, colaboração e execução persistente em uma única plataforma.
Não seria um sistema operacional que substitui o Windows, nem um produto que garante autonomia ilimitada. Seria uma camada operacional acima dele, capaz de coordenar diferentes tecnologias e agentes.
A maior oportunidade competitiva do SENTRA seria oferecer tudo isso sem transformar a experiência do usuário em dezenas de painéis técnicos: uma interface minimalista, sofisticada e simples de operar, sustentada por uma arquitetura robusta por trás.
















Eu gostei muito do visual do OpenDots, acredito que eu gostaria de implementar na verdade o nosso Canvas atual como uma seleção interna do OpenDots que pode ser gerenciada em uma conversa com um dots que cria e se liga a subagentes e ser algo visual como uma opção interna do proprio OpenDots, pois visualmente ele está muito bonito












Pensou por 1m 29s






Essa mudança de direção pode deixar o SENTRA muito mais interessante como produto. Em vez de o Canvas ser a interface principal de tudo, o SENTRA passaria a ter uma experiência centrada em conversas com Dots, e o Canvas se tornaria uma visualização avançada integrada a essa experiência.
Eu preservaria toda a engenharia que já construímos. O que mudaria radicalmente seria a maneira como o usuário interage com ela.
O CopilotKit OpenDots já utiliza conceitos que combinam bastante com essa proposta: Spaces, Dots especializados, conversas contínuas, documentos, computadores e ferramentas incorporadas à interface. 

GitHub
+1



Como eu estruturaria o novo SENTRA
SENTRA

Conceito de navegação


ESPAÇO DE TRABALHO
Conversas

Dots

Spaces

Canvas

Arquivos



Dot Coordenador

Conversa principal do projeto
Crie uma equipe para desenvolver meu aplicativo.

Frontend
Backend
QA


Visualização Canvas

Equipe conectada visualmente, tarefas e progresso





Representação conceitual da organização, não uma captura ou implementação concluída.
O papel de cada parte
Componente	Experiência desejada
Home	Uma página inicial elegante, com conversas, projetos e Dots recentes
Dot Coordenador	Interface conversacional que planeja, cria equipes e supervisiona objetivos
Dots especializados	Agentes com seus próprios modelos, instruções, ferramentas, histórico e limites
Spaces	Projetos, documentos, arquivos e contexto persistente
Canvas	Representação visual das relações entre agentes, máquinas, terminais e tarefas
Painel contextual	Arquivos, terminal, navegador, atividade e resultados sem sair da conversa
A mudança mais importante: controlar o Canvas conversando
Imagine escrever para um Dot:
Crie uma equipe de cinco agentes. Quero dois desenvolvedores, um arquiteto, um pesquisador e um responsável por testes. Organize as dependências entre eles e abra o Canvas para acompanhar a execução.

O SENTRA executaria um fluxo supervisionado: o coordenador propõe a equipe, cria os agentes autorizados, atribui responsabilidades, registra as relações e apresenta o Canvas correspondente.
Ao abrir a visualização, você veria os cinco Dots conectados, os trabalhos em andamento e os resultados em tempo real.
Poderia clicar em um Dot e conversar diretamente com ele. Ou voltar à conversa principal e pedir:
Pause o agente Backend, envie o resultado do pesquisador para o arquiteto e reorganize as próximas tarefas.

A interface conversacional e o Canvas exibiriam o mesmo estado verdadeiro, sem duplicação de agentes.
Como implementar sem destruir o SENTRA atual
Já confirmei no código que o Canvas usa React Flow/XYFlow em sentra_canvas/desktop_ui/src/main.jsx, enquanto o runtime e a autoridade principal continuam nas classes Canvas, TaskRuntime e ControlPlaneService.
Eu faria a migração em quatro etapas:
1. Nova interface principal: adaptar o design e os componentes adequados do OpenDots, com navegação por Dots, conversas e Spaces.
2. Canvas como visualização interna: transformar o Canvas existente em um componente acessível por navegação, painel lateral ou expansão para tela inteira, preservando seus nós, conexões e terminais.
3. Dot Coordenador real: conectar comandos conversacionais ao Control Plane para criar agentes, equipes, WorkItems, operações e relações, com permissões e confirmações.
4. Integração e homologação: sincronizar chat e Canvas, preservar projetos existentes e validar reinicialização, cancelamento, concorrência, permissões e recuperação de falhas.
Eu não executaria o backend do OpenDots como uma segunda autoridade dentro do SENTRA. Isso duplicaria estados e criaria conflitos. O SENTRA continuaria controlando as operações, enquanto a nova interface utilizaria seus serviços.
Há também uma questão de dependências: o CopilotKit/OpenDots é MIT, mas seu funcionamento conversacional utiliza CopilotKit Intelligence, com modalidades hospedada, avaliação local e implantação própria licenciada. Para o SENTRA, prefiro aproveitar a experiência visual e os componentes compatíveis, sem tornar obrigatório um serviço externo adicional. E a delegação automática entre vários Dots precisaria ser implementada no SENTRA: o próprio OpenDots ainda a descreve como trabalho futuro. 

GitHub
+1



Minha proposta de identidade
O nome continuaria SENTRA, e o usuário teria uma interface inicial extremamente refinada, parecida com o conceito do OpenDots, com elementos que aparecem apenas quando necessários.
O Canvas deixaria de competir visualmente com a conversa. Ele seria o modo de orquestração visual: uma capacidade poderosa, disponível quando o usuário quisesse explorar ou controlar a estrutura dos agentes.
Essa abordagem combina a experiência simples e bonita que você gostou com a engenharia mais profunda que o SENTRA já possui.

Só preciso confirmar uma coisa antes de definir a migração visual: você está se referindo ao visual do [CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots) — aquele organizado em Spaces, Dots e conversas — ou ao [Open Dots de Anil-matcha](https://github.com/Anil-matcha/open-dots)? Como a fidelidade ao design é importante para você, quero usar exatamente a interface correta como referência.  

Referencia visual:

[CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots) 


### Fonte ORDER ? docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md

# SENTRA — implementação integral coordenada no Maestri

## Ordem mandatória do usuário

1. Estado inicial preservado na `main` e enviado a `origin/main`: `3639a2e296428db8e3bb0839fac87d9237ec8592`.
2. Implementar integralmente a nota conectada `todos-os-projetos-ja-estao-clo`, os estudos por ela referenciados e a migração visual para **CopilotKit/OpenDots**.
3. **Implementação integral primeiro; validação somente no final de todas as implementações.** Durante esta fase não executar testes, builds de verificação, lint, benchmarks, auditorias de homologação ou QA visual. É permitido ler código, levantar requisitos, implementar, criar testes para execução futura e registrar contratos/dependências.
4. Não usar skills nem MCP do SENTRA nesta tarefa. Usar shell, edição direta e comunicação Maestri.
5. Até cinco Codex implementadores, mais um Codex auxiliar de orquestração: todos gpt-6.1-sol com esforço high (alto), em papéis heterogêneos; seis OpenCode Muse Spark 1.3 gratuitos com esforço High. Não criar agentes adicionais sem o orquestrador principal.

## Fonte de requisitos (ler integralmente o material pertinente)

- Nota Maestri `todos-os-projetos-ja-estao-clo` (465 linhas).
- `C:/Users/vitor/OneDrive/Desktop/SENTRA_RESEARCH_OPENDOTS/SENTRA_OPEN_DOTS_RESEARCH.md`: 55 achados e matriz G01–G13/A01–A21.
- `docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md`: 37 projetos.
- `docs/SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md`: propostas adicionais por projeto.
- `docs/SENTRA_THIRD_PARTY_REUSE_2026-10-08.md`.
- `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md`: 34 frentes/subfrentes.
- `docs/SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md` e `docs/SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md`.
- Clones locais: `third_party/*`, `SENTRA_RESEARCH_OPENDOTS/CopilotKit-OpenDots`, `SENTRA_RESEARCH_OPENDOTS/Anil-matcha-open-dots`. Usar o código atual como fonte, não alegações antigas de conclusão.

## Resultado integral requerido

Home, Dots especializados, conversas e Spaces são a experiência principal; Canvas existente passa a visualização interna. Dot Coordenador cria equipes/subagentes, delega tarefas, pausa e reorganiza trabalhos pela conversa. Chat, Canvas, CLI e Desktop consultam os mesmos agentes e o mesmo estado autoritativo. Projetos anteriores devem migrar de forma recuperável.

Incorporar todos os mecanismos aplicáveis dos estudos: documentos ricos/autosave/conflitos/versionamento/colaboração; continuidade e compactação; agendamentos; aprovações duráveis; outbox e recibos; execução Windows/browser/sandbox/remota; terminais persistentes; ACP/A2A/MCP; plugins MCPB/Skills; políticas e identidade; automações/conectores; histórico/anexos; observabilidade/diagnósticos; instalação/atualização/distribuição. Componentes opcionais podem permanecer opcionais, mas seus fluxos reais devem ser implementados; contratos vazios, stubs, placeholders e simulação não substituem integração.

Preservar ControlPlaneService/Run/WorkItem/Operation/Grant como autoridade única. Não executar backend OpenDots como segunda autoridade. Preservar proveniência/licenças de código reutilizado e falhar de forma explícita quando um serviço opcional não estiver configurado.

## Responsáveis e propriedade de arquivos

Todos trabalham na árvore compartilhada. Não editar arquivos de outro responsável; enviar contrato/solicitação ao dono e ao Codex principal. Não fazer commit/push/reset/stash nem remover mudanças alheias. Cada responsável pode criar arquivos novos no seu domínio e testes exclusivos, mas não executar validação ainda.

| Agente | CLI/modelo | Responsabilidade e arquivos exclusivos |
|---|---|---|
| Meridiano | Codex gpt-6.1-sol high | Auxiliar de orquestração. Extrair a matriz completa de requisitos dos três estudos, dependências, lacunas de implementação e distribuição sem reduzir escopo. Dono de `docs/integral/requirements.md`, `docs/integral/coverage.json`, `docs/integral/contracts.md`. Sem editar código de outros. |
| Prisma | Codex gpt-6.1-sol high | Migração visual integral OpenDots, Home/Dots/Spaces/conversas, Canvas interno e painéis contextuais. Dono de `sentra_canvas/desktop_ui/src/main.jsx`, `desktop.css`, novos componentes de shell/conversa e package.json da UI. Acompanhar integração real com os endpoints do Codex principal. |
| Nexo | Codex gpt-6.1-sol high | Autoridade central, Run/WorkItem/Grant/Operation, coordenação conversacional e persistência de Dots/Spaces/equipes. Dono de `sentra_core/*`, `sentra_runtime/*`, `sentra_mcp/services/control_plane.py`, `control_store.py`, `durable.py`, `context*.py`, `task_ledger.py`, `budget_policy.py`, `governance.py`, `conversation_memory.py`, `workspaces.py`. Criar módulo próprio de serviço coordenador/Spaces se necessário. |
| Forja | Codex gpt-6.1-sol high | Execução Windows/UFO/UIA, Daytona/HCS/gVisor, Playwright, remoto/Guacamole/RustDesk e RPA. Dono de `sentra_executors/*` EXCETO `goal_loop.py`, `conpty_sessions.py`, `operation_receipts.py` e benchmarks. Implementar provedores reais e memória/recovery, não apenas contratos. |
| Lume | Codex gpt-6.1-sol high | ACP/A2A/OpenHands/MCP SDK, registry, lifecycle, descoberta, streams/artefatos/delegação. Dono de `sentra_interop/*` EXCETO `workflow*` e `activepieces*`. |
| Tessela | Codex gpt-6.1-sol high | Documentos ricos, autosave/CAS/conflitos/versionamento, Yjs/y-protocols/Hocuspocus, presença/undo, PDFs/código/diff. Dono de `sentra_collab/*`, `sentra_canvas/project_review.py`, `sentra_canvas/project_documents.py` e componentes novos `document-*`/`collaboration-*` na UI. Coordenar inserção no shell com Prisma. |
| Rastro | OpenCode Muse Spark 1.3 Free high | Continuidade A→B, Compact & Resume, outbox cifrada/recibos/recuperação, gateway modelos/contas/esforços. Dono de `native_bridge/*`, `sentra_model_gateway/*` EXCETO `browser_host_identity.py`, e `sentra_mcp/services/session_checkpoint.py`, `web_account_dispatch.py`, `web_history_*`. |
| Brisa | OpenCode Muse Spark 1.3 Free high | Extensão Edge/browser, identidade/provas de conversa, streaming/anexos/aprovação observada e catálogo de conta autenticada. Dono de `edge_extension/*`, `browser/*`, `sentra_model_gateway/browser_host_identity.py`, `sentra_mcp/services/browser_evidence.py`, `integrations/codex_chatgpt_web/*`. Contratos com Rastro. |
| Pacto | OpenCode Muse Spark 1.3 Free high | MCPB stdio/HTTP/OAuth/supervisão/sandbox/uninstall, Skills versionadas, superfícies mínimas/Code Mode e consentimento por chat. Dono de `sentra_mcp/services/mcpb_*`, `plugin_*`, `skill_library.py`, `tool_exposure.py`, `chat_access.py`, `action_consent_gate.py`, `sentra_mcp/tool_policy.py`, `sentra_code_mode/*`, componentes existentes de plugins/skills/chat-access. |
| Pulso | OpenCode Muse Spark 1.3 Free high | Scheduling persistente, Goal/Loop, NATS/Temporal/LangGraph, Activepieces, workflows empresariais, terminal persistente e recibos humanos. Dono de `sentra_interop/workflow*`, `activepieces*`, `sentra_executors/goal_loop.py`, `conpty_sessions.py`, `operation_receipts.py`, `sentra_mcp/services/routine_scheduler.py`, `jobs.py`. |
| Selo | OpenCode Muse Spark 1.3 Free high | OPA/OpenFGA/Keycloak/SPIRE, Tessera/immudb, telemetria OpenTelemetry/Langfuse, memória/custos/diagnósticos e Grype. Dono de `sentra_quality/*`, `memory/*`, `sentra_mcp/services/authorization.py`, `capabilities.py`, `telemetry.py`, módulos novos de política/identidade/auditoria e benchmarks de `sentra_executors/benchmark*`. |
| Vitra | OpenCode Muse Spark 1.3 Free high | Setup/Doctor/reparo, staged update/migração/rollback, Windows/Electron/CLI, instalação/distribuição e proveniência. Dono de `sentra_remote/*`, `scripts/commander/*`, `.github/workflows/*`, `sentra_electron/*`, `sentra_canvas/electron_host.py`, `native_app.py`, `__main__.py`, `sentra_cli/*`, manifests de release. Preparar QA final sem executar. |
| Codex | Orquestrador principal | Dono dos pontos centrais de composição: `sentra_canvas/service.py`, `graph.py`, `sentra_mcp/server.py`, configuração raiz/pyproject e integração entre todos os módulos. Libera etapa de validação somente após TODAS as frentes implementadas e integradas. |

## Comunicação e entrega

Executar `maestri list` antes de contatar colegas. Cada agente lê a nota ou este documento e o estudo de seu domínio, implementa integralmente sua parte e registra `docs/integral/<Nome>.md`: requisitos, arquivos alterados, contrato de integração, pendências reais, plano de validação futura. A documentação não substitui implementação.

Relatar progresso e dependências ao principal com `maestri ask "Codex" "..."`; no término da implementação, usar esse comando para retornar o resultado completo. Não declarar homologado nem completo por leitura de arquivos. Meridiano consolida a matriz e solicita expansão das tarefas faltantes ao principal. Não recrutar mais agentes. Todos preservam mudanças existentes e a regra de validação ao final.

## Etapa final (ainda não liberada)

Depois da implementação integral e integração de todas as frentes, executar testes apropriados, builds, verificação visual/fidelidade ao CopilotKit/OpenDots, concorrência/recovery/permissões, provedores autorizados e instalação/release. Confrontar requisito por requisito com evidência atual. Não declarar sucesso integral enquanto faltarem implementação, integração ou evidências.


### Fonte SHELL ? docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md

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


### Fonte OD ? C:/Users/vitor/OneDrive/Desktop/SENTRA_RESEARCH_OPENDOTS/SENTRA_OPEN_DOTS_RESEARCH.md

# SENTRA — pesquisa comparativa OpenDots

**Data:** 10/10/2026, America/Sao_Paulo. **Natureza:** estudo estático; nenhuma implementação ou homologação. **Destino exclusivo:** SENTRA_RESEARCH_OPENDOTS.

## Índice

1. Resultado e critérios de decisão
2. Aquisição, SHAs e qualidade da evidência
3. Licenças, notices e relações entre projetos
4. CopilotKit/OpenDots: arquitetura, funcionalidades e riscos
5. Anil-matcha/open-dots: arquitetura, funcionalidades e riscos
6. feder-cr/invisible_dots: arquitetura, funcionalidades e riscos
7. Compatibilidade com a autoridade SENTRA
8. Matriz completa das 34 entradas G/A
9. Threat model, dependências e publicação
10. Design e plano futuro por prioridade
11. Testes e limites de cobertura
12. Checklist de fontes e pendências

## 1. Resultado e critérios de decisão

A melhor aplicação desta pesquisa é aproveitar padrões de experiência e consistência, mantendo o SENTRA como autoridade exclusiva de Run, WorkItem, Operation e Grant. Importar qualquer um dos três backends inteiros criaria outra máquina de estados, outra aprovação e outro executor. Isso contrariaria os quatro documentos autoritativos consultados.

**Recomendação:** priorizar revisão com versão, estados claros de salvamento, recibos humanos de ferramentas, aprovação vinculada a argumentos, recuperação explícita de trabalho interrompido e política de agendamento. Adiar voz, canais externos e computadores adicionais até que autorização, instalação e evidência Web estejam homologadas. Não copiar o classificador de shell do Anil como controle de segurança; não usar autodeclaração MCP de leitura como concessão; não importar a autoridade de execução do feder.

| Projeto | Maior contribuição | Decisão de estudo | Compatibilidade principal |
|---|---|---|---|
| CopilotKit/OpenDots | Editor de páginas, trabalho organizado, integração de ferramentas e estados de interação | Adaptar padrões de UI e revisão; avaliar trechos MIT individualmente no futuro | Alta como referência de apresentação; baixa como backend substituto |
| Anil-matcha/open-dots | Agendamento transacional, retomada de conversa CLI, aprovação inline | Aproveitar ideias; bloquear cópia enquanto a licença não estiver estabelecida | Média para semântica de agenda; baixa para identidade e autorização |
| feder-cr/invisible_dots | Aprovação durável, outbox e separação host/guest | Estudar protocolos e recibos; integração de VM somente como hipótese futura | Média para contratos; baixa para importação do control plane inteiro |

P0 significa pré-condição de segurança, identidade, legalidade ou instalação real. P1 significa melhoria útil sobre a autoridade existente, depois dos gates P0. P2 significa expansão de capacidade com custo operacional adicional. Prioridade não concede autorização de implementação: este relatório apenas propõe trabalho futuro.

Custo **baixo/médio/alto** é avaliação relativa de complexidade, operação e manutenção. Não houve orçamento, benchmark ou medição de desempenho; não são estimativas contratuais. Compatibilidade é por recurso, nunca percentual de equivalência.

### O que esta pesquisa não comprovou

- Não se obtiveram três clones completos nem histórico suficiente para comparar ancestralidade.
- Não se executaram aplicações, suites, builds, dependências ou scripts upstream.
- Não se comprovou 100% de leitura, cobertura de testes, segurança ou adequação jurídica.
- Não se inspecionou código atual do SENTRA além dos quatro documentos autorizados. Estados do produto são declarações desses documentos, sujeitos a alterações concorrentes.
- Nenhum desses projetos fornece, pela evidência examinada, o vínculo exigido entre conta ChatGPT Web, plano/modelo/effort observado, request MCP, mensagem, documento/epoch, WorkItem, Operation e Grant.

## 2. Aquisição, SHAs e qualidade da evidência

### 2.1 Resultado real das tentativas Git

| Destino autorizado | SHA de HEAD verificado por rev-parse | Estado observado | Histórico |
|---|---|---|---|
| CopilotKit-OpenDots | **625452e06cde74cb25b0ce319e2c1be0488f5a5f** | Diretório preexistente com apenas .git; 195 entradas na árvore HEAD; checkout e índice ausentes | shallow=true; rev-list --count HEAD=1 |
| Anil-matcha-open-dots | **3d8de1cd6657c6d70583f34b89c2dc034512c1ea** | Diretório preexistente com apenas .git; 108 entradas na árvore HEAD; checkout e índice ausentes | shallow=true; rev-list --count HEAD=1 |
| feder-cr-invisible_dots | **Não obtido** | Clone falhou na conexão a github.com:443; diretório não presente na conferência da raiz | Não obtido |

Os dois primeiros diretórios já existiam quando a inspeção funcional começou. O documento SENTRA de retomada atualizado explica que o coordenador havia tentado clones rasos. Não se atribui a esta pesquisa um clone bem-sucedido que ela não fez.

Foram tentados os três comandos de clone com **--filter=blob:none**, destinos exatos e sem --depth nas tentativas desta sessão. O terminal inicial falhou antes de iniciar processo com “helper_unknown_error: setup refresh had errors”. No fallback de processo Git, CopilotKit e Anil recusaram o destino não vazio; feder retornou erro de conexão. Não se apagaram, substituíram, completaram ou fizeram checkout/fetch nos diretórios existentes. O acesso remoto de consulta foi a alternativa permitida pelo pedido.

A propriedade Windows dos repositórios provocou inicialmente a proteção safe.directory. A inspeção usou exceção **somente no comando**, para cada caminho exato; não modificou configuração global. Prompts e helpers de credenciais foram desabilitados. A leitura Git desabilitou lazy fetch e locks opcionais. git show de um blob do CopilotKit falhou por objeto ausente; os nomes na árvore não significam conteúdo disponível.

O status mostrava remoções de arquivos de HEAD porque o índice/worktree não havia sido materializado. Isso **não** foi interpretado como checkout limpo, nem houve restore/reset. Datas registradas dos commits: CopilotKit, 07/10/2026 03:46:40 +05:00, “dark mode (#81)”; Anil, 07/10/2026 13:51:46 +05:30, ajuste documental de posicionamento.

### 2.2 Classes de evidência

- **V — verificado estaticamente:** conteúdo ou metadado efetivamente inspecionado; não prova comportamento em execução.
- **D — declaração upstream:** README, guia, arquitetura ou CI descrevem a capacidade; sua execução não foi homologada.
- **H — hipótese/inferência:** conclusão de revisão ou proposta futura, explicitamente identificada.
- **N — não demonstrado:** fonte necessária ausente, inacessível ou fora do recorte; não significa inexistência absoluta.
- **S — estado SENTRA documental:** informação dos quatro documentos, não nova auditoria do checkout instalado.

Fontes públicas foram acessadas em URLs main. Isso não fixa automaticamente cada conteúdo no HEAD local. Para parte dos arquivos, reconstruiu-se o texto bruto servido pela consulta e comparou-se **Git blob SHA-1** com ls-tree HEAD. O checklist final identifica os matches positivos. Falta de match pode resultar de formatação/linhas da consulta, cache ou revisão diferente; não autoriza afirmar que o código mudou.

Para feder não houve árvore Git local nem SHA raiz. Todos os resultados sobre ele são uma fotografia pública **não fixada**, mesmo quando o arquivo de código foi lido. O SHA do nanobot apresentado adiante é de um componente upstream, não do repositório feder.

A documentação de arquitetura do feder apareceu com totais de linhas diferentes entre apresentações consultadas. Isso reforça a limitação de cache/revisão. Nenhum link main deve ser promovido a pin de produção.

### 2.3 Documentos SENTRA consultados

Foram lidos integralmente os quatro documentos especificados. A retomada foi relida após detectar mudança concorrente. O snapshot dessa releitura tem checkpoint aproximadamente 14h18 Brasília. Os hashes das leituras serão registrados no checklist.

O estado autoritativo determina ControlPlaneService, AuthorizationService, DurableRunService, SQLiteControlPlaneStore, Canvas e TaskRuntime; os efeitos devem passar pelo DurableOperationGate. Os documentos relatam validações locais anteriores, mas distinguem essas validações do app instalado e da homologação das 34 entradas.

**Atualização relevante:** a auditoria anterior registrava falta de integração HTTP do PDF visual. A retomada mais recente relata que o coordenador integrou essa rota, com autorização e 17 testes locais aprovados. Este estudo não repetiu esses testes nem abriu o app instalado. Portanto, o achado correto é “integração local declarada; instalação real pendente”, e não “PDF ainda inexistente”.

As lacunas anteriores de relay instalado e junção WebMCP/ToolPolicy permanecem questões a confirmar pelo coordenador; não se afirma que o checkout concorrente continue inalterado. O Codex implementador e os seis agentes possuem escopos próprios. Este pesquisador não assumiu nenhum deles.

## 3. Licenças, notices e relações entre projetos

### 3.1 Situação jurídica por projeto

| Projeto | Licença encontrada | Copyright / condição | Consequência para SENTRA |
|---|---|---|---|
| CopilotKit | LICENSE: MIT; package.json declara MIT | **Copyright (c) Atai Barkai** | Cópia futura condicionada à preservação do copyright e texto da licença nas cópias/porções substanciais; dependências têm análise separada |
| OpenBot usado pelo CopilotKit | deployment/computers/LICENSE.openbot: MIT | **Copyright (c) 2026 CopilotKit** | Preservar notice próprio se houver redistribuição desse componente; não basta o LICENSE raiz |
| Anil | Nenhum LICENSE/LICENCE/COPYING/NOTICE encontrado entre as 108 entradas HEAD | About apresenta MIT, mas o grant e titular não foram estabelecidos | **Não copiar código, estilos ou assets** sem esclarecer a licença com o titular |
| feder | LICENSE raiz: MIT | **Copyright (c) 2026 feder-cr** | A raiz não cobre indiscriminadamente todo o software agregado; THIRD_PARTY_NOTICES enumera exceções |

Fontes: [CopilotKit LICENSE](https://github.com/CopilotKit/OpenDots/blob/main/LICENSE), [OpenBot notice](https://github.com/CopilotKit/OpenDots/blob/main/deployment/computers/LICENSE.openbot), [Anil repositório](https://github.com/Anil-matcha/open-dots), [feder LICENSE](https://github.com/feder-cr/invisible_dots/blob/main/LICENSE).

No Anil, a ausência foi comprovada no inventário local HEAD, e a tentativa pública de LICENSE retornou 404. Outros nomes tentados tiveram falhas de consulta. A descrição “open-source” ou um badge/About não substitui uma licença verificável. Ideias podem orientar uma implementação original futura, sujeita à avaliação jurídica aplicável; este estudo não reproduz sua implementação.

### 3.2 Notices específicos do feder

O catálogo upstream registra: nanobot MIT, com licença aninhada; derivações MIT de OpenMultiAgent, context-chef, OpenHands, opencode, shadcn/ui, OpenDots, open-cowork e assistant-ui; trechos **Apache-2.0** de OpenAI Codex e Vercel AI Elements; hev-socks5-tunnel MIT na imagem. Também aponta libsignal **GPL-3.0** na integração WhatsApp opcional e libvips **LGPL-3.0-or-later** em binários sharp transitivos. Fonte: [THIRD_PARTY_NOTICES.md](https://github.com/feder-cr/invisible_dots/blob/main/THIRD_PARTY_NOTICES.md).

Uma adoção futura precisa selecionar os arquivos exatos e suas notices, inclusive histórico/origem quando aplicável. MIT não exige publicar todo o SENTRA, mas exige conservar aviso e permissão nas cópias abrangidas. Apache-2.0 exige licença, avisos pertinentes, marcação das modificações e NOTICE aplicável; não concede direito de marca. Fonte normativa: [Apache License 2.0, seção 4](https://www.apache.org/licenses/LICENSE-2.0).

O upstream separa a instalação WhatsApp e declara excluí-la do bundle normal. Isso é uma característica de empacotamento, não uma conclusão jurídica universal sobre qualquer futura distribuição SENTRA. Redistribuir imagem Linux, QEMU, browser, bibliotecas nativas ou um conjunto com GPL/LGPL exige inventário binário e avaliação das obrigações específicas; não se verificaram todos os componentes, textos e ofertas de código-fonte.

Não foi criado SBOM nesta missão, nem conferido um pacote de release. A análise de notices é triagem para seleção, não parecer de liberação comercial.

### 3.3 Relações verificadas, sem equivalência por nome

| Relação | Evidência | Conclusão permitida |
|---|---|---|
| CopilotKit → feder | THIRD_PARTY_NOTICES identifica origem OpenDots, revisão curta 88f2a08, de time.ts, use-visible-interval.ts, tool-labels.ts e task-status.tsx | Há derivação declarada de quatro utilitários/componentes; não prova fork completo nem ancestralidade Git |
| nanobot → feder | invisible_engine_dots/UPSTREAM.md fixa base f75470e72f0993dcf92accc81282adaa48b16f56, importação curta 8dd5ddb1 e hard fork | Engine Python derivado de nanobot; manutenção própria explícita |
| Outro OpenDots → feder | Notice cita Shashankss1205/OpenDots para diff-preview/diff | Não é prova de origem Anil ou CopilotKit; quarto projeto não foi expandido nesta missão |
| Anil ↔ CopilotKit/feder | Stacks e layouts distintos; história suficiente indisponível; nenhum vínculo comprovado nas fontes lidas | Relação não estabelecida; sem alegar independência jurídica absoluta ou equivalência funcional |

Fonte complementar: [feder UPSTREAM.md](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/UPSTREAM.md). Sua árvore histórica menciona engine TypeScript anterior, hoje substituído. Um componente removido do presente não deve ser anunciado como funcionalidade atual.

**Custo upstream:** CopilotKit depende fortemente de APIs de Intelligence/Threads e SDKs; Anil depende de Boat e CLI Claude/OAuth; feder assume manter um hard fork Python, daemon Go, imagem Linux e host TypeScript. Esses custos persistem mesmo quando a licença de um arquivo é permissiva.

## 4. CopilotKit/OpenDots

### 4.1 Hierarquia e arquitetura

Árvore HEAD inventariada: 195 arquivos. A organização principal separa src/client, src/server, src/shared, src/browser, tests, docs, public e deployment/computers. O servidor é composto em src/server/index.ts; a interface não é uma distribuição desktop Windows.

O fluxo de composição cria stores locais, camada Platform baseada em CopilotKit, Runner e aplicação HTTP. Metadados de workspace/páginas/tarefas e conversas Threads pertencem a camadas distintas. Consequentemente, copiar apenas SQLite não demonstra backup integral de conversas nem restauração de serviço externo. Fonte: [index.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/index.ts), [platform.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/platform.ts).

Manifesto declara Node >=24, React 19, Vite 8, TypeScript 6, Hono 4, CopilotKit 1.75, Channels 0.11, AG-UI 0.0.59, TanStack AI 0.63, MCP SDK 1.31 e TipTap 3.31.3. Várias versões são ranges, não o grafo instalado. Vitest, ESLint e Prettier são ferramentas de desenvolvimento. Existe lockfile inventariado, mas não se auditou a árvore transitiva completa. Fonte: [package.json](https://github.com/CopilotKit/OpenDots/blob/main/package.json).

Não se demonstrou uma CLI de produto com o contrato SENTRA. Scripts npm servem ao desenvolvimento/build/servidor/browser; a configuração inicial usa ferramentas externas do ecossistema. A documentação de self-hosting do Intelligence exige licença própria e infraestrutura de PostgreSQL, Redis e OIDC/Kubernetes. **MIT do template não garante gratuidade ou disponibilidade de Intelligence.** Fonte: [self-hosting oficial](https://docs.copilotkit.ai/intelligence/self-hosting).

### 4.2 Índice funcional por caminho

A coluna SENTRA é recomendação H. “Adaptar” significa preservar o contrato autoritativo existente; não copiar automaticamente.

| ID | Capacidade observada e limite | Evidência principal | Classe | Decisão / compatibilidade / prioridade |
|---|---|---|---|---|
| CF01 | Composição de servidor e provider; aplicação utilizável em partes sem provider | src/server/index.ts; src/server/platform.ts | V | Aproveitar degradação explícita; média; P1 |
| CF02 | Spaces, organização de Dots e contexto de workspace | src/server/workspace.ts; src/client/App.tsx | V/recorte | Adaptar organização visual ao Canvas; alta; P1 |
| CF03 | Páginas hierárquicas, revisão, versões e exclusão | src/server/pages.ts; src/server/page-service.ts | V | Adaptar revisão com conflito; alta; P1 |
| CF04 | Editor Markdown/rich text, listas, tabelas e comandos | src/client/editor/RichEditor.tsx | V | Aproveitar UX; não supre editor de código/PDF; alta; P1 |
| CF05 | Autosave, erro/conflito, preservação de draft em memória | src/client/editor/autosave.ts | V | Adaptar estados e recuperação; alta; P1 |
| CF06 | Fallback de source, export Markdown, atalhos e aviso de saída | src/client/PageDocument.tsx | V | Adaptar ao project_review; alta; P1 |
| CF07 | Agente com contexto, tools e streaming AG-UI | src/server/dot-agent.ts | V | Usar apresentação do progresso; baixa para importar executor; P2 |
| CF08 | Pesquisa Web via Parallel MCP, browser ou modo desabilitado | src/server/parallel.ts | V | Adaptar provenance e falha explícita; média; P2 |
| CF09 | Browser read-only separado e transporte com limites | src/browser/index.ts; src/browser/transport.ts | V parcial | Estudar limites de consulta; não equivale à extensão MV3; P0 |
| CF10 | Conexões MCP HTTP, catálogo de ferramentas e namespaces | src/server/connections.ts; docs/CONNECTIONS.md | V/D | Adaptar descoberta através de MCPB existente; média; P1 |
| CF11 | Aprovação vinculada a thread, tool e argumentos persistidos | src/server/connection-routes.ts; src/server/connection-store.ts | V | Estudar recibos; endurecer vínculo Operation/Grant; P0 |
| CF12 | Computador por Dot com browser/files/shell e auditoria | src/server/computer-service.ts | V | Referência de status/recibos; executor novo somente futuro; P2 |
| CF13 | Deployment OpenBot isolado, pin upstream e credenciais por Dot | deployment/computers/README.md; LICENSE.openbot | D/V licença | Avaliar custo e pin; não instalar; P2 |
| CF14 | Tarefas persistidas, claim/lease e recuperação | src/server/store.ts; src/server/runner.ts | V | Adaptar semântica a DurableRunService; média; P1 |
| CF15 | Chamadas de voz WebRTC, transcript e ferramentas delimitadas | src/server/voice.ts | V | Adiar após autorização e receipts; média; P2 |
| CF16 | Slack via Channels, allowlist de workspace/usuário | src/server/slack-channel.ts | V | Canal opcional futuro; baixa necessidade atual; P2 |
| CF17 | Automatic Learning/containers por Dot | src/server/learning.ts | V chamada SDK/D backend | Não importar publicação automática de Skills; P2 |
| CF18 | Escopo agent/thread separado do principal proprietário | src/server/runtime-scope.ts; src/server/platform.ts | V | Aproveitar isolamento lógico; insuficiente para prova Web; P0 |
| CF19 | Guardas HTTP, CSP e restrição de exposição | src/server/app.ts; src/server/index.ts | V | Comparar com auth local existente; média; P0 |
| CF20 | Tema escuro, biblioteca, sidebar e feedback de polling | src/client/App.tsx; tests/dark-theme.test.ts; tests/library.test.ts | V recorte/inventário | Referência minimalista; validar ARIA/DPI no SENTRA; P1 |
| CF21 | CI de testes, formato, lint, tipos e build | .github/workflows/ci.yml | V configuração | Referência de gates, sem alegar execução; P1 |
| CF22 | Telemetria SDK/setup e opções de opt-out | docs/SETUP.md; package.json; arquivos de telemetry inventariados | D/parcial | Consentimento e diagnóstico redigido antes de publicar; P0 |

Links de todos os caminhos efetivamente consultados aparecem no checklist. Caminhos apenas inventariados são identificados como tal; não se atribui leitura integral a testes de tema/biblioteca ou arquivos de telemetry.

### 4.3 Fluxos de ponta a ponta

**Edição e revisão.** O usuário navega até uma página; o editor mantém draft e tenta salvar com revisão esperada. O serviço recusa versão concorrente, em vez de sobrescrever silenciosamente. Hierarquia de pais e exclusões têm regras próprias; uma revisão humana não deve ser ressuscitada por recriação de objeto. A UI permite source/export e sinaliza erro. Esse conjunto é útil para G10/A18/A20, mas páginas de texto não substituem diff de arquivo, watch de Git ou renderização PDF autenticada. Fontes: [pages.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/pages.ts), [page-service.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/page-service.ts), [PageDocument.tsx](https://github.com/CopilotKit/OpenDots/blob/main/src/client/PageDocument.tsx).

**Autosave.** A máquina de estados distingue dirty, saving, saved, error e conflict e protege troca de documento contra resposta antiga. Erro não provoca retry ilimitado. O draft inspecionado é mantido em memória; não se comprovou recuperação durável após crash. Fonte: [autosave.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/client/editor/autosave.ts). Para SENTRA, adaptar feedback e versionamento é valioso; persistência e autorização continuam responsabilidade do produto.

**Chat/agente.** A camada de agente oferece ferramentas de página, pesquisa, memória, computador e conexões a um loop de modelo; AG-UI fornece eventos. O escopo delimita agente/thread, mas não cria prova de origem ChatGPT Web. Fonte: [dot-agent.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/dot-agent.ts). Não se demonstrou delegação multiagente, grupos entre Dots ou compatibilidade de modelo/effort com a conta Web SENTRA.

**Pesquisa.** Parallel é serviço remoto; a alternativa browser oferece consulta separada. Há limitação/normalização de resultados e erro explícito. Consulta, objetivo e URLs podem sair para o provider selecionado. Não assumir que uma instalação local mantém pesquisa inteiramente local. Fonte: [parallel.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/parallel.ts).

**Execução agendada.** Store reivindica tarefa com lease e transação; o runner controla posse e interrupção, limita tempo e serializa execução local. Lease expirado se torna trabalho interrompido para decisão explícita. A recorrência é baseada no término bem-sucedido, diferente de cron com calendário/timezone. Fontes: [store.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/store.ts), [runner.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/runner.ts). Isso inspira recuperação segura; não constitui o Goal/Loop com orçamento, fencing e efeitos externos do SENTRA.

**Ferramentas MCP.** Catálogo recebe namespaces e limites de quantidade/resultado. Conexões aceitam endereços locais por decisão de produto e não fornecem OAuth genérico. Ferramentas novas ficam habilitadas e readOnlyHint pode dispensar aprovação. Fonte: [connections.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/connections.ts), [CONNECTIONS.md](https://github.com/CopilotKit/OpenDots/blob/main/docs/CONNECTIONS.md). No SENTRA, annotations são dados não confiáveis; exposição mínima e Grant continuam exigidos.

**Computador.** Serviço exige configuração explícita e deriva credencial por Dot, registra intenção antes da chamada e verifica cancelamento/revogação. Permissões browser/files/shell e recibos visíveis ajudam o humano, mas não demonstram fencing físico de cada operação no executor. Fonte: [computer-service.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/computer-service.ts). O deployment documenta OpenBot no SHA b6932d31a8d6e7896c15139dfc27a6c6911deb27 e preservação de volumes; não se auditou o repositório OpenBot inteiro.

**Voz e Slack.** Voz usa WebRTC e mantém registro de chamada; Slack aplica allowlist e encaminha mensagens ao mesmo principal. São entradas adicionais de ação, com custo de identidade, vazamento e consentimento. Fontes: [voice.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/voice.ts), [slack-channel.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/slack-channel.ts). A integração conectada desses serviços não foi testada aqui. Learning cria vínculos por Dot através do SDK; aprendizado remoto não comprova revisão humana, pin Git ou imutabilidade de SkillPack. Fonte: [learning.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/learning.ts).

### 4.4 Riscos específicos

1. **Tokens em SQLite — V.** connection-store.ts contém campo token TEXT. É armazenamento server-side, sem comprovação de vault/criptografia em repouso nesse componente. Migrar esse padrão sem revisão criaria superfície de segredo fora do vault SENTRA. Fonte: [connection-store.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/connection-store.ts).
2. **Consumo de aprovação — H crítica.** O claim inspecionado usa chave threadId/toolCallId; approvalId é associado, sem unicidade equivalente demonstrada. Uma aprovação reutilizada com outro toolCallId parece não ser impedida por esse mecanismo. Não houve exploração ou confirmação dinâmica. Além disso, crash entre claim e recibo requer reconciliação, sem retry automático. Fonte: [connection-routes.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/connection-routes.ts).
3. **SSRF — V/D.** MCP com destino local é permitido; esse canal e o browser de pesquisa têm políticas diferentes. DNS pinning/limites vistos no transporte do browser não provam que todas as conexões MCP herdam proteção. Fonte: [transport.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/browser/transport.ts). src/browser/security.ts não pôde ser lido.
4. **Identidade — V.** Modelo é de um proprietário, não RBAC multiusuário. Exposição fora do loopback exige OWNER_TOKEN longo, mas isso não resolve conta Web, app ligado ou Grants por operação. Fontes: [index.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/index.ts), [app.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/app.ts).
5. **Distribuição — V/N.** Docker usa processo não root, mas tags e dependências precisam de política de supply chain. Não foi demonstrado MSI assinado, updater com rollback ou primeira instalação Windows limpa. Fonte: [Dockerfile](https://github.com/CopilotKit/OpenDots/blob/main/Dockerfile).
6. **Serviços externos — D.** Telemetria, Intelligence, pesquisa, voz e Channels ampliam transferências de dados. Licença MIT do template não substitui termos, consentimento ou análise dos providers. A seleção de recursos deve permitir produto útil com opcionais desligados.



## 5. Anil-matcha/open-dots

### 5.1 Hierarquia, stack e autoridade

Árvore HEAD inventariada: 108 arquivos. backend contém app/core, db/models, routers, services, telegram, migrations e tests; frontend contém aplicação Next e cliente de API; scripts/dev.sh é facilitador de desenvolvimento. Nomes “Vadoo” remanescentes em documentos/interface revelam evolução do protótipo, não identidade com os outros OpenDots.

O manifesto backend exige Python >=3.14 e declara FastAPI, SQLAlchemy assíncrono, asyncpg, Alembic, Boat SDK, python-telegram-bot, cryptography, structlog e APScheduler 3.x. frontend declara Next 16.3.5, React 19.2.8, TypeScript 5 e Tailwind 4. Fontes: [pyproject.toml](https://github.com/Anil-matcha/open-dots/blob/main/backend/pyproject.toml), [frontend/package.json](https://github.com/Anil-matcha/open-dots/blob/main/frontend/package.json). A recomendação Node 18+ do README não deve ser tratada como compatibilidade demonstrada de todo o stack atual.

Web e bot Telegram compartilham serviços e PostgreSQL; sandboxes são provisionados pelo Boat, e o trabalho usa Claude CLI. A aplicação FastAPI registra routers, CORS e loops de tarefa/agenda/report em sua vida útil. Não foi encontrada, nessa composição, autenticação global de usuário que compense as rotas examinadas. Fonte: [main.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/main.py).

Não é terminal local persistente SENTRA nem executor ConPTY. CLI Claude é um componente remoto do sandbox, com sessão reaproveitada; isso não cria console pertencente ao processo Windows instalado.

### 5.2 Índice funcional por caminho

| ID | Recurso / limite | Caminho | Evidência | Decisão / compatibilidade / prioridade |
|---|---|---|---|---|
| AF01 | REST e bot compartilham backend | backend/app/main.py; routers/router.py | V | Ideia de canal único; não importar backend; média; P2 |
| AF02 | Identidade guest/Telegram no navegador | frontend/app/page.tsx; frontend/lib/api.ts | V | Rejeitar localStorage como autoridade; baixa; P0 |
| AF03 | Provisionamento, stop/resume e diagnóstico de sandbox | backend/app/routers/sandbox.py | V | Só referência de estados; ações exigem Grant; baixa; P2 |
| AF04 | Login Claude OAuth e GitHub device flow | routers/sandbox.py; README.md | V parcial/D | Não confundir com prova da conta ChatGPT; P0 |
| AF05 | Credenciais cifradas com rotação MultiFernet | backend/app/core/crypto.py; core/config.py | V | Avaliar fluxo, manter vault próprio SENTRA; média; P0 |
| AF06 | Tarefa CLI, continuação de session e resultado completo | services/task_execution_service.py; routers/task.py | V | Adaptar semântica de resume/resultados; média; P1 |
| AF07 | Claim e recuperação de queued/starting | services/task_execution_service.py | V | Diferenciar falha de efeito incerto; P0 |
| AF08 | Regras allow/deny/ask e escopo | services/permission_service.py | V | UI de consentimento útil; política não é Grant; P0 |
| AF09 | Aprovação inline, resposta e deadline | services/permission_ask_service.py; routers/permission.py | V | Adaptar apresentação, rejeitar owner gate ausente; P0 |
| AF10 | Classificação de git em comandos shell | services/github_classifier.py | V | Apenas rótulo informativo; rejeitar autorização; P0 |
| AF11 | Cron/timezone, ocorrência única e não sobreposição | services/schedule_service.py | V | Ideias para Goal/WorkItem existentes; média/alta; P1 |
| AF12 | Resultado agendado em Telegram, pausa por falhas | schedule_service.py; notification_service.py | V | Adaptar política de pausa; entrega precisa de receipt; P1 |
| AF13 | Histórico simples de tasks, polling e continuação | frontend/app/page.tsx; frontend/lib/api.ts | V | Referência de interação; não é histórico Web completo; P1 |
| AF14 | Ambiente de desenvolvimento, Postgres e migrações | README.md; backend/README.md; scripts/dev.sh inventariado | D/inventário | Descrever somente; não equivale a Setup/Doctor; P2 |
| AF15 | Testes de permissões, agenda, recuperação e bot | backend/tests/ — 11 módulos inventariados | V inventário | Melhorar disciplina de evidência; nenhuma suite executada |

Licença incerta bloqueia a opção “copiar” em todos os AF. O estudo de ideias permanece distinto de portar implementação.

### 5.3 Fluxo de tarefa e recuperação

A submissão grava tarefa queued; o serviço valida relação com tarefa anterior e reaproveita session ID ao continuar. Faz claim queued → starting antes de resumir sandbox e preparar CLI/hook. Após iniciar comando remoto, persiste process_id e acompanha conclusão. Resultado usa saída JSON e recuperação de log quando stdout é truncado. Fonte: [task_execution_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/task_execution_service.py).

Há recuperação de queued órfão e limite para starting prolongado. A decisão de marcar falha quando a inicialização ficou incerta não prova que o processo externo deixou de existir. **H:** no SENTRA, esse caso deve conservar Operation UNCERTAIN até receipt/reconciliação, sem duplicar ação. Também não se demonstrou serialização transacional completa de duas continuações simultâneas da mesma sessão. Isso exige revisão futura, não exploração nesta pesquisa.

routers/task.py usa identificadores recebidos do cliente; as rotas examinadas não acrescentam autenticação de dono. Fonte: [task.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/routers/task.py). O fato de o backend validar vínculo entre IDs de tarefa não corrige identidade controlada pelo chamador.

### 5.4 Agenda: contribuição real e limite de entrega

schedule_service.py traduz cron/timezone, trata convenções de dia da semana e calendário, usa FOR UPDATE SKIP LOCKED para claim e avança next_run junto à ocorrência. Evita sobreposição com tarefa ativa, aplica janela de atraso e pausa em falhas repetidas/necessidade de intervenção. Essas decisões são referência útil para especificar a agenda SENTRA. Fonte: [schedule_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/schedule_service.py).

O report marca reported_at antes do envio. notification_service retorna falso em falha/ausência de bot. **H sustentada por leitura estática:** crash ou falha de envio nessa janela pode perder notificação; não se comprovou “entrega exatamente uma vez”, embora o README use linguagem semelhante. Fonte: [notification_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/notification_service.py). A distinção é entre claim único de tentativa e confirmação durável da entrega.

Proposta SENTRA: ocorrência gera WorkItem sob a mesma Run, Operation autoriza efeito e outbox aguarda receipt identificável. Janela de atraso, pausa, custo e sobreposição são política do control plane, sem outro APScheduler autoritativo.

### 5.5 Permissões e threat model específico

**Gate humano incompleto — V.** A rota de check do hook verifica shared bearer, mas as rotas de consulta/resposta de aprovação examinadas não autenticam um proprietário independente. Token do sandbox e decisão humana são autoridades diferentes. Fonte: [routers/permission.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/routers/permission.py).

**Efeito remoto exposto — V.** sandbox.py inclui endpoint /{box_id}/test-write-file que chama Boat para escrever path/conteúdo fornecidos. Não há gate de dono visível na rota/composição examinada. Stop/resume e fluxos de auth também precisam de identidade real. Fonte: [sandbox.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/routers/sandbox.py). Se esse backend for exposto pelo túnel recomendado, CORS não impedirá cliente não navegador de chamá-lo. Não se acessou endpoint em execução.

**Allow once e always — V/H.** O serviço registra pedido pendente, espera resposta e nega após deadline; regras persistentes podem evitar futuras perguntas. Não se demonstrou fencing físico nem consumo de Grant sob owner comprovado. A concorrência answer/expiry merece validação; não se afirma exploit confirmado. Fontes: [permission_ask_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/permission_ask_service.py), [permission_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/permission_service.py).

**Classificador inadequado como fronteira — V/H.** github_classifier.py separa segmentos por operadores simples e reconhece comandos Git; segmentos não Git podem não determinar a classificação. Verbos amplos como branch, remote e fetch não equivalem sempre a ausência de mutação; flags/config/aliases ampliam comportamento. **H:** classificar “git status; outra ação” como leitura não torna o shell seguro. Não se executou exemplo ou exploração. Fonte: [github_classifier.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/github_classifier.py). A alternativa futura é catálogo exato de operações/argumentos e executor limitado, não uma allowlist baseada em texto.

**Hook dentro do sandbox — D/H.** O PermissionRequest descrito pelo README é configurado em arquivo do ambiente que executa a tarefa. **H:** aprovação de write/shell ampla pode atingir a própria configuração do hook; esse desenho não prova enforcement externo ao agente. Fonte: [README.md](https://github.com/Anil-matcha/open-dots/blob/main/README.md). Evitar tratar hook de CLI como equivalente ao DurableOperationGate.

**Cifra não resolve identidade — V.** crypto.py usa MultiFernet; chaves vêm de configuração. Isso permite rotação, mas não é atestação de conta nem vault Windows. Perda/exposição da chave muda o risco dos registros cifrados. Fonte: [crypto.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/core/crypto.py). Esta pesquisa leu exclusivamente código público; nenhum valor de segredo, arquivo de credenciais ou cookie foi aberto.

### 5.6 Instalação, persistência e lacunas

O README orienta Postgres em Docker, serviços API/bot/frontend e sandbox Boat, com callback público para decisão. O script de desenvolvimento instala dependências e migra DB; **não foi executado**. Limitações documentadas incluem ausência de limpeza automática de sandboxes e falta de autenticação Web real. Não se confirmou publicação de instalador desktop, updater ou Doctor. Fonte: [README.md](https://github.com/Anil-matcha/open-dots/blob/main/README.md).

Há referências a logs estruturados, migrações e armazenamento criptografado, mas não se auditou backup/restore, retenção, toda a hierarquia ORM ou observabilidade distribuída. Não se demonstraram MCPB, OAuth genérico de conectores, editor/PDF, voz, multiagent orchestration, conta/modelo Web observado ou quota real de plano. A compatibilidade é semântica em recursos isolados, não equivalência de produto.

Documentação diverge do inventário de testes: README/backend README dizem cobertura muito menor ou ausente; a árvore HEAD contém 11 módulos, inclusive task/sandbox/schedule. A contagem de arquivos não prova cobertura, mas prova que a documentação não descreve adequadamente o inventário atual.

## 6. feder-cr/invisible_dots

**Aviso de proveniência:** não há SHA raiz verificado nem inventário completo local. Caminhos e comportamentos abaixo vieram de código/documentação públicos main. Arquitetura grande foi lida em recortes; não integralmente.

### 6.1 Organização e stack

O layout documentado inclui apps/api, scheduler, vm-manager, web e cli; packages/shared, database, events, channels, sdk e iso; guest/dot-agentd e image-builder; invisible_engine_dots; virtualization e testes. Um host composto coordena fila/eventos/VMs, e o raciocínio roda no guest. Fonte: [docs/architecture.md](https://github.com/feder-cr/invisible_dots/blob/main/docs/architecture.md).

Manifesto raiz declara Node >=24, TypeScript 7 e Vitest 5. API usa Fastify 5; web usa Next 16.3.8, React 19.3, Radix e Tailwind 4. Versões declaradas não provam versões efetivamente instaladas. Fontes: [package.json](https://github.com/feder-cr/invisible_dots/blob/main/package.json), [apps/api/package.json](https://github.com/feder-cr/invisible_dots/blob/main/apps/api/package.json), [apps/web/package.json](https://github.com/feder-cr/invisible_dots/blob/main/apps/web/package.json).

Guest tem daemon Go e engine Python hard fork de nanobot. A base exclui vários recursos upstream e usa caminho restrito de browser, com OpenRouter como provider descrito. Não se deve atribuir ao fork todas as capacidades do nanobot original. Fonte: [invisible_engine_dots/UPSTREAM.md](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/UPSTREAM.md).

### 6.2 Índice funcional por caminho

Para diretórios/documentação, o grau D é explícito: não significa leitura de todos os módulos internos.

| ID | Capacidade / limite | Caminho principal | Evidência | Decisão / compatibilidade / prioridade |
|---|---|---|---|---|
| FF01 | Host API e projeções de estado | apps/api/src/server.ts | V público | Adaptar contratos/receipts; não criar outro control plane; P1 |
| FF02 | CLI e SDK de acesso ao host | apps/cli; packages/sdk; docs/guide.md | D | Exigir adaptação ao contrato CLI SENTRA; P2 |
| FF03 | VM por Dot e runtime separado da imagem | apps/vm-manager/src/qemu-args.ts; docs/architecture.md | V/D | Executor opcional de alto custo; P2 |
| FF04 | Daemon privilegiado e contas guest separadas | guest/dot-agentd; docs/architecture.md | D, código incompleto | Exige auditoria própria, não presumir isolamento absoluto; P0 |
| FF05 | Política única de tools e fallback restritivo | invisible_engine_dots/nanobot/dots/permissions.py | V público | Referência para exposição mínima; média/alta; P1 |
| FF06 | Approval durável e argumentos canônicos | invisible_engine_dots/nanobot/dots/gate.py | V público | Adaptar vínculo à Operation/Grant; alta conceitual; P0 |
| FF07 | Transcript + outbox na mesma transação | invisible_engine_dots/nanobot/dots/transcript_outbox.py | V público | Adaptar contrato de receipts; alta conceitual; P0 |
| FF08 | Persistência host, eventos e scheduler | packages/database; apps/scheduler; docs/architecture.md | D | Investigar protocolo; não importar DB autoritativo; P0 |
| FF09 | Tools de arquivo, execução e browser delimitados | permissions.py | V público | Compatibilizar capacidade e Grant exatos; P1 |
| FF10 | Memória e Skills no guest | invisible_engine_dots/UPSTREAM.md; docs/guide.md | D | Não equiparar a SkillPack pinado/revisado; P2 |
| FF11 | Browser persistente por identidade | SECURITY.md; docs/guide.md | D | Privacidade e limpeza explícitas; não prova conta Web SENTRA; P0 |
| FF12 | Cron e retomada de automações | docs/guide.md; arquitetura em recorte | D | Comparar política com Goal/WorkItem; P1 |
| FF13 | Telegram e WhatsApp opcional no host | docs/guide.md; THIRD_PARTY_NOTICES.md | D | Adiar; canais e licença ampliam custo; P2 |
| FF14 | HTTP assíncrono, cancelamento e SSE | apps/api/src/server.ts | V público | Adaptar estados claros de aceitação/conclusão; P1 |
| FF15 | UI, tool labels e aprovação | THIRD_PARTY_NOTICES.md; apps/web/package.json | D proveniência/V manifesto | Selecionar componente e licença por arquivo; P1 |
| FF16 | Golden image, runtime e atualização manual | docs/guide.md | D | Não atende release Windows SENTRA sozinho; P2 |
| FF17 | Gates CI multi-stack e execução opt-in | .github/workflows/tests.yml | V configuração | Referência de gate; não prova VM Windows instalada; P1 |
| FF18 | Hard fork e inventário de terceiros | invisible_engine_dots/UPSTREAM.md; THIRD_PARTY_NOTICES.md | V documental | Orçamento de manutenção/legal antes de copiar; P0 |

### 6.3 Fluxo API, execução e aprovação

**API.** server.ts autentica requests com bearer e comparação em tempo constante baseada em digest, limita corpo/paginação e expõe submissão assíncrona, cancelamento, computador, eventos e Doctor. HTTP 202 significa aceitação, não conclusão de efeito. SSE mantém heartbeat. Fonte: [server.ts](https://github.com/feder-cr/invisible_dots/blob/main/apps/api/src/server.ts). O futuro adapter SENTRA teria de apresentar estado do control plane existente; um token desse host não é Grant humano por operação.

**Política.** permissions.py centraliza mapa de ferramenta/capacidade, defaults e validação. Unknown não vira acesso implícito. Ferramentas cobrem execução, arquivos, cron e browser; as categorias allow/ask/deny continuam amplas em comparação a Grant ligado a operação e alvo específicos. Fonte: [permissions.py](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/nanobot/dots/permissions.py). A ideia útil é impedir divergência entre tools expostas e tools autorizadas.

**Aprovação.** gate.py registra pedido e argumentos canônicos, suspende a continuação e, após resposta válida, muda estado para execução; o restante de um lote não deve escapar enquanto há pendência. Registros interrompidos preservam diferença entre não executado e resultado desconhecido. Fonte: [gate.py](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/nanobot/dots/gate.py). É contribuição forte para A04/A10/A16, mas não demonstra prova independente de owner Web ou fencing no efeito físico externo.

**Entrega.** transcript_outbox.py grava mudanças de transcript e eventos na mesma transação, com IDs/origens e metadados de ferramenta apropriados ao transporte. Isso evita construir a entrega somente a partir da memória do processo. Fonte: [transcript_outbox.py](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/nanobot/dots/transcript_outbox.py). Adaptação futura precisa conservar os IDs SENTRA e aguardar receipt Web; durabilidade de outbox não significa entrega final ou execução exatamente uma vez.

**Host ↔ guest — D.** Arquitetura descreve DB host PGlite/Postgres, locks de instância/ordem, sequência de eventos e handshakes antes de liberar credenciais. Também distingue usuário Stop de retomada automática e declara UI local sem login própria. Esses protocolos precisam ser confrontados com código ainda não lido. Fonte: [architecture.md](https://github.com/feder-cr/invisible_dots/blob/main/docs/architecture.md). Não se confirmou o schema/transação completo de database ou scheduler.

### 6.4 VM e permissões físicas

qemu-args.ts monta uma linha de QEMU, restringe formas de caminho, usa host forwarding em loopback, discos distintos e seleção de acelerador. Essas opções são evidência concreta de desenho de VM, não benchmark de isolamento ou compatibilidade WHPX desta máquina. Fonte: [qemu-args.ts](https://github.com/feder-cr/invisible_dots/blob/main/apps/vm-manager/src/qemu-args.ts).

A documentação descreve contas guest separadas, credenciais fora do usuário das tarefas e auxiliares privilegiados delimitados. Também reconhece acesso de rede do guest a serviços host e ausência de alguns limites internos. Fonte: [SECURITY.md](https://github.com/feder-cr/invisible_dots/blob/main/SECURITY.md). Código completo do daemon Go, filesystem e gestão de processo não foi obtido: traversal, kill de PID reusado, quotas e secret handoff continuam pendências de auditoria.

**H de compatibilidade:** VM pode reduzir exposição do host, mas não substitui autorização. Se adotada futuramente, precisa ser executor subordinado: Run/WorkItem/Operation/Grant do SENTRA, identidade de processo/handle, receipt durável e encerramento apenas dos recursos comprovadamente pertencentes. Não se deve copiar uma rotina de GC baseada apenas em PID/documentação.

O custo relativo é alto: hipervisor disponível, memória e disco por Dot, imagem base, atualizações OS/browser, logs, backup e suporte Windows/Linux. Não se mediram CPU/RAM/latência e não se provisionou VM. O recurso não deve entrar no P0 do produto por parecer mais “autônomo”.

### 6.5 Browser, memória, canais e privacidade

O guia descreve perfis persistentes de browser, memória/Skills locais do guest, jobs cron, canal Telegram e WhatsApp opcional. Atualização é manual; imagem base e runtime têm ciclos diferentes. Fonte: [guide.md](https://github.com/feder-cr/invisible_dots/blob/main/docs/guide.md). Essas capacidades não comprovam A21, backup integral ou atualização staged de desktop.

invisible_engine_dots/UPSTREAM.md documenta remoção de CLI/canais e outras ferramentas do nanobot original, mantendo controle de canais no host. Browser usa caminho específico em vez de MCP genérico irrestrito. Fonte: [UPSTREAM.md](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/UPSTREAM.md). Assim, “tem MCP de browser” não equivale a lifecycle MCPB/OAuth de conectores do SENTRA.

**D/H:** mecanismos de identidade/fingerprint do browser são divulgados como capacidade de evitar bloqueios. Não foram validados, e sua adoção como evasão padrão é rejeitada. Browser persistente contém material sensível; a aprovação de digitação e argumentos de ferramentas exige redaction. Ausência de telemetria própria também não elimina tráfego de modelos, canais e browser. O guia informa chamadas externas de infraestrutura de browser. Não se consultaram cookies ou perfis reais.

**H de produto:** memória e Skills geradas pelo agente só podem tornar-se SkillPack SENTRA após revisão, revisão Git fixada, manifesto de capacidade e concessão explícita. Canal externo precisa de owner binding, mínimo conteúdo e confirmação de entrega própria; não herda prova da conversa ChatGPT.

### 6.6 Publicação e risco upstream

O projeto documenta estado alpha e distribuição de imagem, não release instalado equivalente ao SENTRA. Atualizar código/runtime não demonstra migrar imagem existente, rollback de esquema ou preservar sessão de browser. Não se comprovou MSI assinado, RBAC de equipe, operação multi-host ou snapshot/restore completo. Fonte: [guide.md](https://github.com/feder-cr/invisible_dots/blob/main/docs/guide.md).

O hard fork declara que não acompanha merges upstream automaticamente. Correções de engine, compaction, ferramentas e adapters passam a ser responsabilidade do mantenedor. Fonte: [UPSTREAM.md](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/UPSTREAM.md). Uma cópia ampla criaria responsabilidade semelhante no SENTRA; adaptar contratos menores reduz dependência de roadmap externo.

A licença e o checklist de CI são mais explícitos que os do Anil, mas não compensam SHA raiz ausente nesta pesquisa. Antes de qualquer cópia futura, pin completo, textos aninhados e pacote efetivamente redistribuído são gates obrigatórios.



## 7. Compatibilidade com a arquitetura autoritativa SENTRA

### 7.1 Contratos que não podem ser substituídos

A análise abaixo é proposta H derivada dos quatro documentos SENTRA, especialmente a auditoria das sete frentes e o estudo CoS de 09/10. Não é avaliação de novas edições no checkout.

| Autoridade | Analogias upstream | Adaptação futura admissível | Critério de rejeição |
|---|---|---|---|
| **Run** | Thread/agent CopilotKit; sessão CLI Anil; conversa/task feder | Projeção do Run existente, preservando principal, workspace, lifecycle e continuidade | Criar Run paralelo com progresso ou cancelamento divergente |
| **WorkItem** | Task agendada ou fila de prompts | Usar ocorrência/objetivo como entrada do WorkItem central e referenciar IDs originais | Worker upstream reivindicar tarefa fora do orçamento/ownership central |
| **Operation** | Chamada MCP/computer; comando Boat; tool guest | Intenção persistida antes do efeito, argumentos/target exatos, claim/fencing e receipt | Tratar HTTP 202, stdout do modelo ou status local como prova do efeito |
| **Grant** | Approval card, allow/ask/deny, rule persistente | Consentimento humano autenticado e ligado à Operation, capability, alvo, validade e revogação | readOnlyHint, always allow, token de sandbox ou trust de chat criarem autorização física |
| **Canvas** | Páginas/editor, cards e dashboards | Projetar estado/read APIs autoritativos com ARIA, revisão e receipt verificável | Outro listener privilegiado, DB de aprovação ou botões que contornem auth |
| **CLI** | Scripts npm, Claude CLI remoto, CLI feder | Cliente do contrato central, status e aprovação owner-bound; ConPTY permanece owned | Substituir terminal persistente por exec remoto ou encerrar processo apenas por PID |

A premissa vale também para Scheduler, Skills e MCP: exposições e adapters podem variar; autoridade não. Biblioteca UI não precisa trazer junto runner, storage ou framework de agentes.

### 7.2 Comparação direta de funcionalidades relevantes

| Eixo | CopilotKit | Anil | feder | Implicação SENTRA |
|---|---|---|---|---|
| Unidade de organização | Space/Dot/Page/Thread | Usuário/box/task/session | Dot/VM/chat/task | Converter para projeções, sem equiparar identidades |
| Execução | Tools e serviço computer opcional | Boat + Claude CLI | Guest VM + daemon/engine | Custos e trust boundaries diferentes |
| Agenda | Intervalo após conclusão | Cron/timezone e ocorrência transacional | Cron documentado no guest/host | Escolher política explicitamente, não misturar semânticas |
| Aprovação | Pedido/argumentos persistidos | Hook + regra + prompt | Estado durável no gate | Nenhuma aprovação substitui Grant SENTRA |
| Persistência | SQLite local + Threads separado | Postgres + processos remotos | Host DB + guest DB/disco | Backup e receipt precisam atravessar camadas |
| Edição | Página rich/Markdown e revisão | Composer de tarefas | UI documentada/derivações de diff | Priorizar project_review já existente |
| Browser | Serviço de consulta e computer | Não demonstrado como subsistema próprio | Browser guest persistente | Nenhum prova conta da extensão Edge instalada |
| Extensibilidade | MCP HTTP, learning e SDK | Regras/serviços e bot | Tools definidos, fork/SDK/canais | MCPB/SkillPack SENTRA continuam específicos |
| CLI instalada | Não demonstrada | Não demonstrada | Documentada, implementação incompletamente auditada | Não usar como argumento de paridade |
| Multiusuário | Principal único | IDs de usuário sem auth real | Local single-host documentado | Identidade/RBAC não são intercambiáveis |

### 7.3 Incompatibilidades semânticas decisivas

- **Thread ID ≠ mensagem Web atestada.** É identidade de conversa do framework; não prova origem/browser epoch.
- **Outbox ≠ receipt final.** Commit de evento prova intenção durável; não prova que ChatGPT recebeu.
- **Aprovação da aplicação ≠ cartão do ChatGPT.** Espera humana da página tem estado e autoridade próprios.
- **Permissão da tool ≠ isolamento físico.** Mapa allow/ask não limita automaticamente filesystem, rede ou filhos do processo.
- **Skill gerada ≠ revisão Git aprovada.** Conteúdo aprendido pode ser prompt injection persistente.
- **VM/container ≠ quota e DLP.** Rede/segredos e permissões internas continuam relevantes.
- **Provider API ≠ conta/plano/modelo Web observado.** Configurar nome de modelo não constitui atestado da sessão.
- **Testes em harness ≠ instalação homologada.** Esse limite também se aplica ao SENTRA.

## 8. Matriz completa das 34 entradas G/A

**Base S:** SENTRA_AUDITORIA_INTEGRAL_SETE_FRENTES_VS_COS_2026-10-10.md e SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md; atualização PDF conforme retomada relida. L = declarado localmente implementado/testado; P = pendência de integração/instalação; B = bloqueado. São estados documentais, não novos resultados.

CF/AF/FF referenciam os índices e seus caminhos. **N** significa não demonstrado no recorte, não afirmação universal de ausência. A prioridade é do próximo passo SENTRA proposto, podendo elevar um requisito por ser gate de outros trabalhos. Em nenhuma linha se afirma cobertura integral.

| Entrada / estado S | CopilotKit | Anil | feder | Compatibilidade e ação futura | Prioridade |
|---|---|---|---|---|---|
| **G01 — MCPB lifecycle / L/P** | CF10: MCP HTTP, sem lifecycle MCPB completo | N | FF09: browser restrito, não catálogo MCPB genérico | Média só para discovery/status; manter ZIP/stdio/OAuth PKCE/vault/supervisor central e provar uninstall/restart real | P0 |
| **G02 — conta/modelo/effort/Automatic / P** | CF01: provider configurado | AF04: login Claude, diferente conta | FF01: provider OpenRouter descrito | Baixa; nenhum atesta picker/conta ChatGPT. Não inferir plano ou trocar modelo silenciosamente | P0 |
| **G03 — Compact & Resume / L/P** | CF07: Threads/contexto | AF06: session-id/resume | FF10: engine fork/compaction | Média semântica; continuidade Web A→B só após receipt, mesma Run/WorkItem, sem atribuição por horário | P0 |
| **G04 — entrega Web/outbox / L/P** | CF11: claim/receipt MCP, distinto | AF12: janela de perda de report | FF07: outbox transacional | Alta ideia feder; conservar ciphertext/IDs/epoch, produtor/relay/host reais e UNCERTAIN sem retry | P0 |
| **G05 — Goal/Loop/workers / L/P** | CF14: runner/lease | AF07/11: recuperação/agenda | FF03/08/12: VM/fila documentadas | Média; aproveitar pausa/ownership, não importar scheduler. Validar orçamento, cancelamento e GC físico | P0 |
| **G06 — terminal persistente / L/P** | CF12: shell de serviço | AF06: comando remoto | FF09: exec guest | Baixa como substituto; ConPTY Start/Write/Close com handle owned e API owner-auth continua obrigatório | P0 |
| **G07 — Skills versionadas / L/P** | CF17: learning/containers | N | FF10: Skills guest | Média para discovery; rejeitar ativação aprendida sem revisão SHA, ACL, update/revoke e rollback | P1 |
| **G08 — API read/action opt-in / L/P** | CF19/11: bearer/aprovação | AF02/09: autenticação insuficiente | FF01/06: bearer/policy | Média; ação exige duas provas e clique owner real, limits/rate/deadline por endpoint | P0 |
| **G09 — Setup/Doctor/repair / L/P** | CF01/22: setup de template | AF14: script dev | FF02/16: Doctor/instalação manual | Baixa para release; preservar Doctor SENTRA, reparar por etapa e homologar Setup/MSI contemporâneo | P0 |
| **G10 — editor/diff/PDF / L/P** | CF03–06: melhor referência de página | N | FF15: UI/diff com terceiros | Alta para UX; PDF central local já declarado integrado, ainda precisa prova instalada e dependência renderer | P1 |
| **G11 — allowlist de comandos / P** | CF12: permissões amplas | AF10: parser não seguro | FF05/09: tool map | Média para catálogo, baixa para shell livre. Rejeitar classificação textual como autorização; validar quoting/filhos/limites | P0 |
| **G12 — observabilidade browser / L/P** | CF09: consulta/computer | N | FF11: browser guest | Baixa para objetivo; screenshot/URL não prova request/message/epoch/conta do Edge. Preservar BrowserEvidence | P0 |
| **G13 — UX acessível / L/P** | CF04/06/20: atalhos/status/tema | AF09/13: cards/polling | FF15: componentes web | Alta como referência; validar leitor de tela, WebView2, DPI físico, foco e performance real | P1 |
| **A01 — join MCP↔mensagem↔epoch/doc / L/P** | CF18: escopo thread, insuficiente | N | FF07: IDs de transcript, outra origem | Baixa; nenhuma fonte resolve join Web. Guard deve cobrir toda chamada MCP instalada | P0 |
| **A02 — bloquear chat específico / L/P** | CF18: escopo lógico | AF08: regra de usuário | FF06: gate do Dot | Média ideia; chat block central prevalece, sem bloquear outros chats/WorkItems ou aceitar chamada tardia | P0 |
| **A03 — ChatTrust/default deny / L/P** | CF18/10: scope; annotation não é trust | AF02: identidade cliente inadequada | FF05: deny no tool map | Média; exigir proveniência, unknown nega, sucessor só herda após prova e trust nunca cria Grant | P0 |
| **A04 — esperar aprovação humana ChatGPT / P** | CF11: card da aplicação | AF09: prompt web/Telegram | FF06: aprovação própria durável | Média para WAITING, baixa para integração Web. Não resolver com reload/envio repetido | P0 |
| **A05 — app/plugin comprovado na conta / L/P** | CF10: conexão registrada | AF04: outro OAuth | FF01: token de API própria | Baixa; separar ready/tunnel/app-observed/tools-authorized/version-current com prova independente | P0 |
| **A06 — refresh schemas na conta / L/P** | CF10: discovery MCP | N | FF05: tools estáticas | Média catálogo local; validar cache/refresh no cliente ChatGPT instalado, versão e respostas tardias | P0 |
| **A07 — superfícies mínimas por domínio / L/P** | CF10: namespaces/limites | AF01: routers por serviço | FF05: mapa restrito | Alta conceitual; projetar subsets na mesma autoridade, sem novos control planes/túneis desnecessários | P1 |
| **A08 — QuickJS WASM limitado / B** | N; Node/agent não serve de prova | N; CLI não serve | N; guest engine não serve | Baixa; manter desabilitado até SHA/SBOM, fuel/CPU/mem/IO e cada tool sob Operation/Grant | P0 gate |
| **A09 — extensão instalada/pareada/login / B/P** | CF09 não é MV3 | N | FF11 não é Edge pareado | Baixa; observação real por perfil/conta, logout/revogação/restart, sem cookies | P0 |
| **A10 — consentimentos read/action / L/P** | CF11/12: booleans e cards | AF08/09: regras sem owner gate | FF05/06: allow/ask/deny | Média; callback ligado à sessão e clique real, alvo/escopo exatos e revogação em execução | P0 |
| **A11 — busca textual de conversas / L/P** | CF02: biblioteca de páginas, diferente | AF13: lista de tasks | FF07: transcript, busca não verificada | Média só para UX; índice opt-in com ACL/provenance e deep link, não indexar segredos | P1 |
| **A12 — anexos/chunks/upload receipt / L/P** | N no fluxo Web alvo | N | FF09: arquivos guest, não upload Web | Baixa; ref por WorkItem/Grant e receipt de anexo na conversa real, limites/formato/quota | P1 |
| **A13 — streaming por message ID / L/P** | CF07/15: AG-UI/transcript | AF13: polling de task, não streaming Web | FF07: eventos/transcript transacional | Alta ideia; identidade e revisão por mensagem Web, overflow referenciado e restart observado | P1 |
| **A14 — quota observada na conta / P** | CF01: uso provider, outra métrica | N | FF01: custo API, outra métrica | Baixa; separar accounted de observed, frescor e conta independente; não inferir quota Web | P1 |
| **A15 — diagnóstico anonimizado / L/P** | CF22: opt-out não é anonimização | Logs não demonstram export redigido | FF01: Doctor não prova anonimização | Média; preview/export com remoção de paths/hosts/URLs/nomes, retention/exclusão no instalado | P1 |
| **A16 — recibos humanos uniformes / L/P** | CF11/12/15: cards e registros | AF06/12: status/output | FF07/14/15: eventos/tool labels | Alta; derivar do receipt real: alvo, duração, status, exit, alterações, sem segredo ou inferência do modelo | P1 |
| **A17 — GC de recursos próprios / L/P** | CF14: lease/cancel | AF03: cleanup ausente documentado | FF03/04: gestão VM, auditoria pendente | Média semântica; cleanup por ownership/handle, crash/restart e UNCERTAIN, nunca PID-only | P0 |
| **A18 — Git/diff/watch revisions / L/P** | CF03/05: revisão de página | AF10: classificação não é diff | FF15: diff derivado de outro repo | Alta para estados; API Git/watcher real, CAS/debounce/rename, watcher nunca concede write | P1 |
| **A19 — updater staged / L/P** | CF13: pin de serviço, sem desktop updater | AF14: dev script | FF16: atualização manual | Baixa; updater SENTRA mantém integridade/assinatura, coordena schema/MCPB/extension e rollback sem interromper terminal | P0 gate/P1 UX |
| **A20 — export Markdown / L/P** | CF06: export de página, diferente sessão | AF06: output, export não demonstrado | N para export Web selecionado | Alta para affordance; exportar conversa/mensagem comprovada, overflow e redaction opcional | P2 |
| **A21 — SkillPack Git-pinned / L/P** | CF17: learning, não pin | N | FF10: SKILL.md, não prova pin | Média discovery; SHA completo, teto de arquivos/tamanho, review e update/revoke no WorkItem | P2 |

**Contagem conferida:** 13 entradas G + 21 entradas A = 34. A matriz não declara 34 recursos concluídos. Em particular, G02/G12 e A01/A05/A06/A09/A14 dependem de evidência Web real ausente nesta pesquisa.

## 9. Threat model, dependências e publicação

### 9.1 Ativos e adversários

Ativos relevantes: arquivos/workspaces SENTRA, identidade da conta, credenciais de providers/conectores, histórico e anexos, Grants, receipts, processos/terminais owned, banco central e release instalado.

Adversários considerados como H de integração: conteúdo de página/arquivo/Skill com prompt injection; MCP malicioso; cliente local sem autorização; caller externo do túnel; tool comprometida; supply chain; reexecução/replay após crash; usuário/WorkItem que tenta acessar recursos de outro. Não houve pentest.

| Fronteira | Evidência de alerta | Risco futuro | Gate de adoção |
|---|---|---|---|
| Modelo → tool | CF10 annotations; AF10 classifier; FF05 categories | Confundir sugestão/classificação com permissão | Catálogo exato + Operation/Grant + executor limitado |
| Browser/CLI → principal | AF02 identidade local; CF18 Threads; FF11 perfis | Atribuição incorreta de conta/conversa | BrowserEvidence independente; unknown deny |
| Humano → aprovação | CF11 hipótese de consumo; AF09 owner gate | Replay, resposta sem owner, mudança de args | Grant imutável vinculado à operação/argumentos; consumo atômico |
| Claim → efeito externo | CF14 lease; AF07 starting; FF06 interruption | Duplicação física após perda de resposta | Persistir intenção; UNCERTAIN; reconciliação por receipt |
| Estado → entrega | AF12 report; FF07 outbox | Notificação perdida ou ACK confundido com efeito | Receipt de destinatário/origem, retries apenas onde seguros |
| Host → sandbox/VM | CF12/OpenBot; AF03 Boat; FF03/04 | Escape, serviços loopback, segredos e filhos | Ownership físico, limites/rede/paths e audit do executor |
| Skills → ferramentas | CF17/FF10 learning | Prompt injection persistente | Revisão/pin/proveniência; Skill não concede Grant |
| Persistência → backup | CF01 Threads separados; AF05 keys; FF08 host/guest | Backup parcial, segredo órfão, restore inconsistente | Plano integrado de chave/DB/artifact e ensaio autorizado futuro |
| Build → usuário instalado | CF21/FF17 CI; AF14 dev | Release distinto do checkout, dependência adulterada | Pin/hash/SBOM/notices, assinatura legítima, clean install e rollback |
| Diagnose → compartilhamento | CF22 e Doctor FF01 | Vazamento de paths/identidade/argumentos | Redaction com preview, retenção e consentimento |

Os mecanismos centrais de SENTRA já descritos devem ser reforçados por casos negativos, não substituídos por outro “permission engine”. Fonte do requisito: documentos S de sete frentes e CoS, não uma promessa upstream.

### 9.2 Dependências e impacto operacional

| Projeto | Superfícies de dependência | Risco/custo relativo | Limitação da revisão |
|---|---|---|---|
| CopilotKit | SDKs CopilotKit/AG-UI/TanStack, provider, TipTap, MCP, browser, opcionais computer/Slack/voice | Médio; alto se Intelligence e serviços conectados forem requisitos | Manifesto lido; lock e licenses transitivas não auditados integralmente |
| Anil | Python muito recente, Boat, Claude CLI, OAuth, Postgres, Telegram, Next | Médio/alto; preço e lifecycle do sandbox externos | Manifests e serviços chave; SDK/CLI remoto e termos não auditados |
| feder | Node/Next, Go, Python fork, QEMU/OS/browser, DB, imagens, canais | Alto em suporte e supply chain; VM/guest adicionam duas camadas de atualização | Sem root SHA; manifests selecionados; imagem e cadeia nativa não inspecionadas |

Não se pesquisou banco CVE completo nem se rodou npm audit/pip audit: nenhuma instalação ou execução upstream foi autorizada. Não se declararam dependências “sem vulnerabilidades”. A pré-condição futura é inventário do **grafo efetivo e binários distribuídos**, não somente package.json.

Custos de provider, Boat, Intelligence, voz e infraestrutura não foram cotados. Nada neste estudo garante disponibilidade comercial, conta elegível ou termos permanentes. Adotar opcional com interface degradável evita impor esses serviços a todo usuário SENTRA.

### 9.3 Compliance e dados

A autorização para ler fontes públicas não autoriza coletar histórico, anexos, cookies ou credenciais dos usuários. O produto futuro deve separar prova mínima de estado da conta de dados de autenticação; guardar provenance e consentimento, não cópia de sessão.

Transferências para providers/pesquisa/canais dependem de finalidade e contexto de uso. Exigem política de retenção/exclusão, informação ao usuário e avaliação dos termos aplicáveis. Não se conclui conformidade LGPD/GDPR a partir de “self-hosted”. A missão não auditou contratos, subprocessadores, DPA, bases legais ou operação produtiva.

Cópia futura de componentes exige o license gate da seção 3. Não autorizar scraping/evasão de browser por um projeto alegar capacidade técnica. O caso de uso SENTRA deve priorizar integração observável e permitida pelo proprietário.

## 10. Design e plano futuro, sem implementação

### 10.1 Design minimalista Apple/OpenAI

Proposta H de experiência: uma área de trabalho principal, navegação compacta e inspector opcional. A informação persistente é tarefa/documento atual, estado de autorização e resultado. O restante aparece sob demanda, sem ilustrações, mascotes, diagramas animados ou mosaicos de agentes.

- **Estado curto e verdadeiro:** “Salvo”, “Conflito”, “Aguardando sua aprovação”, “Interrompido”, “Resultado ainda não confirmado”. Nunca “Concluído” a partir de texto do modelo.
- **Um receipt por Operation:** frase curta com ferramenta/target e resultado; detalhes expandem duração, exit code, revisão, evidência e artifact. IDs técnicos permanecem no detalhe.
- **Consentimento contextual:** ação, alvo, alcance e validade junto do botão; leitura e ação são decisões diferentes. Sem “sempre permitir” genérico como padrão.
- **Revisão focada:** documento/diff e versão esperada; source/Markdown como fallback. PDF e terminal pertencem ao mesmo Canvas, com gates próprios.
- **Recuperação acessível:** erro não apaga draft; foco preservado; teclado, status ARIA, reduced motion e contraste. Tema escuro é complemento, não certificado de acessibilidade.
- **Opcionais discretos:** voz/Slack/Telegram/VM não ocupam a primeira tela nem são pré-condição para usar o produto.

Referências upstream escolhidas: CF03–06/20 e FF15. A expressão visual deve seguir os componentes SENTRA; não portar um shell inteiro de outra aplicação.

### 10.2 Backlog de decisões: aproveitar, copiar, adaptar, melhorar ou rejeitar

“Copiar elegível” abaixo ainda depende de revisão/seleção jurídica e futura autorização de implementação. Nenhum código foi copiado nesta missão.

| Item | Decisão | Ganho esperado H | Custo / risco / legalidade | Compatibilidade | Prioridade |
|---|---|---|---|---|---|
| Autosave/version conflict e draft | Adaptar CF03–06; copiar elegível trecho MIT isolado | Menos perda de edição e feedback confiável | Baixo/médio; API de revisão existente; conservar notice | Alta | P1 |
| Tool labels e receipt compacto | Adaptar CF11/12, FF07/15 | Resultados verificáveis e UI menos ruidosa | Médio; redaction e origem dos terceiros por arquivo | Alta | P1 |
| Approval + args + consume | Melhorar contrato usando CF11 como alerta e FF06 como referência | Evitar replay e alteração pós-consentimento | Alto valor P0; pin/legal e teste de crash futuros | Alta conceitual | P0 |
| Outbox transacional | Aproveitar FF07; implementar originalmente no storage central futuro | Estado e entrega coerentes | Médio/alto; manter receipt Web e UNCERTAIN | Alta conceitual | P0 |
| Cron/occurrence/pause | Aproveitar AF11 como ideia, sem copiar | Agenda previsível e recuperação explícita | Médio; licença Anil não resolvida | Média/alta | P1 |
| Exposição mínima MCP | Adaptar CF10/FF05 ao MCPB existente | Menor disclosure e revisão mais simples | Médio; annotations não são autorização | Alta conceitual | P1 |
| Learning automático → Skill ativa | Rejeitar ativação automática; adaptar discovery somente | Revisão humana e manutenção de pins | Médio; prompt injection e backend externo | Média | P2 |
| Classificador shell do Anil | Rejeitar como gate; rótulo informativo apenas se original | Evitar falsa segurança | Risco alto; licença incerta | Baixa | P0 |
| ID localStorage / owner ausente | Rejeitar | Identidade real e consentimento válido | P0; não é refinamento cosmético | Nula como autoridade | P0 |
| Outra DB/Run/Grant upstream | Rejeitar como autoridade | Coerência de cancelamento, audit e custos | Importação ampla tem alto risco arquitetural | Baixa | P0 |
| VM por Dot | Investigar somente depois; executor subordinado | Isolamento opcional para casos definidos | Alto; QEMU/OS/guest/notices e suporte Windows | Média como adapter | P2 |
| Voice/Slack/Telegram | Adiar; canal autorizado opcional | Acesso adicional | Médio/alto; identidade/dados/licenças/receipts | Média | P2 |
| Browser antifingerprint/evasão | Rejeitar como objetivo padrão | Manter evidência e integração permitida | Risco operacional/termos alto | Baixa | P0 |
| CI com guard de testes coletados | Aproveitar FF17 | Detectar suites silenciosamente esvaziadas | Baixo/médio; custo contínuo; não garante E2E | Alta | P1 |
| Copiar frontend completo | Rejeitar importação ampla; selecionar padrões | Evitar dependências e UI paralela | Médio/alto; compatibilidade de componentes e notices | Baixa como shell | P1 |
| Desktop release upstream | Não tratar como solução; preservar release SENTRA | Primeira instalação e rollback reais | Alto gate; assinatura não pode ser simulada | Baixa | P0 |

### 10.3 Sequência e responsáveis das sete frentes

| Fase proposta | Responsável já definido nos documentos | Entrega futura reviewable | Dependência / aceite |
|---|---|---|---|
| **0 — pin/legal/proveniência** | Coordenador e responsável por release; pesquisa de apoio | HEADs completos, mapa de arquivos selecionados, licença/notices e SBOM do pacote candidato | Sem copiar Anil antes de licença; sem copiar feder sem root SHA |
| **1 — identidade e cadeia de autorização** | Frente 2 MV3/conta; frente 3 relay; coordenador; Codex ToolPolicy no seu escopo | Prova independente de conta/profile/epoch, join MCP e estados de app/schema/approval | Casos unknown, logout, concorrência, late call, ACK perdido; nenhuma autorização presumida |
| **2 — efeitos e recuperação** | Frente 4 executores/Code Mode e coordenador | Claim/fencing/receipt, estado UNCERTAIN, ownership físico e cancelamento real | Mesma Run/WorkItem/Operation/Grant; Code Mode permanece bloqueado sem gate de runtime |
| **3 — UX/revisão** | Frente 5 Canvas UX/PDF; rotas centrais pelo coordenador | Editor/diff/autosave/status/receipt uniforme e fallback/export | Conflito/CAS, auth HTTP, DPI/ARIA; PDF instalado não inferido dos 17 testes declarados |
| **4 — MCPB/Skills/agenda** | Frente 1 MCPB/Skills; executor/coordenador para agenda | Lifecycle e status mínimos, Skill pin/revoke; política de ocorrência/pausa | OAuth real, recovery/uninstall, nenhuma Skill cria Grant; agenda não duplica autoridade |
| **5 — release e diagnóstico** | Frente 6 instalador/release e coordenador | Setup/MSI contemporâneo, assinatura legítima, Doctor redigido, staged update/rollback | Primeira instalação limpa, browser pareado e fluxo ponta a ponta com evidência real |
| **6 — opcionais P2** | Responsável designado futuramente pelo proprietário | Estudo de VM/voice/canais com custo e termo explícitos | Produto principal homologado; executor/canal subordinado, sem nova autoridade |

A ordem não redefine propriedade dos arquivos. O documento de retomada reserva certas rotas/serviços centrais ao coordenador e server.py/tool_policy.py ao implementador extra. Essa distribuição deve ser respeitada em trabalho futuro.

### 10.4 Critérios de integração para FUTURO

Critérios abaixo são especificações de pesquisa, não testes criados/executados:

1. Duas conversas/tabs, conta trocada e chamada tardia não recebem atribuição por proximidade temporal.
2. Uma aprovação não autoriza outro alvo, argumentos alterados ou segundo efeito com identificador novo.
3. Crash antes/depois do envio separa “não executado” de “incerto”; nenhuma recuperação duplica efeito sem receipt.
4. Cancelamento/revogação prevalecem no executor; cleanup só toca recursos owned.
5. Estado salvo/conflito da UI deriva de revisão real, e erro preserva draft com ação acessível.
6. Export/diagnóstico remove segredos e identificadores escolhidos; anexos exigem confirmação da conversa correta.
7. Updater preserva versão funcional, schema e terminais; assinatura/pin/notices correspondem ao binário instalado.
8. O aceite de cada G/A identifica ambiente, fonte e limitação; testes locais não são promovidos a conta/browser instalado.

## 11. Testes, observabilidade e limites de cobertura

| Projeto | Evidência de teste examinada | O que não se pode concluir |
|---|---|---|
| CopilotKit | **48 módulos .test** no HEAD; CI com test/format/lint/typecheck/build; leitura de tests/computer.test.ts | Não são 48 testes individuais nem cobertura percentual; mocks não provam serviços conectados ou Windows |
| Anil | **11 módulos test_*.py** no HEAD; leitura do teste de github_classifier | Não prova suite verde, auth suficiente ou abrangência do parser/sandbox |
| feder | Workflow Node Ubuntu/Windows, DB, Go, Python, imagem/browser smoke, web e gates de coleta | Não houve execução; VM real/WHPX instalada não inferida do workflow |

No CopilotKit, o arquivo de teste de computer examinado cobre permissões default, auditoria/segredo, alvos/paths, cancelamento/revogação e limites. É evidência de intenção de proteção, não auditoria do OpenBot externo. Fonte: [computer.test.ts](https://github.com/CopilotKit/OpenDots/blob/main/tests/computer.test.ts). Os demais módulos foram inventariados, com alguns fetches falhos explicitados adiante.

No Anil, o teste de classifier cobre verbos e composições Git, sem estabelecer correção de um parser de shell geral. Fonte: [test_github_classifier.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/tests/services/test_github_classifier.py). Testes de agenda/recuperação existem no inventário; não foram lidos integralmente por esta pesquisa.

No feder, tests.yml chama guard que confronta execução/coleta com floors, além de build e jobs multi-stack. Isso detecta perda silenciosa de coleta, mas não mede qualidade dos assertions. Fonte: [tests.yml](https://github.com/feder-cr/invisible_dots/blob/main/.github/workflows/tests.yml). A documentação distingue ensaio de VM real de CI normal; logs/resultados contemporâneos não foram obtidos.

Observabilidade útil para o SENTRA é correlação por Run/WorkItem/Operation, estados e receipts, com redaction. Logs, transcript e SSE upstream são referências; não se demonstrou pipeline OTel/export de métricas completo em todos os projetos. Ausência de evidência aqui não prova ausência absoluta desse suporte.

O documento SENTRA de auditoria menciona suites locais anteriores; a retomada relata os 17 testes da rota PDF. **Nenhuma dessas suites foi executada pelo pesquisador**. Não houve build do SENTRA, consulta a serviço em uso, reinício de aplicação ou alteração de setup.



## 12. Checklist de fontes, evidência inspecionada e pendências

### 12.1 Documentos autoritativos SENTRA — somente leitura

Os hashes abaixo identificam os bytes consultados. Os três primeiros foram lidos na etapa documental; a retomada foi relida após atualização concorrente. A conferência final dos quatro hashes não detectou nova mudança desde o snapshot registrado. Não houve inspeção de cookies, tokens, arquivos de configuração privada ou outros documentos do checkout SENTRA.

| Documento | Bytes | SHA-256 |
|---|---:|---|
| [docs/SENTRA_COS_SETE_FRENTES_2026-10-10.md](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_COS_SETE_FRENTES_2026-10-10.md) | 16350 | 7c880f58396dc46e77e833d2bbf1cc1725d5e060b1a81a4069adac62e7792647 |
| [docs/SENTRA_AUDITORIA_INTEGRAL_SETE_FRENTES_VS_COS_2026-10-10.md](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_AUDITORIA_INTEGRAL_SETE_FRENTES_VS_COS_2026-10-10.md) | 19723 | 3ce78948ecb681ef0bdf01f3bbecab6c6171d0465bf384213973a43914701f03 |
| [docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md) | 35034 | e2286dd00c9eade7749747c3135b844e2bcfbaf8d04813dc90e5481f7cf4cf26 |
| [docs/SENTRA_COS_RETOMADA_7_FRENTES_OPEN_DOTS_2026-10-10.md](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_COS_RETOMADA_7_FRENTES_OPEN_DOTS_2026-10-10.md) | 7084 | dc9a8caf981b1abc78a5c4e0d5d7e5ed0ea481160bc00b9d1b9a0e06347d8f91 |

O modelo/effort solicitados pelo proprietário são gpt-6.1-sol/high. A retomada documental registra essa configuração nos terminais suplementares; este estudo não alterou modelo/configuração, nem tratou esse registro externo como medição independente do runtime.

### 12.2 Metadados Git e inventários

- [x] Verificação de git rev-parse HEAD nos dois diretórios existentes, contagem de commits, flag shallow e árvore HEAD.
- [x] Inventário completo de nomes/IDs de blobs das árvores CopilotKit (195) e Anil (108); isso não é leitura de todos os conteúdos.
- [x] Conferência de índice/worktree ausentes e falha de leitura local de blob; nenhuma conclusão de clone completo.
- [x] Tentativas de clone --filter=blob:none dos três destinos, com falhas registradas; feder sem HEAD verificado.
- [x] Comparação positiva de **20 arquivos públicos** com IDs Git de blob: 18 CopilotKit e 2 Anil. A comparação é de bytes reconstruídos; não houve fetch.
- [ ] Histórico suficiente dos três projetos; ancestralidade Git/fork entre eles.
- [ ] Árvore HEAD e SHA raiz feder.
- [ ] Grafo instalado/lockfiles completos, imagens/binários e licenças transitivas.

### 12.3 Fontes públicas obtidas

**M** = texto reconstruído com match positivo de blob no HEAD indicado; link fixa o commit verificado. **P** = fonte pública main sem vínculo byte a byte estabelecido. **R** = arquivo grande/documento examinado em recortes. “Disponibilizado” descreve o retorno da consulta; a revisão foi dirigida por arquitetura, fluxos e riscos. Não equivale a afirmar leitura semântica exaustiva de cada linha.

O ledger não inclui páginas de erro como fontes lidas. Fontes auxiliares oficiais e tentativas falhas vêm depois. Quando o documento é de arquitetura/guia/segurança, as capacidades continuam classe D mesmo com texto disponível.

| Repo | Caminho / fonte | Proveniência | Extensão da consulta |
|---|---|---|---|
| Anil-matcha/open-dots | [backend/app/core/config.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/core/config.py) | P | 57 linhas disponibilizadas |
| Anil-matcha/open-dots | [backend/app/core/crypto.py](https://github.com/Anil-matcha/open-dots/blob/3d8de1cd6657c6d70583f34b89c2dc034512c1ea/backend/app/core/crypto.py) | M | 15 linhas disponibilizadas |
| Anil-matcha/open-dots | [backend/app/main.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/main.py) | P | 46 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/app/routers/permission.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/routers/permission.py) | P | 116 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/app/routers/router.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/routers/router.py) | P | 12 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/app/routers/sandbox.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/routers/sandbox.py) | P | 339 linhas disponibilizadas |
| Anil-matcha/open-dots | [backend/app/routers/task.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/routers/task.py) | P | 55 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/app/services/github_classifier.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/github_classifier.py) | P | 76 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/app/services/notification_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/notification_service.py) | P | 54 linhas disponibilizadas |
| Anil-matcha/open-dots | [backend/app/services/permission_ask_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/permission_ask_service.py) | P | 172 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/app/services/permission_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/permission_service.py) | P | 78 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/app/services/schedule_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/schedule_service.py) | P | 395 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/app/services/task_execution_service.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/app/services/task_execution_service.py) | P | 379 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/pyproject.toml](https://github.com/Anil-matcha/open-dots/blob/main/backend/pyproject.toml) | P | 32 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/README.md](https://github.com/Anil-matcha/open-dots/blob/main/backend/README.md) | P | 66 linhas reconstruídas |
| Anil-matcha/open-dots | [backend/tests/services/test_github_classifier.py](https://github.com/Anil-matcha/open-dots/blob/main/backend/tests/services/test_github_classifier.py) | P | 67 linhas disponibilizadas |
| Anil-matcha/open-dots | [frontend/app/page.tsx](https://github.com/Anil-matcha/open-dots/blob/main/frontend/app/page.tsx) | P | 69 linhas disponibilizadas |
| Anil-matcha/open-dots | [frontend/lib/api.ts](https://github.com/Anil-matcha/open-dots/blob/main/frontend/lib/api.ts) | P | 206 linhas disponibilizadas |
| Anil-matcha/open-dots | [frontend/package.json](https://github.com/Anil-matcha/open-dots/blob/3d8de1cd6657c6d70583f34b89c2dc034512c1ea/frontend/package.json) | M | 26 linhas reconstruídas |
| Anil-matcha/open-dots | [frontend/README.md](https://github.com/Anil-matcha/open-dots/blob/main/frontend/README.md) | P | 34 linhas reconstruídas |
| Anil-matcha/open-dots | [README.md](https://github.com/Anil-matcha/open-dots/blob/main/README.md) | P | 282 linhas reconstruídas |
| CopilotKit/OpenDots | [.github/workflows/ci.yml](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/.github/workflows/ci.yml) | M | 22 linhas reconstruídas |
| CopilotKit/OpenDots | [CONTRIBUTING.md](https://github.com/CopilotKit/OpenDots/blob/main/CONTRIBUTING.md) | P | 14 linhas reconstruídas |
| CopilotKit/OpenDots | [deployment/computers/LICENSE.openbot](https://github.com/CopilotKit/OpenDots/blob/main/deployment/computers/LICENSE.openbot) | P | 19 linhas disponibilizadas |
| CopilotKit/OpenDots | [deployment/computers/README.md](https://github.com/CopilotKit/OpenDots/blob/main/deployment/computers/README.md) | P | 7 linhas disponibilizadas |
| CopilotKit/OpenDots | [Dockerfile](https://github.com/CopilotKit/OpenDots/blob/main/Dockerfile) | P | 25 linhas reconstruídas |
| CopilotKit/OpenDots | [docs/CONNECTIONS.md](https://github.com/CopilotKit/OpenDots/blob/main/docs/CONNECTIONS.md) | P | 25 linhas reconstruídas |
| CopilotKit/OpenDots | [docs/SETUP.md](https://github.com/CopilotKit/OpenDots/blob/main/docs/SETUP.md) | P | 195 linhas disponibilizadas |
| CopilotKit/OpenDots | [LICENSE](https://github.com/CopilotKit/OpenDots/blob/main/LICENSE) | P | 19 linhas reconstruídas |
| CopilotKit/OpenDots | [package.json](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/package.json) | M | 88 linhas reconstruídas |
| CopilotKit/OpenDots | [SECURITY.md](https://github.com/CopilotKit/OpenDots/blob/main/SECURITY.md) | P | 18 linhas reconstruídas |
| CopilotKit/OpenDots | [src/browser/index.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/browser/index.ts) | P | 134 linhas reconstruídas |
| CopilotKit/OpenDots | [src/browser/transport.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/browser/transport.ts) | M | 80 linhas disponibilizadas |
| CopilotKit/OpenDots | [src/client/App.tsx](https://github.com/CopilotKit/OpenDots/blob/main/src/client/App.tsx) | R/P | recortes de composição, navegação e controles; 962 linhas |
| CopilotKit/OpenDots | [src/client/editor/autosave.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/client/editor/autosave.ts) | M | 242 linhas disponibilizadas |
| CopilotKit/OpenDots | [src/client/editor/RichEditor.tsx](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/client/editor/RichEditor.tsx) | M | 217 linhas disponibilizadas |
| CopilotKit/OpenDots | [src/client/PageDocument.tsx](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/client/PageDocument.tsx) | M | 365 linhas disponibilizadas |
| CopilotKit/OpenDots | [src/server/app.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/app.ts) | M | 251 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/computer-service.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/computer-service.ts) | M | 369 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/connection-routes.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/connection-routes.ts) | M | 151 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/connection-store.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/connection-store.ts) | M | 185 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/connections.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/connections.ts) | M | 303 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/dot-agent.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/dot-agent.ts) | P | 447 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/index.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/index.ts) | M | 135 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/learning.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/learning.ts) | P | 34 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/page-service.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/page-service.ts) | M | 147 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/pages.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/pages.ts) | M | 314 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/parallel.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/parallel.ts) | P | 199 linhas disponibilizadas |
| CopilotKit/OpenDots | [src/server/platform.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/platform.ts) | M | 232 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/runner.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/runner.ts) | M | 106 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/runtime-scope.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/runtime-scope.ts) | M | 81 linhas disponibilizadas |
| CopilotKit/OpenDots | [src/server/slack-channel.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/slack-channel.ts) | P | 160 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/store.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/store.ts) | P | 312 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/voice.ts](https://github.com/CopilotKit/OpenDots/blob/main/src/server/voice.ts) | P | 302 linhas reconstruídas |
| CopilotKit/OpenDots | [src/server/workspace.ts](https://github.com/CopilotKit/OpenDots/blob/625452e06cde74cb25b0ce319e2c1be0488f5a5f/src/server/workspace.ts) | M | 372 linhas reconstruídas |
| CopilotKit/OpenDots | [tests/computer.test.ts](https://github.com/CopilotKit/OpenDots/blob/main/tests/computer.test.ts) | P | 305 linhas disponibilizadas |
| feder-cr/invisible_dots | [.github/workflows/tests.yml](https://github.com/feder-cr/invisible_dots/blob/main/.github/workflows/tests.yml) | P | 316 linhas reconstruídas |
| feder-cr/invisible_dots | [apps/api/package.json](https://github.com/feder-cr/invisible_dots/blob/main/apps/api/package.json) | P | 25 linhas reconstruídas |
| feder-cr/invisible_dots | [apps/api/src/server.ts](https://github.com/feder-cr/invisible_dots/blob/main/apps/api/src/server.ts) | P | 472 linhas reconstruídas |
| feder-cr/invisible_dots | [apps/vm-manager/src/qemu-args.ts](https://github.com/feder-cr/invisible_dots/blob/main/apps/vm-manager/src/qemu-args.ts) | P | 143 linhas disponibilizadas |
| feder-cr/invisible_dots | [apps/web/package.json](https://github.com/feder-cr/invisible_dots/blob/main/apps/web/package.json) | P | 54 linhas disponibilizadas |
| feder-cr/invisible_dots | [docs/architecture.md](https://github.com/feder-cr/invisible_dots/blob/main/docs/architecture.md) | R/P | abertura e seções selecionadas; 2636 linhas na consulta raw |
| feder-cr/invisible_dots | [docs/guide.md](https://github.com/feder-cr/invisible_dots/blob/main/docs/guide.md) | R/P | abertura e recorte posterior de segurança/atualização; 716 linhas |
| feder-cr/invisible_dots | [invisible_engine_dots/nanobot/dots/gate.py](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/nanobot/dots/gate.py) | P | 215 linhas reconstruídas |
| feder-cr/invisible_dots | [invisible_engine_dots/nanobot/dots/permissions.py](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/nanobot/dots/permissions.py) | P | 253 linhas reconstruídas |
| feder-cr/invisible_dots | [invisible_engine_dots/nanobot/dots/transcript_outbox.py](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/nanobot/dots/transcript_outbox.py) | P | 170 linhas disponibilizadas |
| feder-cr/invisible_dots | [invisible_engine_dots/UPSTREAM.md](https://github.com/feder-cr/invisible_dots/blob/main/invisible_engine_dots/UPSTREAM.md) | P | 206 linhas disponibilizadas |
| feder-cr/invisible_dots | [LICENSE](https://github.com/feder-cr/invisible_dots/blob/main/LICENSE) | P | 19 linhas reconstruídas |
| feder-cr/invisible_dots | [package.json](https://github.com/feder-cr/invisible_dots/blob/main/package.json) | P | 31 linhas reconstruídas |
| feder-cr/invisible_dots | [SECURITY.md](https://github.com/feder-cr/invisible_dots/blob/main/SECURITY.md) | P | 36 linhas reconstruídas |
| feder-cr/invisible_dots | [THIRD_PARTY_NOTICES.md](https://github.com/feder-cr/invisible_dots/blob/main/THIRD_PARTY_NOTICES.md) | R/P | recortes, incluindo o complemento final 535–560; 561 linhas no arquivo |

Fontes oficiais auxiliares efetivamente consultadas:

- [CopilotKit Intelligence self-hosting](https://docs.copilotkit.ai/intelligence/self-hosting): pré-requisitos de licença e infraestrutura; consulta dirigida, não auditoria do produto proprietário.
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0): requisitos de redistribuição/NOTICE/alterações e limites de marca.
- Páginas públicas dos três repositórios e metadados do commit CopilotKit: identificação/posicionamento; sem prova de história completa.
- Skill operacional consultada: sentra-commander/sentra-operator, apenas para instruções de acesso e escopo; nenhum candidato foi implementado ou promovido.

### 12.4 Testes inventariados, distinguindo leitura e nomes

Os nomes abaixo pertencem às árvores HEAD verificadas. Só computer.test.ts (CopilotKit) e test_github_classifier.py (Anil) tiveram conteúdo de teste disponibilizado e revisado nesta etapa. O workflow feder também foi lido. Os demais nomes não autorizam alegação de cobertura ou suite verde.

**CopilotKit — 48 módulos:**

- tests/app-origin.test.ts — inventário de caminho
- tests/app.test.ts — inventário de caminho
- tests/autosave.test.ts — inventário de caminho
- tests/chat-composer.test.ts — inventário de caminho
- tests/computer-card.test.tsx — inventário de caminho
- tests/computer-deployment.test.js — inventário de caminho
- tests/computer.test.ts — conteúdo consultado
- tests/connection-card.test.tsx — inventário de caminho
- tests/connections.test.ts — inventário de caminho
- tests/controls.test.tsx — inventário de caminho
- tests/dark-theme.test.ts — inventário de caminho
- tests/dot-agent-channel.test.ts — inventário de caminho
- tests/headless-runtime.test.ts — inventário de caminho
- tests/headless.test.ts — inventário de caminho
- tests/intelligence-key.test.ts — inventário de caminho
- tests/learning-delivery.test.ts — inventário de caminho
- tests/learning.test.ts — inventário de caminho
- tests/library.test.ts — inventário de caminho
- tests/markdown.test.ts — inventário de caminho
- tests/page-chat-request.test.ts — inventário de caminho
- tests/page-context.test.ts — inventário de caminho
- tests/page-document-delete.test.tsx — inventário de caminho
- tests/page-review-card.test.tsx — inventário de caminho
- tests/page-review.test.tsx — inventário de caminho
- tests/page-routes.test.ts — inventário de caminho
- tests/page-service.test.ts — inventário de caminho
- tests/page-snapshots.test.ts — inventário de caminho
- tests/pages.test.ts — inventário de caminho
- tests/parallel.test.ts — inventário de caminho
- tests/poll-notice.test.ts — inventário de caminho
- tests/research.test.ts — inventário de caminho
- tests/runner.test.ts — inventário de caminho
- tests/runtime-scope.test.ts — inventário de caminho
- tests/security.test.ts — inventário de caminho
- tests/setup-telemetry.test.ts — inventário de caminho
- tests/setup.test.ts — inventário de caminho
- tests/shutdown.test.ts — inventário de caminho
- tests/slack-channel-wiring.test.ts — inventário de caminho
- tests/slack-channel.test.ts — inventário de caminho
- tests/store.test.ts — inventário de caminho
- tests/tanstack-agent.test.ts — inventário de caminho
- tests/telemetry.test.ts — inventário de caminho
- tests/transcript.test.tsx — inventário de caminho
- tests/transport.test.ts — inventário de caminho
- tests/use-voice-control-poll.test.ts — inventário de caminho
- tests/use-voice.test.ts — inventário de caminho
- tests/voice.test.ts — inventário de caminho
- tests/workspace.test.ts — inventário de caminho

**Anil — 11 módulos:**

- backend/tests/core/test_config.py — inventário de caminho
- backend/tests/routers/test_sandbox_recovery.py — inventário de caminho
- backend/tests/routers/test_task_complete_stdout.py — inventário de caminho
- backend/tests/routers/test_task_launch_errors.py — inventário de caminho
- backend/tests/services/test_github_classifier.py — conteúdo consultado
- backend/tests/services/test_permission_ask_service.py — inventário de caminho
- backend/tests/services/test_permission_deadline.py — inventário de caminho
- backend/tests/services/test_permission_service.py — inventário de caminho
- backend/tests/services/test_schedule_service.py — inventário de caminho
- backend/tests/telegram/test_poll_budget.py — inventário de caminho
- backend/tests/telegram/test_task_output.py — inventário de caminho

### 12.5 Consultas falhas e arquivos não lidos

| Consulta | Resultado / consequência |
|---|---|
| Terminal inicial para clones e comandos locais | helper_unknown_error antes de iniciar processo; fallback de leitura/processo Git foi necessário |
| Algumas ferramentas SENTRA MCP | “MCP tool call requires approval, but approval policy is never”; não houve bypass/elevação; usaram-se leituras disponíveis |
| Git clone CopilotKit e Anil no fallback | Destinos existentes não vazios; não sobrescritos |
| Git clone feder | github.com:443 inacessível; não existe HEAD local comprovado |
| Git show de README no clone parcial CopilotKit | Blob ausente com lazy fetch desabilitado |
| GitHub API refs/trees/commits, feeds e páginas de histórico | Respostas incompletas/cache miss; não se estabeleceu SHA feder ou história suficiente |
| Anil LICENSE | 404; outros nomes de licença falharam por consulta; árvore HEAD não contém licença/notice |
| CopilotKit src/browser/security.ts | Fetch falhou; não se confirmou o conjunto completo de validações de URL/IP |
| CopilotKit tests/connections.test.ts e tests/autosave.test.ts | Cache miss; nomes existem no inventário, conteúdo não confirmado |
| Anil backend/tests/services/test_schedule_service.py | Cache miss; somente inventário |
| feder apps/scheduler/src/index.ts e scheduler.ts; packages/database/src/database.ts | Cache miss; protocolo host/DB permaneceu documental |
| feder packages/shared/src/config.ts e process.ts; apps/vm-manager/src/guest.ts | Cache miss; gestão de processo/config/guest sem revisão direta suficiente |
| feder apps/api/src/index.ts | Cache miss; server.ts foi acessível, composição completa não |
| feder guest/dot-agentd/internal/protocol/account_linux.go | Cache miss; não se auditou daemon inteiro ou todo secret handoff |
| feder apps/cli/package.json, src/cli.ts; packages/sdk/package.json, src/index.ts | Cache miss; CLI/SDK descritos por documentação/CI, não revisão completa de implementação |
| feder approval-card.tsx tentado | Cache miss; origem/licença por notice, comportamento de UI não homologado |
| Caminhos tentados inicialmente com layout incorreto | CopilotKit PageEditor.tsx e Anil frontend/src/app; corrigidos para RichEditor.tsx e frontend/app/page.tsx |
| CopilotKit docs/architecture.md tentado | Não obtido; arquitetura reconstruída dos entrypoints/stores/serviços acessíveis |
| GNU GPL página normativa tentada | Consulta falhou; não se concluiu liberação de distribuição GPL/LGPL |

Falha de um caminho tentado não prova que esse arquivo exista naquela revisão. Quando o nome não foi confirmado por árvore, a tabela registra **tentativa**, não inventário.

### 12.6 Achados faltantes que condicionam adoção futura

1. **Proveniência:** obter clones completos no mesmo escopo quando rede permitir, verificar HEADs/história e fixar cada arquivo candidato. feder continua sem pin raiz.
2. **Licença Anil:** licença escrita, titular e abrangência. Não inferir autorização comercial a partir de About.
3. **Notices feder:** ler textos aninhados e mapear arquivos selecionados, Apache/MIT e dependências GPL/LGPL do pacote efetivamente escolhido.
4. **Supply chain:** locks completos, hashes de imagens/browser/SDKs, SBOM binário e política de atualização; nenhum inventário de vulnerabilidades exaustivo.
5. **Execução:** provar enforcements físico/owner de OpenBot, Boat/CLI e daemon VM antes de considerar adapters. Nenhum foi executado.
6. **Replay/crash:** hipótese CF11, janela AF12, concorrência de sessão/approval e estado incerto precisam de validação futura autorizada.
7. **Persistência:** ensaio completo de backup/restore, migrações, secret rotation, revogação e artefatos de todas as camadas.
8. **Conta/Web:** picker/effort/Automatic, app/plugin/schema, cartão humano, attachments e quota observados na sessão real. Upstreams não fornecem prova suficiente.
9. **UX instalada:** screenshots/teste visual no SENTRA real, WebView2/ARIA/DPI físico, latência e perfil de memória. Não foram criadas ilustrações ou protótipos.
10. **Release:** assinatura legítima, clean install, update staged/rollback e Doctor redigido. CI e setup de desenvolvimento não suprem esses gates.
11. **Legal/dados:** termos de providers/CLI/browser, custos, subprocessadores, retenção e avaliação de distribuição. Não é parecer jurídico definitivo.
12. **Estado SENTRA concorrente:** coordenador deve confrontar as propostas com alterações dos seis agentes/implementador; este estudo não auditou source atual fora dos documentos.

### 12.7 Registro dos efeitos desta missão

Efeitos autorizados realizados: tentativas de git clone nos três destinos especificados e escrita deste **único relatório Markdown** na raiz de pesquisa. Os dois diretórios parciais eram preexistentes; não foram completados ou apagados. Na conferência antes da gravação, a raiz continha somente CopilotKit-OpenDots e Anil-matcha-open-dots.

Não se escreveu ou modificou arquivo do checkout SENTRA. Não se criou patch, implementação, função de produto, interface, teste, protótipo, script de projeto, dependência instalada, imagem, export, log ou segundo relatório. Ferramentas locais foram usadas para consulta, hashes, metadados Git e composição deste documento; nenhum código upstream foi executado. Não houve acesso a credenciais/cookies, comunicação a terceiros ou alteração de serviço em uso.

O resultado é pesquisa rastreável com limites explícitos, e não autorização de integrar. A recomendação principal permanece: melhorar o SENTRA existente por contratos e UX selecionados, sem transportar outra autoridade de execução.



### Fonte ECO ? docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md

# SENTRA OS — Auditoria integral do ecossistema de 37 repositórios



Data: 2026-10-09T00:21:56.311995+00:00 (gerado localmente).



Este documento analisa cada clone como fonte potencial de funcionalidades do SENTRA. A inspeção foi estática (arquivos Git, organização de código, documentação, contratos e interfaces), não uma auditoria linha por linha nem uma certificação de segurança. Código externo não foi executado nem integrado nesta etapa.



## I. Evidência da clonagem e metodologia



- Clones: 37 repositórios novos, além do codex-chatgpt-web pré-existente. Todos os 37 snapshots possuem commit congelado no manifesto.

- Inventários: `third_party/SENTRA_SOURCES_MANIFEST.json`, `third_party/SENTRA_COMPREHENSIVE_SOURCE_INDEX.json` e `third_party/SENTRA_CLONE_VERIFICATION.json`.

- O terceiro código fica fora do Git principal por configuração preexistente; não há upload público, execução de clone, migrações no core ou instalação de serviços.

- Destino da proposta: uso pessoal e entre amigos, com o SENTRA como autoridade durável de tarefas, identidade, permissões e evidência.

- Alguns projetos autorizam cópia e modificação, mas obrigações de autoria, redistribuição ou disponibilização do código ainda podem existir em usos compartilhados, inclusive entre amigos. Conferir avisos do módulo efetivamente incorporado; sem impedir estudo, prototipagem e integração por API.



## II. O que o SENTRA já resolve e não deve reconstruir



| Núcleo | Componentes reais | Capacidade existente e limitação |

|---|---|---|

| Grafo e terminais | `sentra_canvas/{graph,service,terminal,task_runtime}.py`, `sentra_canvas/static/native.js` | Canvas com nós, links dirigidos, ConPTY, equipes, handoffs, política básica e projeção de tasks. Falta colaboração distribuída universal. |

| CLIs/agentes | `sentra_cli/canvas.py` e Model Gateway | Handoff interno e seleção de provedores; necessita ACP/A2A/Agent runtime genérico. |

| Orquestração durável | `sentra_mcp/services/{durable,governance,event_ingress}.py` | WorkItem, Runs, Operations, leasing, budgets, recuperação; falta prova multi-node extensa. |

| Autorização | `sentra_mcp/services/authorization.py` e `plugin_host.py` | Grants de capability e plugins; faltam controles unificados por ação de app/Machine. |

| Sandbox | `sentra_mcp/services/process_sandbox.py` | Docker para algumas execuções; ConPTY Windows ainda roda com privilégios do usuário. |

| Controle remoto | `sentra_remote/{agent,gateway,store}.py` | Device pairing/jobs; falta sessão de aplicação/desktop e inventário de máquinas. |

| Auditoria | `sentra_mcp/audit.py` e `sentra_core/telemetry.py` | Eventos correlacionados e redaction, ainda sem provas externas completas contra adulteração. |

| Entrega | `.github/workflows/ci.yml` | Gates e releases em evolução; inclusão de terceiros exigiria testes e revisão de artefatos. |



## III. Comparativo rápido de encaixe



| Projeto | Família | Impacto | Tratamento inicial |

|---|---|---|---|

| ufo | Agentes, protocolos e descoberta | P0 | extrair/adaptar |

| openhands | Agentes, protocolos e descoberta | P1 | extrair UI |

| openhands-agent-sdk | Agentes, protocolos e descoberta | P1 | provider adapter |

| agent-client-protocol | Agentes, protocolos e descoberta | P0 | adapter de protocolo |

| acp-registry | Agentes, protocolos e descoberta | P2 | catalogo |

| a2a | Agentes, protocolos e descoberta | P0 | gateway interagente |

| mcp-typescript-sdk | Agentes, protocolos e descoberta | P1 | cliente de ferramentas |

| daytona | Execução isolada, máquinas e interfaces | P0 | adapter e serviço |

| pywinauto | Execução isolada, máquinas e interfaces | P0 | biblioteca direta |

| hcsshim | Execução isolada, máquinas e interfaces | P1 | container Windows opcional |

| gvisor | Execução isolada, máquinas e interfaces | P1 | sandbox Linux |

| playwright-mcp | Execução isolada, máquinas e interfaces | P1 | executor browser |

| guacamole-client | Execução isolada, máquinas e interfaces | P1 | viewer web |

| guacamole-server | Execução isolada, máquinas e interfaces | P1 | proxy remoto |

| rustdesk | Execução isolada, máquinas e interfaces | P2 | controle remoto alternativo |

| langgraph | Orquestração e distribuição | P2 | subfluxo opcional |

| temporal | Orquestração e distribuição | P2 | referência worker |

| nats-server | Orquestração e distribuição | P1 | barramento |

| toolhive | Política, confiança e autenticação | P0 | integrar host opcional |

| spire | Política, confiança e autenticação | P1 | identidade de dispositivos |

| keycloak | Política, confiança e autenticação | P2 | serviço opcional |

| openfga | Política, confiança e autenticação | P2 | policy backend |

| opa | Política, confiança e autenticação | P2 | motor de política opcional |

| tessera | Auditoria, telemetria e dependências | P0 | log de transparência |

| immudb | Auditoria, telemetria e dependências | P2 | storage alternativo |

| opentelemetry-collector | Auditoria, telemetria e dependências | P1 | telemetria |

| langfuse | Auditoria, telemetria e dependências | P2 | tracing opcional |

| grype | Auditoria, telemetria e dependências | P1 | scanner CI |

| xyflow | Canvas e colaboração | P2 | referência UI |

| yjs | Canvas e colaboração | P1 | biblioteca CRDT |

| y-protocols | Canvas e colaboração | P1 | protocolo de presença |

| hocuspocus | Canvas e colaboração | P1 | serviço colaborativo |

| activepieces | Integrações, automações e RPA | P2 | conector externo |

| rpaframework | Integrações, automações e RPA | P2 | extrair libs |

| windows-agent-arena | Benchmarks e validação de agentes | P1 | benchmark |

| osworld-v2 | Benchmarks e validação de agentes | P2 | benchmark |

| windowsworld | Benchmarks e validação de agentes | P1 | benchmark |



## IV. Análise individual por projeto com arquivos do clone



### Agentes, protocolos e descoberta



#### ufo — P0, extrair/adaptar



**Resolve.** AgentOS Windows UFO2 e coordenador Galaxy/Constellation para agentes que executam ações em aplicativos e máquinas distribuídas.



**Aproveitamento de código.** Adaptar módulos de ações em apps Windows, critérios de descoberta de capacidades, decomposição de objetivos e estratégias de recuperação.



**Encaixe arquitetural.** MachineRuntime seleciona um Windows executor, cada ação vira Operation idempotente e cada resultado vira Evidence; aproveitar Galaxy como inspiração de DAG.



**Sobreposições e limitações.** SENTRA já possui Goals/WorkItems e Remote Agent; não criar um segundo orquestrador soberano, especialmente baseado só em decisão de LLM.



**Aceite obrigatório.** Abrir app de teste, operar elemento UIA, negar ação fora do PID/escopo, reconectar e auditar resultado.



**Evidências concretas.** `third_party/ufo/galaxy/agents/constellation_agent.py`, `third_party/ufo/galaxy/agents/constellation_agent_states.py`, `third_party/ufo/documents/docs/galaxy/constellation_agent/state.md`, `third_party/ufo/documents/docs/galaxy/constellation_agent/command.md`, `third_party/ufo/documents/docs/galaxy/constellation_agent/overview.md`; `third_party/ufo/README.md`. Revisão `a795552d976c`; 931 arquivos versionados; principais extensões: .py: 496, .md: 226, .png: 92, .yaml: 33.



#### openhands — P1, extrair UI



**Resolve.** Agent Canvas visual especializado em conversas, execução de agents, terminal, browser, arquivos, seleção de backend e observabilidade.



**Aproveitamento de código.** Comparar componentes de interface, seleção de agentes, estados de conversa, visibilidade de ações e UX de permissões.



**Encaixe arquitetural.** Extrair padrões ou widgets úteis para o Canvas SENTRA sem mudar sua identidade visual nem substituir o grafo de terminais.



**Sobreposições e limitações.** Seu frontend depende de Agent Server; importar a aplicação inteira recriaria estados e telas que já existem.



**Aceite obrigatório.** Duas sessões de agentes em backends diferentes, feedback real, cancelamento e reabertura da UI.



**Evidências concretas.** `third_party/openhands/src/services/canvas-ui.ts`, `third_party/openhands/src/fixtures/canvas-demo-conversation.ts`, `third_party/openhands/src/services/child-conversation-launch.ts`, `third_party/openhands/src/contexts/conversation-websocket-context.tsx`, `third_party/openhands/src/api/backend-registry/last-conversation-store.ts`; `third_party/openhands/README.md`. Revisão `76398bb5c5b9`; 2564 arquivos versionados; principais extensões: .ts: 1094, .tsx: 1059, .svg: 146, .md: 78.



#### openhands-agent-sdk — P1, provider adapter



**Resolve.** Servidor REST/WebSocket, SDK Python, lifecycle de agentes e workspace, stream de eventos e integração ACP.



**Aproveitamento de código.** Extrair contratos tipados de eventos, streams, adaptação de agentes, ferramentas e ciclo de vida de sessões.



**Encaixe arquitetural.** OpenHandsProviderAdapter opcional usando Run/Agent/Chat do SENTRA como identidades duráveis.



**Sobreposições e limitações.** Não delegar credenciais nem decisão de promoção ao Agent Server externo.



**Aceite obrigatório.** Teste com 2 agentes, restart, eventos repetidos, política de workspace e rastreio de tool call.



**Evidências concretas.** `third_party/openhands-agent-sdk/clients/typescript/src/events/websocket-client.ts`, `third_party/openhands-agent-sdk/clients/typescript/src/events/bash-websocket-client.ts`, `third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/conversation/events_list_base.py`, `third_party/openhands-agent-sdk/openhands-workspace/openhands/workspace/agent_sandbox/README.md`, `third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/workspace_router.py`; `third_party/openhands-agent-sdk/README.md`. Revisão `2804c1273b40`; 1855 arquivos versionados; principais extensões: .py: 1401, .ts: 117, .md: 88, .json: 83.



#### agent-client-protocol — P0, adapter de protocolo



**Resolve.** Padrão de sessões, capabilities e comunicação entre clientes e agentes CLI.



**Aproveitamento de código.** Implementar JSON-RPC stdio, session/new, prompt, progress, tool updates, solicitações de consentimento e cancelamento.



**Encaixe arquitetural.** ACPAdapter por agente, plugável no Canvas e no SENTRA CLI; mensagens podem usar contexto tipado interno.



**Sobreposições e limitações.** As diretivas internas do Canvas não substituem o protocolo ACP.



**Aceite obrigatório.** Testes de contrato, dois CLI ACP, recusa de permissão, encerramento incerto e reconexão.



**Evidências concretas.** `third_party/agent-client-protocol/agent-client-protocol-schema/src/v1/tool_call.rs`, `third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/tool_call.rs`, `third_party/agent-client-protocol/schema/v1/src/lib.rs`, `third_party/agent-client-protocol/schema/v2/src/lib.rs`, `third_party/agent-client-protocol/schema/v1/CHANGELOG.md`; `third_party/agent-client-protocol/README.md`. Revisão `8c4b8faff610`; 273 arquivos versionados; principais extensões: .mdx: 168, .rs: 33, .md: 11, .json: 11.



#### acp-registry — P2, catalogo



**Resolve.** Catálogo interoperável de agentes compatíveis com ACP.



**Aproveitamento de código.** Ler descritores, versões, capacidades declaradas, compatibilidade e instruções de instalação.



**Encaixe arquitetural.** Catálogo de agentes do Canvas com version pin e importação autorizada.



**Sobreposições e limitações.** Registry não é fonte confiável de executáveis; exigir aprovação/pin/verificação.



**Aceite obrigatório.** Bloquear agente incompatível, link malicioso, downgrade e instalações sem consentimento.



**Evidências concretas.** `third_party/acp-registry/.github/workflows/build_registry.py`, `third_party/acp-registry/.github/workflows/registry_utils.py`, `third_party/acp-registry/.github/workflows/build-registry.yml`; `third_party/acp-registry/README.md`. Revisão `f44424b681c1`; 551 arquivos versionados; principais extensões: .json: 256, .md: 218, .svg: 42, .py: 20.



#### a2a — P0, gateway interagente



**Resolve.** Protocolo de interoperabilidade entre agentes, tasks, Agent Cards, artefatos e atualizações.



**Aproveitamento de código.** Aproveitar schemas e patterns de agent discovery, handoff, task progress e artefatos.



**Encaixe arquitetural.** A2A gateway externo que converte task em WorkItem, preservando owner e source identity.



**Sobreposições e limitações.** A2A é transporte e semântica de troca, não autoridade de custo, lease ou aprovação.



**Aceite obrigatório.** Duas instâncias SENTRA trocam tarefa, duplicata bloqueada, artifact validado e revogação.



**Evidências concretas.** `third_party/a2a/docs/topics/streaming-and-async.md`, `third_party/a2a/docs/tutorials/python/7-streaming-and-multiturn.md`; `third_party/a2a/README.md`. Revisão `12e9d2fbb9ba`; 142 arquivos versionados; principais extensões: .md: 48, .yml: 12, .png: 11, .yaml: 10.



#### mcp-typescript-sdk — P1, cliente de ferramentas



**Resolve.** SDK oficial TypeScript para clients/servers MCP e transports de tools, resources e prompts.



**Aproveitamento de código.** Reaproveitar cliente MCP tipado e contracts, tools schemas, transport safety e testes cruzados.



**Encaixe arquitetural.** Expor API do SENTRA para frontends/plug-ins TypeScript sem criar outra implementação de autorização.



**Sobreposições e limitações.** SENTRA já tem sentra_mcp Python; ambos devem negociar contratos idênticos.



**Aceite obrigatório.** Contract tests Python/TS, permissões, paginação, erros semânticos e versão.



**Evidências concretas.** `third_party/mcp-typescript-sdk/packages/server-legacy/src/auth/clients.ts`, `third_party/mcp-typescript-sdk/packages/server-legacy/src/auth/middleware/clientAuth.ts`, `third_party/mcp-typescript-sdk/docs/servers/resources.md`, `third_party/mcp-typescript-sdk/docs/clients/server-requests.md`, `third_party/mcp-typescript-sdk/packages/server/src/server/perRequestTransport.ts`; `third_party/mcp-typescript-sdk/README.md`. Revisão `b022522089a0`; 1143 arquivos versionados; principais extensões: .ts: 667, .json: 279, .md: 124, .mjs: 20.



### Execução isolada, máquinas e interfaces



#### daytona — P0, adapter e serviço



**Resolve.** Compute/control plane de sandboxes, runners, daemon, snapshots, tools, files, processos, SSH e computer-use.



**Aproveitamento de código.** Adaptar SDK Python, processo de sandbox, snapshots, endpoints de ComputerUse e acessibilidade AT-SPI para Linux.



**Encaixe arquitetural.** DaytonaExecutor opcional gerenciado por WorkItem/Run/Operation SENTRA; sandbox é um recurso de máquina e não uma autoridade de projeto.



**Sobreposições e limitações.** Operar a infraestrutura inteira é mais custoso que instalar uma lib; ambiente Linux não restaura ConPTY Windows.



**Aceite obrigatório.** Criar sandbox, limitar FS e rede, executar, snapshot/recover, encerrar/revogar e confirmar cleanup.



**Evidências concretas.** `third_party/daytona/apps/daemon/pkg/toolbox/process/types.go`, `third_party/daytona/apps/daemon/pkg/toolbox/process/execute.go`, `third_party/daytona/apps/runner/pkg/docker/snapshot_sandbox.go`, `third_party/daytona/apps/daemon/pkg/toolbox/process/pty/types.go`, `third_party/daytona/apps/daemon/pkg/toolbox/process/pty/manager.go`; `third_party/daytona/README.md`. Revisão `fc98a5032c04`; 5702 arquivos versionados; principais extensões: .ts: 1367, .go: 818, .py: 803, .java: 733.



#### pywinauto — P0, biblioteca direta



**Resolve.** Automação de aplicativos Windows por elementos UI Automation e Win32.



**Aproveitamento de código.** Usar wrappers de controles, investigação de janelas/elementos, estado e esperas semânticas.



**Encaixe arquitetural.** WindowsUIAExecutor com PID, janela, selector, capability e approval; preferir UIA a cliques cegos.



**Sobreposições e limitações.** Pode não funcionar em apps com UI customizada, privilégios elevados ou sem árvore de acessibilidade.



**Aceite obrigatório.** Executar fluxo em Notepad/Calculator de teste, negar janela errada, tratar timeout e foco.



**Evidências concretas.** `third_party/pywinauto/pywinauto/controls/uiawrapper.py`, `third_party/pywinauto/pywinauto/controls/uia_controls.py`, `third_party/pywinauto/pywinauto/controls/win32_controls.py`, `third_party/pywinauto/pywinauto/windows/uia_element_info.py`, `third_party/pywinauto/pywinauto/windows/win32_element_info.py`; `third_party/pywinauto/README.md`. Revisão `18d2a95cebed`; 293 arquivos versionados; principais extensões: .py: 123, .exe: 77, .txt: 67, .yml: 5.



#### hcsshim — P1, container Windows opcional



**Resolve.** Interface com Windows Host Compute Service e containers Windows, integração com HCS/OCI.



**Aproveitamento de código.** Estudar lifecycle de instâncias Windows e execução confinada de processos/containers, com integração opcional ao sistema.



**Encaixe arquitetural.** WindowsContainerExecutor para workloads headless, sob o mesmo ExecutorAdapter e policy engine.



**Sobreposições e limitações.** Windows containers não são desktop interativo genérico; exigem versão/recursos específicos do host.



**Aceite obrigatório.** Provisionar e destruir container isolado, testar filesystem, privilégios e filhos.



**Evidências concretas.** `third_party/hcsshim/cmd/runhcs/container.go`, `third_party/hcsshim/internal/runhcs/container.go`, `third_party/hcsshim/internal/jobcontainers/doc.go`, `third_party/hcsshim/internal/jobcontainers/env.go`, `third_party/hcsshim/internal/jobcontainers/oci.go`; `third_party/hcsshim/README.md`. Revisão `ab8249e8a111`; 5443 arquivos versionados; principais extensões: .go: 4486, (sem extensão): 270, .md: 199, .json: 167.



#### gvisor — P1, sandbox Linux



**Resolve.** User-space kernel para aumentar isolamento de contêineres Linux não confiáveis.



**Aproveitamento de código.** Reaproveitar runsc como runtime de sandboxes de código e ferramenta em executores Linux.



**Encaixe arquitetural.** SandboxProfile gVisor no Daytona/Docker quando compatível; recurso opcional.



**Sobreposições e limitações.** Não resolve privilégios de um terminal ConPTY host Windows; compatibilidade de syscalls precisa teste.



**Aceite obrigatório.** Testes adversariais de filesystem, networking, syscall e impacto no desempenho.



**Evidências concretas.** `third_party/gvisor/pkg/sentry/platform/context.go`, `third_party/gvisor/pkg/sentry/platform/kvm/kvm.go`, `third_party/gvisor/pkg/sentry/platform/platform.go`, `third_party/gvisor/pkg/sentry/platform/kvm/config.go`, `third_party/gvisor/pkg/sentry/platform/cpuid_amd64.go`; `third_party/gvisor/README.md`. Revisão `25e4d4778b06`; 4413 arquivos versionados; principais extensões: .go: 2526, (sem extensão): 658, .cc: 370, .md: 137.



#### playwright-mcp — P1, executor browser



**Resolve.** Serviço MCP de operação de navegador, snapshots de acessibilidade e ações contextuais.



**Aproveitamento de código.** Adaptar ferramentas de browser de alto nível e mapeamento de ações DOM/ARIA.



**Encaixe arquitetural.** BrowserExecutor separado e consentido para tarefas web, dentro de scope SENTRA.



**Sobreposições e limitações.** Não pode tomar controle do Edge principal protegido nem herdar cookies sem autorização.



**Aceite obrigatório.** Teste isolamento entre sessões, navegação restrita, tentativas de exfiltração e timeout.



**Evidências concretas.** Nenhum arquivo candidato indexado; `third_party/playwright-mcp/README.md`. Revisão `b8b4183e099f`; 39 arquivos versionados; principais extensões: .ts: 10, .md: 6, .yml: 5, (sem extensão): 5.



#### guacamole-client — P1, viewer web



**Resolve.** Frontend HTML5 para desktops remotos RDP/VNC/SSH.



**Aproveitamento de código.** Reaproveitar interface de stream remoto, teclado, mouse, clipboard restrito e sessão visual.



**Encaixe arquitetural.** Nó Machine no Canvas abre view Guacamole limitada pelo grant da máquina.



**Sobreposições e limitações.** Somente renderiza e transmite interação; não é controlador de privilégio nem tool semântico.



**Aceite obrigatório.** Abrir e fechar sessão remota, revogar ao vivo e registrar evidências de operação.



**Evidências concretas.** `third_party/guacamole-client/guacamole/src/main/frontend/src/app/client/types/ManagedDisplay.js`, `third_party/guacamole-client/extensions/guacamole-display-statistics/src/main/resources/directives/guacClientStatistics.js`, `third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Client.js`, `third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Display.js`, `third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Keyboard.js`. Revisão `38e8cb8ff5cd`; 2033 arquivos versionados; principais extensões: .java: 853, .js: 293, .json: 153, (sem extensão): 149.



#### guacamole-server — P1, proxy remoto



**Resolve.** Gateway guacd e suporte de protocolos de desktop remoto.



**Aproveitamento de código.** Executar proxy RDP/VNC/SSH, gerenciamento de conexões e separação de frontend/servidor.



**Encaixe arquitetural.** RemoteDesktopTransport para Máquina existente com credenciais efêmeras SENTRA.



**Sobreposições e limitações.** Não expor RDP/VNC público; proxy precisa isolamento e atualizações.



**Aceite obrigatório.** Testar duas conexões, queda de rede, revogação e recursos de clipboard transfer.



**Evidências concretas.** `third_party/guacamole-server/src/protocols/rdp/doc/svc-example/README.md`. Revisão `ae12b8e51aa6`; 602 arquivos versionados; principais extensões: .c: 282, .h: 234, .keymap: 25, (sem extensão): 21.



#### rustdesk — P2, controle remoto alternativo



**Resolve.** Sistema de desktop remoto multiplataforma, rede e relay para suportar máquinas existentes.



**Aproveitamento de código.** Estudar comunicação P2P/relay e, opcionalmente, incorporar cliente/serviço separado.



**Encaixe arquitetural.** Alternativa a Guacamole para máquinas de amigos, gerenciada por aprovações SENTRA.



**Sobreposições e limitações.** Remote desktop visual não equivale a automação semântica; superfície de rede e consentimento elevados.



**Aceite obrigatório.** Parear duas máquinas, negar comando sem consentimento, medir reconexão e revogação.



**Evidências concretas.** `third_party/rustdesk/src/client.rs`, `third_party/rustdesk/src/server.rs`, `third_party/rustdesk/src/server/dbus.rs`, `third_party/rustdesk/src/client/helper.rs`, `third_party/rustdesk/src/custom_server.rs`; `third_party/rustdesk/README.md`. Revisão `1d4abd0258bb`; 1000 arquivos versionados; principais extensões: .rs: 289, .dart: 140, .md: 81, .png: 61.



### Orquestração e distribuição



#### langgraph — P2, subfluxo opcional



**Resolve.** Grafos de estado para agentes com checkpoints e interrupções.



**Aproveitamento de código.** Reaproveitar subflows LLM com state persistence, interrupt/resume e human-in-loop.



**Encaixe arquitetural.** LangGraphTaskAdapter opcional operando dentro de WorkItem e relatando progressos.



**Sobreposições e limitações.** Não substituir Durable Run, lease, Quality Gate nem política de promoção.



**Aceite obrigatório.** Crash entre etapas, checkpoint reaberto e side effects sem repetição.



**Evidências concretas.** `third_party/langgraph/libs/checkpoint/langgraph/store/base/batch.py`, `third_party/langgraph/libs/checkpoint/langgraph/store/base/embed.py`, `third_party/langgraph/libs/prebuilt/langgraph/prebuilt/interrupt.py`, `third_party/langgraph/libs/langgraph/langgraph/pregel/_checkpoint.py`, `third_party/langgraph/libs/checkpoint/langgraph/checkpoint/base/id.py`; `third_party/langgraph/README.md`. Revisão `bfcfea554ed5`; 684 arquivos versionados; principais extensões: .py: 465, .ipynb: 35, .json: 30, .yml: 28.



#### temporal — P2, referência worker



**Resolve.** Engine durável distribuída para workflows, activities, histories, timers e retries.



**Aproveitamento de código.** Utilizar padrões de worker queues, liveness, reconciliation e retries como referência/adapter futuro.



**Encaixe arquitetural.** TemporalWorkerAdapter opcional se benchmarks provarem ganho sobre scheduler atual.



**Sobreposições e limitações.** Segundo workflow authority aumenta complexidade e split-brain se não houver limites claros.



**Aceite obrigatório.** Failover de dois workers, evento incerto, recuperação, idempotência e compensação.



**Evidências concretas.** `third_party/temporal/service/history/workflow/activity.go`, `third_party/temporal/service/history/workflow/matcher/activity_matcher.go`, `third_party/temporal/service/history/workflow/matcher/activity_evaluator.go`, `third_party/temporal/service/history/workflow/retry.go`, `third_party/temporal/service/history/tasks/activity_retry_timer.go`; `third_party/temporal/README.md`. Revisão `bae8771853cf`; 3971 arquivos versionados; principais extensões: .go: 3006, .gz: 370, .json: 118, .sql: 111.



#### nats-server — P1, barramento



**Resolve.** Broker pubsub e JetStream para filas e consumo persistente distribuído.



**Aproveitamento de código.** Reaproveitar streams, consumers, ack, redelivery, retenção e observabilidade de eventos.



**Encaixe arquitetural.** Barramento entre SENTRA Gateway, remote agents e executor; envelope idempotente SENTRA permanece autoridade.



**Sobreposições e limitações.** Ack de mensagem não é prova de efeito concluído, e consumers podem reenviar.



**Aceite obrigatório.** Teste queda de rede, message duplicate, ordem, backpressure e revogação.



**Evidências concretas.** `third_party/nats-server/server/jetstream.go`, `third_party/nats-server/server/jetstream_api.go`, `third_party/nats-server/server/jetstream_errors.go`, `third_party/nats-server/server/jetstream_events.go`, `third_party/nats-server/server/jetstream_cluster.go`; `third_party/nats-server/README.md`. Revisão `6af2d22525d5`; 598 arquivos versionados; principais extensões: .go: 258, .pem: 144, .conf: 107, .key: 15.



### Política, confiança e autenticação



#### toolhive — P0, integrar host opcional



**Resolve.** Registro, proxy e isolamento de servidores MCP com policy gates, auth e telemetria.



**Aproveitamento de código.** Incorporar ToolHost/runner MCP, catálogo de servidores, interceptação de tools e isolamento por instância.



**Encaixe arquitetural.** ToolHiveExecutor opcional executa ferramentas após autorização no SENTRA Policy Gate.



**Sobreposições e limitações.** Não permitir tool registry independente expondo ferramentas além de grants.



**Aceite obrigatório.** Testes tool injection, registro indevido, policy deny, sandbox FS/rede, shutdown e rastreabilidade.



**Evidências concretas.** `third_party/toolhive/pkg/runner/policy_gate.go`, `third_party/toolhive/pkg/telemetry/registry.go`, `third_party/toolhive/pkg/registry/policy_gate.go`, `third_party/toolhive/pkg/runner/telemetry_config.go`, `third_party/toolhive/pkg/vmcp/auth/outgoing_registry.go`; `third_party/toolhive/README.md`. Revisão `33ba170aad63`; 2877 arquivos versionados; principais extensões: .go: 2229, .yaml: 287, .md: 250, .yml: 38.



#### spire — P1, identidade de dispositivos



**Resolve.** Identidade de workloads SPIFFE com SVID, attestation, mTLS e rotação.



**Aproveitamento de código.** Reaproveitar identidade criptográfica por máquina, agent/daemon e serviços conectados.



**Encaixe arquitetural.** DeviceIdentityProvider mapeia SPIFFE ID à identidade de principal SEN​TRA e autorização.



**Sobreposições e limitações.** É infraestrutura de confiança para multidevice; desnecessário impor ao uso local simples.



**Aceite obrigatório.** Rotação, clone de agente, certificado vencido, revogação e falha de attest.



**Evidências concretas.** `third_party/spire/cmd/spire-server/cli/federation/list.go`, `third_party/spire/cmd/spire-server/cli/federation/show.go`, `third_party/spire/cmd/spire-server/cli/federation/common.go`, `third_party/spire/cmd/spire-server/cli/federation/create.go`, `third_party/spire/cmd/spire-server/cli/federation/delete.go`; `third_party/spire/README.md`. Revisão `9dbd864e8923`; 2210 arquivos versionados; principais extensões: .go: 1230, (sem extensão): 371, .conf: 144, .md: 136.



#### keycloak — P2, serviço opcional



**Resolve.** Identity server com OIDC, SAML, SSO, MFA, realms e federação.



**Aproveitamento de código.** Reaproveitar login de humanos, acesso de amigos e integração OIDC/MFA.



**Encaixe arquitetural.** OIDCIdentityProvider autenticando humanos; autorizações granulares continuam no SENTRA.



**Sobreposições e limitações.** Serviço Java pesado para uso casual; opcional/hosted e não obrigatório no desktop.



**Aceite obrigatório.** Convidar amigo, multiworkspace, logout/revoke, MFA e troca de identidade.



**Evidências concretas.** `third_party/keycloak/js/apps/admin-ui/src/identity-providers/add/OIDCAuthentication.tsx`, `third_party/keycloak/federation/ldap/src/main/java/org/keycloak/storage/ldap/idm/store/IdentityStore.java`, `third_party/keycloak/federation/ldap/src/main/java/org/keycloak/storage/ldap/LDAPIdentityStoreRegistry.java`, `third_party/keycloak/federation/ldap/src/main/java/org/keycloak/storage/ldap/idm/store/ldap/LDAPIdentityStore.java`, `third_party/keycloak/server-spi-private/src/main/java/org/keycloak/broker/provider/UserAuthenticationIdentityProvider.java`; `third_party/keycloak/README.md`. Revisão `c7de391ae4d8`; 13514 arquivos versionados; principais extensões: .java: 8580, .png: 686, .adoc: 680, .tsx: 630.



#### openfga — P2, policy backend



**Resolve.** ReBAC de relacionamentos, tuplas e avaliação de permissões.



**Aproveitamento de código.** Modelar relações user/team/agent/workspace/machine e compartilhamento de recursos.



**Encaixe arquitetural.** ReBACPolicyBackend consultado pela autoridade única AuthorizationService.



**Sobreposições e limitações.** Evitar duas bases de grants com estados diferentes e cache incorreto.



**Aceite obrigatório.** Acesso transitivo, revogação, concorrência, negação fora de workspace.



**Evidências concretas.** `third_party/openfga/pkg/server/authorization_models.go`, `third_party/openfga/pkg/storage/storagewrappers/cached_datastore.go`, `third_party/openfga/pkg/storage/storagewrappers/bounded_datastore.go`, `third_party/openfga/pkg/storage/storagewrappers/sharediterator/shared_iterator_datastore.go`; `third_party/openfga/README.md`. Revisão `526995eb2024`; 578 arquivos versionados; principais extensões: .go: 476, .md: 22, .yaml: 19, .sql: 16.



#### opa — P2, motor de política opcional



**Resolve.** Policy Decision Point com Rego, bundles e condições de contexto.



**Aproveitamento de código.** Reaproveitar regras versionadas para risco de operação, contexto de app, rede e escopo.



**Encaixe arquitetural.** PDP externo consultado pelo SENTRA para regras complexas, com fail-closed.



**Sobreposições e limitações.** OPA não cria identidade e não deve administrar grants em paralelo.



**Aceite obrigatório.** Rego test, negative policy, timeout, atualização e rollback de bundle.



**Evidências concretas.** `third_party/opa/docs/blog/2025-05-14-introducing-swift-opa-native-policy-evaluation-for-swift-d5136c8a662e.md`, `third_party/opa/bundle/bundle.go`, `third_party/opa/v1/ast/policy.go`, `third_party/opa/v1/bundle/file.go`, `third_party/opa/v1/bundle/hash.go`; `third_party/opa/README.md`. Revisão `4dcda5da919a`; 7910 arquivos versionados; principais extensões: .yaml: 2398, .stmt: 1914, .go: 1030, .json: 703.



### Auditoria, telemetria e dependências



#### tessera — P0, log de transparência



**Resolve.** Infrastructure de transparency log append-only e checkpoints/witness verificáveis.



**Aproveitamento de código.** Reaproveitar logs Merkle, provas de inclusão, checkpoints assinados e mecanismos de witness.



**Encaixe arquitetural.** AuditWitness externaliza hashes canônicos dos eventos SENTRA; guardar provas por Operation.



**Sobreposições e limitações.** Registro verificável não garante que todas as ações foram registradas ou que não houve side effects fora da plataforma.



**Aceite obrigatório.** Alterar/apagar evento e verificar prova offline; retenção e falha segura.



**Evidências concretas.** `third_party/tessera/witness.go`, `third_party/tessera/append_lifecycle.go`, `third_party/tessera/internal/witness/otel.go`, `third_party/tessera/internal/witness/client.go`, `third_party/tessera/cmd/mtc/log/internal/checkpoint/reader.go`; `third_party/tessera/README.md`. Revisão `0489e17418aa`; 295 arquivos versionados; principais extensões: .go: 152, (sem extensão): 43, .md: 34, .tf: 18.



#### immudb — P2, storage alternativo



**Resolve.** Banco verificável com provas criptográficas de registros e consistência.



**Aproveitamento de código.** Usar como backend opcional para event ledgers e checagem de integridade.



**Encaixe arquitetural.** AuditStorageAdapter opcional para trilha externa, com somente hashes/metadados sensíveis redigidos.



**Sobreposições e limitações.** Mais complexo que log merkle leve; verificar implicações de licença BSL se compartilhado.



**Aceite obrigatório.** Prova de escrita/leitura, prova inválida, interrupção e restauração.



**Evidências concretas.** `third_party/immudb/pkg/server/remote_storage.go`, `third_party/immudb/embedded/store/verification.go`, `third_party/immudb/embedded/ahtree/verification.go`, `third_party/immudb/pkg/verification/verification.go`, `third_party/immudb/embedded/appendable/remoteapp/remote_storage_reader.go`; `third_party/immudb/README.md`. Revisão `bfdce03649f5`; 1203 arquivos versionados; principais extensões: .go: 970, (sem extensão): 38, .md: 26, .sh: 18.



#### opentelemetry-collector — P1, telemetria



**Resolve.** Pipelines de traces, logs e métricas com receivers, processors e exporters.



**Aproveitamento de código.** Exportar sinais de brokers, machine runtimes, agentes e gateways; padronizar OTLP.



**Encaixe arquitetural.** TelemetryExporter SENTRA -> Collector com run_id/operation_id/device_id.



**Sobreposições e limitações.** Tracing operacional não é trilha auditável criptográfica; proteger conteúdos dos usuários.



**Aceite obrigatório.** Rastreio distribuído completo, redaction, quotas de logs e perda de collector.



**Evidências concretas.** `third_party/opentelemetry-collector/processor/memorylimiterprocessor/internal/mock_exporter.go`, `third_party/opentelemetry-collector/processor/memorylimiterprocessor/internal/mock_receiver.go`, `third_party/opentelemetry-collector/receiver/doc.go`, `third_party/opentelemetry-collector/exporter/README.md`, `third_party/opentelemetry-collector/pipeline/signal.go`; `third_party/opentelemetry-collector/README.md`. Revisão `cee245c32ca5`; 2860 arquivos versionados; principais extensões: .go: 1802, .yaml: 419, .md: 131, (sem extensão): 119.



#### langfuse — P2, tracing opcional



**Resolve.** Tracing e avaliação de aplicações LLM, scores, custo e experimentos.



**Aproveitamento de código.** Dashboards por tarefa/modelo, spans de inferência e comparação de agentes.



**Encaixe arquitetural.** LLMTraceSink opcional correlacionando WorkItem ao provider turn.



**Sobreposições e limitações.** Custo efetivo, quota e hard stop pertencem ao SENTRA, não ao dashboard.



**Aceite obrigatório.** Observar falhas/custo sem registrar prompt secreto nem duplicar orçamento.



**Evidências concretas.** `third_party/langfuse/packages/shared/src/features/scores/interfaces/ingestion/validation.ts`, `third_party/langfuse/web/src/features/traces/fns/nodeScores.ts`, `third_party/langfuse/web/src/features/scores/lib/prepareTraceAnnotation.ts`, `third_party/langfuse/web/src/features/traces/hooks/useParsedObservation.ts`, `third_party/langfuse/web/src/features/traces/hooks/usePrefetchObservation.ts`; `third_party/langfuse/README.md`. Revisão `c106bb3d9453`; 6811 arquivos versionados; principais extensões: .ts: 3641, .tsx: 1849, .sql: 552, .md: 305.



#### grype — P1, scanner CI



**Resolve.** Varredura de CVEs em código, dependências, containers e SBOMs.



**Aproveitamento de código.** Integrar scan em CI e avaliação de snapshots de terceiros instaláveis.



**Encaixe arquitetural.** Release Gate analisa SBOM/artefato antes de instalar ferramenta externa.



**Sobreposições e limitações.** Não substitui threat modeling, análise de código nem execução isolada.



**Aceite obrigatório.** Scan executável/imagen Docker de teste, CVE threshold, relatório e exceções.



**Evidências concretas.** `third_party/grype/grype/vulnerability_matcher.go`, `third_party/grype/cmd/grype/cli/ui/handle_update_vulnerability_database.go`, `third_party/grype/grype/match/matcher.go`, `third_party/grype/grype/matcher/matchers.go`, `third_party/grype/grype/vulnerability/fix.go`; `third_party/grype/README.md`. Revisão `5dbdab183e88`; 1624 arquivos versionados; principais extensões: .go: 753, .json: 574, (sem extensão): 106, .yaml: 53.



### Canvas e colaboração



#### xyflow — P2, referência UI



**Resolve.** Engine React Flow de nodes, edges, handles, zoom e ergonomia de grafos.



**Aproveitamento de código.** Extrair padrões de seleção, acessibilidade e performance para canvases grandes.



**Encaixe arquitetural.** Benchmark de interação UI versus renderer próprio; integrar apenas se melhorar e preservar física.



**Sobreposições e limitações.** Uma migração React inteira duplicaria interface e arriscaria estética e ConPTY/xterm.



**Aceite obrigatório.** 100 nós, 200 cabos, FPS, resize, zoom e keyboard a11y.



**Evidências concretas.** `third_party/xyflow/packages/svelte/src/lib/hooks/useNodesEdgesViewport.svelte.ts`, `third_party/xyflow/packages/react/src/hooks/useViewport.ts`, `third_party/xyflow/packages/react/src/hooks/useViewportSync.ts`, `third_party/xyflow/packages/react/src/hooks/useViewportHelper.ts`, `third_party/xyflow/packages/react/src/container/Viewport/index.tsx`; `third_party/xyflow/README.md`. Revisão `3d35b5731757`; 697 arquivos versionados; principais extensões: .ts: 253, .tsx: 198, .svelte: 128, .css: 27.



#### yjs — P1, biblioteca CRDT



**Resolve.** CRDT para sincronizar alterações concorrentes entre clientes.



**Aproveitamento de código.** Replicar layout, notas, tamanho/posição de nós e cursores offline/online.



**Encaixe arquitetural.** CanvasSharedDocument recebe atualizações por workspace autorizado.



**Sobreposições e limitações.** CRDT não guarda grants, locks, WorkItems nem quotas.



**Aceite obrigatório.** Dois clientes, desconexão, merge, revogação e limites de payload.



**Evidências concretas.** `third_party/yjs/src/utils/updates.js`, `third_party/yjs/src/utils/encoding.js`, `third_party/yjs/src/utils/Transaction.js`, `third_party/yjs/src/utils/UpdateDecoder.js`, `third_party/yjs/src/utils/UpdateEncoder.js`; `third_party/yjs/README.md`. Revisão `d01eefc997cf`; 75 arquivos versionados; principais extensões: .js: 51, .md: 9, .json: 6, .yml: 4.



#### y-protocols — P1, protocolo de presença



**Resolve.** Protocolos Yjs de sync, awareness e mensagem de autorização.



**Aproveitamento de código.** Usar presença/cursores, encode de updates e handshake eficiente.



**Encaixe arquitetural.** Módulo de presença de amigos/agentes no Canvas Web com servidor Hocuspocus.



**Sobreposições e limitações.** Awareness é sinalização efêmera e não política de autorização.



**Aceite obrigatório.** Stale clients, heartbeat, reconexão, erro de permissão e dados malformados.



**Evidências concretas.** `third_party/y-protocols/src/awareness.js`; `third_party/y-protocols/README.md`. Revisão `73b2ff75486c`; 13 arquivos versionados; principais extensões: .js: 5, .json: 4, (sem extensão): 2, .md: 2.



#### hocuspocus — P1, serviço colaborativo



**Resolve.** Servidor WebSocket Yjs com auth hooks, colaboração e provider.



**Aproveitamento de código.** Sincronização e persistência em tempo real do layout do Canvas sem reimplementar CRDT protocol.



**Encaixe arquitetural.** CanvasCollaborationService verifica principal/workspace em cada sessão e recebe atualizações Yjs.



**Sobreposições e limitações.** Não expor direto o estado autoritativo SENTRA em documentos CRDT.



**Aceite obrigatório.** E2E com dois amigos, colaboração simultânea, token revogado e offline sync.



**Evidências concretas.** `third_party/hocuspocus/packages/provider/src/HocuspocusProviderWebsocket.ts`, `third_party/hocuspocus/packages/provider/src/OutgoingMessages/AuthenticationMessage.ts`, `third_party/hocuspocus/packages/provider-react/src/HocuspocusProviderWebsocketComponent.tsx`, `third_party/hocuspocus/packages/server/README.md`, `third_party/hocuspocus/packages/provider/README.md`; `third_party/hocuspocus/README.md`. Revisão `ee7c6e123c3a`; 266 arquivos versionados; principais extensões: .ts: 163, .md: 39, .json: 24, .tsx: 15.



### Integrações, automações e RPA



#### activepieces — P2, conector externo



**Resolve.** Motor de automações com peças para SaaS/APIs, trigger/ação, OAuth e webhook.



**Aproveitamento de código.** Adaptar conectores e catálogos de receitas para automações de trabalho pessoal.



**Encaixe arquitetural.** ConnectorExecutor aciona fluxo em serviço externo governado por WorkItem e approvals.



**Sobreposições e limitações.** Não duplicar scheduler/retry e controle de segredos em dois sistemas.



**Aceite obrigatório.** E2E webhook assinado, OAuth por usuário, aprovação para ação irreversível e dedupe.



**Evidências concretas.** `third_party/activepieces/packages/pieces/community/microsoft-copilot/src/lib/triggers/copilot-interaction-webhook.ts`, `third_party/activepieces/packages/pieces/community/knock/src/lib/actions/trigger-workflow.ts`, `third_party/activepieces/packages/pieces/community/feedhive/src/lib/actions/fire-workflow-trigger.ts`, `third_party/activepieces/packages/pieces/community/github/src/lib/actions/trigger-workflow-dispatch.ts`, `third_party/activepieces/packages/pieces/community/savvycal/src/lib/triggers/workflow-action-triggered.ts`; `third_party/activepieces/README.md`. Revisão `a9b86f6ed9e5`; 30020 arquivos versionados; principais extensões: .ts: 17001, .json: 10309, .md: 967, .tsx: 943.



#### rpaframework — P2, extrair libs



**Resolve.** Bibliotecas Python de RPA para GUI, sites, documentos, Excel e automações repetitivas.



**Aproveitamento de código.** Reaproveitar tarefas específicas e bibliotecas Robot Framework/Python para fluxos determinísticos.



**Encaixe arquitetural.** RPAExecutor para sequências aprovadas dentro do sandbox Windows/Linux.



**Sobreposições e limitações.** Seletores frágeis e riscos de credencial; RPA não é arquitetura de agente.



**Aceite obrigatório.** Preencher formulário de teste, Excel/PDF mock, falha de UI, evidência e cancelamento.



**Evidências concretas.** `third_party/rpaframework/packages/main/src/RPA/Desktop/utils.py`, `third_party/rpaframework/packages/main/src/RPA/Browser/common.py`, `third_party/rpaframework/packages/windows/src/RPA/Windows/main.py`, `third_party/rpaframework/packages/main/src/RPA/Browser/Selenium.py`, `third_party/rpaframework/packages/main/src/RPA/Browser/__init__.py`; `third_party/rpaframework/README.rst`. Revisão `7a419fb7a7bd`; 704 arquivos versionados; principais extensões: .py: 250, .rst: 110, .jpg: 65, .robot: 39.



### Benchmarks e validação de agentes



#### windows-agent-arena — P1, benchmark



**Resolve.** Benchmark de execução de tarefas no Windows com aplicativos reais.



**Aproveitamento de código.** Criar suíte de aferição de agente e ambiente reproduzível para Machine Runtime.



**Encaixe arquitetural.** SENTRA BenchRunner executa tarefas em VM e reporta sucesso/latência/custo.



**Sobreposições e limitações.** Passar benchmark não certifica permissão, segurança ou robustez em ambiente não controlado.



**Aceite obrigatório.** Baseline repetível com 3 execuções, avaliações e evidência anexada.



**Evidências concretas.** `third_party/windows-agent-arena/src/win-arena-container/client/evaluation_examples_windows/create_json.py`, `third_party/windows-agent-arena/src/win-arena-container/client/desktop_env/evaluators/getters/windows_clock.py`; `third_party/windows-agent-arena/README.md`. Revisão `6d39ed88c545`; 514 arquivos versionados; principais extensões: .json: 314, .py: 127, .png: 19, .md: 11.



#### osworld-v2 — P2, benchmark



**Resolve.** Benchmark de tarefas de computador multietapas em ambientes padronizados.



**Aproveitamento de código.** Medir eficácia de ações de interface, recuperação e impacto do contexto longo.



**Encaixe arquitetural.** Harness de benchmark externo para comparar WindowsUIA/Playwright/RPA e agent providers.



**Sobreposições e limitações.** Infraestrutura/VM grande; não testar em estação pessoal com dados reais.



**Aceite obrigatório.** Execuções isoladas com métricas e comparações por tarefa.



**Evidências concretas.** `third_party/osworld-v2/benchmark_releases/README.md`, `third_party/osworld-v2/docs/PUBLIC_EVALUATION_GUIDELINE.md`, `third_party/osworld-v2/mm_agents/anthropic/tools/computer.py`, `third_party/osworld-v2/docs/PUBLIC_EVALUATION_GUIDELINE_v2.1.md`, `third_party/osworld-v2/hybrid_agents/codex/evaluation_transport.py`; `third_party/osworld-v2/README.md`. Revisão `acdd3493808e`; 1256 arquivos versionados; principais extensões: .py: 642, .json: 407, .md: 75, .png: 46.



#### windowsworld — P1, benchmark



**Resolve.** Benchmark Windows multiaplicativo com tarefas empresariais e checkpoints.



**Aproveitamento de código.** Avaliação por etapas e objetivos finais, útil para agentes que trabalham entre aplicativos.



**Encaixe arquitetural.** Adaptador de AcceptanceSuite por WorkItem e operações de interface real.



**Sobreposições e limitações.** Depende de apps e imagens com configuração própria; pontuação não substitui auditoria.



**Aceite obrigatório.** Avaliar etapas intermediárias, falhas, retry seguro e resultados finais.



**Evidências concretas.** `third_party/windowsworld/desktop_env/evaluators/metrics/libreoffice.py`, `third_party/windowsworld/desktop_env/evaluators/README.md`, `third_party/windowsworld/desktop_env/evaluators/__init__.py`, `third_party/windowsworld/desktop_env/evaluators/getters/vlc.py`, `third_party/windowsworld/desktop_env/evaluators/metrics/pdf.py`; `third_party/windowsworld/README.md`. Revisão `fbccd464f94f`; 547 arquivos versionados; principais extensões: .py: 457, .md: 24, .txt: 21, .json: 17.



## V. Arquitetura proposta sem duplicar autoridades



Plataforma de controle principal: SENTRA guarda Principal, WorkItem, Run, Operation, Artifact, PolicyDecision, Budget, Lease, Fencing e Audit.

Camada de transporte: ACP para CLIs; A2A para serviços/agentes; MCP para ferramentas; NATS para eventos. Transporte não substitui commit durável.

Camada de execução: WindowsUIA/UFO, Daytona/gVisor, WindowsContainers/hcsshim, browsers Playwright, workflows RPA/Activepieces, desktop Guacamole/RustDesk.

Camada de confiança: autorização do SENTRA recebe identidades SPIRE/OIDC e decisões opcionais OpenFGA/OPA; ToolHive isola ferramentas; Tessera recebe raízes de auditoria; OpenTelemetry transporta sinais.

Camada visual: Canvas próprio e physics rope; Yjs/Hocuspocus para layout/notas/presença; OpenHands/xyflow fornecem padrões visuais selecionados.



### Contratos recomendados no SENTRA



- Machine: ID, principal proprietário, capacidades tipadas, provider, atestação e estado observado.

- AgentSession: agente lógico, modelo/CLI/provedor, transporte ACP/A2A/MCP, permissions e estado de conversa isolado.

- ToolSession: autoridade de autorização, escopo workspace, limites de FS/network, audit context.

- ExecutorAdapter: discover, authorize, start, observe, cancel, reconcile, snapshot opcional, cleanup e evidence.

- EventEnvelope: source_instance_id, source_epoch, source_seq, operation_id, idempotency_key, content hash e timestamps.

- AuditProof: hash de evento canônico, hash chain ou Merkle, checkpoint assinado, prova de inclusão e verificador independente.



### Lacunas ainda não resolvidas apenas por clones



1. Sandbox Windows interativa com isolamento verdadeiro e acesso GUI — combinar conta restrita/VM, Windows UIA, HCS e aprovação, não usar somente Job Objects.

2. Storage transacional hospedado e multiusuário (Postgres nativo com migrations) ainda precisa ser projetado/implementado.

3. Segurança por ação e gerenciamento de consentimento durável, com revogação imediata e sem dois pontos de decisão.

4. Auditoria realmente verificável — projetos de log não garantem completude se recursos executam fora do gateway.

5. Integração total do Canvas com eventos de máquina, rollback, retries, budgets e approval comum.

6. UI refinada com performance de centenas de nós e sessões, além de fonte de dados e estratégia de multiuser.

7. Engenharia de produção: instalação opcional de serviços, licenciamento de componentes individuais, atualizações e testes end-to-end.



## VI. Ordem de integração priorizada



| Etapa | Objetivo testável | Projetos |

|---|---|---|

| A | Contrato Machine + Executor + PolicyDecision em todo side effect | Núcleo SENTRA / UFO / ACP / A2A |

| B | Computer Use Windows real com autorização e isolamento | pywinauto / UFO / hcsshim |

| C | Sandbox opcional de agentes com snapshot/recovery | Daytona / gVisor |

| D | MCP seguro e descoberta de agentes | ToolHive / OpenHands SDK / ACP registry |

| E | Eventos multinó e identidades rotativas | NATS / SPIRE |

| F | Auditoria forte e tracing | Tessera / OTEL Collector / Langfuse |

| G | Web Canvas compartilhado e presença | Yjs / y-protocols / Hocuspocus |

| H | Controle visual de máquinas remotas | Guacamole; RustDesk opcional |

| I | Apps, SaaS, automações e catálogo de fluxos | Playwright MCP / Activepieces / RPA Framework |

| J | Qualidade: benchmarks + supply chain | WindowsWorld / WindowsAgentArena / OSWorld-V2 / Grype |



## VII. Como aproveitar código diretamente com menos risco de quebrar o projeto



- **Incorporar bibliotecas pontuais primeiro:** pywinauto, Yjs, y-protocols, cliente MCP TS, handlers de ferramentas/browser, algumas libs do RPA Framework.

- **Serviço externo com adapter quando pesado:** Daytona, Guacamole, ToolHive, NATS, SPIRE, Keycloak, Hocuspocus, Activepieces, OpenTelemetry Collector.

- **Adaptar protocolos ou padrões sem copiar o app completo:** ACP/A2A, UFO Galaxy, OpenHands Agent Server, Temporal, LangGraph, OpenFGA/OPA.

- **Não incluir em produto executável:** suites de benchmark, assets de treino, imagens de avaliação, dados privados de teste.

- Para módulos incorporados, armazenar o SHA original, LICENSE/NOTICE, arquivo de origem, alteração local e testes. A ausência de intenção comercial não elimina necessariamente obrigações ao distribuir aos amigos.



## VIII. Critérios de conclusão de engenharia



- Todo adapter novo deve ter sucesso, falha, timeout, concorrência, duplicação, cancelamento, revogação e reconciliação testados.

- Modelos externos só contam como operantes quando houver uma resposta real autenticada, não apenas subprocesso vivo.

- Toda operação irreversível exige aprovação por policy, com prova de identidade, escopo e artefato resultante.

- CRDT só gerencia interface; GitHub code/CI nunca embute credenciais; clones não rodam em nome do usuário sem avaliação.

- Antes de dizer que o produto está pronto: E2E em dois computadores reais e dois amigos, com cabo visual, agentes comunicando, sessão desktop remota e audit proofs verificáveis.



## IX. Arquivos de pesquisa



- `third_party/SENTRA_SOURCES_MANIFEST.json` — SHA e origens de 37 repositórios.

- `third_party/SENTRA_COMPREHENSIVE_SOURCE_INDEX.json` — estrutura e candidatos de código.

- `third_party/SENTRA_CLONE_VERIFICATION.json` — verificação de Git.

- `docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md` — este estudo.


## X. Evidências adicionais descobertas na inspeção de código (prioridade para decisões)

1. **UFO / Constellation já implementa DAG real.** Em third_party/ufo/galaxy/agents/constellation_agent.py, a classe ConstellationAgent implementa processamento de pedidos/resultados, invoca TaskConstellationOrchestrator, cria e atualiza DAGs e mantém estados de tarefas. Os objetos do SENTRA Goal/WorkItem podem reutilizar a estratégia de composição, mantendo a validação e a autoridade durável no SENTRA. Isso reduz a necessidade de construir outro motor de planejamento visual desde zero.
2. **ToolHive requer política obrigatória configurada pelo integrador.** third_party/toolhive/pkg/runner/policy_gate.go contém PolicyGate.CheckCreateServer(), mas sua implementação padrão NoopPolicyGate devolve allow. O SENTRA não deve confiar nessa configuração por padrão: registrar uma implementação customizada deny-by-default ainda no startup, exigir verificação por tool call e bloquear iniciação se autorização externa não estiver funcional. PolicyGate de criação não prova que todo método executado pelo MCP ficou protegido.
3. **Tessera já oferece lifecycle com batching e witness.** third_party/tessera/append_lifecycle.go implementa limites e tempos de lote, publicação de checkpoints, witness, mirror e tratamento de filas. Bons padrões para log de provas do SENTRA. Isso NÃO significa que o SENTRA automaticamente capturará todas as operações; a instrumentação precisa morar no ponto de autorização/efeito.
4. **Hocuspocus fornece ganchos suficientes para um Canvas com amigos.** third_party/hocuspocus/packages/server/src/Hocuspocus.ts implementa onConnect, onRequest, beforeSync, beforeHandleMessage, awareness e onStoreDocument, além de quotas para mensagens não autenticadas e estados de documentos. É possível configurar autorização/limite por workspace; políticas de execução continuam no Control Plane.
5. **WindowsWorld já disponibiliza métricas para fluxos de escritório.** third_party/windowsworld/README.md documenta 181 tarefas, 17 aplicações, 77,9% com múltiplos apps e aproximadamente 4,97 checkpoints intermediários por tarefa. Necessita ambiente Windows em VM e utilitários de provisionamento; é um excelente critério mensurável para avaliar o SENTRA Machine Runtime sem tocar em dados pessoais.
6. **Daytona pode fornecer Computer Use estruturado, além de pixels.** third_party/daytona/libs/computer-use/pkg/computeruse/accessibility.go modela escopos focused/PID/all, ações e estados por AT-SPI; third_party/daytona/libs/sdk-python/src/daytona/_sync/sandbox.py expõe process, fs, git e computer_use como subsistemas do Sandbox. Sugestão: adaptar o SDK por API e mapear cada ação a uma operação autorizada SENTRA.
7. **A aplicação Web e os agentes devem continuar desacoplados.** Em third_party/openhands/docs/architecture.md, o Agent Canvas é frontend de estado/apresentação e o OpenHands Agent Server é responsável pelo runtime; third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/README.md descreve REST/WebSocket. Preservar essa fronteira na migração multiusuário do SENTRA.

### Decisões de reaproveitamento imediato

- Código **copiável/encapsulável** com pouco acoplamento: pywinauto para UIA Windows, bibliotecas Yjs/y-protocols, cliente MCP TypeScript, componentes RPA especializados, classes de contratos ACP/A2A.
- **Serviços implantáveis isoladamente:** Daytona, ToolHive, NATS, SPIRE, Hocuspocus, Guacamole, OpenTelemetry Collector.
- **Padrões arquiteturais para adaptar, não substituir:** Constellation do UFO, OpenHands Server, Temporal, LangGraph, OpenFGA e OPA.
- **Evidência/qualidade:** Tessera (trilha), Grype (vulnerabilidades), WindowsWorld e WindowsAgentArena (tarefas Windows), OSWorld-V2 (cross-platform).
- **Nenhum clone foi executado**; essas decisões ainda requerem protótipos isolados com testes positivos, negativos e de recuperação antes da incorporação ao SENTRA.

### Sequência mínima de entregas técnicas para transformar pesquisa em produto

A) Criar schemas de Machine, Capability, AgentSession e ExecutorAdapter (test-first) usando Run/Operation/WorkItem/PolicyDecision existentes.

B) Integrar pywinauto e ações Windows do UFO como adaptadores tipados com UIA sob um usuário/VM restritos; autorização por PID/aplicação/ação e logs de resultado verificáveis.

C) Adicionar DaytonaProvider por SDK externo sem exigir Daytona para quem usa apenas máquinas locais; testar sandbox lifecycle/snapshots e fallback explícito.

D) Envelopar ToolHive como MCP ToolHost deny-by-default e compatibilizar ACP/A2A nas fronteiras de agentes externos.

E) Introduzir NATS + SPIRE para dispositivos remotos e Tessera + OpenTelemetry para transparência/observabilidade, mantendo SQLite local no modo single-user.

F) Ligar Hocuspocus + Yjs à apresentação (somente layout/anotações/presença) e planejar armazenamento hospedado transacional separado do grafo UI.

G) Estabelecer suíte WindowsWorld + WindowsAgentArena + Grype como critérios de aceitação do Machine Runtime, com fixtures/desktops isolados.


### Fonte REE ? docs/SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md

# SENTRA — Reavaliação técnica dos 37 projetos clonados

Data: 2026-10-09. Projeto: `C:/Users/vitor/OneDrive/Desktop/SENTRA`.

## Resultado da reavaliação

**O alinhamento anterior está correto como direção arquitetural, mas não esgota o reaproveitamento e não fecha todas as lacunas do SENTRA.** Há recursos adicionais úteis em quase todas as famílias: memória de experiências, compactação de contexto, recuperação de streams, descoberta seletiva de ferramentas, terminais remotos persistentes, gravação de sessões, verificadores de resultados e colaboração com histórico.

O principal trabalho restante é conectar essas peças ao produto existente. Um contrato implementado, uma simulação local e um serviço externo funcionando são níveis diferentes de entrega. Copiar mais componentes sem fechar essas conexões aumenta o número de módulos, mas não necessariamente a capacidade do SENTRA.

Para o uso individual informado pelo usuário, a prioridade proposta é: agentes interoperáveis reais, execução Windows/browser confiável, documentos e conectores úteis, diagnóstico e recuperação. Infraestrutura de vários servidores ou usuários entra quando houver uma necessidade concreta. Esta revisão trata exclusivamente de reaproveitamento técnico; licenças não foram reavaliadas.

## Base e alcance

Documentos confrontados:

- [Auditoria integral de 08/10](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md).
- [Estudo de reaproveitamento de 08/10](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_THIRD_PARTY_REUSE_2026-10-08.md).
- [Matriz de absorção Gate 5](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md).

A lista de projetos veio do [manifesto local](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/SENTRA_SOURCES_MANIFEST.json). Nesta rodada, os **37 HEADs correspondem aos commits do manifesto e as 37 árvores dos clones estão limpas**. O estudo anterior de reaproveitamento contém etapas históricas de 23 clones; a auditoria integral e o manifesto são a referência para o conjunto atual de 37. `codex-chatgpt-web` está fora desse conjunto.

Foram inspecionados contratos, módulos e trechos de implementação selecionados individualmente em cada clone, além dos pontos correspondentes no SENTRA. Esta é uma reavaliação estática orientada a integração, não uma leitura linha a linha de todos os arquivos dos projetos externos. Nenhum runtime externo foi iniciado nem benchmark externo executado nesta rodada. As propostas e os critérios de entrega abaixo não são resultados de testes já realizados.

Evidência auxiliar da inspeção, com caminhos, linhas e commits:

- [Verificação dos 37 pins](C:/Users/vitor/.codex/visualizations/2026/10/09/01a120e0-6942-74a1-8b36-731fc500d980/reuse-pin-verification.json).
- [Trechos por projeto](C:/Users/vitor/.codex/visualizations/2026/10/09/01a120e0-6942-74a1-8b36-731fc500d980/reuse-evidence.json).
- [Evidência complementar](C:/Users/vitor/.codex/visualizations/2026/10/09/01a120e0-6942-74a1-8b36-731fc500d980/reuse-extra-evidence.json).
- [Leituras focadas de comportamento](C:/Users/vitor/.codex/visualizations/2026/10/09/01a120e0-6942-74a1-8b36-731fc500d980/reuse-focused-evidence.json).

## Ajustes necessários no entendimento do estado atual

1. **Interop ainda não despacha efeitos externos pela ponte central.** [CentralInteropAdapter](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_interop/central.py:69) passa `control.durable` diretamente ao contrato de admissão; essa interface exige métodos diferentes dos oferecidos diretamente pelo serviço. Já existe [CentralDurableIntentAuthority](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_runtime/central_authority.py:23), que adapta a reserva transacional do mesmo banco. Mesmo se essa ligação for corrigida, [o despacho continua bloqueado](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_interop/central.py:152) até existir controle de fencing na fronteira real do provedor. Não basta remover o bloqueio.

2. **A colaboração tem código real de biblioteca, mas a autoridade de referência é local.** [sqlite_host.mjs](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_collab/sqlite_host.mjs:1) se apresenta explicitamente como referência local, sem integração de autenticação. [server.mjs](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_collab/server.mjs:17) exige callbacks de grants, nonce e persistência. Falta vinculá-los ao host autoritativo e ao fluxo real de edição do Canvas.

3. **Os snapshots CRDT não correspondem à família de pacotes usada no SENTRA.** O clone Yjs declara `@y/y` **14.0.0-rc.28**; y-protocols declara `@y/protocols` **1.0.6-rc.1** e importa `@y/y`. Hocuspocus 4.7.0 e o [package.json do SENTRA](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_collab/package.json) dependem de `yjs ^13.6.8` e `y-protocols ^1.0.6`. Tratar os clones como dependências diretamente intercambiáveis é incorreto. Isso evidencia uma divergência de pacote/API; a compatibilidade de dados e wire precisa de teste próprio.

4. **O clone Playwright MCP não contém a implementação completa do executor.** Seu [index.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/index.js:18) exporta `tools.createConnection` de `playwright-core/lib/coreBundle`. O [README de src](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/src/README.md) aponta a implementação para o monorepo Playwright. Portanto, o pin do clone não substitui o pin e a inspeção do pacote efetivamente executado.

5. **HCS, runsc, A2A/SSE, OpenHands e Activepieces possuem mais fronteiras locais do que a matriz de 08/10 registrava.** Isso mostra avanço do código, mas não comprova serviços externos operando. O caso HCS ainda requer um [provider injetado](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_executors/winhcs_boundary.py:64); Activepieces continua com [fixture loopback](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_interop/activepieces_loopback.py:46); o bridge de workflows é [SQLite local](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_interop/workflow_bridge.py:30), não execução Temporal/LangGraph.

6. **O gate Grype interpreta relatórios, não executa a varredura.** [evaluate_grype_json](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_quality/grype_gate.py:40) acrescenta validação útil, mas ainda falta produzir o inventário do artefato e obter o relatório de uma execução real do scanner. O mesmo cuidado vale para OTLP local versus Collector implantado, hash chain versus Tessera e JWT verificado versus login OIDC completo.

## Matriz de decisão técnica

P0 = próximo ciclo de uso real; P1 = próximo ganho funcional ou de qualidade; P2 = condicionado a escala ou necessidade. As frentes são as da matriz anterior, com colaboração indicada quando necessário; não representa atribuição de trabalho a agentes nesta conversa.

| Projeto | Principal ampliação recomendada | Prioridade | Frente |
|---|---|---|---|
| ufo | Memória de experiências, edição reversível de planos e seleção por capacidade | P1 | EXEC-001 + COORDENADOR |
| openhands | Recuperação de eventos por sequência, saúde de backends e relações pai/filho | P1 | CRIT-003 + CRIT-002 |
| openhands-agent-sdk | Compactação de contexto, análise de comandos e recuperação de sessão | P0 | CRIT-002 + COORDENADOR |
| agent-client-protocol | Lifecycle completo de sessão, configuração e semântica correta de updates | P0 | CRIT-002 |
| acp-registry | Distribuição por plataforma, ambiente reservado e diagnóstico de instalação | P1 | CRIT-002 |
| a2a | Artefatos incrementais, continuidade de tarefa e notificações assíncronas | P1 | CRIT-002 |
| mcp-typescript-sdk | Negociação de revisão, subscriptions e interação com input_required | P0 | CRIT-002 |
| daytona | PTY persistente, entradas/logs, previews e políticas de ciclo de vida | P1 | EXEC-001 |
| pywinauto | Esperas limitadas, cache de observação e seletores mais estáveis | P0 | EXEC-001 |
| hcsshim | Recursos, identidade de processo e limpeza de workloads headless | P2 | EXEC-001 |
| gvisor | Perfil de FS/rede e checkpoint experimental de workloads Linux | P2 | EXEC-001 |
| playwright-mcp | Contextos isolados, evidência de browser e política de rede | P0 | EXEC-001 + CRIT-002 |
| guacamole-client | Viewer e reprodução temporal de sessões | P1 | EXEC-001 + CRIT-003 |
| guacamole-server | Gravação seletiva e canais RDP/VNC/SSH separados por capability | P1 | EXEC-001 |
| rustdesk | Provedor alternativo para máquinas sem RDP/VNC acessível | P2 | EXEC-001 |
| langgraph | Subfluxos, memória por namespace e recuperação de etapas | P1/P2 | CRIT-002 |
| temporal | Semântica de retries, recuperação e versionamento de workers | P2 | COORDENADOR |
| nats-server | Transporte com ack, backpressure, replay e retenção limitada | P2 | COORDENADOR |
| toolhive | Descoberta seletiva de ferramentas e autenticação por backend | P1 | CRIT-002 |
| spire | Identidade de workloads, rotação e bundles de confiança | P2 | COORDENADOR |
| keycloak | Lifecycle de login/sessão, revogação e token exchange | P2 | COORDENADOR |
| openfga | Descoberta autorizada de recursos e invalidação de relações | P2 | COORDENADOR |
| opa | Políticas versionadas, distribuição e decisão explicável | P1/P2 | COORDENADOR |
| tessera | Verificação independente de checkpoints e provas | P2 | COORDENADOR |
| immudb | Estado confiável no verificador e exportação verificável | P2 | COORDENADOR |
| opentelemetry-collector | Batching, filas limitadas, retries e correlação transversal | P1 | COORDENADOR |
| langfuse | Datasets de regressão, versões de prompts e avaliações | P1 | COORDENADOR |
| grype | Scan real, estado de correção e validade da base de vulnerabilidades | P1 | COORDENADOR |
| xyflow | Renderização de nós visíveis e acessibilidade de grafo | P1 | CRIT-003 |
| yjs | Undo por origem, cursores relativos e sincronização por diferenças | P1 | CRIT-003 |
| y-protocols | Presença com expiração, clocks e vínculo à conexão | P1 | CRIT-003 |
| hocuspocus | Persistência, reconexão e limites; Redis quando houver vários hosts | P1/P2 | CRIT-003 |
| activepieces | SDK de peças, forms, triggers e dedupe sem importar o produto inteiro | P1 | CRIT-002 |
| rpaframework | Excel, PDF e tabelas como capacidades determinísticas | P0/P1 | EXEC-001 |
| windows-agent-arena | Observação híbrida UIA/visão e harness em VM | P1 | EXEC-001 |
| osworld-v2 | Verificadores compostos e avaliação em checkpoints | P1 | EXEC-001 + COORDENADOR |
| windowsworld | Verificação semântica de artefatos e fluxos entre aplicativos | P1 | EXEC-001 + COORDENADOR |

## Reavaliação individual

### 01. ufo

**Alinhamento anterior:** automação Windows e padrões Galaxy/Constellation continuam úteis. A decomposição em DAG se sobrepõe ao OMA; seu valor adicional deve estar na operação de aplicativos e na qualidade dos planos.

**Ampliar:** transformar execuções bem-sucedidas e malsucedidas em experiências recuperáveis; usar edição com histórico para revisar planos; aproveitar critérios de escolha de dispositivo por capacidade e carga como sugestões para o controlador SENTRA.

**Evidência:** [ExperienceSummarizer](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/ufo/ufo/experience/summarizer.py:165) cria documentos com metadados e índice vetorial; [CommandHistory](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/ufo/galaxy/constellation/editor/command_history.py:15) mantém undo/redo; [ConstellationManager](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/ufo/galaxy/constellation/orchestrator/constellation_manager.py:132) oferece estratégias de atribuição.

**Encaixe e limite:** acrescentar experiências à memória existente do SENTRA, com origem, escopo, resultado e validade. O carregamento FAISS do clone usa `allow_dangerous_deserialization=True`; esse trecho não deve ser transplantado como importador de memória externa. Undo de plano não desfaz ações já executadas em aplicativos.

**Entrega verificável:** uma segunda tarefa recupera uma experiência pertinente e mostra sua origem; uma experiência obsoleta não é usada; edição do plano gera revisão sem repetir efeitos anteriores.

### 02. openhands

**Alinhamento anterior:** aproveitar UX de agentes, conversas, arquivos e ações continua adequado. A aplicação inteira exigiria outra pilha de frontend e estados paralelos.

**Ampliar:** recuperação de eventos após reconexão, representação de relações entre conversas e indicação de backends que falham repetidamente. Isso melhora o Canvas e as sessões existentes sem exigir sua substituição.

**Evidência:** [session-seq-cursor.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands/src/utils/session-seq-cursor.ts:1) trata gaps e replay de sequências; [health-store.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands/src/api/backend-registry/health-store.ts:46) conta falhas e desabilita probes; [child-conversation-launch.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands/src/services/child-conversation-launch.ts) mantém metadados de lançamento e relação com conversas.

**Encaixe e limite:** adaptar cursor e deduplicação ao journal do SENTRA; relações pai/filho precisam continuar em Run/WorkItem/Chat no backend. `localStorage` pode guardar preferências de UI, mas não ser o registro durável de lançamentos.

**Entrega verificável:** derrubar a conexão durante eventos fora de ordem; reabrir o Canvas e recuperar todos os eventos persistidos sem duplicar mensagem nem lançar outro agente.

### 03. openhands-agent-sdk

**Alinhamento anterior:** usar provider e eventos tipados é correto, mas o SDK oferece mais do que uma conexão com Agent Server. Os adapters SENTRA atuais ainda não comprovam uma sessão no servidor externo.

**Ampliar:** compactação de contexto que preserva o system prompt e eventos iniciais; analisadores estruturados de comandos; política de confirmação por risco; recuperação da posse de sessão com geração e expiração.

**Evidência:** [LLMSummarizingCondenser](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py:54), [policy_rails.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/security/defense_in_depth/policy_rails.py:68) e [conversation_lease.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/conversation_lease.py:24).

**Encaixe e limite:** adotar esses padrões no gerenciamento de contexto e no provider. Manter transcrição original e referências às operações fora do resumo. A classificação de risco ajuda a decidir o fluxo; não concede capability. O lease do Agent Server é posse interna do processo externo, subordinada à admissão do SENTRA.

**Entrega verificável:** conversa longa resume contexto sem perder instruções ou pendências; servidor reinicia e reanexa à mesma sessão; uma tool call aponta para a Operation correspondente.

### 04. agent-client-protocol

**Alinhamento anterior:** o subconjunto `session/new`, prompt, updates e cancel constitui um primeiro adapter, não a cobertura completa de um cliente de agentes.

**Ampliar:** resume, close, list e delete quando anunciados pelo agente; configuração de sessão/modelo; uso/custos reportados; conteúdo estruturado, terminais e arquivos; interação para coletar dados ou decisões do usuário.

**Evidência:** [agent.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/agent.rs:1228) contém lifecycle de sessão; [tool_call.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/tool_call.rs:18) explicita a diferença entre campo ausente, `null` e valor; [elicitation.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/elicitation.rs) contém os tipos de interação.

**Encaixe e limite:** negociar versão e capabilities antes de oferecer controles na UI. Não apagar dados recebidos ao aplicar um update parcial. Recursos experimentais do schema precisam continuar condicionados à revisão e à implementação do agente escolhido.

**Entrega verificável:** conectar um agente ACP externo, retomar sua sessão e configurar um recurso suportado; updates parciais preservam os campos antigos; recurso não anunciado não aparece como disponível.

### 05. acp-registry

**Alinhamento anterior:** o catálogo deve continuar separado de instalação e execução. O descriptor local existente cobre somente parte do problema de entregar um agente utilizável.

**Ampliar:** seleção de distribuição por sistema/arquitetura, diferenças entre binary/npx/uvx, ambiente reservado, diagnóstico de instalação e encerramento da árvore de processos.

**Evidência:** [agent.schema.json](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/acp-registry/agent.schema.json:68) descreve variantes de distribuição; [registry_utils.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/acp-registry/.github/workflows/registry_utils.py:116) filtra variáveis reservadas e oferece helpers de grupos de subprocessos.

**Encaixe e limite:** evoluir o catálogo para responder “qual distribuição roda aqui e quais dependências faltam?”. O hash do clone não autentica automaticamente cada pacote ou binário baixado. Aproveitar verificação de artefatos e um plano de instalação com versão fixada. Não transformar atualização de catálogo em execução automática.

**Entrega verificável:** escolher a variante Windows correta, rejeitar descriptor incompatível e manter a configuração conhecida quando a nova instalação falhar.

### 06. a2a

**Alinhamento anterior:** converter tasks e artifacts para WorkItem e Artifact é adequado. O código local evoluiu para fixtures de transporte e SSE; continua faltando um par de agentes externos reais.

**Ampliar:** continuidade de tarefas que aguardam entrada, artefatos em chunks, Agent Card autenticado/estendido, capacidades opcionais e push notifications para tarefas demoradas.

**Evidência:** [a2a.proto](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/a2a/specification/a2a.proto:167) define Task/context; [TaskArtifactUpdateEvent](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/a2a/specification/a2a.proto:308) diferencia append e último chunk; [AgentCapabilities](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/a2a/specification/a2a.proto:412) anuncia streaming, push e extensões.

**Encaixe e limite:** persistir a correspondência entre IDs externos e internos. Chunks precisam formar um artefato completo verificável, com limites e proveniência. O protocolo e o schema não fornecem, sozinhos, um runtime A2A nem a autoridade de execução.

**Entrega verificável:** tarefa externa pausa por entrada e retoma; reconexão recupera o artefato completo sem duplicar chunks; callback de outra identidade não altera a tarefa.

### 07. mcp-typescript-sdk

**Alinhamento anterior:** usar o SDK como cliente de tools/resources/prompts é correto. O `MCPTypescriptCompatClient` SENTRA é uma implementação Python para fixtures; isso não prova compatibilidade com o SDK TypeScript real.

**Ampliar:** negociação de revisão do protocolo, subscriptions de mudança de catálogo, interações `input_required`, validação de respostas e streams com reconexão. São recursos particularmente úteis para ferramentas dinâmicas e solicitações de dados durante uma chamada.

**Evidência:** [client.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/mcp-typescript-sdk/packages/client/src/client/client.ts:237), [protocol.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/mcp-typescript-sdk/packages/core-internal/src/shared/protocol.ts:1012) e [subscriptions.md](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/mcp-typescript-sdk/docs/clients/subscriptions.md:7).

**Encaixe e limite:** o snapshot distingue conexões de 2025 e a revisão 2026-07-28; também documenta depreciação de roots/sampling e Tasks como extensão em determinados caminhos. Implementar por revisão negociada, não por uma lista genérica de métodos. Auto-fulfilment e retry interno do cliente precisam respeitar a identidade da Operation e a admissão de efeitos.

**Entrega verificável:** cliente TS real conversa com servidor SENTRA, anuncia apenas recursos compatíveis e trata uma interação sem executar a mesma ação externa duas vezes.

### 08. daytona

**Alinhamento anterior:** sandbox Linux, Computer Use e snapshots continuam valiosos. O adapter atual e o lifecycle separado são uma base, não prova de provisionamento operacional completo.

**Ampliar:** PTYs persistentes com conexão/resize/kill; sessões de comandos, entrada stdin e logs separados; previews de serviços; rede e políticas de auto-stop/archive/delete; volumes e metadados de ambiente.

**Evidência:** [process.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/daytona/libs/sdk-python/src/daytona/_sync/process.py:562) oferece lifecycle de PTY; [sandbox.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/daytona/libs/sdk-python/src/daytona/_sync/sandbox.py:79) modela volumes, intervalos e rede; [PTYManager](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/daytona/apps/daemon/pkg/toolbox/process/pty/manager.go:18) mantém sessões.

**Encaixe e limite:** tratar o terminal remoto como ProcessSession exibida pelo Canvas existente. Provisionamento, escrita stdin, preview e destruição são capacidades distintas. Snapshot de disco, backup de ambiente e estado de processo precisam ter garantias separadas; restore não autoriza repetir uma Operation incerta.

**Entrega verificável:** terminal persiste após desconexão da UI, logs retomam, rede segue o perfil escolhido e o encerramento remove apenas os recursos daquela execução.

### 09. pywinauto

**Alinhamento anterior:** UIA/Win32 e esperas semânticas são a opção mais direta para aplicativos Windows acessíveis. Os bindings SENTRA existentes ainda precisam de comprovação nos aplicativos alvo.

**Ampliar:** construir um repertório de seletores por aplicativo, esperar estado do controle em vez de tempos fixos, aproveitar cache de propriedades em observações grandes e combinar backend UIA/Win32 quando necessário.

**Evidência:** [timings.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/pywinauto/pywinauto/timings.py:309), [UIAElementInfo](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/pywinauto/pywinauto/windows/uia_element_info.py:104) e [Application.connect](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/pywinauto/pywinauto/windows/application.py:299).

**Encaixe e limite:** cache melhora observação, mas uma ação precisa revalidar elemento e processo. Retry de localizar/observar não equivale a retry de clique ou envio. PID restringe o alvo; não cria isolamento do sistema operacional. Interfaces sem árvore exigem outro método de observação.

**Entrega verificável:** fluxo de aplicativo com carregamento variável funciona com timeout limitado; controle recriado não recebe ação por referência antiga; resultado é confirmado semanticamente.

### 10. hcsshim

**Alinhamento anterior:** manter como backend opcional para workloads Windows headless. Sua existência não fecha a necessidade de um desktop interativo isolado.

**Ampliar:** padrões de JobContainer, limites de recursos, associação de processos, obtenção de token de usuário, lifecycle HCS/uVM, mounts e limpeza de processos descendentes.

**Evidência:** [jobcontainer.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hcsshim/internal/jobcontainers/jobcontainer.go), [logon.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hcsshim/internal/jobcontainers/logon.go:98) e [create_wcow.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hcsshim/internal/uvm/create_wcow.go:63).

**Encaixe e limite:** o [binding SENTRA](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_executors/winhcs_boundary.py) tem create/status/terminate condicionados ao provider. Falta um provider real e diagnóstico de suporte do host. Grande parte do código upstream está em pacotes Go `internal`; o caminho prático é um serviço/shim com API estreita, não importar esses arquivos diretamente para Python.

**Entrega verificável:** workload headless inicia no host suportado, respeita limites e termina com seus filhos; uma VM com sessão GUI deve ser uma prova separada.

### 11. gvisor

**Alinhamento anterior:** reforço de sandbox Linux por runsc continua válido. Há agora uma fronteira local SENTRA para runsc, sem equivaler a uma implantação demonstrada.

**Ampliar:** perfis de acesso a filesystem, rede e capabilities; diagnóstico de syscalls/workloads incompatíveis; checkpoint/restore de processos quando aplicável.

**Evidência:** [config.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/gvisor/runsc/config/config.go:93), [checkpoint.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/gvisor/runsc/cmd/checkpoint.go:64) e [restore.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/gvisor/runsc/cmd/restore.go:69). O próprio clone descreve checkpoint/restore como experimental.

**Encaixe e limite:** perfil de runsc deve ser uma propriedade de execução, registrada com o ambiente e a imagem. Não transforma o Windows host em sandbox Linux nem garante recuperação transparente de sockets e efeitos externos. O arquivo de checkpoint é um artefato de ambiente com compatibilidade própria.

**Entrega verificável:** um workload Linux representativo passa com o perfil escolhido; tentativa fora do mount/rede é recusada; teste de restore declara exatamente quais estados foram recuperados.

### 12. playwright-mcp

**Alinhamento anterior:** browser isolado e operações estruturadas continuam prioridade alta. O browser lab somente leitura do SENTRA não constitui ainda esse executor completo.

**Ampliar:** contextos isolados, configuração explícita de perfil, traces de sessão, evidência de rede/console e capacidades opcionais para PDF/visão/devtools; vincular referências de elementos à observação atual.

**Evidência:** [config.d.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/config.d.ts:130) anuncia capabilities e opções de evidência; [network config](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/config.d.ts:181) contém allow/block de origins. [index.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/index.js:18) e [package.json](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/package.json:39) mostram a dependência efetiva em Playwright.

**Encaixe e limite:** obter e validar o pacote exato que implementa as tools. Configuração de origem é uma camada de controle do browser, não prova de confinamento completo da rede. Trace é evidência de browser e pode conter conteúdo; requer armazenamento e escopo definidos pelo SENTRA.

**Entrega verificável:** navegar, interagir e gerar resultado em um contexto dedicado; coletar diagnóstico quando falha; descartar contexto sem afetar o perfil principal do usuário.

### 13. guacamole-client

**Alinhamento anterior:** viewer web de desktop remoto é adequado, mas o maior ganho adicional é uma interface de revisão do que aconteceu na sessão.

**Ampliar:** gravação reproduzível com play/pause/seek, estados de conexão, renderização de display e suporte a diferentes canais de entrada/saída. Uma timeline de sessão pode ligar imagem observada, ação e resultado ao journal do SENTRA.

**Evidência:** [SessionRecording.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/SessionRecording.js:1128) implementa controles de reprodução e keyframes; [Client.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Client.js:366) envia eventos de entrada e recebe streams.

**Encaixe e limite:** separar `session.view` de `session.control`, inclusive na UI. Reprodução de gravação deve ser somente visual; nunca reenviar as ações gravadas à máquina. O cliente precisa de um tunnel/proxy operacional; importar o JS não cria a sessão remota.

**Entrega verificável:** acompanhar uma sessão real e depois revisar um intervalo gravado, sem qualquer entrada ser enviada durante o playback.

### 14. guacamole-server

**Alinhamento anterior:** guacd como tradução RDP/VNC/SSH continua complementar aos executores e ao viewer.

**Ampliar:** gravação com escolha explícita de output/mouse/touch/teclado/clipboard; canais de filesystem, clipboard e áudio separados; lifecycle e metadados de conexão para diagnóstico.

**Evidência:** [recording.c](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-server/src/libguac/recording.c:42) permite selecionar o que registrar; [rdp.c](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-server/src/protocols/rdp/rdp.c:84) prepara redirecionamentos e plugins da sessão.

**Encaixe e limite:** projetar cada canal como capability do MachineSession. Uma conexão autorizada para visualizar não deve habilitar implicitamente upload, clipboard ou teclado. O proxy de tunnel precisa integrar o principal do SENTRA e não expor credenciais remotas ao frontend.

**Entrega verificável:** sessão somente visual rejeita entrada e transferência; gravação respeita os canais escolhidos; revogação encerra o tunnel e deixa recibo no journal.

### 15. rustdesk

**Alinhamento anterior:** manter como provedor alternativo de controle remoto. Seu encaixe deve depender de um cenário que Guacamole ou o agente remoto existente não resolvam.

**Ampliar:** considerar caminhos de conexão para máquinas fora da rede local, permissões por sessão/canal, clipboard de arquivos, controle de privacidade e gravação. São possibilidades de provider, não motivos para incorporar o cliente inteiro.

**Evidência:** [connection.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rustdesk/src/server/connection.rs) contém login/permissões e canais; [clipboard_file.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rustdesk/src/clipboard_file.rs:4) traduz mensagens de clipboard; [record_upload.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rustdesk/src/hbbs_http/record_upload.rs:27) processa gravações.

**Encaixe e limite:** não presumir uma API pública e estável de embedding a partir desses módulos internos. Começar por um contrato de provider e uma prova de controle/revogação. Pareamento SENTRA deve continuar identificando a máquina e sua sessão.

**Entrega verificável:** mesma máquina é endereçada pelos IDs internos, sessão pode ser revogada pelo SENTRA e os canais permitidos são demonstrados. Se não houver esse cenário, adiar.

### 16. langgraph

**Alinhamento anterior:** subfluxo subordinado a WorkItem continua apropriado. Evitar outro scheduler global não exige descartar suas bibliotecas e padrões de estado.

**Ampliar:** checkpoints com parent e pending writes, etapas interrompíveis, recuperação seletiva, timeout por ausência de progresso e memória pesquisável por namespace com TTL.

**Evidência:** [checkpoint/base](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langgraph/libs/checkpoint/langgraph/checkpoint/base/__init__.py:140), [pregel/_retry.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langgraph/libs/langgraph/langgraph/pregel/_retry.py:215) e [store/base](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langgraph/libs/checkpoint/langgraph/store/base/__init__.py:203).

**Encaixe e limite:** memória e checkpoint podem complementar o contexto existente. Cada nó com efeito deve invocar o gateway SENTRA; um retry do grafo não pode repetir escrita externa por conta própria. Time travel/fork de estado computacional não desfaz efeitos no mundo.

**Entrega verificável:** subfluxo interrompe por entrada, retoma de checkpoint e preserva etapas concluídas; consulta de memória fica no namespace autorizado. Biblioteca é P1 quando resolve um subfluxo concreto; runtime adicional é P2.

### 17. temporal

**Alinhamento anterior:** extrair semântica de execução durável antes de instalar o servidor é uma boa decisão para o modo individual.

**Ampliar:** distinguir falha transitória de não repetível, impor expiração e máximo de tentativas, representar atualizações admitidas versus concluídas e estudar evolução de workers de fluxos longos.

**Evidência:** [retry.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/temporal/service/history/workflow/retry.go:43) calcula retry a partir do tipo de falha e da política; [update/registry.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/temporal/service/history/workflow/update/registry.go:26) mantém updates admitidos e sua recuperação.

**Encaixe e limite:** o clone é principalmente o servidor Temporal; uma integração de aplicação também exige SDK/worker compatíveis. O SENTRA já tem Runs, leases e recuperação. Usar Temporal somente para subworkloads em que histórico determinístico e timers duráveis justifiquem a operação adicional.

**Entrega verificável:** falha não repetível termina sem retry; atividade com resposta incerta reconcilia antes de tentar outra vez; atualização de worker não altera o resultado de um fluxo em andamento.

### 18. nats-server

**Alinhamento anterior:** JetStream é adequado para transporte entre nós. No uso individual em uma máquina, um broker adicional precisa de uma razão operacional.

**Ampliar:** consumers duráveis com ack explícito, MaxAckPending, backoff e limite de redelivery; replay por posição/tempo; retenção e janela de deduplicação configuradas por classe de evento.

**Evidência:** [ConsumerConfig](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/nats-server/server/consumer.go:93) e [StreamConfig](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/nats-server/server/stream.go:56).

**Encaixe e limite:** publicar pela outbox e reconhecer consumo somente depois da persistência necessária no SENTRA. Deduplicação do broker tem janela finita; não substitui idempotência de Operation. Não transportar streams de terminal e comandos de execução com a mesma política de retenção indiscriminadamente.

**Entrega verificável:** consumer cai depois de receber uma mensagem, recupera e não repete o efeito; backlog permanece limitado e observável. Fila de falhas e reconciliação são decisões da aplicação.

### 19. toolhive

**Alinhamento anterior:** ToolHost, isolamento e autenticação são úteis. Há uma oportunidade adicional de reduzir o catálogo de ferramentas enviado ao modelo.

**Ampliar:** descoberta seletiva por descrição/keywords, métricas de economia de tokens, autenticação específica por backend e token exchange com audience/scope. Isso pode evoluir o catálogo MCP do SENTRA com menos consumo de contexto.

**Evidência:** [optimizer.FindTool](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/vmcp/optimizer/optimizer.go:379), [TokenExchangeStrategy](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/vmcp/auth/strategies/tokenexchange.go:99) e [OutgoingAuthRegistry](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/vmcp/auth/outgoing_registry.go:30).

**Encaixe e limite:** buscar dentro do conjunto de ferramentas já autorizado ao agente; similaridade não concede acesso. [PolicyGate](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/runner/policy_gate.go:11) controla criação de servidor e usa allow-all por padrão, portanto não comprova autorização por tool call. Parte da auditoria está delegada a `toolhive-core`, outra dependência a fixar.

**Entrega verificável:** agente encontra ferramentas pertinentes sem receber as não autorizadas; chamada e credencial ficam vinculadas à Operation; parar o host não perde o diagnóstico.

### 20. spire

**Alinhamento anterior:** identidade de daemons/dispositivos é coerente. O ganho principal é identidade verificável de workloads, além de um identificador de máquina.

**Ampliar:** atestação de processo por seletores, SVID X.509/JWT de curta duração, renovação por subscriptions e bundles de confiança/federação quando houver mais de um domínio.

**Evidência:** [Workload API handler](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/spire/pkg/agent/endpoints/workload/handler.go:54), [workload attestor](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/spire/pkg/agent/attestor/workload/workload.go:27) e [X509 cache](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/spire/pkg/agent/manager/cache/x509_lru_cache.go:45).

**Encaixe e limite:** identidade autenticada se converte em Principal; a capability continua sendo uma decisão SENTRA. Validar atestador adequado ao Windows e ao ambiente real escolhido. Uma instalação local simples pode manter pareamento existente até ter múltiplos workers ou relays que justifiquem SPIRE.

**Entrega verificável:** worker renova credencial sem identidade instável; processo de outro escopo não obtém o SVID; certificado vencido não permite uma nova operação.

### 21. keycloak

**Alinhamento anterior:** login OIDC opcional é apropriado para uso com outras pessoas. Para uma única identidade local, não é requisito para evoluir agentes e executores.

**Ampliar:** ciclo de sessão e logout, revogação de tokens, consentimentos e token exchange para uma audience específica. Isso resolve mais do que apenas verificar a assinatura de um JWT.

**Evidência:** [TokenRevocationEndpoint](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/keycloak/services/src/main/java/org/keycloak/protocol/oidc/endpoints/TokenRevocationEndpoint.java:62) e [StandardTokenExchangeProvider](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/keycloak/services/src/main/java/org/keycloak/protocol/oidc/tokenexchange/StandardTokenExchangeProvider.java:232).

**Encaixe e limite:** o verificador JWT local SENTRA não constitui ainda login/logout OIDC completo. Um token com assinatura válida pode continuar tecnicamente válido após uma mudança de sessão, conforme a estratégia escolhida; definir como revogação externa altera novas admissões internas e conexões abertas.

**Entrega verificável:** login cria Principal coerente; logout/revogação impede novas operações e trata sessões existentes; token de outra audience não é aceito como identidade SENTRA.

### 22. openfga

**Alinhamento anterior:** ReBAC como decisão consultada é útil quando surgem relações entre pessoas, projetos, máquinas e documentos. O veto local existente não é implantação OpenFGA.

**Ampliar:** `ListObjects` para montar um catálogo de recursos acessíveis, `ReadChanges` para invalidar projeções/caches, assertions para testar o modelo e consistência diferenciada para operações sensíveis.

**Evidência:** [list_objects.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openfga/pkg/server/commands/list_objects.go:86), [read_changes.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openfga/pkg/server/commands/read_changes.go:19) e [check_command.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openfga/pkg/server/commands/check_command.go:44).

**Encaixe e limite:** navegar recursos permitidos melhora a UX, mas listagem não substitui autorização da ação. Fixar versão do modelo de relações e registrar a decisão consultada. Não usar contextual tuples fornecidas pelo próprio agente como fonte independente de privilégios.

**Entrega verificável:** alteração de relação remove o recurso da descoberta e bloqueia a próxima ação; cache antigo não permite escrita. Adiar o serviço enquanto a autorização individual existente resolver o cenário.

### 23. opa

**Alinhamento anterior:** PDP contextual opcional é adequado; o módulo local SENTRA já oferece uma fronteira de veto, sem equivaler a um OPA externo integrado.

**Ampliar:** políticas versionadas em bundles, ativação controlada, logs de decisão com revision/decision ID e mascaramento de campos. Regras contextualizadas podem ficar auditáveis e testáveis fora de condicionais espalhadas pelo código.

**Evidência:** [bundle/plugin.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opa/v1/plugins/bundle/plugin.go:444), [EventV1](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opa/v1/plugins/logs/plugin.go:49) e [sdk/opa.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opa/v1/sdk/opa.go:145).

**Encaixe e limite:** iniciar por políticas de rede, ambiente e classes de ação, subordinadas aos grants. Definir semântica para decisão indefinida, indisponibilidade e mudança de versão durante uma operação. Bundle/versionamento é aproveitável mesmo quando o motor completo permanecer opcional.

**Entrega verificável:** mesma entrada e mesma versão produzem a mesma decisão; troca inválida preserva a última política válida; log explica a regra aplicada sem conteúdo sensível desnecessário.

### 24. tessera

**Alinhamento anterior:** testemunhar heads de auditoria é uma boa opção de transparência. Para uso individual, eu reduziria sua prioridade de implantação frente a agentes, executores e recuperação operacional.

**Ampliar:** cliente verificador independente, provas de inclusão/consistência, checkpoints assinados, quorum explícito de witnesses e conservação de evidência de divergência.

**Evidência:** [witness.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/tessera/witness.go:29), [client/client.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/tessera/client/client.go:44) e [append_lifecycle.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/tessera/append_lifecycle.go).

**Encaixe e limite:** exportar digests/checkpoints pela outbox do ledger. Hash chain local e witness independente têm garantias diferentes. Quorum configurado como nenhum não entrega testemunho externo. Prova de inclusão demonstra que um registro foi incluído; não demonstra que todo efeito real foi registrado.

**Entrega verificável:** verificador com estado anterior detecta checkpoint incompatível; receipt aponta ao evento correto. A cobertura de efeitos precisa ser demonstrada pela instrumentação SENTRA.

### 25. immudb

**Alinhamento anterior:** storage verificável alternativo continua possível, mas sua adoção integral concorre com bancos e journals já existentes.

**Ampliar:** provas de inclusão e avanço linear, conservação de estado confiável no cliente/verificador e exportação de transações para recuperação/replicação.

**Evidência:** [verification.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/immudb/embedded/store/verification.go:28), [StateService](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/immudb/pkg/client/state/state_service.go:28) e [stream_replication.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/immudb/pkg/server/stream_replication.go:29).

**Encaixe e limite:** aproveitar o modelo de cliente que guarda o último estado confiável, inclusive para o audit local. Se a necessidade for apenas provar a cadeia existente, começar por um verificador/arquivo de checkpoints é mais simples. Replicar registros não prova que a restauração de todos os artefatos do SENTRA funciona.

**Entrega verificável:** cliente com checkpoint antigo detecta histórico incompatível; restauração recupera os registros previstos e compara o head. Escolher uma necessidade distinta antes de implantar immudb junto de Tessera.

### 26. opentelemetry-collector

**Alinhamento anterior:** exportação OTLP redigida continua adequada. O sink local atual é um ponto de integração inicial, não um pipeline operacional completo.

**Ampliar:** batching por tamanho/tempo, limite de cardinalidade, memory limiter, filas limitadas, retries e exportação desacoplada. Isso pode tornar o diagnóstico resistente a indisponibilidade sem bloquear a execução principal.

**Evidência:** [batchprocessor/config.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opentelemetry-collector/processor/batchprocessor/config.go:16), [queuebatch/config.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opentelemetry-collector/exporter/exporterhelper/internal/queuebatch/config.go:18) e [memorylimiter config](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opentelemetry-collector/processor/memorylimiterprocessor/config.go).

**Encaixe e limite:** correlacionar Run/WorkItem/Operation/Provider/Machine nos spans, sem transformar traces em ledger de autoridade. Fila persistente depende da storage extension configurada; o campo `StorageID` não garante persistência por si. Redação adicional e determinados exporters podem exigir componentes fora do clone core.

**Entrega verificável:** sink fica indisponível, o pipeline respeita limites e depois exporta conforme a retenção definida; diagnóstico mostra perda/fila sem fingir completude de auditoria.

### 27. langfuse

**Alinhamento anterior:** tracing LLM e custos são úteis, mas limitar o projeto a esse papel deixa um dos seus maiores ganhos de fora: aprendizado por avaliação.

**Ampliar:** prompts com versão/labels/config, datasets com entrada e saída esperada, ligação entre dataset run e trace, scores numéricos/categóricos/booleanos/textuais e correções humanas.

**Evidência:** [prompts.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langfuse/packages/shared/src/domain/prompts.ts:5), [dataset-run-items.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langfuse/packages/shared/src/domain/dataset-run-items.ts:5) e [score validation](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langfuse/packages/shared/src/features/scores/interfaces/ingestion/validation.ts:8).

**Encaixe e limite:** converter tarefas pessoais repetidas em regressões do SENTRA, fixando prompt, modelo, ferramentas, ambiente e critério de resultado. Pode-se adotar primeiro o formato e um runner local; a implantação completa é uma decisão posterior. Scores externos auxiliam comparação, sem substituir o QualityGate nem contabilização autoritativa de orçamento.

**Entrega verificável:** comparar duas versões de prompt/provider no mesmo conjunto de casos, mostrando sucesso objetivo, custo, latência e regressões por tarefa.

### 28. grype

**Alinhamento anterior:** scanner de dependências/artefatos continua útil mesmo para uso pessoal. Corrigir a descrição: o objetivo é identificar pacotes e vulnerabilidades conhecidas; não é análise estática geral de cada linha do código.

**Ampliar:** registrar versões com correção disponível, motivo do match, validade da base e diferenças entre scans para orientar atualização de dependências.

**Evidência:** [Fix](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/grype/grype/vulnerability/fix.go:23), [Matcher](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/grype/grype/match/matcher.go:13) e [DBCheck](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/grype/cmd/grype/cli/commands/db_check.go:59).

**Encaixe e limite:** conectar execução real do binário ao parser SENTRA. A identificação de pacotes envolve Syft e formatos de inventário; essas dependências também precisam de versão e procedência registradas. Varredura do checkout não equivale à varredura do pacote/instalador final.

**Entrega verificável:** scan de um artefato conhecido produz relatório correlacionado ao seu digest; base ausente/obsoleta é diagnosticada; recomendação de atualização distingue vulnerabilidade corrigível de sem correção.

### 29. xyflow

**Alinhamento anterior:** extrair ergonomia/performance sem migrar todo o Canvas continua a melhor escolha. Existem algoritmos e padrões concretos para além do aspecto visual de nodes/edges.

**Ampliar:** renderizar somente nós visíveis, seleção e bounds de grafo, descoberta de vizinhos/arestas e descrição acessível com aria-live. Adaptar os princípios ao renderer e à física de cabos existentes.

**Evidência:** [useVisibleNodeIds.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/xyflow/packages/react/src/hooks/useVisibleNodeIds.ts:8), [graph.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/xyflow/packages/system/src/utils/graph.ts) e [A11yDescriptions](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/xyflow/packages/react/src/components/A11yDescriptions/index.tsx:26).

**Encaixe e limite:** o SENTRA já tem módulos locais de acessibilidade e cabos; verificar a ligação ao Canvas antes de reimplementá-los. Desmontar nó fora da viewport não deve destruir a ProcessSession nem perder estado de terminal. Desenho, física e sessão precisam ter lifecycles separados.

**Entrega verificável:** medir pan/zoom/seleção com 100 e 500 nós; esconder nó não encerra o processo; navegação por teclado encontra nós e anuncia mudanças relevantes.

### 30. yjs

**Alinhamento anterior:** CRDT limitado à apresentação permanece correto. Há ganhos além de sincronizar coordenadas e notas.

**Ampliar:** undo/redo limitado à origem do usuário, posições relativas em texto colaborativo e sincronização por state vectors/diffs. Isso permite edição concorrente com histórico local e tráfego incremental.

**Evidência:** [UndoManager](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/yjs/src/utils/UndoManager.js:164), [RelativePosition](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/yjs/src/utils/RelativePosition.js:154) e [updates.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/yjs/src/utils/updates.js:178).

**Encaixe e limite:** o clone é `@y/y` 14 RC; a biblioteca atualmente usada pelo sidecar é `yjs` 13. Adotar primeiro o recurso equivalente na família já integrada, ou estudar uma migração explícita. Undo colaborativo não pode reverter grants, iniciar/encerrar Runs ou repetir execução.

**Entrega verificável:** dois clientes editam notas; desfazer a alteração de um não remove o trabalho do outro; reconexão transmite diferenças; snapshots existentes continuam legíveis na versão escolhida.

### 31. y-protocols

**Alinhamento anterior:** sync e awareness devem permanecer separados de autorização. Presença não precisa virar estado durável do controlador.

**Ampliar:** expiração de presença, clocks de atualização, remoção de clientes desconectados e vínculos entre awareness client ID e sessão autenticada.

**Evidência:** [awareness.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/y-protocols/src/awareness.js:13) usa timeout e clocks; [sync.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/y-protocols/src/sync.js:38) define sync step 1/2 e updates.

**Encaixe e limite:** o clone usa `@y/protocols` e importa `@y/y`, diferente dos pacotes atuais do SENTRA. Awareness pode representar cursor/nome/status visual, mas “online” não demonstra que um agente está executando ou possui o lease. O módulo local `awareness_guard.mjs` já cobre parte do vínculo e da filtragem; falta comprovar isso no Canvas conectado.

**Entrega verificável:** presença expira e reaparece corretamente; cliente não publica estado de outro usuário; uma sessão revogada não permanece enviando awareness.

### 32. hocuspocus

**Alinhamento anterior:** sidecar colaborativo com callbacks de host continua adequado e já usa a biblioteca real em laboratório.

**Ampliar:** persistência por extensão Database, limites de conexão, reconexão e, somente quando houver múltiplas instâncias, propagação por Redis com coordenação de documentos.

**Evidência:** [Database.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hocuspocus/packages/extension-database/src/Database.ts:45), [Throttle](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hocuspocus/packages/extension-throttle/src/index.ts:3) e [Redis.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hocuspocus/packages/extension-redis/src/Redis.ts:78).

**Encaixe e limite:** persistência genérica upstream não substitui o precommit/CAS já construído no SENTRA. Redis locks de documentos não são leases de execução. O passo prioritário é ligar callbacks ao host e edição ao Canvas; adicionar Redis antes disso não fecha o fluxo.

**Entrega verificável:** dois clientes reais editam o Canvas, host recusa update inválido antes de publicar, reinício restaura documento e revogação é aplicada às conexões abertas.

### 33. activepieces

**Alinhamento anterior:** catálogo de conectores SaaS e automações é útil. Importar somente workflows completos de um servidor externo não é a única forma de aproveitamento.

**Ampliar:** reaproveitar o SDK de peças e conectores específicos; propriedades tipadas para gerar formulários; output schemas; hooks de enable/disable, renovação de webhook e dedupe de triggers.

**Evidência:** [action.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/activepieces/packages/pieces/framework/src/lib/action/action.ts:23), [trigger.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/activepieces/packages/pieces/framework/src/lib/trigger/trigger.ts:11) e [oauth2-prop.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/activepieces/packages/pieces/framework/src/lib/property/authentication/oauth2-prop.ts:38).

**Encaixe e limite:** escolher conectores usados de fato e hospedá-los por um executor Node subordinado, ou acionar serviço externo quando necessário. Contexto, storage e helpers do framework são dependências dos conectores; copiar só um arquivo de ação pode não bastar. Retry interno da peça precisa se alinhar à idempotência externa e ao SENTRA.

**Entrega verificável:** um trigger real cria apenas um WorkItem para eventos duplicados; uma ação usa credencial vinculada à conexão escolhida; desligar o trigger remove sua assinatura externa.

### 34. rpaframework

**Alinhamento anterior:** bibliotecas pontuais Python são um ganho direto. A análise anterior deu mais destaque à GUI/browser do que às capacidades determinísticas de documentos.

**Ampliar:** leitura/escrita de Excel sem GUI, tabelas com filtros/agrupamento/conversão, extração/manipulação de PDFs e workflows que verificam seus próprios resultados. Priorizar isso antes de macros baseadas em coordenadas.

**Evidência:** [Excel/Files.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rpaframework/packages/main/src/RPA/Excel/Files.py:194), [Tables.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rpaframework/packages/main/src/RPA/Tables.py:772) e [PDF document.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rpaframework/packages/pdf/src/RPA/PDF/keywords/document.py:588).

**Encaixe e limite:** disponibilizar capacidades explícitas de transformação de arquivos, com escrita temporária e promoção do resultado validado. Excel Files distingue fórmula de valor armazenado; não presumir que editar uma fórmula recalcula o workbook. Extração de texto PDF também não garante OCR ou fidelidade visual.

**Entrega verificável:** tarefa transforma planilha/PDF conhecido e compara conteúdo esperado; falha preserva original; necessidade de recalcular ou renderizar aciona o backend apropriado.

### 35. windows-agent-arena

**Alinhamento anterior:** benchmark Windows em VM continua útil, mas o clone também oferece um laboratório de observação para melhorar o executor.

**Ampliar:** comparação entre UIA, visão e observação mista; representação de elementos numerados na imagem; escolha entre janela e tela; harness de VM e captura de trajetória.

**Evidência:** [Navi agent](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windows-agent-arena/src/win-arena-container/client/mm_agents/navi/agent.py:74) anuncia origens de observação a11y/visão/mistas; [vm.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windows-agent-arena/src/win-arena-container/client/desktop_env/controllers/vm.py:8) gerencia conexão QMP.

**Encaixe e limite:** usar isso para comparar métodos e definir fallback do WindowsUIAExecutor. O adapter do SENTRA continua recebendo ações tipadas; não expor diretamente o executor de código arbitrário de benchmark ao produto. Modelos de visão/OCR e imagens de VM são dependências adicionais.

**Entrega verificável:** mesmo conjunto pequeno de tarefas é repetido com UIA e modo híbrido; diferenças de sucesso/latência são acompanhadas de evidência, versão do ambiente e reset reproduzível.

### 36. osworld-v2

**Alinhamento anterior:** benchmark multietapas continua adequado. O maior reaproveitamento para o SENTRA pode estar no avaliador, sem importar todos os agentes da suíte.

**Ampliar:** composição de métricas com conjunção/short-circuit, resultado estruturado além do score, avaliação intermediária e backend de avaliador separado do agente executante.

**Evidência:** [generated_task_utils.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/osworld-v2/evaluation_examples/task_class/generated_task_utils.py:57), [backend/base.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/osworld-v2/desktop_env/evaluators/backends/base.py:66) e [lib_run_single.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/osworld-v2/lib_run_single.py:27).

**Encaixe e limite:** enriquecer AcceptanceSuite com verificadores objetivos e explicação do resultado. Avaliação por LLM pode ajudar quando necessária, mas é probabilística e deve ser marcada como tal. `postconfig` de avaliador pode alterar ambiente; medir em clone/snapshot ou registrar essa mutação separadamente.

**Entrega verificável:** tarefa apresenta score e evidência de cada critério; checkpoints de avaliação não alteram a conclusão por efeito colateral oculto; resultados se mantêm comparáveis entre providers.

### 37. windowsworld

**Alinhamento anterior:** tarefas Windows entre aplicativos e avaliação por etapas continuam valiosas. Também há verificadores diretamente reutilizáveis para artefatos de trabalho.

**Ampliar:** comparar tabelas/CSV e propriedades de documentos, conferir resultado final em arquivo, reset/snapshot do ambiente e explicar quais critérios foram satisfeitos.

**Evidência:** [metrics/table.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windowsworld/desktop_env/evaluators/metrics/table.py:239), [desktop_env.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windowsworld/desktop_env/desktop_env.py:469) e [getters/replay.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windowsworld/desktop_env/evaluators/getters/replay.py:4).

**Encaixe e limite:** adaptar os verificadores como funções puras sobre artefatos autorizados. O replay do clone constrói comandos pyautogui a partir de strings e inclui um TODO sobre selecionar a janela correta; não é um mecanismo pronto para repetir ações no host. Checkpoint de avaliação, snapshot de VM e recuperação de execução são conceitos diferentes.

**Entrega verificável:** workflow entre aplicativos termina com documento/planilha verificável, critérios por etapa e evidência final; falha no aplicativo é distinguida de falha no avaliador.

## Lacunas que continuam exigindo engenharia no SENTRA

Os 37 projetos fornecem implementações ou padrões para quase todas essas áreas. Nenhum deles conecta automaticamente suas garantias à identidade, ao journal e às interfaces do SENTRA.

| Lacuna | Fontes úteis | Parte que ainda precisa ser entregue no SENTRA |
|---|---|---|
| Admissão e efeito externo ligados ponta a ponta | ACP, A2A, MCP, ToolHive, SDK OpenHands | Ligar CentralDurableIntentAuthority, provider e verificação na fronteira do efeito; observar/reconciliar a mesma Operation |
| Sessão persistente de agente/terminal | ACP, OpenHands SDK/UI, Daytona | Mapa durável de IDs, cursor, reattach e estados após perda de conexão; não recriar sessão por heurística de terminal |
| Desktop Windows isolado e interativo | pywinauto, UFO, Arena, hcsshim | Provedor de VM/sessão compatível, ciclo de vida, arquivos, observação e execução reais; headless HCS não fecha essa entrega |
| Posse de foco/teclado/clipboard | pywinauto, Guacamole, RustDesk | Serializar o recurso compartilhado e definir handoff humano/agente; validar alvo antes de cada ação |
| Recuperação de efeito incerto | Temporal, LangGraph, Daytona, NATS | Consultar estado externo, usar IDs idempotentes quando disponíveis e representar impossibilidade de saber; snapshot não resolve sozinho |
| Evidência e artefatos recuperáveis | A2A, Guacamole, benchmarks, immudb | Guardar bytes/referências/digests e proveniência; digest sem conteúdo não permite inspeção nem restauração |
| Memória útil sem perder instruções | UFO, OpenHands SDK, LangGraph | Memória por escopo, origem, validade e resultado; compactação com transcrição preservada e avaliação de qualidade |
| Descoberta e compatibilidade de ferramentas | Registry, MCP SDK, ToolHive | Negociar versão/capability, validar schema e instalar distribuição correta; catálogo filtra o conjunto autorizado |
| Credenciais e revogação transversal | Activepieces, Keycloak, SPIRE, ToolHive | Vincular conexão/segredo ao principal e operação, invalidar sessões e definir renovação; identidade não é grant |
| Eventos recuperáveis sem duplicar efeitos | OpenHands UI, NATS, MCP | Cursor/outbox/inbox, dedupe durável, limites de fila e revisão do estado projetado |
| Colaboração no Canvas real | Yjs, y-protocols, Hocuspocus | Compatibilidade de pacotes, callbacks do host, edição real, precommit, reautorização e recuperação |
| Canvas com muitos nós | xyflow | Viewport culling sem destruir terminais, limites da física e medição com carga real |
| Qualidade objetiva de tarefas | Arena, OSWorld V2, WindowsWorld, Langfuse | Dataset pessoal, verificadores por artefato, reset e comparação de providers/prompts; incorporar ao QualityGate |
| Diagnóstico atravessando serviços | OTel, Langfuse, ToolHive | Correlação de IDs, redação, política de filas e separação entre resultado operacional e sucesso de exportação |
| Backup e atualização recuperáveis | Daytona, immudb, Temporal como referências | Backup coordenado de SQLite, artefatos e configuração; migrações e teste de restauração do SENTRA inteiro |
| Entrega e instalação das integrações | Registry, Grype, ToolHive | Dependências transitivas fixadas, diagnóstico, serviços opcionais, instalação/remoção e teste de pacote final |
| Vários usuários/hosts, quando necessário | NATS, SPIRE, Keycloak, OpenFGA, OPA | Modelo transacional e migrações para esse modo; o ControlStore atual aceita SQLite, não entrega backend Postgres |
| Independência da prova de auditoria | Tessera, immudb | Verificador com estado confiável e witnesses independentes; demonstrar a cobertura dos efeitos instrumentados |

### Contratos que vale especificar explicitamente

Esses nomes descrevem propostas de integração, não classes já implementadas:

- **AgentSession / ProcessSession:** ID SENTRA e externo, versão/capabilities, cursor, estado de conexão, proprietário, recovery e vínculo a Run.
- **MachineSession / InputLease:** recurso de desktop/browser, contexto/PID/janela, epoch, posse de entrada e handoff entre humano e agentes.
- **Observation / Evidence / Artifact:** instante e revisão de observação, origem, dados ou referência recuperável, digest, estado completo/incremental e vínculo à Operation.
- **ConnectorConnection:** provider, principal, referências a segredos, scopes, renovação/revogação e idempotência suportada pelo serviço externo.
- **ProviderHealth / Compatibility:** dependências disponíveis, revisões suportadas, estado operacional e razão de indisponibilidade mostrada ao usuário.
- **AcceptanceCase:** ambiente/versionamento, resultado esperado, verificadores, custo/latência, seed quando aplicável e evidência da avaliação.

## Ordem proposta para o uso individual

### Ciclo 1 — Tornar o caminho existente utilizável

1. Ligar a autoridade durável à ponte interop e ao provider, mantendo o bloqueio até a fronteira real de efeitos estar resolvida.
2. Demonstrar um agente ACP externo e um cliente MCP TypeScript real, com versão negociada, streaming e reattach.
3. Demonstrar execução Windows em ambiente controlado e browser em contexto isolado, com resultado verificável.
4. Fechar o armazenamento de evidência e a recuperação de operações incertas desses dois caminhos.

Frentes: COORDENADOR + CRIT-002 + EXEC-001. **Aceite:** uma tarefa real passa pelo Canvas/CLI → WorkItem/Run → Operation → provider → artefato → verificador; reinício não cria outro efeito.

### Ciclo 2 — Aumentar utilidade e reduzir custo de contexto

1. Expor capacidades determinísticas de planilha/PDF/tabelas do RPA Framework.
2. Introduzir compactação de contexto do SDK OpenHands e experiências inspiradas no UFO, avaliadas no histórico de tarefas pessoais.
3. Implantar descoberta seletiva de ferramentas inspirada no ToolHive.
4. Selecionar dois ou três conectores Activepieces que o usuário realmente usa.

Frentes: EXEC-001 + CRIT-002 + COORDENADOR. **Aceite:** tarefas repetidas resolvem trabalho concreto, com menos falhas e custo mensurado; memória mostra a experiência usada.

### Ciclo 3 — Diagnóstico, recuperação e regressão

1. Corpus pessoal com formatos Langfuse e verificadores WindowsWorld/OSWorld.
2. Observação híbrida a partir de Arena/UFO quando UIA for insuficiente.
3. OTel com IDs correlacionados e filas limitadas; Grype executado sobre o pacote real.
4. Se máquina remota fizer parte do uso, Guacamole com viewer e playback; se execução Linux fizer parte do uso, Daytona com PTY e lifecycle real.

Frentes: EXEC-001 + COORDENADOR + CRIT-003. **Aceite:** regressões mostram qual critério quebrou; falhas têm evidência recuperável; restauração do conjunto de dados do SENTRA é demonstrada.

### Ciclo 4 — Colaboração e escala sob demanda

1. Ligar o sidecar ao Canvas e à autoridade real, antes de distribuir instâncias.
2. Resolver a escolha Yjs 13 versus família @y 14 e medir desempenho do Canvas usando padrões xyflow.
3. Adicionar NATS/SPIRE/Keycloak/OpenFGA/OPA somente para cenários que exijam essas capacidades.
4. Considerar Temporal, Redis multinó, Tessera, immudb, HCS e gVisor a partir de requisitos concretos e provas próprias.

Frentes: CRIT-003 + COORDENADOR, com CRIT-002/EXEC-001 conforme o provider. **Aceite:** cada serviço novo fecha uma lacuna definida e tem instalação, health, recovery e remoção demonstrados.

## Decisão final

Manter o alinhamento de preservar Canvas, ConPTY, OMA e a autoridade SENTRA. Ampliar o estudo anterior com os módulos concretos apresentados aqui. Para o cenário individual, elevar documentos/RPA, contexto e avaliação objetiva; condicionar infraestrutura distribuída e serviços de identidade à demanda.

A próxima entrega de maior valor é **um fluxo completo real e recuperável**, seguido de capacidades pessoais úteis. O catálogo de 37 projetos é suficiente para fornecer muitas das peças; a integração dessas peças, o isolamento Windows interativo, a recuperação de efeitos e a verificação do resultado continuam sendo trabalho próprio do SENTRA.


### Fonte COS ? docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md

# SENTRA × Chat On Steroids — análise de incorporação (09/10/2026)



**Escopo:** auditoria estática e comparação de código, não incorporação automática. Código upstream **não foi executado** e nenhum agente/serviço recebeu novas permissões. Repositório principal SENTRA mantido no estado de trabalho anterior.



## Proveniência verificada



- Upstream: https://github.com/totec448-spec/chat-on-steroids

- Clone local: `third_party/chat-on-steroids/`

- Branch upstream: `main`; commit exato: `151e7ef96bc16bf594ffbd35efe620e4ef6e4c2c` (merge PR #1246).

- Versão `package.json`: `2.1.31`. Licença do próprio repositório: MIT (retenha o aviso/atribuição em qualquer cópia); terceiros têm notices próprios.

- Primeira tentativa `git clone --depth 1 --filter=blob:none` falhou por DNS, deixando um checkout incompleto. Recuperação: ZIP oficial Codeload do **mesmo commit**, SHA-256 `26b2e7bf7d967fd0490f3937691850881fa205301d260db1519537858c39daa3`; CRC e 1.203 arquivos verificados, **zero divergências de Git blob SHA-1**; objetos locais reconstruídos a partir de bytes autenticados pelo commit; `git status --porcelain`: **limpo**. O diretório é um Git checkout verificável, não apenas uma cópia renomeada.

- Linguagens/integração: Electron 44, TypeScript 7, Node.js, `@modelcontextprotocol/*`, MCPB, node-pty, xterm, CodeMirror, extension Manifest V3, Windows desktop APIs; suporte declarado Windows/macOS/Linux. Não executar `npm install`, hooks, extensão, serviços ou comandos de terceiros até aprovar a fatia selecionada.



## Veredito



**Alto valor para UX e confiabilidade da integração ChatGPT, moderado para infraestrutura de agentes, baixo para substituir a arquitetura central.** O SENTRA já dispõe de Canvas React/WebView2, agentes, CLI, ConPTY, operações duráveis, Control Plane, política de grants, Web Models, execução desktop e comunicação entre peers em desenvolvimento. Chat On Steroids aprofunda **sessão/chat do navegador, seleção por conta, handoff entre chats, outbox com confirmação, plugins MCP instaláveis, skills e UX de arquivos**. Copiar o aplicativo Electron integral geraria duas fontes de verdade e dois executores privilegiados: **não recomendado**.



A regra de incorporação é **um único SENTRA Control Plane**. Adaptadores portados podem oferecer catálogo, contexto e UI, mas nenhum `tool call` externo cria Run, Grant, Lease ou executa efeitos fora de `AuthorizationService` + `DurableRunService` + `DurableOperationGate`.



## Matriz de aproveitamento (caminhos exatos no upstream)



| Prioridade | Capacidade e fonte Chat On Steroids | Estado relativo SENTRA | Aproveitamento concreto / destino no SENTRA | Gate obrigatório |

| --- | --- | --- | --- | --- |

| **P0** | **MCPB/plugin lifecycle:** `src/main/plugins/installer.ts`, `manager.ts`, `oauth.ts`, `exposure.ts` | SENTRA possui `sentra_interop/mcp.py`, `tool_catalog.py`, `sentra_mcp/tool_policy.py`, onboarding; falta evidência de instalação MCPB integrada ao Canvas | Adaptar parsing MCPB seguro (arquivo, path, limite, manifest, source), stdio/HTTP/OAuth, health/restart, inventário e revogação. Encaixar no catálogo autoritativo e no instalador/Quick Start. `pluginExposure()` (62 linhas) é candidata específica a porte para checagem de conflitos e limites, sem substituir policy | Duas ferramentas homônimas **não** colidem nem redirecionam uma chamada; grant obrigatório por capability; sem segredos em logs; uninstall idempotente |

| **P0** | **Modelo real da conta:** `src/main/chat-models.ts`, `src/renderer/chat-models.ts`, `test/model-picker-state.test.ts` | SENTRA tem `/model` numerado em `sentra_cli/repl.py` e `sentra_canvas/service.py::model_catalog`; pode depender da prontidão do Gateway | Adaptar estados `unknown/pending/ready/unavailable`, observação vinculada a nonce, modelo/effort efetivamente oferecidos e escolha **Automatic** para conta sem picker. Exibir observação de conta/modelo no Canvas e CLI, sem inferir direitos de GPT-6 High por nome | Não escolher modelo não anunciado; conta Free/Go sem picker não congela 120 s; cancelamento e troca durante geração não alteram sessão ativa; seleção reconciliada |

| **P0** | **Compact & Resume transacional:** `src/main/session/continuation.ts`, `handoff.ts`, `resume-gate.ts`, `test/continuation.test.ts` | CLI tem `/resume` e `/continue`, runtime guarda work/contexto; não há prova da troca **de uma conversa Web A para B mantendo o mesmo agente/Run/WorkItem** | Portar **o protocolo de fases**, não o módulo 1.807 linhas: open → summary → exclusive claim → preflight → durable commit → publish/abort; rebind de conversation_id dentro do mesmo agente, mantendo leases, grants e proveniência, sem reprodução de efeitos incertos | Crash/reload em cada fase, dois chats concorrendo ao mesmo handoff, abort preserva origem; workers filhos não perdem contexto ou execução |

| **P0** | **Outbox e prova de entrega:** `src/main/session/input.ts`, `recorder.ts`, `store.ts`, `test/input-delivery-integration.test.ts` | SENTRA já tem journals SQLite/outbox de Tasks/Operations, mas entrega de **mensagem ao ChatGPT Web** não deve ser confundida com sucesso do WorkItem | Adaptar estados `not_sent/pending/unconfirmed/sent`, generation/receipt, um envio por chat; correlacionar BrowserRequest/Conversation com Control Plane usando identidade local e revisão, não DOM sozinho | Perda de resposta HTTP, reload, reenvio tardio e interrupção não duplicam mensagens; `unconfirmed` exige reconciliação |

| **P1** | **Workers, equipes e Goal/Loop:** `src/main/agents.ts`, `goal.ts`, `session/request-plans.ts` | SENTRA possui agentes/filhos e `sentra_canvas/task_runtime.py` vinculado a governance; tem planos revisionados `sentra_runtime/plan_history.py` | Reaproveitar tratamento de fila, worker health, retorno de contexto, limites e decisões de conclusão *após* recibos. Opcional `Goal/Loop` com modelo autorizado já configurado; nunca ligar um provedor pago/externo por padrão | Stop/cancel, duplicidade e progresso vinculados a Run; sem execução infinita, sem burlar quota ou refusals |

| **P1** | **Ferramentas de terminal persistente:** `src/main/codex/unified-exec.ts`, `head-tail-buffer.ts`, `truncate.ts`, `test/exec*.test.ts` | SENTRA já possui ConPTY, xterm, CLI e executor/registry | Portar semântica testável de `exec_command/write_stdin`, streaming drenável, head/tail com limite, árvore de processos e output por operation ID, **sobre o terminal do SENTRA**, não novo shell paralelo | Fencing no ponto de efeito; no-repeat; cancelamento mata apenas subprocesso autorizado; saída truncada marcada; Windows quoting |

| **P1** | **Skills versionadas:** `src/main/skill-library.ts`, `skills.ts`, `skill-metadata.ts`, `skill-package.ts`, `test/skills.test.ts` | SENTRA dispõe de ferramentas/provedores e contexto, mas skill registry versionado requer auditoria específica | Catálogo de `SKILL.md` com importação controlada, checksum/revisão, leitura sob escopo, progressive disclosure, ativação explícita e vínculo ao WorkItem | Uma skill nunca acrescenta grant, cwd fora de workspace nem acesso a secrets; revisão imutável por operação |

| **P1** | **API local de observação e ações opt-in:** `src/main/control-api.ts`, `control-reads.ts`, `control-actions.ts` | SENTRA já tem broker/HTTP Canvas e Control Plane | Aproveitar dois níveis de consentimento (leitura e envio de mensagens separadamente), endpoint/token local, host/origin guards, limite de corpo, rate/deadline, outbox e paginação; sem segunda autoridade | Desligado ou leitura por padrão; ações 403 sem segundo consentimento; não vazar URLs MCP, tokens e path de segredo |

| **P1** | **Setup/diagnósticos e reparo:** `src/main/connection.ts`, `tunnel/health.ts`, `setup-profiles.ts`, `docs/setup.md` | SENTRA possui Quick Start, Secure MCP Tunnel, app/plugin manual, Setup/MSI e Doctor | Portar UX de estado `local MCP ready / tunnel healthy / ChatGPT app authorized / extension paired / model verified`, repair por etapa, instruções de reload da extensão e refresh do app MCP após update | Setup não afirma app instalado em conta sem prova externa; telas mostram falhas e ações claras; nenhum segredo copiado |

| **P1** | **Editor e visualizadores de projeto:** `src/renderer/file-panel.ts`, `file-code-editor.ts`, `file-pdf-viewer.ts`, `unified-diff.ts`, `src/main/project-files.ts` | SENTRA Canvas tem nós, notas e terminais; dispõe de workflows/documentos, mas editor visual rico necessita validação E2E | Adaptar painéis laterais discretos CodeMirror/merge e PDF com diffs de arquivos efetivamente autorizados, sem poluir a estética minimalista | Escritas seguem Operation/grant/review; preview jamais executa código; arquivos grandes e path traversal limitados |

| **P2** | **Política de comandos baseada em allowlist:** `src/shared/command-allowlist.ts`, `src/main/sandbox.ts` | SENTRA tem policy+grants centrais e paths escopados | Reaproveitar somente parser de invocações simples/fail-closed e casos de teste, subordinados à policy central. Não copiar a suposição de que cwd aprovado sandboxa um processo | Todo comando precisa de capability+effect gate; binário permitido pode executar filhos/IO e continua exigindo isolamento verdadeiro |

| **P2** | **Extensão/browser observability:** `extension/chatgpt-dom.js`, `content.js`, `fiber.js`, `background.js`; `src/main/browser-proof.ts` | SENTRA tem Edge/Web Models, extensão e Playwright, com contrato próprio | Extrair conceitos de estado da página, tab lifecycle, detecção de geração, rebind e health, com testes de compatibilidade; **não** substituir extensão inteira nem copiar seletores sem avaliação de termos, privacidade e atualização | Browser UI não é API pública; políticas do provedor, usuário e Chrome respeitadas; sem importação silenciosa de cookies |

| **P2** | **UX, acessibilidade, testes:** `src/renderer/settings-search.ts`, `workspace-docks.ts`, `panel-motion.ts`; `scripts/verify-*.cjs`; `test/*` | Canvas React/Lucide/Radix/React Flow atualizado, design corporativo minimalista | Adotar pesquisa nas configurações, acessibilidade de teclado, persistência de docks, reduced motion e cenários Playwright; não copiar o visual inteiro | Screenshot/dpi 100/125/150%, foco, teclado, performance e teste da janela WebView2 |

| **Não prioritário** | Pet overlay, apps Electron duplicados, gravação indiscriminada, cópia de cookie/sessão, permissões gerais da extensão | Regressão arquitetural/superfície desnecessária | **Não incorporar** por padrão | Consentimento granular, privacidade e manutenção |



## O que o SENTRA já resolve melhor / não duplicar



1. **Autoridade:** `sentra_mcp/services/control_plane.py`, `authorization.py`, `durable.py`, `sentra_runtime/central_authority.py` e `durable_admission.py` já fornecem admission/fencing/grants/Run/WorkItem/Operation; CoS organiza chats e ferramentas sobretudo dentro de um processo Electron. O núcleo central do SENTRA continua a fonte de verdade.

2. **Canvas como produto:** `sentra_canvas/service.py`, `task_runtime.py`, `desktop_ui/src/*`, WebView2; importar o renderer Electron concorrente contraria a meta de uma única interface.

3. **Execução/interop:** `sentra_interop/acp.py`, `mcp.py`, `a2a.py`, `activepieces.py`; `sentra_executors/playwright_browser.py`, `uia_semantic.py`, `daytona_sessions.py`, remotos Guacamole/RustDesk: o stack já contempla esses domínios. Adicionar wrappers duplicados só aumentaria pontos de falha.

4. **Auditoria/distribuição:** aprovação, outbox e peers `peer_work_wire.py`/`peer_admission.py`, trilhas e telemetria não devem ser bypassados por plugins locais.

5. **Modelos:** o novo `sentra_cli/repl.py` já suporta `/model` interativo e `/effort`. O novo valor de CoS é a **correlação comprovada com a conta/sessão Web**, não refazer o menu.



## Achados de segurança e compatibilidade no upstream



- `SECURITY.md` declara que **`exec_command` não fica confinado** à pasta aprovada: começa em cwd aprovado, mas age com privilégios normais do usuário. Não herdar esse modelo para agentes autônomos SENTRA.

- Extensão Manifest V3 pede `debugger`, `tabs`, `scripting` e hosts HTTP(S) amplos. Estabelecer permissions review e pareamento por sessão; não instalar a extensão externa automaticamente no perfil real.

- `SECURITY.md` documenta transferência **opt-in** de cookies de sessão para browser integrado. Alto risco se copiado; **excluir** desse plano.

- `Goal` usa uma segunda chamada ao modelo, por padrão via OpenRouter configurado (não gratuita universalmente); não introduzir cobrança extra involuntária. Os limites, restrições e recusas de provedores continuam válidos.

- O projeto declara explicitamente que automação da UI ChatGPT **não é API pública** nem promessa de conformidade; testar e manter fallback que não depende do DOM.

- `pluginExposure` bloqueia nomes de ferramentas conflitantes, até quando um dos providers está desabilitado (evita redirecionamento de chamada cacheada) e limita publicação a 256 tools/250.000 bytes de schema. O SENTRA deve preservar **essa propriedade**, possivelmente com limites mais restritos por workspace.

- MCPB `extractBundle` valida ZIP com teto 128 MiB, rejeita symlinks, traversal, colisão case-insensitive e nomes Windows proibidos. É candidato a porte de testes, **não** uma razão para executar bundles de procedência desconhecida.

- Browser snapshots / gravação de chat são dados sensíveis; não compartilhar integralmente com outro agente, peer Hamachi/Radmin ou provedor de Goal.



## Ordem de implementação integrada (fatias completas, não módulos isolados)



**Sprint A — Plugin-first onboarding (maior ganho prático):**

- Um único registro de providers MCP autorizado pelo host e vinculado a `ExecutorRegistry`/ToolCatalog.

- Importar `MCPB` com validação + manifesto, mostrar ferramentas expostas/conflitos, health, revogação; conectar pelo Quick Start. Provar um provider real stdio e um HTTP local através de WorkItem/Operation/Grant.

- Testes: ZIP malformado, mesma tool name em providers diferentes (inclusive disabled), tentativa de capability não concedida, restart, reconnect, uninstall e falha em OAuth.



**Sprint B — Catálogo de modelos + ChatGPT lifecycle:**

- Fonte de observação da conta Web verificável, com nonce/generation, modelo/effort e estado Automatic. Projetar no `/model` e Canvas sem criar modelos fictícios.

- Outbox de mensagens Web com recibo claro, no-repeat após resultado incerto e indicação na UI.

- Testes: conta sem seletor, modelo desaparecido, conta trocada, DOM alterado, restart durante send, respostas atrasadas e seleção explícita inválida.



**Sprint C — Continuação e produtividade:**

- Handoff A→B transacional no storage do SENTRA, mesmo WorkItem/Run/contexto/worker; sem clonar grants ou executar novamente ações incertas.

- Skills versionadas e editor de arquivos/diff opcional em docks compactos.

- Testes: duas reivindicações concorrentes, crash em preflight/commit/publish, cancelamento, integridade de contexto e permissões do arquivo.



## Validação e aceitação



Esta análise é **estática de fontes e contratos** (1.203 arquivos verificados + leitura de módulos e testes). **Não** são evidências de que CoS rodou ou que alguma função acima já foi copiada/conectada ao SENTRA. Ao iniciar cada fatia, testar código portado primeiro em ambiente hermético; depois E2E com provider autorizado e o **Control Plane real** em SQLite temporário; só então incluir na suíte CI e no instalador Windows. Não usar conta/chat do usuário ou extensão instalada como fixture.



## Referências principais



- `third_party/chat-on-steroids/README.md`, `SECURITY.md`, `docs/setup.md`, `docs/plugins.md`, `docs/tool-surface.md`

- `third_party/chat-on-steroids/src/main/chat-models.ts`, `session/continuation.ts`, `session/input.ts`, `agents.ts`, `goal.ts`, `plugins/*`, `codex/unified-exec.ts`

- `third_party/chat-on-steroids/test/model-picker-state.test.ts`, `test/continuation.test.ts`, `test/input-delivery-integration.test.ts`, `test/agents.test.ts`, `test/goal.test.ts`

- SENTRA: `sentra_canvas/service.py`, `task_runtime.py`, `sentra_cli/repl.py`, `sentra_runtime/central_authority.py`, `sentra_interop/tool_catalog.py`, `sentra_remote/onboarding.py`, `sentra_mcp/tool_policy.py`



**Conclusão:** manter CoS **como fonte de referência pinada em third_party** e priorizar a integração central de plugins MCP, descoberta de modelos reais e continuidade transacional entre chats. Não declarar 38/38 projetos incorporados: **clone e auditoria ≠ funcionalidade integrada, testada ou homologada**.



---

# Segunda auditoria profunda — adendo e correcoes da matriz inicial

**Base examinada:** mesmo checkout Git imutavel do Chat On Steroids, commit 151e7ef96bc16bf594ffbd35efe620e4ef6e4c2c, com 1.203 arquivos rastreados e sem modificacoes. A arvore Git completa possui 1.274 entradas (inclusive diretorios). Inventario de src/main, src/main/session, src/main/mcp, src/main/computer, src/main/plugins, src/main/codex, src/renderer, src/shared, extension, docs e test. Foram observados **326 arquivos sob test/**; sua presenca nao e evidencia de testes executados. Comparacao com modulos autoritativos SENTRA por leitura direta. Esta etapa NAO executou dependencias, extensao ou app externo.

**Retificacao:** as 13 frentes da primeira matriz nao esgotavam o repositorio. Detectei **21 subfrentes adicionais ou antes agregadas indevidamente**, algumas prioritarias para seguranca e primeiro uso. A palavra **nao comprovado** significa que falta uma demonstracao de equivalencia no SENTRA, nao que nao exista codigo semelhante em outra parte.

## Descobertas adicionais — identidade, seguranca e instalacao

| ID / prioridade | Mecanismo do Chat On Steroids (fonte) | Confronto com SENTRA | Entrega integrada e gate |
| --- | --- | --- | --- |
| A01 / **P0** | **Join exato de origem MCP**: src/main/session/correlation.ts e recorder.ts unem o x-request-id do MCP ao message.metadata.request_id do browser e ao conversationId. Identidade comprovada nao expira por TTL nem troca de dono sob observacao conflitante | sentra_mcp/identity.py autentica principal e sessao de transporte; sentra_mcp/services/context_projection.py armazena conversation_id. Isto nao prova sozinho um join completo request-ID-da-pagina para a chamada MCP | Projetar RequestCorrelation no Control Plane como **prova de origem, nunca grant**. Testar duas abas concorrentes, refresh, troca de conta, colisao e chamada tardia sem atribuicao por horario/chat ativo |
| A02 / **P0** | **Bloqueio imediato por chat especifico**: src/main/session/blocked-chats.ts impede novas ferramentas numa conversa travada; test/blocked-chats.test.ts | Control Plane ja revoga grants e operacoes; busca no pacote sentra_canvas nao encontrou politica equivalente com chaves de conversa Web | Botao Bloquear ferramentas deste chat, filtro antes do dispatcher, sem derrubar outros agentes e sem executar chamadas tardias |
| A03 / **P0** | **Confiança/default deny por conversa**: src/main/session/trusted-chats.ts e conversation-access.ts fazem autorizacao adicional por conversation ID e sucessor comprovado | Grants SENTRA por principal, workspace, agente e WorkItem nao substituem o criterio de qual chat web e confiavel | Permissao adicional opcional ChatTrust: trust nao cria grant, block prevalece, unknown owner nega no modo estrito, handoff so herda apos commit comprovado |
| A04 / **P0** | **Espera pela aprovacao humana no proprio ChatGPT**: src/main/approval-wait.ts e renderer/tool-approval.ts; espera nao e resolvida por auto-reload | SENTRA ja tem seu proprio fluxo de aprovacao, mas nao ha prova de tratamento do cartao de aprovacao que a pagina ChatGPT apresenta | Estado WAITING_CHATGPT_USER_APPROVAL no Canvas/CLI; nao repetir envio nem reiniciar chat durante cartao pendente |
| A05 / **P0** | **Comprovacao duravel de app/plugin na conta e uso real por tunel**: src/main/connector-proof.ts; preserva a ultima prova e invalida se o tunel ou perfil mudar | sentra_remote/onboarding.py tem ready_to_install e requires_account_authorization; readiness local nao comprova instalacao na conta ChatGPT | Separar LOCAL_MCP_READY, TUNNEL_ONLINE, CHATGPT_APP_OBSERVED, TOOLS_AUTHORIZED e VERSION_CURRENT; sem gravar credenciais na prova |
| A06 / **P0** | **Refresh de schemas MCP no ChatGPT apos update**, grace period, debounce, respostas tardias e falha limitada: src/main/plugin-refresh.ts, test/plugin-refresh-workflow.test.ts | SENTRA recompila e verifica o MCP local, mas nao ha prova E2E de re-publicacao de tool schema **cacheado no lado da conta** | Confrontar tools/list e version/fingerprint com o publicado, avisar usuario quando refresh manual for necessario e testar schema antigo |
| A07 / **P0-P1** | **Superficies MCP separadas por dominio**, Core/Desktop/Plugins: src/main/mcp/surfaces.ts e kernel.ts | SENTRA tem ToolPolicyProxy, ToolCatalog e diversos provedores; expor 37+ integracoes no mesmo namespace aumenta disclosure e revisao de permissao | Uma unica autoridade com projecoes MCP distintas e tool sets minimos. Nao criar tres control planes nem exigir tres tunéis sem justificar o custo |
| A08 / **P1** | **Code Mode com JavaScript dentro de QuickJS WASM** e limites CPU/memoria/tempo/chamadas/tamanho: src/main/mcp/code-mode-runtime.ts e code-mode-worker.ts | sentra_interop/tool_catalog.py ja oferece descoberta seletiva; nao ha prova de composicao sandboxed dessas chamadas em um unico orquestrador | Adaptar como **compositor** sem IO host proprio; cada ferramenta interna ainda precisa de OperationRequest/grant/fencing do SENTRA. Nunca tratar QuickJS como isolamento de efeito fisico |
| A09 / **P1** | **Prova de extensao instalada, pareada e login anterior**, mesmo entre reinicios: src/main/browser-proof.ts | sentra_remote/openai_browser_enrollment.py cobre captura guiada, mas o wizard precisa distinguir instalada, pareada, autenticada, revogada e perfil/browser-ID | Evidencia somente de status sem copia de cookies. Tela de reparo por etapa e teste de logout/troca do Edge |
| A10 / **P1** | **API local de leitura e acao com duas chaves de consentimento**, action opt-in, limite de corpo, Origin/Host guard e paginação: src/main/control-api.ts e control-actions.ts | Broker/HTTP do Canvas e Control Plane ja existem; nao introduzir listener privilegiado concorrente | Apenas projecao autorizada do servidor central, default read-only; POST com politica propria e budget. Este e um refinamento da P1 da matriz anterior, nao uma nova autoridade |

## Descobertas adicionais — historia, arquivos e operacao

| ID / prioridade | Mecanismo do Chat On Steroids (fonte) | Confronto com SENTRA | Entrega integrada e gate |
| --- | --- | --- | --- |
| A11 / **P1** | **Busca textual entre conversas em indice incremental**: src/main/session/search.ts e renderer/chat-search.ts criam search.txt pequeno por sessao sem reler journals enormes | sentra_mcp/services/search_sessions.py faz pesquisa persistente de **arquivos dos workspaces**, diferente de busca em texto de chat. sentra_core/conversations.py ja persiste conversas com protecao OS | Indice local opt-in por principal/workspace, acesso limitado, snippets e saltos para mensagem. Deletar indice com sessao, nao indexar secrets por padrao |
| A12 / **P1** | **Anexos de mensagem por armazenamento independente e chunks**: src/main/session/input-attachments.ts, input-images.ts, input-history.ts, com limites por formato, tamanho e quota | SENTRA tem artefatos, documentos e journals; precisa prova de envio de imagens/arquivos **no composer Web** com recibo e identidade de conversa | Proteger refs de artefato por WorkItem/grant e prova de envio, sem inflar outbox e sem mandar automaticamente arquivos a peers |
| A13 / **P1** | **Historico de streaming por message ID, nao cada frame**: src/main/session/store.ts e recorder.ts, com asset quotas e overflow referenciado | sentra_core/conversations.py tem SQLite e journal idempotente, mas a equivalencia para mensagem Web parcial/virtualizada nao foi demonstrada | Portar contrato de identidade e revisao da mensagem para persistencia SENTRA, nao copiar storage JSONL concorrente |
| A14 / **P1** | **Limites e consumo observados na conta ChatGPT Web**: src/main/session/usage.ts distingue percentuais restantes, janela de reset e observacao recente | sentra_core/provider_usage.py registra tokens reportados e budgets; isso nao prova cota ou disponibilidade mostrada na conta Web | Exibir lado a lado SENTRA-accounted usage e ChatGPT-observed limits, com frescor/conta/estimativa identificados; nao usar um como verdade do outro |
| A15 / **P1-seguranca** | **Relatorio de diagnostico anonimizado antes de compartilhar**: src/main/diagnostics-report.ts e report-scrub.ts removem nomes de usuario, pastas, chat titles e segredos | sentra_remote/diagnostics.py::collect inclui hostname, device_id, relay_url, allowed_roots e caminho do audit log no JSON atual. Sao metadados identificadores, mesmo sem tokens explicitos | Separar diagnostico interno de export redigido com preview, tags estaveis e testes de nao vazamento de IP, URL, path, e-mail, titulo, chave e nomes de projeto |
| A16 / **P1** | **Resumo humano de chamadas de ferramenta com evidencias**: src/main/mcp/call-context.ts e session/summarize.ts produzem detalhes por tipo (exit code, linhas alteradas, hits) e ownership isolado por async call | SENTRA tem Operation/Artifact e timeline, mas a renderizacao uniforme desse recibo por provedor nao foi provada | Derivar linha curta do evento real, nunca inferir de texto do modelo. Ligar ao painel do Canvas e CLI sem expor secrets |


| ID / prioridade | Mecanismo do Chat On Steroids (fonte) | Confronto com SENTRA | Entrega integrada e gate |

| --- | --- | --- | --- |

| A17 / **P1** | **GC controlado de workers, processos e terminais**: src/main/runtime-gc.ts e codex/ownership.ts distinguem a retencao de recursos do deadline da tarefa | SENTRA ja tem leases, ConPTY e reconciliacao, mas o ciclo de vida de terminal, Run, worker e processo nao e necessariamente o mesmo | Limpeza so por ownership e prova de idle; nunca encerrar ConPTY do usuario ou processo de outro WorkItem. Testar crash/restart/UNCERTAIN |
| A18 / **P1** | **Git/diff integrado, revisionamento de vista e watchers de arquivos limitados**: src/main/project-git.ts, project-file-watcher.ts; debounce e check contra mudanca externa | SENTRA tem RepositoryService, PatchManager e workspace sandbox; o Canvas nao tem aceite de paridade de revisao visual de diff/watch | Painel minimalista opcional, revisao por documento, detecao de alteracao externa e arquivo renomeado, sem permitir write por watcher |
| A19 / **P1** | **Updater sem bloquear startup, pacote encenado e aplicado quando usuario encerra app**: src/main/update.ts, test/update.test.ts | sentra_remote/updater.py JA valida manifest SHA256 e Authenticode. A lacuna e UX/restart/compatibilidade com extensao e plugin, nao download seguro basico | Upgrade coordenado do aplicativo, extensao, Web Models e schema MCP, sem interromper ConPTY. Em falha, permanecer na versao funcional e permitir rollback |
| A20 / **P2** | **Export Markdown por resposta ou sessao completa**, incluindo trechos longos em overflow: src/main/session/markdown-export.ts, shared/markdown-export.ts | SENTRA tem documentos e historico protegido, mas nao foi verificado um atalho simples de export da conversa com proveniencia | Exportar apenas conversa selecionada, com redacao opcional, sem expor evidencias secretas. UI compacta sem novo backend de documentos |
| A21 / **P2** | **Skill packs vindos do GitHub fixados em SHA, atualizacao e skills recomendadas**: src/main/skill-github.ts, recommended-skills.ts, test/skill-github.test.ts | Complementa a frente Skills da primeira matriz, em vez de criar outro framework de agentes | Import com teto de tamanho/arquivos, hash e aprovacao de usuario, acao de atualizar/revogar; skill nao cria grants |

## Diferencas de arquitetura que nao devem ser confundidas

| Ja existe no SENTRA | Valor especifico adicional do Chat On Steroids | Situacao |
| --- | --- | --- |
| Identidade OAuth/sessao via sentra_mcp/identity.py | Correlacao provada por x-request-id do MCP e metadata da mesma conversa observada no ChatGPT | **Nao demonstrado no fluxo central** |
| Grants, WorkItems e DurableRunService | Bloqueio/trust de uma conversa ChatGPT especifica + cartao de aprovacao pendente | **Filtro adicional proposto**, jamais substitui os grants |
| sentra_mcp/services/search_sessions.py | Busca de palavras das mensagens ja trocadas em conversas | **Objetos de busca diferentes** |
| sentra_core/provider_usage.py | Limites de uso/refresh reportados pela conta Web | **Metodos de medicao diferentes** |
| sentra_core/conversations.py com DPAPI/keyring | Reconciliacao de frames do browser por ID logico e assets do chat | **Testes de paridade Web necessarios** |
| sentra_remote/onboarding.py com ready_to_install | Evidencia de que plugin foi observado, autorizado e atualizado na conta | **Preparacao nao equivale a instalacao** |
| sentra_remote/diagnostics.py | Export publico redigido e revisavel | **Melhoria de privacidade concreta** |
| sentra_remote/updater.py com Authenticode | Coordenacao de atualizacao da extensao e cache da tool list no ChatGPT | **Melhoria de experiencia e recovery** |
| sentra_executors/playwright_browser.py, UIA e Edge | Browser tab identity, recebimentos no-repeat e detectores de pausa/aprovacao de tela | **Portar contratos e testes, nao extensao inteira** |

## Riscos e filtros de incorporacao

1. **Atribuicao nao equivale a autenticacao:** associar uma chamada MCP a uma conversa Web nao deve criar grant, session token, Run, WorkItem, acesso a pasta ou permissionamento de maquina. A origem e evidencia adicional, nunca autoridade.
2. **ChatTrust nao amplia privilegios:** a decisao por conversa e negativa ou filtro; o Control Plane autoritativo continua mandatorio. Ao bloquear chat, chamadas em voo e resultados tardios continuam sob reconciliacao e fencing.
3. **Nao confundir tres instalacoes:** runtime MCP + cliente Tunnel, plugin criado na conta ChatGPT e extensao Chromium sao objetos independentes. Mesmo instalador Windows funcional nao comprova os dois ultimos.
4. **Code Mode possui DUAS camadas de isolamento:** QuickJS pode limitar a linguagem JS, mas as ferramentas chamadas exigem grant + intent durable + limites de rede, arquivos e efeitos. Nao executar JS arbitrario no processo privilegiado.
5. **Historico, anexos e diagnosicos precisam de privacidade:** armazenamento, indexacao, exportacao e compartilhamento com peer requerem ACL, retencao, opcoes de exclusao e reducao de dados. Nao copiar transferencia de cookies de sessao, gravacao generalizada nem permissao ampla de extensao por padrao.
6. **Nao tratar automacao do DOM como API publica:** verificacoes de modelo, status do browser e cartoes de aprovacao podem quebrar com mudanca da pagina. Prever falha segura e reparo manual.
7. **Upstream nao equivale a funcionalidade validada:** a presenca de 326 arquivos de teste no clone nao prova que esses testes passaram na maquina SENTRA. Sem npm install, sem execucao da extensao, sem integracao remota e sem E2E com conta real nesta auditoria.
8. **Licenca e proveniencia sao requisitos de distribuicao:** ainda que o uso pretendido seja privado, qualquer copia concreta de codigo deve preservar creditos e avisos do arquivo/livraria incorporada.

## Nova sequencia de trabalho sem duplicar o nucleo

**Fatia 1 — Primeiro uso:** ConnectorProof + BrowserProof + PluginRefresh, vinculados ao assistente que o SENTRA ja possui. Gates: mostrar cada etapa real, reabrir apos reboot, detectar plugin ausente, schema desatualizado e tunel trocado, sem copiar segredos. Conectar as provas no Control Plane antes de marcar operacional.

**Fatia 2 — Seguranca de conversas:** Correlation + ChatTrust/BlockedChat + ApprovalWait. Gates: 2 chats simultaneos, x-request-id duplicado/conflitante, aba recarregada, falta de comprovante, revogacao no meio da chamada, cartao de aprovacao sem clique automatico. A permissao original do SENTRA prevalece.

**Fatia 3 — Conversas duraveis:** usar storage SENTRA ja protegido para streaming Web por message_id, anexos e search index com ACL; integrar outbox/not_sent/unconfirmed e Compact & Resume transacional da matriz anterior. Gates: perda de POST/reply, crash apos enfileiramento, duas reclamacoes do handoff, migracao de chats sem reaplicar efeitos.

**Fatia 4 — Operacao e produtividade:** UI com resumo de recibos, limites Web observados, diagnósticos redigidos, revisao Git/diff, GC de workers e staged update; adicionar Skills Git e Markdown export conforme beneficio e manutencao. Canvas permanece minimalista, com detalhes progressivos, sem duplicar aplicativo Electron.

**Fatia 5 — Performance de grandes catalogos:** depois que plugins MCP reais funcionarem, avaliar surface splitting e Code Mode restrito com budgets. Nao introduzir mais conectores/tuneis so para reproduzir a arquitetura upstream.

### Matriz de prova para cada incorporacao

| Prova | Exigencia |
| --- | --- |
| Codigo estatico | Contrato de esquema, versao, bounds, fingerprint e fontes fixadas |
| Integracao | Run/WorkItem/Operation e grants reais via Control Plane/SQLite em tmp_path; sem segunda autoridade |
| Concorrencia | Duplicacao, observacao tardia, duas abas/agents, cancelamento, crash e replay |
| Privacidade | Dados de conta/chat/anexos nunca vazam em log/export, grants e ACL respeitados |
| UX | Canvas WebView2 + CLI com recovery amigavel, status explicito e acoes guiadas |
| Primeiro uso | Setup, extensao e plugin ChatGPT testados COMO etapas distintas |
| Aceite | Teste unitario + integracao + E2E real em ambiente autorizado; nao afirmar homologacao por mera compilacao |

## Veredito atualizado da segunda auditoria

A primeira matriz **deixou passar lacunas reais** na camada de proveniencia de conversa, operacao do plugin na conta, stop/trust de chat, autorizacao humana, indices de historico, anexos Web, uso observado, diagnosticos anonimizado e limpeza de recursos. Mais ferramentas ou mais executores nao sao a principal necessidade do SENTRA. A melhor absorcao preserva o SENTRA como unica autoridade e faz os mecanismos do Chat On Steroids melhorarem **a confiabilidade e usabilidade do fluxo real**.

Esta segunda auditoria amplia a lista de trabalho, mas **nao declara** qualquer dessas 21 frentes implementada ou testada no SENTRA. A auditoria foi estatica e seu limite de cobertura continua sendo revisao de codigo e contratos selecionados, nao execucao exaustiva de cada arquivo e servico.


### Fonte REUSE ? docs/SENTRA_THIRD_PARTY_REUSE_2026-10-08.md

# SENTRA: análise comparativa de fontes terceirizadas



Data: 8 outubro 2026 (Sao Paulo). Auditados por inspeção estática os diretórios de third_party; projetos externos NÃO foram executados, compilados, nem integrados.



## 1. Integridade e limites



- Fontes independentes e rasas (shallow clones), registradas com SHA completo em third_party/SENTRA_SOURCES_MANIFEST.json.

- O Git principal já ignora third_party, portanto versões e licenças precisam ser registradas em manifest e processadas pelo release apenas se explicitamente aprovadas.

- Licença abaixo refere-se somente a indicação do LICENSE de raiz. Não valida módulos, fontes, assets nem dependências transitivas.

- Revisões clonadas não demonstram segurança, compatibilidade nem funcionamento. Nenhum clone recebeu instalação de dependências, tokens ou execução.



## 2. Inventário por repositório



| Projeto | Clone | Commit | Licença aparente da raiz | Evidência de código |

| --- | --- | --- | --- | --- |

| daytona | ok | fc98a5032c04 | AGPL (root) | apps/runner, apps/daemon, apps/snapshot-manager |

| openhands | ok | 76398bb5c5b9 | MIT (root) | docs/architecture.md, src/api, src/stores |

| agent-client-protocol | ok | 8c4b8faff610 | Apache-2.0 (root) | schema/v2, docs/protocol, agent-client-protocol-schema |

| a2a | ok | 12e9d2fbb9ba | Apache-2.0 (root) | specification/a2a.proto, docs/specification.md, specification/json |

| mcp-typescript-sdk | ok | b022522089a0 | Apache-2.0 (root) | packages, README.md |

| langgraph | ok | bfcfea554ed5 | MIT (root) | libs/langgraph, libs/checkpoint, README.md |

| temporal | ok | bae8771853cf | MIT (root) | service, common, client |

| xyflow | ok | 3d35b5731757 | MIT (root) | packages/react, packages/system, examples |

| yjs | ok | d01eefc997cf | MIT (root) | src, tests, README.md |

| playwright-mcp | ok | b8b4183e099f | Apache-2.0 (root) | src, tests, README.md |

| guacamole-client | ok | 38e8cb8ff5cd | Apache-2.0 (root) | guacamole, extensions |

| guacamole-server | ok | ae12b8e51aa6 | Apache-2.0 (root) | src, src/protocols, README |

| openfga | ok | 526995eb2024 | Apache-2.0 (root) | pkg, cmd, README.md |

| opa | ok | 4dcda5da919a | Apache-2.0 (root) | rego, topdown, server |

| gvisor | ok | 25e4d4778b06 | Apache-2.0 (root) | runsc, pkg/sentry, README.md |

| opentelemetry-collector | ok | cee245c32ca5 | Apache-2.0 (root) | receiver, processor, exporter |

| langfuse | ok | c106bb3d9453 | MIT (root) | web, packages, worker |

| activepieces | ok | a9b86f6ed9e5 | MIT (root) | packages/pieces, packages/server, packages |

| rustdesk | ok | 1d4abd0258bb | needs review | src, libs, flutter |

| immudb | ok | bfdce03649f5 | BSL (root) | pkg, embedded, cmd |



## 3. Reaproveitamento técnico - projeto por projeto



### daytona - Compute plane / sandboxes

Optional external sandbox provider. Analyze snapshots, computer use, daemon and lifecycle first; AGPL obligations.

Locais de código verificados: third_party/daytona/apps/runner, third_party/daytona/apps/daemon, third_party/daytona/apps/snapshot-manager, third_party/daytona/libs/computer-use, third_party/daytona/libs/sdk-python, third_party/daytona/apps/otel-collector, third_party/daytona/apps/daytona-e2e



### openhands - Agent Canvas + backend selection

Reuse backend registry, conversation and observability UI patterns without replacing the SENTRA Canvas.

Locais de código verificados: third_party/openhands/docs/architecture.md, third_party/openhands/src/api, third_party/openhands/src/stores, third_party/openhands/src/hooks, third_party/openhands/docs/ACP_AGENTS.md



### agent-client-protocol - Agent-editor sessions

Implement ACP adapter for session creation, progression, permission, cancel and resume.

Locais de código verificados: third_party/agent-client-protocol/schema/v2, third_party/agent-client-protocol/docs/protocol, third_party/agent-client-protocol/agent-client-protocol-schema



### a2a - Inter-agent interoperability

Expose and consume bounded tasks across agent servers while retaining SENTRA authority.

Locais de código verificados: third_party/a2a/specification/a2a.proto, third_party/a2a/docs/specification.md, third_party/a2a/specification/json



### mcp-typescript-sdk - Tooling and resources

Generate typed clients for SENTRA MCP capabilities; assess interoperability.

Locais de código verificados: third_party/mcp-typescript-sdk/packages, third_party/mcp-typescript-sdk/README.md



### langgraph - Agent state graphs

Compare checkpoint and human-in-loop patterns; avoid swapping SENTRA durable core.

Locais de código verificados: third_party/langgraph/libs/langgraph, third_party/langgraph/libs/checkpoint, third_party/langgraph/README.md



### temporal - Durable workflow engine

Borrow cancellation/recovery and worker lifecycle patterns; avoid a second task authority.

Locais de código verificados: third_party/temporal/service, third_party/temporal/common, third_party/temporal/client, third_party/temporal/README.md



### xyflow - Node editor

Compare accessibility, edge performance, graph APIs; migration only if objectively better.

Locais de código verificados: third_party/xyflow/packages/react, third_party/xyflow/packages/system, third_party/xyflow/examples, third_party/xyflow/packages



### yjs - Collaborative CRDT

Sync layout and annotations only; execution and policy state remains server authoritative.

Locais de código verificados: third_party/yjs/src, third_party/yjs/tests, third_party/yjs/README.md



### playwright-mcp - Browser automation

Optional audited browser toolset with separate browser session and permissions.

Locais de código verificados: third_party/playwright-mcp/src, third_party/playwright-mcp/tests, third_party/playwright-mcp/README.md



### guacamole-client - Browser remote desktop

Study browser RDP/VNC/SSH session UX.

Locais de código verificados: third_party/guacamole-client/guacamole, third_party/guacamole-client/extensions



### guacamole-server - Remote desktop gateway

Consider guacd as separately deployed desktop proxy, not as agent authority.

Locais de código verificados: third_party/guacamole-server/src, third_party/guacamole-server/src/protocols, third_party/guacamole-server/README



### openfga - Relationship permissions

Assess optional ReBAC implementation behind SENTRA authorization interface.

Locais de código verificados: third_party/openfga/pkg, third_party/openfga/cmd, third_party/openfga/README.md



### opa - Policy engine

Assess external decision engine for conditional policy without split-brain.

Locais de código verificados: third_party/opa/rego, third_party/opa/topdown, third_party/opa/server, third_party/opa/README.md



### gvisor - Linux sandbox isolation

Compare Linux isolation for remote executor, not for Windows host ConPTY.

Locais de código verificados: third_party/gvisor/runsc, third_party/gvisor/pkg/sentry, third_party/gvisor/README.md



### opentelemetry-collector - Distributed telemetry

Export correlated traces/metrics with redaction and bounded retention.

Locais de código verificados: third_party/opentelemetry-collector/receiver, third_party/opentelemetry-collector/processor, third_party/opentelemetry-collector/exporter, third_party/opentelemetry-collector/service



### langfuse - LLM observability

Optional LLM spans, cost and experiments; control retention and prompt privacy.

Locais de código verificados: third_party/langfuse/web, third_party/langfuse/packages, third_party/langfuse/worker, third_party/langfuse/README.md



### activepieces - Enterprise integrations

Enterprise connector catalog, webhooks and triggers via out-of-process plugin.

Locais de código verificados: third_party/activepieces/packages/pieces, third_party/activepieces/packages/server, third_party/activepieces/packages



### rustdesk - Remote desktop alternative

Separate remote screen transport option; AGPL and packaging require legal review.

Locais de código verificados: third_party/rustdesk/src, third_party/rustdesk/libs, third_party/rustdesk/flutter, third_party/rustdesk/README.md



### immudb - Verifiable event storage

Compare immutable-verifiable log strategy; commercial use requires BSL review.

Locais de código verificados: third_party/immudb/pkg, third_party/immudb/embedded, third_party/immudb/cmd, third_party/immudb/README.md



## 4. Capacidades já presentes no SENTRA (evitar reconstrução)



- Canvas próprio: sentra_canvas/static/native.js, native.css, rope-physics.js e fractal-grid.js; nós, links, PTY e estado persistente em sentra_canvas/graph.py.

- SENTRA CLI -> Canvas: sentra_cli/canvas.py e sentra_canvas/service.py; handoffs endereçados e recibos; ainda não equivale a um cliente ACP completo.

- Durable Run/WorkItem: sentra_mcp/services/durable.py, governance.py, control_store.py, sentra_canvas/task_runtime.py; já há identidade, leases, budgets e workflow.

- Integração MCP e plugins: sentra_mcp/server.py, sentra_mcp/services/plugin_host.py; não criar gateway concorrente de autorização.

- Acesso remoto: sentra_remote/gateway.py e agent.py; complementar com MachineSession e desktop remoto, sem duplicar o pairing.

- Auditoria: sentra_mcp/audit.py, sentra_core/telemetry.py; correlação e redaction existentes, porém não comprovam integridade contra adulteração.

- Sandbox: sentra_mcp/services/process_sandbox.py usa Docker para escopos próprios. Já sentra_canvas/terminal.py + owned_process.py executa PTY como usuário Windows: Job Objects não reduzem privilégios do processo.



## 5. Lacunas, prioridade e aceitação



| Ordem | Lacuna | Mudança proposta | Teste necessário |

| --- | --- | --- | --- |

| P0 | Isolamento real de Canvas CLI | Criar ExecutorAdapter com sandbox, denies e credenciais efêmeras por operação | tentativa de fuga de pasta/host/rede, filhos e privilégio |

| P0 | Protocolo interoperável | ACP com sessão/permits/progressos/cancel, A2A na fronteira externa | dois agentes distintos em comunicações reais, reinício e deduplicação |

| P0 | Auditoria verificável | Encadear hashes, checkpoints assinados, verificador externo e retenção política | alterar/remover evento e comprovar detecção sem vazamento de segredos |

| P1 | Sandbox externa Daytona | Criar DaytonaAdapter sem colar código AGPL no core | provisionar -> executar -> snapshot -> recuperar -> destruir, cleanup garantido |

| P1 | Máquina e aplicações como recursos | Machine, Capability, Session, Executor e inventário unificado | selecionar máquina permitida, negar ações fora de escopo, revogar a quente |

| P1 | Multi-tenant hospedado | Storage adapter Postgres com transações/locks nativos + identidade federada | concorrência/isolamento de 2 locatários, quedas e lock/fencing |

| P1 | Canvas colaborativo | SSE/WebSocket para execução; Yjs só para layout/notas | editar em dois clientes, offline/reconexão, concorrência e permissão |

| P2 | Integração empresarial | Adaptador Activepieces com catálogo e webhooks assinados | consentimento por ação, idempotência e ataques via webhook |

| P2 | Telemetria ponta a ponta | OpenTelemetry e endpoint de observabilidade opcional | rastros por Run/Operation/Device com redaction e hard-stop |

| P2 | Guias de sandbox desktop | Guacamole/RustDesk para acesso consentido e observável | sessão RDP/VNC/SSH autorizada, cancelamento e auditoria |



## 6. Daytona: análise de arquitetura e licença



- Revisão fixada: daytonaio/daytona v0.188.0, commit fc98a5032c04e13de737b8d4d45dd2c7e5d1291a. O repositório upstream parou de receber manutenção em junho de 2026.

- Control Plane: apps/api (NestJS); Compute Plane: apps/runner; agent interno: apps/daemon. Separação de autoridade semelhante à que SENTRA precisa para execução em máquinas externas.

- Persistência/recuperação: apps/snapshot-manager + libs/sdk-python e libs/sdk-typescript. Explorar como contrato de snapshot de sandbox; não confundir com reattachment de terminais Windows que caíram.

- Computer Use: libs/computer-use/README.md descreve Xvfb, XFCE, acessibilidade AT-SPI, x11vnc/noVNC e processo supervisionado para Linux.

- Rede e inspeção: apps/proxy, apps/ssh-gateway, apps/otel-collector e apps/daytona-e2e. Boas referências para gateway, isolamento e E2E.

- Integração recomendada: adapter SENTRA -> Daytona API isolada, com SENTRA governando principal/policy/Run/Operation/budgets/logs. Começar com SDK como cliente; evitar importar o daemon e UI ao núcleo.

- Risco jurídico importante: LICENSE raiz é GNU AGPL-3.0. Estudar alcance do copyleft na modificação e disponibilização pela rede; componentes independentes podem ter outra licença.

- Risco operacional: demanda imagens, compute nodes, rede, manutenção de forks, correções de CVEs e políticas de egress. Não tratar como biblioteca plug-and-play.



## 7. Contrato único proposto



Principal + Capability + Scope + Conditions -> PolicyDecision -> WorkItem/Operation -> ExecutorAdapter -> Evidence + Audit.



- AgentSession separa agentes lógicos da sessão de um modelo ou terminal; fornece ACP, MCP e A2A como transportes/adaptadores.

- Machine/ExecutionWorkspace descrevem um ambiente local, remoto, Docker ou Daytona, mas nenhum adaptador controla ACL nem autorização por conta própria.

- O Control Plane SENTRA decide alocação, permissões, custos, approvals e efeitos colaterais. Não permitir que a UI ou callbacks de IA se tornem autoridade.

- Estado compartilhado de Canvas via CRDT é somente apresentação. Nunca usar CRDT para leads/locks, cobrança ou permissões.

- Em multiusuário, substituir compartilhamento de SQLite por backend transacional com migrações, locking e reconciliação aprovados.



## 8. Roadmap de integração (não implementado nesta etapa)



1. Publicar contratos de Machine/Executor/Capability; endurecer autorização e threat model.

2. Criar adapter ACP e A2A, E2E com duas identidades reais e prova de negativa de autorização.

3. Provar DaytonaAdapter em ambiente isolado, sem alterar SENTRA core: create/exec/snapshot/restore/delete e tolerância a falhas.

4. Incluir auditoria verificável e OTEL transversal, mantendo dados sensíveis redigidos.

5. Construir plataforma multiusuário Web (Postgres, streaming, CRDT para layout, MFA/SSO).

6. Adicionar catálogo de plugins e conectores enterprise com consentimento por tarefa.

7. Auditoria de licenças, supply chain, CVEs, releases e testes adversariais antes da primeira implantação comercial.



## 9. Critérios de evidência



- Este relatório é de inspeção estática. Nenhum build de projeto externo nem prova de sandbox remota executada.

- Atualizar fontes só com revisão explícita, novo manifesto SHA, aprovação de licença, SBOM, testes e controle de regressão.

- Não automatizar a promoção de nenhum projeto externo a dependência do instalador do SENTRA.



Artefatos: third_party/SENTRA_SOURCES_MANIFEST.json, third_party/SENTRA_STATIC_ANALYSIS.json e este relatório.


## 10. Inspeção de código adicional: componentes reutilizáveis concretos

A análise abaixo verifica arquivos e contratos específicos (não apenas README). Propostas são novas integrações, não capacidades declaradas como já concluídas no SENTRA.

### 10.1 Daytona como provedor de execução (prioridade mais alta)

**Código verificado:** third_party/daytona/libs/sdk-python/src/daytona/_sync/sandbox.py; third_party/daytona/libs/computer-use/pkg/computeruse/accessibility.go; mouse_validation.go; third_party/daytona/apps/runner; apps/snapshot-manager; apps/daytona-e2e.

O objeto Sandbox do SDK Python já agrega FileSystem, Git, Process, ComputerUse, CodeInterpreter, rótulos, volumes, snapshots e metadados do usuário/organização. Uma integração através de uma API adaptadora evitaria recriar sete famílias de operações remotas diferentes. A interface padronizada SENTRA deve projetar cada chamada como Operation idempotente com Run, WorkItem, approval, terminal status e Audit próprios.

**Computer Use:** o código accessibility.go utiliza D-Bus/AT-SPI para navegar elementos reais da interface com escopo focused/PID/all, atributos, ações, bounds e estados. É melhor como fonte estrutural de observação de aplicação Linux do que depender exclusivamente de screenshots e cliques por coordenada. Outros módulos oferecem mouse, keyboard, screenshot, processos e validação de argumentos. Não confundir isso com acessibilidade Windows (UI Automation), que precisaria de outro executor.

**Snapshots e recuperação:** reutilizar snapshot de ambiente apenas onde o provedor garante persistência e atomicidade; snapshots não ressuscitam processos locais Windows, nem substituem o registro de operações UNCERTAIN do SENTRA. Testar consistência de FS, idempotência, privilégios, redaction de segredos, rede restrita e descarte.

**Licenciamento fino:** a raiz Daytona é AGPL-3.0, assim como accessibility.go e mouse_validation.go (marcados SPDX AGPL-3.0). Contudo o arquivo libs/sdk-python/src/daytona/_sync/sandbox.py declara SPDX Apache-2.0. Verificar o pacote inteiro, transitivos e termos do servidor antes de copiar ou redistribuir código. Um cliente independente de API pode ser uma melhor fronteira do que incorporar o runtime AGPL.

### 10.2 OpenHands frontend + Agent Server (alto reaproveitamento de padrões)

**Código verificado:** third_party/openhands/docs/architecture.md; docs/ACP_AGENTS.md; third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/README.md.

No OpenHands a interface Canvas NÃO executa ações do agente. Ela trabalha por API com Agent Server, que gerencia subprocesso ACP via JSON-RPC stdio, converte eventos e expõe REST/WebSocket. O servidor suporta conversas/eventos, WebSocket e webhooks. É uma separação replicável no SENTRA: UI visual / Control Plane / ProviderAdapter / Executor, com cada domínio possuindo contrato explícito. O SDK/Agent Server foi clonado em terceiro repositório, além do frontend, para facilitar um protótipo real.

**Melhoria concreta:** quando um agente sai da UI, o SENTRA continua preservando Run/Agent/WorkItem; o backend mantém Process Session separada. Preferir streaming de eventos e eventos tipados às heurísticas de ler saída do terminal e identificar comandos de um modelo.

### 10.3 Yjs + @y/protocols e registro ACP

**Código verificado:** third_party/y-protocols/readme.md, que define sync, awareness e auth error. third_party/agent-client-protocol/schema/v2 e third_party/acp-registry, clonados para contratos de wire e catálogo.

Yjs pode sincronizar coordenadas, tamanho, agrupamentos, notas e cursores de colaboradores no SENTRA Web Canvas. O protocolo awareness trata estados efêmeros de usuário e cursores; não é uma base de permissões. Todo update CRDT deve passar por validação de workspace/tenant no servidor. Os estados WorkItem, Run, custos, política e leases continuam exclusivamente no servidor transacional.

O ACP Registry ajuda a descobrir adaptadores e capacidades de agentes. A lista externa deve passar por allowlist, pin de versão, assinatura/verificação de artefatos e autorização de instalação. Registro não prova confiabilidade do executor.

### 10.4 Controle de máquinas: Daytona + Guacamole

O Guacamole separa cliente HTML5 de proxy guacd; o Daytona descreve ambientes completamente gerenciados. São opções complementares: Daytona é apropriado para **criar e destruir computadores/sandboxes de agente**; Guacamole para **entrar em desktops existentes por protocolos remotos**. Para Windows host continuar com agentes locais limitados e provedores de sessão remota. Não conceder domínio amplo de teclado, rede ou FS sem autorização.

RustDesk utiliza AGPL-3.0 no arquivo LICENCE da revisão clonada. Para adoção comercial inicial, estudar Guacamole (Apache-2.0) como alternativa de menor risco jurídico; revisar suas licenças transitivas e segurança de sessão.

### 10.5 Observabilidade e compliance

A raiz do Langfuse usa MIT, mas exclui explicitamente componentes enterprise em ee/, web/src/ee e worker/src/ee. Activepieces também separa o núcleo MIT dos módulos enterprise em packages/ee e packages/server/api/src/app/ee. Não assumir que a interface inteira pode ser copiada.

immudb utiliza Business Source License com restrições para ofertas comerciais concorrentes, como consta no LICENSE. Usar como referência para algoritmo/trilha verificável, não como dependência obrigatória sem autorização jurídica.

OpenTelemetry Collector é apropriado para transportar traces estruturados, mas o ledger de auditoria verificável deve continuar na autoridade SENTRA. Métricas e tracing nunca devem habilitar leitura de credenciais, prompts sensíveis ou arquivos do cliente sem consentimento.

## 11. Complementos clonados após identificar dependências arquiteturais

Além dos 20 repositórios inicialmente selecionados, foram clonados:
- **openhands-agent-sdk**: OpenHands/software-agent-sdk — Agent Server, SDK, ferramentas e workspace.
- **y-protocols**: yjs/y-protocols — protocolo wire CRDT, awareness e erros de autorização.
- **acp-registry**: agentclientprotocol/registry — catálogo de agentes e seus metadados.

Os três estão registrados por commit no third_party/SENTRA_SOURCES_MANIFEST.json e não foram incorporados nem executados.

## 12. Decisões concretas para o SENTRA OS

| Decisão | Proposta | Razão |
|---|---|---|
| A1 | Manter Canvas próprio e introduzir sincronização por Yjs opcional | Evita descartar a UI e a física dos cabos existentes. |
| A2 | Criar ACPProviderAdapter e A2AIngress | Padroniza protocolos reais sem usar modelos como controladores de autorização. |
| A3 | Desenvolver DaytonaExecutor como componente externo opcional | Reaproveita sandbox/execução/snapshot sem substituir o core. |
| A4 | Expor Machine/Capability/Session/Operation como recursos endereçáveis | Torna cada ação disponível ao agente com política e auditoria uniformes. |
| A5 | Reforçar sandbox Windows e Linux antes de escalar | PTY em conta Windows de usuário não é isolamento suficiente. |
| A6 | WebSocket/SSE para telemetria em tempo real; CRDT apenas para UI | Evita polling constante e preserva fonte única de verdade. |
| A7 | Postgres transacional para modo hospedado/multiusuário | Escala sem compartilhar SQLite por rede ou perder fencing. |
| A8 | Guacamole como opção de desktop remoto, OTel como pipeline | Boa separação entre infraestrutura e regras do SENTRA. |
| A9 | Revisão jurídica de AGPL/BSL/enterprise antes de reutilização binária | Protege a possibilidade de comercialização do SENTRA. |

**Próximo passo de engenharia:** antes de copiar uma linha de Daytona, especificar o contrato ExecutorAdapter em termos de identidade de máquina, autenticação de sessão, capabilities, limites, operação idempotente, snapshot, cleanup, logs correlacionados e revogação. Em seguida implementar um protótipo externo com teste E2E isolado e aprovar licença e threat model.

## 13. Verificação final de clonagem

- 23 repositórios externos novos, todos com HEAD verificável e correspondência exata ao SHA do manifesto.
- 23/23 árvores de trabalho limpas; relatório gravado em third_party/SENTRA_CLONE_VERIFICATION.json, com 0 falhas.
- O clone Langfuse inicialmente perdeu 12 arquivos por limite de caminhos do Windows. A configuração local core.longpaths=true foi habilitada exclusivamente naquele clone e a restauração desses arquivos foi validada.
- Nenhuma dependência de projetos externos foi instalada nem suas aplicações executadas. Os 23 snapshots permanecem fora do versionamento principal por third_party/ estar excluído em .gitignore.
- O único novo arquivo de documentação no projeto principal é este relatório de auditoria. Os clones permanecem no computador, disponíveis para análise adicional e prototipagem explícita.


### Fonte GATE ? docs/SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md

# SENTRA OS — Gate 5 · Auditoria de absorção e coordenação de 37 projetos

Estado local: 2026-10-08, revisão no projeto C:\Users\vitor\OneDrive\Desktop\SENTRA. Não implica prontidão comercial nem release. Fonte: checkout local, docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md, testes de cada frente e snapshots Git.

## Critério de status

- **Código efetivo**: existe módulo SENTRA consumível ou extensão opt-in, com teste concreto.
- **Fronteira implementada**: há contrato/adaptador ou mock com teste, porém sem dependência externa real em execução.
- **Referência clonada**: código estudado e indexado, mas sem uso no runtime do aplicativo.
- **Infraestrutura planejada**: depende de serviços externos/configuração, deve ser opcional no modo local.
- **Benchmark**: ferramenta para validação, não componente de runtime.

## Governança por equipe

EXEC-001 → sentra_executors/ e tests/unit/test_sentra_executors_*.py: máquinas, Windows UIA, Daytona e executores de browser/remoto, nunca Control Plane.
CRIT-002 → sentra_interop/ e tests/unit/test_sentra_interop_*.py: agentes ACP/A2A/MCP, catálogo, ToolHive/OpenHands adapters.
CRIT-003 → sentra_collab/, sentra_canvas/static/sentra-collab.js e tests/unit/test_sentra_collab_*.py: colaboração e somente estado de apresentação.
COORDENADOR → sentra_runtime/, sentra_quality/, docs/SENTRA_OS_* e testes próprios: autoridade durável, hash/audit, integridade de fontes, plano de absorção e validação cruzada.

## Matriz dos 37 projetos

| Projeto | Dói onde no SENTRA | Absorção mínima | Estado verificado | Frente |
|---|---|---|---|---|
| UFO³ | Windows computer use, Galaxy DAG | estudar padrões/ações UIA/Win32 por app e mapear Machine/Operation | Referência clonada; sem operação UFO real | EXEC-001 |
| OpenHands | interface agêntica | padrões isolados de UX de agentes, conversas e aprovação | Referência clonada; Canvas SENTRA preservado | CRIT-003 |
| OpenHands Agent SDK | agentes externos | typed AgentSession/Event stream adapter | Fronteira implementada em sentra_interop/openhands.py, sem servidor real | CRIT-002 |
| Agent Client Protocol (ACP) | CLIs interoperáveis | session/new, prompt, updates, cancel e stdio seguro | Código efetivo local: fixture stdio JSON-RPC, não agentes externos | CRIT-002 |
| ACP Registry | catálogo | descriptors + versão fixada sem execução automática | Fronteira em sentra_interop/registry.py | CRIT-002 |
| A2A | comunicação agent-agent | envelopes task/artifact/ack + identidade confiável | Fronteira em sentra_interop/a2a.py, sem HTTP real | CRIT-002 |
| MCP TypeScript SDK | interoperar ferramentas TS | client/contract tool/resources seguro | SDK referência; boundaries MCP Python testados | CRIT-002 |
| Daytona | sandboxes isoladas | executor privado opt-in por SDK para sandbox previamente criado | sentra_executors/daytona.py com testes via doubles; sandbox real não validada | EXEC-001 |
| pywinauto | ações Windows UIA | janela/PID/seletor limitado, sem shell arbitrário | sentra_executors/windows_uia.py; teste UIA real skip por dependência/opt-in | EXEC-001 |
| hcsshim | Windows container | provider opcional headless, se host suportar | Referência clonada, sem runtime integrado | EXEC-001 |
| gVisor | sandbox Linux reforçada | perfil runsc opcional para workloads compatíveis | Referência clonada; não dá isolamento host Windows | EXEC-001 |
| Playwright MCP | browser agent | navegador em perfil/contexto isolado sem cookies do Edge principal | Referência clonada; não integrado ao executor | EXEC-001 |
| Guacamole Client | visualizar desktop | viewer de Machine remota com aprovação | Referência clonada; não integrado | EXEC-001 |
| Guacamole Server | RDP/VNC/SSH | guacd remoto governado por SENTRA | Infraestrutura planejada; serviço não instalado | EXEC-001 |
| RustDesk | acesso remoto máquinas | provider opcional alternativo ao Guacamole | Referência clonada; não integrado | EXEC-001 |
| LangGraph | subgrafos LLM | adapter por WorkItem, sem outro scheduler global | Referência clonada; integração opcional somente se necessário | CRIT-002 |
| Temporal | retries duráveis | padrões/worker adapter subordinado ao Run | Referência clonada; SENTRA mantém lease/runs | COORDENADOR |
| NATS JetStream | eventos dispositivos | barramento de envelopes idempotentes no gateway | Infraestrutura planejada; não instalada | COORDENADOR |
| ToolHive | MCP ToolHost | policy por tool, server registry e isolação | Boundary em sentra_interop/mcp.py com doubles; daemon não iniciado | CRIT-002 |
| SPIRE | identidade de dispositivo | SPIFFE SVID para relays/daemons remotos | Infraestrutura planejada; não instalada | COORDENADOR |
| Keycloak | login amigos | provider OIDC opcional | Referência clonada; não instalado | COORDENADOR |
| OpenFGA | autorização ReBAC | backend de decisão consultado, sem grants duplicados | Referência clonada; não integrado | COORDENADOR |
| OPA | política contextual | PDP versionado Rego opcional, deny-by-default | Referência clonada; sem PDP externo | COORDENADOR |
| Tessera | log transparência | witness/checkpoint externo para heads audit | Referência clonada; sentra_runtime/audit_chain.py só protótipo local | COORDENADOR |
| immudb | storage verificável | alternativa audit store com provas | Referência clonada; sem serviço | COORDENADOR |
| OTel Collector | traces distribuídos | exporter OTLP redigido | Referência clonada; não conectado | COORDENADOR |
| Langfuse | tracing LLM/custos | sink opt-in sem conteúdo sensível | Referência clonada; não instalado | COORDENADOR |
| Grype | CVEs SBOM | scanner de release e dependências de terceiros | Referência clonada; sentra_quality já verifica origem, NÃO CVEs | COORDENADOR |
| xyflow | nodes/edges | ergonomia/benchmark para Canvas sem substituir física | Referência clonada; não integrado | CRIT-003 |
| Yjs | edição simultânea | documentos CRDT somente layout/nós/notas | Código efetivo opt-in sentra_collab com WebSocket de teste | CRIT-003 |
| y-protocols | awareness/sync | presença sanitizada autorizada | Código efetivo no sidecar; produção não habilitada | CRIT-003 |
| Hocuspocus | servidor Yjs | WebSocket hooks auth/precommit/fencing | Código efetivo opt-in sidecar; fixture host, não conectado ao Canvas | CRIT-003 |
| Activepieces | automação SaaS | conector por WorkItem com OAuth isolado | Referência clonada; não integrado | CRIT-002 |
| RPA Framework | apps/documentos | biblioteca pontual em ExecutorRPA opcional | Referência clonada; não integrado | EXEC-001 |
| Windows Agent Arena | benchmark Windows | suíte VM de tarefas de Computer Use | Benchmark clonado, não executado | EXEC-001 |
| OSWorld V2 | benchmark geral | comparar efetividade dos executores em VM | Benchmark clonado, não executado | EXEC-001 |
| WindowsWorld | benchmark cross-app Windows | validação de etapas e efeitos | Benchmark clonado, não executado | EXEC-001 |

## Entregas atuais e evidência

- Testes de integração das frentes (pytest de 16 arquivos) em 2026-10-08 23:55–23:57: **196 passed, 1 skipped, 1 xfailed**. O xfail era defeito core conhecido de request.arguments mutável.
- Coordenador corrigiu no mesmo dia o problema core: ExecutorRegistry captura fingerprint e cópia canônica da requisição, rejeitando replay com alteração de intent; 33/33 testes runtime focados passaram; teste antigo de EXEC-001 tornou-se XPASS(strict), portanto aguardando remoção da marcação xfail pela equipe.
- GATE-4 anterior: colaboração chegou a 17/17 testes Node; cross Python 98/98. Essa rodada de pytest atual com test_sentra_collab_boundary passou, mas o runner Node separado deve ser validado após novas alterações.
- ACP stdio testado com fixture Python em subprocesso, incluindo casos de cancelamento, timeout e bloqueio de tool calls agent-initiated; histórico de falhas sob carga exige stress repetido. Não equivale a acesso a Codex/Antigravity real.
- Sentra_quality compara clones Git com approved_sources.json independente; 37/37 fontes foram verificadas na rodada anterior. Isso não é SBOM/CVE scan.
- Alterações desta sprint em módulos novos estão em arquivos **untracked**. Não promover a release sem revisão explícita de diffs, CI, package/build, security negative tests.

## Lacunas prioritárias para próxima integração

1. Gateway ControlStore/Run/Operation durável: autorização por grant e WorkItem e journal persistido, lease, fencing, reserva transacional ANTES de qualquer side effect; não duplicar autoridade.
2. Máquina real: executar WindowsUIA **somente em VM/usuário restrito**, distinguir limites de UIA por PID de isolamento OS. Daytona SDK em sandbox autorizado e privado somente após provisionamento manual revisado.
3. Agent real: ACP e A2A com agente terceiro autenticado, grantee/capability scoped, recuperação e reattach; evitar prompt-hacks. ToolHive só sob policy por ferramenta.
4. Canvas: host callbacks atômicos de commit/nonce/grant e sidecar opt-in, sem permitir CRDT alterar Run/Operation/Grant/Lease; 2 dispositivos autenticados E2E e TLS.
5. Fonte e auditoria: SBOM/Grype, testes de instalação, witness Tessera e OTel, segredo/redaction, backups/migrations; serviços opcionais para uso entre amigos.

## Política de absorção

Não substituir os componentes autoritativos do SENTRA por motores completos concorrentes. Incorporar bibliotecas pontuais, adaptar interfaces e habilitar servidores pesados apenas sob demanda. Preservar NOTICE/LICENSE aplicáveis ao compartilhamento, mesmo sem fins comerciais. As provas de E2E devem dizer precisamente qual processo/serviço/ambiente estava de fato em execução.


### Fonte CHECKPOINT ? docs/SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md

# SENTRA — checkpoint de implementação e retomada

Data: 09/10/2026. Snapshot solicitado pelo proprietário para preservar e enviar ao GitHub o trabalho antes do limite de uso. Base anterior: `68e3894`. Este documento descreve implementação, integrações e lacunas; não declara uma release aprovada.

## Estado real da entrega

Há uma base de código muito mais extensa: execução central durável, adaptadores reais, workflows, colaboração de documentos, agentes com contexto e uma nova superfície desktop. Há testes preparados e handoffs por frente. Ainda não temos a incorporação integral aceita dos37 projetos.

Nenhum requisito dos37 foi marcado concluído apenas pela existência de módulos. A regra continua sendo: implementação concreta + ligação ao produto + evidência de execução correspondente ao critério de aceitação. Configuração, registro de máquina, catálogo, ACK de transporte e retorno de processo não comprovam por si só uma tarefa verificada.

O snapshot reúne as alterações de projeto presentes no checkout, incluindo trabalho anterior ao coordenador desta rodada. Não atribuir todas as mudanças deste commit a um único agente ou somente à solicitação mais recente. Estado local, credenciais, caches, node_modules e clones independentes de third_party não fazem parte da entrega versionada.

## O que avançou no núcleo

1. **Autoridade central e persistência:** admissão pelo Control Plane existente, vínculo entre principal/Run/WorkItem/máquina/capability, intent imutável, fencing e recuperação por recibos duráveis.
2. **Efeitos físicos:** locks de recursos e máquina, leases/checkpoints e posse de workers. Cancelamento do chamador não libera antecipadamente um efeito físico ainda em andamento. Operação incerta bloqueia repetição até reconciliação.
3. **Evidências:** captura de Artifact dentro da fronteira física, hashes, resultados protegidos e referências no ledger. Retorno tardio serve como evidência diagnóstica; não promove sozinho uma operação incerta a sucesso.
4. **Host de máquinas:** event loop próprio, configuração persistida, restauração com verificação de workspace/agente, inventário, seleção por capability e despacho ligado ao WorkItem correto.
5. **Governança e limites:** integração com tarefas, orçamento/consumo, quota e estados centrais. Consumo não informado não é tratado como custo zero conhecido.
6. **Produto:** rotas Canvas/CLI para configuração, preparação de tarefa, execução, observação, experiências, planos e diagnóstico. Central com paginação de Runs, WorkItems e Operations, máquinas e limites.

Principais arquivos: `sentra_runtime/central_authority.py`, `effect_boundary.py`, `machine_host.py`, `provider_content.py`, `machine_budget.py`, `sentra_mcp/services/durable.py`, `sentra_executors/central_integration.py`, `sentra_canvas/service.py` e `sentra_cli/canvas.py`.

## Canvas desktop e qualidade visual

- Nova superfície em `sentra_canvas/desktop_ui/`; entrada `sentra_canvas/static/desktop.html`; bundle local em `static/desktop-assets/`.
- Componentes efetivamente incorporados: React Flow/XYFlow 12.12.0, React 19.3.0, Radix, Lucide e xterm 6.0.0. Pins transitivos no package-lock e manifesto do bundle.
- Direção visual da imagem Maestri: sidebar grafite, grid fino, barra de ícones flutuante, nós de terminal compactos, conexões curvas tracejadas e controles de zoom/mapa.
- Launcher pywebview/WebView2 abre uma janela Windows. O frontend usa HTML/React local dentro dessa aplicação; esse caminho não depende de abrir um navegador comum.
- Uma janela de avaliação foi aberta com três PowerShell/ConPTY reais. A instância antiga e seus terminais foram preservados.
- O frontend mantém views xterm por identidade de PTY, com filas de input/resize e sem recriar processos por pan/zoom/expansão.
- Dialogs para recursos/agentes/equipes, objetivo do agente, contexto e Rede. Integração visual com painéis de máquinas, workflows, Central e colaboração.
- Corrigida a colisão do import Lucide `Map` com o construtor JavaScript `Map`, responsável pela tela preta.

**Inspeção efetivamente relatada pelo agente visual:** superfície do broker de avaliação em 1440×900 com três nós/três xterms e nenhum pageerror. Capturas em `desktop_ui/evidence/`. Isso não comprova aprovação visual do proprietário, todos os fluxos nem a execução em WebView2 após reload.

**Limitação da prévia aberta:** o broker carregou o backend antes da nova rota Rede e respondeu `route not found`; o diálogo apresentou esse erro, sem simular sucesso. O bundle corrigido exige reload da janela. A nova API exige um processo atualizado; preservar terminais existentes antes de trocar o broker.

**Ainda falta:** revisão visual pelo proprietário, DPI/teclado/acessibilidade, drag e controles da janela, reconexão e Unicode/PTY, todos os diálogos com dados reais, build do executável, atalho, instalador e teste de fechar/reabrir sem perder sessões.

Detalhes: `sentra_canvas/desktop_ui/README.md` e `docs/SENTRA_DESKTOP_AUTONOMIA_REDE_2026-10-09.md`.

## Contexto e autonomia dos agentes

- Contexto protegido por workspace/agente, digest e revisão CAS: objetivo, papel, tarefas próprias, conexões e notas dirigidas.
- A CLI consulta o contexto atual por sua capability de sessão, sem copiar indiscriminadamente conversas de outros agentes.
- Criação de filho aceita nome/modelo/papel/brief. O objetivo selecionado e a entrega inicial persistente permitem que o filho recupere contexto.
- Identidades de filhos são registradas antes do bootstrap. Resposta perdida não relança automaticamente o agente nem a entrega.
- Comandos de criação de equipe, conexão e colaboração são reutilizados. Contexto e notas não criam grants de execução.

**Ainda falta:** prova com modelos reais criando filho/equipe e respondendo, testes de concorrência/restart/bootstrap, integração completa da coordenação à admissão central e tratamento de falhas parciais entre criação, registro e contexto.

## Hamachi/Radmin e whitelist

- Configuração protegida com CAS: adaptador Hamachi/Radmin/manual, IPv4 local, whitelist, porta comum37037 e rótulo.
- Cadastro vazio com descoberta desativada é permitido. Interfaces locais são obtidas do Windows quando disponíveis; entrada manual continua válida.
- Diálogo Rede no desktop. Rotas owner `GET/POST /api/center/network` e pareamento explícito `POST /api/center/network/pairing`.
- Agente vivo pode consultar e configurar campos autorizados da rede via `network_settings`/`network_whitelist`, solicitando os IPs ao usuário. Não recebe nem altera a chave de pareamento.
- Presença UDP assinada com Ed25519 e autenticação do mesh, whitelist de fonte, porta, validade, limites e defesa contra replay. Unicast explícito permite descoberta em VPN sem multicast.
- Descoberta não concede autoridade de máquina. A UI mostra somente peers efetivamente retornados pelo serviço.

**Ainda falta implementar:** transporte autenticado de tarefas e resultados, outbox/receipts/reconexão, despacho remoto ligado à admissão local, seleção de contexto compartilhado e política de colaboração automática. A presença implementada não é colaboração distribuída completa.

**Ainda falta validar:** duas máquinas reais Hamachi/Radmin. O proprietário informou que ainda não há IPs disponíveis. Não inventar pares nem declarar esse fluxo funcionando antes dessa prova.

## Workflows, documentos e colaboração

- Workflows com definições do proprietário, checkpoints, sinais, subflows, retries classificados e retomada. Inputs protegidos e operação separada por atividade.
- Máquina de workflows de documentos ligada ao host, com editor de etapas/sinais no Canvas. Falha de verificador falha a atividade.
- CSV/XLSX/PDF e interfaces explícitas para OCR/recalcular, sem tratar arquivo produzido como resultado semanticamente correto.
- Yjs/Y.Text, posições relativas, UndoManager e presença y-protocols; sidecar Hocuspocus com grants centrais, tickets de uso único e snapshots CAS.
- Projeção de layout/notas separada da autoridade de execução. Recuperação após interrupção de commit.
- Experiências derivadas de recibos e revisão/undo de planos preservam proveniência de efeitos já iniciados.

**Ainda falta:** pieces e providers completamente ligados ao produto, provas de crash/revoke/concorrência, runtime externo Activepieces, funcionalidades adicionais LangGraph/Temporal e verificação de workflows reais ponta a ponta.

## Desktop, serviços externos e isolamento

- Browser Playwright real com sessão/perfil, captura e verificadores; documentos/RPA com paths autorizados.
- UIA semântico e workflows de ações, identidade de sessão Windows e bindings de guest.
- Daytona com lifecycle/PTY/comandos/streaming; Guacamole com protocolo guacd, TLS/pins, cursores/gravação e contratos de viewer/tunnel.
- RustDesk com launcher/patch nativo próprio, pin da identidade do peer e watchdog; bundle privado copiado/verificado por hashes. Runtime, manifest e outputs têm autoridades de path separadas.
- Helpers de guest Windows/Hyper-V, bridge HCS e worker runsc/gVisor preparados.

**Ainda falta:** builds nativos/Go, providers/guests reais e seus prerequisitos, login/frame/input/revoke/cleanup, montagem final do viewer Guacamole e comprovação de isolamento. Posse de subprocesso/JobObject não equivale a sandbox de sistema operacional.

## Identidade, auditoria e observabilidade

- Keycloak OIDC, ciclo de vida OpenFGA, políticas OPA/bundles e cliente SPIRE com SDK/Workload API oficial implementados em módulos.
- NATS JetStream via SDK Go: PubAck, dedupe/reconciliação, pull e ACK/NAK/TERM/InProgress.
- Tessera: append, checkpoints/tiles, inclusão/consistência e quorum de witnesses.
- immudb: operações verificáveis, estado assinado, proofs e export de transação audit.
- Outbox/inbox protegidos, dedupe, retenção, tombstones, anchors e divergências. Recebimento de evento não executa comando nem cria grant.
- Pipeline OTLP com fila persistente, batching, limites, retenção, retries e contadores de perda.
- Grype: execução por binário pinado, SBOM, freshness, diagnósticos e diff de scans.

**Ainda falta:** AuditHost/configuração CAS/rotas owner, ligar ledger real aos providers, script de build SDK, go.sum/binários, TLS/ACL/credenciais, serviços e anchors/witnesses reais. Integração definitiva de identidade/políticas ao produto, deployment Collector e ligação de avaliação Langfuse. Scanner/DB/SBOM reais e revisão de TOCTOU. Nenhuma prova externa desta rodada foi executada.

## Benchmarks e avaliação independente

- Catálogo e formatos reais locais de Windows Agent Arena, OSWorld e WindowsWorld; pins/source drift e assets declarados.
- APIs `select`, `attempt`, `evaluate`, `resume` e `report`; tentativa separada de avaliação.
- Intents/IDs persistidos por passo e callbacks de host para bind/dispatch/recover/checkpoint/fixture/verifier; retomada consulta estado, sem reset/replay de efeito incerto.
- Métricas e relatórios separam resultado do agente e juiz independente. Assets/providers/formatos gated ausentes ficam unsupported.

**Ainda falta:** ligar callbacks a Core/guests reais, preparar snapshots/fixtures/goldens/collectors, assets autorizados e executar tarefas. Nenhuma tarefa foi declarada evaluated nesta implementação. OSWorld V2 gated e casos sem providers permanecem indisponíveis.

Detalhes: `sentra_executors/DATASET_EVALUATION_HANDOFF.md`.

## Matriz dos37 projetos para retomada

Todas as linhas permanecem com aceitação integral pendente. A coluna de avanço indica código/contratos entregues, não validação de runtime externo.

| # | Projeto | Avanço presente | Principal trabalho restante |
|---|---|---|---|
| 1 | UFO | Experiências protegidas e revisões de plano ligadas a recibos | Seleção de dispositivo/carga e prova de reutilização/obsolescência |
| 2 | OpenHands | Provider Agent Server, IDs/cursor/eventos e binding ao host | Runtime real, reconexão fora de ordem e recuperação completa |
| 3 | OpenHands Agent SDK | Condensação preservando instruções/contexto e leases/boundary | Sessão real, retomada e correspondência tool→Operation |
| 4 | ACP | Lifecycle negociado, config/usage e processos owned | Binding completo ao produto e CLI externo real |
| 5 | ACP Registry | Planos de instalação pinados binary/npx/uvx | Instalar/lançar distribuição selecionada e conferir integridade |
| 6 | A2A | Mapeamento/gates/transportes e estados duráveis | Recursos adicionais e servidor/peer real; loopback não prova VPN |
| 7 | MCP TypeScript SDK | Binding/transporte compatível com autoridade central | Contratos TS e execução real integrada |
| 8 | Daytona | SDK lifecycle, PTY, comandos e streaming ligados ao host | Serviço/credenciais/toolbox e aceitação real |
| 9 | pywinauto | UIA semântico, workflows e identidade Windows | Aplicações/guest reais, selectors/revoke/cleanup |
| 10 | hcsshim | Bridge Go/HCS e contratos de boundary | Build, host compatível e container real |
| 11 | gVisor | Worker OCI/runsc e verificação de workload | Linux/runsc real e prova de isolamento/cleanup |
| 12 | Playwright MCP | Backend real de browser e verificadores | Integração completa de contrato e aceitação final |
| 13 | Guacamole Client | Viewer/playback e contratos de tunnel | Bundle/montagem na UI e desktop real |
| 14 | Guacamole Server | Protocolo guacd/TLS/pins/cursor/gravação | Provisionar guacd/guest e testar login/input/revogação |
| 15 | RustDesk | Patch/launcher próprios, bundle privado, path separation | Build próprio, peer real, login/frame/control |
| 16 | LangGraph | Checkpoints/subflows/controle e workflows de documentos | Cobertura restante e runtime completo ponta a ponta |
| 17 | Temporal | Sinais/retries classificados/retomada no workflow | Cobertura restante e integração de runtime externo |
| 18 | NATS Server | SDK JetStream e outbox/inbox | AuditHost, broker/ACL/TLS e prova de entrega/reconciliação |
| 19 | ToolHive | Catálogo seletivo autorizado e invalidação de schemas | Catálogo no produto e prova de redução/correção |
| 20 | SPIRE | SDK oficial/Workload API e estado de identidade | Build, atestação, renovação/revogação real |
| 21 | Keycloak | Provider OIDC e lifecycle | Realm/serviço real e integração de login |
| 22 | OpenFGA | Lifecycle/modelo/relacionamentos/autorização | Serviço/modelo real e binding na política central |
| 23 | OPA | PDP, bundles e máscara de logs | Serviço/bundle real, decisões e revogação na aplicação |
| 24 | Tessera | Append/checkpoints/proofs/witnesses | AuditHost, log, anchors e quorum reais |
| 25 | immudb | VerifiableSet/Get, proofs/estado/export | AuditHost, DB/TLS/estado confiável e provas reais |
| 26 | OpenTelemetry Collector | Pipeline OTLP persistente e configuração | Deployment Collector e demonstração de export |
| 27 | Langfuse | Requisitos/fronteiras de observabilidade mapeados | Integração completa de traces/datasets/evals no produto |
| 28 | Grype | Scanner pinado e comparação/diagnóstico SBOM | Binário/DB reais, prova e revisão da captura de inputs |
| 29 | XYFlow | React Flow real no desktop, nodes/resize/pan/zoom/mapa | QA de sessões, escala, teclado, DPI e aprovação visual |
| 30 | Yjs | Y.Text, undo e posições relativas | Concorrência, persistência e revogação ponta a ponta |
| 31 | y-protocols | Awareness com propriedade/clock/TTL | Disconnect/revoke real e integração distribuída |
| 32 | Hocuspocus | Sidecar real, tickets/grants e snapshot CAS | Crash/recovery, revogação e runtime integrado |
| 33 | Activepieces | Provider HTTP e worker SDK piece | Pieces/providers no produto e runtime externo real |
| 34 | RPA Framework | CSV/XLSX/PDF, OCR/recalcular configuráveis | Providers opcionais e aceitação semântica real |
| 35 | Windows Agent Arena | Catalog/attempt/evaluate/report e métricas | Guest/fixtures/juiz reais e tarefas avaliadas |
| 36 | OSWorld V2 | Loader/contratos e unsupported explícito | Assets gated/snapshot/providers e avaliações reais |
| 37 | WindowsWorld | Loader/métricas/estado intermediário/report | Seeds/goldens/collectors e execução real |

## Validação: o que foi e o que não foi feito

- Existiram execuções de testes em etapas anteriores, documentadas nos respectivos relatórios. Não usar esses resultados históricos como prova do snapshot atual.
- Bundles de colaboração e desktop foram construídos para materializar a interface. A inspeção visual do agente confirmou renderização após a correção MapIcon; não substitui suite de funcionalidade nem aprovação visual.
- Por instrução do proprietário, implementação veio primeiro e bateria integral ficou para o final. Novos testes foram escritos/preparados, mas a bateria integral deste estado não foi executada.
- Não houve aceitação real nesta rodada dos serviços externos, builds nativos/Go, VMs ou colaboração Hamachi/Radmin. Ausência de prerequisite deve aparecer como pendência explícita, nunca sucesso simulado.
- O commit é checkpoint de trabalho em andamento. Fazer push não valida nem publica uma release operacional.
- Na preparação do commit, `git diff --cached --check` apontou whitespace em patch upstream, documentação e bundle gerado. Esses arquivos foram preservados; a conferência de whitespace não passou limpa. Não alterar linhas de contexto do patch ou bytes/manifest do bundle apenas para ocultar o aviso.

## Ordem prática para continuar

1. Restaurar o checkout deste checkpoint e consultar os handoffs, matriz e manifests. Clones third_party são independentes: recriar/verificar pelos HEADs/pins registrados quando não estiverem presentes.
2. Atualizar a prévia desktop de forma que preserve as sessões, recarregar o bundle e testar diálogo Rede em backend atualizado. Obter avaliação visual do proprietário.
3. Terminar viewer/gateway Guacamole e transporte peer de tarefas/resultados. Autenticação/discovery não substituem admissão de trabalho.
4. Terminar AuditHost e ligações de identidade/políticas/ACP/MCP/A2A/Activepieces/Langfuse ao produto, com configuração owner e secrets privados.
5. Ligar datasets ao host central e preparar ambientes/fixtures/providers reais. Completar lacunas por projeto, sem reduzir critérios ao código existente.
6. Compilar bridges/builds nativos e provisionar serviços necessários. Registrar prerequisites, versões e evidências reproduzíveis.
7. Executar validação integral Python/JS/frontend/integração/E2E e aceitação real por provider; corrigir falhas. Registrar pass/fail/skip e limitações.
8. Empacotar e aceitar executável/instalador Windows. Só então promover os requisitos correspondentes a concluídos e avaliar a conclusão integral dos37.

## Documentos de referência

- Auditoria original: `docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md`.
- Reavaliação37: `docs/SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md`.
- Requisitos verificáveis: `sentra_quality/incorporation_requirements.json` e `desktop_agent_collaboration_requirements.json`.
- Núcleo/Canvas: `docs/SENTRA_INCORPORACAO_NUCLEO_CANVAS_2026-10-09.md`.
- Workflows: `docs/SENTRA_INCORPORACAO_WORKFLOWS_CANVAS_2026-10-09.md` e `SENTRA_INCORPORACAO_WORKFLOW_ACTIVEPIECES_2026-10-09.md`.
- Identidade: `docs/SENTRA_INCORPORACAO_IDENTIDADE_POLITICA_2026-10-09.md`.
- Auditoria externa: `docs/SENTRA_INCORPORACAO_NATS_TESSERA_IMMUDB_2026-10-09.md`.
- Desktop/guest: `sentra_executors/DESKTOP_GUEST_BENCHMARK_HANDOFF_ROUND4.md`.
- Dataset: `sentra_executors/DATASET_EVALUATION_HANDOFF.md`.
- Desktop visual: `sentra_canvas/desktop_ui/README.md` e capturas em `evidence/`.


## Validacao futura (nao executada)

Depois de todas as implementacoes e composicoes integradas e liberacao do Codex: confronto requisito/clausula por requisito/clausula com codigo, endpoints/UI/CLI/desktop, ambiente/provider real, logs/receipts/artefatos recuperaveis, sucesso/falha/timeout/concorrencia/duplicata/cancel/revoke/crash/recovery. Incluir conta Web real autorizada, servicos opcionais configurados, duas maquinas/identidades, scopes/multiusuario, backups/restore, pacote assinado/clean install/rollback e fidelidade visual CopilotKit/ARIA/DPI. Registrar pass/fail/skip e prerequisites sem promover skip/fixture a aprovado. Nenhum destes passos foi executado por Meridiano.

## Atualizacao concorrente e lacunas adicionais dos donos

Assinatura central shell confirmada keyword-only no codigo; HTTP bearer ja encaminha Canvas.shell_bridge(p), cuja composicao ainda esta em andamento. Store ganhou ramo Postgres em trabalho; nao declarar backend completo pela factory. Selo reportou exporter Langfuse/OTLP, diferente de prompts/datasets/evals/learning revisado ainda abertos. Pulso reportou explicitamente sem runtimes Temporal/LangGraph. Pacto deny-only A08 permanece rejeitado pelo usuario. Relatos completos e snapshots separados em coverage.json; contratos atualizados em contracts.md.

- GAP-13 (Brisa, Rastro, Prisma): Attachment upload and recoverable content still required. Brisa reports descriptors/fingerprints, not composer upload delivery. Rastro explicitly distinguishes READY_LOCAL from upload. Must retain authorized artifact bytes/refs, perform real upload to exact conversation, and obtain receipt; hash or chip alone does not close A12.
- GAP-14 (Brisa, Vitra, Codex): Browser Host evidence endpoints and extension identity update open. Brisa report says host lacks /v1/sentra/approval-snapshot and /v1/sentra/account-catalog and extension version 1.7.0 still has source hash/bootstrap proof from 1.6.52. Implement Host evidence contract and coordinate release re-stamp (future build prohibited now); no implicit proof.
- GAP-15 (Brisa, Rastro): Streaming identity by logical message needs final binding. Brisa reports content script revision by message index while requirement A13 demands stable logical message ID/revision under virtualization/reorder/reload. Bind attested message ID to ledger rather than frame/index alone, preserve overflow content and reconcile restarts; no message receipt from DOM observation alone.

Todas as lacunas permanecem sem homologacao; comparar snapshots temporalmente, nao usar busca inicial para negar codigo que foi adicionado depois.

## Contrato Lume recebido e confirmado por leitura

InteropProviderMachine em sentra_interop/provider_machine.py:

```python
InteropProviderMachine(control, *, owner, agent_id, machine_id,
                       workspace_root, kind, configuration)
catalog()
dispatch_request(*, run_id, work_item_id, machine_id, capability_id,
                 operation_id, arguments, idempotency_key=None)
submit(*, run_id, request)  # async
shutdown()                # async
```

Factory ACP/A2A/MCP para MachineHost existente, sem criar WorkItem/Grant nem iniciar agente implicitamente. Config host enabled, executable pin/consent para ACP/MCP, secret refs vault e destination/identity/process derivados do host. Catalog reporta transport_ready unverified e validation_status pending.

Lume informa em implementacao: projections cifradas ControlStore; ACP lifecycle/config/usage/absent-null preservados e elicitation duravel; A2A HTTPS AgentCard pin/context/continuidade/SSE/chunks/push; SDK MCP TS real 2.3.1 por revisao sem auto-retry/auto-fulfillment; registry instalacao real. Assinatura enviada a Nexo para composicao. Nada homologado.

Canais escolhidos: Slack/Telegram/WhatsApp **Cloud via APIs oficiais**, signature/replay/allowlists/outbox+receipts, alinhamento Pulso. Essa escolha e estado em andamento supersedem busca anterior sem adapters. Nao impor libsignal por analogia com feder; inventariar somente dependencias concretamente selecionadas e notices de distribuicao. Contratos finais serao publicados por Lume em docs/integral/Lume.md.

## Atualizacao Tessela - contrato implementado recebido

Contrato recebido em 11/10/2026 e confirmado por leitura estatica de codigo. Nao foram executados testes, build, lint, benchmark ou QA. GAP-07 anterior de escopo workspace-only foi superado no novo ProjectDocuments; watch renames e evidencia final permanecem pendentes.

```python
ProjectDocuments(control, *, owner, resolve_space, resolve_run=None, clock=time.time)
dispatch(action, payload, *, project_id, principal_id,
         principal_type="user", work_item_id=None)
host_call(method, params)
```

Allowlist completa: document_list, document_get, document_create, document_save, document_history, document_restore, document_delete, document_diff, document_export, document_session, document_session_close. Namespace canvas_collaboration; project_id canonico corresponde ao workspace_id das metadata do WorkItem, com space_id/document_id e Grants read/write por tarefa/documento. Escritas: expected_revision CAS, mutation_id ligada a intent fingerprint, Operation e receipt; hierarquia/ciclos, tombstones, historico imutavel e restore cria nova revisao. Snapshots Yjs binary/precommit pertencem a mesma historia.

Callbacks privados em /api/collab/host: documentResolveGrant, documentCheckGrant, documentConsumeNonce, documentLoadSnapshot, documentCommitSnapshot. CentralCollabBridge seleciona callbacks document quando documentId presente. Canvas _document_service compoe ProjectDocuments, dispatch repassa identidade de servidor e collab_host_call delega a DOCUMENT_HOST_METHODS; leitura confirma pontos de composicao, sem prova runtime. Owner credential nunca vai ao renderer.

UI named export ProjectDocuments({bridge, spaceId, projectId, documents, onRefresh, onError, onDirtyChange}); TipTap 3.31.3 Markdown/TableKit, CodeMirror 6, IndexedDB drafts, estados dirty/saving/saved/error/conflict e guard onDirtyChange. Prisma consome props/bridge; nao edita componentes document-* pertencentes a Tessela.

Ownership: Tessela implementa servico/documentos/collab/componentes; Nexo preserva associacao Space/project e Control Plane; Codex compoe HTTP/Canvas/identity, Prisma encaixa shell e dirty-navigation guard. Compatibilidade com Postgres/migracoes de Nexo continua dependencia transversal; presenca de SQL SQLite/ATTACH no servico nao prova multiusuario.

Pendencias declaradas: finalizar watch/renames e entregar docs/integral/Tessela.md com contratos finais. Validacao somente na etapa final liberada pelo Codex. Nenhum requisito promovido a homologado por este relato.

### Alinhamento de contrato documento/shell ainda pendente

Leitura posterior confirma Canvas.shell_bridge(self, payload) presente: identidade derivada de servidor, project_id/ws consistentes, dispatch DOCUMENT_ACTIONS para ProjectDocuments e restante para control.shell_dispatch. Isso supera registro anterior de facade Canvas nao encontrada; nao houve execucao HTTP.

Diferenca textual: collaboration-document.js envia document_session com permission='write', enquanto Canvas.shell_bridge rejeita permission globalmente. O contrato central exige permissao derivada da sessao/grants, nunca autoridade do renderer. Codex/Tessela/Prisma devem alinhar schema do pedido e derivacao do servidor preservando esse limite; nao tratar como erro validado em runtime e nao editar arquivo de outro dono. GAP-07 mantem esse alinhamento, watch renames/relatorio final e homologacao futura abertos.

## Ordem atual - OpenCode TUI persistente e composicao shell

Atualizacao do usuario em 11/10/2026: seis OpenCode corrigidos para TUI interativa persistente com --session dos IDs existentes e --auto, sem run; processos/telas high confirmados pelo principal. Essa ordem SUPERA as instrucoes historicas de relancar opencode run --file via raw. Nao relancar tarefas via raw agora. Prompts simples somente apos confirmar UI do agente; progresso por docs/integral/Nome.md, evitando ask sincrono. Meridiano nao reiniciou terminais nem enviou novo ask neste checkpoint.

Documento do principal: docs/integral/COORDINATOR_TERMINALS.md. Nao editar esse arquivo, nem os terminais, para registrar progresso de Meridiano. Arquivos tasks/Nome.md continuam referencia de escopo, sem ordem ativa de relaunch.

Principal informa _shell_service/shell_bridge/ProjectReviewService/document callbacks e shell_runtime CLI real criados. Leitura estatica confirma Canvas._shell_service compoe CanvasShellRuntime(canvas, host.control, owner=host.owner) e attach_shell_runtime na mesma autoridade; ProjectReviewService tem dispatch escopado ao projeto; documento/callbacks seguem contrato Tessela. CanvasShellRuntime conserva protected queue vinculada a Operations centrais, so recupera queued se operacao central tambem QUEUED e marca submissao interrompida UNCERTAIN sem automatic_retry. Transporte de anexos ainda exige configuracao explicita.

Dependencia ainda aberta: binding provider_usage por Nexo para consumidor CanvasShellRuntime/ControlPlaneService, contabilizacao/budget/quota autoritativos e custo desconhecido explicitamente representado. Nao tratar CLI criada como provider real homologado nem zero-custo conhecido. GAP-08 foi atualizado para esse binding e evidencias futuras; demais lacunas/contratos de expansao permanecem abertos. Nenhum requisito foi removido ou homologado. Nenhum teste/build/lint/benchmark/QA ou execucao de CLI foi realizado por Meridiano.

## Inventario atual de callbacks e dependencias de execucao

Inventario conciso em docs/integral/composition_inventory.md: doze owners (Codex + onze implementadores), callbacks/consumidores e dez dependencias concretas de composicao/artefato/ambiente. coverage.json tem composition_inventory e execution_dependencies, snapshots contemporaneos e relatos atualizados. Nenhuma fonte antiga ausente foi promovida a ausencia atual sem releitura; nenhum artefato/binding foi promovido a operante pela existencia de callback.

Prisma UI e expansoes Forja entregues por relato explicito/fontes; Tessela permission corrigida. Host QuickJS existe mas guest QuickJS/wasmtime faltam; workflow adapters existem mas SDK client/worker/definition/server faltam; voice/API/anexo bytes existem mas delegacao Canvas/runtime/provider configurado e chunks >512KiB faltam; canais APIs existem mas ingress/admitter/sender/unsubscribe enrollment faltam; learning/eval local existe mas binding central/servicos/verificadores faltam. Postgres store existe mas ProjectDocuments._guard ainda ATTACH enquanto backend rejeita ATTACH/path_for=None; compor guarda transacional nativa Nexo/Tessela/Codex. Vitra runners existem mas binarios/PKI/manifests assinados/exit-helper/keys callbacks finais pendem. provider_usage Nexo permanece pendente pelo principal.

Fonte entregue != integrado != homologado. Todas as clausulas/aceites e opcionais mantidos; nenhuma validacao, ask sincrono ou relaunch raw executado neste inventario. Pendencias ao Codex por este arquivo conforme protocolo TUI.

## Atualizacao Nexo/Lume/Forja/Tessela - entregas atuais

Inventario composition_inventory.md/coverage.json atualizado sem reduzir escopo. Nexo entregou binding shell provider_usage, reassign transacional/agent_run_memberships e MachineHost channels/acp_registry/executors/input/UFO; backup/restore/migrate/rollback/principals Postgres seguem em andamento. _shell_context fonte presente vincula conversa a Run/WorkItem/Operation; caminho SQLite/ATTACH ainda inspecionado, sem inferir aceite Postgres.

Tessela entregou relatorio final e authority_guard Postgres nativo: mesmos tenant schemas, sorted advisory locks, FOR UPDATE membership/Grant/WorkItem/Run/Operation, reader nega escrita, sem fallback SQLite. Watch/debounce/rename/TTL e permission corrigidos. Antiga lacuna ATTACH-only documental superada; deps/lock/bundle e provas nativas/runtime continuam pendentes.

Forja entregou Forja.md final e INTEGRAL_PROVENANCE.json (SHAs completos/upstreams/license_files declarados, nao verificados por Meridiano). Expansoes providers/InputControl/UFO/hybrid/Playwright/Daytona/Guacamole/RustDesk prontas para integrar; callback application_action posicional async alinhado Nexo. HTTP/UI/MCP + builds/VMs/SDK/guacd/peer/config/aceitacao sao pendencias reais, nao declarar operabilidade.

Lume: channels.py/ChannelProviderMachine concretos para Slack Events/WebAPI, Telegram webhook/BotAPI e WhatsApp Cloud Graph API(api_version), inbox/outbox OS-cifrados, assinatura/replay/allowlists/mapping e ACK distinto de recipient statuses/reply/claims. Cloud nao precisa/importa libsignal. Variante QR/libsignal permanece separada explicitly unavailable; invisible_dots local ausente conforme pesquisa/relato. Se variante QR independente for explicitamente exigida, encaminhar escopo/pin-fonte aprovado e notices GPL-3.0 pertinentes antes de implementar/validar. Nao inferir grant/prova QR de Cloud e nao fechar FF13 por stub. Fonte original, variante escolhida e alternativa indisponivel permanecem na matriz.

Nenhum teste/build/lint/benchmark/QA/execucao externa, ask sincrono ou relaunch raw. ZERO requisitos homologados. Fontes finais e protocolos nao substituem evidencias contemporaneas.

## Lume - entrega final de dominio registrada

Fonte final docs/integral/Lume.md preservada com hash em coverage.json. Factories ACP/A2A/MCP/channels/acp_registry exp?em catalog/dispatch_request/submit/shutdown para MachineHost; projections OS-cifradas no ControlStore. Namespaces: interop_projections, interop_interactions, interop_installations, interop_push, channels; provider_content reutilizado. Registro de namespace/factory/facade em arquivo nao e runtime homologado.

Implementacao entregue: lifecycle/elicitation/config/usage/absent-null/terminal-display; A2A Card/push/SSE/chunks/recovery; MCP SDK oficial 2.3.1 por revision/subscriptions/input_required owner-consumed; staged binary/npx/uvx com lock/pins/manifests/reconcile; OpenHands condense/transcricao preservada/health/tool links/delete; Slack/Tg/WA Cloud autentica??o/inbox/outbox/receipts/revoke. Quatro testes de persistencia/canais foram preparados em tests/unit/test_sentra_interop_integral_lume.py e NAO executados.

Callbacks adicionais Codex/Nexo: factory.receive_callback(raw_body,headers) para push A2A autenticado e limitado; ChannelService.receive(connector_id,raw_body,headers) para webhook raw <=1MiB e challenge WhatsApp; ProtocolInteractionService.pending/reply/consume_embedded para entrada owner; Pulso pending_inbound/claim/ack para admissao, send/receipt/lifecycle para canal. Ingestao so persiste inbox; nao cria WorkItem/Grant nem dispara efeito.

Limites retidos na matriz: ACP host filesystem/terminal privileged requests indisponiveis por padrao (terminal do agente display-only; executor/Pulso exige grants); restart SDK MCP legado fail-closed sem replacement/replay, requer reconciliacao; QR/libsignal separado nao incorporado, Cloud API real configuravel nao prova essa variante, notice separado. Nao reduzir requisito ao estado unavailable: manutencao da pendencia, provisionamento/runtime e composicao outros donos continuam explicitos.

Codex/Nexo receberam os contratos pelo relato do dono. Este update reporta via documentos conforme protocolo TUI; sem novo ask sincrono/raw, nenhum codigo alterado, nenhum teste/build/lint/benchmark/QA. Entrega de dominio != integracao integral aceita != homologacao. ZERO requisitos homologados.

### Lume - composicao central presente em fonte

Leitura posterior confirma cinco namespaces em control_store.py, MachineHost.receive_interop_callback(machine_id,raw_body,headers) e handlers POST /api/interop/webhook/<machine_id>, POST /api/channels/webhook/<connector_id> e GET handshake no handler Canvas. Supera ausencia/solicitacao historica desses pontos. Status: composicao presente em fonte, sem request HTTP, processo provider ou runtime executado. UI/claims/resolvers restantes, provisionamento externo, compatibilidade Postgres e evidencias continuam pendentes. Nenhuma homologacao.

## Delta root - composicao protegida, machines e optional

Fonte atual docs/integral/Codex.md registrada com hash/snapshots. ShellHostRequests(control,owner).invoke(project_id,action,payload,request_key,callback) reserva fingerprint/payload protegido antes do efeito e deixa interrupcao UNCERTAIN sem replay; operation_id derivado servidor. Journal duravel nao substitui central effect fence/lifecycle ainda pendente.

ShellMachineServices(canvas).dispatch(project_id,action,params,request_key): machine_list/input_status/input_handoff/remote_viewer_open/remote_viewer_close/machine_execute/machine_observe. WorkItem/Run/agente/projeto/grant/live epoch conferidos, capability derivada so quando unica. Viewer exige scope_verified/transporte vivo; listener loopback lazy port=0/origins Canvas, tickets view/human, dispatch_human com epoch, revoke-all/shutdown. Fonte composta, nao listener/provider executado.

OptionalShellServices(runtime): voice_availability/attachment_availability/voice_dispatch/attachment_dispatch/validate_attachments/attachment_bytes; VoiceRuntime/AttachmentStore no control.store; call/ref/upload escopados projeto/Space/conversa, bindings upload duraveis, chunks/status request key CP. CanvasShellRuntime ja delega metodos optional; antiga ausencia de delegates/chunks superada. A2A raw POST 1MiB com factory/projeto conferidos antes do receive; ingress-only, nao admissao/efeito. Channels/acp_registry na configuracao central existente.

Shell runtime instala binding provider apenas sob execution-lock de conversa; recover_completed valida Operation SUCCEEDED e protected journal hash/sequence/receipt para publicar resposta ja confirmada, SEM model replay. Isso nao fecha fluxo hosted/nativo por si.

PENDENCIAS EXPLICITAS DO ROOT (nao encerrar): helper multimodal Rastro; central optional fence/lifecycle Nexo; hosted TaskRuntime factory Nexo/Codex; Pulso runtime machine factory; bindings Selo/Pacto/Vitra. Registradas em coverage.composition_inventory.root_remaining, GAP-16/GAP-17 novas e demais gaps correspondentes. Todos artefatos/providers/builds/ambientes/acceptance futuros continuam em escopo.

Preview autorizado isolado PID47408 permanece intocado por Meridiano. Root relata dependencias/assets materializados pela excecao visual, sem liberar validacao geral; nao confundir com nenhuma execucao de teste/build/QA por Meridiano nem com homologacao. Este delta nao executou testes/lint/QA/build novo, provider, listener, preview ou terminal. Reporte somente por arquivo; SEM ask-back root. ZERO requisitos homologados.

## Adendos atuais Prisma e Nexo - fontes presentes, integracao em andamento

Prisma: novos shell-mascot/shell-attachments/shell-machines registrados; uploads begin/chunk/complete/abort/status reais no bridge,4 refs/imagem8MiB/docs20MiB/chunks512KiB/SHA/TTL1800/same-key retry/status incerto/reselect hash apos reload.512KiB e chunk, nao mais limite total UI. Viewer/InputControl contextual readonly default/human epoch-live-granted/scopes-opID servidor, closes transport nao OS, playback local sem input. Fonte e composicao entregues; servicos/pacote/config/receipts/aceitacao pendentes.

Assets fonte Prisma:4 PNG originais OpenDots pin625452e/MIT/copyright/PROVENANCE; Guacamole-common-js1.5.0 repack padarom (nao cloneApacheatual), SRI conforme PROVENANCE.json,Apache LICENSE/NOTICE/PROVENANCE, TipTap menus3.31.3 pins/overrides. Vitra informado para transportar notices/payload/manifest. Nenhuma install/build/lock/bundle/QA nova; preview PID47408/lock/assets preservados. Historica pesquisa sem mascotes superada por feedback visual explicito do usuario registrado Prisma; nao modificar fontes historicas.

Nexo delta concretizado: postgres_store native psycopg/tenant/RLS/DDL/migration/advisory locks/fence/backup-restore; NativeAuthorityMigration prepare -> native atomic commit -> protected CAS activate -> rollback/export_sqlite_rollback, fonteSQLite preservada, RunRECOVERING/OpUNCERTAIN/leases invalidated sem replay. Default factory/store selection compartilhada durable/context/governance semSQLitefallback.

CanvasAuthorityRuntime(state_root,canvas_store,*,control,owner) herda TaskRuntime e injeta cp durable/governance/budgets/UsageLedger(control=control). Antiga falta de hosted factory superada em fonte; integracao completa/aceitacao nao inferidas. Componente recebido como ShellOptionalAuthority tem entrada atual execute_optional(shell,*,owner,project,action,payload,key,callback), pre-effect Grant/intent/OSlock/fence/budget, signaling/storage receipts seguros nunca completion model/audio. Antiga ausencia de gate superada em fonte; lifecycle integral/final evidence permanecem abertos.

PENDENCIAS: multimodal helperRastro, runtime machinefactoryPulso, bindingsSelo/Pacto/Vitra, native full-file backup/keys prerequisite Nexo em implementacao, finalNexo.md e toda aceitacao provider/duas maquinas/PG/pacote/lock/bundle. GAP-02/07/08/10 seguem implementacao/integracao em andamento por instrucao Nexo; GAP-16/17 agora registram fonte presente e evidencia/integracao pendente, nao ausencia antiga. Escopo integral e textos de aceites preservados.

Zero testes/build/lint/benchmark/QA/install/execucao provider/preview, nenhuma homologacao. A primeira tentativa de gerar adendoPrisma falhou antes de gravar por variavel indefinida; esta grava todos os registros. Reporte ao principal por arquivo, sem ask-back/sincrono/raw.

## Ownership ATUAL - Cobalto sucessor dos seis dominios OpenCode

Autorizacao explicita usuario 11/10/2026: Cobalto gpt-6.1-sol/high ja recrutado pelo root, PID28432/high/YOLO informado, conectado nota+Meridiano e implementadores ativos. Meridiano nao recrutou/reiniciou; maestri list confirma Cobalto e nota disponiveis a Meridiano. Seis dominios Rastro/Brisa/Pacto/Pulso/Selo/Vitra transferidos para Cobalto. Nomes anteriores agora autoria/frente HISTORICA, nao dono atual de nova implementacao. Codex raiz/Nexo/Prisma/Forja/Lume/Tessela/Meridiano conservam ownership; root reserva code_machine.py e arquivos Canvas/HTTP/MCP/root.

Handoff completo: tasks/Cobalto-priorities.md (P0/P1/GAPs/fontes presentes/pendencias reais/interfaces) e tasks/Cobalto-sources.md (nota integral e dezfontes/hash/caminhos) associados aqui para leitura de Cobalto. Taskroot tasks/Cobalto.md preservada. Atual owners em coverage requirements/current_gaps mapeados a Cobalto, historical_owners/ownership_history preservam autoria. Clauses da fonte original nunca alteradas.

Prioridade: QuickJS guest/flags A08/replay RUNNINGuncertain/fullresult; one-turn multimodal receipts e quota2/PDFbinary vs4localrefs; Host account/approval/voz transcript verificado/restamp; RuntimeProviderHost/RuntimeMachine/TerminalWriteMachine factory/policy/restore/claims; VitraHostFacade admission-before-effect/trustedpaths/quiesce/keys/notices; Selo build_client real config/vault/scopes/CAS e policy/audit/learning/Langfuse/OTLP. Novas fontes Pulso factories/QuickJS guestC/hostfacade presentes, nao manter ausencia antiga nem inventar pacote/servico emexecucao.

Cobalto vai criar Cobalto-status.md por frente e IMPLEMENTAR; nao apenas auditar. Prioridades nao reduzemescopo; todos mecanismos/opcionais/aceites mantidos. Relato arquivos, sem ask-back root. Sem validacao/test/build/install/lint/benchmark/QA/runtime/recrutamento/restart/commit/push/reset/stash; previewPID47408 intacto. ZERO homologados.

## Redistribuicao vigente e delta root

> Ownership ATUAL: Cobalto=Brisa/Rastro; Prisma=Pacto; Lume=Pulso; Forja=Selo; Tessela=Vitra. REDISTRIBUICAO_CODEX.md supera transferencia anterior. Autoria historica preservada; root/Nexo e demais donos mantidos. Nenhuma homologacao.

Fonte de prioridades em fechamento-backlog.md (entregue; varredura est?tica por cl?usula); Codigo root code_* e MCP CP compartilhado presentes, nao ausencias antigas. Coordinator chat ainda exige token CLI operationbound e CP Grant/admissao antes legacy_coordagent. Sem ask-back/test/build/QA/restart/recrutamento; PID47408 preservado.


## Entrega do backlog integral de fechamento

[fechamento-backlog.md](fechamento-backlog.md) entregue com 69 frentes, por arquivo/dono/acao e constatacao atual. [fechamento-backlog-data.json](fechamento-backlog-data.json) e coverage conservam 449 registros, 1.366 segmentos internos e 2.176 clausulas nao vazias das dez fontes, incluindo contexto/proveniencia/aceites e opcionais. Associacao por topico ? encaminhamento, nao prova semantica de implementacao; clausulas continuam abertas ate corpo+consumidor+autoridade+receipt ou condicao explicitamente implementada.

Atualizados ownership atual/historico, contracts, callback inventory e tasks originais sem editar fontes dos donos. Prioridades reais: coordenador token/admissao FB-01; LangGraph colisao atributo/metodo FB-09; guest-artifact allowlist root FB-47; bindings runtime/Selo/Vitra/voz/multimodal. Corrigidas ausencias historicas ja superadas (code_*, CPshared, lifecycle reserve, SDKasync, SeloLangfuse, transcript sideband e binary composer).

Relato por arquivos conforme protocolo vigente; maestri list executado, sem ask-back sincrono, recrutamento/restart, skills/MCP SENTRA, commit/push/reset/stash. Nenhum teste/build/install/lint/benchmark/QA/provider externo executado. ZERO homologados; preview preservada.
