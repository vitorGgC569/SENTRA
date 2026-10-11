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
