# Avaliação B — evidência técnica independente

Data: 2026-10-23. Alvo: shell stable SENTRA. Modo: Operate.
Independência: avaliação realizada sem consultar resultado de A. Apenas a informação de que A terminou foi recebida ao encerrar B.

## Detector CLI

Uma única execução, no cwd C:\Users\vitor\Desktop\SENTRA:

```powershell
& 'C:\Users\vitor\.codex\skills\impeccable\scripts\impeccable.cmd' detect --json sentra_canvas/desktop_ui/src/shell-app.jsx sentra_canvas/desktop_ui/src/shell-conversation.jsx sentra_canvas/desktop_ui/src/shell-dialogs.jsx sentra_canvas/desktop_ui/src/workspace/DotWorkspace.jsx
```

- Exit: 0.
- JSON integral: `detector.json`, conteúdo `[]`.
- Findings: 0. Rules: nenhuma. Locations: nenhuma.
- Cada um dos quatro paths foi passado explicitamente; o JSON não fornece metadados de quantidade de arquivos efetivamente analisados.
- Falsos positivos do detector: 0 (não houve findings a triar).
- Ignore list fornecida: nenhuma; não foram modificadas configurações de exclusão.
- Este resultado não certifica acessibilidade, contraste ou cascata CSS no navegador.

## Falhas comprovadas fora do detector

Total: 4 achados técnicos, P0=0, P1=2, P2=2, P3=0. As observações de targets abaixo não entram nessa contagem.

### P1 — contraste do skip link no tema escuro

- Markup: `sentra_canvas/desktop_ui/src/shell-app.jsx:839`.
- Estilo efetivo: `sentra_canvas/desktop_ui/src/desktop.css:506`.
- Com Tab, o link “Ir ao conteúdo” apareceu em x=15/y=15, com texto de 13px `rgb(82,105,187)` sobre fundo opaco `rgb(24,25,28)`.
- Razão calculada a partir das cores computadas: 3,4294:1; insuficiente para texto pequeno (WCAG 1.4.3 AA, 4,5:1).
- O foco existe: outline sólido de 2px `rgb(253,171,99)`. O problema é o texto, não ausência de foco.
- Causa: cor literal #5269bb não acompanha o token do tema. Recomenda-se usar token de texto/link que alcance 4,5:1 nesse fundo. Comando sugerido: `$impeccable harden`.

### P1 — contraste do botão Nova sessão no cabeçalho do Canvas

- Markup: `sentra_canvas/desktop_ui/src/workspace/DotWorkspace.jsx:183`.
- Cascata: `sentra_canvas/desktop_ui/src/workspace/workspace.css:26` aplica `color:var(--sw-text)` ao botão do cabeçalho com seletor mais específico; [component source inventory](../../../../THIRD_PARTY_NOTICES.md)/197 fornece fundo laranja e tenta aplicar texto escuro, mas perde na propriedade color.
- Em Canvas, `.sw-new-session` apresentou texto de 12px `rgb(245,246,248)` sobre `rgb(251,146,60)`; medição repetida em estado Canvas confirmou as mesmas cores.
- Razão: 2,0930:1, abaixo de 4,5:1 (WCAG 1.4.3 AA).
- Dimensão medida: aproximadamente 119,22×34 CSS px. Controle habilitado.
- Recomenda-se fazer a regra efetiva desse CTA consumir `--sc-accent-ink`, como os demais botões primários sobre esse fundo. Comando sugerido: `$impeccable harden`.

### P2 — fechar Novo Dot perde o ponto de retorno do teclado

- Entrada: `sentra_canvas/desktop_ui/src/shell-app.jsx:951`; diálogo em `sentra_canvas/desktop_ui/src/shell-dialogs.jsx:37`; primitiva em `sentra_canvas/desktop_ui/src/primitives.jsx:15`.
- Reprodução: abrir “Novo Dot”, foco inicial no input Nome, pressionar Escape. `document.activeElement` passa a BODY em vez de retornar ao botão Novo Dot.
- Confirmado com abertura por clique e novamente com Enter no botão via locator.
- A primitiva usa Dialog.Root/Content sem Dialog.Trigger e sem restauração explícita no fechamento. O usuário de teclado perde a posição de trabalho.
- Recomenda-se registrar/restaurar o acionador ou conectar um Dialog.Trigger apropriado; não foi alegada falha do focus trap durante o modal. Comando sugerido: `$impeccable harden`.

### P2 — landmark main ausente nas superfícies Canvas e conversa

- `sentra_canvas/desktop_ui/src/shell-app.jsx:931` mantém o contêiner comum como div; `:946` só renderiza main fora de canvas/documents/chat.
- No DOM de Canvas e de conversa, número de `main,[role=main]` com caixa renderizada: zero. Home possui main.
- As superfícies têm sections nomeadas e o skip link continua disponível; portanto não se afirma falha automática de WCAG 2.4.1. O defeito é a inconsistência na navegação por landmark principal.
- Recomenda-se um main comum que contenha a superfície ativa, evitando landmarks principais duplicados. Comando sugerido: `$impeccable harden`.

