# SENTRA OS — CHAT 1/3 — Provas e handoff (10/10/2026)

## Escopo
Documentos lidos: docs/SENTRA_COS_4_CONVERSAS_2026-10-10.md seção CHAT 1 e
docs/SENTRA_COS_EXECUCAO_INTEGRAL_2026-10-10.md.
Execução real pelo Desktop Commander em OGrandeOxta, repositório:
C:\Users\vitor\OneDrive\Desktop\SENTRA.
Checkout partilhado preservado: SEM reset, checkout, stash, commit, push,
mudança de credenciais/cookies ou alterações nas fachadas centrais reservadas.

## Arquivos editados no escopo
- sentra_interop/mcp_http.py (NOVO)
- sentra_mcp/services/mcpb_http.py (NOVO)
- sentra_mcp/services/plugin_bundles.py
- sentra_mcp/services/tool_exposure.py
- sentra_mcp/services/skill_library.py
- tests/unit/test_sentra_cos_mcpb_http.py (NOVO)
- tests/unit/test_sentra_cos_mcpb_schema_snapshot.py (NOVO)
- tests/unit/test_sentra_cos_mcpb_lifecycle.py (NOVO)
- tests/unit/test_sentra_cos_skill_workitem_revision.py (NOVO)
- docs/SENTRA_COS_AGENT_1_2026-10-10.md (este arquivo)

## Implementações verificáveis
1. MCP HTTP: cliente JSON-RPC 2025-06-18 limitado a IP loopback literal
   com porta explícita, sem DNS/proxy/redirecionamento/retry/cookie/SSE.
   Bearer token efêmero fornecido por callback do host; não persiste nem
   revela tokens. Recusa requests sem OperationRequest/grant autorizado.
   É suporte a bearer efêmero, NÃO um fluxo OAuth2 completo.
2. MCPHttpRegistry: catálogo operador-approved no SQLite plugin_bundle,
   owner/workspace/server_id/endpoint pinados, enable/revision e revogação.
   execute(...) exige Run e WorkItem reais, assignee e agente do Run,
   grants independentes mcp:http-connect, mcp:list, mcp:<tool>,
   DurableInteropGate com Operation e fences, revalidação de endpoint e
   dos 3 grants antes/depois de initialize/tools/list/tools/call, retorno
   apenas text-only limitado e checagem de segredos óbvios. Repetição de
   operation_id/idempotency_key NÃO reenvia POST.
3. MCPBBundleCatalog.update: revisão nova previamente staged/verificada,
   mesmo nome/publisher/tipo, operador aprova, anterior desativada ANTES
   de registrar nova; sem grants ou worker. Falha parcial fail-closed com
   revisão antiga desativada. Uninstall marca status REMOVED tombstone
   permanente, sem reativar; archive permanece por auditoria e operações.
   disk_purge_completed=False (NÃO desinstalação física completa).
4. ToolExposureRegistry: snapshot seletivo provider+tool ACL com
   generation persistida no SQLite e schema_sha256 canônico; detecta
   refresh até em mudança A->B->A. Reservas/collisions globais preservadas
   inclusive quando disabled. Impede provider_id sentra-core malicioso.
   Snapshot cria ZERO grants e NÃO prova sincronização de Web account.
5. SkillLibrary: deactivate por WorkItem e replace_activation transacional
   por dois SHAs diferentes; valida owner/workspace/assignee/estado real,
   mantém proteção dos snapshots e impede disclosure pós revogação.

## Provas REALMENTE executadas
Seleção pytest executada por Python Windows no checkout, incluindo:
tests/unit/test_sentra_cos_mcpb_http.py
tests/unit/test_sentra_cos_mcpb_schema_snapshot.py
tests/unit/test_sentra_cos_mcpb_lifecycle.py
tests/unit/test_sentra_cos_skill_workitem_revision.py
tests/unit/test_sentra_cos_mcpb_registration.py
tests/unit/test_sentra_cos_mcpb_activation_plan.py
tests/unit/test_sentra_cos_mcpb_import.py
tests/unit/test_sentra_cos_mcpb_sandbox_execution.py
tests/unit/test_sentra_cos_tool_exposure.py
tests/unit/test_sentra_cos_plugin_namespace.py
tests/unit/test_sentra_cos_skill_library.py

Comando: python -B -m pytest [arquivos acima] -q --tb=short
RESULTADO FINAL: 34 passed, 1 skipped, exit 0, 13.41s.
Skipped = requisito de privilégio Windows para symlink no teste Git Skill.
Py compileall de mcp_http, mcpb_http, plugin_bundles, tool_exposure,
skill_library: exit 0.
Git diff --check: exit 0 (avisos CRLF/LF em outros arquivos partilhados).

Teste hermético MCP HTTP com HTTPServer real 127.0.0.1 e JSON-RPC
initialize, tools/list e tools/call: sem grants = zero POST; com 3 grants
persistidos por WorkItem = Operation SQLite SUCCEEDED, conteúdo HTTP_OK,
token de teste somente em memória. Replay não enviou nova requisição.
Revogação de mcp:echo e endpoint desativado bloquearam POST novo.
SSRF por host DNS, link-local, query, fragment e usuário na URL negados.
NÃO houve OAuth externo nem conta ChatGPT Web nessa prova.

Skill: duas revisões SHA, Run/WorkItem reais, dois agentes,
disclosure isolado por assignee, troca atômica, leitura revogada
negada. Lifecycle MCPB: troca aprovada, publisher mismatch bloqueia,
antigo DISABLED, novo REGISTERED, uninstall REMOVED e archive retido.
Namespace: schema SHA e geração persistidos, colisão case-insensitive,
seleção por tool e tombstone core testados. Suites sobrepostas não somadas.

## Handoff EXATO para coordenador (sem editar fachada nesta conversa)
Criação pela fachada central:
from sentra_mcp.services.mcpb_http import MCPHttpRegistry
registry = MCPHttpRegistry(control_plane)
registry.register(owner,workspace,server_id,endpoint,approved=True)
registry.get(owner,workspace,server_id)
registry.disable(owner,workspace,server_id,approved=True)
await registry.execute(owner=...,workspace=...,server_id=...,run_id=...,
  work_item_id=...,agent_id=...,tool_name=...,arguments=...,
  operation_id=...,idempotency_key=...,access_token=callback_efemero_do_host)

Crucial: aprovação humana e autenticação do operador ANTES de registro
e revogação HTTP na fachada/Canvas; nunca enviar callback/token em rota
HTTP nem persistir bearer. mcp:http-connect é diferente de mcp:launch,
pois a política central reserva launch para processos com paths/argv
fixados. O endpoint HTTP vem de registro operator-approved, não de MCP
ou texto de um agente.

Facade bundle:
control_plane.bundle_catalog.update(owner,workspace,old_sha,new_sha,
  control_plane.governance,approved=True)
control_plane.bundle_catalog.uninstall(owner,workspace,sha,
  control_plane.governance,approved=True)
Fazer UX de revisão por SHA/publisher/versão e human approval.

Exposição/refresh:
control_plane.tool_exposure.publication_snapshot(
  provider_ids,allowed_names=[...],previous={"generation":N,"schema_sha256":H})
Retorna tools,generation,schema_sha256,changed,grants_created=False.
Provider IDs e allowed_names devem vir da ACL do host, não do modelo.
Pelo menos um refresh remoto REAL por provider/conta precisa ser provado.

Skill UI:
control_plane.skill_library.deactivate(owner,workspace,package_sha,
  work_item_id,agent_id)
control_plane.skill_library.replace_activation(owner,workspace,
  old_sha,new_sha,work_item_id,agent_id)
Só ativação/desativação explícita no WorkItem real.

## Limitações, riscos e bloqueios ainda abertos
- Este HTTP é stateless JSON-RPC em endpoint local pré-existente; não
  instala/inicia automaticamente um servidor HTTP MCPB padrão. Não há
  suporte MCP Streamable HTTP SSE, sessão obrigatória, OAuth2 PKCE/
  authorization-code/refresh/revoke vault. Token efêmero não é OAuth E2E.
