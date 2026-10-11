# SENTRA OS — Colaboração entre Canvas, reconciliação e release QA

Base local: main e4b3968; código adicional desta sessão ainda não incorporado a commit de release. O proprietário deseja dois SENTRA Canvas cooperando via VPN Hamachi ou Radmin, com agentes, notas, tarefas, contexto autorizado, trabalho próprio e recibos persistentes — **não** somente remote desktop e presença.

## Fluxo pretendido de colaboração real

1. Em cada computador, o proprietário seleciona um workspace e uma rede VPN existente (Hamachi/Radmin), identifica seus IPs e confirma peers explícitos. Um segredo de pareamento/identidades criptográficas pertencem ao host, nunca ao agente nem ao texto de uma nota.
2. O host A prepara uma oferta vinculada a um WorkItem RUNNING e a um grant atual `peer.task.offer`; autentica, criptografa e envia uma referência idempotente. Um ACK não significa que a tarefa foi executada.
3. O host B verifica identidade Ed25519, criptografia AEAD, workspace, TTL, nonce/replay e registra a oferta como PENDING_LOCAL_ADMISSION.
4. O proprietário do host B mapeia a referência remota a um WorkItem **LOCAL** com escopo, assignee, objetivo, peer explícito e grant independente `peer.task.accept`. Só o Control Plane de B pode reservar Operation/lease/fence, sem aceitar autoridade do host A.
5. Receber ou admitir a referência NÃO inicia código, modelo, shell, navegador ou execução remota. A futura execução exige capability de efeito apropriada, sandbox e fencing no ponto de efeito, com no-repeat/reconciliação.
6. O resultado real precisa de receipt verificado pelo Control Plane de B, referência de artefato, persistência e transmissão autenticada de volta a A, e reconciliação de estado independente no lado A. Isso ainda está PENDENTE.

## Código implementado nesta frente

- `sentra_canvas/peer_work_wire.py`: TCP loopback autenticado com chave de mesh, Ed25519 e AES-GCM, envelope estrito e SQLite inbox/outbox; ACKs autenticados não convertem recebimento em sucesso; `prepare_authorized_offer` verifica grant do host A.
- **NOVO** `sentra_canvas/peer_admission.py`: `admit_pending_offer` vincula inbox validado a WorkItem RUNNING e grant local com `remote_peer_id`, `remote_subject_id` explícitos; cria `Operation` durável no `DurableRunService` real via `CentralDurableIntentAuthority` e `DurableOperationGate`; marca inbox ADMITTED_LOCAL_NO_EFFECT. Não executa trabalho e não autocria grants.
- `tests/unit/test_canvas_peer_admission.py`: 5 testes aprovados, cobrindo host real/SQLite, grant ausente, submissão somente leitura, replay fail-closed, identidade remota incorreta, outro workspace e spoof.
- `tests/unit/test_canvas_peer_work_wire.py`: 14 testes anteriormente aprovados, incluindo dois sockets reais e leases/ack persistentes.
- Os testes estão num único Windows, com hosts de laboratório; **não** constituem validação de rede VPN multi-PC, de mTLS, sincronização de anotações ou execução remota.

## Providers / reconciliação

- Verificação seletiva ACP/A2A/MCP/OpenHands/Activepieces: inicialmente 40 passed, 1 skipped e 1 failed.
- Falha reproduzida: Activepieces POST com resposta perdida ficava corretamente UNCERTAIN, mas um `activepieces:observe` posterior sofria DuplicateOperation porque usava o lease de efeitos físicos.
- **Corrigido** em `sentra_runtime/observations.py`: `pieces` e `activepieces` classificam somente `activepieces:observe`, `activepieces:artifact`, `activepieces:catalog`, `activepieces:trigger_reconcile` como observações. `action`, `cancel`, `trigger_ingest` etc. continuam efeitos físicos.
- Testes da reconciliação que falhavam agora passaram; `tests/unit/test_sentra_runtime_observations_activepieces.py` adiciona negativos contra spoof em `arguments.action`.
- Não há evidência de daemons SaaS nem de serviços reais Activepieces, A2A, OpenHands, ToolHive ou ACP Registry provisionados. Protocolos locais/mock transports não substituem E2E externo.

## CLI e UI

- `sentra_canvas/service.py`, `sentra_cli/agent.py` e `sentra_cli/canvas.py` tiveram correções anteriores de leitura read-only de notas recebidas pelo CLI, exemplos de modelos/nomes válidos e mensagens HTTP 400 seguras. O aplicativo/broker antigo não recarregou automaticamente código Python.
- Tentativa adicional de normalização de `Terminal 1` pelo CLI foi BLOQUEADA pelas configurações de segurança da ferramenta. Não contornamos; o CLI ainda deve usar nomes válidos como `Terminal_4`. Não anunciar normalização automática como entregue.
- Não reiniciamos brokers de produção nem encerramos ConPTY com sessões em andamento.

## Empacotamento e CI

- Novo build candidato `.tmp/qa-checkpoint-20261009/canvas-dist-fixed/sentra-canvas.exe` (110.888.390 bytes) finalizou exit 0, SEM instalá-lo e SEM afirmar aceite WebView2.
- `scripts/ci/verify_release_contract.py --require-tracked`: SENTRA_CICD_CONTRACT_OK (somente gate de inputs).
- `git show --format= --check HEAD` continua exit 2 no checkpoint e4b3968, devido a espaços e linhas vazias introduzidos no commit anterior (desktop.js gerado, notices, docs e check_mypy_baseline). Um novo commit aprovado será necessário para superar o gate HEAD; não modificar bundle gerado byte a byte só para silenciar verificador.
- Suíte Python unitária integral do checkout está EM EXECUÇÃO nesta sessão; registrar contagens/exit code depois de terminar. A última suíte integral **anterior** a estes novos fixes retornou 1855 passed, 54 failed, 37 skipped, 1 error.

