# Modo Simples e acesso preparado — 21/10/2026

Atualização posterior: [continuidade e colaboração](ORCA_CONTINUITY_COLLABORATION_2026-10-21.md) implementa persistência protegida no host, retomada e permissões na conversa. Os parágrafos abaixo registram a rodada inicial.

Build de fontes/artefatos: `sentra-orca-experimental-1a724e4b6a1f`.
Classificação: progresso implementado e validado localmente. O plano integral
ORCA/SENTRA permanece aberto.

## Apresentação do Canvas interno

O Modo Simples passa a ser o padrão do workspace experimental. A Home, a
navegação externa e a conversa principal continuam com seus componentes atuais.
A instalação não recebeu os bundles experimentais.

- Uma tela inicial com o Dot e a ação principal de conversar.
- “Nova sessão” reúne conversa, terminal, navegador e computador. A lista de
  ferramentas aparece depois de escolher terminal, com indisponibilidade real.
- Nenhuma aba de ferramenta é pré-aberta no layout simples novo. Abas surgem
  conforme a seleção; fechar uma aba continua desacoplando apenas a visualização.
- Arquivos e subagentes recolhidos; controles discretos permitem abri-los.
- Dispositivos/QR acessível por ícone com nome acessível e tooltip.
- Ações incertas ficam visíveis como um aviso curto, com consulta no diagnóstico.
  O aviso continua bloqueando efeitos novos; escondê-lo visualmente não autoriza
  repetição. IDs e recibos completos ficam no diagnóstico ou no modo avançado.
- Layouts simples e avançados separados por escopo. O layout avançado anterior
  não é sobrescrito; alternar modos não cria processos, Grants ou operações.
- Navegador usa nomes legíveis e omite seletores quando existe apenas uma opção.
  O computador recebe apresentação simples somente quando aberto pelo workspace;
  seus usos fora do Canvas conservam o comportamento anterior.

Preferências/layouts continuam no armazenamento do renderer. Persistência no
host e entre dispositivos permanece no plano, especialmente porque o perfil de
exibição Electron atual usa partição de sessão.

## Preparação de permissões

“O que o Dot pode fazer?” oferece três escolhas: consultar arquivos, trabalhar
com aprovação ou desativar o acesso local a arquivos/comandos da conversa.
Há revisão antes de confirmar; não se exige preencher IDs, Grants ou WorkItems.

`dot_canvas_access` compõe o serviço `shell_access` existente. O servidor confere
dono autenticado, projeto, Space, associação ao Canvas e conversa do membro.
Só aceita receitas fixas e confirmação booleana explícita. O host prepara o
WorkItem e os Grants da conversa; modelos e dispositivos não recebem uma nova
API para conceder autoridade a si mesmos.

A receita de leitura concede somente `computer:file.read`, com escopo de
WorkItem e política do projeto. A receita de aprovação mantém o perfil existente
`ask`: leituras autorizadas seguem, alterações e comandos geram pedido ao dono.
Não oferece `full`, aprovação irrestrita ou escopo de computador completo.

Selecionar uma receita substitui o acesso local de arquivos/comandos dessa
conversa, inclusive as autorizações legadas que o serviço existente já substitui.
Não encerra terminais nem altera outras conversas. Não é uma declaração de que
o Dot perdeu todas as permissões que eventualmente possua para outros recursos.

A intenção original fica no diário protegido, com seletor persistido no cliente.
Pedido duplicado devolve o registro anterior. Consultar confirmação não aplica a
receita novamente. Uma falha depois do início da composição fica incerta: a
mudança cruza stores existentes e não foi apresentada como transação única.

Isso prepara o acesso local aos arquivos/comandos. Grants de VM, navegador,
terminal central, modelos e provedores continuam em seus contratos específicos.
O requisito de VM dos terminais de agente foi preservado. Não se introduziu um
fallback para PowerShell do host quando uma ferramenta do Dot exige VM.

## Evidências

- 21 testes Python na rodada final: receitas, confirmação obrigatória, escopos,
  downgrade, leitura real de arquivo, recusa de exclusão/comando, idempotência,
  recuperação sem reenvio e isolamento do launcher de avaliação.
- Seis testes do serviço de perfis existente passaram na rodada anterior desta
  implementação; os lotes têm sobreposição e não são somados como novos ensaios.
- 145 testes Node desktop passaram, incluindo três novos de apresentação.
- Dois builds desktop isolados concluíram; bundles instalados foram preservados.
- Renderer Electron descartável conferiu: padrão simples; zero efeitos e zero
  consultas de arquivos no início; ferramentas sob demanda; zero alterações
  antes da confirmação e uma chamada após confirmar; arquivo e layout restaurados
  entre modos; tecla End move foco/seleção da aba; largura de 660 px sem overflow
  horizontal; tokens de tema claro aplicados. As capturas escuras foram inspecionadas.

O teste do renderer usa um adaptador de fixture, sem serviço externo ou conta.
Os testes Python usam o host real com estado próprio. Uma evidência não é
apresentada como substituta da outra. A verificação de tema e uma tecla não
homologa integralmente contraste, leitores de tela e todos os atalhos.

Artefatos: `.tmp/workspace-simple-ux-proof/` e
`vendor/orca/simple-mode-validation.json`.

## Janela para avaliar

Aberta a janela **SENTRA · Modo Simples**, estado independente em
`.tmp/orca-simple-evaluation`, supervisor PID 8520 e display PID 380 no momento
da conferência. O launcher confirmou CSS, mascotes e botão de dispositivos.
As janelas “SENTRA Desktop” e “SENTRA · Avaliação ORCA” foram preservadas.

O novo gateway usa a porta LAN 5199. O QR continua exigindo aplicativo SENTRA
instalado; os pacotes nativos e a homologação Android/iPhone permanecem pendentes.
A janela foi aberta antes dos últimos ajustes de texto/chave de componente;
seus assets de avaliação foram atualizados em disco para a próxima recarga.
Não se encerrou o broker ou qualquer sessão para aplicar esses ajustes.

O próximo aceite é a avaliação do fluxo simples pelo usuário, seguida da
continuação dos demais contratos e da distribuição móvel do plano integral.
