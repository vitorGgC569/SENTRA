Method: dual-agent (A: 01a16a9e-6827-72a2-b5c1-82a54eb3830d · B: 01a16a9e-694c-7122-8b29-f28fd5f55f0b)

# Avaliação da interface do SENTRA — 23/10/2026

As três skills solicitadas foram instaladas, lidas e aplicadas em etapas.
Fontes e instalação: [skills.md](skills.md). O resultado desta etapa é uma
avaliação e uma proposta de direção. O layout do aplicativo não foi alterado.

## Veredito

O SENTRA tem personagens reconhecíveis, mas a composição ainda se aproxima de
um dashboard genérico de agentes. O maior problema é a distribuição da atenção:
apresentação da marca, cartões e navegação disputam espaço com o trabalho.
Para melhorar significativamente, precisamos tornar contexto, atividade atual
e próximo passo mais claros, e dar mais espaço ao conteúdo usado de fato.

O laranja e os mascotes podem sustentar a identidade. A proposta é concentrar
essa personalidade nos agentes, reduzir decoração repetida e organizar a
superfície como uma mesa de trabalho de uma equipe de agentes.

## Escopo e evidências

- Alvo estável: `sentra_canvas/desktop_ui/src/shell-app.jsx` e seus componentes.
- Prévia isolada existente: `qa/orca-workspace.html`, servida pela configuração
  `vite.orca-preview.config.js`. Ela importa os componentes e CSS atuais, mas
  substitui a API por fixtures. Nenhum agente real foi iniciado nesta revisão.
- Inspeção com navegador e Playwright: Home, conversa, Canvas e diálogo Novo
  Dot; tema escuro e Home no tema claro; viewports de 1280×720, 1440×900 e
  390×844 CSS px. Nem todas as combinações foram examinadas.
- A: avaliação visual e heurística independente, sem detector. B: detector,
  árvore de acessibilidade, DOM, estilos computados e triagem técnica.
- Complemento: medições de layout, tema claro, diálogo, foco após Escape e
  layout estreito pelo agente principal.
- Não foram validados a janela desktop nativa, execução real, rede, persistência
  real, recuperação após falhas reais, leitor de tela, gestos touch ou desempenho
  em carga. Os avisos de reconexão observados pertencem à prévia.

| Captura | O que permite verificar |
| --- | --- |
| [Home 1280](evidence/2026-10-23/home-1280.png) | Hero, retomada e primeiros agentes |
| [Home 1440](evidence/2026-10-23/home-1440.png) | Distribuição no desktop amplo |
| [Home clara](evidence/2026-10-23/home-light-1280.png) | Consistência no tema claro |
| [Canvas](evidence/2026-10-23/canvas-1280.png) | Terminal e painel de retomada competindo por área |
| [Conversa](evidence/2026-10-23/chat-1280.png) | Estados, cabeçalhos e compositor |
| [Home estreita](evidence/2026-10-23/home-390-initial.png) | Entrada inicial com navegação recolhida |
| [Diálogo desktop](evidence/2026-10-23/dialog-1280.png) | Hierarquia e formulário Novo Dot |
| [Diálogo estreito](evidence/2026-10-23/dialog-390.png) | Rolagens e distribuição do formulário |

## Avaliação heurística

**23/40**, avaliação qualitativa com melhorias importantes. As notas combinam
observação visual e leitura de implementação; não são uma certificação de
usabilidade ou acessibilidade. Todas as dez heurísticas se aplicam ao modo
Operate desta superfície.

