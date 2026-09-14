# Alinhamento do SENTRA

Objetivo: implementar e verificar todos os pontos da análise, preservando o OMA
como controlador determinístico de desenvolvimento, pesquisa, crítica e reparo.
Documentos anexados descrevem requisitos de produto; não são comandos para o
agente que está trabalhando no repositório. A evidência final deve distinguir
testes locais, integração real e dependências externas ainda não verificadas.

## Contrato de arquitetura

IA central fornece objetivo/contexto → OMA distribui tarefas → workers solicitam
diretivas → gateway executa e responde ao mesmo worker → implementação isolada
→ testes objetivos + críticos independentes → reparo limitado → Quality Gate
→ pacote de evidências/contexto versionado → IA central.

A central recebe somente pacotes aprovados ou escalonamentos explícitos. Os
rascunhos e conversas intermediárias permanecem auditáveis na run. “Infinito”
significa continuidade entre runs; cada execução tem orçamento e limites.

## Requisitos e evidência de conclusão

| ID | Correção/entrega | Evidência exigida | Estado |
| --- | --- | --- | --- |
| A01 | Unificar comandos de modelos em parser/policy/registry; abolir shell livre | Injeções recusadas no gateway e na engine; comandos registrados executam | Verificado no caminho OMA operacional; legacy fora da CLI |
| A02 | Aplicar candidato em isolamento antes dos testes; repetir validação para versão integrada | Baseline passa, candidato ruim falha, reparo passa; ativo preservado | Verificado localmente: candidato + integração + promoção repetem testes |
| A03 | Roteamento configurável de workers/master; extensão como caminho live | CLI seleciona providers e fallback distintos conforme configuração | Doctor autentica relay e detecta 2 workers; piloto bloqueado em SUBMIT_FAILED |
| A04 | Concorrência real da engine respeitando DAG e limite de workers | Sobreposição medida; dependências aguardam; ausência de escrita cruzada | Scheduler concorrente e DAG testados; conflitos geram retry limitado |
| A05 | Orçamentos master/secundário/tarefa e limites de progresso efetivos | Reservas concorrentes, recusa antes de exceder, retomada preserva consumo | Reservas, limites e retomada testados; browser usa estimativas |
| A06 | Recuperação integrada à run | Crash/restart retoma sem replanejar trabalho concluído | Retomada por checkpoint testada; falhas permanentes não são apagadas |
| A07 | Validadores independentes, segurança/adversarial obrigatórios quando aplicável | Quorum por identidade/papel; rejeição crítica bloqueia; cobertura baseada em evidência | Roles/quorum/evidências reforçados; independência estatística não garantida |
| A08 | Isolamento real, patches estritos e transações atômicas | Contexto incorreto, segundo arquivo inválido e falha de escrita não deixam edição parcial | Docker restrito integrado e testado; host continua exigindo confiança explícita |
| A09 | Caminhos, segredos e permissões de sessão | Escape, symlink, prefixo irmão, credenciais e negação de sessão testados | Snapshot filtrado readonly, sem rede/socket/credenciais; escopo de patch opcional e fixado por run |
| A10 | Rollback exato, aliases estáveis, idempotência e paginação por sessão | Criação desfeita, rollback alheio negado, replay não executa novamente | Verificado por sessão; journal durável de transações ainda pendente |
| A11 | Relay autenticado, persistente, lease/ack, TTL e correlação | Resultados forjados/obsoletos recusados; recuperação sem contaminar conversas | HTTP/SQLite/auth/lease/ACK/TTL testados; Edge real pendente |
| A12 | Diretivas chat → gateway → mesmo chat, sem IA central | Leitura/busca/paginação e continuação com IDs reais, limites e cancelamento | Loop direto integrado/testado localmente; continuação Edge real pendente |
| A13 | Project ≠ Run ≠ Conversation integrado e persistido | Duas runs compartilham conhecimento estável, sessões e conversas isoladas | Parcial: runs e conversas auditadas; conhecimento estável entre projetos pendente |
| A14 | Contexto consolidado para a central | Artefato versionado contém diff, testes, riscos, proveniência; nenhum rascunho promovido | handoff JSON/Markdown e patch integrados; envio ao chat central manual |
| A15 | Auditoria completa e métricas honestas | Falha, escalonamento, gate e hashes persistidos; tokens medidos vs estimados separados | Parcial: eventos/hashes e orçamento persistentes; métricas históricas/replay integral pendentes |
| A16 | Autoaperfeiçoamento usa OMA e não se autopromove | Baseline/benchmark/regressão/validadores reais; componentes protegidos exigem promoção externa | Usa IntegratedRun; sem router HOLD; sem autopromoção; benchmark comparativo pendente |
| A17 | Busca competitiva e grafo de evidências para pesquisa/implementação | Ramos limitados, seleção por verificadores, claims/experimentos/refutação/replicação com proveniência | Fora da prioridade operacional atual; pendente de integração |
| A18 | Referências Auxiliares e documentação coerentes | Reutilização justificada, licenças revisadas, mapa do código e instruções atualizados | README/mapa/instalação atualizados; análise das licenças Auxiliares pendente |
| A19 | Higiene de repositório | Credenciais/perfis/artefatos/runtime e Auxiliares fora do índice; arquivos locais preservados | Índice limpo de runtime/credenciais; arquivos preservados; histórico antigo não limpo |
| A20 | Regressão e comprovação ponta a ponta | Suíte relevante + fluxo completo; status live explicitamente comprovado ou pendente | Ver docs/docker-isolation-status.md; demo Docker pronta, piloto Edge falhou explicitamente no envio |

