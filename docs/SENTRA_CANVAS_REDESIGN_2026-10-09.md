# Redesenho do SENTRA Canvas — 9 de outubro de 2026

Implementação de design concluída no escopo autorizado. A aceitação funcional integral permanece pendente da integração dos agentes. Nenhum `pytest`, `node --test`, typecheck ou suíte E2E foi executado nesta etapa.

## Arquivos entregues

| Arquivo | Mudança |
| --- | --- |
| `sentra_canvas/static/native.css` | Estilos consolidados do canvas, sidebar, nós, inspector, modais, busca, terminais, máquinas, workflows e Central. |
| `sentra_canvas/static/native.html` | Toolbar agrupada com rótulos, nomes acessíveis, `show-center`, `/center-panel.js` antes de `/native.js` e `/remote-panel.js` antes de `/machine-panel.js`. |
| `sentra_canvas/static/app.css` | Console de workspaces alinhado à mesma paleta, hierarquia, formulários, sessões e responsividade. |
| `sentra_canvas/static/index.html` | Rótulos persistentes nos formulários e ajuste das mensagens de navegação. |
| Este relatório | Decisões, limites, integração e critérios de aceitação. |

Nenhuma escrita em `native.js`, `app.js`, `machine-panel.js`, `workflow-panel.js`, `center-panel.js`, backend, runtime, executores, testes ou clones. Nenhum commit, stage ou reset. O checkout já continha alterações de outros agentes; esta entrega foi feita sobre esse conteúdo, sem restaurar arquivos a partir do Git.

## Direção e decisões

- Console de engenharia escuro: fundo `#11151a`, painéis `#1a2027`, superfícies `#202831`, texto `#e8edf2`, secundário `#a4afbb` e acento SENTRA `#8cd4c4`.
- Fontes do sistema: Segoe UI Variable / Segoe UI / system-ui. Código e terminais usam Cascadia Mono / Consolas. Nenhuma fonte externa, CDN, biblioteca ou dependência adicionada.
- Espaçamento consistente, bordas de 1 px, cantos de 6–8 px e sombras restritas a nós, overlays e feedback. Gradientes decorativos, blur e ampliação da toolbar sob o mouse removidos do CSS.
- Grid de fallback com pontos espaçados a 40 px e opacidade de 0,18. Canvas fractal preservado com opacidade de 0,16. O motor JS continua existente; isto reduz ruído visual, não afirma eliminar seu custo de renderização.
- Sidebar de 248 px, filtro com controle explícito de criação, seleção legível, lista de workspaces e sessões com rolagem independente. Rodapé permanece acessível. A lista de workspaces ocupa até 32% quando existem sessões; sem sessões, usa a área livre.
- Identificação do workspace e busca/atividade ficam na primeira linha. Toolbar ocupa a segunda linha, com grupos de seleção, criação, conexão/navegação e operação. Todos os controles têm texto visível e/ou nome acessível e título.
- Toolbar tem rolagem horizontal quando não cabe, inclusive com inspector aberto. O foco de teclado pode alcançar os botões além da área visível. Nenhum controle é removido em telas pequenas.
- Área do viewport começa abaixo dos 112 px de cabeçalho e termina antes dos 52 px de rodapé. Isto evita que ferramentas e status cubram os nós. Em telas estreitas, o rodapé divide status e zoom em duas linhas.
- Inspector de 408 px em telas amplas; até 432 px sobreposto à direita abaixo de 1180 px, limitado à largura disponível. Cabeçalho sticky, fechamento acessível, abas com seleção explícita e textos/identidades selecionáveis.
- Nós têm cabeçalho de 38 px, título de 13 px, tipo legível, seleção/foco com borda e ação de expansão preservada. Estado do terminal continua vindo do runtime, acompanhado de texto; cor não substitui a informação.
- Terminais mantêm o fundo `#13181e`, o mesmo container xterm e a fonte de 13 px configurada no JS existente. A escala do mundo, larguras/alturas dos nós e quantidade de linhas/colunas permanecem sob controle do grafo e do FitAddon.
- Modais e busca têm largura finita, limite de altura, rolagem, foco visível e ações legíveis. O título, kicker e fechamento do modal agora ocupam posições claras em grid.
- Dashboard usa campos com rótulo persistente para nome, shell, agente, modelo, função, equipe, instrução e busca de eventos. As colunas passam de três para duas e uma conforme a largura. Seletores, defaults, validações HTML e IDs permanecem existentes.
- Texto estático “Conectado ao runtime local” foi substituído por “Runtime local”, sem afirmar conexão verificada. “Sessões ativas” passou a “Sessões do workspace”, pois o dashboard também mostra sessões interrompidas. Indicadores estáticos de localização usam cor neutra.

