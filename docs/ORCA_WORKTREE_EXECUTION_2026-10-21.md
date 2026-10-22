# Trabalhos Git isolados por Dot

Entrega experimental de 21/10/2026. A migração ORCA → SENTRA continua aberta.

## Implementado

- `CANVAS isolate_work` seleciona uma worktree real para a conversa de trabalho.
  A criação passa pela máquina Git, WorkItem, Grant e operação centrais existentes.
  Acesso completo prepara os recursos admitidos; o agente não recebe um endpoint
  de autoautorização.
- O vínculo usa o registro central `execution_workspaces`, com usuário, projeto,
  Space, conversa, Dot, Run, WorkItem e operação de criação. Nenhum registro de
  autoridade paralelo foi criado.
- Arquivos relativos do computador local e do serviço de arquivos com gravação
  atômica/captura durável usam a pasta vinculada, assim como o diretório dos comandos.
  `cwd` relativo também é resolvido dentro dela. Novos terminais admitidos pela
  máquina de terminal usam essa pasta. Sessões anteriores conservam seu diretório.
- Novos processos de conversa usam a pasta vinculada como diretório de trabalho;
  a identidade canônica do projeto no CLI e no gateway continua preservada.
- Explorador e prévia de arquivo podem ler a pasta exata da conversa. Abas novas
  persistem a conversa e a identidade do workspace. Um vínculo divergente ou
  indisponível produz erro; não é substituído silenciosamente pelo projeto principal.
- Criar uma worktree não confirmada não autoriza seu consumo. Falha, descarte,
  troca de agente, Run diferente e remoção da pasta não provocam recriação.
- `CANVAS review_worktrees` e a consulta do proprietário `dot_worktree_review`
  ensaiam a combinação de até oito trabalhos em uma pasta descartável.
  Seletores são IDs de conversas existentes, sem caminhos ou autoridade no pedido.
  O agente só consulta Dots conectados de seu Canvas.
- A aba **Revisão** oferece essa consulta dentro do Canvas do Dot. A moldura,
  Home e navegação externa não foram substituídas.

## O que a revisão comprova

As alterações de texto rastreadas são capturadas contra uma base comum e aplicadas
em ordem a um snapshot temporário. O resultado distingue compatibilidade, conflito,
arquivos alterados durante a consulta e necessidade de revisão manual. Se a base do
projeto avançou, essa divergência aparece mesmo quando o ensaio é compatível.

Não são modificados o índice, as referências ou os arquivos do projeto principal.
O resultado registra hashes das alterações observadas. Compatibilidade de patches
não comprova correção semântica nem autoriza integração/publicação.

Limites iniciais: oito trabalhos, patch de 8 MiB, snapshot de 32 MiB e 4.096 entradas.
Arquivos novos não rastreados, binários, links e submódulos exigem revisão explícita.
O ensaio rejeita caminhos reservados e saídas do diretório temporário. Git é chamado
sem as variáveis `GIT_*` herdadas e com hooks desabilitados nesses caminhos internos.

## Correções encontradas nos ensaios

1. O prompt distinguia mal a colaboração por conversa e a execução de ferramentas
   CLI. A documentação do agente agora apresenta `dispatch` para a conversa
   permanente do Dot e reserva `dot_tool_dispatch` ao pedido de uma ferramenta.
2. O inventário da máquina Git estava sem `actions`, exigido pelo catálogo do agente.
   O contrato foi corrigido: as capacidades Git já representam operações específicas
   e não recebem um seletor `action` adicional. A regressão consulta contexto depois
   da criação real da worktree.
3. Consultas de contexto e admissão de filhos ultrapassaram o prazo antigo de oito
   segundos sob carga Windows concorrente. Seus prazos foram ajustados sem retry.
   Cinco casos unitários conferem uma única requisição com a identidade original.
4. A criação, leitura, edição, conferência e resposta final ultrapassaram o limite
   antigo de oito rodadas. Turnos do Canvas agora têm um limite explícito de 32
   rodadas, conservando prazos finitos e os controles de autorização.

## Evidências

Os relatórios desta rodada ficam em `vendor/orca/worktree-execution-validation.json`
e no manifesto `vendor/orca/validation-build.json`. Os logs completos de ensaio estão
em `.tmp`, separados do estado instalado.

- 97 casos Python únicos aprovados, contando as suítes de integração, regressão,
  contexto do agente e prazos sem duplicar as repetições.
- 152 casos Node desktop aprovados.
- Um renderer Electron descartável aprovado: leitura de arquivo com escopo
  persistido após reload, revisão sem efeito físico, modos, teclado e tema claro.
- Git, autorização central, edição relativa, comandos e ConPTY são reais nos testes
  de integração. Esses testes usam atores de unidade e não são apresentados como
  geração real de modelo.

O roteiro `tests/qa/dot_worktree_execution.py` exercita separadamente modelos reais.
Tentativas anteriores são preservadas: v1 escolheu a rota CLI; v2/v3 expuseram o
campo ausente no inventário; v4 perdeu a confirmação da delegação por timeout.
Nenhuma dessas tentativas conta como aprovação ou foi reenviada sobre seu estado.

Checkpoint em 22/10: v5 produziu arquivos e três conferências de integridade, mas
encerrou os turnos no limite de oito rodadas. v6 usou o novo limite e executou
alterações reais, porém o provedor encerrou as gerações com categoria `quota`.
A homologação completa com três resultados finais verificados continua pendente.
Não houve reenvio das operações incertas. O proprietário pediu commit/push do
estado atual e, depois, novo build local, validação básica e publicação de tag.

## Ainda falta para o aceite integral

- Editor com save condicionado à versão, rascunhos e conflitos de edição.
- Arquivos não rastreados/binários na revisão e resolução estruturada de conflitos.
- Ciclo de limpeza, descarte e publicação Git com decisões e recibos próprios.
- Vínculo explícito da pasta do trabalho às ferramentas executadas dentro da VM.
  O trabalho desta rodada usa os recursos locais admitidos; não converte terminais
  guest em processos do host.
- Homologação na distribuição instalada, migração e atualização segura dos pacotes.
- Demais critérios macro do tracker, incluindo aparelhos Android/iPhone físicos,
  ACP completo, browser gráfico, relay e distribuição assinada.

Nada foi ativado na instalação principal. Os bundles são gerados nas entradas
isoladas de validação e de prévia.