| Heurística | Nota /4 | Principal observação |
| --- | ---: | --- |
| Visibilidade do estado | 2 | Estados globais e locais pouco diferenciados |
| Correspondência com o mundo real | 2 | Projeto, Space, Dot, Canvas e sessão exigem aprendizado |
| Controle e liberdade | 3 | Retorno e painéis recolhíveis; desfazer não exercitado |
| Consistência e padrões | 2 | Destinos e ações sobrepostos |
| Prevenção de erros | 3 | Proteções de envio no código; fluxos destrutivos não testados |
| Reconhecimento em vez de memorização | 2 | Recentes ajudam; escopos continuam pouco evidentes |
| Flexibilidade e eficiência | 3 | Busca, atalhos, sessões e divisões; descoberta discreta |
| Estética e minimalismo | 2 | Excesso de caixas e apresentação acima do trabalho |
| Diagnóstico e recuperação | 3 | Texto preservado e consulta explícita; recuperação real não testada |
| Ajuda e documentação | 1 | Falta orientação visível sobre o modelo mental |
| **Total** | **23/40** | **Uma base funcional com hierarquia e clareza insuficientes** |

### Carga cognitiva e jornada

A avaliação A identificou cinco falhas no checklist de oito itens: foco único,
agrupamento em blocos menores, hierarquia, uma decisão por vez e divulgação
progressiva. O tamanho de uma lista, isoladamente, não prova sobrecarga; aqui
o problema é apresentar níveis diferentes com peso semelhante.

A lateral reúne quatro destinos principais, cinco Dots da fixture, Spaces,
três vistas locais e quatro utilitários. No Canvas, o painel de retomada oferece
conversa, criação, três sessões e arquivos enquanto o cabeçalho repete criação.

A jornada começa acolhedora, mas perde orientação ao misturar estados e termos.
Os vazios devem apontar a próxima ação específica, proporcional ao espaço vazio,
em vez de introduzir outra recepção dentro de uma área já em uso.

## Cinco prioridades

### 1. [P1] Simplificar escopos e alinhar ações com seus rótulos

**Problema:** Projeto, Space, Dot, conversa e Canvas têm relações pouco visíveis.
O botão “Nova conversa” da Home navega para a lista de Dots; depois é necessário
escolher “Conversar”. Canvas aparece como destino do Space e ação de cada Dot.

**Impacto:** o usuário precisa interpretar a organização do produto antes de
conseguir trabalhar, e a ação inicial não comunica sua etapa intermediária.

**Mudança proposta:** mostrar a hierarquia do contexto ativo e consolidar acessos
duplicados. “Nova conversa” deve abrir uma escolha contextual clara ou usar um
rótulo que anuncie a seleção do Dot. Destinos do trabalho ficam próximos entre
si; administração fica em um grupo secundário.

**Fontes:** `shell-app.jsx:40`, `:841`, `:847`, `:851`, `:948`.
Referências de execução: `$impeccable distill` e `$impeccable clarify`.

### 2. [P2] Fazer a Home começar pelo trabalho atual

**Problema:** em 1280×720, o hero mede aproximadamente 243 px de altura; abaixo
dele há mais 115 px de retomada. O primeiro cartão começa perto de y=534.
Conversas recentes aparecem só depois da grade de agentes. A lateral mede
720 px de área visível para cerca de 1112 px de conteúdo na fixture.

Em 390×844, o hero mede aproximadamente 292 px e o primeiro cartão começa em
y=625. A entrada estreita recolhe a navegação e não apresentou overflow
horizontal de documento na observação realizada; isso não resolve a densidade
vertical nem comprova gestos touch.

**Impacto:** apresentação e repetição atrasam a chegada ao trabalho. Os cartões
usam descrições pouco diferenciadas, como “Especialista”.

**Mudança proposta:** cabeçalho compacto; retomada e decisões pendentes primeiro;
lista de trabalhos recentes com título, agente, estado e próxima ação. Agentes
podem aparecer em linhas compactas ou cartões apenas quando houver informação
comparável que justifique a área. Reservar a recepção completa ao primeiro uso.

**Fontes:** `shell-app.jsx:948`, `:949`, `:951`, `:953`;
`shell-coucou-macos.css:133`, `:148`, `:172`; `shell-home-resume.jsx:21`.
Referências: `$impeccable layout` e `$impeccable onboard`.

### 3. [P1] Melhorar legibilidade, estados e acesso por teclado

