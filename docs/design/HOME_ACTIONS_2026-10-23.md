# Início centralizado, anexos e ações rápidas

Preferência final de cor: fundos em preto e grafite neutros, sem tonalidade azul.
Base `#101010`, lateral `#090909`, painéis `#1b1b1b` e campos `#242424`.
O azul permanece apenas como destaque nas ações e na identidade dos Dots.
Captura atual: `evidence/2026-10-23/home-actions/home-neutral-black.png`.

Refinamento solicitado a partir da nova referência enviada pelo usuário.
O Dot animado, o título, o campo de mensagem e os atalhos formam agora um único
grupo central. O espaço entre título e campo é de 28 px no desktop e 24 px em
janela estreita. O tema escuro usa grafite azulado, painéis mais distintos e
texto mais claro; o azul substitui o laranja nas ações principais. O envio
habilitado tem contraste medido de 7,12:1 entre ícone e fundo.

## Ações disponíveis

- **Analisar documentos:** prepara um rascunho sem sobrescrever texto existente
  e abre a escolha de arquivo.
- **Criar novo canvas:** abre a configuração de um novo Dot/Canvas. Após a criação
  pelo contrato existente, abre o Canvas correspondente. Não inicia terminal.
- **Gerar código:** prepara um rascunho e move o foco para a mensagem; não envia
  nem executa código por conta própria.
- **Explorar rede:** abre a área de Rede já existente.
- **Botão +:** permite selecionar um arquivo local, exibe seu nome e permite
  removê-lo. Imagens têm o limite já existente de 8 MiB e documentos, 20 MiB.

O arquivo inicial é mantido em memória durante a navegação. O nome e o rascunho
ficam preservados após recarregar; nesse caso, a interface solicita selecionar
o arquivo novamente e bloqueia o envio até isso acontecer ou o anexo ser removido.
Continuar com anexo cria a conversa e o encaminha ao uploader existente. O usuário
confirma o upload e revisa o envio na conversa. Não foi introduzido reenvio
automático nem alteração de permissões. O backend não foi modificado.

As conversas recentes passaram a ser ordenadas por data também quando uma nova
conversa é acrescentada à coleção, preservando a ordem da coleção original.

## Verificação

265 testes da interface passaram. Build e verificação de integridade do bundle
concluídos. Inspeção nos temas claro e escuro, em 1440×900, 1280×720 e 390×844;
sem overflow horizontal nas superfícies observadas. Ações de toque novas têm
44 px em janela estreita. Conferidos foco ao fechar o formulário de Canvas,
atalho de código, navegação para Rede e consistência do novo tema no Canvas.

A prévia local simulou seleção pelo botão + e pelo atalho de documentos,
transferência, confirmação do upload e envio: um registro de mensagem do usuário
e uma resposta explicitamente fictícia. Também foi conferida a exigência de
selecionar novamente o arquivo após recarregar. A simulação não valida execução
de modelos, armazenamento real de anexos ou criação real de Canvas. O formulário
de Canvas foi aberto e cancelado, sem mutação real.

Capturas e recibo de verificação: `evidence/2026-10-23/home-actions/`.