- Infra stdio Docker já estava implementada ANTES do CHAT 1 nesta rodada.
  mcpb_sandbox.py reservado ao coordenador. Orphan reconcile verdadeiro
  requer registrar container_name + image ID + ownership e lease no SQLite
  ANTES de iniciar Docker e limpar somente containers comprovadamente
  pertencentes a Operation. Não apagar contêineres apenas por prefixo.
- Health/restart supervisionado, instalação isolada de dependências,
  instalação completa HTTP/Node, rollback de update entre dois bancos,
  desinstalação com safe disk purge, sincronização de schemas na conta
  ChatGPT Web, assinatura/CI e Setup/MSI ainda NÃO concluídos.
- Nenhum fluxo credencial OAuth foi executado. Nenhuma UI central,
  ControlPlaneService, sentra_mcp/server.py, sentra_canvas/service.py
  ou mcpb_sandbox.py foi alterado nesta conversa.
- Não homologar G01/A06/A07/G07/A21 nem 34/34 E2E externo a partir
  destes testes herméticos locais. Sem commit/push global.

## Estado
Código e testes efetivamente presentes no checkout compartilhado, pronto
para consumo da coordenadora pelas assinaturas acima. Produto NÃO homologado.


---

# 7 FRENTES — CHAT 1 — RODADA ADICIONAL (10/10/2026)

Lido docs/SENTRA_COS_SETE_FRENTES_2026-10-10.md, seção Chat 1. Trabalhei
diretamente no checkout compartilhado OGrandeOxta. Nenhuma edição feita em
mcpb_sandbox.py, ControlPlane, Canvas, edge_extension ou native_bridge;
nenhum reset, checkout, stash, clean, commit, push ou leitura de cookies,
tokens reais de conta, arquivos secretos ou credenciais. Código local ainda
NÃO homologado E2E.

## Arquivos desta rodada (todos dentro dos direitos de escrita)

Novos serviços:
- sentra_mcp/services/mcpb_oauth.py
- sentra_mcp/services/mcpb_orphans.py
- sentra_mcp/services/mcpb_offline.py

Alterados:
- sentra_interop/mcp_http.py
- sentra_mcp/services/mcpb_http.py
- sentra_mcp/services/plugin_host.py
- sentra_mcp/services/plugin_bundles.py

Novos testes:
- tests/unit/test_sentra_cos_mcpb_oauth.py
- tests/unit/test_sentra_cos_mcpb_streamable.py
- tests/unit/test_sentra_cos_mcpb_orphans.py
- tests/unit/test_sentra_cos_mcpb_offline.py
- tests/unit/test_sentra_cos_mcpb_worker_health.py

Teste ampliado: tests/unit/test_sentra_cos_mcpb_lifecycle.py (rollback).

## Funcionalidade entregue

OAuth2: MCPBOAuthPKCE usa state/verifier único em RAM, challenge S256,
callback literal loopback, prazo 300s e operador approved. OAuthDPAPIVault
usa win32crypt/Windows DPAPI CurrentUser com entropy vinculada ao tuple
owner,workspace,server_id; ciphertext BLOB em plugin-bundles.sqlite3
existente, nenhuma chave/token em claro persistido, sem dados sensíveis
nas APIs de status. Refresh grava estado REFRESHING antes de enviar ao
provedor; falha incerta vira UNCERTAIN com ciphertext nulo, reinício
não reenvia. Revogação local apaga ciphertext. revoke_remote registra
REVOKING ANTES do efeito, depois REVOKED ou REVOKED_UNCONFIRMED, zero
retry após falha. PinnedOAuthHTTPS aceita unicamente HTTPS,
DNS validado contra IPs públicos, TLS validado contra hostname,
sem redirect/proxy/cookies/retry, POST único para code/refresh;
não foi conectado a um provedor externo real.

MCP Streamable HTTP: modo operator-approved streamable=True no registro
MCPHttpRegistry, salva flag no SQLite com migração. Implementados
Mcp-Session-Id com identidade imutável, notifications/initialized 202,
respostas JSON e SSE event: message com limites, sem repetição em estado
uncertain. Cada Operation cria cliente próprio: INITIALIZING -> ACTIVE
-> COMPLETED/UNCERTAIN no SQLite central plugin_bundle; session_status
read-only e reconcile_abandoned converte sessões abandonadas em
UNCERTAIN após grace (nenhum POST, kill, retry ou false health claim).
Compatibilidade com HTTP JSON stateless anterior preservada. Import
lazy de CentralInteropAdapter corrigiu conflito circular quando a
fachada compartilhada do coordenador passou a importar mcpb_http.

MCPBDockerOwnership em mcpb_orphans.py: registra claim aleatório,
container_name, image sha256, Run/WorkItem/Operation centrais e owner
ANTES do lançamento no SQLite. bind exige Docker inspect com image ID,
labels exatas, name e container ID de 64 hex; cleanup_candidate
requer operador, grace>=30s, Operation e inspect exato e apenas gera
candidato (performed=False). mark_cleaned exige confirmação de
ausência do ID. NÃO houve docker rm, Docker real crash fixture ou
processos de terceiros encerrados. Coordenador deve integrar
mcpb_sandbox.py dentro do gate físico.

mcpb_offline.py: preflight de requirements.lock com name==version
e --hash=sha256, wheel py3-none-any e inventário limite, checksum,
ZIP symlinks/path-traversal/size/inventory recusados; comando pip
no-index/require-hashes/no-deps/no-cache-dir é CANDIDATO INERTE,
exclusivamente para sandbox offline pinado. Nenhuma instalação foi
executada, nenhuma dependência host adicionada.

PluginWorkerHost.health: checa identidade sessão ProcessService, owner,
run_id, operation_id e running; PID isolado não prova ownership.
reconcile_worker: sem sessão exata, READY/HANDSHAKING vira FAILED,
exposure.disable e governance DISABLED, sem auto-restart inseguro.
Rollback MCPBBundleCatalog.rollback: operador aprova, valida revisões
imutáveis e publisher, corrente REGISTERED e anterior DISABLED e
inerte. Desabilita corrente, readmite anterior sem worker/grants.
Não afirma rollback atômico entre bancos separados. Uninstall
mantém arquivo imutável para auditoria: não há safe disk purge.

## Provas e comandos EXECUTADOS

Regressão conjunta (sem somar contagens sobrepostas):
python -B -m pytest
 tests/unit/test_sentra_cos_mcpb_oauth.py
 tests/unit/test_sentra_cos_mcpb_streamable.py
 tests/unit/test_sentra_cos_mcpb_orphans.py
 tests/unit/test_sentra_cos_mcpb_offline.py
 tests/unit/test_sentra_cos_mcpb_worker_health.py
 tests/unit/test_sentra_cos_mcpb_lifecycle.py
 tests/unit/test_sentra_cos_mcpb_http.py
 tests/unit/test_sentra_cos_mcpb_schema_snapshot.py
 tests/unit/test_sentra_cos_mcpb_registration.py
 tests/unit/test_sentra_cos_mcpb_activation_plan.py
 tests/unit/test_sentra_cos_mcpb_import.py
 tests/unit/test_sentra_cos_mcpb_sandbox_execution.py
 tests/unit/test_sentra_cos_tool_exposure.py
 tests/unit/test_sentra_cos_plugin_namespace.py
 tests/unit/test_sentra_cos_skill_library.py
 tests/unit/test_sentra_cos_skill_workitem_revision.py
 -q --tb=short

RESULTADO: 46 PASSED, 1 SKIPPED, 0 FAILED, exit 0, 19.22s.
Skipped = criação de symlink sem privilégio Windows. compileall -q
nos nove serviços editados: exit 0. git diff --check: exit 0,
somente avisos de CRLF/LF em arquivos de outros agentes.
Nenhum teste Node nesta frente Python; Node não executado.

