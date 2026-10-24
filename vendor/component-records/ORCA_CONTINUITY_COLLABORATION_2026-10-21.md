# Continuidade, permissões e trabalho conjunto dos Dots

Data: 21/10/2026. Build experimental `sentra-orca-experimental-6d3814ddf526`.

As seis melhorias solicitadas foram implementadas nas fontes e no build de avaliação.
A Home e a navegação externa seguem os componentes SENTRA existentes. A instalação
não recebeu estes bundles. O plano integral ORCA/SENTRA continua aberto.

## 1. Comportamento entregue

| Pedido | Implementação |
|---|---|
| Continuar de onde parou | Perfil protegido no host por usuário/projeto/Space/Dot, com layouts Simples/Avançado, painel ativo e recursos existentes. Reabrir não cria terminal nem operação. Sem layout anterior, retoma um recurso conhecido. |
| Permissões na conversa | Cartão junto ao compositor explica motivo, caminho, alcance e validade. Permite ou recusa a ação exata, sem configurar Grants manualmente. Coordenação também usa cartões da conversa. |
| Nomes úteis | Nome da tarefa no diálogo Nova sessão e renomeação em Mais opções → Gerenciar sessões. Abas e listas usam esse nome; ferramenta/identidade ficam como informação secundária. Sessões antigas recebem nome legível, sem adivinhar uma tarefa pelo comando. |
| Estado claro | Uma projeção principal por tarefa: Trabalhando, Precisa de você, Concluído ou Na fila. IDs e estado interno ficam em detalhes. Entrega de instrução não equivale a conclusão da tarefa. |
| Painéis contextuais | Arquivo aprovado e confirmado pode aparecer ao lado da conversa. Novos terminais observados aparecem quando não há digitação/diálogo em curso. O menu Ferramentas deste trabalho oferece somente os terminais do Dot e navegador configurado. Selecionar navegador não cria sessão nem concede acesso. |
| Primeiro uso guiado | Convites curtos para conhecer o projeto ou planejar melhoria preenchem um rascunho; o usuário decide quando enviar. Boas-vindas de primeiro uso não reaparecem quando há trabalho anterior. |

O navegador contextual abre por seleção explícita. Não é iniciado automaticamente
por palavras no prompt. O painel atual continua usando o serviço semântico de
navegador; página gráfica compartilhada e migração de login continuam pendentes.
A preferência de painéis contextuais controla as aberturas automáticas; a seleção
explícita de uma ferramenta continua disponível.

A conversa permanece montada ao visitar seu Canvas. Rascunho, anexos locais e
posição de leitura são conservados. Um painel auxiliar não substitui o compositor.

## 2. Limites e autoridade das permissões

- Operações locais vinculam o pedido ao WorkItem e à impressão digital da ação.
- Pedido de arquivo/comando: uma ação exata, com validade fixa de cinco minutos;
  consultar novamente não prorroga esse prazo. Um comando pode produzir efeitos
  fora do diretório inicial; a interface não o apresenta como sandbox do projeto.
- Decisão de coordenação: escopo do turno, até cinco minutos enquanto ele estiver
  ativo; a aprovação não repete a instrução anterior automaticamente.
- Decisões são registradas antes do envio. Confirmação perdida é consultada por
  seletor original; não há segundo envio para tentar descobrir se funcionou.
- O modelo explica o motivo, mas não se autoriza. Serviços, políticas, Grants e
  WorkItems existentes continuam responsáveis por admitir ou recusar o efeito.
- Perfil visual tem esquema/limites próprios, comparação de revisão e conteúdo
  protegido. Conflito entre janelas recusa sobrescrever a versão mais recente.

## 3. Validação real das conversas atuais

Comando reproduzível:

```powershell
python tests/qa/shell_dot_collaboration.py --output-dir .tmp/orca-flow-shell-collaboration-v6 --timeout 90
```

**Passou com modelo real `sentra/codex/current`, sem reenvio automático.**

