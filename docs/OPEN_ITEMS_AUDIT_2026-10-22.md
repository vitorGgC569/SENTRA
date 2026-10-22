# Auditoria das pendências — SENTRA, ORCA e Coucou

Data: 22/10/2026. Base: `bfa09a5a43a47132fa4474fb52a0ac5536d6bd0b`.
Última observação dos ensaios: aproximadamente 17h32, horário de Brasília.
Análise do código, relatórios locais, estado dos ensaios e GitHub. Não foram
iniciados novos testes, builds ou alterações funcionais nesta revisão.

## Conclusão

A migração integral **não está concluída**. Existem entregas funcionais e ensaios
reais aprovados, mas também implementação parcial, critérios sem homologação e
falhas observadas. Não há base para anunciar estabilidade completa ou atribuir
um percentual único de conclusão.

## 1. Bloqueios para considerar a entrega estável

| Prioridade | Pendência | Evidência e critério para fechar |
|---|---|---|
| P0 | Confiabilidade prolongada do daemon instalado | Ensaios anteriores falharam por limite de histórico, perda de cobertura e timeout. A última correção passou no ensaio curto e nos bloqueios deliberados de disco. O novo ensaio de 1.800 s ainda estava `running`, com quase 20 minutos, no momento desta revisão. Precisa terminar e comprovar recuperação, ausência de replay e limites de recursos. |
| P0 | CI integral aprovado | Última medição de tipos: 297 erros em 83 arquivos, contra limite de 47. O limite não foi aumentado. As suítes de integração/falhas, Canvas Edge e Web Models passaram em rodadas identificadas; isso não torna o CI inteiro aprovado. |
| P0 | Suíte unitária com resultado final verificável | O log local corrigido registra falhas e último progresso em 69%, sem JUnit final. O dump situa uma espera no teste A2A/SSE `test_a2a_http_sse_real_stream_resume_terminal_and_no_leak`. Nenhum processo dessa suíte foi observado ainda ativo nesta revisão. Não há resumo final utilizável, nem comprovação da causa de seu encerramento. |
| P0 | Admissão entre hosts | Subconjunto de federação: 51 passaram, dois testes de admissão/Grants falharam. É necessário distinguir defeito funcional de fixture desatualizada, mantendo as recusas de autoridade. |
| P1 | Novo pacote Windows completo | O Canvas instalado recebeu patch local recente; isso não recompila nem qualifica todos os outros executáveis. Faltam instalação limpa, login, atualização/rollback, migrações e qualificação independente da distribuição atual. |

Evidências: `DELIVERY_ACCEPTANCE_2026-10-22.md`, logs e relatórios em
`.tmp/sentra-delivery/`. Um resultado `running`, um handshake ou HTTP 200 não
fecham esses critérios.

## 2. O que já está entregue e não deve voltar ao início

- **Estrutura do aplicativo:** navegação SENTRA, conversa central e workspace
  dentro do Canvas do Dot; mapa acessível como ferramenta, modos Simples/Avançado,
  abas, splits, redimensionamento, foco e painéis retidos.
- **Continuidade e permissões:** retomada de recursos existentes, nomes de
  sessão, estados de tarefa, decisões na conversa e reconciliação sem reenvio.
  O ensaio de Acesso completo preparou acessos dos descendentes com uma seleção
  do proprietário e zero chamadas manuais de Grant.
- **Trabalho conjunto real:** três trabalhadores criados pelo modelo, worktrees
  distintas, aproximadamente 234 s de sobreposição, alterações conferidas por
  leitura/hash e conflito detectado. O ensaio usou estado de laboratório e não
  publicou commits, merge ou push dos trabalhadores.
- **ACP/OpenCode 1.19.3:** geração real, aprovação única de caminho, cancelamento
  confirmado pelo provedor, carga da mesma sessão e perda de transporte sem
  replay. Não equivale à homologação de todos os provedores ACP.
