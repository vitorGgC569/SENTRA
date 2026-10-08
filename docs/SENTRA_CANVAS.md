# SENTRA Canvas — MVP nativo experimental (Windows)

Este pacote é o gerenciador visual **SENTRA**, independente do aplicativo Maestri.
Foi construído em módulos novos para preservar as edições simultâneas no instalador,
onboarding, release, gateway e orquestrador. O executável agora faz parte da
definição do payload Windows e dos requisitos Setup/MSI; a validação do
instalador completo ainda está pendente.

## Inicialização

No código-fonte SENTRA, execute sentra_canvas/Iniciar-SENTRA.cmd (duplo clique)
ou, num PowerShell, a partir da raiz do repositório:

    python -m sentra_canvas --root "C:\Users\vitor\OneDrive\Desktop\SENTRA"

O lançamento abre uma janela independente do Windows por pywebview e WebView2,
sem abas de navegador. A API interna escuta apenas 127.0.0.1. Um serviço local
independente mantém os terminais e tarefas ativos quando a janela fecha;
reabrir a interface recupera a conexão com o mesmo serviço autenticado.
O token de conexão é protegido pelo sistema operacional em broker.json.
O comando Iniciar-SENTRA.cmd abre o executável do payload dist/sentra-canvas.exe,
quando presente, ou o código-fonte. O antigo binário experimental separado não
é escolhido automaticamente.

Para testes automatizados:

    python -m sentra_canvas --root "." --no-open

O modo --no-open executa o serviço no processo atual; Ctrl+C encerra os
processos gerenciados. Duas janelas reutilizam o mesmo serviço. Um segundo
serviço no mesmo diretório de estado é bloqueado. A opção --port permite
escolher outra porta local, embora a porta aleatória seja preferível.
Não publique a API em rede ou em proxies.

## Funcionalidades implementadas

- Workspaces independentes: diretórios sob .sentra/canvas/projects/ e IDs estáveis.
- Terminais CMD, PowerShell e PowerShell 7 (se disponível), com ConPTY Windows:
  streams incrementais, entrada de teclado, resize, graceful close, renomeação,
  duplicação em outro processo independente e quotas.
- A interface nativa usa xterm.js 6.0.0 para interpretar o fluxo VT original,
  com cores ANSI, cursor, teclado direto, IME, paste e resize por viewport.
  As dependências MIT são locais, versionadas e verificadas por hash durante o
  build; não dependem de CDN. O comando `python scripts/commander/vendor_canvas_terminal.py`
  reproduz os arquivos a partir de tarballs com SHA-512 fixado.
- Agentes SENTRA CLI iniciados em sessões de terminal independentes com modelo
  selecionável. A autenticação do modelo **não é presumida**.
- Equipes com coordenador e até 12 trabalhadores e delegação assíncrona.
- Provedor test determinístico, claramente identificado como sem IA, ou
  SENTRA CLI real, sujeito a aprovação explícita antes de possível escrita.
- SQLite WAL com transações, eventos por workspace, idempotência por chave,
  persistência de agentes/tarefas/workspaces e migração versionada.
- Namespaces por UUID no formato workspace/<id>/team/<id>/agent/<id>/session/<id>.
- Fechar/reabrir a janela mantém a conexão com os mesmos terminais ativos.
  Após uma falha/reinicialização do serviço, terminais anteriores viram
  interrupted e tarefas running viram uncertain, sem repetição automática.
- Histórico incremental dos terminais protegido por DPAPI no Windows,
  com retenção de 120 mil caracteres por terminal e cursores estáveis.
  Após reiniciar o serviço, esse histórico pode ser recuperado sem declarar
  que o processo anterior continua ativo. Falhas de armazenamento aparecem
  na API e na interface.
- Interface original desktop com barra lateral, canvas infinito com grade,
  zoom em torno do cursor, pan, nós arrastáveis/redimensionáveis, conexões
  persistentes, notes, inspector de recursos, tarefas e auditoria.
- Painel web legado permanece apenas como rota de diagnóstico/regressão;
  a janela principal usa /native.html e não abre um navegador.

## Componentes