## Targets: evidência e triagem

Medições em 1280×720 CSS px, antes do aviso sobre viewport global:

- Home, Novo Space no rail: 21×21.
- Home, Modelo/summary de card: altura 19; largura aproximada 196,41.
- Ícones da topbar e menus de Dot: 30–33×32–33.
- Canvas, fechar aba: 21×31.
- Canvas, ações de dividir/maximizar/fechar painel: 24×31.
- Canvas, separador: 4px de largura.
- Chat, Acesso: altura 28,5; Enviar: 34×34 (desabilitado com mensagem vazia).

São alvos compactos em relação à referência ergonômica de 44×44. Não foram contados como violações AA por tamanho isolado: 2.5.8 usa 24×24 com exceções; Novo Space tem outro acionador maior no mesmo Home, fechar aba possui alternativa no menu, e summaries podem satisfazer espaçamento. A exceção de equivalência/espaçamento requer consideração antes de reportar uma infração. O separador também oferece teclado e alternativas de organização no painel. Responsividade e outros viewports ficaram a cargo do responsável pela avaliação conjunta.

## Suspeitas descartadas / proteções verificadas

- Cores antigas do workspace (#737373 etc.) não provam tema quebrado. A camada visual sobrescreve tokens em [component source inventory](../../../../THIRD_PARTY_NOTICES.md); o Canvas medido usava `--sw-accent:#fdab63`, fundo #0e0f11 e texto #f5f6f8. Não há finding genérico de ausência de tokens.
- Inputs de ShellEntityDialog e ShellCoordinateDialog usam Field, que renderiza label envolvente em `primitives.jsx`. AX do diálogo mostrou Nome e Papel nomeados. Não há finding de campos sem labels.
- Botões de ícone observados têm nomes acessíveis. Menus usam Radix; tabs possuem role, seleção e associação com tabpanels. Não há finding genérico de ARIA ausente.
- Foco visível foi medido diretamente no skip link. Há regras finais de focus-visible no shell; declarações antigas de outline não foram usadas para inventar falha.
- o componente de divisão, dependência do alvo, tem role separator, tabIndex, valor/orientação, setas de teclado, pointer capture, limpeza em pointercancel/lostpointercapture e touch-action:none. Não procede classificá-lo como implementação mouse-only. Gesto touch não foi sintetizado.
- Conversa usa textarea nomeada Mensagem, busca nomeada, log nomeado e status separado para resposta disponível. O log com aria-live=off é intencionalmente acompanhado de um status polite; não foi tratado isoladamente como falha.
- Há ShellMessageWindow para histórico e RetainedTab/portals para retenção de painéis. Sem profiler, não se atribuiu custo de render, layout thrashing ou bundle excessivo.
- Há regras de reduced motion e `useReducedMotion` na conversa. A presença de cancelamento global de animação, sem evidência de perda de estado, não foi contada como falha funcional.

## Limitações e notas de execução

- Browser preview: [component source inventory](../../../../THIRD_PARTY_NOTICES.md), página QA que importa o shell real e usa fixtures. Não é verificação da janela desktop nativa nem da execução real de agentes.
- Aba nova própria em browser 2/iab, mantida em background (`visible:false`). Nenhuma aba de A/pai foi usada. Estados examinados: Home, Novo Dot, Canvas de Dot existente e conversa existente. Nenhuma criação/envio foi submetida.
- Overlay indisponível: evaluate documentado como somente leitura. Não houve tentativa de injetar detector, alterar título ou DOM por evaluate. Não há findings de console do overlay. Fallback: AX, screenshot nativo, leituras DOM, estilos computados e caixas renderizadas, mais fonte/cascata.
- Nenhum live-server ou serviço extra iniciado; limpeza de live-server não aplicável.
- Sem novos tamanhos/medições após o aviso de que o responsável usaria a capability global de viewport. Sem conclusão sobre mobile, zoom, 320 CSS px, outros temas, gestos touch, screen reader real ou desempenho em carga.
- A prévia voltou a Home entre duas leituras sem ação explícita desta avaliação; a medição do CTA foi repetida em Canvas e confirmada. As cores registradas são evidência dos estados observados, não de estabilidade do runtime QA.
- Não foi atribuída nota global /20: desempenho e responsividade não tiveram cobertura suficiente para pontuação defensável.
- Home restaurado ao terminar; a aba criada por B foi fechada com sucesso. Nenhum código do produto foi modificado.
- `detector.json`, `detector.stderr.txt` (vazio) e este relatório foram mantidos em `.tmp/design-audit-20261023` para reutilização pelo responsável; não rerodar detector para obter essas contagens.

Prioridade sugerida: corrigir os dois contrastes, restaurar foco de fechamento, estabilizar o landmark principal e, após integrar a verificação responsiva externa, finalizar com `$impeccable polish`.
