# SENTRA × CoS — implementação do transporte Web durável

Atualização: 2026-10-11, America/Sao_Paulo. **Implementação candidata integrada; homologação e ativação em produção pendentes.** Este documento distingue código/testes em diretórios isolados da versão efetivamente carregada nos serviços. Não houve commit/push, reset, clean, stash, alteração do tunnel MCP, OAuth, cookies ou envio a conta real nesta missão.

## 1. Diagnóstico original

A rota Responses encaminhava chamadas ao Browser Worker sem composição integral com a outbox V2 central. Sucesso HTTP/SSE não comprovava entrega nem resposta. Identidade de conta, perfil, seleção física e origem de chamadas MCP precisavam de prova independente. Continuidades e Goals existentes ainda não tinham todos os entrypoints CLI/Canvas comuns.

No incidente 503 informado pelo usuário, a inspeção encontrou upstream saudável em 17841 e ausência de listener em 17842. A inicialização antecipada de um módulo candidato também provocava falha SQLite em testes do Gateway. Foram corrigidas a criação do diretório e a inicialização sob demanda. Apenas o Gateway ausente foi iniciado, oculto, sem `--launch-upstream`; upstream e sessões foram preservados. Isso explica a recuperação observada, sem atribuir retrospectivamente todas as falhas Cloudflare a uma causa comprovada.

## 2. Arquitetura resultante

CLI/Canvas usam o Control Plane, Run, WorkItem, principal e grant originais. Responses recebe capability vinculada à mesma autoridade; intenção original é protegida antes do upstream. O Worker realiza preflight do prompt físico, admission/claim na outbox existente e fence durável single-use antes de Enter. Recibo user associa request/message/document/epoch reais. Answer exige prova host independente, histórico protegido revisionado e ACK do job original. UNCONFIRMED requer reconciliação, nunca reenvio automático.

Não há segunda fila, clonagem de grants ou segundo Control Plane. As projeções novas ficam nos namespaces SQLite centrais existentes. O JobStore V2 e o broker autenticado continuam proprietários de leases, receipts e recuperação. A extensão não consome jobs reservados ao Worker externo.

## 3. Subagente 1 — backend

Implementou WebSendAuthority, claim externo serializado, fence, receipts/reconciliação, streaming/final protegido, ACK final recuperável, collector Electron host-only, ConversationGoalLoop e ConversationWebContinuation. UsageLedger resolve scopes centrais para Goals e Web e valida owner/workspace/Run/WorkItem/assignee. Preferências e projeção de entrega são cifradas por conversa; a projeção de entrega é somente display, fora do contexto enviado ao modelo. Revisões Host e Worker têm relógios independentes: a projeção Host é gravada na mesma transação SQLite do frame protegido. Regressão, conflito na mesma revisão, mudança de source/document/epoch ou omissão de prova já fixada negam sem alterar a mensagem original.

Evidência e comandos: [relatório backend](SENTRA_COS_SUBAGENT_BACKEND_FINAL.md), [contrato backend](SENTRA_COS_BACKEND_CONTRACT_CURRENT.md). Foram retomados exatamente os mesmos dois subagentes da missão. Os agentes retomados usam a mesma família de modelo com especializações e esforços de raciocínio diferentes; não se afirma heterogeneidade de família.

## 4. Subagente 2 — navegador e UI

Patch allowlisted do upstream conecta adapter/IPC/Worker ao handshake durável, sem alterar a árvore upstream original ou inventar request/message IDs. Implementa leitor de committed React, doc/epoch, seleção atual e snapshot privado do Browser Host. UI React mostra estados centrais, bloqueio de loop sem grant e Compact&Resume com preview do resumo e checkpoint real.

Typecheck e duas compilações isoladas passaram; hashes CLI/helper coincidiram entre árvores. Nenhum candidato foi instalado. O Host agora emite desafio single-use e observa independentemente user/assistant, request/parent, SHA do corpo e status em committed React; expectativas Worker não são prova. Hash do patch atual: `875d632c9b93b674c7318edd3800686606f66a7e8fe292a7e5ea256defa98d90`. Hash Host conferido nas duas árvores: `f7578e85528675487f574605e5fc61ec8d7e6dae244ad6fc7f39ff77d553d956`. Evidência, hashes e regressões antigas: [relatório browser](SENTRA_COS_SUBAGENT_BROWSER_FINAL.md), [contrato browser](SENTRA_COS_BROWSER_CONTRACT_CURRENT.md). O código de observação independente está integrado; calibração de identidade/seleção/aprovação em conta real continua pendente.

## 5. Integrações do coordenador

