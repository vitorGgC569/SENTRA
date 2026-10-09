# SENTRA Desktop UI

Superfície React real, materializada em /desktop.html. Direção visual: screenshot Maestri fornecida pelo usuário, com sidebar grafite de 256 px, grid fino, toolbar cápsula flutuante, terminais retangulares pequenos, conexões curvas tracejadas e controles compactos inferiores. O redesign anterior não é a direção aceita; o frontend legacy permanece como fallback existente.

## Build e pins

Na pasta sentra_canvas/desktop_ui, executar npm ci e npm run build.

O build escreve ../static/desktop.html e arquivos em ../static/desktop-assets/. node_modules é ignorado. package-lock.json contém pins transitivos e integridades; manifest.json contém versões e SHA-256; THIRD_PARTY_NOTICES.txt reúne licenças dos pacotes de runtime.

| Pacote | Pin |
| --- | --- |
| @xyflow/react | 12.12.0 |
| React / React DOM | 19.3.0 |
| @radix-ui/react-dialog | 1.2.0 |
| @radix-ui/react-dropdown-menu | 2.1.25 |
| @radix-ui/react-tooltip | 1.3.0 |
| lucide-react | 1.54.0 |
| @xterm/xterm | 6.0.0 |
| @xterm/addon-fit | 0.11.0 |
| Vite | 8.3.4 |
| @vitejs/plugin-react | 6.1.2 |

React Flow foi instalado do registro npm na mesma versão do clone local third_party/xyflow/packages/react. Grafo, handles, resize, pan/zoom, projeção, curvas, Background e MiniMap são componentes da biblioteca. Radix fornece Dialog, portals, focus scope, menus e tooltips; Lucide fornece os ícones SVG. Não se afirma ter instalado um template shadcn completo. O runtime final não precisa de npm, CDN, fontes externas ou internet para renderizar.

## Fontes oficiais pesquisadas