DPAPI REAL Windows: tokens de fixture ciphertext no arquivo SQLite;
strings de acesso/refresh ausentes dos bytes de DB; reload em novo
objeto vault conserva acesso owner correto; outro owner não acessa;
refresh timeout mantém UNCERTAIN sem nova tentativa mesmo após restart;
revoke_remote usa callback local uma vez, guarda incerteza caso falhe.
Prova NÃO envolve OAuth de provedor externo.

HTTP real: TCP 127.0.0.1, initialize, notifications/initialized,
tools/list, tools/call SSE e JSON com session ID; Run/WorkItem e
grants reais; Operation SUCCEEDED e repetição não reenviou HTTP POST.
Crash simulado no SQLite marca sessão abandonada UNCERTAIN, sem reenvio.
Docker orphan ownership: Run/WorkItem/Operation SQLite reais,
claims/labels/ID/image mismatch negados; não invoca Docker para remoção.
Offline wheel: fixture zip MCPB com wheel real e sha locked;
online index e alterações após stage negados. Worker health:
governance/worker SQLite reais, ProcessService session evidence
controlada em fixture, sem iniciar processo; liveness perdida bloqueia.
Rollback aprovado/desaprovado e tombstone tratados.

## Handoff EXATO ao coordenador (não editar fachadas no Chat 1)

OAuth host-only:
  from sentra_mcp.services.mcpb_oauth import OAuthDPAPIVault, MCPBOAuthPKCE, PinnedOAuthHTTPS
  vault = OAuthDPAPIVault(control.store)
  https = PinnedOAuthHTTPS(approved_https_token_url)
  pkce = MCPBOAuthPKCE(authorize_url=approved_https_authorize_url,
      token_url=https.token_url, client_id=reviewed_public_client_id,
      redirect_uri=approved_loopback_callback, scopes=("tool.read",),
      vault=vault)
  pkce.begin(owner,workspace,server_id,approved=True)
  pkce.finish(owner,workspace,server_id,state=callback_state,
      code=callback_code,exchange=https.exchange_code,approved=True)
  vault.refresh(owner,workspace,server_id,
      lambda refresh: https.refresh(reviewed_public_client_id,refresh))
  vault.revoke_remote(owner,workspace,server_id,
      send=host_authorized_revoke_once,approved=True)
  vault.access(owner,workspace,server_id)  # somente host!

Coordenador: implementar receiver loopback CSRF+state com human approval
autoritativo, seguro contra spoof; nunca passar token em rota/modelo,
nunca prometer permissão sem prova real do provedor. Integração de
revoke remoto exige callback HTTPS seguro do próprio provedor.

HTTP:
  from sentra_mcp.services.mcpb_http import MCPHttpRegistry
  registry = MCPHttpRegistry(control)
  registry.register(owner,workspace,server_id,loopback_url,
      approved=True,streamable=True)
  await registry.execute(owner=owner,workspace=workspace,
      server_id=server_id,run_id=run_id,work_item_id=work_item_id,
      agent_id=agent_id,tool_name=tool_name,arguments=arguments,
      operation_id=op_id,idempotency_key=idem_key,
      access_token=lambda: vault.access(owner,workspace,server_id))
  registry.session_status(owner,workspace,op_id)
  registry.reconcile_abandoned(owner,workspace,min_age_seconds=60)

Requer grants independentes mcp:http-connect, mcp:list, mcp:<tool>
dentro do WorkItem, autorização owner e aprovação humana HTTP/Canvas.

Docker sandbox, para coordenador integrar APENAS sob gate físico:
  from sentra_mcp.services.mcpb_orphans import MCPBDockerOwnership
  ledger = MCPBDockerOwnership(control)
  claim = ledger.prepare(owner=owner,workspace=workspace,run_id=run_id,
      work_item_id=work_item_id,operation_id=op_id,image_id=pinned_image_id)
  # docker run --name claim.container_name e labels exatas de
  # claim.docker_labels, depois inspect real com ID/imagem.
  ledger.bind(owner,op_id,inspect_object)
  ledger.cleanup_candidate(owner=owner,operation_id=op_id,
      inspect=fresh_inspect,approved=True,min_age_seconds=60)
  # Revalidar fencing, inspecionar NOVAMENTE e remover APENAS ID exato;
  # conferir ausência antes de:
  ledger.mark_cleaned(owner,op_id,observed_absent=True)

Dependências:
  from sentra_mcp.services.mcpb_offline import preflight_offline_wheels
  plan = preflight_offline_wheels(control.bundle_catalog,owner,workspace,
      immutable_mcpb_sha,control.governance)
  # executar sandbox_command_candidate SOMENTE no Docker pinado e físico,
  # sob mesma Operation/Grant/Lease, jamais host pip.

Worker:
  host.health(plugin_worker_id, owner)
  host.reconcile_worker(plugin_worker_id, owner)
  # reinício requer operação nova, grant, sessão e handshake novos.

Bundle:
  catalog.rollback(owner,workspace,current_sha,previous_sha,
                   governance,approved=True)

## Bloqueios não homologados

- Não houve OAuth real/PKCE consent confirmado pelo navegador/conta
  externa, nem token real lido. pywin32 no instalador Windows ainda
  depende de empacotamento/teste Setup.
- Streamable HTTP suporta SSE via resposta POST e session ID, mas
  GET stream contínuo, Last-Event-ID, session DELETE com grant próprio
  e reconciliação remota de efeitos seguem pendentes.
- Wheel install em Docker e dependências runtime offline não executados;
  preflight é prova de integridade, não prova de execução.
- Docker ledger precisa integração efetiva em mcpb_sandbox.py pelo
  coordenador e teste de crash físico/cleanup real. Sem GC PID/prefixo.
- Restart de worker supervisionado com autorização nova ainda não
  existe; somente health/fail-closed implementados.
- Uninstall físico safe purge e rollback cross-DB atômico não fechados.
  A política atual prioriza tombstone e retenção de auditoria.
- E2E completo conta ChatGPT, schema remoto, release Setup/MSI e
  homologação 34/34 continuam NÃO COMPROVADOS.

ESTADO: código e testes REAIS no checkout compartilhado; pronto para
handoff e integração autorizada, NÃO HOMOLOGADO para produção.


### Adendo de validação final (mesma rodada, substitui a contagem 46/1 acima)

Foi concluído também PinnedOAuthHTTPS.revoke(token): exige endpoint HTTPS de
revogação aprovado com mesmo hostname do token endpoint, POST de efeito único,
resposta 200/204 vazia confirmada, sem redirect, proxy ou retry; o callback
de revogação do vault continua vinculando revogação local antes do efeito
remoto, registrando estado unconfirmed quando necessário. Foi reforçado
o Streamable MCP: notifications/initialized agora exige HTTP 202 sem corpo,
fail-closed se o servidor emitir confirmação diferente.

Teste extra de revogação TLS-origem (fixture somente) foi acrescentado a
tests/unit/test_sentra_cos_mcpb_oauth.py. A seleção integral de 16 módulos
descrita acima foi REPETIDA após esses ajustes com o veredito autoritativo:
**47 passed, 1 skipped, 0 failed; 18.72s; exit 0**.
Python compileall -q de 9 módulos: exit 0; git diff --check: exit 0,
somente avisos de newline em arquivos de outras frentes.
Este resultado SUPERA o checkpoint intermediário 46/1 da seção anterior.

Permanece sem prova OAuth externo ou revogação de provedor remoto real.
Para revogação host-only usar:
  https = PinnedOAuthHTTPS(approved_token_url,
                           revoke_url=approved_revoke_url)
  vault.revoke_remote(owner,workspace,server_id,
                      send=https.revoke,approved=True)
A aprovação deve ser host-only e escopada ao provedor/owner, não um
booleano arbitrário vindo do modelo. Nenhuma credencial real foi aberta.


---

# RODADA 4 — CHAT 1 — entrega integrada e provas (10/10/2026)

Plano consultado: docs/SENTRA_COS_RODADA_4_2026-10-10.md e
docs/SENTRA_COS_SETE_FRENTES_2026-10-10.md, seção CHAT 1.
Checkout compartilhado Windows, Desktop Commander OGrandeOxta.
Preservados arquivos dos Chats 2-6 e do coordenador. Sem git
reset/checkout/stash/clean/commit/push, sem cookies, credenciais reais,
conta ChatGPT/DOM como identidade, ou replay de envio Web UNCERTAIN.

