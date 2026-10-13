# SENTRA — correções solicitadas na interface e capacidade de arquivos (2026-10-11)

## Evidência do usuário
Na conversa do Dot `testegpt6`, modelo `sentra/chatgpt-web/gpt-6`, o agente respondeu que não recebeu `machine_list` nem `machine_execute` e não criou/escreveu/leu/editou/excluiu o arquivo de teste no workspace Oxta. Isto é um relato da sessão, não prova de falha de autorização.

## Inspeção estática do checkout atual
- `sentra_canvas/desktop_ui/src/shell-bridge.js` já permite `machine_list` e `machine_execute` como ações do bridge.
- `sentra_canvas/desktop_ui/src/shell-machines.jsx` chama `machine_list` e usa `machine_execute`; `shell-code.jsx` usa `machine_list`.
- `sentra_canvas/service.py` implementa `machine_list` via `_machine_service().task_catalog(workspace_id=ws, agent_ids=agents)` e inventory filtrado pelas capabilities do WorkItem; `agent_control` reconhece `machine_list` e `machine_execute`.
- Portanto, a ausência das ferramentas **na conversa do Dot** pode ocorrer entre registro/exposição do catálogo de ferramentas do runtime conversacional, associação agent_id/workspace/WorkItem e grants da sessão, e não necessariamente na API de máquinas da UI.
- `sentra_canvas/desktop_ui/src/shell-app.jsx` compõe os cards em `dotCard`, header `shell-wordmark` hoje com texto antes da imagem; CSS em `desktop.css` usa `shell-dot-card`, `shell-dot-avatar`.
- Checkout compartilhado contém muitas mudanças não commitadas de outras frentes. Não editar código alheio nem realizar QA antes do freeze coordenado.

## Entrega de implementação para os respectivos responsáveis

### Nexo + Pacto + Codex principal — execução dos arquivos na conversa
1. Inventariar cadeia real `message_send` => dispatcher Dot => catálogo de ferramentas => `agent_control`/ControlPlane. Distinguir ferramentas do renderer e ferramentas disponíveis ao LLM.
2. Expor ao Dot apenas ferramentas tipadas e autorizadas por conversação/WorkItem, com workspace resolvido pelo servidor; `machine_list` deve explicar `no eligible WorkItem`/grant ausente, não simular sucesso.
3. Implementar caminho completo criar/escrever/ler/editar/excluir via executor real ou ferramentas de arquivo apropriadas; para mutações, request_key idempotente e receipt durável, aplicação sem reexecução de estado UNCERTAIN.
4. Emitir estados explícitos na UI: indisponível; solicitando aprovação; autorizado; executando; confirmado; falhou; incerto. Nunca afirmar escrita concluída sem leitura/receipt.
5. Preparar teste hermético com criação, duas leituras, alteração e exclusão no workspace temporário autorizado; negar traversal, outside-workspace, ausência de grant e WorkItem errado. Deferir execução de QA conforme coordenação.

### Prisma — interface
1. Aumentar espaçamento real entre mascote do Dot e o bloco textual no card, incluindo título com nome comprido e zoom; evitar sobreposição com avatar 3D.
2. Adicionar botão X visível e acessível ao diálogo Novo Dot, mantendo controle de minimizar existente e comportamentos de Escape/foco.
3. Exibir avatar/mascote do Dot à esquerda do respectivo nome no cabeçalho de cada resposta, com identidade de Dot persistida por mensagem, não inferida do último Dot selecionado.
4. Exibir indicador animado de processamento associado à mensagem pendente desde dispatch até estado terminal, harmonizado às variáveis CSS do tema light/dark; respeitar prefers-reduced-motion e aria-live.
5. Mudar `shell-wordmark` para ícone SENTRA à esquerda e texto à direita; manter nome acessível e área clicável.
6. Garantir loading estados `queued/dispatched/waiting_approval/uncertain` distintos; nunca indicar progresso eterno após erro.

### Vitra — CLI
Aproximar shell/REPL do OpenCode visto no screenshot: identidade e título discretos e centralizados, caixa de input com borda esquerda de destaque, linha de modelo/provedor/esforço, hint de atalhos e agentes, modo dark minimalista e foco no prompt. Preservar compatibilidade Windows/terminal sem VT, contraste, seleção de modelo real, streams, comandos existentes, histórico, keyboard shortcuts e acessibilidade. Não copiar código de terceiros sem avaliação de licença.

