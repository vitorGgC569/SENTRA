# SENTRA — cinco revisões consultivas via Gemini 4 / Argon Médio

Data: 14/10/2026. Origem: Edge, conta Gemini Pro com seletor Argon Médio visualmente observado antes da rodada. O modelo exato não é atestado criptograficamente por turno no relay.

ESC OPO: O Gemini recebeu somente excertos do SENTRA e de projetos third_party; não teve acesso direto ao checkout ou permissão para editar código, executar comandos ou chamar ferramentas. Respostas abaixo são sugestões para validação, não auditoria conclusiva.

## Conversas e recibos

| Frente | Conversa na conta Pro | Resposta |
|---|---|---:|
| Orquestração e execução durável | [Abrir no Gemini](https://gemini.google.com/u/7/app/1f31fed302d6360e) | 14,838 caracteres |
| Segurança, autorização e governança | [Abrir no Gemini](https://gemini.google.com/u/7/app/9a08b6662396382c) | 17,423 caracteres |
| VM Windows e comandos guest | [Abrir no Gemini](https://gemini.google.com/u/7/app/b02a80e349b1a68b) | 14,915 caracteres |
| Federação entre usuários e peers | [Abrir no Gemini](https://gemini.google.com/u/7/app/32faac1b27fabe37) | 10,960 caracteres |
| Produto, instalador, observabilidade e UX | [Abrir no Gemini](https://gemini.google.com/u/7/app/8890817479af0eeb) | 14,672 caracteres |

As cinco URLs são da conta /u/7 e foram verificadas com CHAT_PEEK ready=true, finished=true, assistant_count=1. As primeiras três foram recuperadas do navegador quando os jobs expiraram na fase de leitura, SEM REENVIO. Federation e produto tiveram recibos CHAT_SEND e coleta CHAT_PEEK confirmados.

## Triagem preliminar para o SENTRA (não implementada pelo Gemini)

1. Fronteiras de efeitos e recibos: avaliar a vinculação de nonces a WorkItem, Dot e entrega reservada; auditar UNCERTAIN e terminal_lost antes de refatorar. Confirmar eventuais lacunas em execução física.
2. Isolamento de execução: comparar higiene de ambiente do sidecar com os runners de CLI e VM; evitar herança de segredos sem interromper os modelos necessários.
3. Governança/Federation: estudar ABAC/ReBAC, pinagem de identidade e admissão entre peers. Comparar NATS JetStream com o transporte existente sem expor peers nem retirar fencing/recibos.
4. Windows guest: explorar pywinauto somente após comprovar Windows, Guest Additions e guest.run; priorizar VDI íntegro e reconciliação de entradas incertas.
5. Produto: avaliar Grype/SBOM e proveniência no instalador, OpenTelemetry sem prompts/tokens, testes E2E e XYFlow opcional para visualização dos Dots.

Não incorporar automaticamente Temporal, LangGraph, OPA/OpenFGA, NATS, frameworks de UI ou automação de desktop. Toda hipótese precisa de análise de código integral, teste e validação do custo/risco.

## Respostas integrais, sem edição

### Orquestração e execução durável

Conversa: https://gemini.google.com/u/7/app/1f31fed302d6360e
Registro local: .tmp/gemini_argon_medio_recovered_responses/01_orchestration.json

O Gemini disse
Parecer Técnico Consultivo — Revisão de Orquestração e Execução Durável (SENTRA)

Escopo e Limitações da Análise: Este parecer baseia-se exclusivamente nos excertos fornecidos. O arquivo sentra_remote/orchestrator.py encontra-se ausente/não elegível nos trechos disponibilizados, e os demais módulos (dot_tool_receipts.py, effect_boundary.py, owned_process.py, store.py) são conhecidos apenas pelas suas assinaturas de importação e chamadas superficiais. Nenhuma ferramenta externa ou execução foi acionada.

1. Cinco Oportunidades Concretas Priorizadas
Prioridade 1: Fortalecimento da Entropia e Vinculação Contextual do Nonce de Inferência

Evidência nos excertos: Em sentra_canvas/dot_tool_runner.py:0008-0010 e 0026-0028, o módulo propõe distinguir inferência genuína do eco de terminal/PTY usando um desafio nonce (generate_nonce), mas implementa apenas uuid.uuid4().hex[:12] (48 bits de entropia, via gerador pseudoaleatório padrão) sem vínculo com o dot_id, work_item ou reserve_delivery. Em contraste, sentra_canvas/shell_actor.py:0004 já importa o módulo secrets (CSPRNG).

Ganho: Previne colisões em cenários de alto paralelismo/fan-out de múltiplos Dots e impede que um eco parcial ou replay cruzado entre terminais falsifique um recibo de inferência (verifiable inference receipt), garantindo idempotência estrita por entrega reservada.

Custo / Risco: Custo de implementação muito baixo. Risco nulo para operações UNCERTAIN ou Grants, desde que o formato do token continue compatível com o parser de saída dos CLIs (sentra-cli, opencode, codex — sentra_canvas/dot_tool_runner.py:0004-0006).

Dependências: Depende apenas da biblioteca padrão (secrets, hashlib já importado em dot_tool_runner.py:0013) e do identificador da reserva gerada por dot_tool_receipts.reserve (sentra_canvas/shell_dot_canvas.py:0010).

Prioridade 2: Reconciliação Determinística de Estado UNCERTAIN e terminal_lost via Nonce antes de Reenvio

Evidência nos excertos: sentra_canvas/shell_dot_canvas.py:0010-0012 importa explicitamente a máquina de estados de recibos (reserve_delivery, delivery_sent, delivery_uncertain, tool_deliveries, delivery_terminal_lost) e ações como dot_canvas_task_submit, dot_canvas_task_cancel e dot_canvas_handoff (0016-0020).

Ganho: Em execuções paralelas ou quedas de ConPTY (delivery_terminal_lost), evita a reexecução cega de operações em estado UNCERTAIN. Ao exigir que o dot_tool_runner.py valide o recibo criptográfico/nonce na saída antes de transicionar de reserve/sent, o sistema pode congelar (freeze) a entrega como UNCERTAIN caso o processo morra após delivery_sent, exigindo resolução explícita (inspeção de artefatos/VDI ou confirmação de recibo) sem violar a regra de "não reenviar operações UNCERTAIN".

Custo / Risco: Custo médio. Risco de manter tarefas órfãs bloqueadas se não houver um fluxo claro de auditoria/resolução manual ou sondeio passivo (read-only) do workspace do Dot.

Dependências: Integração direta entre sentra_canvas/dot_tool_receipts.py (referenciado em shell_dot_canvas.py:0010-0012) e o construtor de recibos de sentra_canvas/dot_tool_runner.py:0001.

Prioridade 3: Padronização do Isolamento de Ambiente (Zero Autoridade Herdada) nos Runners de Ferramentas

Evidência nos excertos: Em sentra_canvas/collaboration.py:0001 e 0024-0028, o sidecar Hocuspocus aplica higienização rigorosa de os.environ (mantendo apenas PATH, SYSTEMROOT, TEMP, HOME, etc.) e encapsula o processo em TaskProcess (owned_process.py). Já em sentra_canvas/dot_tool_runner.py:0015-0018, observa-se a importação direta de os e subprocess sem a importação de TaskProcess ou de current_effect_context (sentra_canvas/shell_actor.py:0008).

Ganho: Garante que o fan-out de tarefas não-interativas (sentra-cli, opencode, codex em dot_tool_runner.py:0003-0006) cumpra a mesma invariante declarada em shell_dot_canvas.py:0001 ("No implicit provider authority") e collaboration.py:0001 ("no inherited authority environment"), evitando vazamento de tokens do host ou quebra de isolamento entre Dots durante execuções concorrentes.

Custo / Risco: Custo baixo. Risco moderado de quebrar CLIs externos (opencode, codex) caso dependam de variáveis de ambiente específicas de configuração local que precisem ser injetadas explicitamente via Grants do Dot em vez de herdadas do processo pai.

Dependências: sentra_canvas/owned_process.py (TaskProcess), sentra_runtime/effect_boundary.py (current_effect_context) e definição de política de variáveis permitidas por adapter (sentra_canvas/adapters.py).

Prioridade 4: Cobertura Completa de Estruturas e Prevenção de Vazamento Parcial em _redact_guest_secret

Evidência nos excertos: Em sentra_canvas/shell_actor.py:0014-0028, a função _redact_guest_secret trata str, dict, list e inicia o bloco para tuple na linha 0028. Contudo, quando value é um dict (0020-0025), ela remove completamente as chaves listadas em _GUEST_SECRET_KEYS (password, guest_password), mas não higieniza chaves de dicionário caso o próprio segredo apareça como chave, nem garante (no trecho visível) tratamento para tipos como set, frozenset, bytes ou objetos serializáveis em JSON (import json na linha 0003).

Ganho: Preserva a segurança de arquivos/VDI e credenciais de Guest VM em fluxos de paralelismo onde múltiplos Dots despacham resultados de turnos de shell simultaneamente (shell_actor.py:0001), impedindo que senhas de VDI vazem em logs, recibos ou projeções de tarefas.

Custo / Risco: Custo muito baixo. Risco mínimo (apenas garantir que a remoção de chaves em dicionários não quebre contratos de schema que esperem a chave presente com valor None ou "[REDACTED]").

Dependências: Nenhuma dependência externa; restrito a sentra_canvas/shell_actor.py.

Prioridade 5: Controle de Concorrência e Coordenação de Fan-out por canvas_root

Evidência nos excertos: sentra_canvas/shell_dot_canvas.py:0005 importa threading e define ações de grafo e execução (dot_canvas_link, dot_canvas_handoff, dot_canvas_task_submit, dot_canvas_task_cancel em 0016-0020), além da resolução de raiz em canvas_root(dot) (0026-0027).

Ganho: Ao estruturar o fan-out e paralelismo em torno de canvas_root(dot) (em conjunto com o current_effect_context de shell_actor.py:0008), é possível aplicar limites de execução concorrente por árvore de Dots (e não globalmente bloqueante), garantindo que o cancelamento (dot_canvas_task_cancel) ou handoff respeite as fronteiras de Grants de cada Dot individual e mantenha o isolamento de recursos de VDI/ConPTY.

Custo / Risco: Custo médio. Risco de deadlock se locks de threading (shell_dot_canvas.py:0005) forem adquiridos fora de ordem hierárquica durante operações de dot_canvas_link ou dot_canvas_handoff.

Dependências: sentra_canvas/shell_dot_canvas.py, sentra_canvas/shell_requests.py (ShellHostRequests) e sentra_canvas/store.py (Denied).

2. Possíveis Duplicações com third_party

Com base na comparação entre os mecanismos nativos do SENTRA e os repositórios presentes em third_party/:

Durabilidade de Execução, Recibos e Estado UNCERTAIN vs. Temporal (third_party/temporal):

Conflito/Sobreposição: O Temporal (third_party/temporal/README.md:0003, third_party/temporal/chasm/archetype.go:0001-0007) é uma plataforma completa de execução durável em Go. No entanto, o SENTRA já possui sua própria semântica fina de durabilidade e confirmação de efeitos em Python via dot_tool_receipts (reserve, sent, uncertain, deliveries, terminal_lost em shell_dot_canvas.py:0010-0012) e effect_boundary (shell_actor.py:0008).

Grafo de Agentes, Handoff e Estado vs. LangGraph (third_party/langgraph):

Conflito/Sobreposição: O LangGraph (third_party/langgraph/README.md:0012) gerencia orquestração de agentes com estado em grafos. O SENTRA já implementa sua própria topologia espacial e de execução baseada em Dots (canvas_root, dot_canvas_link, dot_canvas_handoff, dot_canvas_task_submit em shell_dot_canvas.py:0016-0027).

Runners de Agentes de Código e Terminais vs. OpenHands SDK (third_party/openhands-agent-sdk):

Conflito/Sobreposição: O OpenHands (third_party/openhands-agent-sdk/README.md:0005) fornece abstrações de execução de agentes de software. O SENTRA já possui runners dedicados e verificáveis por nonce em sentra_canvas/dot_tool_runner.py:0001-0010 e gerenciamento de ConPTY por Dot em sentra_canvas/shell_dot_canvas.py:0001.

Orquestração de Fluxos/Automações vs. Activepieces (third_party/activepieces):

Conflito/Sobreposição: Activepieces (third_party/activepieces/README.md:0009) é um motor de automação em TypeScript/Node, que sobrepõe-se conceitualmente ao despacho de ferramentas e ShellHostRequests (shell_dot_canvas.py:0013), mas com modelo de permissões incompatível com Grants e Denied (shell_dot_canvas.py:0014, shell_actor.py:0009).

Mensageria/Transporte Distribuído vs. NATS Server (third_party/nats-server):

Conflito/Sobreposição: O NATS (third_party/nats-server/README.md:0005, main.go:0001) oferece pub/sub e filas em Go. Para sincronização colaborativa em tempo real, o SENTRA já gerencia um sidecar dedicado Node.js/Hocuspocus (sentra_canvas/collaboration.py:0016-0028).

3. O Que NÃO Integrar (e Justificativa Técnica)

NÃO integrar o motor do Temporal (third_party/temporal) para gerenciar WorkItems ou recibos de ferramentas:

Motivo: A política de retry automático padrão de workflows/activities do Temporal entra em conflito direto com a invariante do SENTRA de preservar operações UNCERTAIN sem reenviar (delivery_uncertain / delivery_terminal_lost em shell_dot_canvas.py:0011-0012). Além disso, introduziria um cluster Go pesado (archetype.go) que contorna o current_effect_context (shell_actor.py:0008).

NÃO substituir o fluxo de Dots/Handoff pelo LangGraph (third_party/langgraph):

Motivo: O modelo de estado do LangGraph assume autoridade implícita de execução entre nós do grafo, o que violaria a diretriz "No implicit provider authority" (shell_dot_canvas.py:0001), o modelo de Grants/Denied (store.py) e o isolamento estrito de VDI/arquivos por Dot.

NÃO adotar o runtime do OpenHands SDK (third_party/openhands-agent-sdk) no lugar de dot_tool_runner.py:

Motivo: O setup.py local (third_party/openhands-agent-sdk/setup.py:0004) é apenas um stub vazio (version="0.0.0", packages=[]), e o SDK completo não implementa o protocolo de desafio nonce criptográfico (dot_tool_runner.py:0008-0010) nem a contabilidade de recibos (dot_tool_receipts).

NÃO integrar Activepieces (third_party/activepieces) nem NATS (third_party/nats-server) no ciclo de vida do Canvas:

Motivo: Aumentam drasticamente a superfície de ataque e o número de processos sidecar (além do Hocuspocus já estritamente contido em collaboration.py:0016-0028), criando canais laterais fora da fronteira de auditoria de Grants e _redact_guest_secret (shell_actor.py:0014).

NÃO presumir ou acoplar código a sentra_remote/orchestrator.py:

Motivo: Como o arquivo consta como [arquivo ausente/não elegível], qualquer tentativa de acoplamento cego às suas interfaces internas introduziria regressões não verificáveis.

4. Três Testes de Aceitação Reais e Reproduzíveis

Os testes abaixo verificam as invariantes exigidas (WorkItems, Grants, recibos, UNCERTAIN sem reenvio, proteção de VDI e isolamento por Dot) apoiando-se apenas nos módulos evidenciados nos excertos:

Teste de Aceitação 1: Preservação do Estado UNCERTAIN e Proibição de Reenvio em Queda de ConPTY/Runner

Alvo: sentra_canvas/shell_dot_canvas.py (reserve_delivery, delivery_sent, delivery_uncertain, delivery_terminal_lost, dot_canvas_task_submit) e sentra_canvas/dot_tool_runner.py.

Cenário (Passos Reproduzíveis):

Instanciar um Dot válido e submeter uma tarefa via dot_canvas_task_submit utilizando uma das ferramentas de TOOLS (ex.: codex ou sentra-cli).

Confirmar a criação do registro em reserve_delivery e a transição para delivery_sent com um nonce gerado por generate_nonce (dot_tool_runner.py:0026).

Simular a perda abrupta do terminal/processo (delivery_terminal_lost) antes do retorno do nonce transformado (recibo de inferência).

Acionar uma tentativa de reprocessamento/retomada da mesma tarefa ou dot_canvas_handoff.

Critério de Aceite:

A entrega em tool_deliveries deve transicionar e permanecer em estado delivery_uncertain (ou terminal_lost vinculado).

O runner não deve invocar novamente o subprocesso (subprocess em dot_tool_runner.py:0018) para a mesma entrega reservada.

Nenhuma mutação duplicada deve ocorrer no workspace do Dot.

Teste de Aceitação 2: Isolamento de Autoridade, Grants e Sanitização de Segredos de VDI em Fan-out Paralelo

Alvo: sentra_canvas/shell_actor.py (_redact_guest_secret, current_effect_context, Denied), sentra_canvas/shell_dot_canvas.py (canvas_root, Denied) e sentra_canvas/collaboration.py (CollaborationProcess).

Cenário (Passos Reproduzíveis):

Criar dois Dots distintos (Dot_A e Dot_B) sob o mesmo canvas_root(dot) (shell_dot_canvas.py:0026), atribuindo um Grant de execução e um segredo de VDI (guest_password) exclusivamente ao Dot_A.

Disparar em paralelo (usando threading como em shell_dot_canvas.py:0005) uma ação dot_canvas_task_submit no Dot_A e uma tentativa de acesso/handoff não autorizado a partir do Dot_B.

No retorno do despacho de Dot_A, injetar o valor da senha de VM tanto em chaves explícitas ({"password": "secret_vm_123", "guest_password": "secret_vm_123"}) quanto embutido em strings dentro de listas, tuplas e dicionários aninhados.

Critério de Aceite:

A operação originada em Dot_B sem Grant válido deve levantar/retornar Denied (shell_dot_canvas.py:0014, shell_actor.py:0009), sem afetar a execução em andamento no Dot_A.

A saída processada por _redact_guest_secret (shell_actor.py:0014-0028) não deve conter a substring "secret_vm_123" em nenhum nível da estrutura (incluindo tuplas e strings internas) nem manter as chaves _GUEST_SECRET_KEYS.

As variáveis de ambiente do processo filho não devem conter credenciais do processo host fora da allowlist definida (collaboration.py:0024-0026).

Teste de Aceitação 3: Anti-Spoofing de Recibo de Inferência contra Eco de Terminal (PTY Echo)

Alvo: sentra_canvas/dot_tool_runner.py (0008-0010, 0026-0028) e sentra_canvas/shell_dot_canvas.py (0010-0012).

Cenário (Passos Reproduzíveis):

Invocar o runner não-interativo (dot_tool_runner.py) para um comando de ferramenta (sentra-cli, opencode ou codex).

Configurar um processo simulado (mock/stub de CLI) que apenas ecoa no stdout exatamente o prompt de entrada (incluindo o NONCE_<hex> bruto gerado por generate_nonce na linha 0028), sem realizar a transformação/desafio esperado pela inferência real do modelo.

Critério de Aceite:

O construtor de recibos de dot_tool_runner.py deve rejeitar o eco bruto como prova de inferência válida.

Nenhum recibo de conclusão de inferência verificável deve ser emitido como bem-sucedido apenas pela presença literal da string de entrada no eco do PTY.

---

### Segurança, autorização e governança

Conversa: https://gemini.google.com/u/7/app/9a08b6662396382c
Registro local: .tmp/gemini_argon_medio_recovered_responses/02_security.json

O Gemini disse

Este parecer técnico avalia exclusivamente os excertos fornecidos do projeto SENTRA e dos repositórios em third_party, mantendo estrita conformidade com a arquitetura de governança central, preservação de WorkItems, Grants, recibos, semântica UNCERTAIN sem reenvio automático, arquivos/VDI e isolamento por Dot.

1. Cinco Oportunidades Concretas Priorizadas
Prioridade 1: Enriquecimento ABAC/ReBAC na Autorização Secundária (OperationAccess)

Evidência nos excertos: Em sentra_runtime/access.py (linhas 0018–0028), a classe OperationAccess modela o escopo com atributos planos (principal_id, action, operation_id, machine_id, owner_principal_id, work_item_id, capability_id), mas não explicita o vínculo com o contexto de isolamento espacial (workspace_id, space_id, conversation_id ou Dot) nem o estado de aprovação humana, que aparecem fragmentados em sentra_executors/input_control.py (linhas 0024–0026) e sentra_canvas/shell_permissions.py (linha 0014).

Recomendação: Estender o contrato de validação em OperationAccess (ou o payload avaliado pelo AuthorizationService citado na linha 0005 de sentra_runtime/access.py) para exigir atributos de isolamento por Dot/workspace_id e vínculo explícito de epoch/fencing antes de autorizar leitura ou controle em rotas HTTP/MCP/Web.

Ganho: Garante least-privilege estrito e combina ABAC (atributos da operação e máquina) com ReBAC (relação principal_id ↔ owner_principal_id ↔ work_item_id ↔ Dot), impedindo cross-workspace/cross-Dot inspection nas bordas dos gateways.

Custo / Risco: Baixo custo de refatoração em estruturas de dados imutáveis (@dataclass(frozen=True, slots=True)). Risco de quebrar chamadas de gateway que ainda não propaguem o identificador do Dot/workspace; mitigável com validação deny-by-default (linha 0001).

Dependências: sentra_runtime/access.py, sentra_runtime/contracts.py (não visível nos excertos, apenas importado na linha 0014) e AuthorizationService.

Prioridade 2: Validação de Esquema e Transição Segura em AccessStore (Confirmação Humana)

Evidência nos excertos: Em sentra_canvas/shell_access.py (linhas 0019–0028), AccessStore persiste perfis e requisições de acesso em SQLite (shell_access_profiles e shell_access_requests) usando serialização genérica (body TEXT via _encode/_decode), retornando um dicionário padrão {'mode': 'ask', 'scope': 'workspace', 'approval': 'ask'} (linha 0026) quando ausente.

Recomendação: Implementar validação estrita de esquema e máquina de estados ao ler/gravar body em AccessStore.save (linha 0028) e nas ações ACCESS_ACTIONS (access_set, access_approve, access_reject na linha 0013), vinculando toda aprovação humana ao work_item_id, operation_id e a um hash imutável dos parâmetros da ferramenta (_request_snapshot visto em sentra_executors/central_integration.py, linha 0021).

Ganho: Evita escalonamento de privilégio por corrupção ou manipulação do JSON em body (ex.: mudar silenciosamente approval de ask para automático sem confirmação humana explícita) e impede ataques de Time-of-Check to Time-of-Use (TOCTOU) entre o pedido de aprovação no Shell e a admissão central.

Custo / Risco: Custo baixo. Risco de rejeitar registros legados malformados no banco local shell; deve falhar de forma fechada (fail-closed para 'mode': 'ask').

Dependências: sentra_canvas/shell_access.py, sentra_canvas/shell_requests.py (importado na linha 0011) e sentra_runtime/executor.py (_request_snapshot).

Prioridade 3: Unificação do Vínculo de Turno (ShellTurnPermissions) com Fencing de Execução

Evidência nos excertos: Em sentra_canvas/shell_permissions.py (linhas 0001, 0013–0028), ShellTurnPermissions gerencia controles explícitos do usuário sobre Grants centrais escopados a um turno (_FIELDS = {"space_id", "conversation_id", "work_item_id"}), validando o espaço via self.control.shell.get_space(sid, self.owner, project_id=project_id) (linha 0027) e abrindo conexão direta com o banco "shell" (linha 0028).

Recomendação: Garantir que toda concessão (turn_permission_grant) ou revogação (turn_permission_revoke) emita e valide tokens de fencing monotônicos compatíveis com CentralDurableIntentAuthority e DurableOperationGate (sentra_executors/central_integration.py, linhas 0018–0023), revogando imediatamente a posse de dispositivos/input caso o Grant do turno seja revogado.

Ganho: Alinha o controle de permissões de turno da UI/Canvas com o plano de controle central, garantindo que uma revogação pelo usuário interrompa futuras admissões sem corromper operações já em voo (preservando recibos e marcando estados interrompidos ou ambíguos como UNCERTAIN sem reexecução automática).

Custo / Risco: Custo médio. Risco de condição de corrida se a camada shell tentar manter estado paralelo aos Grants centrais; a tabela "shell" deve atuar apenas como projeção/vínculo de turno, nunca como autoridade substituta.

Dependências: sentra_canvas/shell_permissions.py, sentra_runtime/coordinator_admission.py (linha 0009) e sentra_executors/central_integration.py.

Prioridade 4: Endurecimento do Handoff Humano/Agente em VDI/Desktop (_HumanInputScope)

Evidência nos excertos: Em sentra_executors/input_control.py (linhas 0001–0004, 0020–0027), o docstring estabelece que a posse de input desktop é subordinada a Grants centrais de WorkItem, que o handoff humano/agente usa Compare-And-Swap (CAS) com expected_epoch: int (linha 0027) e que "Possession grants no capability". Nota-se também que control: object (linha 0022) é tipado de forma genérica e _HumanInputScope não possui slots=True (diferente de OperationAccess em sentra_runtime/access.py, linha 0018).

Recomendação: Substituir control: object por um protocolo/interface estrita que exija a verificação conjunta de BoundWorkItemPolicy (importado na linha 0015) + expected_epoch a cada evento de input em VDI/arquivos, além de adicionar slots=True em _HumanInputScope. Caso o humano assuma o controle (incremento de epoch via CAS), qualquer operação do agente em andamento naquele resource_id/machine_id deve transitar de forma determinística para falha segura ou UNCERTAIN (sem retry automático).

Ganho: Protege a superfície de VDI e manipulação de arquivos contra injeção de comandos concorrentes entre agente e operador humano, respeitando o isolamento por workspace_id/machine_id.

Custo / Risco: Custo baixo. Nenhum risco arquitetural se mantida a invariante de não armazenar dados de área de transferência ou teclado (linha 0004).

Dependências: sentra_executors/input_control.py e sentra_runtime/authority_bridge.py (BoundWorkItemPolicy).

Prioridade 5: Isolamento e Validação de Capacidades de Ferramentas antes do Registro Central

Evidência nos excertos: Em sentra_executors/central_integration.py (linhas 0003–0006, 0026–0028), o módulo integra executores como BrowserLabExecutor (declare_browser_lab_machine, BrowserReadBinding) ao ExecutorRegistry e DurableOperationGate, exigindo autoridade atômica (CentralDurableIntentAuthority e CentralEffectContext, linhas 0023–0024).

Recomendação: Inspirado nos conceitos de isolamento e validação de servidores/ferramentas MCP (como visto no propósito de third_party/toolhive/README.md, linha 0008, e isolamento de execução em third_party/gvisor/README.md, linhas 0010–0013), exigir que cada binding de ferramenta (ex.: BrowserReadBinding) declare estaticamente seu manifesto de capacidades mínimas (capability_id), efeitos colaterais esperados (leitura pura vs. mutação) e restrições de Dot antes de ser aceito pelo DurableOperationGate.

Ganho: Impede que um executor registrado com capacidade de leitura (BrowserReadBinding) execute efeitos fora do CentralEffectContext ou atravesse fronteiras de Dot/VDI, fortalecendo a validação de ferramentas MCP/internas.

Custo / Risco: Custo médio. Se uma ferramenta não declarar seu escopo de efeito, será bloqueada por padrão (Live dispatch DENIED, linha 0005).

Dependências: sentra_executors/central_integration.py, sentra_executors/browser_lab.py e sentra_runtime/effect_boundary.py.

2. Possíveis Duplicações e Sobreposições com third_party

Com base exclusivamente nos excertos e READMEs fornecidos, identificam-se as seguintes sobreposições funcionais entre o núcleo do SENTRA e os repositórios em third_party:

Componente third_party (Excerto)	Componente SENTRA Atual (Excerto)	Análise de Duplicação / Sobreposição
Open Policy Agent - OPA (third_party/opa/README.md: L0005; main.go: L0011)	AuthorizationService, PolicyDecision (sentra_runtime/access.py: L0005, L0014; input_control.py: L0016; shell_access.py: L0009)	Alta sobreposição conceitual (ABAC/Políticas). O OPA é um motor de políticas de propósito geral em Go (Rego). O SENTRA já possui um AuthorizationService durável em Python que emite PolicyDecision integrado nativamente com WorkItems e DurableOperationGate.
OpenFGA (third_party/openfga/README.md: L0004; assets/assets.go: L0006–0010)	ShellTurnPermissions, AccessStore, BoundWorkItemPolicy (shell_permissions.py: L0001–0028; shell_access.py: L0016–0021; central_integration.py: L0015)	Alta sobreposição em ReBAC e Persistência. O OpenFGA gerencia relações de autorização finas com migrações próprias para SQLite/Postgres/MySQL (assets.go: L0007–0009). O SENTRA já gerencia relações owner ↔ workspace ↔ space_id ↔ conversation_id ↔ work_item_id e Grants em seu próprio store SQLite.
Keycloak (third_party/keycloak/README.md: L0012; js/eslint.config.js: L0001–0011)	Identidade de owner e principal_id (sentra_runtime/access.py: L0022, L0026; shell_permissions.py: L0021)	Sobreposição de IAM Pesado. Keycloak é uma solução completa de IAM empresarial (Java/JS). O SENTRA opera com identidades de principal_id e owner já autenticadas e injetadas no runtime.
SPIRE (third_party/spire/README.md: L0001–0006)	Identidade de máquina e autoridade (machine_id em access.py: L0025; CentralDurableIntentAuthority em central_integration.py: L0023)	Sobreposição de Identidade de Workload. SPIRE fornece atestação de identidade SPIFFE para infraestrutura distribuída. No SENTRA, máquinas (Machine, machine_id) e executores são declarados e vinculados ao ControlPlaneService local/central.
ToolHive (third_party/toolhive/README.md: L0008)	sentra_mcp.services.control_plane e ExecutorRegistry (central_integration.py: L0014, L0020)	Sobreposição de Plataforma MCP. ToolHive é uma plataforma MCP externa; o SENTRA já possui seu próprio sentra_mcp (ControlPlaneService) com garantias específicas de recibos, Grants e admissão durável.
gVisor (third_party/gvisor/README.md: L0010–0013; runsc/main.go: L0001)	Isolamento de executores / VDI / BrowserLab (central_integration.py: L0026–0027)	Complementar (baixo risco de duplicação lógica, mas alto custo operacional). gVisor (runsc) atua no nível de kernel de aplicação para containers Linux, enquanto o código Python exibido atua na camada de coordenação lógica, Grants e fencing.
3. O Que NÃO Integrar (e Riscos de Integração)

Para proteger as invariantes do SENTRA (WorkItems, Grants, recibos, não-reenvio de operações UNCERTAIN, VDI e isolamento por Dot), NÃO devem ser realizadas as seguintes integrações:

NÃO substituir o AuthorizationService ou o store de Grants pelo OpenFGA ou OPA como autoridade primária externa (third_party/openfga, third_party/opa):

Risco: Como documentado em sentra_executors/central_integration.py (linhas 0003–0006), o despacho ao vivo exige autoridade atômica de intenção completa e fencing fornecida pelo coordenador (CentralDurableIntentAuthority e DurableOperationGate). Externalizar a decisão de Grants para um processo separado em Go (OPA/OpenFGA) com seu próprio banco SQLite/Postgres (third_party/openfga/assets/assets.go, linhas 0007–0009) quebraria a atomicidade transacional entre a verificação do Grant, a emissão do recibo e a admissão durável, criando janelas onde uma operação falha após o efeito lateral sem registro consistente de estado UNCERTAIN.

NÃO embutir o Keycloak (third_party/keycloak) ou SPIRE (third_party/spire) no fluxo crítico de execução de turnos ou handoff de VDI:

Risco: Introduzir dependências pesadas de rede/JVM/infraestrutura no caminho crítico de ShellTurnPermissions (sentra_canvas/shell_permissions.py) ou _HumanInputScope (sentra_executors/input_control.py) adicionaria latência e pontos de falha em operações sensíveis a epoch (CAS fencing), além de complexidade desnecessária para o isolamento por Dot.

NÃO delegar o ciclo de vida de ferramentas MCP ao ToolHive (third_party/toolhive) contornando o DurableOperationGate:

Risco: Ferramentas executadas fora do DurableOperationGate e do CentralEffectContext (sentra_executors/central_integration.py, linhas 0018, 0024) podem realizar retries automáticos ocultos em caso de timeout de rede, violando diretamente a regra de preservar operações UNCERTAIN sem reenviar e executando ações sem recibos ou Grants válidos.

NÃO expor métodos internos do ExecutorRegistry em rotas públicas ou nos adaptadores do Canvas (sentra_runtime/access.py, linhas 0003–0004):

Risco: Violar a fronteira explícita de sentra_runtime/access.py permitiria que clientes web/MCP invocassem executores diretamente, ignorando OperationAccess, BoundWorkItemPolicy e o isolamento por Dot.

4. Três Testes de Aceitação Reais e Reproduzíveis

Os cenários abaixo validam diretamente os contratos visíveis nos excertos fornecidos, podendo ser implementados na suíte de testes Python do repositório sem dependências externas:

Teste 1: Negação por Padrão e Isolamento Cross-Owner / Cross-WorkItem em OperationAccess

Alvo: sentra_runtime/access.py (OperationAccess, linhas 0018–0028) e integração com AuthorizationService / ExecutorRegistry (linhas 0003–0005, 0014–0015).

Pré-condição: Uma operação ativa registrada sob owner_principal_id="user_A", work_item_id="wi_100", machine_id="mach_vdi_1" e associada ao Dot/workspace ws_A.

Passos Reproduzíveis:

Instanciar OperationAccess onde principal_id="user_B" (ou um agente operando em um work_item_id="wi_200" pertencente a outro Dot), tentando executar action="control" ou action="read" sobre operation_id de "wi_100".

Submeter a requisição ao wrapper de autorização secundária de sentra_runtime/access.py.

Resultado Esperado (Critério de Aceite):

A chamada deve levantar AuthorizationRequired (ou retornar PolicyDecision negada) antes de invocar qualquer método interno de ExecutorRegistry.

Nenhum estado da operação original (wi_100), recibo ou sessão VDI (mach_vdi_1) deve ser alterado.

Teste 2: Prevenção de Execução Concorrente via CAS Epoch no Handoff Humano/Agente (_HumanInputScope) e Preservação de UNCERTAIN

Alvo: sentra_executors/input_control.py (_HumanInputScope, linhas 0020–0027) e sentra_executors/central_integration.py (DurableOperationGate, CentralDurableIntentAuthority, linhas 0018, 0023).

Pré-condição: Um WorkItem possui um Grant ativo para controle de desktop na máquina machine_id="vdi_01", resource_id="desktop_input", com expected_epoch=5 em _HumanInputScope.

Passos Reproduzíveis:

Simular a intervenção física do usuário humano assumindo o mouse/teclado no VDI, incrementando atomicamente (CAS) o epoch do recurso para 6.

Tentar despachar uma OperationRequest do agente que ainda carrega _HumanInputScope(..., expected_epoch=5) através do DurableOperationGate.

Simular uma segunda operação que já havia cruzado a fronteira de efeito (CentralEffectContext, linha 0024) exatamente no instante do handoff para epoch=6 e cujo retorno do executor falhou por interrupção de posse.

Resultado Esperado (Critério de Aceite):

A operação do passo 2 (pré-despacho com expected_epoch=5 obsoleto) é rejeitada imediatamente com AuthorizationRequired, sem emitir efeito no VDI e sem gravar conteúdo de teclado/clipboard (conforme linha 0004 de input_control.py).

A operação em voo do passo 3 tem seu recibo durável registrado com status UNCERTAIN e não é reenviada automaticamente pelo runtime.

Teste 3: Escopo Estrito de Permissão de Turno (ShellTurnPermissions) e Revogação de Grant no Meio do Turno

Alvo: sentra_canvas/shell_permissions.py (ShellTurnPermissions._scope e TURN_PERMISSION_ACTIONS, linhas 0013–0028) e sentra_canvas/shell_access.py (AccessStore.profile, linhas 0023–0026).

Pré-condição: Conversa conversation_id="conv_1" no espaço space_id="space_A" (projeto/Dot "proj_1") sem perfil customizado salvo em shell_access_profiles.

Passos Reproduzíveis:

Consultar AccessStore.profile("conv_1") e verificar que o fallback padrão é estritamente {'mode': 'ask', 'scope': 'workspace', 'approval': 'ask'} (linha 0026 de shell_access.py).

Conceder uma permissão de turno via turn_permission_grant vinculada a {"space_id": "space_A", "conversation_id": "conv_1", "work_item_id": "wi_55"}.

Tentar reutilizar esse mesmo Grant a partir de outra conversa ("conv_2") ou outro espaço/Dot ("space_B") chamando _scope("proj_1", {"space_id": "space_B", "conversation_id": "conv_1", "work_item_id": "wi_55"}).

Executar turn_permission_revoke para "wi_55" e tentar admitir uma nova chamada de ferramenta (BrowserLabExecutor em central_integration.py, linha 0027) sob "wi_55".

Resultado Esperado (Critério de Aceite):

No passo 3, a verificação de escopo falha com Denied (shell_permissions.py, linha 0011), impedindo vazamento de Grant entre Dots/espaços ou conversas.

No passo 4, após turn_permission_revoke, a nova admissão central no DurableOperationGate é negada por falta de Grant ativo, mantendo intactos os recibos das operações que já haviam sido concluídas anteriormente no mesmo WorkItem.

---

### VM Windows e comandos guest

Conversa: https://gemini.google.com/u/7/app/b02a80e349b1a68b
Registro local: .tmp/gemini_argon_medio_recovered_responses/03_windows_vm.json

O Gemini disse

Avaliação técnica consultiva do projeto SENTRA, baseada estritamente nos excertos fornecidos. Nenhum arquivo adicional foi lido ou modificado, e nenhuma ferramenta foi executada.

1. Oportunidades Concretas e Priorizadas
Prioridade 1: Automação semântica no Guest com pywinauto para substituir input.key/input.mouse cegos

Evidência nos excertos: sentra_executors/virtualbox_vm.py (linhas 0020–0028) define vm:input (input.key, input.mouse, input.bios_dvd) e vm:guest (guest.run, installation.verify, project.import), operando sob effect_checkpoint (linha 0018). Em third_party/pywinauto/setup.py (linhas 0001–0008), há uma biblioteca madura de automação GUI Windows sob licença permissiva.

Proposta: Em vez de depender exclusivamente de coordenadas de mouse ou eventos brutos de teclado (vm:input) após a instalação do SO, invocar scripts estruturados via guest.run (vm:guest) que utilizem pywinauto dentro do guest Windows para inspecionar a árvore de controles da UI antes de agir.

Ganho: Reduz drasticamente falhas por variação de resolução/foco e evita que ações de interface caiam no estado uncertain_requires_reconciliation (sentra_canvas/shell_dot_vm.py, linha 0026) por cliques perdidos.

Custo/Risco: Baixo custo de licenciamento (BSD). O risco é introduzir dependências no guest, violando a diretriz "No host desktop capture, paid extension, dependency installation or OS download" (virtualbox_vm.py, linha 0003). Para mitigar, o pywinauto deve fazer parte da imagem/ISO local previamente selecionada pelo owner (shell_dot_vm.py, linha 0003) ou ser injetado de forma portátil via project.import sem downloads externos.

Dependências e Invariantes: Mantém o GuardedExecutor (virtualbox_vm.py, linha 0017), preserva BoundWorkItemPolicy (shell_dot_vm.py, linha 0017) e garante que falhas de pré-condição na árvore GUI abortem antes do effect_checkpoint, evitando operações UNCERTAIN desnecessárias.

Prioridade 2: Endurecimento de verificação TOCTOU e integridade estrutural em inspect_vdi

Evidência nos excertos: sentra_executors/virtualbox_installation.py (linhas 0018–0028) lê os primeiros 512 bytes do arquivo VDI, captura before = os.fstat(source.fileno()) (linha 0021) e desempacota header_size, image_type, blocks_offset, data_offset, capacity, block_size, count, allocated e ident (linhas 0025–0028). O excerto termina na linha 0028.

Proposta: Garantir (ou validar na continuação da função após a linha 0028) que:

image_type seja estritamente validado contra o valor de imagem dinâmica base (conforme prometido na docstring, linhas 0004–0005: "supports only a dynamic, non-differencing v1.1 base image").

Os invariantes aritméticos do cabeçalho (allocated <= count, blocks_offset >= header_size, data_offset >= blocks_offset + count * 4, capacity == expected_capacity e ident == expected_uuid) sejam verificados antes de aceitar a evidência.

Um segundo os.fstat(source.fileno()) ao final da leitura confirme que st_mtime_ns e st_size não mudaram em relação a before (linha 0021) enquanto a VM ou outro processo acessa o arquivo.

Ganho: Previne corrupção silenciosa de estado e condições de corrida (TOCTOU) durante installation.verify e installation.reconcile (virtualbox_vm.py, linhas 0022–0027), protegendo o isolamento de arquivos/VDI por Dot.

Custo/Risco: Custo computacional nulo (operações em memória e uma syscall fstat extra). Risco zero de quebrar contratos existentes.

Dependências: Nenhuma dependência externa; utiliza apenas os e struct já importados (virtualbox_installation.py, linhas 0010–0012).

Prioridade 3: Unificação de recibos e semântica UNCERTAIN entre ConPTY (shell_dot_canvas) e VM (shell_dot_vm)

Evidência nos excertos: sentra_canvas/shell_dot_canvas.py (linhas 0010–0012) dispõe de um módulo explícito de recibos de entrega (reserve_delivery, delivery_sent, delivery_uncertain, delivery_terminal_lost). Já sentra_canvas/shell_dot_vm.py (linha 0026) define estados protegidos de provisionamento (_PROTECTED_PROVISIONING = frozenset({'uncertain_requires_reconciliation', 'installation_launch_sent'})), e virtualbox_vm.py (linhas 0022–0023) expõe ações de reconciliação (installation.reconcile, project.import.reconcile).

Proposta: Alinhar o ciclo de vida de execução de dot_vm_execute e dot_vm_input (shell_dot_vm.py, linha 0025) ao mesmo contrato formal de recibos de dot_tool_receipts (reserve
→
→ sent / uncertain), vinculando cada transição ao OperationRequest e BoundWorkItemPolicy (shell_dot_vm.py, linhas 0017–0018).

Ganho: Garante por construção que nenhuma operação em estado uncertain_requires_reconciliation ou delivery_uncertain seja reenviada automaticamente sem passar por dot_vm_reconcile (shell_dot_vm.py, linha 0025), mantendo auditoria idêntica para ferramentas locais (ConPTY) e ações em VM.

Custo/Risco: Baixo custo de refatoração interna. Risco moderado caso a camada de persistência de recibos bloqueie leituras (DOT_VM_READS, linha 0024) — leituras como dot_vm_status e dot_vm_frame devem permanecer isentas de reserva de mutação.

Dependências: Depende de dot_tool_receipts e sentra_runtime.authority_bridge (shell_dot_vm.py, linha 0017).

Prioridade 4: Adaptação da metodologia de avaliação e trajectories do osworld-v2 (sem portar fcntl diretamente)

Evidência nos excertos: third_party/osworld-v2/lib_results_logger.py (linhas 0001–0012) implementa logging estruturado de resultados de tarefas para avaliação de agentes em sistemas operacionais, mas importa fcntl (linha 0010), que é exclusivo de sistemas POSIX/Unix e falha nativamente no Python para Windows.

Proposta: Aproveitar o esquema de dados de resultados e a estrutura de verificação pós-ação do osworld-v2 para enriquecer os testes de installation.verify e diagnostics (virtualbox_vm.py, linhas 0021–0023), substituindo o bloqueio fcntl por primitivas compatíveis com Windows (ou pelo próprio controle de concorrência do canvas._lock visto em shell_dot_computer.py, linha 0021).

Ganho: Fornece métricas padronizadas e reprodutíveis para auditar se os agentes operando via dot_vm_execute e dot_computer_action atingem o estado esperado no guest sem violar políticas.

Custo/Risco: Baixo custo se usado apenas como referência de esquema e harness de teste; alto risco de quebra em runtime no Windows se lib_results_logger.py for importado diretamente devido ao import fcntl (linha 0010).

Dependências: sentra_executors/virtualbox_vm.py e suíte de testes local.

2. Possíveis Duplicações com third_party
Componente no SENTRA	Componente em third_party	Análise de Sobreposição e Diferenças Arquiteturais


Controle de VM e Processo Guest




(virtualbox_vm.py linhas 0001–0023: VMs VirtualBox completas via COM, ISO local e VDI)



third_party/hcsshim




(README.md linha 0005, container.go linha 0003: interface Go para Windows HCS/HNS e GCS)

	Ambos gerenciam isolamento de computação e execução de processos em guest no Windows (guest.run vs GCS). Contudo, o SENTRA exige VMs persistentes por Dot baseadas em imagens locais e VDI (virtualbox_installation.py), enquanto hcsshim é escrito em Go e focado em containers Windows/Hyper-V efêmeros (Moby/Containerd).


Acesso a Desktop e Framebuffer




(virtualbox_vm.py linha 0001: COM framebuffer; shell_dot_computer.py linhas 0016–0025: DotComputerServices e viewers)

	third_party/guacamole-server e third_party/rustdesk (README.md linha 0002)	O SENTRA já possui transporte e sessão de visualização próprios com controle central de admissão (shell_dot_computer.py, linhas 0004–0005 e 0020: "Reuse the same provider tickets and transport as the existing panel"). guacamole-server e rustdesk duplicam a camada de transporte de desktop remoto, mas operam fora do modelo de Grants e BoundWorkItemPolicy do SENTRA.


Automação de Input no Guest




(virtualbox_vm.py linha 0023: input.key, input.mouse)



third_party/pywinauto




(setup.py linha 0001)

	virtualbox_vm.py injeta eventos físicos no nível do hipervisor; pywinauto automatiza aplicações Windows internamente no nível de APIs Win32/UI Automation. São complementares se o pywinauto for acionado via guest.run.


Orquestração de Ambientes de Agentes




(shell_dot_vm.py, shell_dot_canvas.py)



third_party/daytona




(README.md linha 0012, ecosystem.config.js linha 0009)

	Ambos orquestram ambientes para execução de código de IA (Run AI Code), mas o SENTRA faz isso com isolamento estrito por canvas_root_dot_id (shell_dot_canvas.py, linha 0026) e reservas duráveis no host, enquanto o Daytona é uma plataforma Node.js/cluster externa.
3. O que NÃO Integrar (e Justificativa)

NÃO integrar third_party/daytona (ecosystem.config.js, linhas 0001–0012):

Motivo Legal e Arquitetural: Licenciado sob AGPL-3.0 (linha 0003), o que impõe risco severo de contaminação de licença (copyleft de rede) ao núcleo proprietário/corporativo do SENTRA. Além disso, introduz uma pilha Node.js/PM2 em modo cluster (instances: 4, exec_mode: 'cluster', linhas 0010–0012) que conflita com a arquitetura Python e com o modelo de autoridade central sem identidade implícita (shell_dot_canvas.py, linha 0001).

NÃO integrar third_party/rustdesk no caminho de captura/execução (build.py, linhas 0001–0012):

Motivo de Segurança e Invariantes: O script build.py importa urllib.request (linha 0009) para baixar artefatos externos, e o cliente/servidor RustDesk realiza captura de tela do host e travessia de rede/NAT. Isso viola frontalmente os invariantes de virtualbox_vm.py (linha 0003: "No host desktop capture, paid extension, dependency installation or OS download") e contornaria a posse de input controlada em shell_dot_computer.py (linhas 0004–0005).

NÃO substituir o executor VirtualBox por third_party/hcsshim (container.go, linhas 0001–0012):

Motivo Técnico: Exigiria manter um runtime Go paralelo e quebraria os contratos de evidência de disco baseados em arquivos .vdi v1.1 (virtualbox_installation.py, linhas 0004–0005 e 0018–0028), além de invalidar o fluxo de instalação de ISO local e BIOS/DVD (virtualbox_vm.py, linhas 0001 e 0022–0023).

NÃO acoplar third_party/guacamole-server ao shell_dot_computer.py:

Motivo Arquitetural: DotComputerServices (shell_dot_computer.py, linhas 0020–0024) já reutiliza ShellMachineServices e os tickets de provedor existentes, e o framebuffer da VM já é obtido diretamente via COM real (virtualbox_vm.py, linha 0001). Adicionar um daemon C (guacd) aumentaria a superfície de ataque e dificultaria o filtro de chaves sensíveis (_VM_HIDDEN_KEYS em shell_dot_vm.py, linhas 0027–0028).

4. Três Testes de Aceitação Reais e Reprodutíveis
Teste 1: Invariante de Não-Reenvio em Operações UNCERTAIN e Reconciliação Obrigatória

Alvo: sentra_canvas/shell_dot_vm.py (linhas 0024–0026), sentra_canvas/shell_dot_canvas.py (linhas 0010–0012) e sentra_executors/virtualbox_vm.py (linhas 0018, 0022–0023).

Procedimento:

Provisionar um Dot com um WorkItem e Grant válidos vinculados via BoundWorkItemPolicy (shell_dot_vm.py, linha 0017).

Disparar dot_vm_execute com a ação installation.launch ou project.import e forçar uma interrupção controlada logo após o effect_checkpoint (virtualbox_vm.py, linha 0018), registrando o estado uncertain_requires_reconciliation (shell_dot_vm.py, linha 0026) / recibo delivery_uncertain (shell_dot_canvas.py, linha 0011).

Tentar reenviar a mesma chamada dot_vm_execute ou dot_vm_input com o mesmo OperationRequest antes de reconciliar.

Executar dot_vm_reconcile_status (leitura) e, em seguida, dot_vm_reconcile (installation.reconcile / project.import.reconcile).

Critério de Aceitação: No passo 3, o executor deve rejeitar a mutação (Denied) sem invocar o VirtualBox nem reexecutar o comando no guest. No passo 4, dot_vm_reconcile_status deve refletir o estado pendente sem efeitos colaterais, e dot_vm_reconcile deve inspecionar o estado real da VM/VDI, resolver a operação com recibo auditável e só então liberar novas mutações para o Dot.

Teste 2: Isolamento Cruzado por canvas_root_dot_id e Ocultação de Segredos (_VM_HIDDEN_KEYS)

Alvo: sentra_canvas/shell_dot_vm.py (linhas 0019–0028), sentra_canvas/shell_dot_canvas.py (linhas 0026–0027) e sentra_canvas/shell_dot_computer.py (linhas 0007, 0027–0028).

Procedimento:

Instanciar duas árvores de Dots independentes (Root_A com Child_A1, e Root_B com Child_B1), verificando que canvas_root(dot) (shell_dot_canvas.py, linha 0026) resolve cada filho para sua respectiva raiz.

Configurar uma VM em Root_A (dot_vm_configure) contendo metadados sensíveis (password, guest_password, marker, base_folder, work_items).

A partir do contexto de autoridade de Child_B1, invocar dot_vm_status, dot_vm_frame, dot_vm_handoff (shell_dot_vm.py, linhas 0024–0025) e DotComputerServices.dispatch (shell_dot_computer.py, linha 0027) apontando para o dot_id/space_id de Root_A, além de testar a passagem de parâmetros extras fora de {"dot_id", "space_id", "conversation_id", "request"} (linha 0028).

A partir de Child_A1 (autorizado na mesma raiz via dots_for_root), chamar todas as ações de DOT_VM_READS.

Critério de Aceitação: Todas as chamadas originadas de Child_B1 ou com parâmetros extras em dispatch devem falhar com Denied (ou erro de validação na linha 0028 de shell_dot_computer.py), sem vazar frames ou status. Nas respostas legítimas para Child_A1, nenhuma chave presente em _VM_HIDDEN_KEYS (shell_dot_vm.py, linhas 0027–0028) nem credenciais (emits_credentials: False, virtualbox_vm.py, linha 0028) podem aparecer no payload serializado.

Teste 3: Validação Estrita de Evidência Binária VDI (inspect_vdi) sem Montagem no Host

Alvo: sentra_executors/virtualbox_installation.py (linhas 0018–0028) e sentra_executors/virtualbox_vm.py (linhas 0026–0028: NEXT_AUTHORIZED_GUEST_STEP / installation.verify).

Procedimento:

Gerar em diretório temporário de teste quatro arquivos binários sintéticos de 512+ bytes:

Caso A (Válido): Assinatura 0xBEDA107F e versão 0x00010001 no offset 64 (linha 0023), tipo dinâmico v1.1, capacity no offset 368 igual a expected_capacity (linha 0027) e UUID little-endian nos bytes 392:408 igual a expected_uuid (linha 0028).

Caso B (Assinatura/Versão inválida): Alterar o inteiro no offset 64 para 0xBEDA107E ou versão para 0x00010002.

Caso C (Divergência de Identidade/Capacidade): Manter cabeçalho v1.1 válido, mas fornecer expected_uuid ou expected_capacity divergentes dos bytes 392:408 e 368:376.

Caso D (Truncado): Arquivo com 511 bytes.

Executar inspect_vdi(path, expected_uuid=..., expected_capacity=...) contra os quatro casos.

Critério de Aceitação: O Caso A deve concluir a leitura em modo somente-leitura ('rb', linha 0020) sem invocar utilitários de montagem do host, validando UUID e capacidade com exatidão. Os Casos B e D devem levantar ValueError('unsupported VDI signature or version') exatamente na guarda da linha 0023–0024. O Caso C deve rejeitar a imagem por divergência de UUID/capacidade sem tentar adivinhar metadados ("never guesses when metadata is unsupported", linha 0005).

---

### Federação entre usuários e peers

Conversa: https://gemini.google.com/u/7/app/32faac1b27fabe37
Registro local: .tmp/gemini_argon_medio_verified_results/final_04_federation.json

Avaliação consultiva baseada estritamente nos excertos fornecidos do projeto SENTRA e third_party.

1. Oportunidades Concretas Priorizadas
P1. Evoluir o transporte de protótipo loopback para P2P externo seguro ou NATS JetStream embutido

Evidências: sentra_canvas/peer_work_wire.py:0001-0028 define um protótipo restrito a sockets loopback (socketserver, sqlite3, struct), exigindo explicitamente mTLS pinado, IP allowlist e admissão no ControlPlane para redes externas (Hamachi/Radmin). Já third_party/nats-server/README.md:0005 disponibiliza um servidor de comunicações seguro e performático.

Ganho: Elimina a fragilidade de gerenciar framing binário (struct), reconexão manual, partições de rede e filas em SQLite customizado (peer_work_wire.py:0009, 0026-0028), habilitando transporte real entre máquinas mantendo a semântica de que ACK prova apenas ingestão durável no transporte (peer_work_wire.py:0004-0005).

Custo/Risco: Médio. Se optar por manter peer_work_wire.py, é preciso implementar mTLS, controle de backoff no reconnect e tratamento de estados UNCERTAIN sem reenvio automático cego. Se usar nats-server como transporte subjacente, o NATS deve atuar estritamente como dumb pipe autenticado: a criptografia de carga por workspace (AES-256-GCM) e assinatura Ed25519 por nó (peer_work_wire.py:0007-0008), bem como a barreira de admissão (peer_admission.py:0003-0006), jamais devem ser delegadas ao broker.

Dependências: sentra_canvas/peer_work_wire.py, sentra_canvas/peer_admission.py, sentra_federation/bind.py (shell_federation.py:0015) e opcionalmente third_party/nats-server.

P2. Unificar Identidade de Nó, Presença e Pining Criptográfico entre Descoberta e Transporte

Evidências: A identidade aparece fragmentada em três pontos nos excertos: InstallationIdentity (sentra_canvas/shell_federation.py:0017), PeerNodeIdentity (sentra_canvas/peer_directory.py:0028) e o signer Ed25519 pinado por node id (sentra_canvas/peer_work_wire.py:0008). Além disso, peer_directory.py:0008 importa hmac enquanto peer_work_wire.py:0008 exige Ed25519.

Ganho: Garante que o anúncio de presença em 239.255.55.37:37037 (peer_directory.py:0018-0019) use exatamente a mesma raiz de identidade criptográfica exigida pelo transporte e pelo Control Plane, evitando discrepâncias de chaves durante reconexões ou partições de LAN/VPN. Preserva a regra de não auto-habilitar conexões apenas por presença (peer_work_wire.py:0014).

Custo/Risco: Baixo. Requer padronizar os contratos de verificação de chave pública sem conceder autoridade automática de execução (peer_directory.py:0003-0004).

Dependências: sentra_canvas/peer_directory.py, sentra_canvas/peer_work_wire.py e sentra_federation/identity.py.

P3. Isolamento por Dot/Workspace e Reconexão Resiliente no Sidecar de Colaboração Local

Evidências: sentra_canvas/collaboration.py:0016-0028 inicia o processo central_sidecar.mjs via TaskProcess com um único secret: str e port: int por instância de CollaborationProcess, limpando variáveis de ambiente para evitar herança de autoridade (0001, 0024-0026).

Ganho: Como Hocuspocus (third_party/hocuspocus/README.md:0006) e Yjs (third_party/yjs/README.md:0006-0013) mantêm documentos CRDT em memória e sincronizam reconexões automaticamente, vincular a autenticação de cada sala/documento Yjs a um Grant específico do WorkItem e ao isolamento por Dot impede que um secret único do processo permita vazamento cruzado entre diferentes Dots ou workspaces locais após quedas e reconexões do WebSocket.

Custo/Risco: Baixo/Médio. Exige validar tokens/grants por sala no central_sidecar.mjs (não visível nos excertos) e garantir logs estruturados capturados pela queue/threading (collaboration.py:0007, 0011) sem expor segredos ou payloads de arquivos/VDI nos logs.

Dependências: sentra_canvas/collaboration.py, sentra_collab/central_sidecar.mjs e pacotes em third_party/hocuspocus / third_party/yjs.

P4. Contrato Estrito de Reconciliação para Estados UNCERTAIN e Auditoria entre Transporte e Admissão

Evidências: sentra_canvas/peer_admission.py:0003-0026 verifica WorkItem, principal, workspace, Capability (peer.task.accept) e DurableOperationGate (0021), enquanto shell_federation.py:0018 importa DurableStateConflict. O transporte mantém inbox/outbox em SQLite (peer_work_wire.py:0009).

Ganho: Quando ocorre particionamento de rede logo após o envio de um TASK_OFFER ou RESULT, antes do recebimento do ACK de ingestão (peer_work_wire.py:0003-0005), a operação entra em estado UNCERTAIN. Formalizar recibos idempotentes e consulta de estado via network_status (shell_federation.py:0021) permite reconciliar o outbox local com o DurableOperationGate remoto sem reenviar a operação e sem duplicar efeitos em arquivos/VDI.

Custo/Risco: Baixo. Baseia-se na infraestrutura existente de CentralDurableIntentAuthority (peer_admission.py:0017) e hashes determinísticos (hashlib em shell_federation.py:0010, peer_admission.py:0012, peer_work_wire.py:0020).

Dependências: sentra_canvas/peer_work_wire.py, sentra_canvas/peer_admission.py, sentra_canvas/shell_federation.py.

2. Possíveis Duplicações com third_party
Componente SENTRA (Excertos)	Equivalente em third_party	Análise de Sobreposição
sentra_collab/node_modules/@hocuspocus/server e sentra-collab-runtime.js (collaboration.py:0020-0023)	third_party/hocuspocus e third_party/yjs	Alta duplicação de dependências: collaboration.py:0021 exige npm ci na pasta sentra_collab, sugerindo que o código ou pacotes de @hocuspocus/server e yjs podem estar sendo baixados externamente ou duplicados em vez de consumir/buildar diretamente a partir das árvores já versionadas em third_party/hocuspocus (rolldown.config.js) e third_party/yjs.
Framing JSON e envelopes de tarefas/resultados (peer_work_wire.py:0008, peer_directory.py:0022-0025)	third_party/agent-client-protocol (README.md:0013) e third_party/mcp-typescript-sdk	Sobreposição parcial de esquemas: O ACP já define modelos tipados de envelopes JSON-RPC, versão de protocolo, requisições e notificações para agentes (README.md:0013), enquanto o SENTRA define serialização e estruturas próprias em Python.
Mensageria TCP/Socket (peer_work_wire.py:0025-0026) e presença UDP/Multicasting (peer_directory.py:0012-0019)	third_party/nats-server (README.md:0005, main.go)	Sobreposição de camada de transporte: A implementação manual de sockets, framing, retries e armazenamento intermediário de trânsito em peer_work_wire.py sobrepõe-se às capacidades nativas de transporte seguro, reconexão e persistência de streams do nats-server.
3. O Que NÃO Integrar

NÃO substituir o peer_admission.py ou o Control Plane pelo ACP (third_party/agent-client-protocol) ou MCP (third_party/mcp-typescript-sdk):

Justificativa: O ACP padroniza a comunicação direta entre editores de código e agentes autônomos (agent-client-protocol/README.md:0007). No SENTRA, o transporte de entrada nunca é uma autoridade e nunca despacha instruções remotas ou inicia modelos diretamente (peer_admission.py:0003-0006). Adotar o fluxo padrão do ACP quebraria o isolamento por Dot, a validação de BoundWorkItemPolicy (peer_admission.py:0016) e a exigência de Grant local.

NÃO usar CRDTs (third_party/yjs / third_party/hocuspocus) para sincronizar estados do Control Plane, WorkItems, Grants ou recibos:

Justificativa: O Yjs faz merge automático e sem conflitos de tipos compartilhados de forma P2P e agnóstica de rede (yjs/README.md:0008-0011). Contudo, Grants, WorkItems e transições do DurableOperationGate exigem autoridade central estrita (CentralDurableIntentAuthority, peer_admission.py:0017) e detecção explícita de conflito (DurableStateConflict, shell_federation.py:0018), jamais resolução eventual otimista. Yjs/Hocuspocus devem ficar restritos à colaboração de UI/documento no sidecar (collaboration.py).

NÃO usar auto-descoberta ou roteamento implícito do nats-server ou de presença (peer_directory.py) para conceder acesso a arquivos/VDI:

Justificativa: Violará as invariantes explícitas de peer_directory.py:0003-0004 e peer_work_wire.py:0011-0014 ("Never auto-enable based on presence alone").

4. Testes de Aceitação Reais e Reproduzíveis
Teste 1: Invariante de Leitura Passiva e Isolamento de Renderer (shell_federation.py)

Pré-condição: Instância do runtime inicializada sem identidade de federação criada e sem sockets de escuta ativos.

Ação: Invocar as ações network_home e network_status (NETWORK_READS, shell_federation.py:0021) passando no payload do renderer campos forjados de identity e Grant.

Resultado Esperado:

Nenhuma porta TCP/UDP (PEER_PORT=37037 ou loopback do PeerWorkWire) entra em estado LISTEN (shell_federation.py:0005).

Nenhuma InstallationIdentity ou Grant é criada ou persistida (shell_federation.py:0004-0005).

Quaisquer atributos de identidade ou Grant vindos do payload do renderer são ignorados ou rejeitados com Denied (shell_federation.py:0004, 0014).

Teste 2: Barreira de Admissão, Semântica de ACK e Proteção contra Replay (peer_work_wire.py & peer_admission.py)

Pré-condição: Dois nós pareados em loopback com chaves AES-256-GCM de workspace e signers Ed25519 pinados (peer_work_wire.py:0007-0008).

Ação:

Enviar um frame TASK_OFFER válido do Nó A para o Nó B.

Interromper a conexão antes do retorno ao Nó A (simulando partição e estado UNCERTAIN) e reconectar.

Reproduzir (replay) exatamente o mesmo pacote binário na porta do Nó B após reinicialização do serviço.

Enviar um TASK_OFFER de um principal sem a capability peer.task.accept (peer_admission.py:0026).

Resultado Esperado:

No passo 1, o ACK retornado pelo Nó B confirma apenas a gravação no SQLite inbox (peer_work_wire.py:0004-0009); nenhum modelo é iniciado e nenhuma alteração em arquivos/VDI ocorre (peer_admission.py:0005-0006).

No passo 2, o Nó A marca a operação como UNCERTAIN e não reenvia automaticamente um novo WorkItem.

No passo 3, o peer_work_wire rejeita o pacote duplicado via prevenção de replay persistente em SQLite (peer_work_wire.py:0009).

No passo 4, peer_admission.py nega a operação (PeerWireDenied / AuthorizationRequired, linhas 0022-0024) preservando o isolamento do Dot.

Teste 3: Sanitização de Ambiente e Ciclo de Vida do Sidecar (collaboration.py & peer_directory.py)

Pré-condição: Definir variáveis de ambiente sensíveis no processo pai (ex.: SENTRA_ROOT_KEY, AWS_SECRET_ACCESS_KEY, DOT_AUTHORITY_TOKEN) e iniciar CollaborationProcess (collaboration.py:0016-0028).

Ação:

Inspecionar o ambiente do processo filho central_sidecar.mjs (collaboration.py:0024-0028).

Enviar um payload de presença para canonical(value) com mais de 4096 bytes (peer_directory.py:0022-0025).

Resultado Esperado:

O processo Node.js contém exclusivamente o subconjunto permitido de variáveis (PATH, SYSTEMROOT, WINDIR, TEMP, TMP, HOME, USERPROFILE, LOCALAPPDATA, APPDATA), garantindo zero herança de autoridade (collaboration.py:0001, 0024-0026).

A função canonical() levanta ValueError("peer presence exceeds bound") imediatamente (peer_directory.py:0024).

---

### Produto, instalador, observabilidade e UX

Conversa: https://gemini.google.com/u/7/app/8890817479af0eeb
Registro local: .tmp/gemini_argon_medio_verified_results/final_05_product.json

Análise técnica restrita exclusivamente aos excertos fornecidos do projeto SENTRA e do diretório third_party, preservando integralmente WorkItems, Grants, recibos, a semântica de não reenvio para operações UNCERTAIN, arquivos/VDI, isolamento por Dot e o modo do modelo selecionado pelo usuário no navegador.

1. Oportunidades Concretas Priorizadas (1 a 5)
Prioridade 1: Segurança de Release e Varredura do Instalador no Build Windows com Grype

Evidências: scripts/commander/build_windows.py:0001-0028 (pipeline de empacotamento Windows em LOCAL_BUILD_ROOT, BUILD_STATUS_PATH e _source_fingerprint()) e third_party/grype/README.md:0005-0007 / third_party/grype/.make/main.go:0001-0012.

Diagnóstico: O script build_windows.py gera executáveis e o instalador autocontido calculando fingerprints de insumos (_source_fingerprint na linha 0027), mas não há evidência de verificação automatizada de vulnerabilidades (CVEs) sobre a árvore de artefatos estáticos antes da selagem do setup.

Proposta: Integrar a execução offline do scanner Grype (third_party/grype) como etapa de validação (gate fail-closed) sobre o filesystem de stage em LOCAL_BUILD_ROOT (build_windows.py:0016-0020), registrando o resumo no BUILD_STATUS_PATH (build_windows.py:0024).

Ganho: Bloqueia empacotamento de binários ou dependências de frontend/Python com vulnerabilidades conhecidas antes da distribuição do instalador, sem alterar o runtime de Dots, VDI ou WindowControls (sentra_canvas/native_app.py:0012-0023).

Custo/Risco: Baixo risco (execução apenas em tempo de build/release). Requer manutenção periódica do banco de vulnerabilidades local do Grype para manter o build determinístico e sem dependência de rede externa.

Dependências: Binário compilado a partir de third_party/grype e integração no fluxo de scripts/commander/build_windows.py.

Prioridade 2: Telemetria de Streaming Não-Intrusiva e Isolamento por Dot no Gateway

Evidências: sentra_model_gateway/gateway.py:0001-0028 (encaminhamento deliberado de bytes SSE sem coletar o turno nas linhas 0003-0005; uso de ThreadingHTTPServer, sqlite3, zstandard nas linhas 0020-0026) e third_party/opentelemetry-collector/client/client.go:0004-0011.

Diagnóstico: O gateway.py encaminha bytes SSE diretamente para que o cancelamento upstream e a ordenação de eventos permaneçam observáveis pelo Codex (gateway.py:0003-0005). Qualquer instrumentação de observabilidade que faça buffering do payload violaria essa garantia ou alteraria o modelo escolhido no navegador (já que o upstream detém o runtime de navegador e protocolo, gateway.py:0001).

Proposta: Instrumentar contadores passivos por chunk (TTFB, contagem de bytes, desconexão/cancelamento e metadados de tenancy/Dot inspirados no modelo de contexto de third_party/opentelemetry-collector/client/client.go:0004-0007) emitidos de forma assíncrona fora do caminho crítico do socket (http.client / socket em gateway.py:0012, 0019), preservando o passthrough exato de bytes SSE e o modelo definido no navegador.

Ganho: Visibilidade em tempo real de latência e quedas de stream por Dot sem introduzir jitter, sem inspecionar/acumular turnos completos e sem reenviar operações UNCERTAIN.

Custo/Risco: Médio. Se o coletor de telemetria bloquear a thread do ThreadingHTTPServer (gateway.py:0026), haverá degradação de throughput SSE. A emissão deve usar fila em memória com descarte rápido (non-blocking) ou gravação assíncrona comprimida (zstd, gateway.py:0024).

Dependências: sentra_model_gateway/gateway.py e esquema de metadados de tenancy alinhado a third_party/opentelemetry-collector.

Prioridade 3: Padronização do Grafo de Dots e Canvas com @xyflow

Evidências: sentra_canvas/desktop_ui/src/shell-app.jsx:0005-0021 (ShellCoordinateDialog, ShellDotCanvas, ShellDotContextMenu, NetworkSurface, canvasNavigation) e third_party/xyflow/README.md:0010-0012.

Diagnóstico: A interface gerencia superfícies baseadas em coordenadas e nós (ShellDotCanvas na linha 0013, ShellCoordinateDialog na linha 0005, NetworkSurface na linha 0020) além de estado de navegação e mutações pendentes (pendingShellMutations, acknowledgeVerifiedPending na linha 0003). Manter lógica própria de pan/zoom, seleção de nós e roteamento de arestas aumenta o custo de manutenção e o risco de bugs visuais.

Proposta: Adotar o motor de grafo React de third_party/xyflow dentro de ShellDotCanvas e NetworkSurface, mantendo estritamente o controle de estado transacional no shell-bridge (shell-app.jsx:0003), os diálogos de aprovação (ShellApprovalNotifications, 0012), o acesso VDI/computador (ShellDotComputer, 0014) e a listagem de recibos (EventList, Status em shell-receipts, 0006).

Ganho: Melhoria imediata de performance de renderização e UX em grafos de Dots/Spaces, acessibilidade de teclado e redução de código proprietário de coordenadas.

Custo/Risco: Médio. Risco de dessincronizar o estado visual do grafo com pendingShellMutations (0003) se o @xyflow assumir mutações otimistas locais. Os nós do @xyflow devem operar como componentes controlados (read-only até confirmação via acknowledgeVerifiedPending).

Dependências: sentra_canvas/desktop_ui/src/shell-app.jsx, componentes shell-dot-canvas / shell-network e pacote local third_party/xyflow.

Prioridade 4: Otimização da Varredura de Atualização Frontend (native_refresh.py) e Coordenação com UI

Evidências: sentra_canvas/native_refresh.py:0001-0028 (_REFRESH_LOCK, _BUSY_STATES, frontend_source_mtime com folder.rglob("*") nas linhas 0021-0028) e sentra_canvas/desktop_ui/src/shell-app.jsx:0018, 0023 (closeUpdateMenuOnEscape, classifyUpdate, versionDecision, BUNDLE_VERSION).

Diagnóstico: frontend_source_mtime (native_refresh.py:0021) percorre recursivamente src e public via rglob("*") e filtra extensões em Python a cada verificação. Em árvores grandes ou verificações frequentes, isso gera I/O de disco desnecessário no host. Além disso, o módulo exige semântica fail-closed (0001-0005), checando o ledger central e o browser relay antes de tocar em assets compartilhados, sem jamais tentar novamente operações UNCERTAIN.

Proposta:

Em frontend_source_mtime (native_refresh.py:0021-0028), retornar max((p.stat().st_mtime_ns for p in paths), default=0) com avaliação preguiçosa (generator) ou cache curto invalidado por mtime dos diretórios-pai, mantendo _REFRESH_LOCK (0017).

Garantir que o manifesto gerado por materialize.mjs (0024) exponha o BUNDLE_VERSION consumido por classifyUpdate e versionDecision (shell-app.jsx:0023), bloqueando a transição na UI caso o ledger reporte qualquer estado em _BUSY_STATES (0018) ou UNCERTAIN.

Ganho: Redução de latência de I/O na checagem de atualização e alinhamento determinístico entre a decisão de versão na UI (versionDecision) e a trava fail-closed do host (native_refresh.py).

Custo/Risco: Baixo. No Windows (NTFS), o mtime de um diretório pai não se atualiza automaticamente quando arquivos em subpastas profundas mudam; portanto, manter a varredura de arquivos otimizada via os.scandir recursivo é mais seguro do que confiar apenas no mtime da pasta raiz.

Dependências: sentra_canvas/native_refresh.py e sentra_canvas/desktop_ui/src/shell-updates.

Prioridade 5: Automação de Testes de Componentes e E2E da Shell UI com Cypress/Vitest

Evidências: sentra_canvas/desktop_ui/src/shell-app.jsx:0001-0028, sentra_canvas/native_app.py:0012-0028 (WindowControls), third_party/xyflow/examples/react/cypress.config.ts:0001-0012 e third_party/langfuse/vitest.workspace.ts:0001.

Diagnóstico: A camada React (OpenDotsShell em shell-app.jsx:0028) concentra fluxos críticos: restauração de superfície (restoreWorkSurface, 0016), mutações pendentes (pendingShellMutations, 0003), notificações de aprovação (0012), explicação de falhas (FailureNotice, explainFailure, 0019, 0022) e controles nativos (nativeControls, 0028 -> WindowControls em native_app.py:0012).

Proposta: Reaproveitar o padrão de configuração de testes de componente e E2E presente em third_party/xyflow/examples/react/cypress.config.ts e third_party/langfuse/vitest.workspace.ts para testar OpenDotsShell isoladamente com mocks da shellBridge e nativeControls.

Ganho: Previne regressões visuais e de estado (especialmente em recibos, Grants/aprovações e bloqueio de reenvio UNCERTAIN) sem depender de instanciar o WebView2 real a cada teste unitário.

Custo/Risco: Baixo risco técnico; requer apenas configuração de ambiente de teste local de dev.

Dependências: sentra_canvas/desktop_ui/package.json (native_refresh.py:0023).

2. Possíveis Duplicações com third_party
Funcionalidade no SENTRA (Excertos)	Equivalente em third_party	Recomendação
Renderização de coordenadas, nós de Dots e topologia de rede (ShellDotCanvas, ShellCoordinateDialog, NetworkSurface em shell-app.jsx:0005, 0013, 0020).	third_party/xyflow (README.md:0010: biblioteca React pronta para UIs baseadas em nós).	Consolidar: Usar @xyflow/react para a camada visual de canvas/grafo, mantendo o estado de domínio (WorkItems, Grants, Dots) no shell-bridge.
Cálculo manual de integridade/status de artefatos de build (_source_fingerprint em build_windows.py:0027).	third_party/grype (README.md:0007: scanner de vulnerabilidades para filesystems).	Complementar: Manter _source_fingerprint para reprodutibilidade de cache, mas delegar a inspeção de segurança de pacotes ao Grype.
Rastreamento de conexões e contexto no gateway (gateway.py:0003-0005, 0026).	third_party/opentelemetry-collector/client/client.go:0004-0011 (representação de cliente, tenancy e agrupamento de lotes).	Alinhar esquema: Adotar a semântica de atributos de cliente/tenancy (por Dot/Space) na telemetria local, sem substituir o servidor HTTP leve em Python.
3. O Que NÃO Integrar (e Por Quê)

NÃO substituir o ledger local/SQLite nem o armazenamento de recibos pelo immudb (third_party/immudb):

Justificativa: O sentra_model_gateway/gateway.py:0020 já utiliza sqlite3 embutido, e native_refresh.py:0003-0005 exige uma arquitetura host-owned sem serviços extras complexos que precisem ser mortos ou reiniciados. Embutir um servidor Go/gRPC (immudb/tools.go:0006-0009) aumentaria drasticamente a superfície de ataque, o tamanho do instalador (build_windows.py) e o risco de dessincronização com as operações UNCERTAIN e recibos (shell-receipts em shell-app.jsx:0006).

NÃO integrar o stack completo do langfuse (web + worker em third_party/langfuse/vitest.workspace.ts:0001) no runtime desktop nem como proxy no gateway.py:

Justificativa: O gateway.py:0003-0005 declara explicitamente que encaminha bytes SSE sem coletar um turno para preservar o cancelamento upstream e a ordem de eventos para o Codex. Intermediar chamadas pelo pipeline assíncrono do Langfuse introduziria coleta de turno, quebraria o passthrough SSE, criaria dependências pesadas de banco/worker no desktop do usuário e arriscaria sobrescrever ou interferir no modo do modelo escolhido pelo usuário no navegador (gateway.py:0001).

NÃO expor o objeto self._window do WebView2 nem seletores de diretório/porta para o frontend (sentra_canvas/native_app.py:0015-0023):

Justificativa: Conforme documentado nas linhas 0016-0021 de native_app.py, o pywebview reflete objetos públicos recursivamente. Expor _window ou permitir que o JS escolha _state_dir violaria o isolamento de credenciais do broker e travaria a inicialização da bridge.

4. Três Testes de Aceitação Reais e Reproduzíveis
Teste 1: Invariante Fail-Closed e Não-Reenvio de Operações UNCERTAIN no Refresh Nativo

Alvo: sentra_canvas/native_refresh.py:0001-0028 e sentra_canvas/desktop_ui/src/shell-app.jsx:0003, 0023.

Pré-condição: Simular no ledger central de operações (consultado por native_refresh.py:0004-0005) uma operação em estado UNCERTAIN e outra em um dos _BUSY_STATES (STARTING, RUNNING, WAITING_EXTERNAL, QUEUED na linha 0018), além de alterar o timestamp de um arquivo .jsx em sentra_canvas/desktop_ui/src (native_refresh.py:0025-0028).

Ação: Invocar a rotina de atualização de frontend sob _REFRESH_LOCK (native_refresh.py:0017) e acionar versionDecision / classifyUpdate (shell-app.jsx:0023).

Resultado Esperado (Critério de Aceite):

frontend_source_mtime (0021) detecta o novo timestamp nos arquivos monitorados (.js, .jsx, .ts, .tsx, .css, .html, .json, .svg).

O processo aborta a substituição dos assets construídos (fail-closed) enquanto houver estado ocupado ou UNCERTAIN.

A operação marcada como UNCERTAIN permanece intocada no ledger (contagem de tentativas = 1; zero reenvios) e pendingShellMutations (shell-app.jsx:0003) não é limpo sem acknowledgeVerifiedPending.

Teste 2: Passthrough de Streaming SSE, Cancelamento Upstream e Preservação do Modo do Navegador

Alvo: sentra_model_gateway/gateway.py:0001-0028.

Pré-condição: Subir o ThreadingHTTPServer (gateway.py:0026) conectado a um upstream simulado de respostas SSE que emite 5 eventos numerados com intervalo de 100 ms e registra os cabeçalhos/parâmetros recebidos.

Ação:

Iniciar uma requisição de streaming sem forçar override de modelo no gateway, deixando o modo definido pelo runtime do navegador upstream (gateway.py:0001).

Ler os 2 primeiros eventos SSE no cliente e fechar abruptamente a conexão antes do 3º evento.

Resultado Esperado (Critério de Aceite):

Os 2 primeiros eventos chegam ao cliente imediatamente após a emissão (sem buffering de turno completo, cumprindo gateway.py:0003-0005).

O fechamento da conexão propaga o cancelamento ao upstream antes do envio do 5º evento, mantendo a ordem exata dos eventos.

O modo/modelo utilizado no upstream permanece idêntico ao selecionado no navegador, sem adulteração pelo gateway.

Teste 3: Isolamento da Bridge WindowControls e Fingerprinting Determinístico de Build

Alvo: sentra_canvas/native_app.py:0012-0028 e scripts/commander/build_windows.py:0014-0028.

Pré-condição: Instanciar WindowControls(state_dir="...") (native_app.py:0015) com um mock de janela atribuído a _window (0022) e preparar o ambiente de build_windows.py.

Ação:

Inspecionar todos os atributos públicos (não iniciados por _) da instância de WindowControls.

Chamar minimize() (native_app.py:0025).

Executar _source_fingerprint() (build_windows.py:0027) duas vezes consecutivas, modificando entre elas apenas um arquivo dentro de .tmp/build-windows-status.json (0024) ou cache privado.

Resultado Esperado (Critério de Aceite):

Nenhum atributo público de WindowControls expõe _state_dir ou _window ao renderer JS (native_app.py:0018-0022), e minimize() retorna True acionando o método interno com segurança.

O dicionário retornado por _source_fingerprint() permanece idêntico nas duas execuções, comprovando que estados privados e caches gerados em .tmp estão excluídos do hash do instalador (build_windows.py:0027-0028).

---