| Arquivo | Responsabilidade |
| --- | --- |
| sentra_canvas/terminal.py | ConPTY Win32, pipes, streaming, resize, ciclo de vida |
| sentra_canvas/store.py | SQLite, identidade, isolamento e eventos |
| sentra_canvas/namespaces.py | Hierarquia de identidades sem Maestri |
| sentra_canvas/instance_lock.py | Instância exclusiva e estado seguro |
| sentra_canvas/broker.py | Serviço persistente, conexão autenticada e ciclo de vida da janela |
| sentra_canvas/service.py | Serviço de terminais, agentes, equipes e tarefas |
| sentra_canvas/__main__.py | API HTTP loopback autenticada e janela desktop |
| sentra_canvas/static/ | Interface HTML/CSS/JS |
| tests/unit/test_sentra_canvas.py | Testes de contratos, CLI, isolamento e segurança |
| tests/e2e/test_sentra_canvas_ui.py | E2E real no Edge, com imagem de evidência |

O SENTRA CLI reaproveita a implementação original e o Model Gateway disponível,
mas **nenhum sucesso de login/modelo externo é inferido** a partir do processo.

## Modelo de segurança

- Servidor restrito a 127.0.0.1 e cabeçalhos Host, Origin e Sec-Fetch-Site.
- Token de sessão exigido em todas as chamadas API, passado ao navegador como
  fragmento de URL e removido da barra após persistir em sessionStorage.
- A API valida IDs associados ao workspace do principal local.
- Criação de workspaces restrita à raiz autorizada do Canvas.
- ConPTY falha fechado quando não disponível, sem subprocesso de fallback.
- Limite de 12 terminais simultâneos, tamanho de entrada restrito, respostas
  de terminal retidas em memória até 120.000 caracteres.
- Terminal e CLI rodam com os privilégios do usuário Windows: isso **não é
  um sandbox**. Não execute prompts/comandos não confiáveis sem aprovação.

## Contratos da API local

