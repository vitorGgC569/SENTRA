# SENTRA OS — coordenação de quatro conversas paralelas (10/10/2026)

## Premissas obrigatórias

Repositório autoritativo: `C:\Users\vitor\OneDrive\Desktop\SENTRA`.
Use Desktop Commander conectado ao computador OGrandeOxta; execute testes, trabalhe no checkout real, não responda apenas com plano ou exemplos.
Git contém MUITAS alterações simultâneas não commitadas. **Não faça reset, checkout, clean, stash global, commit/push global, instalação não solicitada, ou alteração de credenciais/cookies da conta.**
Não edite fora do domínio indicado. Faça modificações cirúrgicas, com testes de implementação real e não apenas unit mocks. Não use uma segunda fonte de verdade. A autoridade é `sentra_mcp/services/control_plane.py::ControlPlaneService`, `authorization.py::AuthorizationService`, `durable.py::DurableRunService`, `sentra_runtime/central_authority.py`, `sentra_canvas/service.py::Canvas`, `sentra_canvas/task_runtime.py`.
Arquivos compartilhados `control_plane.py`, `sentra_mcp/server.py`, `sentra_canvas/service.py`, `sentra_canvas/__main__.py`, `sentra_canvas/desktop_ui/`, `sentra_remote/installer.py`, workflows CI, `sentra_runtime/central_authority.py` são **reservados à conversa coordenadora**. Se precisar integrar nesses, deixe patch/handoff explícito no relatório da sua frente, incluindo assinatura exata da API e testes existentes; não modifique cegamente.
Cada agente escreve resultados reais e próximos bloqueios em `docs/SENTRA_COS_AGENT_N_2026-10-10.md`, com paths/testes/evidências. Não marque 34/34 como aceitos sem E2E completo. A conversa coordenadora integrará as APIs e fará regressão/Setup.
Fonte de escopo: `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md`; auditoria `docs/SENTRA_AUDITORIA_COBERTURA_CHAT_ON_STEROIDS_2026-10-09.md`; checkpoint recente `docs/SENTRA_COS_EXECUCAO_INTEGRAL_2026-10-10.md`. Upstream como referência fixada `third_party/chat-on-steroids/` (não executar scripts upstream). Identidade de conversa/account ChatGPT Web e permissões devem ser provadas; sem capturar ou compartilhar tokens/cookies.
Não crie loops autônomos de reenvio em chamadas Web com efeito incerto; não afirme permissões de modelos ausentes da conta. Não introduza consumo financeiro automático.

## CHAT 1 — MCPB + Skills (G01, A06, A07, G07, A21)

Propriedade: `sentra_mcp/services/plugin_bundles.py`, `plugin_host.py`, `tool_exposure.py`, `skill_library.py`, `sentra_interop/mcp.py`, `mcp_stdio.py`, arquivos novos na família MCPB/skills e `tests/unit/test_sentra_cos_mcpb_*`, `test_sentra_cos_skill_*`. Coordene com a conversa coordenadora antes de alterar `mcpb_sandbox.py` (foi criado pela própria coordenadora nesta sessão) ou fachada central.

Implementar lifecycle completo MCPB: stdio já existe com Docker Linux real e operação durável; melhorar isolamento, identidade de imagem, reconciliação de órfãos, health/restart com fail-closed; MCP HTTP local autorizado + OAuth sem armazenar segredo em logs, atualização/revogação/uninstall e catálogo com schema+colisão global. Verificar publicação seletiva e refresh schema com prova de conta externa (sem fingir teste se conta não permitir). Completar Skills pinadas por SHA, ativação/revogação/update, leitura por WorkItem real e UX handoff (UI da coordenadora). Provar grants por tool e status SQLite; testes E2E herméticos. Documente o que ficar externo.

## CHAT 2 — Conta Web + Segurança + APIs/Code Mode (G02, G12, A01–A05, A09, G08, G11, A08, A10)

Propriedade: `edge_extension/`, `browser/`, `sentra_mcp/services/chat_access.py`, `browser_evidence.py`, `chat_models.py` se existir, novos módulos nomeados `web_account_*`, `code_mode_*`, `action_consent_*` + testes próprios. Não edite `native_bridge/` (Chat 3); escreva contrato entre produtor/browser e receptor/broker para integração.
Implementar prova exata request MCP ↔ message.metadata.request_id ↔ conversation, aba/perfil/geração/approval; não confiar em DOM desconhecido ou TTL para atribuir identidade. Separar status de conta, modelo/effort/Automatic suportados, logout/troca de conta, extension/browser/connector proof, bloqueio e trust por conversa. APIs locais read/action com dois consentimentos; Code Mode QuickJS WASM sem host IO, limites reais e ferramenta interna submetida individualmente a Operation/Grant. Sem ler/exportar cookies ou executar extensões desconhecidas. Provar conta real só quando possível e distinguir fixtures. Handoff para integrar no Canvas/CLI, sem mudar arquivos compartilhados.