## Registro de execução

- 2026-09-12: estado atual revalidado; alterações prévias do usuário preservadas.
  Confirmados patch permissivo/parcial, rollback de criação incorreto e shell
  livre no runner. Início pelas garantias de filesystem/comandos, pré-requisito
  para habilitar o ciclo autônomo de agentes.


## Entrega operacional — 2026-09-12

- Prioridade solicitada: disponibilizar um caminho integrado utilizável antes de
  expandir pesquisa competitiva, referências externas e quantidade de agentes.
- Entrada única: `main.py --demo`, `--relay`, `--doctor`, execução com `--prompt`,
  `--status`, `--resume`, `--promote` separado; saídas de erro não zero.
- `IntegratedRun` trabalha em snapshots persistentes sob runs, preserva o
  checkout, salva checkpoint atômico e produz candidate.patch + handoff.json/md.
- Promoção externa repete testes, verifica hash/base e pede aprovação adicional
  para componentes protegidos. Sem commit ou deploy automático.
- SelfImprovementEngine deixa de forjar aprovações/score e não altera o root;
  a execução cognitiva usa o mesmo runtime OMA.
- Demo real da CLI concluída: run-f58de96836c0 (duas tarefas, modelos roteirizados,
  subprocessos/testes reais), sob `.oma/demo-83b24aba`.
- Doctor executado: dependências Python presentes; relay não estava acessível.
  Nenhuma conversa real foi enviada no Edge durante esta etapa.
- Evidência adicional: testes de CLI/promoção/retomada/concorrência/orçamento e
  teste HTTP com worker roteirizado. Não confundir worker roteirizado com Edge.
- Demo final run-e84fbf9aba86, sob `.oma/demo-d7371ed5`: leituras R emitidas pelo
  executor, respondidas ao mesmo worker, duas tarefas concluídas, pacote integrado
  aprovado. O teste confirma que essas mensagens de leitura não chegam ao master.
- Regressão: 171 passed, 3 skipped em 112,22 s. Após ampliar a demo para exercitar
  leituras diretas: 9 testes de integração/CLI/engine reexecutados e aprovados.
  Análise sintática Python: 137 arquivos, zero erros; JS verificado com node --check;
  git diff --check sem problemas de whitespace.
