# SENTRA × Chat On Steroids — auditoria de cobertura dos 34 itens

Data de verificação: 2026-10-09. Fonte: `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md` (13 frentes + 21 subfrentes, com sobreposição). Estado confrontado: checkout de trabalho no Desktop Commander e `docs/SENTRA_COS_INCORPORACAO_EXECUCAO_2026-10-09.md`. Upstream pinado: `151e7ef`. **Não confundir presença de classe, arquivo ou teste unitário com integração real no Canvas/CLI, provider autorizado, E2E ou instalador homologado.**

## Veredito

**NÃO foi coberta integralmente a matriz.** Para os critérios completos do documento: **0/34 com aceite E2E integral demonstrado**; **23/34 com implementação parcial ou base reutilizada**; **11/34 ainda sem a funcionalidade específica comprovada**. Esta contagem é *por entrada documental* (há duplicatas temáticas); não é porcentagem de código, de produto nem número de sistemas independentes. Uma entrada classificada como parcial pode ter componente funcional e testes aprovados, mas ainda faltar algum gate.

Legenda: **PARCIAL** = código, integração local ou base preexistente, mas critérios de aceite não fechados; **NÃO DEMONSTRADO** = função específica do CoS não localizada/ligada a fluxo real no escopo examinado. Não equivale a provar ausência absoluta em todos os projetos externos.

## Cobertura das 13 frentes principais

| ID | Frente original | Verificação atual | O que falta para aceite |
| --- | --- | --- | --- |
| G01 / P0 | MCPB: instalar/autorizar/atualizar/remover | **PARCIAL**: import ZIP seguro em `sentra_mcp/services/plugin_bundles.py`, Canvas e catálogo SQLite; `PluginWorkerHost` existente separado | Ativação de bundle staged sob WorkItem/Operation/grant, dependências, stdio/HTTP, OAuth, health/restart, revogar/desinstalar, conflitos globais inclusive providers desabilitados e limite de schema total |
| G02 / P0 | Catálogo real de modelos por conta/effort/Automatic | **PARCIAL**: `sentra_cli/repl.py` tem `/model`, `/effort` e valida catálogo Gateway; `Canvas.model_catalog` | Evidência Web de conta/picker/effort e nonce/generation; estados unknown/pending/ready/unavailable e Automatic (sem picker); troca de conta, concorrência, cancelamento e desaparecimento de modelo |
| G03 / P0 | Compact & Resume entre conversas A→B | **PARCIAL**: `session_continuations` + Control Plane prepare/commit/reconcile/cancel, checkpoint fixado e CAS na rebind local; testes locais | Handoff Web real em fases open/summary/claim/preflight/commit/publish/abort, contexto entregue ao novo chat, mesma identidade Run/WorkItem/worker/grants e teste de falha por fase |
| G04 / P0 | Outbox e recibos de mensagens **ChatGPT Web** | **NÃO DEMONSTRADO**: há journals de CLI/provedor/ConPTY e receipt de handoff entre agentes, mas não comprovam envio ao composer ChatGPT Web | Estados not_sent/pending/unconfirmed/sent por mensagem e geração; ownership exato, reload/crash/resposta perdida sem duplicação |
| G05 / P1 | Goal/Loop e health/GC de workers | **PARCIAL**: governo de agentes/WorkItems, TaskRuntime, budgets e cronologia próprios | Adaptar fechamento guiado por recibos, worker health/queue/limites/GC, loop limitado sem cobrança extra involuntária, E2E stop/cancel |
| G06 / P1 | exec_command/write_stdin persistente | **PARCIAL**: ConPTY, agentes CLI e operações existentes; receipt no handoff | Paridade verificável de API de terminal, head/tail, truncation, stdout streaming, ownership e encerramento apenas do subprocesso autorizado |
| G07 / P1 | Skills SKILL.md com versões | **NÃO DEMONSTRADO** | Importação controlada, hash/revisão imutável, registro central, leitura por ACL, ativação vinculada a WorkItem; skill não cria grants |
| G08 / P1 | API local: leitura separada de ações opt-in | **PARCIAL**: Canvas HTTP usa bearer, Host/Origin, limites e confirmações específicas | Política adicional de consentimento por classes read/action, actions default-off, rate/deadline/paginação e E2E |
| G09 / P1 | Setup/Doctor/repair completo | **PARCIAL**: Tunnel/MCP onboarding, evidências locais, status do plugin no Canvas | Provas independentes da instalação no ChatGPT, extensão pareada, modelo real, refresh remoto, reparo pós-restart e instalação limpa |
| G10 / P1 | CodeMirror/PDF/diff e painel de arquivos | **NÃO DEMONSTRADO** como editor/preview integrado exigido | Dock discreto com escrita autorizada via Operation/grant e diff/revisão, PDF seguro, arquivos grandes e proteção de paths |
| G11 / P2 | Parser fail-closed de comandos allowlist | **PARCIAL**: policy, filesystem grants e sandbox do SENTRA preexistentes | Paridade/fixtures do parser de invocações CoS sem tratar cwd como isolamento, filhos/quoting Windows e fencing no efeito |
| G12 / P2 | Observabilidade Web/extension | **NÃO DEMONSTRADO** para origem exata da página: Edge/captura de túnel já existem | Coleta segura de conversa/request ID, lifecycle de aba, geração, aprovação pendente, troca de perfil e compatibilidade DOM sem cookies |
| G13 / P2 | Config search, docks, a11y, reduced motion, E2E visual | **PARCIAL**: React Flow/Radix, painéis e colaboração com testes próprios | Busca de configurações, persistência/teclado/reduced motion por tela, DPI 100/125/150% e perf/regressão WebView2 |

