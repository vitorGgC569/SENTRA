# Lapidação visual do SENTRA

Implementação autorizada após os estudos de interface, estrutura e experiência
do cliente. Direção: aplicação de trabalho sóbria, com superfícies neutras,
contraste legível, laranja reservado às ações principais e mascotes como
identificação dos assistentes. As skills UI/UX Pro Max, Frontend Design e
Impeccable foram aplicadas em etapas, preservando a identidade do produto.

## O que mudou

- Início com cabeçalho compacto, retomada do trabalho, quatro conversas recentes,
  assistentes e espaços. A listagem completa de conversas continua disponível.
- Terminologia mais clara: Início, Assistentes e Espaços. O botão que leva à
  escolha do assistente agora descreve seu destino.
- Navegação com projeto e ferramentas fixos; um único trecho central rolável.
  Em janela estreita, o menu deixa o botão de recolher acessível.
- Temas claro e escuro com uma paleta compartilhada, controles consistentes,
  foco visível e contraste corrigido no botão principal do Canvas.
- Conversa com cabeçalho enxuto, estado da conexão legível, orientação inicial
  direta e área de escrita sem brilho decorativo. Removido o recorte do mascote
  em janelas de menor altura.
- Formulário de assistente compacto, identidade junto ao nome, seleção de
  personalidade em grade e abas de modelo e instruções. O foco volta ao botão
  que abriu o diálogo; as restrições durante operações pendentes permanecem.
- Canvas com acolhimento mais compacto quando já existe terminal aberto.
  Ajustes de apresentação não recriam sessões nem alteram PTYs.
- Ilha flutuante interna removida conforme o pedido do usuário. A integração
  da barra externa permanece; atividade e decisões seguem acessíveis no app.

O adapter visual existente [component source inventory](../../THIRD_PARTY_NOTICES.md) foi consolidado; não foi
adicionado um quarto stylesheet de overrides. A atribuição e licença dos componentes
permanecem. Fontes do backend não foram alteradas por esta implementação.

## Validação realizada

- 261 testes existentes da interface: passaram, nenhuma falha.
- Build de produção: passou; entrada `/desktop.html` e 124 arquivos validados
  pelo verificador de integridade do bundle.
- Detector estático Impeccable, nos arquivos editados: nenhuma ocorrência.
- Comparação SHA-256 de 1.413 arquivos Python com o início desta tarefa visual:
  nenhuma diferença. As alterações anteriores existentes no checkout foram
  preservadas.
- Inspeção renderizada de Início, conversa, Canvas, criação de assistente e
  seletor de sessão. Temas claro/escuro, desktop 1440×900 e 1280×720; Início,
  conversa e diálogo também conferidos em 390×844.
- Conferidos ausência de overflow horizontal nas superfícies observadas,
  fechamento do menu estreito, Escape no diálogo e retorno do foco ao botão
  “Novo assistente”. Um único landmark principal visível na Home e conversa/Canvas.

Capturas e resultado resumido em `evidence/2026-10-23/refinement/`.
As capturas usam a prévia isolada com dados fictícios. O estado de reconexão da
conversa nessa prévia não valida conectividade real. Não foram exercitados
envio a modelos, alterações de permissões, instalação, execução real de agentes
ou validação do instalador congelado. O build mantém avisos de scripts clássicos
e tamanho do chunk principal; essa arquitetura não foi alterada nesta tarefa.
