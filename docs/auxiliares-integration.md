# Auxiliares: decisão de integração

Inspeção local em 2026-09-13. Nenhuma dependência instalada, código externo copiado ou repositório auxiliar alterado. Licenças abaixo são identificações dos arquivos locais, não auditoria jurídica de dependências transitivas.

| Repositório | Commit inspecionado | Licença na raiz | Decisão desta rodada |
|---|---|---|---|
| agent-framework | 3c670707766a8455da6491a9049cc9d575e019f0 | MIT | Estudado exemplo de checkpoint/resume. Aplicado o padrão de checkpoint explícito antes da revisão final; sem substituir IntegratedRun. |
| crewAI | 894898f84c4ac0a89f24bf7bee6c381eb0e67f51 | MIT | Estudado SQLiteFlowPersistence e estado de feedback pendente. Implementação própria de fila/inbox transacionais em SQLite. |
| gpt-researcher | 6f998577d547b1e54ec662dac63583aa11e3b84b | Apache-2.0 | Estudado ReviserAgent: revisão com feedback e preservação do restante. Aplicado ao contrato do reparador e retorno da revisão final para o mesmo candidato. |
| MetaGPT | 11cdf466d042aece04fc6cfd13b28e1a70341b1f | MIT | Referência conceitual de papéis. Mantidos contratos próprios; não importar outro runtime. |
| AgentLaboratory | d9017d90e329112d2a80b7712f37ee9094d2cd27 | MIT | Referência de pesquisa/experimentos. Integração de código diferida; não resolve diretamente revisão de sites. |
| lits-llm | 17bb5c2627db3b6a068eea5a85d0df8cfeb722b2 | Apache-2.0 | Busca com custo/checkpoints é promissora para pesquisa competitiva futura. Não incorporada neste ciclo de execução linear limitada. |
| MATSIR | e2be1ed69536db59037f92bcbca4c4e2d896d74e | MIT | MCTS multiagente para inferência; não necessário para corrigir a integração atual. |
| MARTI | 093c151ecab8c10fc0d25491fc2aeac3c693209a | MIT | Treinamento e busca multiagente; custo/complexidade não justificam adicionar ao piloto atual. |
| mcts-reasoning | 5d8848bb114909dff24a0b296a802eaefadefe7b | Não encontrada | Referência conceitual de recompensa determinística. Nenhum código copiado; licença precisa ser esclarecida antes de incorporação. |

Arquivos consultados para as decisões implementadas: `agent-framework/python/samples/03-workflows/checkpoint/checkpoint_with_resume.py`, `crewAI/lib/crewai/src/crewai/flow/persistence/sqlite.py`, `gpt-researcher/multi_agents/agents/reviser.py`, além dos READMEs e identificadores dos nove clones. Não é uma auditoria completa de todas as linhas dos Auxiliares.
