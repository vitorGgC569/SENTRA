# SENTRA Canvas Web — direção visual e paridade funcional

## Objetivo
O **Canvas Web do SENTRA**, acessível em `/canvas` no servidor local autorizado, é a interface principal da orquestração. A integração com Maestri permanece **legada/opcional**. Nenhum ativo ou código proprietário do aplicativo Maestri é copiado.

## Pesquisa Cult UI (8 out 2026)
Fontes oficiais:
- Dock: https://www.cult-ui.com/docs/components/dock
- Halo Card: https://www.cult-ui.com/docs/components/halo-card
- Halo Tabs: https://www.cult-ui.com/docs/components/halo-tabs
- Halo Toast: https://www.cult-ui.com/docs/components/halo-toast
- Halo Search: https://www.cult-ui.com/docs/components/halo-search
- Prompt Composer: https://www.cult-ui.com/docs/components/prompt-composer
- Canvas Fractal Grid: https://www.cult-ui.com/docs/components/canvas-fractal-grid
- Intro Disclosure: https://www.cult-ui.com/docs/components/intro-disclosure
- Setup/compatibilidade: https://www.cult-ui.com/docs/installation

Cult UI publica os componentes como código React + Tailwind + shadcn/ui. O Canvas tem frontend JavaScript/CSS sem React e backend Python, protegido por token local. Para preservar CSP e footprint do EXE, os padrões de interação foram adaptados em **código original**, e não importados como componentes React.

## Implementado nesta iteração
- Visual de superfícies discretas e foco (Halo Card), Dock interativo com ampliação sob o mouse, Halo Toast empilhável e dispensável, Halo Search por nós/comandos com Ctrl+K e botão para limpar.
- Canvas Fractal Grid adaptado em `sentra_canvas/static/fractal-grid.js`: pontos animados, ondas suaves, gradientes e ruído determinístico sobre uma paleta grafite/azul-petróleo; brilho leve ao mouse, no máximo 28 FPS, DPR limitado, desativação de animação por preferência do sistema, pausa ao ocultar a aba e fallback CSS.
- Halo Tabs implementadas no inspetor: Detalhes, Conexões dirigidas e Atividade do nó, com setas, Home, End, indicadores de foco e conteúdo selecionável.
- Prompt Composer funcional no handoff: textarea estilizada, contador de caracteres, Ctrl+Enter, indicador de envio e normalização da quebra de linhas para o contrato do backend (somente texto, não shell livre).
- Cabos SVG com física de segmentos e restrições Verlet; âncoras nos nós, gravidade controlada, trajetória suavizada, visualização distinta no sentido reverso, inércia limitada, fallback para movimento reduzido e remoção quando o vínculo deixa o grafo.
- Feedback discreto após um handoff com transporte confirmado. Não é confirmação de interpretação do modelo.
- Atalhos de teclado para selecionar/remover vínculos com confirmação; comando Ctrl+K com navegação por setas, Enter e Esc; busca de nó e centralização.
- Rota web `/canvas` sem a barra de título do aplicativo Windows, preservando o frontend anterior em `/index.html`.
- Link de entrada para o Canvas Web a partir do dashboard anterior. O token permanece na URL fragment (não transmitido como path/query), é transferido para sessionStorage e removido da URL pelo novo frontend.
- SENTRA CLI aberto manualmente no Canvas usa `Canvas._cli_command`, assim como os agentes, com estado persistente, nova conversa e modelo validado explicitamente no formulário. Não depende de compilação antiga em `dist/`.
- O controle de criação de agentes, conectividade dirigida, handoff e leitura de resposta continua no runtime do Canvas, com autorização de workspace e identidade de operação, e não no HTML.

