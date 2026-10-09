# SENTRA OS — Integração direta com o centro autoritativo (09/10/2026)

Ambiente: Desktop Commander, OGrandeOxta, C:\Users\vitor\OneDrive\Desktop\SENTRA.
**Estágio: código central integrado + HTTP laboratório validado; broker ativo antigo AINDA não atualizado.**

## Pedido do usuário

Coordenar três agentes originais usando Desktop Commander para integrar os módulos no SENTRA principal e validar a conexão direta ao centro operacional. O controle único continua sendo sentra_mcp.services.control_plane.ControlPlaneService, seu DurableRunService, AuthorizationService/GovernanceService e o Canvas real, não um ledger paralelo.

## As quatro entregas principais desta rodada no coordenador

1. sentra_mcp/services/durable.py: nova API ADITIVA reserve_operation_intent(run_id,owner,operation_id,idempotency_key,intent_sha256,resource_key,kind,ttl_s). Insere em UM BEGIN IMMEDIATE do durable.sqlite3 o Operation state STARTING, fingerprint canônico SHA256, resource_key, fencing_token monotônico, lease e evento MACHINE_INTENT_RESERVED. Migração SQLite antiga preservada. Replay idempotente EXISTING **jamais inicia novo efeito**; colisões legacy sem fingerprint negadas. Política exige Run RUNNING e operação com owner certo. A API anterior create_operation foi preservada (não fornece permissão nova). Lease/fence continuam no ControlStore autoritativo.
2. sentra_runtime/central_authority.py: CentralDurableIntentAuthority sobre o MESMO DurableRunService do ControlPlane, atende DurableOperationGate.reserve_intent/fence_active/record_result e liga estados STARTING->RUNNING->SUCCEEDED/FAILED/UNCERTAIN. Check de fence ativo e armazenamento de digest de evidência em vez de payload potencialmente sensível.
3. sentra_canvas/service.py: Canvas.center_capabilities(ws) e Canvas.center_inspect(ws,work_item_id,operation_id,request_key). A capacidade ÚNICA exposta nesta versão é canvas.workspace.inspect, read-only. Usa Canvas Store + TaskRuntime originais, WorkItem RUNNING com metadata.workspace_id do host, assignee_agent_id, required_capabilities, AuthorizationService/BoundWorkItemPolicy REAL, ExecutorRegistry e DurableOperationGate. Não cria grants, não aceita principal de payload nem executa processos/terminal/browser/WinUIA sem infraestrutura e aprovação.
4. sentra_canvas/__main__.py: GET autenticado /api/center/capabilities?ws=... e POST autenticado /api/center/inspect, exigindo confirm=true. Usa CanvasServer existente em loopback, Origin+Host e bearer DPAPI, sem alterar rotas legadas/nova UI nativa.

## Testes concluídos e evidências

- tests/unit/test_sentra_runtime_central_integration.py: **10/10** testes de ControlPlaneService REAL + SQLite/WAL (grant/WorkItem/fence, operação no ledger principal, replay sem efeito, revogação, intent collision, cross-connection race, stale fence, migração legacy e pause denial).
- tests/unit/test_sentra_runtime_canvas_center_http.py: **3/3** HTTP reais com CanvasServer da aplicação em 127.0.0.1 e estado temporário, sucesso, replay UNCERTAIN, grants revogados, bearer inválido, workspace cruzado negado e confirmação explícita.
- Teste de regressão central com governance e admission anteriores: **25 passed**.
- Suíte tests/unit COMPLETA em andamento; registrar apenas resultado real após terminar.

## Situação do broker Canvas em execução (NÃO reiniciar automaticamente)

Lido com sentra_canvas.broker.read_endpoint(), sem expor token:
- Processo local (broker) PID 27804, porta loopback 60089, origem 08/10/2026.
- 3 workspaces; 2 terminais running; 0 tasks running, 0 agents running.
- A rota nova no processo antigo retornou HTTP **404**, pois o processo não recarrega Python ao atualizar arquivos.
- NÃO matar nem reiniciar o broker: perda provável de sessões ConPTY em uso. Antes de disponibilizar no aplicativo em execução, agendar hot-upgrade/restart quando terminais estiverem parados, ou implementar migração validada de sessões. A instância de laboratório nova é REAL CanvasServer, mas NÃO é o broker atual da conta.

## Orquestração dos outros agentes (mesmos chats)