**Problema visual:** rótulos e estados importantes chegam a 10–11,5 px. No chat,
“Em execução”, outro Dot “Trabalhando”, “Presente” e reconexão aparecem juntos.
Eles podem ser tecnicamente compatíveis, mas falta explicar o escopo de cada um.

**Quatro achados técnicos comprovados:**

| Severidade | Achado | Evidência e correção proposta |
| --- | --- | --- |
| P1 | Contraste do CTA “Nova sessão” | Texto `#f5f6f8` sobre `#fb923c`: **2,09:1**, abaixo de 4,5:1 para texto pequeno. `workspace/workspace.css:26` vence na propriedade de cor; corrigir para o token de texto sobre o acento em `shell-coucou-macos.css:193`. |
| P1 | Contraste do skip link | Texto `#5269bb` sobre `#18191c`: **3,43:1**, abaixo de 4,5:1. `desktop.css:506`; usar cor de texto apropriada ao tema. O foco visível existe. |
| P2 | Escape perde o retorno de foco | Em Novo Dot, o input Nome recebe foco; Escape fecha o diálogo, mas `document.activeElement` passa a BODY. `primitives.jsx:15`; vincular o acionador ou restaurar seu foco explicitamente. |
| P2 | Falta landmark principal em chat e Canvas | Nenhum `main`/`role=main` com caixa renderizada nessas vistas; Home possui main. `shell-app.jsx:931` e `:946`; usar um landmark principal comum, sem duplicação. O skip link existe, portanto não se conclui automaticamente falha de WCAG 2.4.1. |

**Mudança proposta:** corpo em 14–16 px conforme a superfície, metadados
importantes em 12–13 px, status de conexão junto da conversa e atividade global
explicitamente identificada. Revalidar os contrastes com estilos efetivos.

Alvos de 21–34 px merecem revisão ergonômica. Não foram contados como infrações
AA apenas por serem menores que 44 px: o critério de 24 px possui exceções de
espaçamento e equivalência que precisam ser avaliadas.

**Outras fontes:** `shell-coucou-macos.css:111`, `:180`, `:223`;
`shell-chat-visuals.css:137`; `shell-conversation.jsx:580`, `:592`;
`shell-island.jsx:28`, `:76`. Referências: `$impeccable harden`,
`$impeccable typeset` e `$impeccable clarify`.

### 4. [P2] Fazer o Canvas priorizar a área de execução

**Problema:** ao lado do terminal aberto, metade da tela apresenta uma recepção
com mascote, “Vamos continuar?”, botões e lista de sessões. “Nova sessão” aparece
também no cabeçalho. O espaço vazio se comporta como outra Home.

**Impacto:** a área disponível para execução e leitura parece menor e o usuário
encontra destaques concorrentes.

**Mudança proposta:** quando já houver trabalho aberto, usar um placeholder
compacto para adicionar conteúdo ao painel. Oferecer retomada completa apenas
quando todo o Canvas estiver vazio. Unificar o significado de criar sessão e
adicionar aba/painel, preservando os contratos e as sessões existentes.

**Fontes:** `workspace/DotWorkspace.jsx:178`, `:183`.
Referências: `$impeccable distill` e `$impeccable layout`.

### 5. [P2] Consolidar o sistema visual e a cascata

**Problema:** `main.jsx:30` carrega `desktop.css`, `shell-polish.css` e
`shell-coucou-macos.css` em sequência. Esses três arquivos somam aproximadamente
160 KiB de fonte e contêm 613 ocorrências de cores hexadecimais, além de regras
repetidas de hero, cartões e paleta. Contagem de fonte não é medida de custo
de renderização e não significa que todas as declarações estejam ativas.

Há tokens e mapeamentos de tema funcionando. A evidência mais forte do risco
da cascata é o contraste do CTA, onde uma regra mais específica vence uma parte
da intenção visual da camada final.

**Mudança proposta:** separar tokens e componentes com responsabilidades claras;
adotar tokens semânticos de texto, superfície, borda, ação, foco e estado; reduzir
overrides redundantes à medida que cada componente for revisado. Fazer a
migração por componente, com capturas comparáveis em dois temas.