Factory do relay usa o mesmo Control Plane; MCP encadeia guard de recibo/conta antes das tools; Gateway admite Responses na autoridade existente, controla rollout durável e projeta delivery SSE. CLI persiste escolhas, exige effort anunciado, bloqueia fallback da escolha Web e integra Goal/Loop/Compact&Resume. Canvas fornece rotas owner-auth e projeções centrais para React.

Hardening do Gateway: conexão inicial limitada, nenhuma repetição de POST, classificação NOT_SENT/UNCONFIRMED, stream truncado permanece quebrado, frames SSE completos/limitados, token e flag de produtor exclusivamente host, pin de principal/grant através de restart, watchdog sem reinício de owner externo/ativo/desconhecido, liveness separada de readiness. Porta exclusiva é reservada antes de tocar storage/chaves; falha de leitura ou token inválido nunca autoriza sua substituição. Gate final impede publicar sucesso Responses sem recibos ANSWERED, inclusive terminal maior que 8 KiB ou com caixa divergente. Authentication revision exige inteiro explícito, exclui bool e deve corresponder à identidade já verificada. Budget/binding/delivery/usage usam o mesmo contexto aprovado, mesmo se Goal mudar durante a resposta.

## 6. Arquivos desta missão

Esta lista não atribui ao trabalho atual todas as mudanças do checkout, que já estava amplamente modificado.

- Gateway: `sentra_model_gateway/gateway.py`, `turn_authority.py`, `web_transport.py`, `browser_host_identity.py`.
- Entry points: `sentra_cli/agent.py`, `client.py`, `config.py`, `repl.py`; `sentra_canvas/service.py`, `__main__.py`; `sentra_remote/browser_relay.py`; `sentra_mcp/server.py`.
- Backend: `native_bridge/web_send.py`, `conversation_continuation.py`, `job_store.py`, `protocol.py`, `relay.py`, `web_delivery.py`, `continuation_web.py`, `web_evidence_ingress.py`; `sentra_core/conversations.py`, `provider_usage.py`; `sentra_executors/goal_loop.py`; `sentra_mcp/services/browser_evidence.py`.
- Browser/UX: `integrations/codex_chatgpt_web/sentra-upstream.patch`, `prepare_durable_qa.py`; React `durable-web-state.js`, `durable-web-dialog.jsx`, `compact-resume-panel.jsx`, QA entries, inserções pontuais em `main.jsx`/`desktop.css`; testes Electron isolation.
- Testes: módulos backend próprios e composition/CLI/Canvas/Worker/Host/Gateway citados nos relatórios e comandos abaixo. Novos arquivos permanecem no checkout, incluindo untracked.

## 7. Referências CoS reaproveitadas

Contratos de input/start-input, correlação/recorder, armazenamento revisionado, continuation/handoff/resume-gate, Goal e seleção de modelos. Foram adaptadas invariantes ao storage e autoridade SENTRA, sem copiar armazenamento JSONL/fila/renderer concorrentes, sessões ou cookies.

## 8. Componentes SENTRA preservados

ControlPlaneService, DurableRunService, AuthorizationService, Governance/Budget, SQLiteControlPlaneStore, leases/fencing, JobStore/WebDeliveryJournal V2, AuthenticatedWebReceiptBroker, ChatAccess/BrowserEvidence, WebHistoryStore, ConversationStore, OS secret broker, Browser Host/control token, terminal/Canvas existentes. Enrollment de collector não autentica conta e não cria grant.

## 9. Testes e resultados

Resultados sobrepostos não devem ser somados como testes distintos.

| Seleção | Resultado | Limite |
|---|---|---|
| Consolidado atualizado: 23 módulos Python, inclui Worker Edge + Electron Host HTTP + mudança de identidade | **220 passed, 116.46s; nenhum skip** | Antes das últimas correções de caixa SSE e pin doc/epoch; conta/DOM/calibração são fixtures |
| Host HTTP adversarial + clocks duráveis + composição default Host | **40 passed, 14.99s** | Relógios central 17 / Host 1 aceitos; bool/null/texto/revisão de conta diferente negados |
| Gate final após reproduzir a inconsistência de caixa SSE | **23 passed, 18.22s** | Três casos falhavam antes da correção, passaram depois; HTTP/SQLite reais temporários |
| Gateway + startup + gate final após a correção de caixa SSE | **80 passed, 49.36s** | Não modifica Gateway/upstream ativos |
| Default Host + Worker HTTP + snapshots + clocks, após pin original doc/epoch | **48 passed, 20.68s; nenhum skip** | Troca de aba/snapshot mantém SENDING, sem recibo final; inclui 17 testes de clocks/atomicidade |
| Coordenador: 18 módulos Gateway/turn/composition/CLI/Canvas/Worker/Web V2/crypto/history/Goal/usage | **139 passed, 75.15s** | Antes das duas correções finais da revisão independente |
| Host HTTP/endpoint adversarial + SSE oversized + flag host-only | **15 passed, 52 deselected, 7.21s** | Servidor/descriptor descartáveis |
| Gateway/Host/entrypoints/Goal usage focal | **76 passed, 49.56s** | Após gate de conclusão do proxy; antes do último contexto aprovado CLI |
| Goal usage + provider usage + entrypoints após contexto aprovado CLI | **17 passed, 6.58s** | Modelo fixture; sem conta real |
| Backend amplo relatado pelo subagente | **154 passed, 68.77s** | Ambiente isolado; antes da última revisão |
| Backend atualizado: 32 módulos, comando no relatório próprio | **229 passed, 107.59s** | Antes dos cinco casos extras de clocks e do último pin doc/epoch; testes de clocks finais 17/17 |
| Browser Worker→Gateway e React→Canvas | **2 passed, 6.64s** | HTTP/SQLite reais; conta/DOM/attestors fixtures |
| Worker/Host/DOM atual | **29 passed / 455 assertions** | Chromium isolado; 11 testes Host adversariais incluídos |
| Node Canvas / Electron isolamento atual | **2 / 4 passed** | Perfil descartável; nenhum skip Electron |
| Upstream amplo comparado à baseline | Bun **145 pass / 19 fail**, Node **118 pass / 3 fail** | Mesmas falhas na baseline reconstruída; não declarar suíte toda verde |

