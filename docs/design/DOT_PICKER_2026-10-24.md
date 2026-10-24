# Escolha do assistente pelo Dot central

O seletor nativo do compositor foi removido. O mascote central e seu nome são
agora um botão que abre uma lista visual com imagem, nome e indicação da escolha
atual. O controle usa os componentes Radix já presentes no aplicativo.

- Escolher um assistente existente muda o destinatário da próxima conversa,
  o mascote e o modelo apresentado. Não cria outro Dot nem executa ferramentas.
- O texto e o anexo preparado permanecem ao trocar a seleção.
- **Novo assistente** abre o cadastro existente. Após criação confirmada, o novo
  Dot é selecionado no mesmo projeto/espaço. O sinal de seleção é consumido uma
  vez: atualizações posteriores não desfazem uma escolha manual.
- Escape retorna o foco ao mascote. Escolher outro assistente leva o foco à
  mensagem. A seleção e o rascunho foram conferidos após recarregar.

## Conferência e entrega

265 testes existentes da interface passaram; build de produção e detector
Impeccable concluídos sem falhas/ocorrências. Na prévia isolada, foram conferidos
troca, foco, Escape, rascunho, recarga e abertura do cadastro. A prévia não oferece
modelos configurados e não foi usada como prova de criação real ou inferência.
No laboratório com backend real foi observado o cadastro de um novo assistente
retornar ao Início com seu nome e mascote selecionados.

O executável foi recompilado de um snapshot de 1.887 arquivos, aplicado com
backup e aberto contra os dados existentes. O novo controle foi conferido na
instalação escolhendo **dasd**; o manifesto servido corresponde ao build testado.

- Canvas SHA-256: `c5f90fb29faf795ef0ef9204ec76db80e7adeb2f1f08313ce2d8a10f53e17a8e`.
- Manifesto SHA-256: `2b164d91368f3d02fa7eb2068a6699e96f86c720cb450acd012691edd44ba6cd`.
- Backup local: `.tmp/dot-picker-20261024/installed-backup/patch.json`.
- [Captura ilustrativa do seletor](evidence/2026-10-24/dot-picker/central-selector.png).

## Ocorrência do Windows

Ao tentar reabrir o Electron, o Controle de Aplicativos do Windows recusou o
processo com `WinError 4551`. Nenhuma proteção foi desativada ou modificada.
A instalação estava sem terminais e operações ativas, e a janela não tinha
rascunho. Sua interface ociosa foi encerrada para aplicar o patch.

O SENTRA foi aberto usando seu host nativo WebView2 (`--ui native`). Um atalho
**SENTRA - modo nativo** foi criado na Área de Trabalho para essa abertura.
O modo automático padrão não foi alterado. A barra externa depende do Electron
e continua indisponível enquanto esse componente estiver bloqueado pelo Windows.
Isso permanece uma limitação conhecida, sem declaração de homologação global.

As janelas/servidor de avaliação foram encerrados, preservando os dados do
laboratório em `.tmp/dot-picker-20261024`. A instalação atualizada ficou aberta.
Nenhum Setup, assinatura ou tag nova foi publicado nesta alteração.