1. Coordenador e trabalhador recebem Dots e conversas permanentes distintas.
2. Coordenador usa a ferramenta de delegação para enviar uma única instrução.
3. Trabalhador recebe sua própria permissão de modelo e responde com marcador e
   resultado do cálculo 6 × 7.
4. Coordenador consulta a conversa filha e consolida o resultado recebido.
5. Cinco chamadas de provedor têm recibos concluídos nas duas conversas.
6. O trabalhador não herda autoridade de coordenação do pai.

Os hashes das respostas finais do filho e do coordenador coincidem. O teste usa
estado isolado, permissões explícitas e encerra seus próprios processos.
[Relatório bruto](../.tmp/orca-flow-shell-collaboration-v6/report.json).
As tentativas v1–v5 foram preservadas: tiveram falhas de preparação/coleta do
ensaio e não são contabilizadas como testes aprovados. O v6 executa o roteiro
completo e confirma todas as pós-condições.

Também passou o ensaio independente do CLI real com coordenador e dois
trabalhadores ConPTY: equipe, conexão, arquivos escritos fisicamente, reinício do
coordenador sem duplicar os trabalhadores e uma resposta real de modelo.
[Relatório CLI](../.tmp/orca-flow-cli-coordination/report.json).
Esse roteiro complementa o teste dos Dots atuais; não o substitui.

## 4. Regressões e avaliação visual

- 49 testes Python: persistência, permissões, recibos, filhos, aprovações,
  avaliação e vínculo terminal/WorkItem. Os sete de apresentação foram repetidos
  depois do ajuste final e já estão incluídos nesses 49.
- 151 testes Node desktop e 15 do transporte móvel passaram.
- Tipos de app móvel/transporte passaram; exportações Hermes Android/iOS e dois
  builds desktop isolados concluíram.
- Renderer descartável: primeiro uso, layout após reload, modos separados,
  teclado, tema claro/escuro, largura 660 px e aprovação com confirmação perdida.
- Shell completo descartável: mesmo compositor/transcript, rascunho inalterado,
  scroll 220 preservado ao ir/voltar do Canvas e abrir/fechar navegador contextual;
  ausência de Grant mantém a criação de navegador bloqueada.
- Capturas de primeiro uso, acesso e navegador foram inspecionadas. Fixtures
  visuais simulam serviços; os testes Python e de Dots acima usam os serviços reais.

Manifesto verificado: 161 fontes e 261 saídas,
sem divergências de hash. [Registro de validação](../vendor/orca/continuity-collaboration-validation.json).

## 5. Como avaliar agora

Janela aberta: **SENTRA · Trabalho conjunto**.
Estado exclusivo: `.tmp/orca-flow-evaluation`. Gateway LAN próprio na porta 5201.
O ícone de dispositivos abre o pareamento; Android/iPhone físicos ainda precisam
ser homologados. Não foram copiados cookies, contas ou sessões da instalação.

- Comece em Conversar com Oxta e descreva uma tarefa, ou use uma sugestão de rascunho.
- No Canvas, abra um arquivo; saia e volte para conferir a retomada.
- Use Nova sessão para informar o nome da tarefa antes de escolher a ferramenta.
- Na conversa, acompanhe pedidos de acesso e permita somente o que revisar.
- Use Ferramentas deste trabalho para abrir recursos disponíveis ao lado do chat.

A primeira abertura desta nova avaliação não exibiu o workspace; o visor foi
reaberto sobre o mesmo broker, sem reiniciar o estado. A janela atual confirmou
CSS, modo simples, mascotes, workspace e botão de dispositivos carregados.
Recorrência desse comportamento de primeira abertura ainda precisa ser apurada;
os diagnósticos de desenvolvimento agora preservam uma captura em caso de falha.

## 6. O que este aceite não cobre

Não homologa todas as combinações de modelos Web, ACP/OpenCode, navegador gráfico,
VM, três worktrees concorrentes, relay, instalação assinada ou Android/iPhone
físicos. Eventos de recursos continuam sendo consultados periodicamente. A
sincronização de layout entre dispositivos e a recuperação completa de órfãos
continuam no plano. O sistema não reenvia automaticamente efeitos incertos.
