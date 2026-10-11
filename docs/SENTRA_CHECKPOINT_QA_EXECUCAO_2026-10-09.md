# SENTRA — execução real e QA do checkpoint e4b3968

Data 09/10/2026, equipamento OGrandeOxta, repositório C:\Users\vitor\OneDrive\Desktop\SENTRA, base main e4b39688f67a176b603ac90f04e2d9af6686a20b. Este relatório NÃO é aceite integral dos 37 projetos, nem autorização para liberar o instalador. Mudanças e testes desta sessão ocorreram num laboratório isolado; não substituíram broker/prévia do usuário.

## 1. Desktop React Flow + Radix + Lucide + xterm

- Reconstrução no próprio Windows: cd sentra_canvas/desktop_ui && npm run build; sucesso exit 0. Vite materializou sentra_canvas/static/desktop.html e desktop-assets/desktop.js|desktop.css|manifest.json. Avisos de scripts legacy e chunk JS de 895,75 KB (263,34 KB gzip), nenhum erro de build.
- Com o broker de avaliação existente, HTTP 200, token de fragmento removido, 3 React Flow nodes, 3 terminais xterm, 2 edges, erros JS 0, erro HTTP 0. Viewports 1024×768, 1440×900, 1920×1080, sem scroll horizontal. Reload preservou 3 nodes/3 xterms. Capturas em .tmp/qa-checkpoint-20261009/desktop-fresh-build-*.png.
- Script .tmp/qa-checkpoint-20261009/desktop_e2e.py criou CanvasServer real temporário com 2 PowerShell/ConPTY próprios e grafo com link real, abriu/fechou diálogos Radix terminal/agente/nota, recusa de equipe sem dois agentes, painel Rede carregado da API real, saída de PowerShell enviada/visível no xterm, expansão/resize/reload sem alteração dos dois PIDs. Erros JS/HTTP 0; capturas em .tmp/qa-checkpoint-20261009/qa-*.png.
- A janela nativa pywebview/WebView2 foi identificada anteriormente via Win32, mas a aceitação COMPLETA de minimize/maximize/close, DPI nativo, teclado e visual do usuário permanece pendente.
- PyInstaller criou NOVO candidato .tmp/qa-checkpoint-20261009/canvas-dist/sentra-canvas.exe (110.887.292 bytes), sem substituir instalada. O primeiro smoke HTTP do processo compilado encontrou 404 ao consultar desktop-assets/manifest.json; subsequentemente foi identificado o problema na allowlist de assets (o servidor aceitava js/css mas não manifest.json). Corrigido em sentra_canvas/__main__.py com exceção estrita para manifest.json. O pacote gerado PRECEDE esta correção e NÃO está homologado; precisa rebuild + reteste. Uma investigação adicional do EXE foi bloqueada pelas configurações de segurança da ferramenta; não contornamos o bloqueio. Apenas brokers temporários próprios foram encerrados.
- Teste novo tests/unit/test_canvas_desktop_manifest.py verifica rota correta, conteúdo, paths negados; integração de 19 testes de manifesto, migração graph, workflow e peer passou.

## 2. Autonomia com modelo autenticado REAL e Control Plane durável

- Modelo real autenticado comprovado: python -m sentra_cli --model sentra/codex/current respondeu o marcador SENTRA_MODELO_REAL_OK_20261009, exit 0, 6,93 s, sem execução de ferramentas.
- Script .tmp/qa-checkpoint-20261009/autonomy_live_e2e.py em workspace temporário e CanvasServer real: coordenador QA_Coordenador (Codex real) recebeu instrução para criar somente QA_Filho e o fez espontaneamente via comando Canvas; filho executou Codex real; contexto do filho trouxe parent_agent_id do coordenador e objetivo limitado; bootstrap handoff persistido; recibo answered; resposta de modelo QA_FILHO_RESPONDEU_20261009. 2 agentes, 2 terminais, 1 handoff.
- Script .tmp/qa-checkpoint-20261009/autonomy_reconcile.py reabriu estado do laboratório SEM reexecutar modelos. Vinculou o filho a WorkItem real + grant AuthorizationService/GovernanceService SQLite de capability canvas.workspace.inspect. Chamou Canvas.center_inspect / ControlPlane autoritativo, persistiu Operation SUCCEEDED; replay original UNCERTAIN sem segundo efeito; revoke de grant bloqueou novo submit. Arquivos só na árvore .tmp local de QA. Não demonstra autonomia genérica em produção, mas é inferência real e reconciliação central REAL numa tarefa read-only segura.
- Sem novos tokens/segredos impressos nem alterações no workspace de produção.

## 3. Rede Hamachi/Radmin: contrato e E2E de transporte local