- EXEC-001 https://chatgpt.com/c/6ac83719-1efc-83ea-b448-0763a864bbbe: ordem inicial de centralização confirmada SENT, código sentra_executors/central_integration.py e testes unit de integração chegaram ao disco. Agent handoff técnico mais novo da API core teve retorno NOT_SENT (não reivindicar entrega). Verificar problema de identidade Machine.owner_principal_id vs owner do DurableOperationGate e remover SQLiteAdmissionTestOnly de demostração central.
- CRIT-002 https://chatgpt.com/c/6ac83727-19b4-83ea-8a85-b2096c9faba5: ordem inicial confirmada SENT, código sentra_interop/central.py e testes integrações chegaram. Handoff posterior de API core retornou NOT_SENT. Precisa trocar diagnostic-only blocked adapter para uso autorizado de CentralDurableIntentAuthority com provider read-only de laboratório.
- CRIT-003 https://chatgpt.com/c/6ac83735-217c-83e9-9364-8ab8860f334b: envio da ordem original e duas tentativas por Edge retornaram NOT_SENT (retry safe). Chat aberto novamente no Edge e read-only collect_chat também não respondeu. NÃO afirmar que recebeu; a equipe talvez permaneça na sprint anterior. Não abrir outro chat, não enviar mensagens com entrega incerta sem reconciliação.
- Só editar módulos dos outros agentes mediante negociação explícita. Coordenador possui sentra_runtime/, sentra_mcp/services/durable.py e APIs host sentra_canvas, seus próprios testes e docs.

## P0 / proteção contra alegações excessivas

- O novo Atomic Machine Intent é REAL SQLite single-node do centro, mas não uma transação distribuída com efeito físico externo. Qualquer driver remoto deve verificar fencing e grant NO PONTO de seu efeito; um teste de browser fixture não prova isso.
- Keycloak/OPA/OpenFGA, Daytona, runsc, WinHCS, OpenHands, Activepieces, Guacamole, ToolHive e Hocuspocus WSS real continuam opcionais e não autenticados/testados contra infra pública real.
- Não confiar em dados de requisição para owner, grant, lease ou principal; nenhum script externo pode conceder permissão.
- A execução local browser read-only dos agentes só pode ser ativada após as correções de contrato e tests end-to-end no mesmo core persistente.
- CI, empacotamento, SBOM real, migração de operações e sessão nativa entre restarts ainda precisam passar gate antes de release.
- Todos os novos diretórios e arquivos seguem UNTRACKED até revisão explícita, sem git reset/clean nem commit global sobre trabalho dos demais.

## Fechamento de validação, mesma sessão

- Suíte integral real: `python -B -m pytest -q -p no:cacheprovider tests/unit --disable-warnings` -> **1718 passed, 7 skipped, 1 warning, exit 0**, 404.66s.
- Node colaboração: `npm test --prefix sentra_collab` -> **54 passed, 0 failed**, exit 0.
- Quatro suites de integração central específica: `test_sentra_executors_central_integration.py`, `test_sentra_interop_central_real.py`, `test_sentra_runtime_central_integration.py` e `test_sentra_runtime_canvas_center_http.py` -> **31 passed**, exit 0.
- A suíte completa começou enquanto arquivos das equipes eram editados. O reteste combinado de 31 casos central confirma as versões no disco após as mudanças principais.
- A extensão Edge entregou a ordem INICIAL central aos chats EXEC-001 e CRIT-002; ainda NÃO entregou as mensagens posteriores de handoff informando a nova API (status NOT_SENT). A CRIT-003 permaneceu inacessível para envio e consulta (status NOT_SENT, retry_safe), inclusive após abrir o mesmo chat no Edge. O agendador foi atualizado para tentar apenas quando estiver acessível. **Não afirmar que os três agentes receberam a nova ordem**.
- Não reiniciamos o Canvas broker atual porque existem 2 terminais ConPTY em execução. O programa instalado/aberto AINDA NÃO tem a rota nova; continua resposta 404 no broker antigo. A rota foi exercitada com CanvasServer real em estado temporário e bearer real criado no teste. Promover atualização do broker somente com janela de manutenção ou suporte a handoff seguro de sessões.

**Próximo gate:** quando a extensão voltar a enviar, instruir EXEC-001 e CRIT-002 a injetar `CentralDurableIntentAuthority(control.durable)` em suas factories e testar read-only real contra ControlPlane (sem SQLiteAdmissionTestOnly como autoridade final). CRIT-003 deve receber a integração Canvas+GraphStore+workspace auth. Após o proprietário liberar reinicialização segura e os dois terminais pararem, reiniciar o broker, repetir teste HTTP na porta do broker real e validar montagem UI. Até lá o deploy ativo permanece PENDENTE.
