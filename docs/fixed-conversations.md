# Conversas persistentes — integração e limites

Revisão local de 13/09/2026. Nenhum prompt real enviado nesta revisão.

## O que significa o modo cinco

| Assento remoto por run | Papéis que o utilizam |
|---|---|
| master | planner, judge, master interno |
| executor | executor, repair |
| validator.logic | crítica lógica |
| validator.requirements | crítica de requisitos |
| validator.adversarial | crítica adversarial |

O master interno não é a IA central do usuário e não autoriza promoção.
As instruções do papel/tarefa são reenviadas na abertura de cada diálogo lógico,
mesmo em um chat existente. Aliases de arquivos/resultados são locais à sessão
do gateway, não ao histórico inteiro do chat. Isso não apaga o contexto antigo
do modelo nem prova ausência de contaminação semântica.

`compute_policy` pode acrescentar edge_cases, security e performance mediante
causa. O catálogo atual comporta oito assentos distintos no máximo. Valores como
`add_agents: 10` são tetos sobre os três papéis standby existentes, não dez novos
agentes. `max_agents: 500` não constitui evidência de escala.

## Caminho implementado

`OMAEngine` entrega o mesmo `FixedConversationRouter` a todos os agentes.
`ModelRouter.provider_scope` coloca cada tentativa de provider na fronteira de
persistência, inclusive respostas de `AgentToolLoop` a diretivas de leitura.
O gateway continua local: nenhuma chamada à IA central para interpretar `[[R]]`.

Uma trava assíncrona serializa diálogos da run. Uma trava do sistema operacional
impede dois processos de despacharem simultaneamente usando o mesmo diretório
de conversas. A trava é liberada pelo SO após morte do processo.

`inter_call_delay_s` é um cooldown conservador após cada resposta, antes da
próxima mensagem. Seu timestamp é persistido. Inclui mensagens com resultados
do gateway; não é apenas um sleep concorrente antes de iniciar cada agente.

Cada envio grava antes um estado `IN_FLIGHT`, com assento, papel, tarefa, provider
e hash da requisição. A escrita usa arquivo temporário, flush/fsync e substituição
atômica. Cada resposta válida persiste imediatamente URL/ID e `CONFIRMED`, antes
da próxima leitura pelo gateway ou da contabilização final de budget.

Falha de escrita não é ignorada. Cancelamento, timeout sem prova de não envio,
URL divergente e resposta browser sem identidade bloqueiam novos envios.
Não há fallback automático de uma tentativa falha no modo de assentos fixos.
Providers locais sem URL continuam utilizáveis; isso não prova chat persistente.

Pool, compute policy, transporte/provider e classificação de resultados entram
na lista de componentes protegidos contra promoção sem aprovação externa.

## Operação e retomada

`python -B main.py --status --workspace . --job-id RUN-EXEMPLO-001`

O campo `conversation_pool` é somente leitura:

- `ABSENT`: não há mapa; não significa que inexista histórico remoto.
- `IDLE`: mapa local válido sem envio pendente; não prova disponibilidade/cota.
- `BLOCKED`: há `IN_FLIGHT`, `UNCERTAIN` ou `BLOCKED`; reconciliar antes de retomar.
- `INVALID`: mapa corrompido, identidade inválida ou migração legada ambígua.

O formato novo é `schema_version: 2`, com `run_id`, `last_dispatch_at` e `seats`.
Mapas legados sem colisões são lidos e só migrados ao despachar. Chats antigos
distintos de executor e repair (ou planner/judge/master) não são fundidos nem
descartados automaticamente. Uma run legada com esse tipo de colisão mantém
seus arquivos inalterados por esta revisão.

Não apague o mapa para destravar uma run. É necessário conferir o job no relay
e a conversa remota e decidir explicitamente como reconciliar. Ainda não existe
comando seguro de reconciliação/importação de resposta pendente.

## Limites que continuam abertos

- Persistência é por **run**, não um pool estável compartilhado entre runs.
- Pacing é por run/diretório, não um limitador global de conta, relay ou todos
  os scripts legados. Rodar vários swarms pode contorná-lo.
- Cinco assentos não são cinco chamadas totais nem cinco chamadas simultâneas.
- O bloqueio após envio incerto é conservador, não recuperação automática.
  Não oferece entrega exatamente uma vez entre resposta e checkpoint da tarefa.
- A durabilidade depende do disco/SO; não foi provada contra perda de energia
  ou conflitos de sincronização em nuvem. Prefira um único escritor local.
- Trocar de provider de um assento já persistido é recusado. Rotas distintas
  para papéis que compartilham assento precisam ser reconciliadas pelo operador.
- Histórico remoto cresce. Compactação, rotação com handoff e memória validada
  entre runs continuam pendentes; economia de tokens/créditos ainda não foi medida.
- O supervisor, MASTER_QUEUE e gates de escala não foram concluídos aqui.
- Controles determinísticos não tornam o DOM do ChatGPT estável nem validam
  disponibilidade comercial, capacidade ou limites da conta.

## Evidência

`tests/integration/test_persistent_conversation_delivery.py` exercita componentes
reais locais (router, gateway, disco e locks) com respostas de modelo roteirizadas:
concorrência, cinco assentos, cooldown, continuidade, primeira URL persistida,
cancelamento, estado corrompido, falha de gravação, provider incompatível e status.
Esses testes não são evidência de conversa real ou de qualidade cognitiva.

Testes de Edge/ChatGPT e Docker não foram acionados nesta revisão. A próxima
prova live deve ser pequena, explicitamente delimitada, com inspeção das URLs,
nenhum replay incerto e sem iniciar um swarm de 200 conversas.

Resultados desta revisão:

- Primeira suíte ampliada: 246 passed, 6 skipped, 1 failed. A falha era timeout
  da demo CLI herdando o delay live de 30 s; corrigido somente no modo offline.
- Reexecução ampliada: **262 passed, 6 skipped, 1 deselected**, 172,12 s.
  Comando: `python -B -m pytest -q -k 'not test_e2e_local_model_if_available'`,
  com `OMA_LIVE_EXTENSION`, `OMA_LIVE_EDGE`, `OMA_LIVE_LOCAL` e
  `OMA_DOCKER_TESTS` explicitamente em `0` no processo de teste.
- Recorte final: **58 passed**, 21,97 s, incluindo dois testes adicionados após
  a coleta da suíte ampliada: encerramento forçado de subprocesso e inclusão dos
  controles de entrega na lista de componentes protegidos. O subprocesso usa
  provider roteirizado local; não envia mensagem nem cria conversa remota.
- `--status` real de run legada: FAILED, 0/4, mapa legado ambíguo; SHA-256
  do mapa idêntico antes e depois da consulta.
- `git diff --check`: sem erros de whitespace. Nenhum commit/promoção realizado.

Arquivos de implementação alterados neste recorte: `orchestrator/conversation_pool.py`,
`orchestrator/agents/router.py`, `orchestrator/engine.py`, `orchestrator/compute_policy.py`,
`orchestrator/providers/extension_provider.py`, `repository/agent_loop.py`,
`repository/policy.py`, `browser/outcomes.py`, `main.py` e comentários de `config.yaml`.
Seis arquivos de testes foram adicionados/atualizados, além deste documento,
README, traps e matriz do produto. Alterações anteriores do checkout foram preservadas.
