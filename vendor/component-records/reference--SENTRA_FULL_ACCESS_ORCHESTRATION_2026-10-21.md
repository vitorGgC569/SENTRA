# Estados formais e orquestração com Acesso completo

21/10/2026 · build `sentra-orca-experimental-cffb8f3284b3` · entrega experimental.

## Experiência consolidada

A conversa permanece o centro da utilização. O seletor existente Acesso completo
é a única escolha necessária para autorizar a preparação automática dos acessos
do coordenador e das tarefas delegadas. Não foi acrescentado um painel novo de
configuração ou uma nova camada de navegação.

| Estado | Evidência necessária |
|---|---|
| Solicitado | Pedido registrado na fila durável. |
| Entregue ao Dot | Recebimento/aceitação registrado pelo destinatário. |
| Em execução | Início de execução observado. |
| Aguardando aprovação | Uma decisão é necessária. |
| Aguardando confirmação | Resultado incerto ou conclusão sem evidência conferida. |
| Concluído e verificado | Resultado registrado e recibo de verificação final válido. |
| Falhou | Falha registrada, sem declaração de sucesso. |
| Cancelado | Cancelamento registrado. |
| Expirado | Prazo/autorização expirado. |
| Interrompido | Trabalho pausado ou interrompido. |

A mesma projeção aparece no pedido da conversa e na atividade do Canvas. A
resposta do assistente tem seu próprio reconhecimento de recebimento; texto do
modelo e recibo de transporte não se tornam conclusão verificada de tarefa.

## Acesso completo e gerenciamento automático

- A seleção autenticada do proprietário é a fonte da autorização.
- O host prepara Grants por turno para capacidades declaradas, inclusive criar
  Dots, conectar, delegar e iniciar o modelo de um filho.
- Cada filho recebe WorkItems e Grants próprios, com vínculo à seleção original.
  O modelo não recebe um endpoint para conceder autoridade arbitrária.
- Acesso a arquivos/comandos e recursos locais configurados é preparado na
  conversa correspondente. O terminal é registrado quando necessário; preparar
  seu catálogo não inicia um processo. Navegador, ACP e worktree usam seus
  serviços previamente configurados e seus contratos.
- O modo continua sujeito ao orçamento, às capacidades disponíveis, às conexões
  dirigidas e à identidade do projeto/Space/Canvas. Não cria login nem inventa
  capacidade de um serviço ausente.
- Uma restrição explícita escolhida no filho prevalece sobre a herança.
- Desativar Acesso completo revoga os Grants derivados; gerações antigas não
  voltam a valer ao selecionar o modo novamente. O vínculo é protegido e persiste
  no host. A revogação também é conferida antes de novas ações dos descendentes.
- No modo Solicitar aprovação, os pedidos continuam na própria conversa.

A interface não pede ao usuário que execute comandos de Grants/WorkItems.
Os atalhos de criação/delegação do CLI agora chegam à mesma admissão estruturada
do shell, preservando as verificações existentes. Bootstrap legado de terminal
continua fora desse caminho.

## Verificação de resultados

O Dot pode apresentar os IDs de leituras reais de arquivos ao verificador do
host. O host valida dono, projeto, conversa, capacidade e recibo, e faz nova
leitura autorizada com o SHA esperado. Antes de publicar a conclusão, confere
novamente os arquivos. Alteração ou leitura sem confirmação impede o estado
Concluído e verificado.

O recibo informa `scope=file_integrity` e a hora observada. Ele certifica a
integridade dos arquivos conferidos naquele instante; correção de regras de
negócio exige critérios/testes próprios. No ensaio abaixo os valores foram
conferidos independentemente contra os 60 registros da entrada. Inserir
`verified: true` num texto ou JSON não cria o recibo de verificação do host.

## Ensaio com modelo e efeitos reais

```powershell
python tests/qa/full_dot_recovery.py --output-dir .tmp/full-dot-recovery-v4 --timeout 240
```

**Passou com `sentra/codex/current`.**

1. Uma seleção de Acesso completo pelo usuário; zero chamadas manuais de Grants.
2. Coordenador cria Agregador e Auditor, com suas conexões e conversas permanentes.
3. Duas instruções delegadas, uma por trabalhador. Ambos leem vendas.csv e
   produzem arquivos reais: agregacao.json e auditoria.json.
4. Pausa proposital no checkpoint anterior à consolidação, com os artefatos
   guardados. Broker fechado e reaberto sobre o mesmo estado.
5. Retomada pela conversa: o usuário pede para continuar com os resultados já
   existentes. O coordenador consulta os filhos, lê os arquivos, compara os
   resultados e produz conciliacao.json. Nenhum trabalhador/instrução é duplicado.
6. O host confere novamente os hashes e registra o estado Concluído e verificado.

Resultados conferidos:

| Critério | Resultado |
|---|---:|
| Registros | 60 |
| Total | 594 |
| Norte | 191 |
| Sul | 198 |
| Leste | 205 |
| Dots criados pelo coordenador | 2 |
| Seleções de Acesso completo | 1 |
| Concessões manuais de Grants | 0 |

Chamadas de provedor concluídas: 21. Chamadas de provedor/ferramenta
que ficaram iniciadas sem fechamento no ensaio final: 0.

[Relatório real e hashes](../.tmp/full-dot-recovery-v4/report.json) ·
[checkpoint preservado](../.tmp/full-dot-recovery-v4/checkpoint.json).

As tentativas v1–v3 foram preservadas e não entram no resultado aprovado: v1/v2
revelaram a incompatibilidade dos atalhos do CLI com o caminho estruturado; v3
concluiu a fase dos trabalhadores, mas revelou que o comando de pausa tentava
chamar o objeto ControlPlane como função. Os dois caminhos foram corrigidos e
receberam testes. Nenhum pedido incerto desses ensaios foi reenviado.

### Limite da recuperação demonstrada

A interrupção ocorreu num checkpoint conhecido, antes da consolidação final.
Este ensaio não simula queda no meio de uma escrita física. Uma operação com
efeito desconhecido permanece aguardando confirmação e não é repetida apenas
porque o modo completo está ativo. A retomada demonstrada usa os mesmos dados,
conversas e recibos, sem intervenção técnica ou concessão manual de permissões.

## Validação e avaliação aberta

- **79 testes Python** passaram: estados, permissões, delegação, restrição no
  filho, revogação, preparação de terminal sem processo, pausa/retomada,
  evidência inválida/alterada, isolamento, recibos e regressões de apresentação.
- **151 testes Node** passaram.
- Dois renderers descartáveis passaram: temas, teclado, largura reduzida,
  retomada, aprovação perdida sem reenvio, rascunho/scroll e painel contextual.
- Builds desktop isolados concluíram; 168 fontes e 261
  saídas tiveram seus hashes conferidos.

Janela atual para avaliação: **SENTRA · Orquestração**.
Estado próprio `.tmp/orca-full-evaluation`, gateway LAN na porta 5202. O seletor
Acesso completo está no compositor. Para usar a automação, selecione esse modo
uma vez nessa nova avaliação e descreva a tarefa.

A instalação e as janelas anteriores continuam com seus estados. Android/iPhone
físicos, instaladores assinados, relay, ACP integral e demais itens da migração
continuam com seus critérios de aceite anteriores.

[Registro verificável do build e dos ensaios](../vendor/orca/full-access-orchestration-validation.json).
