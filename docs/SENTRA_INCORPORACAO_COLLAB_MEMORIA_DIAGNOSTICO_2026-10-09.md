# Incorporação — colaboração, memória e diagnóstico

Implementação do coordenador em andamento, com aceitações preparadas e validação integral pendente. Complementa a matriz dos37 projetos e as frentes dos dois subagentes.

## Fluxos ligados ao produto

O Canvas ativa colaboração por ação do proprietário. O host cria um WorkItem de apresentação e grants de leitura/escrita por usuário; tickets duráveis são consumidos uma vez, com expiração. O sidecar Node recebe credenciais por stdin e fica em processo/Job supervisionado. Os callbacks consultam o ControlPlane real; snapshot e revisão usam CAS. Read guards ordenam commit contra revogação, mudança do WorkItem e cancelamento do Run. Persistir a projeção no grafo é idempotente; uma interrupção após o snapshot é reparada pela próxima leitura.

Yjs13/Hocuspocus4.7 são usados pelo browser real. Notas usam Y.Text, diffs de edição, posições relativas e UndoManager limitado à origem local. A migração de notas antigas é persistida por writer autorizado antes de publicar novos structs. Presença usa clocks e identidade autenticada. O documento aceita somente layout, geometria e texto; IDs desconhecidos não criam agentes/terminais nem mudam topologia ou autoridade.

O renderer monta nós visíveis e preserva os atores de terminal fora da viewport. Bounds, vizinhos do grafo e navegação por teclado vêm do grafo do host. Foram preparados testes de browser com 100 e 500 nós, métricas de pan e seleção, dois clientes colaborativos e undo que preserva a edição remota.

Experiências UFO são derivadas de receipts centrais com resultado conhecido, protegidas no armazenamento local e vinculadas à operação/tarefa/configuração. Entradas alteradas, configuração diferente, origem sem evidência verificável e prazo expirado excluem sugestões. O Canvas e a CLI consultam experiências sob grant atual. Planos têm revisões, CAS de edição e undo/redo; passos cujo efeito já começou são conservados como procedência imutável. Revisão de plano não despacha operações.

O pipeline de diagnóstico guarda apenas packets OTLP com campos permitidos e hashes de identidade. Fila, batch, bytes, cardinalidade, retries e retenção são limitados; entregas, perdas e backlog são contabilizados. Replays são deduplicados durante a retenção e retries preservam os mesmos trace/span IDs. Falha no sink não muda resultados centrais. A interface permite ativar um collector loopback e consultar estado. Diagnóstico não afirma completude de auditoria.

## APIs do proprietário

| API | Comportamento |
|---|---|
| POST `/api/collab/prepare` | WorkItem/grants de apresentação escolhidos pelo proprietário |
| POST `/api/collab/session` | Ticket novo para cada autenticação/reconexão |
| POST `/api/collab/disable` | Revoga grants da sessão/tarefa correspondente |
| POST `/api/collab/host` | Callback privado do sidecar autenticado pelo bearer do host |
| POST `/api/center/experiences` | Sugestões com origem e validade; nenhuma concessão de execução |
| POST `/api/center/plan` | read/revise/undo/redo de proposta de plano |
| GET/POST `/api/center/telemetry` | Estado/configuração do diagnóstico do runtime |

`machine_list` da CLI também retorna tarefas com capabilities atualmente admitidas; o agente não precisa inventar WorkItem IDs. `machine_experiences` usa máquina e tarefa atribuídas à sessão corrente.

## Aceitações preparadas

- `tests/unit/test_canvas_collaboration_authority.py`: nonce/revogação/CAS, projeção após interrupção e bloqueio de escrita fora de workspace.
- `tests/unit/test_canvas_experience_and_plan.py`: segunda tarefa recupera origem, entrada alterada é excluída e undo conserva efeito executado.
- `tests/unit/test_canvas_machine_budget.py`: quota compartilhada admite apenas um efeito e replay não cobra novamente.
- `tests/unit/test_sentra_runtime_telemetry_pipeline.py`: sink indisponível, reinício, batching, retry, retenção, overflow e ausência de conteúdo privado.
- `tests/e2e/test_canvas_collaboration_and_culling.py`: browser e sidecar reais, dois clientes, undo e métricas com100/500 nós.
- `tests/js/graph_view.test.cjs`: projeção de viewport, bounds/vizinhos e preservação dos dados de sessão.

Nenhum desses testes foi executado nesta etapa. Aceitação de serviço externo, peer/VM, inferência e identidade real exige o ambiente correspondente; stubs de contrato não substituem essa prova.