## Gates P0 que ainda impedem declarar produto fechado

- Comprovação com dois PCs físicos, IPs Hamachi/Radmin, identidade de ambos, mTLS mutual pinning, firewall/ACL, reconexão, cancelamento e verificação de recebimento e conclusão de tarefas remotas.
- Sincronização de notas/Canvas Yjs/Hocuspocus entre hosts sem criar grants/Operations via CRDT; tarefas e contextos selecionados, autorização no host A e no host B.
- Fluxo external provider real e todos os SDKs/daemons necessários autorizados, configurados e testados.
- Suíte Python/JS/Edge/WebView2 integral verde e build MSI + instalador + aceite Windows com assinatura quando aplicável.
- Não fazer release, commit/push da árvore inteira, `git reset/clean` ou restart do Canvas principal sem consentimento e preservação de sessões.

## Resultado final dos testes desta execução

- `tests/unit`: **1902 passed, 36 failed, 37 skipped, 1 error**, 14 subtests passed, 1 warning, **exit 1** em 462,71 s. Melhorou frente a execução anterior de 1855 passed / 54 failed / 1 error, mas gate Python não está aprovado.
- Principais falhas remanescentes: `test_mcp_hardening_v2` (grants), `test_sentra_benchmark_datasets` (clones/assets), `test_sentra_collab_boundary` (expectativas legadas de opt-in), `test_sentra_executors_daytona_sessions_round3`, `test_sentra_executors_remote_sessions_round3`, `test_sentra_executors_rustdesk_sessions_round3` (+ teardown error), `test_sentra_interop_gate4` e `test_sentra_interop_workflow_worker`.
- `npm test --prefix sentra_collab`: **54 passed, 0 failed, exit 0**, incluindo dois peers WS/Yjs/SQLite, guards de grants e tombstones. Testes localhost não provam VPN multi-PC.
- `test_sentra_interop_activepieces_provider.py` após observação fixada: **4 passed, 1 skipped**; junto com testes específicos de classificação: **7 passed, 1 skipped**. O teste que antes falhava `test_lost_post_reply_never_resends_even_with_fresh_operation_id` agora passa.
- `test_canvas_peer_admission.py`: **5 passed**. Núcleo/Canvas/CLI/peer-wire/manifesto antes selecionados: **31 passed**.
- `tests/failure tests/integration`: execução separada iniciada (pytest wrapper PID **39500**, Python filho PID **24240**) avançou ~62 testes e ficou sem saída prolongada; tentativa de enviar Ctrl-C ao processo pela ferramenta foi BLOQUEADA pelas configurações de segurança. NÃO afirmar conclusão, não contornar o bloqueio ou matar outros processos do usuário. O status permanece INCONCLUSIVO até o processo efetivamente encerrar.
- Build `--phase canvas` terminou exit 0 gerando `.tmp/qa-checkpoint-20261009/canvas-dist-fixed/sentra-canvas.exe` com **110.888.390 bytes**. Ainda sem smoke homologado do executável/WebView2 nativo e sem MSI completo.
- `verify_release_contract.py --require-tracked`: `SENTRA_CICD_CONTRACT_OK`; `git show --check HEAD`: exit 2 por whitespace **já presente no checkpoint e4b3968**. CI required/release não podem ser declarados verdes.

## Resultado operacional e restrições

- As duas instalações de SENTRA *não* conversaram por Hamachi/Radmin nesta sessão: faltam dois IPs de VPN, identificação/pins mTLS/ACL e endpoint remoto. O lado receptor agora aceita somente referência com WorkItem/grant locais e reserva Operation no Control Plane; não executa tarefas.
- O erro do Canvas CLI do usuário (nome `Terminal 1` com espaços/modelo placeholder) tem melhoria de prompt de modelo e erros HTTP 400 segura em código anterior, mas tentativa adicional de normalizador foi BLOQUEADA pela ferramenta; não prometer normalização automática. A versão aberta ainda não recarregou o Python.
- Os providers ACP/A2A/MCP/OpenHands/Activepieces passaram em laboratório de protocolos em grande parte, mas nenhum serviço de terceiros real foi provisionado com credenciais/containers na rede do usuário.
- Nenhum broker principal/ConPTY foi reiniciado, nenhum instalador instalado, nenhum push/commit global efetuado. É checkpoint de desenvolvimento, não release aceita.

### Retificação final — suítes de integração e falhas

A execução `python -B -m pytest -q -p no:cacheprovider tests/failure tests/integration --disable-warnings --tb=short` terminou **normalmente**, apesar da pausa prolongada: **183 passed, 10 skipped, exit 0, 137,38 s**. A observação anterior de que estaria inconclusiva foi superada pelo resultado final; nenhum processo de teste precisou ser finalizado. O único gate de pytest ainda reprovado nesta rodada é `tests/unit` (1902 passed, 36 failed, 37 skipped, 1 error). JavaScript da colaboração: 54/54 passou. Não se trata de homologação E2E entre dois PCs, serviços de terceiros ou instalador Windows.