## Arquivos criados nesta rodada
- sentra_mcp/services/mcpb_oauth_callback.py
- tests/unit/test_sentra_cos_mcpb_oauth_callback.py
- tests/unit/test_sentra_cos_mcpb_session_actions.py
- tests/unit/test_sentra_cos_mcpb_offline_docker.py
- tests/unit/test_sentra_cos_mcpb_worker_restart.py
- tests/unit/test_sentra_cos_mcpb_purge.py

## Arquivos próprios alterados nesta rodada
- sentra_interop/mcp_http.py (GET SSE/Last-Event-ID e DELETE por grant)
- sentra_mcp/services/mcpb_http.py (migração/estado/Operation sessão)
- sentra_mcp/services/mcpb_offline.py (Docker efetivo, gate/ownership)
- sentra_mcp/services/plugin_host.py (restart físico + nova Operation)
- sentra_mcp/services/plugin_bundles.py (purge físico do payload)
- tests/unit/test_sentra_cos_mcpb_streamable.py (migração schema)
- tests/unit/test_sentra_cos_mcpb_session_actions.py (crash recovery)
- este relatório.

NÃO EDITADOS: sentra_mcp/services/mcpb_sandbox.py,
sentra_mcp/services/control_plane.py, sentra_mcp/server.py,
sentra_canvas/*, native_bridge/*, edge_extension/*,
sentra_runtime/*, arquivos reservados de outros chats.

## 1. OAuth receiver loopback com consentimento host

OAuthLoopbackReceiver usa ThreadingHTTPServer REAL em IPv4
127.0.0.1, porta/path do redirect URI PKCE aprovado. Exige
owner,workspace,server_id,host_session,consent_ref e
verify_host_consent callable fornecido pela autoridade host,
revalidado no começo e no callback. Não aceita boolean de
request do modelo como consentimento. Valida IP client,
Host exato, path, state/code únicos com bounds, ausência
de cookies/Origin/Referer, Sec-Fetch-Mode navigate se presente,
one-use state e sem retry. Código/token jamais na resposta,
status, logger ou objeto público do receiver. Cabeçalhos
no-store, CSP default-src none e referrer-policy. Host deve
chamar close em sucesso, erro, timeout/logout; a PKCE state
expira em 300 segundos.

PROVA: teste GET HTTP TCP real em 127.0.0.1, retorno 200
para sessão legítima; Cookie/Host/Origin/Referer inválidos 403;
host session revogada bloqueia; state replay 403; código
não retornou no HTTP, token de fixture persistiu somente via
DPAPI ciphertext no SQLite. Não usado OAuth externo real.

## 2. Streamable HTTP GET e DELETE com Operation durável

LoopbackMCPHttpClient recebeu:
- events_authorized(request,session_id,last_event_id=None)
- delete_authorized(request,session_id)

GET envia Mcp-Session-Id e Last-Event-ID sanitizado, processa
até 16 eventos e 262144 bytes, somente JSON-RPC notifications/*.
DELETE exige grant mcp:session-delete, HTTP 200/202/204 sem corpo.
O token OAuth é callback host-only. Sem SSRF, DNS, redirect,
proxy, cookies, nem resend de RPC uncertain.

MCPHttpRegistry.session_action exige source_operation_id
real SUCCEEDED, Run/WorkItem/assignee/owner, sessão e cursor
armazenados no SQLite (nunca informados pelo modelo).
Usa nova OperationRequest e CentralInteropAdapter.protocol_gate,
gate.execute com recheck/grant/physical context.
GET requer mcp:events; DELETE mcp:session-delete.
Migração SQLite cria event_cursor, observation_state,
deletion_state. READING/DELETING são persistidos ANTES do
efeito; OBSERVED/DELETED somente após recibo. GET após
DELETE concorrente é bloqueado em WHERE do UPDATE. Em falha,
estados UNCERTAIN, sem retry. reconcile_abandoned também
reconcilia leituras/exclusões stale UNCERTAIN, sem POST.

PROVA: servidor MCP TCP real, initialize, initialized,
tools/list, tools/call, GET cursor_1 e GET Last-Event-ID
cursor_1 => cursor_2, DELETE único por ID; todos
vinculados a Run/WorkItem/Grant reais. Falta grant =>
zero GET/DELETE. Outro owner negado, replay de DELETE negado,
operations SQLite SUCCEEDED. Crash fixture GET/DELETE
READING/DELETING fica UNCERTAIN sem retransmissão.

## 3. Execução REAL de dependências offline no Docker

verify_offline_dependencies_in_docker(control, ...) primeiro
executa preflight de archive/lock/SHA e exige WorkItem RUNNING,
owner/agent/grant mcp:deps-install. Dentro de gate.execute
durável com physical_context:
1. revalida pacote imutável e wheel hash;
2. MCPBDockerOwnership.prepare grava nome/nonce/labels e
   Operation/Run/WorkItem/owner/image ID pinado em SQLite;
3. docker create real (network none, read-only, cap-drop ALL,
   no-new-privileges, UID unprivileged, limites CPU/RAM/PID,
   tmpfs descartável, pacote read-only);
4. docker inspect e ledger.bind de ID exato ANTES de start;
5. docker start -a importa o wheel Python pure dentro do
   contêiner e comprova output, exitCode=0;
6. docker rm somente pelo ID já vinculado, inspeção de ausência
   e ledger.mark_cleaned. Falha deixa claim para reconcile,
   não remove por prefixo/PID nem reinicia efeito incerto.
Sandbox usa imagem SHA256 e Docker CLI pinados pelo host.

PROVA FÍSICA: Docker daemon Linux e imagem local
oma-sandbox:local, wheel demo criado em .mcpb fixture
e extraído/importado efetivamente dentro do contêiner isolado,
network none. Sem grant não há Operation nem container.
Operation SUCCEEDED em SQLite e CLEANED com Docker ID real.
Replay idem não recria container. Somente container
temporário pertencente ao próprio teste foi removido.

LIMITE: este é teste/importação em container descartável,
não instalação persistida dentro do processo MCPB final.
Coordenador deve incorporar o mesmo fluxo a mcpb_sandbox.py
sob o gate físico de tool, não executar pip no host.

## 4. Restart físico de worker real, novo grant/approval

PluginWorkerHost.restart_authorized(control, ...) aceita SOMENTE
ProcessService real, worker anterior FAILED com governance
DISABLED, mesma Run/WorkItem/owner/assignee e sessão anterior
fisicamente ausente/terminada. Demanda grant plugin:restart,
nova OperationRequest/idempotency_key, approval_ref e
verify_host_consent callback host-only. ProcessService reinicia
em mode=sandbox obrigatório com idempotency_key NOVA, handshake
de schema verificado, worker_id/session_id distintos.
Não mata PID de terceiros, não reaproveita processo vivo.
PluginWorkerHost.start recebeu argumento opcional
process_idempotency_key sem quebrar chamada legada.

PROVA FÍSICA: processo worker JSON-RPC real no Docker,
handshake; ProcessService encerrou somente sessão fixture,
reconcile_worker marcou FAILED/DISABLED; sem grant/sem
consentimento há negação; com ambos, nova Operation SUCCEEDED,
worker READY/HEALTHY e novo session_id. Worker novo parado
por host.stop e cleanup de processos deste próprio teste.
Sem auto-restart silencioso e sem grants criados.

## 5. Purge físico confinado dos bytes MCPB extraídos

MCPBBundleCatalog.purge_uninstalled_extracted(owner,workspace,
sha,control,approved=True) exige tombstone REMOVED de TODOS
os owners/workspaces para aquele SHA, nenhuma outra staging
registration, nenhum plugin worker não STOPPED, nenhum claim
Docker pendente. Confere archive SHA e recusa symlinks/junctions
ou root fora de plugin-bundles. Rename atômico para quarantine
aleatória no mesmo diretório e remoção física apenas dos
arquivos extraídos. Archive .archives/<sha>.mcpb é RETIDO
para prova forense e operações duráveis. Não cria grants.
Idempotente para payload já removido.

PROVA FÍSICA tmp_path: diretório SHA foi efetivamente removido;
tombstone impede register; archive imutável preservado.
Outro owner staged e claim Docker PREPARED negam purge até
liberação correta. Não tocou arquivo de outros agentes.
NÃO equivale a purge integral do archive/supressão de recibos.

## Regressão FINAL da rodada, execução real OGrandeOxta

Comando executado em PowerShell no checkout:
$specs = @(Get-ChildItem tests/unit -Filter
  'test_sentra_cos_mcpb_*.py' | Select-Object -ExpandProperty FullName)
$specs += @('tests/unit/test_sentra_cos_skill_library.py',
  'tests/unit/test_sentra_cos_skill_workitem_revision.py',
  'tests/unit/test_sentra_cos_tool_exposure.py',
  'tests/unit/test_sentra_cos_plugin_namespace.py',
  'tests/unit/test_sentra_cos_central_mcp_http_facade.py',
  'tests/unit/test_plugin_host.py')
python -B -m pytest @specs -q --tb=short

RESULTADO: 62 PASSED, 1 SKIPPED, 0 FAILED, 50.85s, exit 0.
Skip único: symlink Windows exige privilégio.
python -B -m compileall -q de 8 módulos alterados: exit 0.
git diff --check: exit 0, apenas warnings de CRLF/LF
nos outros arquivos do checkout. Node: não executado,
não necessário para esta frente Python/HTTP/Docker.
Não confundir com suíte integral SENTRA/conta Web.

## HANDOFF EXATO à coordenadora (sem tocar fachadas)

OAuth:
from sentra_mcp.services.mcpb_oauth_callback import OAuthLoopbackReceiver
receiver = OAuthLoopbackReceiver(
  pkce, owner=owner, workspace=ws, server_id=sid,
  host_session=verified_host_session,
  consent_ref=single_use_human_approval_ticket,
  verify_host_consent=owner_auth_approval_revalidator,
  exchange=pinned_oauth_https.exchange_code)
authorization = receiver.start()
# Abrir authorization["authorization_url"] por ação DO USUÁRIO.
# Validar receiver.status() e sempre receiver.close().
# approve callable DEVE consultar owner bearer+CSRF/session real,
# nunca lambda True em produção ou booleans de JSON do modelo.

MCP GET/DELETE:
registry = MCPHttpRegistry(control)
registry.register(owner,ws,sid,loopback_endpoint,
  approved=True,streamable=True)
out = await registry.session_action(
  owner=owner,workspace=ws,server_id=sid,
  run_id=run_id,work_item_id=wi,agent_id=agent_id,
  source_operation_id=successful_tool_op_id,
  operation_id=new_op_id,idempotency_key=new_idem,
  action="events",access_token=host_only_vault_callback)
# DELETE é OUTRA Operation nova com action="delete".
# Os grants de WorkItem são mcp:events e mcp:session-delete.
# O browser não pode passar session_id/Last-Event-ID/secret.
registry.reconcile_abandoned(owner,ws,min_age_seconds=60)

Offline Docker:
from sentra_mcp.services.mcpb_offline import verify_offline_dependencies_in_docker
result = await verify_offline_dependencies_in_docker(
  control,owner=owner,workspace=ws,package_sha256=sha,
  run_id=run_id,work_item_id=wi,agent_id=agent_id,
  operation_id=op_id,idempotency_key=idem)
# GRANT mcp:deps-install e imagem local SHA256 requerida.
# Coordenadora deve inserir mesma sequência de wheeled deps no
# MESMO contêiner do tool call em mcpb_sandbox.py, incluindo
# ledger.prepare -> Docker name/labels -> inspect/bind ANTES start ->
# rm por ID exato e ausência comprovada. Sem GC por PID/prefixo.

Worker:
outcome = await plugin_host.restart_authorized(
  control,owner=owner,workspace=ws,run_id=run_id,
  work_item_id=wi,agent_id=agent_id,
  failed_worker_id=old_id,operation_id=new_op,
  idempotency_key=new_idem,approval_ref=host_ticket,
  verify_host_consent=owner_scoped_consent_revalidator)
# GRANT plugin:restart, ProcessService sandbox e aprovação real.
# Nunca expor PluginWorkerHost.start direto ao modelo.

Uninstall parcial físico:
catalog.uninstall(owner,ws,sha,control.governance,approved=True)
receipt = catalog.purge_uninstalled_extracted(
  owner,ws,sha,control,approved=True)
# approved=True SOMENTE após decisão host owner autenticado,
# jamais mero boolean de input de agente/LLM.

## Bloqueios e riscos de homologação

OAuth externo e refresh de conta ChatGPT real NÃO testados.
Receiver ainda depende de host UI bearer/CSRF e callback de consent.
GET SSE é finito/bounded, não assinatura contínua/replay remoto.
Offine Docker real foi contêiner de verificação, não MCP worker
de produção; conexão ao mcpb_sandbox.py é do coordenador.
Worker restart físico exige nova autorização humana; política
de restart automático e crash do host real continuam fora da prova.
Uninstall elimina payload extraído, NÃO archive auditado.
Rollback entre governance e catalog SQLite ainda não atômico.
Sem prova de ferramenta publicada/refrescada na conta ChatGPT,
modelo/effort/plano, Setup/MSI, CI ou E2E navegador.

STATUS: código real, provas herméticas e físicas validadas,
handoff documentado. NÃO HOMOLOGADO COMO PRODUTO COMPLETO.


---

# Continuação + auditoria de entregas — 10/10/2026

## Auditoria dos sete fluxos, sem alterar outros agentes

Inspecionados no OGrandeOxta os relatórios físicos dos seis agentes,
os planos de sete frentes e rodada 4, o status Git e os processos.
Cada um dos Chats 1–6 possui relatório entregue. O coordenador mantém
a integração central. Checkpoints reportados (NÃO somar como suíte
conjunta): Chat 1 62 passed/1 skipped antes desta fatia; Chat 2
90 passed; Chat 3 possui provas HTTP/Node/SQLite V2 sem conta
ChatGPT real; Chat 4 17 Python + 1 Node, Code Mode desabilitado;
Chat 5 18 Python/1 skipped + 6 Chromium + 6 Node, PDF visual GET
central pendente; Chat 6 102 Python, Electron e lint CI, mas sem
Setup/MSI assinado/homologado. Permanecem pendentes no coordenador
o relay autenticado, pdf_visual, integração física MCPB, gates,
conta Web real e release. Processos Python/Node/Codex estão ativos;
PID por si só não comprova a qual chat pertencem. Este agente não
reenviou mensagens nem interrompeu sessões. Não há prova de
status de geração de cada aba Edge; relato reflete os documentos
do checkout, não leitura direta dos seis chats.

## Fatia implementada de recovery Docker: execução física real

Alterados/criados EXCLUSIVAMENTE Chat 1:
- sentra_mcp/services/mcpb_orphans.py
- tests/unit/test_sentra_cos_mcpb_orphan_cleanup_real.py
- este relatório.

Nova API assíncrona:
  await MCPBDockerOwnership(control).reconcile_stopped_owned(
      owner=owner, workspace=workspace,
      source_operation_id=source_operation_id,
      work_item_id=work_item_id, agent_id=agent_id,
      cleanup_operation_id=fresh_operation_id,
      idempotency_key=fresh_idempotency_key,
      approved_by_host=owner_scoped_human_approval_callback,
      min_age_seconds=60)

Ela exige MESMO ControlPlaneService, Run/WorkItem/Operation central,
source Operation terminal, assignee correto, claim Docker BOUND,
imagem pinada SHA256, nome e labels imutáveis, ID físico exato,
idade mínima, consentimento humano revalidado e grant separado
mcp:container-cleanup no WorkItem. Usa CentralInteropAdapter,
OperationRequest, gate.execute e checkpoint físico; inspeciona
duas vezes o Docker sem executar efeito quando container está
Running. Antes do docker rm realiza CAS SQLite BOUND -> CLEANING:
duas Operations diferentes não conseguem remover a mesma
instância. REMOVE SOMENTE container ID completo de 64 hex, SEM
--force. Confirma daemon Linux saudável e resposta Docker
específica no such object: <ID> antes de registrar CLEANED.
Se daemon/recibo ficar incerto, mantém estado CLEANING e
Operation UNCERTAIN, SEM retry de efeito. Replay da mesma
Operation SUCCEEDED retorna recibo anterior sem novo docker rm.

Prova física: teste criou um container NOVO parado, com labels
de claim e imagem local hash pinned; SQLite Run/WorkItem/Operation
reais. Deny sem grant e deny sem aprovação preservaram container;
após grant e aprovação, foi removido SOMENTE aquele ID, o
ledger ficou CLEANED, Operation SUCCEEDED. Replay duplicate,
sem efeito adicional. Cleanup finally confere image/name/labels
antes de remover qualquer resto do contêiner do próprio teste.
Teste anterior de negação de ownership falso também passou.
Primeira execução detectou incompatibilidade de replay:
corrigida. Segunda detectou diferença lowercase na mensagem
Docker de ausência: corrigida. Nenhum container de outro agente
foi interrompido.

## Handoff exato: integração NO mcpb_sandbox.py reservado

A coordenadora deve trocar o cleanup por nome/prefixo no
mcpb_sandbox.py por sequência física autoritativa:
1. Criar ledger.prepare ANTES de docker create, registrando
   Run/WorkItem/Operation, imagem SHA e labels únicas.
2. Passar nome e labels do claim no Docker create; inspecionar
   ID+imagem+nome+labels e ledger.bind antes do start.
3. Concluir/reconciliar source Operation SEM retry de efeito.
4. Criar nova OperationRequest com capability
   mcp:container-cleanup, grant work_item e approval do
   owner autenticado; então chamar reconcile_stopped_owned.
5. Se Docker mostrar Running, NÃO usar rm --force, PID ou
   prefixo; política de terminação é outro fluxo separado.
6. Se cleanup ficar CLEANING/UNCERTAIN, conciliar recibos
   físicos independente do host, sem retransmissão insegura.

A função approved_by_host é callback exclusivo do host,
NUNCA booleano de JSON, prompt, DOM ou agente. Tests usam
lambda fixture e não provam aprovação remota. Este agente
não editou mcpb_sandbox.py, ControlPlane, Canvas, relay,
edge_extension ou arquivos de outros agentes.

## Regressão comprovada desta continuação

Executado no mesmo checkout Windows:
$specs = @(Get-ChildItem tests/unit -Filter
  'test_sentra_cos_mcpb_*.py' | Select-Object -ExpandProperty FullName)
$specs += @('tests/unit/test_sentra_cos_skill_library.py',
 'tests/unit/test_sentra_cos_skill_workitem_revision.py',
 'tests/unit/test_sentra_cos_tool_exposure.py',
 'tests/unit/test_sentra_cos_plugin_namespace.py',
 'tests/unit/test_sentra_cos_central_mcp_http_facade.py',
 'tests/unit/test_plugin_host.py')
python -B -m pytest @specs -q --tb=short
Resultado FINAL: 63 passed, 1 skipped, 0 failed, 36.33s,
exit 0. Skip por permissão Windows de symlink em teste legado.
Compileall de mcpb_orphans.py exit 0; git diff --check do
arquivo alterado exit 0.

Sem Node nesta fatia Python/Docker. Não houve E2E ChatGPT
Web real, nem assinatura MSI/Setup, nem homologação geral.
Não foi executado reset/checkout/stash/clean/commit/push global.


## Crash recovery adicional — verificação sem replay físico

O arquivo próprio mcpb_orphans.py recebeu a API:

  await MCPBDockerOwnership(control).confirm_uncertain_absence(
      owner=owner, workspace=workspace,
      source_operation_id=source_op_id,
      work_item_id=work_item_id, agent_id=assigned_agent,
      verification_operation_id=fresh_operation_id,
      idempotency_key=fresh_idempotency,
      approved_by_host=owner_scoped_operator_reapproval)

Objetivo: recuperar queda do host ENTRE um docker rm já confirmado
fisicamente e a gravação do estado CLEANED no SQLite. Exige fonte
em estado CLEANING, source Operation terminal, mesmo Run/WorkItem,
owner e agente, grant mcp:container-cleanup, consentimento do
host, operação adicional durável e physical checkpoint.
Executa apenas comandos read-only Docker info/inspect,
valida daemon Linux e erro textual específico
no such object: <container_id> com ID exato.
Somente depois marca CLEANED. NÃO executa docker rm, stop,
kill, retry, nem aceita status apenas por PID/prefixo.
O mesmo verification Operation idempotente duplica o recibo
sem nova inspeção/efeito. Estado CLEANED com uma Operation nova
não autoriza alteração de outros recursos.

Teste físico ampliado:
tests/unit/test_sentra_cos_mcpb_orphan_cleanup_real.py
simulou crash por retorno do registro a CLEANING APÓS o
docker rm já executado pela própria fixture; confirmação
sem aprovação foi negada; confirmação com grant/approval
provou ausência física, marcou CLEANED, contagem
docker_remove_calls=0; replay da mesma verificação não
reexecutou. Junto ao teste anterior de ownership:
2 passed, 0 failed, 3.82s.

O patch recomendado ao coordenador deve chamar
confirm_uncertain_absence SOMENTE para ledger CLEANING com
source Operation terminal e aprovação owner autenticado.
Se a inspeção mostrar contêiner ainda presente, daemon
indisponível ou erro diverso do ID inexistente, FAIL CLOSED:
não presumir ausência nem retransmitir docker rm.

Ainda não provado: crash/reboot físico do host no milissegundo
de rm, terminação com container Running, ligação direta
mcpb_sandbox.py (reservado ao coordenador). Não homologar
produto inteiro com esta prova de laboratório.


## Verificação cruzada independente após recuperação de orphan

Após implementar e testar confirm_uncertain_absence, executei
seleção direcionada inter-frentes, somente testes e fixtures:
- Chat 1: orphan_cleanup_real, session_actions, oauth_callback;
- Chat 2: chat2_http_v2, chat2_receipt_v2_pipeline;
- Chat 3: web_v2_transport, web_v2_http_ingress;
- Chat 4: executors_cos_consented_stdin, code_mode_admission;
- Chat 5: canvas_ux_browser (Chromium headless efêmero);
- Chat 6: release_migration_round4, install_doctor_round4;
- coordenador: central_mcp_http_facade.

Comando: python -B -m pytest -q -p no:cacheprovider
[os 13 módulos acima] --tb=short.
Resultado real: **59 PASSED, 0 FAILED, 49.70s, exit 0**.
Esta amostra prova compatibilidade local atual de contratos entre
as seis frentes e a fachada, NÃO substitui 100% da suíte global,
não equivale a seis chats vivos/terminados e NÃO atesta
conta ChatGPT/Plus, autorização remota, installer assinado,
Code Mode habilitado nem E2E Web/Setup. Não somar esses 59
aos 63/1 da regressão Chat 1, pois os módulos se sobrepõem.
Não alterei arquivos dos demais agentes após esta checagem.


---

# R6 Fechamento CHAT 1: MCPB / Skills sob UM WorkItem (10/10/2026)

## Plano e fronteiras

Lida seção Agente 1 do
docs/SENTRA_COS_RODADA_6_FECHAMENTO_E_HOMOLOGACAO_2026-10-10.md.
Mesmo checkout físico OGrandeOxta e SQLiteControlPlaneStore do
ControlPlaneService, sem banco autoritativo novo. Código e testes
novos limitados a sentra_mcp/services/plugin_bundles.py e
tests/unit/test_sentra_cos_mcpb_round6_lifecycle.py; documentação
somente neste relatório. NÃO editados mcpb_sandbox.py,
control_plane.py, server.py, sentra_canvas/*, edge_extension/*,
native_bridge/* ou arquivos de Chats 2-6. Nenhum reset,
stash, checkout, clean, commit, push, deploy ou instalação real.

## Nova API importável e o que ela de fato conecta

MCPBWorkItemLifecycle(control, owner, workspace, package_sha256,
  run_id, work_item_id, agent_id)

A construção exige Run ativo, WorkItem RUNNING, assignee válido,
workspace canônico idêntico ao Run central, agente vinculado ao
Run, pacote Stage revisado e registro compatível. Cada método
revalida essas identidades, manifest SHA/inventário imutável,
registro não desabilitado e grant WorkItem de capacidade exata.
Identidade estável da sessão:
server_id = "mcpb-" + package_sha256[:32].
Não gera Run/WorkItem/grant/Token alternativos, nem faz deploy
de schema a conta ChatGPT.

Métodos host-only:
- inspect(): visão stage/registration/Run/WorkItem/assignee,
  sem segredo e sem afirmar conta externa verificada;
- oauth_callback(broker, host_session, consent_ref,
  verify_host_consent, exchange): valida mesmo SQLite vault,
  grant mcp:oauth, injeta wrapper host owner+Run+WorkItem,
  revalida grant/sessão durante callback real. O browser
  recebe só authorization_url, nunca verifier/token.
  O HOST inicia e encerra OAuthLoopbackReceiver;
- call_http_tool(registry, vault, name, arguments,
  operation_id, idempotency_key): exige grant mcp:<tool>,
  mesma instância central e SQLite, endpoint Streamable
  autenticado, bearer retornado APENAS por callback host-only;
  registry.execute valida ainda grants separados mcp:http-connect
  e mcp:list, e materializa Operation durável;
- session_action(registry, vault, source_operation_id,
  operation_id, idempotency_key, action="events"|"delete"):
  exige mcp:events ou mcp:session-delete, sessão vinculada
  à Operation anterior SUCCEEDED e bearer no GET/DELETE,
  Last-Event-ID vindo de SQLite, não de JSON/agente;
- install_offline_in_owned_docker(operation_id,idempotency_key):
  exige mcp:deps-install e reusa verificação do archive/lock/wheel
  + gate.execute + Docker real network none + claim/inspect/
  bind/cleanup ID no mesmo WorkItem/Run;
- publish_verified_tool(source_operation_id,tool_name,descriptor,
  approval_ref,verify_host_approval): somente após Operação
  central SUCCEEDED com recibo MCP HTTP COMPLETED e mesmo
  agent/workitem. Requer mcp:publish-schema + aprovação
  host-owner revalidável; publica somente snapshot ACL LOCAL do
  tool_name observado. Não cria grants, não afirma existência
  de ferramenta na conta ChatGPT externa nem transmite schemas;
- oauth_effect(vault,action="refresh"|"revoke",operation_id,
  idempotency_key,approval_ref,verify_host_approval,exchange/revoke):
  exige grant mcp:oauth-refresh OU mcp:oauth-revoke e aprovação
  humana do host (callbacks não podem vir de request Web/LLM).
  Usa CentralInteropAdapter.protocol_gate / OperationRequest /
  gate.execute e checkpoints físicos; a vault DPAPI salva
  REFRESHING ou REVOKING no SQLite ANTES da chamada single-shot.
  Em refresh ambíguo, credencial passa a UNCERTAIN, sem retry;
  revogação remota remove ciphertext local antes da chamada,
  reporta remote_confirmed verdadeiro ou falso, sem reenvio.
  Nenhum token real/conta ChatGPT usado nos testes;
- retire(registry,vault,approval_ref,verify_host_approval,
  uninstall=False,purge=False): exige mcp:manage e consentimento
  do host. Confere mesmíssima central/store de todos serviços;
  esconde schema primeiro, revoga registro MCP HTTP, revoga
  bearer local se ainda ACTIVE, usa facade real
  ControlPlaneService.bundle_disable e seu audit, opcionalmente
  tombstone uninstall e purge de diretório extraído após prova
  global de ausência de worker/container. Preserva archive
  auditado e status REVOKED/REVOKED_UNCONFIRMED preexistente,
  não presume revogação OAuth remota. O resultado declara
  remote_schema_published=False.

Capacidades distintas a conceder APENAS pelo Control Plane:
mcp:launch, mcp:oauth, mcp:oauth-refresh, mcp:oauth-revoke,
mcp:http-connect, mcp:list, mcp:<observed-tool>, mcp:events,
mcp:session-delete, mcp:deps-install, mcp:publish-schema,
mcp:manage. Não permitir wildcard implícito ou owner_auth do LLM.

## Testes e provas físicas da R6

Arquivo novo tests/unit/test_sentra_cos_mcpb_round6_lifecycle.py
cobre:
1. Um ÚNICO control/Run/WorkItem/agent/sha do começo ao fim;
   stage, inspect/manifest/registro real e launch spec negado
   sem grant, depois admitido SEM iniciar processo.
2. Callback PKCE GET/loopback TCP real e vault DPAPI real no
   mesmo SQLite. Verifier/state one-use, credential ciphertext
   não aparece em plugin_bundle, nenhum segredo real.
3. MCP Streamable HTTP local real POST initialize,
   initialized, tools/list, tools/call, GET SSE e DELETE sob
   grants/Operation distintas. Falta mcp:echo nega antes do
   envio; GET e DELETE usam MESMO bearer DPAPI em
   Authorization do servidor local. Nenhum redirect/proxy.
4. Schema ACL local permitido apenas após receipt SUCCEEDED
   MCP HTTP no mesmo WorkItem e approval host; sem approval
   falha, nenhum grant ou alegação de conta externa criada.
5. Wheel offline SHA/lock em contêiner Docker Linux REAL,
   network none, imagem SHA256 pinada, import demo efetivo,
   ledger Run/WorkItem/Operation ID idênticos e CLEANED,
   ausência de replay ao repetir idempotency key.
6. Disable/uninstall/purge físico confinado após autorização
   host, revogação do bearer e endpoint, schema oculto e
   archive forense mantido. Tool posterior negado.
7. Negação de owner, agente ou workspace incorreto;
   falta de grant, aprovação inválida, fonte de vault/registry
   não central e schema sem receipt central negados.
8. Refresh e revogação remota ONE-SHOT (callbacks fake
   revisados de teste, não provedores reais) ligados ao mesmo
   WorkItem e novas Operations; zero reenvio em replay;
   refresh ambíguo é UNCERTAIN na Operation E vault
   após falha. DPAPI/local token não exposto.

A primeira bateria encontrou incompatibilidade na fixture de
subclasse HTTP (corrigida), e a finalização exigia inicializar
a tabela autoritativa plugin_workers via PluginWorkerHost real;
corrigida a PREPARAÇÃO da fixture, não afrouxado purge. Outro
teste identificou capability mcp:oauth-refresh não declarada
no WorkItem (corrigida na lista requerida, não no gate).
Todos esses erros foram resolvidos antes da regressão final.

## Handoff exato à coordenadora (mcpb_sandbox.py RESERVADO)

O host coordenador poderá instanciar MCPBWorkItemLifecycle com
os mesmos IDs existentes do ControlPlaneService. Reaproveitar
control.bundle_stage / bundle_register / bundle_activation_plan
na UI owner autenticada; não expor construtor a modelo/browser.

OAuth:
  binding = MCPBWorkItemLifecycle(
      control, owner=owner, workspace=ws, package_sha256=sha,
      run_id=run_id, work_item_id=work_item_id, agent_id=agent_id)
  receiver = binding.oauth_callback(
      approved_pkce_broker, host_session=owner_session,
      consent_ref=single_use_approval_ticket,
      verify_host_consent=host_auth_ticket_revalidator,
      exchange=pinned_HTTPS_token_exchange)
  receiver.start()
  # navegador abre apenas URL, receiver.close() em todos os caminhos
  # sem cookie, e-mail, senha ou callback aprovado pelo modelo.

MCP HTTP:
  registry.register(owner,ws,binding.server_id,
    reviewed_literal_loopback_endpoint,approved=True,streamable=True)
  outcome = await binding.call_http_tool(
    registry, vault, name=reviewed_name, arguments=reviewed_arguments,
    operation_id=new_op, idempotency_key=new_idem)
  events = await binding.session_action(registry,vault,
    source_operation_id=new_op,operation_id=events_op,
    idempotency_key=events_idem,action="events")
  deleted = await binding.session_action(registry,vault,
    source_operation_id=new_op,operation_id=delete_op,
    idempotency_key=delete_idem,action="delete")

Schema:
  binding.publish_verified_tool(
    source_operation_id=new_op,tool_name=observed_name,
    descriptor=host_reviewed_schema,
    approval_ref=separate_owner_ticket,
    verify_host_approval=host_consuming_ticket_verifier)
  # PUBLICAÇÃO LOCAL APENAS. ChatGPT externo: somente via
  # handshake verdadeiro, cliente autorizado e consentimento
  # oficial provado. O refresh da lista remota NÃO ocorreu.

OAuth token lifecycle:
  await binding.oauth_effect(vault,action="refresh",operation_id=op,
    idempotency_key=idem,approval_ref=ticket,
    verify_host_approval=host_consuming_ticket_verifier,
    exchange=pinned_https_refresh)
  await binding.oauth_effect(vault,action="revoke",operation_id=op2,
    idempotency_key=idem2,approval_ref=ticket2,
    verify_host_approval=host_consuming_ticket_verifier,
    revoke=pinned_https_remote_revoker)
  # Guard central/vault impede retentativas automáticas UNCERTAIN.

Docker:
  await binding.install_offline_in_owned_docker(
    operation_id=fresh_op,idempotency_key=fresh_idem)
  # Essa prova usa contêiner DESCARTÁVEL de verificação de deps.
  # Coordenador DEVE integrar MESMO wheelhouse ao contêiner
  # MCPB stdio que realmente executa a ferramenta:
  # 1 preflight sha + grant + physical fence
  # 2 MCPBDockerOwnership.prepare antes de docker create
  # 3 aplicar claim name/labels, inspecionar ID e bind
  # 4 extrair wheel em tmpfs e importar ANTES do entrypoint
  # 5 manter network none/read-only/cap drop e limites físicos
  # 6 uso de OperationRequest de tool com novo ID/grant
  # 7 cleanup EXATAMENTE por ID com ledger, nunca por prefixo
  # 8 se UNCERTAIN, apenas confirm_uncertain_absence com
  #   nova Operation/owner ticket e zero reenvio.
  # O código de mcpb_sandbox.py é EXCLUSIVO do coordenador.

Retirada:
  binding.retire(registry,vault,
    approval_ref=host_ticket,
    verify_host_approval=host_consuming_ticket_verifier,
    uninstall=True,purge=True)
  # Somente HOST que prove aprovação humana de uso único.
  # Arquivo forense retido; não afirmar uninstall total.

## Bloqueios que não podem ser declarados homologados

- Nenhuma conta ChatGPT Plus/Web ou cliente remoto foi acessada,
  autorizada ou teve schemas publicados/refrescados.
- OAuth externo TLS real não foi exercitado; apenas HTTP callback
  local e transport callbacks herméticos controlados no teste.
- Worker Docker MCPB *de ferramentas* e wheelhouse no MESMO
  processo/contêiner de execução dependem do patch real em
  mcpb_sandbox.py (coordenador). A prova de wheels usa
  Docker isolado temporário e grant central verdadeiro.
- Restart físico do worker já tem testes reais na Rodada 4,
  mas o pacote MCPB inert REGISTERED não representa um
  supervisor de worker persistente do mesmo WorkItem.
- Ainda faltam policy ticket single-use host autenticado
  (a função verify_host_approval deve VALIDAR E CONSUMIR um
  ticket gerado exclusivamente pelo operador real), QA externo,
  revisão de schema, lease após reboot físico, rollback SQLite
  multi-DB atômico e publicação ChatGPT real.
- Nenhum Setup/MSI ou assinatura foi realizado.
- O status de 34/34 não pode ser homologado por esses testes.


## Rodada 6 — consolidação final verificada

Após o handoff e testes anteriores da R6, reforços:
- GET e DELETE MCP HTTP agora usam bearer do mesmo vault DPAPI
  central, host-only. Teste TCP real confirmou Authorization no
  initialize/notifications/list/call, GET com Last-Event-ID e DELETE.
- OAuth refresh/revoke remoto: Operations reais separadas e grants
  mcp:oauth-refresh / mcp:oauth-revoke, tickets host revalidados.
  Estado do vault é persistido ANTES do efeito. Crash/timeout
  UNCERTAIN nunca provoca replay remoto automático.
- Retire verifica Registry, vault e ControlPlane com mesmíssimo
  SQLite/instância. Usa ControlPlaneService.bundle_disable para
  auditoria; mantém REVOKED/REVOKED_UNCONFIRMED prévios.
- Novo teste de prova negativa: uma Operation SUCCEEDED mas
  pertencente a OUTRO Run/WorkItem/Agent não pode habilitar schema
  da instância atual. Registry de outro ControlPlane não aposenta
  MCPB desta instância. O schema continua SOMENTE LOCAL, jamais
  prova conta ChatGPT externa.
- Execução Docker real do wheel continua no MESMO Run/WorkItem
  que a sessão OAuth e o tool HTTP do teste R6, com ledger do
  container ID + labels, network none e cleanup exato.

Regressão final executada no OGrandeOxta:
  $specs = @(Get-ChildItem tests/unit -Filter 'test_sentra_cos_mcpb_*.py' |
    Select-Object -ExpandProperty FullName)
  $specs += @('tests/unit/test_sentra_cos_skill_library.py',
    'tests/unit/test_sentra_cos_skill_workitem_revision.py',
    'tests/unit/test_sentra_cos_tool_exposure.py',
    'tests/unit/test_sentra_cos_plugin_namespace.py',
    'tests/unit/test_sentra_cos_central_mcp_http_facade.py',
    'tests/unit/test_plugin_host.py')
  python -B -m pytest @specs -q --tb=short

**RESULTADO FINAL R6: 68 passed, 1 skipped, 0 failed,
37.54s, exit 0.** Skip Windows symlink legado sem privilégio.
Python compileall de plugin_bundles.py e novo teste: exit 0.
git diff --check do escopo: exit 0. Não somar contagens
sobrepostas de rounds anteriores.

Handoff importável EXATO:
  from sentra_mcp.services.plugin_bundles import MCPBWorkItemLifecycle
  binding = MCPBWorkItemLifecycle(control, owner=owner, workspace=ws,
      package_sha256=sha, run_id=run_id, work_item_id=wi,
      agent_id=assigned_agent_id)

Usar métodos documentados na seção R6 anterior:
binding.inspect, binding.oauth_callback, binding.call_http_tool,
binding.session_action(registry, vault, ...),
binding.install_offline_in_owned_docker,
binding.publish_verified_tool, await binding.oauth_effect,
binding.retire. Exigir callbacks de consentimento owner-auth
que consomem ticket único por NOVO efeito; uma dúvida de receipt
deve gerar consulta/reconciliação, NUNCA reenvio especulativo.
As credenciais permanecem exclusivamente em DPAPI local.

Pendência central NÃO HOMOLOGADA: o executor wheel real é
container DESCARTÁVEL de verificação, e ainda precisa ser
incorporado ao MESMO container stdio de ferramenta em
mcpb_sandbox.py, sob ownership/gate (arquivo exclusivo do
coordenador). Worker persistente health/restart foi provado na
R4 em caso separado, não integrado ao mesmo MCPB end-to-end
de produção. Nenhum OAuth real de provedor ChatGPT, refresh
de schema na conta externa, cookie, credencial ou token pessoal
foi consultado. Sem Setup/MSI/assinatura/VM; 34/34 não homologado.