## Máquinas, workflows e Central

Os componentes são estilizados por suas classes e elementos sem mudar a geração de DOM ou os handlers:

- `.machine-panel`: cartões por formulário/seção, campos com boa largura, textarea redimensionável, checkboxes proporcionais, ações com contraste, orientação textual e resultados selecionáveis.
- `details` / `summary`: disclosures com borda, título legível, foco e separação visual quando abertos. Diagnóstico e evidência continuam expansíveis.
- `fieldset` / `legend`: etapas do workflow e revisões de plano com separação clara, legendas e espaçamento entre campos. Os campos que o JS marca com `hidden` permanecem ocultos; CSS não força sua exibição.
- `.machine-result`: conteúdo preservado, quebra para identidades/caminhos longos, fonte monoespaçada e rolagem própria até 340 px. `.machine-elements` organiza elementos observados e suas ações.
- `.remote-session-list` e `.remote-session-status`: sessões remotas em linhas com quebra, campos e resultados com largura inteira e rolagem própria. Status remoto tem aparência neutra; cadastro, peer verificado e desktop disponível precisam ser distinguidos pelo texto real do componente. Não há inferência de disponibilidade a partir do cadastro ou aparência verde aplicada automaticamente a uma sessão.
- `.center-panel`, `.center-stats`, `.center-stat`, `.center-section`, `.center-list`, `.center-row`, `.center-state`, `.center-empty`, `.center-actions`, `.center-pagination` e `.center-note`: resumo em duas colunas, listas legíveis, identidades que quebram linha, ações que podem envolver e paginação separada.
- A Central utiliza `data-state` já produzido pelo componente para destacar execução/validação, conclusão, incerteza/bloqueio e falha. Estados não conhecidos continuam neutros. Nenhum contador, custo, budget, status ou resultado é gerado pelo CSS/HTML.
- Planos e evidências dentro de uma linha da Central ocupam sua largura inteira; campos desabilitados apresentam aparência distinta sem desaparecer.

## Contratos preservados e integração

A revisão estática comparou os HTMLs recebidos no início com os entregues: **102 IDs originais preservados**, 103 IDs ao final, único acréscimo `show-center`, nenhum ID duplicado em cada documento e nenhum script original removido. `/workflow-panel.js` e `/remote-panel.js` permanecem antes de `/machine-panel.js`; `/center-panel.js` está imediatamente antes de `/native.js`. `/app.js`, xterm, FitAddon, física de cabos, fractal grid, colaboração e graph-view permanecem incluídos.

O JS existente foi lido para conferir delegação de eventos, `data-tool`, containers PTY, expansão de terminal, projeção/culling e uso de `getBoundingClientRect()` do viewport. CSS não define `zoom`, não escala fontes xterm, não fixa dimensões persistidas dos nós e não altera os offsets das portas. A transformação de `world`, SVG de conexões e estados `sidebar-collapsed`, `terminal-expanded`, `expanded`, `hidden`, `selected` e `aria-pressed` permanecem suportados.

O canvas clonado encontrado é **XYFlow**, em `third_party/xyflow`, com exemplos React e Svelte e licença MIT (copyright webkid GmbH). Foram consultados `packages/system/src/styles/base.css`, `style.css`, os estilos do exemplo DragNDrop, DevTools e `examples/react/src/index.css`. A avaliação nesta entrega foi baseada nas regras locais de estilo, sem executar ou instalar o clone. Seus padrões úteis são superfícies neutras, bordas de seleção claras, sombra curta e controles de zoom agrupados com divisórias; essas decisões foram adaptadas ao SENTRA, incluindo as divisórias entre botões de zoom. Não foram copiados arquivos, nós fixos de 150 px, assets ou aplicação React/Svelte. Se futuramente se copiar código substancial, manter o aviso MIT junto à cópia. O runtime continua o frontend existente do SENTRA.

