# ORCA → SENTRA: segunda checagem de aproveitamento

> Registro histórico anterior às últimas mudanças. Para o estado após o pull,
> login/LAN e novas pendências, consultar [a atualização consolidada](ORCA_SENTRA_STATUS_2026-10-21.md).

**Data: 21/10/2026. Estado: implementação experimental; migração ainda não concluída.**

## 1. Conclusão

O plano continua adequado, com a correção visual já solicitada: **Home, navegação
externa, projetos, Spaces, Dots e conversas permanecem com a interface SENTRA;
o workspace derivado do ORCA ocupa somente o Canvas interno de cada Dot**.

Já existe reaproveitamento real no código: oito módulos criptográficos copiados
integralmente e onze origens de adaptação registradas. Também há implementações
SENTRA próprias inspiradas nos padrões ORCA. Isso não significa que onze
componentes oficiais completos tenham sido transplantados, nem que o aplicativo
ORCA esteja rodando dentro do SENTRA.

O próximo ganho vem de fechar a integração e a recuperação dos recursos já
introduzidos. Ampliar a lista de funcionalidades antes disso aumentaria as bases
parcialmente conectadas.

## 2. Escopo e evidência desta checagem

- SENTRA: HEAD `07df23c45f605a056ece92d51f6e34e133e28012`, mais alterações locais.
- Base ORCA efetivamente incorporada: `70b2197c97b164b16c618736a107967295e5af92`.
- Build experimental registrado: `sentra-orca-experimental-9082abca6e87`.
- Conferidos por hash: **62 arquivos-fonte, sete artefatos de build, oito módulos
  copiados e onze referências de origem das adaptações; nenhuma divergência**.
- ORCA `main` consultada nesta rodada: `ad269f471c7ca4532bd560ab547f964e5e5bf423`,
  commit de 21/10/2026 às 09:32 no horário de Brasília. A comparação oficial
  informa **99 commits à frente** da nossa base.
- Foram examinados os assuntos desses commits e patches selecionados de seis
  correções, além de módulos representativos da base fixada. A API de comparação
  retornou 300 nomes de arquivos, limite que impede tratá-la como inventário
  integral de todos os arquivos modificados.
- Esta rodada conferiu código, proveniência e artefatos. Os resultados de testes
  de execução citados adiante são os registrados nas etapas anteriores; a suíte
  completa não foi reexecutada nesta auditoria.
- O checkout de investigação permaneceu no pin. Nenhuma atualização ORCA foi
  incorporada automaticamente e a instalação em uso não foi substituída.