## Critérios que nenhum resultado unitário, sozinho, comprova

- Identidade de mensagem MCP da mesma conversa Web, vinculada por `x-request-id` + `message.metadata.request_id`, transportada por origem autenticada; confiança **não** cria grant.
- OAuth, plugin instalado e schema atualizado **dentro da conta do usuário** não decorrem de uma chamada MCP local nem de túnel operacional.
- Receber texto em ConPTY ou concluir um WorkItem não prova que o ChatGPT Web recebeu e persistiu uma mensagem.
- Handoff local não faz o segundo chat existir nem injeta contexto/estado nele.
- Build do Canvas não comprova UX 100/125/150%, instalador limpo, Authenticode ou extensão consentida.


## Cobertura das 21 subfrentes da segunda auditoria

| ID | Subfrente | Verificação | Bloqueio específico restante |
| --- | --- | --- | --- |
| A01 | Correlação exata request MCP → conversa ChatGPT | **PARCIAL**: `ChatAccessService.bind_verified_request` persiste unicidade por principal/request ID; `ToolPolicyProxy` verifica policy antes da tool | **Ausente coletor autenticado** que prove que request ID veio da metadata daquela conversa/aba/conta; colisão e troca de perfil E2E |
| A02 | Bloquear ferramentas por chat | **PARCIAL**: bloqueio persistente, modal e enforcement por request ID atribuído | Chamada sem origem continua permitida fora do modo estrito (desligado por padrão); não alegar bloqueio global em chamadas não atribuídas |
| A03 | ChatTrust / strict default deny | **PARCIAL**: revisões, trust/block, strict mode e filtro central | Sucessor Web provado e política herdada apenas após handoff validado; a rebind local atual não propaga confiança externa |
| A04 | WAITING_CHATGPT_USER_APPROVAL | **NÃO DEMONSTRADO** | Observação do cartão de aprovação do ChatGPT e bloqueio de auto-reload/reenvio enquanto humano decide |
| A05 | Prova durável de plugin e túnel na conta | **PARCIAL**: `ConnectorProof` registra chamada MCP autenticada por fingerprint do túnel | CHATGPT_APP_OBSERVED, TOOLS_AUTHORIZED, VERSION_CURRENT da conta/cliente verificados externamente, troca de perfil/reboot |
| A06 | Atualização de schemas MCP no ChatGPT | **PARCIAL**: SHA-256 local do `MCPServer`, comparação com assinatura observada na última chamada autenticada, aviso Canvas | Não existe refresh remoto comprovado, grace/debounce/retries/failure recovery, tools/list do cliente e cache do ChatGPT |
| A07 | Superfícies MCP core/desktop/plugins | **PARCIAL**: `enabled_surfaces`, ToolPolicy e catálogo local | Exposição dinâmica mínima por provider/workspace, isolamento de namespace e tests para nomes conflitantes inclusive desabilitados |
| A08 | Code Mode QuickJS WASM isolado | **NÃO DEMONSTRADO** | Compositor WASM com CPU/memória/tempo/call caps, sem IO privilegiado e cada tool subordinada a grant/OperationRequest |
| A09 | BrowserProof: extensão instalada/pareada/logada | **NÃO DEMONSTRADO** | Prova de extensão, browser/profile-ID, login prévio, revogação e reparo — enrollment de túnel não equivale a isso |
| A10 | API local leitura/action opt-in | **PARCIAL**, mesma capacidade de G08 | Duplo consentimento e ações default-read-only, quotas/paginação por permissão |
| A11 | Índice incremental do histórico de mensagens | **PARCIAL**: `ConversationStore.search_page` pesquisa conversas CLI do owner/workspace e Canvas exibe trechos | Atualmente varre/descriptografa até 2.000 mensagens ou 2s, **não há índice incremental**, busca Web, deep link e lifecycle de índice |
| A12 | Anexos/imagens Web independentes e por chunks | **NÃO DEMONSTRADO** | API de anexos por identidade de mensagem/WorkItem/ACL, quota, upload Web verificado, receipt e não encaminhar a peers sem autorização |
| A13 | Streaming Web por message_id e revisão | **NÃO DEMONSTRADO** | Frames parciais, virtualização/overflow e revisões vinculadas a IDs estáveis do browser no storage SENTRA |
| A14 | Uso, limites e reset observados na conta Web | **NÃO DEMONSTRADO** | Observações reais separadas do ledger de tokens/budget, com identidade da conta, frescor e estados de incerteza |
| A15 | Diagnóstico exportável anonimizado | **PARCIAL**, com **redação local implementada**: `shareable_report` usa allowlist e CLI mantém `--internal` separado | Preview de export no Canvas e teste integrado da UX de compartilhamento e exclusão/retention |
| A16 | Resumo de chamadas de ferramentas com evidência | **PARCIAL**: operações/artifacts e receipts nativos | Projeção consistente de exit code, diff, hits e owner da chamada assíncrona no Canvas/CLI |
| A17 | GC por ownership de workers e terminais | **PARCIAL**: gerenciamento de processos, leases e reconciliação próprios | Política explícita de idle/owner/deadline, crash/UNCERTAIN, sem terminar ConPTY do usuário ou outro WorkItem |
| A18 | Git revisions, diff visual e watcher | **PARCIAL**: `RepositoryService`/patches/git já presentes | Watcher limitado/debounce, visualização de mudanças externas e editor/diff revisionados no Canvas |
| A19 | Updater staged e coordenação de dependências | **PARCIAL**: updater Windows com verificação de integridade/autenticidade já existente | Orquestração app + extensão + Web Models + schema MCP, compatibilidade e rollback E2E sem matar ConPTY |
| A20 | Markdown export de resposta/sessão | **PARCIAL**, com **export de conversa CLI implementado**: Canvas exporta até 1.000 mensagens e 2 MiB | Export por resposta, overflow, proveniência Web, redação opcional e revisão da saída |
| A21 | Git-pinned Skills e recomendadas | **NÃO DEMONSTRADO** | Import SHA fixado, limites de repo/arquivos, consentimento, update/revoke, ACL e nenhuma concessão automática de grants |