**Integração do coordenador:** servir `/center-panel.js`, conectar `show-center` ao componente e servir `/remote-panel.js`, chamado pelo painel de máquinas. Esta entrega já inclui HTML e CSS correspondentes. Não é necessário outro hook JS para aplicar o design.

**Ponto de acessibilidade para o coordenador:** o modal de criação já recebe foco inicial em `native.js`, e a busca possui navegação de foco. Na leitura do modal de criação, não foi encontrada contenção de Tab nem restauração do elemento que o abriu. CSS não implementa focus trap, `inert` no fundo ou restauração de foco. Conferir esse comportamento na aceitação e, se necessário, tratá-lo no arquivo JS sob responsabilidade do coordenador. O botão de sidebar também pode sincronizar `aria-expanded` com seu estado; não foi adicionada uma afirmação estática de estado que ficaria desatualizada.

## Inspeção realizada, sem validação integral

Foi iniciada uma prévia temporária somente de HTML/CSS em loopback, com lista fechada de arquivos estáticos. Scripts foram removidos apenas da resposta de prévia; CSP bloqueou scripts, conexões e envio de formulários. Nenhum asset de produção foi alterado para a prévia, nenhum servidor autenticado do usuário foi acessado e nenhum workspace/processo/agent foi criado.

A ferramenta de navegador do SENTRA rejeitou navegação para rede local conforme sua política. A inspeção foi feita pelo navegador local disponibilizado por CUA, na prévia estática, sem alterar essa política. Foram observados visualmente o shell do canvas, onboarding e formulários estáticos do dashboard em tela ampla, em 1280 × 800, em 1440 × 900 e em 390 × 844. O onboarding e o dashboard foram revelados somente na resposta temporária para inspecionar o HTML existente; nenhum dado ou resultado de execução foi simulado.

A aba temporária foi fechada, o override de viewport foi restaurado e a prévia foi encerrada ao terminar a inspeção.

Em 1440 × 900, a leitura do DOM da prévia registrou viewport com x=248, y=112, largura=1192 e altura=736. A toolbar tinha clientWidth=scrollWidth=1158, portanto todos os grupos cabiam nessa largura. Em 1280 px, a toolbar apresentou rolagem para os controles finais. Em 390 px, o dashboard empilhou seus campos; com sidebar aberta, o canvas fica estreito e o controle existente de recolhimento permite liberar a área de trabalho. O fluxo real de recolhimento depende do JS e não foi executado na prévia.

Uma revisão aritmética da paleta produziu os seguintes contrastes nominais: texto principal/painel 13,93:1; secundário/painel 7,37:1; placeholder/input 6,27:1; foco/input 10,39:1; texto/botão primário 9,71:1. Isso é cálculo das cores declaradas, não auditoria completa WCAG, avaliação de todas as combinações ou prova dos estados renderizados pelo runtime.

`git diff --check` dos quatro arquivos passou sem erros de whitespace; houve apenas os avisos esperados de normalização LF/CRLF. A comparação de IDs/scripts e essa leitura são revisões estáticas, não a bateria de validação solicitada para o fim da integração.

**Ainda não inspecionados com dados reais:** nós ativos, PTY/xterm e fit, inspector preenchido, máquinas, workflows, Central, modais com seus campos dinâmicos, colaboração e erros do runtime. Não se afirma paridade funcional ou aceitação integral a partir da prévia estática.

## Aceitação pendente após integrar todos os agentes

Todos os itens abaixo estão **pendentes**, inclusive os que reutilizam suites existentes. Executar em ambiente local isolado de QA, com dados/arquivos próprios para a validação, após concluir a implementação integral.