## CHAT 3 — Continuidade/histórico Web + agentes/terminal (G03, G04, A11–A14, A20, G05, G06, A16, A17)

Propriedade: `native_bridge/`, `sentra_mcp/services/session_checkpoint.py`, módulos novos `web_history_*`, `continuation_*`, `sentra_executors/`, testes `test_sentra_cos_web_*` / `test_sentra_*continuation*` / `test_sentra_executors_*`. NÃO edite `edge_extension/` (Chat 2). Para mensagens browser necessárias, detalhe contrato de entrada para Chat 2.
Concluir Compact&Resume Web A→B real em fases com criação/claim/preflight/commit/publish/reconcile, recibo exato de mensagem e preservação Run/WorkItem/worker/grant; não reemitir em resultados UNCERTAIN. Fortalecer outbox, streaming por ID/revisão, anexos/cotas/histórico Web e busca opt-in com ACL/cripto. Completar Goal/Loop com custo/limites explícitos, worker health/GC sob ownership, terminal persistente com exit/head-tail/streaming e receipts. Priorize evidência em SQLite central e testes de crash/restart/conflitos.

## COORDENADOR (esta conversa) — Canvas/UX + instalador/release (G10, G13, A18, G09, A15, A19)

Propriedade: `sentra_canvas/` (UI React, editor/PDF, dialogs), `sentra_remote/` (setup/diagnostics/updater), `scripts/commander/`, `.github/workflows/`, testes da UI e release, e ARQUIVOS COMPARTILHADOS mencionados acima, respeitando modificações preexistentes.
Entregar visualizador PDF seguro completo e UX minimalista, revisão de edição com gate/Operation, watcher limitado, docks/teclado/reduced-motion e DPI; diagnóstico seguro, reparo guiado, staged app+extension+WebModels+schema, rollback; integrar os contratos dos três agentes no Control Plane/Canvas central; suíte CI/CD, Setup/MSI, instalação limpa e assinatura verdadeira. Não homologue sem certificado/teste real. Coordenação e validação são minhas responsabilidades.

## Protocolo de entregas

1. Inspecionar status/arquivos atuais antes da primeira edição; preservar outros checkouts compartilhados.
2. Criar e testar fatias pequenas mas completas com grants+SQLite, sem camadas soltas.
3. Ao chegar a dependência de outro agente, escrever contrato/handoff com nomes/métodos, entrada, saída, e testes; continuar no próprio escopo enquanto outro integra.
4. Atualizar relatório específico, lista de arquivos, comandos e resultados; NÃO afirmar concluído sem verificação.
5. Deixar a conversa/aba aberta; nenhuma ação automática repetitiva após término do turno sem agendamento próprio e consentimento.

## Conversas criadas no Edge — referências persistentes

- CHAT 1 / MCPB + Skills: https://chatgpt.com/c/6aca2883-cba4-83e9-a371-cf7eef1cb959 (janela Edge dedicada; ordem enviada e resposta constatada).
- CHAT 2 / Conta Web + Segurança + Code Mode: https://chatgpt.com/c/6aca28cf-617c-83ea-b866-dc4f85b40b7f (janela Edge dedicada; ordem enviada e resposta constatada).
- CHAT 3 / Continuidade Web + Agentes: https://chatgpt.com/c/6aca2920-0150-83e8-9d06-ccaf180d7fd2 (janela Edge dedicada; ordem enviada e resposta constatada).
- COORDENADOR: esta conversa do usuário, frente Canvas/UX + instalador/release e integração central.

O navegador Edge existente no perfil Default/Perfil 1 contém a extensão ChatGPT ("Control your browser"), que a própria barra da nova janela sinalizou ter acesso a chatgpt.com. Isso comprova presença/permissão da extensão nesse site, **não** que a extensão SENTRA própria está carregada ou que cada agente já recebeu grants de todos os serviços. A identidade real da conta não foi manipulada. As conversas foram salvas como URLs /c e devem permanecer abertas. Em futuras retomadas, abrir as URLs acima diretamente, não criar mais chats duplicados. As conversas Chat não executam indefinidamente após um turno sem nova solicitação/agendamento; checkpoints em disco são obrigatórios.