- [React Flow components](https://reactflow.dev/api-reference/components): ReactFlowProvider, Background, Handle, NodeResizer, Panel e MiniMap realmente usados.
- [Custom nodes](https://reactflow.dev/learn/customization/custom-nodes): terminais, referências de sessão compartilhada, agentes, equipes e notas.
- [ReactFlow API](https://reactflow.dev/api-reference/react-flow): viewport, eventos e onlyRenderVisibleElements.
- [NodeResizer](https://reactflow.dev/api-reference/components/node-resizer): resize persistido na API do SENTRA.
- [React Flow UI](https://reactflow.dev/ui): catálogo oficial; ui.reactflow.dev não respondeu no fetch da pesquisa.
- [Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog), [Tooltip](https://www.radix-ui.com/primitives/docs/components/tooltip) e [shadcn Dialog](https://ui.shadcn.com/docs/components/radix/dialog): composição dos overlays; runtime implementado com Radix.
- [Lucide React](https://lucide.dev/guide/react): imports de ícones reais.
- [xterm Terminal API](https://xtermjs.org/docs/api/terminal/classes/terminal/): output, input e lifecycle.

Foi inspecionada a screenshot local codex-clipboard-a814b4e9-9c16-48d8-97d4-04cef8d36aec.png e o clone XYFlow. Nenhum asset proprietário do Maestri foi copiado.

## Arquivos

| Fonte | Responsabilidade |
| --- | --- |
| src/main.jsx | Shell desktop, React Flow, workspace lifecycle, viewport, native controls e bridge de apresentação |
| src/nodes.jsx | Custom nodes, handles, NodeResizer, menus e slots xterm |
| src/terminal-pool.js | Views persistentes por PTY, output por cursor, fila serial de input/resize |
| src/api.js | Bearer privado ao módulo, sessionStorage, remoção do fragmento, API local sem redirects |
| src/dialogs.jsx | Workspace/terminal/agent/team/note/handoff/delegação e ações de recursos |
| src/network-dialog.jsx | Rede, interfaces retornadas, whitelist, CAS, presença e pareamento explícito |
| src/panels.js | Ilha DOM compatível para painéis legacy, detalhes, atividade, registry e contexto do agente |
| src/primitives.jsx / src/context.js | Composição Radix e contexto React |
| src/desktop.css | Nova direção visual desktop |
| public/bootstrap.js | Diagnóstico de falha de carregamento, sem chamadas API ou credenciais |
| index.html / vite.config.js / package.json / package-lock.json / scripts/materialize.mjs | Fonte e build reproduzível |
| ../static/desktop.html | Entrada materializada |
| ../static/desktop-assets/ | desktop.js, desktop.css, bootstrap.js, index.html, manifest.json e THIRD_PARTY_NOTICES.txt |
| evidence/ | Capturas desktop-1440.png, agent-goal-dialog.png e network-dialog.png |

Nenhuma edição de backend, native_app.py, __main__.py, service.py, Core, CLI, interop, executores ou módulos JS legacy nesta nova entrega. Nenhum stage, commit ou reset.

## Contratos e sessões

- Endpoints de produção: /api/workspaces, /api/workspace, /api/graph, /api/terminals, /api/agents, /api/teams, /api/tasks, /api/team, /api/events, /api/models, /api/integrations e operações existentes de terminal/grafo.
- onlyRenderVisibleElements=false mantém os nodes montados ao pan/zoom. TerminalPool mantém uma view xterm por (workspace, terminal ID) fora do ciclo de renderização; não inicia, relança ou fecha PTYs. A identidade agente/terminal compartilhada usa um único slot ativo no agente.
- Expansão registra slot prioritário e move a mesma host/view xterm; ao fechar, ela retorna ao nó. Há um writer serial por PTY nesta superfície.
- Input real usa /api/terminal/input em blocos de até 1024 caracteres Unicode. Falha interrompe o restante daquele envio, sem repetição automática. Resize usa FitAddon e /api/terminal/resize; zoom do grafo não altera a fonte lógica xterm.
- Estado vem do output real. Falha de transporte desabilita stdin e mostra conexão indisponível, sem inventar que o processo encerrou ou está pronto.
- Handoff/delegação preservam request_key e payload exato no retry. Criação sem idempotência não é repetida automaticamente após perda da resposta.
- Notas mantêm rascunho na janela até confirmação; troca de workspace/fechamento pelo controle nativo tentam confirmar notas antes de sair.
- Goal é enviado no POST de agente, limitado a 16000 bytes UTF-8. Inspector lê /api/agent/context e envia expected_revision real ao editar. Modelo/catalogo não atestam autenticação.
- Native controls chamam window.pywebview.api.minimize, toggle_maximize e close; fora de WebView2 ficam desabilitados.

## Painéis e colaboração

A entrada carrega workflow-panel, remote-panel, machine-panel, center-panel, runtime de colaboração, sentra-collab e collaboration-panel em ordem. Não carrega native.js ou app.js.

Inspector mantém os IDs inspector, inspector-title, inspector-label, inspector-tabs e inspector-content. Os painéis de máquinas/Central montam numa ilha que React não reescreve; consultas/avisos são limitados à geração atual.

SentraCollaborationPanel.create recebe a estrutura mutável de apresentação existente. Updates são reprojetados para React Flow. Notas usam o hook textarea existente. A UI não concede execução, não envia segredos ao CRDT e não afirma ligação com o novo transporte de rede.

## Rede

- GET /api/center/network lê configuration/revision, local_interfaces, presence e collaboration_transport_ready.
- POST /api/center/network envia configuração explícita do proprietário com CAS: enable, adaptador, IPv4 local, whitelist, porta, label e opcionalmente chave fornecida para ingressar em projeto pareado.
- Interfaces detectadas vêm somente da API. Seleção não comprova peer autenticado e não executa scan. Entrada manual permanece presente.
- Whitelist vazia é válida desativada; enable exige interface local e ao menos um IP permitido. Sem IPs reais não é declarado sucesso de rede.
- IP/porta são rotulados como Configuração. Pares vêm exclusivamente de presence.peers; running descreve o serviço de presença e collaboration_transport_ready=false informa transporte ainda não ligado.
- Atualizar presença não troca a revisão base do formulário sem reload da configuração; preserva CAS contra edições concorrentes.
- Código de pareamento chama POST owner-only /api/center/network/pairing somente por clique, após configuração salva. Chave fica no estado temporário do diálogo e no campo revelado; pode copiar/ocultar. Não vai para goal, modelo, URL, sessionStorage, relatório, logs ou artifacts.
- Nenhum IP, peer, grant, firewall, scan ou status operacional foi fabricado.

## Inspeção e correção da tela preta

Build materializado com npm install/build. Nenhum pytest, node --test, typecheck ou suíte E2E executado. Avisos de classic scripts não bundled são esperados: módulos legacy externos continuam locais. Há aviso de chunk JS >500 kB: aproximadamente 896 kB JS / 263 kB gzip, 40 kB CSS / 8 kB gzip.

A tela preta foi causada pelo import Lucide Map ocultando o construtor JavaScript Map. Corrigido para MapIcon. ErrorBoundary e bootstrap agora informam falhas de carregamento/renderização.

O navegador interativo retornou ERR_BLOCKED_BY_CLIENT para loopback; nenhuma proteção foi alterada. Computer Use capturou a janela vazia, depois foi interrompido pelo usuário com Esc. A investigação seguiu por inspeção de software via Playwright headless em perfil temporário, usando o mesmo desktop.html do broker de avaliação 56000.

read_endpoint leu .tmp/integral-incorporation/desktop-native-review privadamente, sem imprimir/gravar bearer. Após correção, a inspeção registrou **3 nodes, 3 xterms, inspector fechado, fragmento removido e nenhum pageerror** em 1440 × 900. Foram usados os três PowerShells e o layout existentes, sem recriar recursos ou iniciar modelos. Os modais agente/Rede foram abertos e cancelados sem submit.

Objetivo apareceu no modal de agente. Rede abriu, mas o processo de avaliação ainda retornou **route not found** para a API incorporada depois do startup. A UI mostrou esse erro e desabilitou save; não simulou configuração/presença. Essa limitação está na captura de Rede.

A prévia anterior, temporária, tinha três CMDs próprios e foi encerrada. A instância antiga e a janela de avaliação do coordenador não foram encerradas.

**Reload necessário:** a janela aberta conserva o bundle anterior até recarregar a superfície. Assets corrigidos exigem reload sem recriar PTYs. Python não faz hot-reload do backend: incorporação da nova API Rede no broker permanece a cargo do coordenador, preservando as sessões.

## Aceitação integral pendente

Esta inspeção confirma renderização/layout e a correção observada; não substitui a bateria integral para depois da integração.

1. WebView2: reload, minimizar/maximizar/fechar, drag da janela, DPI e janela mínima; captura nativa após reload.
2. Todos os flows de workspace, criação, pastas, registry, terminal/agent/team/note/link/handoff/delegação e ações de recursos.
3. Um xterm/writer por PTY sob pan/zoom/resize/expansão; histórico, cursor/truncamento, Unicode, Ctrl+C, reconexão e ausência de relançamento.
4. Notes/races: autosave, perda de rede, rascunho, troca rápida de workspace, concorrência e polling durante resize.
5. Teclado/foco Radix, menus, reduced motion, leitor de tela e acessibilidade dos custom nodes.
6. Máquinas/remote/workflow/Central com dados reais e falha/incerteza; cadastro/peer verificado não equivale a desktop disponível.
7. Goal: limite de bytes, revisão real, CAS concorrente, herança/admissão do backend.
8. Rede em broker atualizado: disabled com lista vazia, interfaces detectadas ou vazias, entrada manual, CAS concorrente, reveal/copy owner-only e ausência do segredo em consultas normais/agentes.
9. Whitelist/UDP/porta comum e pares somente com IPs fornecidos. Ainda não há IPs para QA de rede real. RPC de trabalho/colaboração fica para a integração de transporte.
10. Suites Canvas/governança/workflow/runtime/JS/E2E com resultados reais pass/fail/skip, depois da implementação integral.
