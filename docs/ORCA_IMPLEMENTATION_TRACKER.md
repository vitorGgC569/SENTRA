# Execução integral ORCA → SENTRA

### 22/10 — setup de prévia e retomada da implementação

- [x] Quatorze executáveis, Web Models e setup Windows compilados localmente.
- [x] Verificação básica do payload, GUI congelada e Canvas/arquivos visuais empacotados.
- [x] Tag `installer-preview-20261022-a8a525d` publicada; artefato e hashes na Área de Trabalho.
- [x] README em inglês com fotos, perfis e créditos dos contribuidores.
- [x] Revisão de worktrees reconhece apenas bloqueios atômicos válidos e conserva evidência.

O setup é uma prévia sem assinatura. Instalação limpa, login, upgrade/rollback e
aparelhos físicos continuam pendentes. A correção dos bloqueios é posterior à
tag, sem alterar o artefato já fixado. [Build e escopo](WINDOWS_PREVIEW_2026-10-22.md).
As pendências macro abaixo permanecem abertas.

### 22/10 — checkpoint de worktrees e documentação pública

- [x] Vínculo no registro central de execução por conversa/Dot/Run, sem nova autoridade.
- [x] Computador local, arquivos atômicos, diretórios de comandos e novo ConPTY usam a pasta vinculada.
- [x] Abas de arquivos preservam conversa e workspace; drift não cai silenciosamente na pasta principal.
- [x] Revisão contextual ensaia patches em diretório descartável e distingue conflito/compatibilidade.
- [x] Contrato de inventário Git e prazos de coordenação corrigidos a partir de ensaios reais.
- [x] Limite dos turnos Canvas ajustado para 32 rodadas; prazos finitos preservados.
- [x] README em inglês com crédito à contribuição de Predo-kn no instalador Windows/Web r18.
- [ ] Aceite real completo de três trabalhadores: última tentativa interrompida por cota do provedor.

97 testes Python únicos, 152 Node e um renderer passaram. Não somar repetições.
Editor, limpeza/publicação Git, mapeamento guest e critérios macro continuam abertos.
[Evidências e limites](ORCA_WORKTREE_EXECUTION_2026-10-21.md).

### 21/10 — estados formais e autonomia autorizada

- [x] Estados solicitados, entrega, execução, aprovação/confirmação, verificação e encerramentos distintos.
- [x] Acesso completo prepara Grants/WorkItems dos turnos, filhos e recursos locais configurados.
- [x] Seleção do proprietário vinculada aos descendentes; restrição no filho e revogação conferidas.
- [x] Evidência por leitura real, hash e nova conferência antes de publicar; texto não atesta sucesso.
- [x] Caminho de pausa do runtime central corrigido e ensaiado.
- [x] Modelo real cria dois Dots, delega, produz arquivos, pausa, reabre broker e consolida pela conversa.

79 Python, 151 Node e dois renderers passaram. Uma seleção full e zero Grants
manuais no ensaio. Interrupção em checkpoint antes da consolidação; efeitos
incertos não são repetidos. Build `sentra-orca-experimental-cffb8f3284b3`.
[Relatório e limites](SENTRA_FULL_ACCESS_ORCHESTRATION_2026-10-21.md).
O aceite integral da migração continua aberto.

### 21/10 — continuidade e colaboração entre Dots

- [x] Perfil visual protegido no host, com escopo e controle de revisão.
- [x] Retomada do último painel sem recriar recursos; primeiro uso com rascunho guiado.
- [x] Pedidos locais e de coordenação na conversa, com alcance e prazo visíveis.
- [x] Consulta de decisão após perda de confirmação, sem repetir o efeito.
- [x] Nomes de tarefa, estado principal e detalhes expansíveis.
- [x] Ferramentas contextuais preservam compositor, rascunho e posição de leitura.
- [x] Coordenador → subagente → coordenador com modelo real, conversas permanentes e cinco recibos concluídos.
- [x] Coordenador CLI e dois trabalhadores reais, efeitos em arquivos e resposta de modelo.

49 testes Python, 151 Node desktop, 15 Node do transporte e dois renderers passaram;
tipos e builds isolados concluíram. Sete testes Python foram repetidos sem aumentar
o total único. Janela `SENTRA · Trabalho conjunto` aberta. Build `sentra-orca-experimental-6d3814ddf526`.
[Relatório e limites](ORCA_CONTINUITY_COLLABORATION_2026-10-21.md). Os critérios
macro continuam abertos, incluindo layout entre dispositivos e execução completa
na distribuição instalada.