| Área | Critério verificável |
| --- | --- |
| Entrada e contrato | `/canvas`, `/native.html` e `/index.html` carregam sob a CSP real; assets retornam sem 404; nenhuma exceção no console; título Windows ausente na rota web e controles presentes no desktop. |
| Navegação | Criar, filtrar e trocar workspace; manter seleção, contagens e sessões reais; abrir visão geral/configurações; recolher/reabrir sidebar com mouse e teclado. |
| Toolbar | Todos os controles são alcançáveis, com labels/títulos e foco visível; controles finais aparecem por rolagem/foco em 1280/1024/768/390 px e com inspector aberto. |
| Grafo | Criar terminal, agente, equipe e nota; mover/redimensionar sem divergência entre cursor e nó; conectar/remover vínculos; pan/zoom/enquadramento/reset; persistência após reabrir. Testar com sidebar aberta/fechada e inspector aberto/fechado. |
| PTY | Uma instância xterm por sessão; digitação, Enter, Ctrl+C, histórico e rolagem; resize correto; ampliar/restaurar e Esc; fonte não escalada por CSS; `/model` e `/effort` continuam usando o terminal real. |
| Nós | Nomes longos, shell/modelo longo, terminal interrompido, agentes sem sessão, referência compartilhada, equipe e nota. Cabeçalho/status não sobrepõem ações; seleção e portas permanecem visíveis. |
| Inspector | Todas as abas e setas/Home/End; textos e identidades copiáveis; ações sem truncamento; rolagem e fechamento sempre acessíveis; largura útil em desktop e overlay dentro da tela estreita. |
| Modais/busca | Criar cada tipo, enviar/cancelar, erro, busy e Ctrl+Enter; foco inicial, Tab/Shift+Tab contidos, Esc e restauração de foco; campos/mensagens longas e viewport de pouca altura; botões permanecem alcançáveis. |
| Máquinas/documentos | Configurar cada recurso integrado, alternar campos condicionais, diagnóstico, experiência, tarefa, navegador e evidência; disclosures, campos e ações legíveis; falha/incerteza não apresentados como sucesso. |
| Sessões remotas | Configurar e consultar Daytona, Guacamole e RustDesk com seus estados reais; listas e evidências acessíveis; distinguir recurso cadastrado, peer verificado e desktop disponível; sessão não assume sucesso/desktop disponível sem evidência do componente. |
| Workflows | Criar etapas de tabela, Excel, PDF, verificação e espera; 1 e 30 etapas; salvar/carregar; iniciar/avançar/consultar; confirmar/cancelar. Campos ocultos continuam ocultos e legendas/ações mantêm hierarquia. |
| Central | Abrir/atualizar, Run/WorkItems/Operations reais, paginação, custos/budgets sem inferir preço desconhecido, evidência e planos. Verificar revisões, etapas bloqueadas, undo/redo e identidades longas. |
| Colaboração | Ativar/desativar, undo/redo, presença e notas; cores/labels não confundem presença com execução ou autenticação; perda de conexão continua usando feedback do runtime. |
| Dashboard | Criação de workspace/terminal/agente/equipe/tarefa, seleções múltiplas, reordenação, refresh e busca de eventos. Nenhum form alterado pelos novos wrappers de label. |
| Responsividade | Capturas em 1920, 1440, 1280, 1024, 768 e 390 px; altura 480 px; zoom do navegador 100/125/200%; sidebar recolhida em telefone; inspector e modal sem saída da área visível. |
| Acessibilidade | Teclado completo, labels no accessibility tree, contraste de cada estado, foco visível, reduced motion, forced colors e leitor de tela. Sinalizações não dependem só de cor. |
| Performance/regressão | Grafo denso com PTYs e culling sem destruir sessões; CPU/FPS e tempo de abertura medidos, sem presumir melhora por reduzir efeitos CSS. |

## Bateria para o coordenador, não executada aqui

A bateria integral do projeto deve ser definida e executada pelo coordenador após a integração de backend, segurança, executores e design. Para esta superfície, incluir as suites já existentes:

- `tests/e2e/test_sentra_canvas_native_ui.py`, `test_native_canvas_interactions.py`, `test_canvas_web_cult_ui.py` e `test_canvas_collaboration_and_culling.py`.
- `tests/e2e/test_sentra_canvas_ui.py`, `test_sentra_canvas_terminal_ui.py`, `test_sentra_canvas_reopen_ui.py`, `test_canvas_governance_ui.py` e `test_canvas_output_validation_ui.py`.
- Testes de integração/unitários de Canvas, máquinas/documentos, workflows, governança e runtime, incluindo os adicionados pelos outros agentes.
- Verificações JS existentes em `tests/js/graph_view.test.cjs` e `tests/js/canvas_cable_physics.cjs`; checks de sintaxe/typecheck/qualidade previstos pelo projeto.
- Checks visuais manuais da matriz acima e cenários ainda sem cobertura automatizada, especialmente PTY em zoom, forms de 30 etapas, Central e foco modal.

Registrar resultados reais, skips, falhas, ambiente e evidências de captura no relatório de integração. Esta entrega termina com implementação de design e critérios prontos; a bateria permanece pendente, conforme a instrução do usuário.
