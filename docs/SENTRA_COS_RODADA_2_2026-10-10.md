# SENTRA — auditoria independente e rodada 2 (10/10/2026)

## Conferência antes de reenvio

Mesmas conversas Edge, sem abrir novas:
- Chat 1 MCPB/Skills: https://chatgpt.com/c/6aca2883-cba4-83e9-a371-cf7eef1cb959
- Chat 2 Web/Conta/Code: https://chatgpt.com/c/6aca28cf-617c-83ea-b866-dc4f85b40b7f
- Chat 3 Continuidade/Agentes: https://chatgpt.com/c/6aca2920-0150-83e8-9d06-ccaf180d7fd2

Relatórios auditados: `docs/SENTRA_COS_AGENT_{1,2,3}_2026-10-10.md`.
Arquivos novos e modificados presentes em `git status --short`; os três agentes preservaram o checkout sem reset/commit/push.
Regressão independente coordenadora de 15 módulos críticos, incluindo implementação MCPB HTTP/Skills, ActionConsent/BrowserEvidence e WebContinuation/History/Goal: `python -B -m pytest -q -p no:cacheprovider <15 módulos> --tb=short --disable-warnings` => **49 passed, 0 failed** (15,31s). `python -B -m compileall -q` de 14 módulos novos/alterados => exit 0. `git diff --check` => 0, avisos de line endings preexistentes. Testes são herméticos e locais, NÃO representam aceite Web de conta real.

## Avaliação crítica

- CHAT 1: HTTP transport é JSON-RPC stateless sobre loopback pré-existente, não lifecycle completo MCP HTTP, sem OAuth2 PKCE/refresh/revoke, health/restart de servidor, dependências pinadas/supervisionadas, reconciliador Docker pós-crash ou purge final. `publication_snapshot` local não é prova de ferramentas atualizadas na conta ChatGPT. Skills replace/deactivate estão testados, UX/aceite real ainda pendentes.
- CHAT 2: duas tabelas de prova exata e `ActionConsentService` dão mais segurança ao gate, porém `require_exact_message` não está integrado a todos os tool calls centrais; contexto DOM/modelos/effort depende de prova externa; QuickJS WASM não implementado. `human_confirmed=True` é sinal confiável APENAS no backend após owner-auth real, nunca argumento MCP.
- CHAT 3: handoff A→B exige recibo Web verdadeiro, não fixture; frames/anexos/observações de quota são superfícies de armazenamento, ainda sem coletor autenticado/upload remoto. `GoalLoop` não é execução autônoma autorizada; terminal `exec_command/write_stdin`, streaming/head-tail e GC com ownership de OS ainda incompletos. **Risco P0: outbox `JobStore` mantém o prompt/resumo em texto claro**, apesar de histórico novo criptografado.
- Coordenador: integração de fachadas/Canvas/CLI/Setup/CI, PDF visual, watcher e UX; autenticação explícita para aprovação de operador; E2E real incluindo conta ChatGPT, extensão SENTRA própria, primeira instalação, assinatura Authenticode.

## Regras da segunda rodada

Mesmos chats; sem abrir sessões novas. Não interromper chat gerando resposta. Instruções para cada chat enviadas quando campo de envio estiver ocioso. Não editar arquivos reservados ao coordenador, nem conflitar `edge_extension` (Chat 2) com `native_bridge` (Chat 3). Nenhum segredo de Edge/ChatGPT/cookie ou certificado. Não declarar implementação completa apenas pela presença de interface. No fim cada agente deve atualizar seu relatório com paths, comandos, test results, crash/restart e handoff exato para central.

### CHAT 1 — P0 MCPB lifecycle real

Implementar **2–3 fatias completas testadas**, priorizando: isolamento/ownership e reconciliação de Docker após crash sem apagar processos de terceiros (contrato para `mcpb_sandbox.py`, não editar arquivo reservado); MCP HTTP Streamable/session/health supervisionado com host-approved endpoint, sem SSRF/retry de POST incerto e com durable fence; OAuth2 Authorization Code + PKCE + token broker seguro (não armazenar secrets em logs nem fixture de conta). Depois update/rollback/uninstall com estado crash-safe e tests. Não falsear refresh remoto da conta; indicar separadamente `publication_snapshot` local e status desconhecido do ChatGPT. Atualizar `docs/SENTRA_COS_AGENT_1_2026-10-10.md`.

### CHAT 2 — P0 Prova Web / fail-closed / ActionConsent

Priorizar **prova de request MCP <-> message metadata com navegador real autorizado** e testes para troca de aba/perfil/conta e pending human approval sem reenvio, sem ler cookie; origin/account/model/effort/Automatic sem inferência. Ligar `require_exact_message` ao ponto certo de autorização de tools pelo contrato, propondo patch exato para fachadas reservadas; avançar consentimento `read` vs `action` com operação durável e revisão owner-auth (somente host), e QuickJS WASM restrito se houver runtime auditado/pinado sem fallback Node/eval. Entregar E2E/fixtures claramente identificados. Atualizar `docs/SENTRA_COS_AGENT_2_2026-10-10.md`.

### CHAT 3 — P0 Segurança do outbox + Web handoff

**Prioridade absoluta:** proteger `ChatJob.prompt`/resumo em repouso no `native_bridge/job_store.py` com criptografia OS-backed, migração compatível fail-closed, sem valor sensível em logs, crash/restart, replay incerto não reenviado. Depois end-to-end de receipt Web: juntar callback autenticado da extensão ao outbox, garantia de 1 submit, handoff B mesmo Run/WorkItem/grant, prevenção de aba/conta trocada e streaming frames/cotas com collector e ACL. Evoluir `exec_command/write_stdin` somente dentro de ConPTY existente com ownership real, sem shell paralelo; GC de kernel handle como etapa posterior. Reportar blocos dependentes de Chat 2/central. Atualizar `docs/SENTRA_COS_AGENT_3_2026-10-10.md`.

### COORDENADOR

Consumir APIs entregues por `MCPHttpRegistry`, `ActionConsentService`, `WebContinuation` e `WebHistoryStore` em fachadas centrais com autenticação humana e revisão; não habilitar publicamente novas ações até E2E. Integrar Canvas/CLI, release e installer; testar segredos no outbox, isolamento das capabilities, operação durável e Docker. Não anunciar 34/34 enquanto houver serviços simulados.

## Protocolo de envio observado no Edge
- Chat 2: segunda mensagem publicada no MESMO URL /c/6aca28cf-617c-83ea-b866-dc4f85b40b7f, confirmada como turno de usuário renderizado via Windows UI Automation (sem reenvio).
- Chat 3: segunda mensagem publicada no MESMO URL /c/6aca2920-0150-83e8-9d06-ccaf180d7fd2, confirmada como turno de usuário renderizado (sem reenvio).
- Chat 1: janela /c/6aca2883-cba4-83e9-a371-cf7eef1cb959 AINDA tinha botão `Parar`/geração ativa no momento da segunda verificação; **não interrompi, não enviei mensagem, não dupliquei turno**, e a instrução de segunda rodada permanece neste arquivo pronta para envio após concluir o turno anterior. Não declarar 3/3 reenviados enquanto esse bloqueio durar.
- É necessária a verificação posterior de encerramento das respostas e dos relatórios para confirmar a segunda implementação; envio de prompt não é entrega de código.
