# SENTRA OS — protocolo de sprint compartilhada v1

Projeto C:\Users\vitor\OneDrive\Desktop\SENTRA — 8 de outubro de 2026.

## Isolamento da implementação em quatro conversas

Todas compartilham a MESMA árvore Windows. Antes/depois, executar git status --short; NUNCA usar git reset, git clean, checkout em massa, commits globais ou sobrescrever arquivos pré-alterados. Testar os módulos próprios sem executar códigos de terceiros sem análise.

EXEC-001, chat 6ac83719-1efc-83ea-b448-0763a864bbbe: única proprietária de sentra_executors/ e tests/unit/test_sentra_executors_*.py. Integração de Machine Runtime, UFO, pywinauto, Daytona SDK (opcional), Windows API, isolamento e controles. Nenhuma edição do núcleo ou Canvas.
CRIT-002, chat 6ac83727-19b4-83ea-8a85-b2096c9faba5: única proprietária de sentra_interop/ e tests/unit/test_sentra_interop_*.py. Integrações reais ACP/A2A/MCP/ToolHive e compatibilidade de agentes OpenHands. Não editar sentra_runtime, browser, native_bridge.
CRIT-003, chat 6ac83735-217c-83e9-9364-8ab8860f334b: única proprietária de sentra_collab/, sentra_canvas/static/sentra-collab.js (arquivo NOVO), tests/unit/test_sentra_collab_*.py. Colaboração Yjs/Hocuspocus, workspace grants, WebSocket. Não alterar native.js/native.css nem Canvas existente.
COORDENADOR na conversa principal: propriedade exclusiva de sentra_runtime/, tests/unit/test_sentra_runtime_*.py e docs/SENTRA_OS_*.md, contrato, testes de integração e auditoria. Não editar as pastas dos outros.

## Contrato fixo de interoperabilidade

sentra_runtime.contracts exporta:
- Machine(machine_id, kind, owner_principal_id, capabilities=tuple)
- Capability(capability_id, description, risk_level='low')
- OperationRequest(operation_id, principal_id, machine_id, capability_id, work_item_id, idempotency_key, arguments={})
- PolicyDecision(allowed, reason, constraints={})
- OperationResult(operation_id, state, evidence={}, error=None)
sentra_runtime.executor exporta ExecutorAdapter (Protocol async discover/start/observe/cancel/reconcile/cleanup) e ExecutorRegistry (deny by default com PolicyDecision injetado).
Não modificar os contratos sem coordenação. Se ainda não estiverem no disco, aguardar sua criação pelo coordenador e inspecionar antes de prosseguir.

## Padrões obrigatórios
- Sem credenciais, cookies, tokens, chaves em prompts, logs ou código.
- Sem serviço HTTP/TCP público sem autenticação.
- Sem reexecução automática de operações de entrega incerta; reconciliar.
- Erros de backend devem falhar fechados, sem fallback para ações privilegiadas.
- Dependências grandes opcionais; testes com mocks e pelo menos um caminho real quando instalado.
- Preservar atribuição/autoria quando copiar fontes; uso com amigos pode envolver obrigações de redistribuição.
- Cada chat reporta arquivos alterados, validações executadas, falhas e próximos pontos de integração.
- Corrigir somente módulos sob propriedade; conflito com outro agente deve ser comunicado, nunca sobrescrito.

## Critérios de aceite mínimos
A) Capability de máquina inexistente: operação negada.
B) Policy ausente/negada/erro: operação negada antes do side effect.
C) Repetir operation_id e idempotency_key não reenvia efeito.
D) Cancelamento, timeout e revogação não viram sucesso falso.
E) Testes unitários claros e verificação por git status sem dano ao projeto.
F) Integração com SENTRA existente acontece em marco separado, após análise do coordenador.

Leia o relatório docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md para os 37 projetos e suas lacunas.