Reprodução principal:

```powershell
$env:SENTRA_BROWSER_QA_TREE='C:\Users\vitor\AppData\Local\Temp\sentra-browser-v2-hlczzsv6'
python -m pytest tests/unit/test_sentra_model_gateway.py tests/unit/test_sentra_gateway_startup_protection.py tests/unit/test_sentra_browser_host_identity.py tests/unit/test_web_turn_authority.py tests/unit/test_sentra_cos_gateway_outbox_composition.py tests/unit/test_sentra_cos_gateway_completion_gate.py tests/unit/test_sentra_cos_central_transport_composition.py tests/unit/test_sentra_cos_cli_canvas_entrypoints.py tests/unit/test_sentra_cos_durable_worker_gateway.py tests/unit/test_sentra_cos_durable_canvas_browser.py tests/unit/test_sentra_cos_web_v2_transport.py tests/unit/test_sentra_cos_web_relay_authenticated_routes.py tests/unit/test_sentra_cos_web_v2_http_ingress.py tests/unit/test_sentra_cos_web_r6_full_cycle.py tests/unit/test_sentra_cos_web_outbox_encryption.py tests/unit/test_sentra_cos_web_history_protected.py tests/unit/test_sentra_executors_cos_goal_loop.py tests/unit/test_provider_usage.py tests/unit/test_sentra_cli_model_effort.py tests/unit/test_sentra_cos_backend_goal_usage.py tests/unit/test_sentra_cos_backend_host_history_clock.py tests/unit/test_sentra_cos_backend_conversation_goals.py tests/unit/test_sentra_cos_backend_conversation_continuation.py -q --tb=short
```

O diretório QA acima é candidato temporário, sujeito a nova compilação quando o patch mudar. Não é o payload instalado. `git diff --check` passou nas fontes Python tracked revisadas. Ao incluir o arquivo patch upstream, detecta sete linhas de contexto de diff com espaço, próprias do artefato patch; não foram retiradas, pois alterar contexto invalidaria o hash/proveniência do candidato. `git apply --check` e as duas builds da proveniência continuam válidos para o patch intacto.

O subagente browser reconferiu o fechamento do pin original doc/epoch e executou independentemente a mesma seleção focal na segunda árvore `cx5hq57r`: **48 passed, 22.59s, nenhum skip**, log `final-p1-closure-qa.log` e resumo `SENTRA_P1_CLOSURE_QA_RESULTS.json`. Não somar aos 48 do coordenador. O achado específico está fechado por fonte/teste; homologação real permanece pendente.

## 10. Problemas corrigidos

Inicialização candidata derrubando Gateway legado; ausência de diretório SQLite; migração serializada; uso incorreto das colunas lease/id; ACK final não liberando worker; segunda fase usando índice zero; replay de preflight READY; preservação de incerteza após perda de página; token retirado não revive; grant substituído durante chamada não é aceito; cliente não habilita produtor; frame SSE incompleto/oversized não vira conclusão limpa; health não abandona socket por falha local. Revisão independente detectou publicação terminal sem gate e budget Run A/binding Run B: corrigidos e testados. Corrigidos também rotação de chave após falha de leitura, mutação de storage antes da reserva exclusiva de porta, leitura terminal limitada a tail, inconsistência de caixa SSE e bool aceito como revisão de identidade. Host/Worker usam clocks separados com persistência atômica, sem fabricar igualdade.

## 11. Evidência de operações e recibos