## Comportamentos importantes
1. Um terminal iniciado **não equivale** a um modelo autenticado. A UI sugere Codex somente quando a integração detecta autenticação.
2. Vínculos do Canvas representam conexões dirigidas reais; a animação nunca cria ou envia mensagens por si mesma.
3. Enviar via ConPTY confirma somente o transporte. Verificação de resposta ou resultado do modelo usa estados/saídas reais.
4. O servidor permanece em `127.0.0.1`; API com bearer, origem local, CSP e assets estáticos explícitos.
5. Os cabos não dependem do Maestri nem de imagens, bibliotecas 3D ou serviços remotos.

## Testes e evidências
- `tests/js/canvas_cable_physics.cjs`: criação, movimento, identidade estável, redução de movimento e limpeza.
- `tests/unit/test_canvas_web_cables.py`: asset/rota, inicialização CLI, seleção validada de modelo, sintaxe JS.
- `tests/e2e/test_canvas_web_cult_ui.py`: navegador real Edge, pixels escuros do Canvas 2D, inspetor por abas, pesquisa/limpeza, Halo Toast, atualização física, e envio de Prompt Composer por ConPTY simulado com `cmd /Q /K`. Evidência local de screenshot: `.sentra/canvas/evidence/cult-dark-fractal-web.png` (ignorada pelo Git).
- Validação isolada real de Codex no Canvas: resposta de cálculo, criação de segundo terminal e vínculo dirigido; projeto de QA criado em pasta temporária e removido. Não foi modificada a instalação atual.

## Próximas entregas para paridade ampliada
- Evoluir Halo Tabs já presentes com orçamento, evidências e autorização por recurso, além de estados de risco/recuperação.
- Evoluir Prompt Composer já funcional com histórico e confirmação de entrega/reconciliação, sem inventar ACK de modelo.
- Navegação por mini-mapa, agrupamento visual de equipes, layout automático opcional, seleção múltipla e organização de portas.
- Performance para 100+ nós: ocultação por viewport, redução adaptativa de física quando a aba perde foco, medição de FPS e consumo.
- Transições de estados e sinais de erro/uncertain diretamente no grafo, acessibilidade auditada e preferências do usuário.
- E2E de Web CLI reproduzível no CI usando provedor mock e QA opcional de modelo real, separando autenticação, transporte, resposta e efeito de ferramenta.

Esta atualização não publica uma nova release, não altera o aplicativo Maestri instalado nem modifica a configuração de credenciais/túnel.

## Controles de modelo e raciocínio (Codex nativo)

No terminal SENTRA CLI recém-iniciado:
- `/model` mostra o modelo atual. `/model list` lista os modelos disponíveis.
- `/model sentra/codex/current` seleciona a sessão Codex autenticada.
- `/model sentra/codex/<id>` permite selecionar um ID explícito; o Codex valida o ID na próxima inferência.
- `/model sentra/chatgpt-web/high` usa o catálogo do Gateway, se anunciado.
- `/effort` mostra o nível; `/effort low|medium|high|xhigh` muda o raciocínio das chamadas **Codex** subsequentes.
- `/status` exibe o modelo e o effort. `--model` e `--effort` também funcionam na inicialização.
- Se o modelo atual é Web, o CLI informa que o effort fica armazenado para futuros turnos Codex, e **não** afirma modificar o modelo Web.

O formulário de novo terminal permite definir o modelo e effort inicial antes de lançar o processo, com validação no backend. Na interface espacial, botões `/model` e `/effort` consultam as opções enviando comandos ao PTY real; o painel lateral agrupa agentes/terminais por workspace. Esses controles são específicos do SENTRA e não exigem o Maestri instalado.

**Processos já em execução:** atualizações no código-fonte não fazem hot-reload do Python carregado no processo. Para usar os novos slash commands numa sessão criada antes da atualização, reinicie-a com recuperação apropriada, sem cancelar tarefas ativas; a alteração de modelo e effort é por processo/sessão interativa e não modifica o perfil global do Codex.

**Paridade visual:** referências à navegação do Maestri são inspiração de interação; não se reutilizam binários, recursos ou código proprietário. Persistem diferenças funcionais de interface (portais, andares e desenho livre não foram replicados).