### 21/10 — complexidade progressiva no Canvas

- [x] Modo Simples padrão, layouts separados e Modo Avançado preservado.
- [x] Arquivos/subagentes recolhidos, ferramentas em Nova sessão e QR por ícone.
- [x] Diagnóstico reúne IDs e recibos, com aviso simples de ação incerta.
- [x] Receitas de acesso compõem o serviço central existente após revisão do dono.
- [x] Escopo, leitura real, recusa de escrita/comando e recuperação sem duplicar Grants.
- [x] Renderer isolado confere os dois modos, uma navegação por teclado e tema claro.

21 testes Python, 145 Node e dois builds desktop isolados passaram. Janela
`SENTRA · Modo Simples` aberta com estado próprio. Build
`sentra-orca-experimental-1a724e4b6a1f`. A preparação de acesso desta rodada cobre
arquivos/comandos locais; os demais recursos conservam seus contratos.
[Evidências e limites](ORCA_SIMPLE_MODE_2026-10-21.md). Os critérios macro abaixo
continuam abertos.

### Rodada mais recente — terminal móvel e configuração nativa LAN

Progresso experimental, sem encerrar os itens macro do plano:

- [x] Observação incremental/checkpoint com Grant e vínculo central da sessão.
- [x] xterm offline, confirmação do renderer e entrada nativa sem repetição.
- [x] Ensaio E2EE/ConPTY real perde confirmação e comprova uma execução física.
- [x] Revogação bloqueia leitura; mudança de escopo invalida entrada pendente.
- [x] Ambiente PowerShell recomposto sem alterar política ou confiança.
- [x] Plugin Android LAN aplicado e mods nativos Android/iOS conferidos.

19 testes Python, 15 Node do transporte, um Node dos mods nativos e tipos
passaram; exportações Hermes concluíram. Build
`sentra-orca-experimental-0840b51b0deb`. A janela de avaliação já aberta usa
o backend anterior. APK/IPA, aparelhos físicos, assinatura de eventos e demais
frentes continuam pendentes. [Evidências e limites](ORCA_MOBILE_TERMINAL_2026-10-21.md).

Objetivo ativo: implementar as pendências do plano e da segunda checagem de
21/10/2026. Este registro não reduz o escopo ao que já está implementado.

Invariantes: Home/navegação externa preservadas; workspace apenas no Canvas
interno do Dot; Grants/WorkItems/recibos centrais continuam sendo autoridade;
conversas Web conservam seus vínculos; nenhuma repetição automática de efeitos
incertos; instalação e sessões existentes preservadas durante o desenvolvimento.

## Entregas e critérios de aceite

- [ ] P0: projeções de recibos produtivas e consultas por intenção original.
- [ ] P0: intenções incertas persistentes no desktop/mobile e reconciliação sem reenvio.
- [ ] P0: daemon/CLI recuperam conexão após reinício do broker sem duplicar execução.
- [ ] P0: histórico PTY persistente, restauração ANSI/TUI e limites explícitos.
- [ ] P0: consumidores lentos/backpressure, lacunas e testes de isolamento.
- [ ] Contratos: capacidades reais, eventos sequenciados, assinatura e retomada.
- [ ] Layout: persistência no host/dispositivos, esquema e recuperação de sessões órfãs.
- [ ] Workspace: paridade de abas/splits/menus/atalhos, arraste nas bordas e foco.
- [ ] Workspace: subagentes, sessões e tarefas reais com identidade Dot/host.
- [ ] Arquivos: editor, conflitos, watchers agrupados, revisão por linhas e previews.
- [ ] Navegador: página gráfica compartilhada, identidade estável e Design Mode.
- [ ] Computador: entrada completa com posse, release e invalidação de callbacks.
- [ ] ACP: geração real, aprovação, cancelamento, interrupção e retomada.
- [ ] Git: agente/editor/terminal usam worktree correta; três trabalhos concorrentes.
- [ ] Git: conflitos, limpeza e publicação estruturada/autorizada.
- [ ] Coordenação: transições/gates/checkpoints transacionais, concorrência e replay.
- [ ] Mobile: terminal interativo/streaming e rascunhos escopados persistentes.
- [ ] Mobile: máquina/projeto/Space/Dot, descoberta LAN, rotação e revogação.
- [ ] Mobile: Android e iPhone físicos; suspensão/reconexão/gestos/entrada seguros.
- [ ] Remoto: SSH, relay E2EE opcional, push e conectores GitHub/Linear.
- [ ] Distribuição: dependências/licenças revisadas e builds nativos assinados.
- [ ] Implantação: migrações, recuperação, drenagem e ativação gradual homologadas.