**Soma documental:** G01–G13: 9 parciais + 4 não demonstradas; A01–A21: 14 parciais + 7 não demonstradas. A15 e A20 têm função local efetivamente implementada, porém não satisfazem *todo* o requisito original. A matriz não conta duas vezes funcionalidades como duas implementações reais.


## Lacunas transversais identificadas pela verificação

1. **Namespace global de plugins:** o limite de 256 métodos em `PluginWorkerHost._method_descriptors` é *por handshake/worker*, não demonstra a propriedade do CoS de recusar colisões entre todos os provedores, inclusive desabilitados, nem o teto de 250.000 bytes de schema exposto. O importador MCPB aceita manifest.json com name/version para stage, não valida ciclo operacional completo de manifesto/instalação/escopo antes de ativação (pois nunca ativa).
2. **Continuação incompleta por desenho:** os métodos `prepare_chat_continuation`, `commit_chat_continuation` e `reconcile_chat_continuation` só alteram estado autoritativo *local*. Não há produtor Web de sucessor, preflight no ChatGPT, transmissão do resumo, pin do WorkItem ou publicação na UI. Ainda não há equivalência ao protocolo completo do CoS.
3. **Provas diferentes não podem ser fundidas:** `ConnectorProof.record_tool` é um sinal de MCP alcançável; a detecção de mudança de `schema_sha256` é um sinal do servidor **local**. Ambos deixam plugin/autorização/cache da conta ChatGPT como `unverified`. O fingerprint usa introspecção `_tool_manager` privada do SDK e captura falhas sem travar o servidor; precisa validação de compatibilidade em integração com SDK real.
4. **Busca não é índice:** `ConversationStore.search_page` descriptografa mensagens no momento da consulta, com orçamento `max_scan=2000`/`budget_seconds=2`. Isso é apropriado para busca inicial local, mas não implementa índice incremental nem pesquisa do histórico ChatGPT Web.
5. **Aprovação humana Web:** o consentimento do próprio SENTRA para executar tarefas não substitui observação de cartão/estado de aprovação da página ChatGPT, que requer pausa sem retry.
6. **Consentimento API:** bearer, Host/Origin, corpo limitado e confirmações em rotas específicas já são bons controles, mas não constituem a política global dupla (read/action) proposta para uma interface externa de automação.
7. **Aceite por requisito:** nenhum dos 34 tem demonstração de E2E integral com contas Web, extensão e plugin reais autorizados, Setup/MSI instalados e workflow completado. Os casos exclusivamente locais (por exemplo redaction/export) podem ser promovidos separadamente como features locais, desde que os limites sejam documentados.
8. **Proveniência e política:** preservar MIT/notices de toda derivação e nunca copiar cookies, Shell sem sandbox, Electron concorrente, gravador indiscriminado ou autorização por mero status `trusted`.

