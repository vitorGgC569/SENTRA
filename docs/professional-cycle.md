# Ciclo integrado — 2026-09-13

## O que mudou nesta rodada

- O revisor interno final usa o mesmo gateway somente leitura, sobre uma cópia do **hash candidato testado**. Diretivas de leitura não viram rejeição técnica.
- `review-<candidate>.json` preserva patch, pacote e evidência antes da revisão. Resposta inválida/indisponibilidade bloqueia sem regenerar. Rejeição técnica retorna ao mesmo reparador, com o candidato e os limites restantes.
- CLI operacional exige notas explícitas. Confiança não vira nota de qualidade; 9.499 não passa uma barra de 9.5 por arredondamento. Biblioteca mantém compatibilidade legada quando o modo estrito não é solicitado.
- Contratos distintos para planejar, executar, reparar, julgar e seis especialidades críticas. Crítica deve apresentar evidência; inventar defeitos também é erro. Contrato do papel prevalece sobre formato embutido no objetivo e histórico de chat.
- `MASTER_QUEUE`: importação atômica SQLite, prioridades, dependências sem ciclos, IDs idempotentes, configuração congelada e reserva de orçamento por tarefa. Um worker executa uma tarefa por comando usando **IntegratedRun**, não outro motor.
- Conversas da fila persistem por projeto, compartilhadas pelas runs da fila. Histórico anterior não substitui contexto fresco. Conversas antigas de runs avulsas não são adotadas silenciosamente.
- Caixa de entrada central recebe somente handoff final verificado, com vínculo de hashes/testes. Leitura e recibo são separados, idempotentes. **Importação de contexto não promove código nem injeta automaticamente uma mensagem no Codex.**
- Gates de escala admitem 5–6 assentos inicialmente. 7–8 exigem pelo menos três runs live recentes no patamar anterior, taxa de candidato pronto >=80%, p95 <=1800s, identidades observadas e nenhuma incerteza/estouro. Evidência de mocks, repetida ou de outra versão/configuração não conta. São heurísticas conservadoras, não limites oficiais da conta.
- Rota API explícita `openai`, sem retry automático, preserva modelo solicitado/observado e consumo do servidor. Browser genérico não é chamado de Sol.
- Métricas distinguem tentativa atual de histórico persistido; zero validações não aparece como 100% de aprovação no JSON.

## Operação

Na raiz do controlador, use um workspace de trabalho seguro e um config do operador com Docker preparado. Edite o exemplo de manifesto antes de importar; o exemplo não foi enfileirado automaticamente.

```powershell
python -B main.py --workspace <REPO_SEGURO> --config <CONFIG_DOCKER> --queue import --manifest docs/MASTER_QUEUE.example.json
python -B main.py --workspace <REPO_SEGURO> --queue status
python -B main.py --workspace <REPO_SEGURO> --queue run
python -B main.py --workspace <REPO_SEGURO> --queue inbox
python -B main.py --workspace <REPO_SEGURO> --queue ack --job-id bounded-improvement-001 --context-digest <HASH_LIDO> --consumer central
```

`run` usa a configuração congelada na importação. Não sobrescreve limites com flags posteriores. Testes no host exigem `--trust-workspace` explicitamente; isso não é sandbox. Tokens e segundos são alocações conservadoras, não reais/unidades monetárias nem garantia contra limite do provedor. A soma dos budgets alocados não pode exceder a fila, nem mesmo reimportando após falha. Não há refund automático.

Promoção continua separada: `--promote mq-<job-id>`, usando o mesmo backend/política verificada e aprovação externa adicional para componentes protegidos. Dependências aguardam **APPLIED**, não apenas candidato pronto/recibo, porque o código de uma run não aparece magicamente na próxima.

Após interrupção, RUNNING/BLOCKED não é reenviado. Inspecione handoff, eventos, budgets e `.oma/master-queue/conversations/conversations.json`. Para encerrar a tarefa sem replay/refund: `--queue abandon --job-id <id> --reason <motivo>`. Incerteza nos assentos continua exigindo reconciliação; abandonar a tarefa não autoriza descartar um envio incerto. Não existe retomada automática de tarefa da fila nesta versão.

## Calibração Sol

A documentação oficial consultada identifica `gpt-5.6-sol` e Responses API. A identidade é registrada da resposta da API, não de texto produzido pelo modelo. Fontes: https://developers.openai.com/api/docs/models/gpt-5.6-sol e https://developers.openai.com/api/docs/guides/text.

```powershell
python -B scripts/prepare_self_improvement.py --case compute-policy --agents 6 --provider openai --model gpt-5.6-sol --run
python -B scripts/calibrate_quality.py <PASTA_DA_RUN> --required-model gpt-5.6-sol
```

Requer `OPENAI_API_KEY` configurada pelo operador e quota/crédito API. Não copie credenciais do Codex, cookies ou auth.json. Sem chave, falha antes de iniciar a calibração. O piloto conserva seu teto menor de 4 reparos, estagnação 5, budgets 20k/200k/150k, 900 segundos por padrão. O teto geral é 15. Não se exige que notas reais percorram 8→9→9.6; isso é um caso de teste determinístico, não uma meta a induzir no avaliador.

## Caso: site estático (diagnóstico delimitado)

Referência genérica (nomes de runs/projetos omitidos): handoff **FAILED, 0/4**,
não um produto aprovado. O candidato pertencia a T-01 (estrutura); design
visual, interação e validação completa eram tarefas separadas. Não havia
relatório de validação persistido para aquele V2 no arquivo consultado. O V1
foi avaliado principalmente por semântica/IDs HTML; houve falha de perfil por
inexistência de testes. Isso exige tarefas em fatias completas, com teste
desde a implementação, além de critérios visuais observáveis.

HTML com textos genéricos, composição baseada em títulos/cards e números
promocionais sem evidência apresentada. Testes de existência de
arquivos/marcadores não avaliam design, fidelidade visual, responsividade
observada ou utilidade. Aumentar rounds/nota por si só não resolve esse
contrato. Os prompts agora explicitam a limitação, mas **um pipeline
automático de avaliação visual com screenshots e avaliador multimodal ainda
não está integrado**.

## Limites de fechamento

Esta rodada integra controle e entrega local. Não transforma o protótipo em produto final certificado: calibração Sol live depende de credencial/quota, gate de escala depende de amostras reais, entrega automática ao chat central requer um consumidor conectado e design de sites exige avaliação visual. Não houve autopromoção, commit do checkout nem alteração de previews/baselines de projeto.