- **Coucou:** ilha com módulos originais fixados, Dots SENTRA, projeção real,
  bandeja, ocultar/reabrir e atalhos. Há ensaio nativo com dois monitores e
  comprovação da entrega instalada; fidelidade visual integral continua sendo
  um critério distinto.
- **LAN:** runtime Node/gateway empacotado, ativação pelo desktop, convite
  temporário, confirmação, escopo, revogação, identidade durável e troca de
  endereço sem aceitar silenciosamente outra chave. O ciclo de parar/reabrir
  preservando identidade passou no executável empacotado e na instalação.
- **Publicação móvel:** APK Android ARM64 de avaliação assinado em
  `mobile-preview-20261022-2`; GitHub Pages com capturas próprias, guia e download.
- **Repositório:** commit/push concluídos até a base indicada; `origin/main`
  conferiu com o HEAD. A árvore estava limpa antes de criar este relatório.

## 3. Funcionalidades ainda parciais

### Workspace, arquivos e navegador

- Completar recuperação de sessões órfãs e o fluxo para recursos indisponíveis,
  sem recriar processos ao restaurar abas.
- Sincronização de layout já adota revisão remota quando não há edição local.
  Falta homologar conflitos e vários dispositivos; não falta toda a persistência.
- Completar paridade de atalhos/menus, arraste para divisão nas bordas, busca
  rápida e comportamento com muitos painéis.
- O editor já grava por admissão central, protege rascunho e detecta conflito.
  Falta conferir a UX final, coordenar edição do mesmo arquivo por várias abas
  e descarte Git, além de revisão por linhas, novos/binários e watchers agrupados.
  Existem watchers em Documentos; o explorador do workspace ainda usa atualização
  explícita. Não é correto declarar inexistentes todos os watchers do produto.
- O navegador já mostra imagem real da sessão Playwright e oferece ações
  semânticas autorizadas. Não é ainda um navegador gráfico interativo completo:
  faltam Design Mode, migração/persistência de perfis do browser de trabalho e
  homologação do login nesse fluxo. Cookies Web existentes continuam no host.
- O workspace ainda consulta inventário por polling de quatro segundos.
  Existe streaming na conversa; falta unificar assinatura/subscrição de eventos
  sequenciados, capacidades e retomada das demais ferramentas.

### Terminais, coordenação e Git

- Homologar TUIs longas, consumidores lentos, drenagem/atualização do daemon,
  recuperação de CLI com modelo real no aplicativo instalado e várias origens.
- Há limites agregados: engine com até 32 espelhos e dois milhões de células,
  além dos limites de filas/cache. Falta medir/qualificar heap real e o conjunto
  sob carga; não é correto dizer que nenhum orçamento foi implementado.
- Ampliar reconciliação e testes de concorrência/replay para todas as famílias
  de efeitos. Aprovação e execução devem permanecer distintas de conclusão
  verificada, inclusive após revogação ou perda de confirmação.
- Completar fluxo estruturado de limpeza, commit, merge e publicação autorizada,
  revisão de novos/binários e mapeamento de workspace em guest/VM. A revisão
  atual dos trabalhos é uma consulta; não implementa toda a publicação Git.
- Acesso completo já resolve os fluxos locais ensaiados. Não significa que
  navegador, VM e toda máquina remota estejam automaticamente provisionados.
  Há rotas móveis que ainda orientam configurar o recurso no desktop.

### Android, iPhone e acesso remoto

- Android físico ainda não foi testado pelo proprietário. Faltam pareamento,
  suspensão, retorno, queda de Wi-Fi, revogação e controle remoto no aparelho.
- VPN privada é aceita por endereço/interface, mas a rota entre aparelhos
  ainda precisa ser validada; descoberta LAN/mDNS e mudança automática de IP
  não estão completas.
- No mobile, as conversas são carregadas/atualizadas por solicitação; o terminal
  já tem feed incremental. Falta continuidade equivalente de chat/atividade.
- Rascunhos do compositor e do terminal móvel usam estado React em memória;
  falta persistência protegida após encerramento do processo do aplicativo.