Referência completa e oportunidades adicionais:
[segunda checagem](ORCA_SENTRA_REAUDIT_2026-10-21.md).

## Rodadas

### 21/10 — correção da avaliação sem estilos

- [x] Falha observada pelo usuário reproduzida no renderer (`ERR_CONNECTION_RESET`).
- [x] Compressão de assets e prazo de escrita separado da leitura de requisições.
- [x] Cliente lento recebe conteúdo completo após retenção por mais de cinco segundos.
- [x] Erro depois dos headers não anexa outra resposta HTTP ao conteúdo parcial.
- [x] Nova janela com CSS aplicado, três mascotes carregados e acesso ao QR presente.

19 testes Python passaram; hashes dos assets descomprimidos coincidiram e
gateway LAN permaneceu pronto. A prontidão foi lida no renderer da avaliação,
superando a evidência insuficiente de HTTP 200 da rodada anterior. Fidelidade
visual completa e testes Android/iPhone permanecem abertos.

### 21/10 — acesso à avaliação integrada e QR

- [x] Janela atual do checkout com estado/perfil próprios, sem reutilizar o banco instalado.
- [x] Recusa de estado existente sem marcador de avaliação; testes de isolamento.
- [x] Acesso `Celular · QR Code` no workspace e na oferta do Canvas anterior.
- [x] Nome explícito `Exibir QR Code`, distinção entre pareamento e instalação do app.
- [x] Segunda tentativa de carregamento das imagens antes da inicial de fallback.
- [x] Gateway LAN real pronto e convite real convertido em QR PNG válido em memória.

Três testes Python de avaliação e 142 Node desktop passaram; dois builds isolados
concluíram. Janela `SENTRA · Avaliação ORCA` aberta. Conferência visual pelo
usuário e Android/iPhone físicos continuam pendentes. Build atual
`sentra-orca-experimental-2327da7a60c1`.
[Como conferir](ORCA_WORKSPACE_EVALUATION_2026-10-21.md).

### 21/10 — checkpoints do emulador de terminal

- [x] 28 arquivos ORCA fixados/verificados, MIT e dependências inventariadas.
- [x] Worker de observação sem autoridade/entrada de PTY, com hashes do build conferidos.
- [x] Eventos ordenados de saída/resize e checkpoints protegidos no esquema 2.
- [x] Restauração de buffers, Unicode, modos, cursor, atributos salvos e escape incompleto.
- [x] Bloqueio de entrada durante replay e descarte de entrada pendente da conexão antiga.
- [x] Consulta HTTP com autenticação/escopo, morte real do daemon e histórico sem recriação física.
- [x] Orçamento agregado de espelhos, descarte após drenagem e limite de resize por sessão.
- [x] Indicação de imagem parcial/histórico limitado; builds isolados incluindo chunks/assets no manifesto.

O critério macro continua aberto: faltam carga prolongada de TUI, conferência
visual, backpressure por consumidor e distribuição/atualização do runtime no
instalado. [Detalhes desta rodada](ORCA_TERMINAL_CHECKPOINTS_2026-10-21.md).
Build `sentra-orca-experimental-80aaff652255`.
Validação: 46 testes Python, 142 Node desktop e quatro Node engine passaram;
dois builds desktop isolados concluíram. Manifesto: 121 fontes/261 saídas.

### 21/10 — histórico PTY e reconexão do cliente CLI

- [x] Histórico protegido em SQLite, migração versionada e recuperação após morte real do daemon.
- [x] Limites de fila global/por sessão incluem a gravação em andamento; lacunas explícitas e sessão pequena preservada sob saturação.
- [x] Leitura não avança além de saída ainda pendente de persistência.
- [x] Histórico restaurado é somente leitura e nunca inicia novamente o processo.
- [x] Drenagem espera o leitor de saída e o checkpoint; não declara parada segura prematuramente.
- [x] Falha de observação com a trava do daemon ocupada recusa iniciar um substituto.
- [x] Registro protegido da credencial restrita do terminal, com prova de sessão viva do daemon.
- [x] Endpoint assinado, verificação de identidade do processo do broker e atualização por pedido, sem retry físico.
- [x] Cliente CanvasBridge em ConPTY separado conserva PID após reinício e não ganha acesso ao bearer administrativo.
- [x] Estado visual distingue gravação pendente, falha, lacuna e histórico somente leitura.