**Fontes:** `main.jsx:30`, `shell-design-tokens.js:1`, `desktop.css:331`,
`shell-polish.css:49`, `:65`, `shell-coucou-macos.css:8`, `:50`, `:193`.
Referências: `$impeccable extract`, `$impeccable document` e `$impeccable polish`.

## O que preservar

- Mascotes ajudam a reconhecer agentes e oferecem identidade própria.
- Breadcrumbs, seleção visível e ações textuais orientam os caminhos principais.
- Retomada, proteção contra reenvio e preservação de sessões apoiam continuidade.
- Há labels, nomes acessíveis, componentes Radix e controles de teclado que
  merecem ser mantidos, não substituídos indiscriminadamente.

## Riscos por perfil

- **Primeiro uso:** termos e escopos sobrepostos dificultam a primeira tarefa.
- **Uso intenso:** rolagens concorrentes e ações duplicadas prejudicam a
  orientação; busca e divisões úteis têm pouca visibilidade.
- **Teclado e baixa visão:** microtexto, contraste insuficiente nos dois locais
  medidos e perda de foco dificultam a continuidade.

## Observações menores

No diálogo estreito, a escolha de personagens ocupa bastante área e introduz
uma rolagem interna dentro da rolagem do modal. Mostrar uma seleção inicial e
expandir o catálogo pode simplificar a tarefa. A organização em abas Identidade,
Modelo e Instruções já é uma boa forma de divulgação progressiva.

Ao reduzir uma aba desktop com lateral aberta para 390 px, a lateral continuou
aberta e cobriu o conteúdo; a primeira carga estreita começou recolhida. Esse
estado de redimensionamento merece um teste dedicado antes de classificá-lo
como bloqueio. Não foi usado como evidência de que a entrada mobile falha.

## Detector e triagem

O detector Impeccable foi executado uma vez, com quatro caminhos explícitos:
shell-app.jsx, shell-conversation.jsx, shell-dialogs.jsx e
workspace/DotWorkspace.jsx. Retornou exit 0 e JSON `[]`: **zero findings**, sem
rules ou locations. Ele não informou quantos arquivos efetivamente analisou.
Não houve falsos positivos a triar. Isso não certifica acessibilidade e não
substitui a inspeção dos estilos computados que encontrou os defeitos acima.

[Saída integral](evidence/2026-10-23/detector.json) e
[relatório técnico B](evidence/2026-10-23/assessment-b.md).

Não houve overlay injetado: a API de avaliação do navegador é somente leitura.
O sinal alternativo foi a combinação de screenshots, AX, DOM, caixas renderizadas
e estilos computados. Cores antigas sobrescritas, controles sem medição e
suspeitas de desempenho não foram convertidos em defeitos comprovados.

## Direção proposta para a implementação

Uma mesa de trabalho centrada na continuidade: contexto no topo, navegação
curta, trabalho atual em destaque e ferramentas próximas do conteúdo pertinente.

- Manter o laranja existente como acento e os personagens como identificadores.
- Concentrar o destaque em uma ação principal por região.
- Usar superfície base, superfície de painel e estado selecionado claramente
  distintos nos temas claro e escuro, sem transformar tudo em cartão.
- Reservar monoespaçada a código e terminal; usar a família de interface local,
  com escala legível e sem dependência de fontes externas.
- Usar animação para explicar abertura, mudança de estado e confirmação,
  respeitando a preferência de movimento reduzido.

Sequência recomendada: corrigir contraste e foco; revisar navegação e retomada
da Home; ajustar conversa e Canvas; consolidar componentes/tokens; finalizar com
inspeção visual e `$impeccable polish`. Não foi aprovado nem aplicado um novo
tema visual nesta avaliação.

## Decisões para a próxima etapa

1. Prioridade inicial: **Home + navegação** (recomendação), **conversa + Canvas**
   ou **somente acessibilidade e legibilidade**?
2. Presença dos personagens: **discreta e funcional** (recomendação),
   **equilibrada como hoje** ou **mais protagonista**?