- O computador móvel oferece observação e toque/clique com posse central.
  Teclado, arraste, gestos, release e callbacks após suspensão/troca de host
  ainda precisam completar a implementação e a homologação.
- Falta navegação móvel completa de máquina/projeto/Space/Dot, rotação de
  credenciais e avisos de conclusão/atenção em segundo plano homologados.
- iOS tem código/exportação, mas não há aplicativo instalável publicado.
  Assinatura/canal Apple são dependência externa ainda indisponível.
- SSH e integração dos conectores GitHub/Linear no workspace continuam abertos.

### Visual e experiência

- O novo tema e a ilha foram compilados e entregues localmente. Falta uma
  conferência interativa consolidada de tema claro/escuro, teclado, foco,
  acessibilidade, layouts estreitos, conteúdo longo, editor, upload e diálogos.
- A conferência nativa de geometria/monitores não prova equivalência visual
  pixel a pixel nem revisão completa das demais telas.
- A origem e MIT estão registradas. A composição final de dependências/assets
  de cada pacote continua sendo um gate de distribuição.
- Hooks/adaptadores CLI e biometria reaproveitáveis do Coucou são backlog
  separado; não foram entregues apenas por integrar o visual da ilha.

## 4. Publicação: três estados diferentes

| Canal | Estado verificado |
|---|---|
| Código | HEAD e `origin/main`: `bfa09a5`. |
| Aplicativo instalado | Canvas compilado de `c8c8a59`; SHA-256 `9101113016ecc815adc73253072f84e3eb868a06719076c81ac4e98547ae507f`. Patch local com backup; preservação de contas e serviços registrada. |
| Windows público | Existe tag Git `installer-preview-20261022-a8a525d` e setup local dessa base antiga. Não há asset desse setup no GitHub Releases consultado; a página aponta para Releases anteriores. A tag não contém as correções posteriores. |
| Android público | APK `mobile-preview-20261022-2`, construído de `3854cd5`; não é uma homologação física. |
| iPhone público | Sem build instalável/canal de distribuição. |

Portanto, "há uma tag", "o código foi enviado" e "o aplicativo instalado foi
atualizado" não significam que o novo setup completo esteja disponível para download.

## 5. Correções de interpretação dos relatórios antigos

- Os três trabalhos reais e o ciclo ACP/OpenCode já passaram nos ensaios
  delimitados; os relatórios que ainda os deixam inteiramente pendentes são
  históricos, não o estado consolidado atual.
- Editor, imagem do navegador, APK, runtime móvel instalado, watchdog e limites
  dos espelhos já existem. O restante é conclusão de fluxo/homologação, conforme
  o item; não se deve implementar tudo novamente.
- A lista macro e os manifestos de revisão upstream misturam itens concluídos,
  parciais e antigos. É necessário consolidar os critérios em uma matriz atual,
  preservando a data/escopo das evidências, sem somar repetições de testes.
- Relay público e push remoto dependente dele foram retirados da entrega atual
  pela escolha do proprietário por LAN/VPN. Não são bloqueios do piloto local.
  Assinatura/distribuição iOS permanece uma limitação externa, não um build pronto.

## 6. Ordem proposta para concluir

1. Fechar resultado do ensaio instalado, falhas unitárias/A2A-SSE, admissão entre
   hosts e dívida de tipos, preservando os gates e os relatórios de falha.
2. Homologar o ciclo instalado de tarefa conjunta, recuperação, permissões,
   editor, navegador e recursos órfãos; terminar os fluxos parciais do workspace.
3. Executar o piloto Android LAN/VPN e completar rascunhos, atualização de
   conversa e entrada móvel. Separar o gate externo de iPhone.
4. Fazer a revisão visual/interativa consolidada.
5. Gerar e qualificar o pacote Windows completo, testar instalação/upgrade/
   rollback e publicar o artefato da versão correspondente. Consolidar a matriz
   e as notas públicas antes de anunciar conclusão.

Esta auditoria registra o estado observado; não marca nenhuma pendência como
concluída nem encerra o trabalho em andamento.