`test_sentra_cos_gateway_outbox_composition.py` usa Control Plane, SQLite, outbox e crypto reais em diretório temporário: uma Run e um grant originais; intenção protegida; preflight idempotente sem segundo job; fence single-use; receipt user SENT não permite conclusão; assistant independente fixture final ANSWERED encerra job; segunda fase mantém Run e cria Operation/job próprios; falha após fence e descriptor perdido permanece UNCONFIRMED; rollback não altera receipts. Restart preserva principal/grant originais. Variante default Host persiste central revision 17 / Host 1 e nega bool/null/texto/revisão de conta diferente. Descriptor e snapshot precisam corresponder ao documento/epoch da submissão original, antes e depois da leitura; os casos de troca mantêm SENDING sem receipt. Não se afirma conta, mensagem remota ou prova assistant real a partir desse ensaio.

## 12. E2E

Integrações de processos/HTTP/SQLite/React/Worker em isolamento passaram. **Nenhum E2E autorizado com conta ChatGPT real foi executado.** Não foram reutilizadas intenções incertas de produção. Snapshots sem schema calibrado mantêm account_verified:false; ausência de cartão mantém approval UNKNOWN; seleção física oculta não é inferida.

## 13. Pendências e critérios A–L

Implementação local e ensaios demonstram admissão comum, ausência de resend incerto, recuperação, crypto, Goals/scopes e handshakes. Permanecem gates de produção: identidade independente de conta/perfil/source atual; modelo/effort e aprovação física comprovados; observação host independente user/assistant homologada; origem MCP associada pelo ingress autenticado; compilado instalado comprovadamente atual; E2E autorizado entregue/respondido e continuidade A→B comprovada. Loop persiste pacing/WorkItems e não executa automaticamente sem o executor/grants centrais. Grant ausente não é resolvido emitindo permissão.

A/B/C/F/H/K/L ainda não estão homologados na rota real. D/E/G/I/J têm evidências isoladas detalhadas, sem extrapolar para uma conta real ou instalação. Custo/quota da conta permanecem desconhecidos quando não reportados. Limite físico exato de ChatGPT: 20.000 caracteres; ChatResult: 200.000 caracteres. WebHistoryStore limita frame a 131.072 bytes UTF-8 e workspace a 8 MiB; aceitar ChatResult não implica aceitar frame no histórico. Não houve ampliação ou truncamento para forçar passagem.

## 14. Ativação e rollback seguros

1. Verificar hash/proveniência/typecheck/build do candidato atual e corrigir/registrar regressões baseline.
2. Obter autorização específica para inspeção/calibração na sessão real e para instalar candidato em janela controlada. Identificar conta/perfil pela fonte permitida, sem cookies/tokens/storage/session APIs.
3. Inscrever collector real source/surface/worker com owner-auth; enrollment não substitui conta. Validar modelo/effort/aprovação e papel/body/request/parent independentemente.
4. Usar uma intenção nova, Run/WorkItem/grant originais, em E2E autorizado; nunca reenvio de UNCONFIRMED. Confirmar user receipt, assistant final e ACK, restart/reconcile e continuidade sob mesmos scopes.
5. Validator host verifica gates; transição CAS `legacy → candidate_v2 → durable_v2`. Booleano de cliente/modelo/HTTP não é evidência. Default validator ausente nega ativação.
6. Para instalar/reiniciar, verificar ownership e drain de chamadas/leases. UNKNOWN ou atividade impede restart. Não matar upstream de usuário/owner externo.
7. Rollback CAS para legacy altera somente novas chamadas. Preservar outbox, receipts e UNCONFIRMED; reconciliar sem novo clique. Nunca executar produtores antigo/novo em paralelo.

## 15. Rota efetivamente ativa

O listener recuperado 17842 (PID20956) encaminha ao upstream preservado 17841 (PID19712), com health 200/ready:true observado novamente em 2026-10-11. O transporte efetivamente ativo permanece legado. O processo foi iniciado após a correção de inicialização lazy; **as proteções acrescentadas depois não estão todas carregadas nesse processo**. Elas estão no código candidato e precisam de ativação/restart controlado. Os builds novos foram somente QA, não substituíram o instalado. Readiness local não prova versão, conta, recibo ou conclusão da missão.

O proprietário autorizou explicitamente a atualização somente do Gateway de recuperação ocioso, preservando upstream e sessões. Mesmo após essa autorização, a revisão automática rejeitou o comando inteiro antes da execução, com `blocked by policy` e sem motivo adicional. Não houve Stop-Process/Start-Process nesta tentativa e nenhuma rota alternativa foi usada para contornar a rejeição. Essa autorização permanece válida; o impedimento é a revisão automática, não falta de confirmação do usuário. Os dois PIDs originais e health saudável foram conferidos após o bloqueio.