## Critérios de aceitação futuros
- Depois do freeze autorizado, repetir na mesma superfície real `testegpt6` ciclo `sentra_teste.txt`: create => read => edit => read => delete => absence, com logs sem credenciais e ID de WorkItem/Operation/receipt.
- Inspecionar visualmente dark/light, teclado, redução de movimento, diferentes tamanhos de tela; CLI em terminal real.
- Não declarar concluído sem retorno observado. Esta nota é **handoff**, não implementação/homologação.

## Restrições de coordenação
Documento `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md` define donos: Prisma (UI), Nexo (ControlPlane), Pacto (exposição e consentimento), Vitra (CLI), Codex principal (bridge/serviço). Preservar as alterações em progresso e o requisito da implementação antes de validação.

## Implementação adicionada ao checkout compartilhado (2026-10-11)

Implementado no código-fonte, ainda **não homologado em execução real**:
- `sentra_executors/workspace_files.py` — máquina UTF-8 com capabilities distintas `workspace:file.read/write/delete`, validação de caminhos relativos, limite 1 MiB, SHA-256 CAS para edit/delete, publicação atômica, checkpoint físico e negação sem grant.
- `sentra_runtime/machine_host.py` — registro/restore persistente da máquina via `CentralExecutorFactory`/ControlPlane, sem grants automáticos, descoberta de WorkItems e conversas autorizadas.
- `sentra_canvas/service.py`, `sentra_canvas/__main__.py` — configuração autenticada com aprovação, WorkItem e Grants vinculados a Dot/projeto/conversa, descoberta filtrada, prevenção de autorizações duplicadas após ACK perdido, revogação explícita.
- `sentra_cli/agent.py`, `sentra_cli/canvas.py` — instruções reais para diretivas CANVAS e etiqueta de observação única para duas leituras no mesmo turno.
- `sentra_canvas/desktop_ui/src/shell-conversation.jsx` — botão Autorizar arquivos, Testar arquivos (ciclo completo de 7 operações via bridge/máquina do projeto), Revogar arquivos; recibos por etapa, interrupção de efeito incerto, mascaramento sem inferir sucesso; identidade do Dot no cabeçalho das respostas; indicador animado com status e redução de movimento.
- `sentra_canvas/desktop_ui/src/shell-app.jsx` e `desktop.css` — logomarca à esquerda, novo espaçamento do Dot, X visível no Modal existente; CSS ligado a temas.
- `sentra_cli/repl.py` — início e entrada minimalistas, layout inspirado no OpenCode, preservando comandos e status operacional.
- `tests/test_workspace_files_machine_20261011.py` — casos herméticos de lifecycle, CAS, traversal, ausência de grant, a executar depois do freeze.

### Bloqueio real específico de GPT Web
A seleção do modelo `sentra/chatgpt-web/gpt-6` **não define, sozinha, a rota física**: em `CanvasShellRuntime._execute_locked`, o turno usa a CLI com diretivas CANVAS quando **não** há anexos nem vínculo de conversa remota no relay; usa `ShellWebRuntime.execute -> dispatch_shell_turn -> relay browser` quando há anexos ou vínculo remoto prévio. A rota de relay obtém resposta textual do ChatGPT Web, **não instancia a CLI local e não expõe ferramentas nativas do host automaticamente**. A rota CLI pode executar diretivas CANVAS emitidas como texto pelo provedor, desde que o WorkItem/Grant já seja válido; ainda é preciso comprovar se o provedor emitiu essa diretiva, e não apenas respondeu em prosa. A implementação acima fornece execução autorizada **pela própria interface** e suporte aprimorado a diretivas CANVAS **na rota CLI**, mas não converte a rota Web relay em um provedor com chamadas nativas de ferramenta. Para fechar esse último gap, coordenar com Rastro/Brisa/Pacto a entrega bidirecional de chamadas tipadas, grants e receipts, ou habilitar o plugin SENTRA autenticado na conta escolhida, com comprovação real. Não executar diretivas retiradas de texto remoto como efeitos físicos sem canal tipado, validação host-owner, fence e idempotência. Não declarar resolvido o caso GPT Web até E2E remoto verificar.

### Inspeções realizadas
O parser `ast.parse` aceitou os módulos Python alterados, incluindo novo teste. A biblioteca Babel/TypeScript parser não está instalada naquele ambiente para inspeção JSX independente; a validação frontend/integração ficou para o freeze coordenado. Nenhum teste real de arquivos em Oxta, build, instalação, commit, push ou migração SQLite foi executado aqui.