- Novo sentra_canvas/peer_work_wire.py: TCP loopback entre peers explicitamente pinados, AEAD AES-256-GCM com HKDF do segredo pareado e AAD workspace, assinatura Ed25519, TTL, strict cap 8 KiB por frame, JSON metadata sem prompts ou segredos, transport receipts autenticados.
- Duas SQLite persistentes inbox/outbox guardam dedupe após restart, TASK_OFFER → PENDING_LOCAL_ADMISSION, TASK_RESULT → PENDING_RESULT_VERIFICATION, ack → RECEIVED_PENDING_REMOTE_ADMISSION. ACK significa transporte e não prova execução/modelo. Sem resend automático após incerteza.
- prepare_authorized_offer(...) exige o REAL Canvas WorkItem RUNNING, assignee, workspace, required_capabilities, AuthorizationService scoped grant peer.task.offer e request_key único antes de gravar outbound intent; após revogação nega. A recepção continua inerte e EXIGE autorização/admissão independente no destino.
- tests/unit/test_canvas_peer_work_wire.py: 14 passed (TCP com 2 sockets reais locais, criptografia, assinatura, bloqueios cross-mesh/workspace/forged, tamper, expiry, idempotência, restart, autorização/grant revocation real).
- NÃO HÁ rede Hamachi/Radmin real de 2 computadores, mTLS remoto ou IPs/identidades peers fornecidos. Loopback remoto é deliberadamente negado. Não foi habilitado serviço público, firewall, VPN nem autoscan. Não declarar funcionalidade de colaboração remota pronta.

## 4. Testes e correções de regressão

- Node: npm test --prefix sentra_collab → 54 passed, exit 0.
- Suíte Python INTEGRAL do checkpoint e4b3968, antes dos pequenos fixes: **1.855 passed, 54 failed, 37 skipped, 1 error, 14 subtests passed, 1 warning, exit 1, 458,65 s**. NÃO está verde. Muitas falhas no Windows por handle SQLite temporário WinError32, além de testes novos com nomes com espaços inválidos, incompatibilidade com grants, collab auto-mounted vs testes antigos, providers/benchmarks.
- Migração sentra_canvas/graph.py: CREATE TABLE IF NOT EXISTS collaboration_projection, mantendo retrocompatibilidade; seu teste focado passou.
- Testes novos de workflow tinham fixture com espaços (violam validator do produto) e faltava max_bytes na leitura de Artifact: atualizados apenas os fixtures em tests/unit/test_canvas_workflow_documents_integration.py; 3 passed.
- Outros 5 testes de workspace/rede/contexto tinham nomes fora do contrato: corrigidos **somente nomes de fixture** em tests/unit/test_canvas_network_whitelist.py e test_canvas_agent_working_context.py; 5 passed. A validação de nomes no produto NÃO foi relaxada.
- Testes adicionais do manifesto desktop, migração graph, workflow, peer wire: **19 passed** com exit 0 após correções.
- Regressão extensa Python precisa ser corrigida por grupos, depois rerodada integralmente antes de release; não reutilizar o 1.718/7 do commit anterior.
- Testes de colaboração antigos tests/unit/test_sentra_collab_boundary.py ainda exigem ausência de script no Canvas, mas o novo produto o carrega opt-in; atualizar aceite de segurança sem retirar negativos de auth/tokens.
- Inconsistência de grant mais específico em test_mcp_hardening_v2.py ainda aberta; não afrouxar policy sem revisão.
- Provider remoto, Daytona, RustDesk, guest HCS/gVisor, TLS/anchors externos, model-provider alternativo, workflows complexos e benchmark físico não foram homologados neste teste.

## 5. Controle de impacto e próximos gates

- NÃO mexeu em .maestri/ nem credenciais/third_party ou WorkItems/ConPTY da instalação principal; não fez git reset/clean, commit, push ou instalou serviços externos.
- O Canvas compilado é apenas candidato local. Não rodar MSI/install/update sem todos os testes relevantes e smoke do novo bundle corrigido.
- Prioridade: correções da suíte Python (54 falhas/1 erro do baseline), rebuild de sentra-canvas.exe com manifesto permitido, smoke da janela nativa WebView2/instalador em ambiente seguro, broker atualizado sem destruir sessões, aprovação visual do proprietário.
- Para colaboração VPN real faltam pelo menos endereço de 2 PCs, identidade mTLS pinada, receiver-side Control Plane admission de WorkItem, armazenamento/consulta de receipts, reconnect sobre VPN, testes de revogação antes de executar, frames/input e cleanup, antes da habilitação.
- Revisar integração com providers externos em ambiente próprio autorizado, sem chamar mocks de E2E real. O checkpoint e4b3968 permanece em main como referência original; alterações desta rodada estão não commitadas para revisão.

Referências internas: docs/SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md, docs/SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md e docs/SENTRA_OS_CENTRAL_INTEGRATION_2026-10-09.md.