## Sequência para atingir cobertura real, sem duplicar o SENTRA

| Ordem | Entrega integrada | Bloqueio removido | Prova de aceite |
| --- | --- | --- | --- |
| 1 / P0 | Correlação Browser ↔ MCP, BrowserProof, ApprovalWait e ChatTrust | A01–A05, A09, G12 | Duas abas, troca de conta, conflito x-request-id, botão bloquear funcionando em ferramenta real, cartão humano pendente sem reenviar |
| 2 / P0 | Lifecycle MCPB completo e PluginRefresh | G01, A05–A07 | Um stdio e um HTTP autorizados, instalação/revogação/restart/OAuth, colisão namespace/schema size, atualização confirmada na conta |
| 3 / P0 | Conta/modelos reais + outbox Web + Compact&Resume ponta a ponta | G02–G04, A12–A14 | Free sem picker → Automatic; envio/reply crash-safe; mesma identidade Run/WorkItem, sem executar tool duplicada ao trocar conversa |
| 4 / P1 | Skills/Git/CodeMode/editor/PDF/diff e API action opt-in | G07–G08, G10–G11, A08, A10, A18, A21 | Grants em cada efeito, SHA fixado, edições com revisão, sandbox sem IO privilegiado, segundo consentimento obrigatório |
| 5 / P1/P2 | A11/A15/A16/A17/A19/A20, UX, terminais e liberação | G05–G06, G09, G13 e subfrentes restantes | Busca Web/index/limpeza, evidências por tool, ownership GC, updater coordenado, DPI/teclado, instalação limpa e rollback |

## Estado de testes e distribuição no momento desta auditoria

- Relatório anterior documenta **1.991 passed, 37 skipped** na última suíte unitária completa, executada **antes** das novas alterações locais de continuação/fingerprint (ainda sem commit).
- Após essas alterações, foram vistos **43 testes direcionados** aprovados, mais **13** de Canvas/MCPB/namespace aprovados em rodada separada. Esses grupos não devem ser apresentados como suíte integral atual.
- Build React/Vite foi concluído e assets gerados; warnings de chunks/scripts permaneceram. Não há prova de executável Windows/Setup/MSI/Authenticode e instalação limpa correspondente ao código mais recente.
- `git status --short` confirma alterações locais e arquivos novos ainda não commitados, inclusive este relatório. O clone upstream permanece em `151e7ef`. Esta auditoria **não alterou código de produção**.

**Decisão:** não promover o total a implementado, homologado ou produto fechado. A cobertura do documento foi agora *conferida e rastreada*, mas não *executada integralmente*. O próximo ganho prioritário está no elo verificável navegador → requisição MCP → política por chat → processo/WorkItem autorizado → recibo, seguido da ativação real de MCPB.