Referências: [ORCA fixado](https://github.com/stablyai/orca/tree/70b2197c97b164b16c618736a107967295e5af92),
[comparação com a revisão consultada](https://github.com/stablyai/orca/compare/70b2197c97b164b16c618736a107967295e5af92...ad269f471c7ca4532bd560ab547f964e5e5bf423).

## 3. O que já aproveitamos e o que falta, frente por frente

| Frente do plano | O que já existe no SENTRA | O que ainda falta | Situação |
|---|---|---|---|
| Origem, licença e versões | MIT preservada, oito cópias verificadas, onze origens de adaptação, inventário de 917 registros de dependências e build com hashes | Revisar distribuição dos 13 registros `UNDECLARED`, binários opcionais e futuros assets | Base implementada |
| Workspace ORCA no Canvas | Abas, splits horizontais/verticais, redimensionamento, arraste de abas, foco, maximização/restauração, explorador, lista de subagentes e sessões, temas e identidade Dot/máquina | Paridade visual/comportamental completa com ORCA, drag para dividir nas bordas, menus completos, busca, atalhos e validação com recursos reais do usuário | Experimental |
| Preservação da interface SENTRA | O componente existente `OpenDotsShell` continua sendo a moldura. O ponto de montagem do Canvas interno é trocado por preferência experimental | Avaliação do usuário e futura ativação controlada; nada foi aplicado ao aplicativo instalado | Preservado no código/prévia |
| Layout e retenção | Layout por escopo, validação da árvore, raízes de portal estáveis, fechamento visual separado do processo, restauração por IDs existentes | Layout entre dispositivos, persistência no host, recuperação de sessões órfãs e casos extensos de abas ocultas/reconexão | Parcial |
| Contrato compartilhado | Tipos para escopo, inventário, recibos, capacidades e cursor; adaptador com inventário/solicitação | Assinaturas de eventos, retomada por sequência, negociação efetiva de capacidades e erros uniformes entre clientes | Parcial; os tipos ainda não compõem o protocolo inteiro |
| Recibos e reconciliação | Autoridade durável SENTRA preservada; ledger no daemon; journal no mobile; helper distingue entrega de conclusão; BrowserPane usa recibos existentes | Integrar `delivery_projection` aos fluxos reais, padronizar projeções e consultas em todos os novos painéis/provedores, recuperar incerteza após reiniciar a UI | P0 parcial |
| Daemon PTY independente | ConPTY separado, autenticação local com DPAPI, identidade de runtime, deduplicação, cache agregado limitado a 16 MiB, cursores e indicação de lacunas | Homologar o ciclo real com agentes SENTRA CLI, renovar a conexão desses agentes com o broker reiniciado, empacotar e testar o daemon no executável instalado | Implementado e ensaiado em shells reais; opt-in |
| Histórico e atualização PTY | Cache em memória; drenagem recusa novas sessões e preserva as ativas; parada só sem processos vivos | Scrollback persistente, restauração ANSI/TUI, controle de consumidores lentos, troca assinada do executável e recuperação operacional | Parcial |
| ACP/OpenCode | Dialeto adaptado, OpenCode 1.19.3 fixado, processo real, criar/consultar/carregar sessão pelo controle central | Turno com modelo real, ferramentas e aprovação, interrupção, cancelamento e perda de conexão durante geração; depois outros dialetos | Homologação parcial |
| Worktrees Git | Worktree real persistente, branch/base/Dot/WorkItem rastreáveis, lock por repositório, admissão central e verificação de drift | Ligar automaticamente agente/editor/terminal/arquivos à worktree correta; ciclo de conflitos, limpeza, decisão estruturada e publicação autorizada; três tarefas concorrentes completas | Base real implementada |
| Coordenação e checkpoints | `convergence` separa tarefas encerradas de tarefas bem-sucedidas; checkpoints SENTRA existentes são preservados | Aplicar os algoritmos às transições/gates reais, checkpoints de recuperação ponta a ponta, concorrência/replay e ações de publicação separadas | Leitura/observação implementada; orquestração transacional ainda não concluída |
| Arquivos e revisão | Serviços SENTRA existentes reutilizados; árvore lateral, arquivos em abas de leitura e acesso à revisão/diff existente | Editor completo no novo painel, conflitos de edição, revisão por linhas, anexos por arraste, previews ricos e watchers eficientes | Parcial |
| Navegador e computador | Serviços Playwright/VM existentes expostos; identidade e permissões existentes; correção CDP validada; tap atômico com liberação no host | Navegador gráfico no estilo ORCA, espelhamento da mesma página/sessão, Design Mode, controles remotos completos e homologação visual/VM física | Serviços integrados parcialmente; visual incompleto |
| Mobile Android/iOS | App Expo/RN próprio, E2EE derivado do ORCA, SecureStore, QR temporário, aprovação/revogação, conversas existentes, arquivos, atividade, decisões, terminal textual, navegador e quadro da VM | Terminal interativo completo/streaming, rascunhos de comando por sessão, navegação hierárquica por máquina/projeto/Space/Dot, descoberta LAN, rotação operacional, notificações e builds nativos | Código + bundles Hermes; sem homologação física |
| Mobile LAN e entrada | Gateway explícito, pareamento escopado, proteção de replay, identidade por dispositivo, epoch de posse e tap com release em `finally` | Testes reais Android/iPhone, Wi-Fi, suspensão/retorno, troca de host, revogação, QR expirado e identidade do host; teclado/arraste seguros | Caminho local ensaiado em loopback; LAN física pendente |
| SSH, relay e conectores | As bases existentes do SENTRA continuam disponíveis | Adaptações ORCA de SSH, relay cifrado opcional, push remoto, GitHub e Linear | P2 não entregue |
| Instaladores e ativação | Builds desktop isolados e bundles Android/iOS identificados; preferência experimental mantém a apresentação anterior | Pacotes nativos Windows/APK/IPA assinados, migrações/recuperação homologadas, atualização segura e implantação gradual | Pendente |

### Correções importantes ao resumo anterior

1. O número atual é **onze origens de adaptação**, não seis. Algumas origens
   contribuem para o mesmo componente SENTRA.
2. `delivery_projection` está implementada e testada como função, mas a busca no
   código não encontrou chamada produtiva fora de sua definição. Não se deve
   apresentá-la como uma projeção unificada já instalada em todos os fluxos.
3. `convergence` é uma leitura do inventário; não controla transições, gates ou
   checkpoints. O item de orquestração transacional não está concluído.
4. `EventCursor` e capacidades compartilhadas estão tipados, mas o workspace
   ainda consulta o inventário a cada quatro segundos. Não há uma assinatura
   unificada retomável entregue por esse contrato.
5. A prévia atual tem xterm real e transcrições fictícias. A aparência funcional
   dos painéis não comprova agentes executando nem sessões reais conectadas.
6. Exportar Hermes para Android/iOS não produz APK/IPA assinado. O script mobile
   `start` atual usa `--localhost`; o piloto físico requer exposição LAN explícita
   ou um build de desenvolvimento apropriado.
7. O cache PTY limitado informa lacunas, mas isso não equivale ao mecanismo
   completo ORCA de backpressure e persistência de histórico.

## 4. Novos aproveitamentos recomendados

As prioridades abaixo são recomendações desta revisão; não representam código
adicional implementado durante a auditoria.

| Oportunidade | O que aprender/aproveitar do ORCA | Adaptação ao SENTRA e critério de aceite | Prioridade |
|---|---|---|---|
| Histórico durável de terminal | Snapshot ANSI, buffer normal/alternativo, replay e checkpoints periódicos | Restaurar histórico após morte do daemon sem afirmar que o processo sobreviveu; limite de armazenamento e lacuna explícita | P0/P1 |
| Consumidor lento sem travar tudo | Backpressure por cliente/sessão, contabilização de filas e watchdog contra produtor congelado | Terminal rápido continua utilizável quando outro painel/celular está lento; limites demonstráveis de memória e perdas sinalizadas | P0 |
| Reconexão e sessões sem aba | Consulta autoritativa de vida, inventário de recursos órfãos, anexar ao recurso vencedor | Fechar UI, reiniciar broker e restaurar abas ocultas conserva uma única execução e evita pane falsamente encerrado | P0 |
| Uma página de navegador para vários visualizadores | Reaproveitar a identidade da página hospedada antes de criar outra | Desktop/mobile observam a mesma página autorizada sem duplicar navegação, login ou envio; cookies ficam no host | P1 |
| Montagem com orçamento | Suspender painéis invisíveis, preservar os que ainda produzem frames e publicar apenas mudanças | Muitos terminais não multiplicam renderização/polling; trocar/maximizar não perde TUI, rascunho ou frame remoto | P1 |
| Capacidades reais por recurso | Catálogo e sondagens versionadas, inclusive opções e permissões de sessões estruturadas | Ocultar/desabilitar recursos ausentes com motivo; incompatibilidade nunca autoriza efeito por fallback silencioso | P0/P1 |
| Rascunhos escopados de terminal | Persistência por host/workspace/sessão e restauração sem envio | Trocar de Dot/telefone/conexão conserva o texto no terminal correto e nunca o executa ao reconectar | P1 |
| Gestos e callbacks obsoletos | Invalidar handlers da superfície antiga antes de replay/restauração | Scroll não vira clique; callbacks antigos não redimensionam/controlam a sessão nova; perda de conexão libera entrada | P1 |
| Eventos de arquivos agrupados | Consolidar mudanças, atualizar diretórios afetados e limitar concorrência | Alterações em massa não competem indefinidamente com a saída PTY; edição externa gera conflito visível | P1 |
| Revisão por linhas | Seleção de intervalos e comentários de diff desacoplados do editor | Revisão identifica arquivo/revisão/linhas e envia instrução ao Dot pelo fluxo autorizado; comentar não aplica código automaticamente | P1 |
| Busca e abertura rápida | Ranking com histórico, arquivos autorizados e foco previsível | Ctrl+P/Ctrl+K internos ao Canvas localizam arquivo, aba ou sessão sem recriar recurso nem alterar a Home | P1 |
| Design Mode | Capturar elemento visual, contexto DOM/CSS e imagem para o agente | Extensão futura do navegador SENTRA, com escopo, consentimento de envio e conteúdo de página tratado como dados não confiáveis | P2; anunciado no README, extração técnica ainda não auditada |
| Escrita atômica e compatibilidade | Snapshot temporário + rename, agrupamento de gravações, testes de esquema/downgrade | Falha ao fechar não corrompe layout; versão antiga recusa esquema incompatível; rollback visual não é downgrade do banco | P0/P1 |
| Entrega inicial do prompt | Distinguir rascunho, entrega ao PTY e mensagem registrada numa sessão estruturada | CLI/ACP/Web exibem comprovantes apropriados; eco no terminal ou saída zero não confirma resposta do modelo | P0 |
| Pastas/remotos indisponíveis | Consultas assíncronas e tratamento de caminhos de rede lentos | Um diretório de trabalho inacessível não congela a janela nem muda silenciosamente o escopo autorizado | P1 |
| Engenharia de build | Verificação de versões compartilhadas, fronteiras entre cliente/host e builds qualificáveis | Desktop/mobile usam contratos compatíveis; diferenças de dependências são detectadas antes de distribuir | P1 |

### Fontes técnicas representativas

- [Histórico](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/main/daemon/daemon-durable-history-snapshot.ts)
- [Backpressure](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/main/daemon/daemon-stream-backpressure.ts)
- [Painéis ocultos](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/components/browser-pane/host-guest/browser-worktree-surface-paintability.ts)
- [Publicação de recursos](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/runtime/sync-runtime-graph/graph-publication.ts)
- [Capacidades mobile](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/mobile/src/transport/mobile-runtime-capability-negotiation.ts)
- [Entrega do prompt](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/main/agent-launch/agent-launch-prompt-delivery.ts)
- [Recusa/replay](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/agent-launch-replay-refusal.ts)
- [Atualização do explorador](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/components/right-sidebar/file-explorer-watch-refresh-scheduler.ts)
- [Comentários de diff](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/components/diff-comments/diff-comment-line-range.ts)
- [Abertura rápida](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/components/quick-open-history-ranking.ts)
- [Snapshot atômico](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/main/persistence/atomic-snapshot-writer.ts)

## 5. O que mudou no ORCA depois do nosso pin

Seleção de correções cujo patch foi consultado. São candidatas a adaptação
seletiva, sem atualizar toda a dependência. Correções com flag experimental do
ORCA não equivalem a funcionalidades estáveis habilitadas para todos os usuários.

| Commit | Aprendizado para o SENTRA | Estado no SENTRA |
|---|---|---|
| [ad269f4](https://github.com/stablyai/orca/commit/ad269f471c7ca4532bd560ab547f964e5e5bf423) | Adotar a página de browser existente do host, evitando criar uma segunda; mudança sob flag de layout-owner | Não incorporado; relevante para desktop/mobile e login único no host |
| [b2370f1](https://github.com/stablyai/orca/commit/b2370f1c6e68503b36bb10688867b8b3040445bf) | Reanexar aba oculta a PTY sobrevivente consultando vida no host; cache local não prova ausência | Não incorporado; ampliar os ensaios do daemon e da UI |
| [513c24b](https://github.com/stablyai/orca/commit/513c24bc1680b4e553d250adac0eba13ca07d162) | Rascunhos de comando por host/workspace | Não incorporado; o campo de comando mobile atual não é esse armazenamento persistente |
| [7a2057e](https://github.com/stablyai/orca/commit/7a2057e65cce017b9f9d616e939b85ccaadf4f92) | Descartar gestos de superfície antiga antes de replay | Não incorporado; necessário antes do terminal/gestos mobile completos |
| [505d671](https://github.com/stablyai/orca/commit/505d6719c075eb0344dac86867a4e4030e970a1d) | Validar ciclos de hierarquia com dados autoritativos mesmo com cache frio | Não incorporado; revisar relações entre Dots/worktrees sem presumir que o cache da UI contém tudo |
| [0a9980b](https://github.com/stablyai/orca/commit/0a9980b14100d9e326d0f92301d68d0a149bbe81) | Evitar acesso síncrono bloqueante a diretório de terminal em rede indisponível | Não incorporado; útil à robustez Windows/remota |

Também apareceram mudanças em tamanho inicial de terminais, callbacks mobile,
ordem das abas entre dispositivos, compatibilidade de dependências e formatos de
layout. Esses assuntos foram catalogados; não houve revisão completa de todos
os respectivos patches nesta rodada.

## 6. O que preservar e o que não importar automaticamente

- Grants, WorkItems, admissão, recibos e identidades SENTRA seguem como autoridade.
- Cada Dot conserva suas conversas. Sessão ACP/PTY é recurso de execução; não
  substitui o vínculo permanente de conversa Web nem seu gateway existente.
- O store global, bootstrap, contas, updater e telemetria do aplicativo ORCA não
  devem ser acoplados à Home SENTRA.
- Catálogo de capacidades de apresentação não concede execução. A negociação
  ORCA examinada trata parte das capacidades como avisos opcionais; controles
  de execução SENTRA devem continuar falhando explicitamente quando ausentes.
- Não converter `forbidden` em permissão para tentar outro caminho. O helper
  ORCA de recusa/replay classifica alguns erros para compatibilidade; sua política
  não deve ser transplantada para os Grants do SENTRA.
- Prompt não pode autorizar exceção Git, commit, merge ou push. A decisão precisa
  ser estruturada e admitida pelo controle central.
- Histórico restaurado não é prova de processo vivo; terminal entregue não é
  prova de tarefa concluída; todas as tarefas encerradas não significa sucesso.
- Assets, fontes e dependências exigem inventário próprio. A licença MIT do
  repositório não resolve automaticamente todos os itens redistribuídos.

## 7. Validação: o que temos de evidência

### Conferido agora

- Hashes das 62 fontes e sete outputs do manifesto: sem divergências.
- Oito cópias de transporte: igualdade com o ORCA fixado e hashes corretos.
- Onze origens das adaptações: hashes conferidos.
- Inventário: 917 registros de dependências; 13 sem licença declarada no lockfile.
- Integração da moldura: o diff de `shell-app.jsx` tem duas substituições de
  linhas, relativas ao import e ao ponto de montagem interno do Canvas.

### Execuções registradas anteriormente

- Núcleo/regressões selecionadas: lote de 44 testes Python.
- VM/mobile: lote de 47 testes, com sobreposição ao lote anterior; não somar
  esses números para anunciar uma quantidade de testes únicos.
- ConPTY real: deduplicação, reconexão e reinício do Canvas com mesmo processo.
- OpenCode real: sessão/estado/load pelo controle central, sem geração homologada.
- Chromium real: 16 testes e quatro subtestes, além de um teste do bridge;
  um caso de ausência de dependência foi ignorado por não se aplicar.
- Transporte mobile: cinco testes; teste adicional cliente cifrado → gateway Node
  → Canvas HTTP reais em loopback cobre pareamento, escopo e revogação.
- Tap atômico: ensaios de sucesso e perda de confirmação verificam liberação.
- Frontend da última etapa: cinco testes Node, builds isolados e inspeção visual
  de temas, Home/Canvas, leitura de arquivo, maximização e teclado.
- Exportação Android/iOS e checagem de tipos concluídas nas etapas anteriores.

Isso não homologa o conjunto em Windows instalado, Android e iPhone físicos,
VM real, rede LAN com interrupções ou distribuição nativa assinada.

## 8. Ordem recomendada para fechar o plano

1. **Concluir P0 de confiabilidade.** Conectar recibos/projeções, persistir
   intenções incertas da UI, reconciliar sem reenviar e recuperar os agentes CLI
   após reinício do broker. Acrescentar consumidores lentos e abas ocultas ao aceite.
2. **Concluir o Canvas interno.** Integrar os painéis com recursos reais e
   escopados, completar sessões/subagentes/atividade e interação de splits/abas,
   navegador gráfico e arquivos/revisão. A Home permanece como está.
3. **Fechar ACP + worktrees.** Geração real com aprovação/cancelamento, três
   trabalhos isolados usando o diretório correto e tratamento de conflitos;
   publicação segue uma autorização própria.
4. **Homologar Mobile LAN nos seus dois aparelhos.** APK/build iOS de avaliação
   ou ambiente de desenvolvimento compatível; terminal completo, rascunhos,
   pareamento, suspensão, revogação, reconexão e entrada segura. Descoberta LAN
   e seleção de contextos precisam ser integradas à experiência.
5. **Empacotar e ativar gradualmente.** Instalador/daemon Windows e builds
   Android/iOS próprios, assinaturas, diagnóstico, recuperação e preferência
   experimental. Validar migrações e drenagem antes de atualizar.
6. **Executar P2.** Relay opcional cifrado, push, SSH e integrações de trabalho.
   A ausência do relay não deve bloquear a avaliação local do Canvas.

Não há evidência para atribuir uma porcentagem única de conclusão. As frentes
estão em estágios diferentes, e a homologação física permanece aberta.

## 9. Inventário integral da origem reaproveitada

### Oito módulos copiados sem alterações

- [e2ee-crypto.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/e2ee-crypto.ts) → [e2ee-crypto.ts](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/transport/src/vendor/e2ee-crypto.ts)
- [mobile-e2ee-v2-contract.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/mobile-e2ee-v2-contract.ts) → [mobile-e2ee-v2-contract.ts](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/transport/src/vendor/mobile-e2ee-v2-contract.ts)
- [mobile-e2ee-v2-framing.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/mobile-e2ee-v2-framing.ts) → [mobile-e2ee-v2-framing.ts](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/transport/src/vendor/mobile-e2ee-v2-framing.ts)
- [mobile-e2ee-v2-node-key-schedule.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/mobile-e2ee-v2-node-key-schedule.ts) → [mobile-e2ee-v2-node-key-schedule.ts](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/transport/src/vendor/mobile-e2ee-v2-node-key-schedule.ts)
- [paired-e2ee-node-primitives.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/paired-e2ee-node-primitives.ts) → [paired-e2ee-node-primitives.ts](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/transport/src/vendor/paired-e2ee-node-primitives.ts)
- [paired-e2ee-primitives.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/paired-e2ee-primitives.ts) → [paired-e2ee-primitives.ts](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/transport/src/vendor/paired-e2ee-primitives.ts)
- [paired-e2ee-v2-client-session.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/paired-e2ee-v2-client-session.ts) → [paired-e2ee-v2-client-session.ts](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/transport/src/vendor/paired-e2ee-v2-client-session.ts)
- [paired-e2ee-v2-key-schedule.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/paired-e2ee-v2-key-schedule.ts) → [paired-e2ee-v2-key-schedule.ts](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/transport/src/vendor/paired-e2ee-v2-key-schedule.ts)

### Onze origens de adaptação

| Origem ORCA fixada | Destino SENTRA |
|---|---|
| [src/renderer/src/components/tab-bar/SortableTab.tsx](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/components/tab-bar/SortableTab.tsx) | [sentra_canvas/desktop_ui/src/workspace/OrcaTabStrip.jsx](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/desktop_ui/src/workspace/OrcaTabStrip.jsx) |
| [src/renderer/src/components/tab-bar/tab-bar-surface.tsx](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/components/tab-bar/tab-bar-surface.tsx) | [sentra_canvas/desktop_ui/src/workspace/OrcaTabStrip.jsx](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/desktop_ui/src/workspace/OrcaTabStrip.jsx) |
| [src/renderer/src/components/tab-bar/tab-width-rules.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/components/tab-bar/tab-width-rules.ts) | [sentra_canvas/desktop_ui/src/workspace/OrcaTabStrip.jsx](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/desktop_ui/src/workspace/OrcaTabStrip.jsx) |
| [src/renderer/src/components/right-sidebar/FileExplorerRow.tsx](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/components/right-sidebar/FileExplorerRow.tsx) | [sentra_canvas/desktop_ui/src/workspace/WorkspaceExplorer.jsx](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/desktop_ui/src/workspace/WorkspaceExplorer.jsx) |
| [src/renderer/src/assets/main.css](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/assets/main.css) | [sentra_canvas/desktop_ui/src/workspace/workspace.css](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/desktop_ui/src/workspace/workspace.css) |
| [src/renderer/src/components/tab-group/TabGroupSplitNodeTree.tsx](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/renderer/src/components/tab-group/TabGroupSplitNodeTree.tsx) | [sentra_canvas/desktop_ui/src/workspace/OrcaSplit.jsx](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/desktop_ui/src/workspace/OrcaSplit.jsx) |
| [src/shared/tab-types.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/shared/tab-types.ts) | [sentra_canvas/desktop_ui/src/workspace/layout.js](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/desktop_ui/src/workspace/layout.js) |
| [src/main/runtime/orchestration/coordinator-dag-convergence.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/main/runtime/orchestration/coordinator-dag-convergence.ts) | [sentra_runtime/orchestration_observation.py](C:/Users/vitor/Desktop/SENTRA/sentra_runtime/orchestration_observation.py) |
| [src/main/acp/acp-dialects/opencode-dialect.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/src/main/acp/acp-dialects/opencode-dialect.ts) | [sentra_interop/acp_dialects.py](C:/Users/vitor/Desktop/SENTRA/sentra_interop/acp_dialects.py) |
| [mobile/src/transport/pairing-keychain.ts](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/mobile/src/transport/pairing-keychain.ts) | [integrations/orca-mobile/app/App.tsx](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/app/App.tsx) |
| [mobile/src/session/MobileNativeChatCardHeaderAction.tsx](https://github.com/stablyai/orca/blob/70b2197c97b164b16c618736a107967295e5af92/mobile/src/session/MobileNativeChatCardHeaderAction.tsx) | [integrations/orca-mobile/app/components/CardHeaderAction.tsx](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/app/components/CardHeaderAction.tsx) |

### Implementações próprias e serviços existentes usados na adaptação

São trabalho SENTRA, e não cópia integral de módulos ORCA: daemon/cliente PTY,
registro e gateway de dispositivos, contrato de inventário, adaptadores de
worktrees e componentes de apresentação. Reutilizam o ConPTY, a autoridade,
Playwright, VM, arquivos e revisão que o projeto já tinha. A correção CDP também
é integração com o backend SENTRA existente, não transplante do browser ORCA.

- [sentra_canvas/pty_daemon.py](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/pty_daemon.py)
- [sentra_canvas/pty_client.py](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/pty_client.py)
- [sentra_canvas/workspace_contract.py](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/workspace_contract.py)
- [sentra_canvas/mobile_devices.py](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/mobile_devices.py)
- [sentra_canvas/mobile_host.py](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/mobile_host.py)
- [workspace/worktrees.py](C:/Users/vitor/Desktop/SENTRA/workspace/worktrees.py)
- [sentra_executors/git_worktrees.py](C:/Users/vitor/Desktop/SENTRA/sentra_executors/git_worktrees.py)
- [integrations/orca-mobile/transport/src/contracts.ts](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/transport/src/contracts.ts)
- [sentra_canvas/desktop_ui/src/workspace/DotWorkspace.jsx](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/desktop_ui/src/workspace/DotWorkspace.jsx)
- [sentra_canvas/desktop_ui/src/workspace/BrowserPane.jsx](C:/Users/vitor/Desktop/SENTRA/sentra_canvas/desktop_ui/src/workspace/BrowserPane.jsx)
- [integrations/orca-mobile/app/App.tsx](C:/Users/vitor/Desktop/SENTRA/integrations/orca-mobile/app/App.tsx)
- [vendor/orca/provenance.json](C:/Users/vitor/Desktop/SENTRA/vendor/orca/provenance.json)
- [vendor/orca/validation-build.json](C:/Users/vitor/Desktop/SENTRA/vendor/orca/validation-build.json)
- [docs/ORCA_SENTRA_IMPLEMENTATION_20261020.md](C:/Users/vitor/Desktop/SENTRA/docs/ORCA_SENTRA_IMPLEMENTATION_20261020.md)
