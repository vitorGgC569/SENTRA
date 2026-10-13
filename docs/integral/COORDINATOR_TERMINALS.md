# Terminais persistentes da implementação

Em 11/10/2026, os seis OpenCode foram convertidos de `opencode run` para
`opencode --auto --session <id> --prompt <tarefa>`, nos mesmos nós do Maestri.
As sessões salvas conservam Muse Spark 1.3 Free e variante high. A interface
interativa permanece disponível depois de concluir a tarefa. Os IDs foram
consultados pela API oficial do serviço local, sem copiar credenciais.

| Responsável | Sessão persistente |
|---|---|
| Vitra | ses_ed5c21f5cffeRkntIpZ7qTg3vY |
| Pacto | ses_ed5c21c60ffeezqQSymW2ePg9C |
| Brisa | ses_ed5c7eba6ffeoh2KFIeC5XLvUv |
| Selo | ses_ed5c7e42cffeZUHsMqjV2cGaIV |
| Pulso | ses_ed5c7e785ffe1T9ZNEJe5NsfvN |
| Rastro | ses_ed5c7edbeffe21fglg9rKH4V5h |

Progresso e contratos devem ser escritos em `docs/integral/<Nome>.md`.
Uma chamada síncrona `maestri ask Codex` pode expirar enquanto o principal
está trabalhando: não reenviar o mesmo resultado nem presumir falha de
implementação. Consultar o processo e a sessão antes de reiniciar.
Prompts simples só devem ser enviados depois de confirmar que o destinatário
está na interface do agente, nunca em um prompt PowerShell.

Nenhum teste, build, lint, benchmark ou QA do produto foi liberado. A matriz
de requisitos continua aberta até a implementação e composição integral.

## Quota OpenCode e transferência autorizada

O usuário pediu explicitamente um Codex adicional em 11/10/2026 para fechar as
seis frentes. `maestri check` mostrou Rate limit exceeded em Pacto/Pulso/Selo/Vitra;
Rastro/Brisa preservam seus últimos resultados nos fontes/relatórios. Os terminais
e históricos OpenCode foram conservados. Não relançar tarefas neles enquanto
vigora a transferência de ownership.

Cobalto foi recrutado com preset Codex, gpt-6.1-sol high, YOLO/full access,
PID28432; UI e argumentos do processo confirmaram os três parâmetros. Conectado
à nota integral e a Meridiano/Nexo/Prisma/Forja/Lume/Tessela. Tarefa e limites em
`tasks/Cobalto.md`; consolidação inicial esperada em `Cobalto-status.md`.
Cobalto assume implementação pendente de Rastro/Brisa/Pacto/Pulso/Selo/Vitra,
sem duplicar o trabalho entregue nem editar os domínios Codex ativos. Root continua
compondo Canvas/HTTP/MCP. Preview PID47408 permanece intocado; não há liberação
de validação com esta mudança de modelo/equipe.
