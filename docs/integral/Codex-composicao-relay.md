# Codex — composição central de relay e autoridade CLI

11/10/2026. Fontes em composição; ZERO homologados. Nenhum teste, build,
install, lint, benchmark ou QA executado. Preview PID47408 intacto.

## Mudanças centrais nesta rodada

- `shell_runtime.py` e o subprocesso legado `service.py::_run_task` removem
  cápsula herdada e bearer/port de owner do ambiente. Chamam
  `prepare_provider_binding` com principal, projeto, conversa, Run, WorkItem e
  Operation do servidor; somente o environment protegido retornado vai ao CLI.
  O processo legado projeta sua autoridade atual antes de emitir a cápsula.
- MachineHost recebe adaptador Canvas e configuration handler de `code-mode`
  ANTES de restore. Removido segundo loop de restore manual. Kind
  `windows_guest_artifact` alcançável pelo mesmo configure_executor existente.
- Novo `sentra_canvas/shell_web.py::ShellWebRuntime` conecta o helper binário
  Cobalto à fila shell existente, shared ControlPlane, RelayServer autenticado,
  grant original de `web:send`/`web:attach`, budget reservation e lease/fence
  central. Nenhum Grant é criado pela composição.
- Reserva protegida do turno antes de staging/admit; os quatro arquivos são
  resolvidos de novo por owner/projeto/Space/conversa e SHA. Modelo e effort
  canônicos passam ao helper. Um conjunto, um job, um Send; nenhum downgrade.
- Grant ausente mantém a Operation QUEUED e projeta waiting_approval. A fila
  reavalia admissão sem staging/submissão. Crash após reserva ou envio torna o
  turno uncertain; recovery só observa o mesmo intent/result/receipt.
- Publicação exige `WebSend.status=ANSWERED`, receipt central attested e
  ChatResult final com task/conversa exatos. A projeção preserva Operation,
  mensagem assistente estável e digest do corpo. Final tardio pode reparar
  UNCERTAIN; nunca readmite ou reenvia. Listener fecha depois dos workers.
- Conversa relay ganha binding ao ID remoto; turnos seguintes usam o mesmo
  transporte inclusive sem refs. Conversa CLI prévia exige continuação
  explícita antes de migrar ao relay, evitando perder contexto silenciosamente.

## Contrato de composição física ainda aberto

`Canvas.attach_shell_relay_observers(*, account_attestor, assistant_observer)`
é slot SOMENTE servidor: não existe endpoint/renderer para registrar callable.
Ambos devem ser clientes reais de host/browser configurado e autorizado.

`account_attestor(control=shared, owner, project_id, message, dot, job)` deve
ler a conta física independente e retornar `account_verified=True`,
`requested_model`/`requested_effort` exatamente canônicos. É chamado novamente
na fase sending antes do ACK/fence físico. Não promover JSON config ou cache.

`assistant_observer(**selectors)` segue contrato exato da última seção de
`Cobalto-fechamento.md`, com observação física independente do FULL body SHA,
parent/role/complete e host_revision/collector/source/document/epoch. Vai ao
RelayServer/StreamingLedger attestor e `/jobs/response-frame`, nunca ao modelo.

Ainda fechar resolução de browser/perfil revisado e produtor de frames do
worker. Slot injetável não é contagem de fluxo integral concluído. Não usar
Host Electron como evidência de outro perfil/Edge. Falta de cliente real
mantém `model_delivery_available=False` com motivo explícito.

Configuração host-only `web_relay`:
`{enabled,extension_dir,token_file,port,models}`. `models` são nomes revisados
do host, não catálogo inventado; seleção física é reatestada. Token fica
somente servidor; RelayServer valida build/origin/bearer/worker/lease. Porta
fixa loopback permite bootstrap do pacote existente, sem abrir outro sender.

`home.attachments` preserva disponibilidade de armazenamento/chunks Brisa e
adiciona `model_delivery_available`/`model_delivery_reason` separados.
`proves_model_delivery=False` permanece até receipt de cada envio real.

## Continuidade do backlog

FB-01 coordenador conversacional, resolvers workflow/runtime/terminal,
serviços Selo/lifecycle, MCP agent-scoped, profile review/enrollment e demais
cláusulas de `fechamento-backlog.md` continuam abertos. Esta rodada não libera
validação nem transforma fontes/assinaturas/slots em homologação.