Todas as rotas /api/* exigem Authorization: Bearer TOKEN.
POST exige Content-Type: application/json com corpo de no máximo 16 KiB.

| Método | Rota | Corpo ou consulta |
| --- | --- | --- |
| GET | /api/health | status de infraestrutura, sem afirmar modelo autenticado |
| GET | /api/workspaces | lista os workspaces acessíveis |
| POST | /api/workspaces | { "name": "meu_projeto" } |
| GET | /api/workspace?ws=ID | workspace, terminals, agents, teams, tasks, events |
| GET | /api/events?ws=ID&q=texto | busca auditável dentro do workspace autorizado |
| POST | /api/terminals | { "ws": "ID", "name": "t1", "shell": "cmd" } |
| GET | /api/terminal/output?ws=ID&id=ID&cursor=0 | texto, cursor e status |
| POST | /api/terminal/input | { "ws": "ID", "id": "ID", "data": "echo ok\r" } |
| POST | /api/terminal/resize | { "ws": "ID", "id": "ID", "cols": 100, "rows": 28 } |
| POST | /api/terminal/rename | { "ws": "ID", "id": "ID", "name": "novo_nome" } |
| POST | /api/terminal/duplicate | { "ws": "ID", "id": "ID", "name": "copia" } |
| POST | /api/terminal/close | { "ws": "ID", "id": "ID", "confirm": true } |
| POST | /api/agents | { "ws": "ID", "name": "worker", "model": "sentra/chatgpt-web/high", "start": true } |
| POST | /api/teams | { "ws": "ID", "name": "equipe", "coordinator": "ID", "workers": ["ID","ID"] } |
| GET | /api/team?ws=ID&id=ID | lista os membros e as funções |
| POST | /api/tasks | { "ws": "ID", "team": "ID", "agent": "ID", "prompt": "...", "request_key": "UUID", "provider": "test" } |
| POST | /api/task/cancel | { "ws": "ID", "id": "ID" } |

Para o provedor sentra-cli, a chamada POST /api/tasks deve trazer
provider=sentra-cli e approved=true. A escolha explicitamente autoriza as
ferramentas do CLI no diretório daquele workspace.
Status possíveis de tasks: queued, running, succeeded, failed, cancelled e
uncertain. Não existe reenvio automático de resposta incerta.

## Testes e artefatos

Executar dentro da raiz do repositório:

    python -m pytest -q tests/unit/test_sentra_canvas.py tests/e2e/test_sentra_canvas_ui.py

Evidência visual E2E gerada em:

    .sentra/canvas/evidence/canvas-e2e.png

## Pendências para concluir a missão integral

1. Ampliar a validação do renderizador VT para TUIs complexas, IME e paste
   no WebView2 nativo. Edge real já confirmou teclado direto, cores, cursor,
   resize e reanexação da página. O binário reconstruído passou em fechamento
   pelo botão nativo e reabertura em janela restaurada. Validar maximização/DPI.
2. Validar memória e retomada com resposta real de modelo entre processos.
   A persistência protegida das conversas e as identidades CLI/Canvas já estão
   implementadas; três processos do CLI compilado passaram em gravação,
   resume e busca. ConPTY não pode ser reanexado após a queda do seu processo.
3. Multiusuário, ACL por ferramenta/agente/equipe, sandbox real de processos,
   limites de CPU/RAM, prevenção contra outras gravações fora do workspace
   feitas pelo shell, RBAC e aprovação pela governança SENTRA.
4. Adaptador para jobs duráveis OMA, revisão independente, pausa, resume,
   mecanismo de aprovação central, compartilhamento seguro de contexto.
5. Catálogo de modelos e autenticação em tempo real via SENTRA Model Gateway;
   medição de tokens, consumo, jobs remotos e provider handoff.
6. Validar instalador completo, atalho, autostart e atualização do executável
   empacotado. Canvas já integra a definição do payload, mas a instalação
   completa do novo pacote ainda precisa de evidência executada.
7. Integrar test-runner Windows CI com E2E e assinar/publicar release.
8. Integrar o ciclo de vida do serviço Canvas ao runtime principal, diagnóstico,
   update e desinstalação, com recuperação de tarefas incertas pela governança.

## Interface de canvas e aplicativo Windows

**Executável independente (sem dependência de Maestri):**

    dist\sentra-canvas.exe

Para abrir a partir da raiz do projeto, execute sentra_canvas/Iniciar-SENTRA.cmd.
O script prefere o executável compilado. A janela desktop usa WebView2 e
o CLI já presente em dist/sentra-cli.exe para iniciar agentes reais.
Setup/MSI agora exigem essa entrada no payload. A validação do pacote completo
e a assinatura de código permanecem pendentes.

**Controles:** T novo terminal; A agente; E equipe; N nota; L conectar;
V selecionar; roda do mouse zoom; arraste do fundo pan; arraste do
cabeçalho move nó; arraste do canto redimensiona; Esc cancela;
Ctrl+0 enquadra. Clique em dois nós no modo L para ligar persistindo
uma aresta. Layout e links ficam segregados entre workspaces.

**Persistência:** o gráfico salva seus nós, notas e conexões no banco
.sentra/canvas/graph.sqlite3, com esquema versionado; o controle
transacional das sessões e tarefas está no canvas.sqlite3 separado.

**API gráfica autenticada:**

| Método | Rota | Campos |
| --- | --- | --- |
| GET | /api/graph?ws=ID | nós, links e metadados |
| POST | /api/graph/move | ws,id,x,y |
| POST | /api/graph/resize | ws,id,width,height |
| POST | /api/graph/note | ws,title,body,x,y |
| POST | /api/graph/note/update | ws,id,body |
| POST | /api/graph/note/delete | ws,id,confirm=true |
| POST | /api/graph/link | ws,source,target |
| POST | /api/graph/unlink | ws,id |

A UI é uma implementação original SENTRA inspirada em editores
de canvas conectados, sem copiar código, recursos ou identidade Maestri.

**Não está completa a equivalência com Maestri:** estão pendentes a
orquestração durável OMA, compartilhamento de contexto, tarefas
multiagente coordenadas, indicadores de consumo, ACL granular por
ferramenta, sandbox de processos, persistência de conversas dos agentes e
emulador terminal VT/TUI completo. A saída dos terminais é protegida e
recuperável; ConPTY não pode ser reanexado após a queda do seu proprietário. O ConPTY
real recebe comandos e apresenta streaming, mas o teclado e
a renderização de aplicativos TUI ainda são limitados.

## Integração de terminais SENTRA CLI, Codex e Antigravity (07/10/2026)

O seletor **Novo terminal** consulta GET /api/integrations autenticada
para detectar os executáveis disponíveis, sem aceitar caminhos arbitrários
enviados pelo navegador. Seleciona SENTRA CLI por padrão se instalado.

| Ambiente | Modo | Comportamento |
| --- | --- | --- |
| CMD, Windows PowerShell e PowerShell 7 | ConPTY | Shell nativo |
| SENTRA CLI | ConPTY | Sessão interativa no workspace |
| OpenAI Codex CLI | ConPTY | Sessão interativa com -C no workspace |
| Antigravity | Aplicativo gráfico | Abre o editor após confirmação; não é agente CLI |

Em builds congelados, o SENTRA CLI é localizado no executável
dist/sentra-cli.exe; o Codex é resolvido pelo codex.exe oficial
instalado. O backend usa apenas executáveis da lista permitida,
sem shell=True, com quotas e isolamento de recursos na API.

### Handoff manual entre nós conectados

Após ligar origem e destino no canvas, o inspetor do nó de origem
oferece **Enviar para CLI conectado**. O destino deve ser um terminal
SENTRA CLI ou Codex ativo, conectado por aresta dirigida, no mesmo
workspace. A ação exige confirmação. Mensagens têm até 4000
caracteres e não podem ter controles ou várias linhas.

POST /api/graph/handoff recebe ws, source, target, message, request_key e
approved=true; GET /api/graph/handoffs?ws=ID consulta o histórico
local. As mensagens ficam persistidas no SQLite graph.sqlite3.
**Não insira segredos no campo de handoff.**

### Agentes no Canvas nativo

O SENTRA CLI iniciado pelo broker recebe uma capacidade privada, ligada ao seu
terminal e workspace. Ela não autoriza endpoints de administração, criação de
workspaces ou encerramento do runtime. O token não é passado na linha de comando.
As conexões de saída do cartão do agente e do seu terminal definem os recursos
acessíveis. Uma conexão no sentido inverso não concede acesso.

- `[[CANVAS|list]]`: IDs, tipos e títulos dos recursos conectados.
- `[[CANVAS|note_read|ID]]` e `[[CANVAS|note_write|ID|texto]]`: contexto de notas conectadas.
- `[[CANVAS|dispatch|ID|mensagem]]`: mensagem de uma linha para o CLI de um agente conectado.
- `[[CANVAS|check|ID]]`: últimas 4.000 posições da saída do terminal conectado.

O resultado de dispatch comprova entrega ao transporte ConPTY, não confirmação
ou resposta do modelo. A identidade da chamada persistida pelo CLI serve como
request_key; uma repetição recupera o registro sem escrever novamente no terminal.
Falhas depois do início da escrita ficam incertas e não são reenviadas. Fechar o
terminal revoga a capacidade; reiniciar o agente gera uma nova capacidade.
Agentes nativos não herdam a identidade de um terminal Maestri externo.

Ao encerrar o broker, novas tarefas e terminais são recusados. O banco e o lock de
propriedade só são fechados depois da conclusão dos workers; se um worker não
terminar no prazo, a propriedade é mantida e o encerramento pode ser repetido.
Interromper uma tarefa com efeito pendente não a transforma em cancelamento confirmado.

### Fila persistente de tarefas

O broker mantém até quatro workers e 128 tarefas pendentes por usuário por padrão.
As tarefas de um mesmo agente executam em sequência; agentes diferentes podem
executar em paralelo. A autorização explícita acompanha a tarefa salva, de modo
que reiniciar o broker retoma apenas tarefas autorizadas que ainda estavam na fila.
Tarefas que já estavam em execução ficam incertas e não são reenviadas. Registros
antigos sem autorização salva permanecem aguardando autorização.

Cada tarefa tem `run_id` e `operation_id` no runtime durável comum do SENTRA.
Uma outbox gravada na mesma transação da tarefa permite recuperar a publicação
de estado após falhas. O registro comum contém apenas IDs e estados; instruções,
resultados e histórico ficam no armazenamento protegido. Uma falha ao registrar
o início impede o lançamento do worker. Cancelamentos em espera não iniciam
processos; cancelamentos durante execução só são confirmados com evidência.

Workers de tarefas também recebem a identidade do agente no Canvas para acessar
suas notas e conexões dirigidas. Essa capacidade é revogada ao terminar a tarefa.
O texto da instrução passa ao CLI por `--prompt-stdin`, por um pipe privado, sem
aparecer nos argumentos do processo. A entrada exige UTF-8 válido e até 4.000
caracteres. No Windows, tarefas e ConPTY são associados a um Job Object antes de
começar a executar; a queda do broker encerra os processos associados e seus
descendentes criados normalmente. Isso não é um sandbox para efeitos externos.

Instruções/resultados das tarefas CLI e entregas entre agentes são protegidos
com DPAPI no Windows. Registros antigos desses conteúdos são migrados ao abrir
os workspaces do usuário. A migração não altera workspaces de outro principal nem
transforma cópias históricas do banco em conteúdo protegido.

### Controle pelo Codex/Commander

`sentra_canvas` é a ferramenta compacta da superfície developer do MCP. Ela usa o
broker nativo autenticado, sem exigir o Maestri externo ou outro túnel. `status`
consulta o broker; `start` inicia ou reutiliza o mesmo proprietário. Os workspaces
visíveis e as ações permitidas seguem os grants do Commander. Execução no host
é recusada quando a política do Commander exige sandbox.

`workspace_attach` recebe `params={"name":"projeto","path":"C:\\..."}` para
anexar uma pasta existente aprovada. As demais ações recebem `workspace` como
ID, nome ou caminho. `agent_create`, `team_create`, `task_delegate`, consultas de
saída e notas, conexões e handoffs permitem coordenar o Canvas pela conversa.
`task_delegate` recebe team/agent/prompt e `confirm=true`; o provedor é o CLI real.

Alterações recebem um `request_key` persistente. O controle grava intenção e
resultado em recibos protegidos antes/depois da chamada HTTP. Reutilizar a chave
com argumentos diferentes é recusado; repetir um recibo concluído recupera sua
resposta original. Consulte `task_status` para o estado atual da tarefa. Uma
entrega ambígua exige `request_status` e resolução explícita com evidência;
`request_resolve` não reenvia a operação automaticamente.

`run_pause` impede novas admissões e preserva tarefas em espera. `run_cancel`
solicita cancelamento dos workers e encerra a execução atual. `run_resume` retoma
uma pausa; depois de uma execução encerrada cria uma nova execução, preservando
os IDs e resultados das tarefas antigas. Tarefas antigas canceladas não entram
na nova execução. Esse vínculo fica persistido no schema v5.

O retorno model_acknowledged=false significa que a mensagem foi
escrita no ConPTY e não que o provedor a processou. Conexões visuais
sozinhas não enviam mensagens automaticamente. Nunca se encaminham
prompts a CMD/PowerShell por este endpoint.

### Controle de tarefas e orçamento

Cada tarefa tem um work item no registro de governança compartilhado. Consulte
`task_governance`, com `params={"id":"ID_DA_TAREFA"}`, para ver execução,
validação, admissão e quota. `task_block` e `task_unblock` recebem o mesmo ID
e controlam tarefas na fila. Bloqueios persistem quando o serviço reinicia.
Uma tarefa interrompida com entrega incerta exige conferência; liberar a fila
não reenvia automaticamente uma tarefa que já começou.

`budget_set` aceita `scope=workspace`, `run` ou `work_item`, `limits` e `mode`
(`hard_stop` ou `warn`). Para work_item, informe também `task_id`. Exemplo:
`params={"scope":"workspace","limits":{"quota_usage":10}}` permite até dez
admissões de tarefas. Não há um limite de quota novo aplicado por padrão.
`budget_list` lista políticas do workspace. Para desativar uma política,
use `budget_set` com `params={"policy_id":"ID_DA_POLITICA","enabled":false}`.
As alterações seguem os mesmos grants e recibos protegidos do Commander.

Uma unidade de quota reserva uma tentativa antes de criar o processo.
Retomar a mesma admissão conferida não cobra outra unidade. Falha no início
do processo não estorna a reserva automaticamente. Essas reservas não medem
preço monetário nem o consumo de tokens do provedor. O consumo informado pelo
modelo é contabilizado separadamente e aparece no painel de atividade. Valores
ausentes aparecem como desconhecidos; cache e raciocínio não são somados duas
vezes ao total. A gravação usa uma fila durável e IDs da chamada original para
evitar cobrança duplicada após uma interrupção.

Limites de tokens verificam o uso informado antes de outra chamada. Uma chamada
já admitida pode ultrapassar um limite, pois sua saída não é conhecida de
antemão. Políticas hard_stop recusam novas chamadas quando o histórico capturado
tem consumo incompleto. Limites monetários hard_stop também recusam a chamada
quando o provedor não informa um preço verificável. Sem uma política configurada,
não há uma nova restrição aplicada por padrão.

A definição de uso de tokens segue a [documentação oficial de contagem](https://developers.openai.com/api/docs/guides/token-counting).

O painel de atividade mostra impedimentos e permite bloquear/liberar tarefas
na fila. A execução bem-sucedida deixa o resultado aguardando validação;
ela não substitui os critérios de qualidade e revisão do produto.

### Verificação de resultados

Ao delegar, você pode informar um arquivo e seu conteúdo esperado. Pela API,
`task_delegate` também aceita `checks=[{"path":"resultado.txt","text":"conteúdo"}]`
ou `checks=[{"path":"resultado.bin","sha256":"HASH_SHA256"}]`, até 16 arquivos
relativos ao workspace. Texto compara UTF-8 com quebras de linha normalizadas;
SHA-256 compara os bytes exatos. Os critérios ficam protegidos e não podem ser
alterados reutilizando a chave da tarefa.

Depois da execução real da CLI, o serviço verifica os arquivos, registra os
artefatos e a evidência e aplica a política de governança. Uma divergência deixa
o resultado para correção, preservando o registro da execução. Etapas de revisão
configuradas continuam valendo. Sem critérios, o resultado aguarda validação.

Use `task_verify`, com `params={"id":"ID_DA_TAREFA"}`, ou **Reverificar arquivos**
no painel para verificar uma correção sem repetir a tarefa. Alterações posteriores
à conclusão são sinalizadas, sem apagar a evidência histórica. A confirmação de
execução ocorre ao delegar, usando as permissões configuradas na instalação;
a interface não solicita outra autorização em uma caixa de diálogo.

### Testes reais executados

- SENTRA CLI 1.1.0: dois processos ConPTY reais iniciados em paralelo.
- Codex CLI 0.161.0: autenticado via ChatGPT e iniciado por ConPTY.
  Uma inferência codex exec em sandbox read-only retornou com marcador.
- Uma tentativa anterior pelo provedor Web falhou por autenticação/provedor.
  A rota nativa `sentra/codex/current` foi depois validada com inferência real,
  efeito de ferramenta pelo Canvas, retomada e memória entre conversas.
  Componentes CLI/Canvas compilados passaram essa validação. Isso não comprova
  o registro do plugin na conta ChatGPT Web, que continua com rejeição de vínculo.
- Gateway local e relay estão escutando; suas rotas protegidas
  exigem autenticação. Não houve reconfiguração de credenciais.
- Antigravity.exe está instalado como aplicativo Electron, sem
  CLI de agente compatível encontrado. A integração abre o editor.
- Handoff foi testado com transporte ConPTY real para um receptor
  simulado, sem alegar resposta real de IA entre modelos.

Não se converte a autenticação OAuth do Codex em chave de API
OpenAI para o SENTRA. As aprovações e o sandbox do Codex continuam
sob controle do próprio CLI.
