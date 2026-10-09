# SENTRA OS — Gate 4, coordenação independente

Data local: 2026-10-08 23:42 (America/Sao_Paulo). Estado de desenvolvimento, não release.

## Frentes e propriedade
- Coordenador: sentra_runtime/, sentra_quality/, tests/unit/test_sentra_runtime_*.py, docs/SENTRA_OS_*.
- EXEC-001: sentra_executors/ e tests/unit/test_sentra_executors_*.py.
- CRIT-002: sentra_interop/ e tests/unit/test_sentra_interop_*.py.
- CRIT-003: sentra_collab/, novo frontend sentra-collab.js, tests/unit/test_sentra_collab_*.py.
- Evitar git reset/clean e alterações em áreas dos outros agentes.

## Evidência do ciclo
- Base 23:25: 141 testes Python aprovados, 1 ignorado; 12/12 Node; 37/37 clones com procedência verificada.
- Enviados GATE-3 às mesmas 3 conversas. URLs originais e recibos verificados no arquivo de runtime da sprint.
- Colaboração ampliada para 17 testes. Houve falha 15/16 na presença sanitizada; após correção, npm test retornou 17/17.
- A suite Python unitária completa, executada durante edições concorrentes, encerrou com 1312 aprovados, 4 ignorados e 1 falha (boundary Node da presença, depois corrigida). NÃO alegar full unit green com essa rodada.
- Reforçado sentra_runtime/executor.py: replay de operation_id agora reavalia grant antes de consultar o provedor. A equipe EXEC-001 atualizou o teste de revogação correspondente.
- Implementada sentra_runtime/authority_bridge.py: usa AuthorizationService e GovernanceService reais com WorkItem RUNNING, identidade, grant e condições verificadas. Não usa local-owner implícito. Testes focados de ponte e contratos anteriores: 24 aprovados.
- Uma execução intermediária de 85 testes mostrou 3 falhas ACP fixture sob carga. Isoladamente, a fixture passou 5/5 e o diagnóstico confirmou PolicyDecision permitido. Diagnóstico de flakiness enviado à CRIT-002, sem relaxar a política.
- Após correções observadas, regressão cruzada de executores, ACP fixture, runtime e boundary de colaboração: 98 testes aprovados.
- Instruções GATE-4 EXEC-001, CRIT-003 e investigação ACP de CRIT-002 entregues e confirmadas nos mesmos chats.

## Bloqueios de produção
- BoundWorkItemPolicy é um gate de admissão, não substitui reserva durável de Operation, lease/fence, revogação ativa e auditoria antes do efeito externo.
- Métodos internos do ExecutorRegistry NÃO devem ser expostos a API pública; AuthorizedOperationGateway existe para verificar autorização atual em observe/reconcile/cancel/cleanup.
- UI Automation em janela Tk própria precisa de ambiente interativo e dependências; Daytona sandbox real ainda não foi comprovado.
- ACP usa processo de laboratório, não agentes externos reais. É obrigatório investigar instabilidade sob carga e cleanup sem órfãos.
- Sidecar Yjs/Hocuspocus não está no Canvas principal; sem transação de storage+fencing+visibilidade comprovada não afirmar consistência distribuída.
- Persistência hosted, segredos de amigos, TLS, witness criptográfico de logs, SBOM, packaging e E2E multinó continuam pendentes.
- Novos módulos permanecem untracked no Git principal e precisam de revisão antes do release.

## Próximo gate
Exigir, antes da integração: prova da autoridade real no caminho Run/WorkItem/Operation, revogação, idempotência e isolamento; ACP estável sob concorrência; precommit colaborativo sem vazamento; executores reais apenas em laboratório; regressão completa após estabilização das três frentes.