O aceite macro continua aberto. Faltam snapshots completos de TUI, backpressure
por consumidor, turno real de modelo no CLI e homologação do daemon instalado.
O teste de transporte não é apresentado como teste de geração do modelo.
Detalhes e limites: [recuperação PTY/CLI](ORCA_PTY_CLI_RECOVERY_2026-10-21.md).

Evidência: 41 testes Python P0/CLI e 20 regressões móveis/recibos passaram; seis
testes P0 foram repetidos após o último ajuste e não aumentam o total único.
14 testes Node e dois builds desktop isolados passaram.
Build: `sentra-orca-experimental-dd1a15aecf6b`.

### 21/10 — pull e continuidade de autenticação/LAN

- [x] Pull do checkout de análise para `fd8b2dc3`, em branch própria, mantendo o pin das cópias existentes.
- [x] Chave do host durável com adoção do arquivo protegido anterior e erro explícito em corrupção.
- [x] Destino do broker atualizado por pipe privado, sem renovar E2EE nem reenviar efeitos.
- [x] Endereço LAN pode mudar conservando credencial, chave e escopo do dispositivo; pin conferido antes de salvar.
- [x] Invites conferem endpoint e identidade do listener; UI distingue LAN, loopback e broker reiniciando.
- [x] Seleção IPv4 por interface e `start:lan` para desenvolvimento móvel.
- [x] Claim perdido recuperável por 120 segundos, com chave original, dono e revogação.
- [x] Callbacks/timer da conexão antiga isolados; retorno ao primeiro plano faz autenticação/leitura.
- [x] Gateway supervisionado fecha seu listener ao perder o pipe do pai.
- [x] Tratamento uniforme do foco nos splits, adaptado do commit mais recente.

As alterações de login desta rodada são de continuidade do pareamento móvel.
A migração de perfis do navegador gráfico e a autenticação real dos modelos
Web nos aparelhos ainda não foram homologadas. Nenhuma sessão instalada foi
reiniciada para estes ensaios. Histórico PTY é código anterior ainda sem a
validação correspondente nesta rodada.

O relatório [consolidado](ORCA_SENTRA_STATUS_2026-10-21.md) reúne a matriz integral,
aprendizados adicionais, critérios em aberto e a diferença entre código/build/
homologação física. Os itens macro acima permanecem abertos.

Evidência desta rodada: 13 testes Python, oito Node do transporte e dez Node do
desktop passaram; tipos, dois builds desktop isolados e exportações Hermes
Android/iOS concluíram. Build `sentra-orca-experimental-ed3a36245581`.

### 21/10 — confiabilidade

Classificação da rodada: progresso no código, na integração e na evidência.

Entregue nesta rodada:

- [x] Leitura `workspace_request_status` sobre o diário protegido já existente.
- [x] Migração transacional/versionada do diário para guardar a intenção protegida.
- [x] Impressão digital compartilhada entre desktop, mobile e host, incluindo Unicode.
- [x] Persistência de seletores no desktop antes de transmitir; sem gravar prompts/comandos/URLs nesse armazenamento.
- [x] Coordenação entre janelas para impedir sobrescrita e duplo envio no mesmo recurso.
- [x] Recuperação das ações do Canvas e navegador depois de reabrir o diário.
- [x] Consulta mobile de operações de máquina com escopo e revogação conferidos.
- [x] Estados físicos abertos/incertos permanecem pendentes mesmo com resposta registrada.
- [x] Projeção de recibos usada pelo inventário e pelas consultas produtivas.

O P0 integral continua aberto: ainda faltam recuperação das outras famílias de
operações (por exemplo decisões de aprovação), ciclo CLI/broker, histórico PTY,
consumidores lentos e os demais critérios de aceite. Nenhum item macro acima foi
marcado como concluído apenas por esta entrega parcial.

A inspeção visual da aba antiga foi recusada pela política de URL do navegador;
não foi usado outro mecanismo para contornar o bloqueio. Foi acrescentado um
cenário explícito de perda de confirmação na prévia isolada, mas sua nova
verificação visual permanece pendente. A prévia não inicia processos reais.

Validação desta rodada: 26 testes Python passaram, incluindo Chromium real e
gateway cifrado/Canvas HTTP reais; 10 testes Node do desktop e cinco do
transporte passaram. Tipos mobile/transport, builds desktop isolados e
exportações Android/iOS concluíram. Estes bundles não são APK/IPA assinados.
Build: `sentra-orca-experimental-9bd339f85792`.
