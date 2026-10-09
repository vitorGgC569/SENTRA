# Workflows e central do Canvas Web

Implementação do coordenador em andamento; testes de aceitação preparados para a bateria final, ainda não executada. O Canvas permanece a interface web do SENTRA servida em `/canvas`; não foi substituído pela aplicação XYFlow clonada.

## Ligação ao produto

`DocumentWorkflowMachine` conecta o worker com checkpoints, sinais, dependências e subflows ao MachineHost existente. O proprietário configura um catálogo versionado e imutável por máquina/agente; a configuração é persistida e reconstruída sob o workspace atual. Agentes recebem apenas as tarefas e capacidades admitidas. A descoberta e o dispatch verificam também o vínculo exato `metadata.machine_id` do WorkItem.

O editor web permite montar etapas de CSV/TSV, XLSX, PDF, espera de confirmação e verificação com referência independente. Os arquivos são parâmetros da execução, permitindo reutilizar uma definição com entradas e saídas distintas. Criar/avançar/consultar/enviar sinal e executar cada atividade são operações distintas, com identidades centrais próprias. `advance` oferece atividades; não inicia outro efeito enquanto mantém a exclusão da operação de controle. Retomar ou consultar não repete uma atividade incerta.

As atividades de documentos usam o executor real com caminhos limitados ao workspace. Helpers síncronos dentro da chamada assíncrona usam `run_blocking`: o thread efetivo conserva lock físico e renovação da lease mesmo se o solicitante sair ou o timeout da atividade vencer. O retorno efetivo é registrado como evidência suplementar verificável; não promove uma operação incerta a sucesso nem autoriza novo dispatch.

Verificadores que retornam `passed=false` geram receipt `FAILED/COMPLETED` com `ACCEPTANCE_FAILED`, sem retry. Execução bem-sucedida do verificador e aceitação do resultado são avaliadas separadamente.

`GET /api/center/overview` oferece páginas de metadata de operações e WorkItems, estados da Run, cadastro de máquinas, consumo registrado, políticas de limite e diagnóstico. A projeção lê os serviços centrais existentes; não replica uma autoridade. Resultados completos ficam na consulta explícita da operação. Cadastro de provedor não comprova execução. O painel de central oferece revisão/undo/redo de planos com CAS; revisões não despacham atividades e conservam passos cujo efeito já começou.

## Aceitações preparadas

- `tests/unit/test_canvas_workflow_documents_integration.py`: rotas de produção, CSV real, artifact, repetição da identidade sem reescrita, reinício do host/checkpoint, sinal, reprovação de referência e revogação antes da publicação.
- `tests/unit/test_canvas_center_overview_integration.py`: operação real na projeção, isolamento entre workspaces, autenticação, páginas e exclusão de corpos de resultado.
- `tests/unit/test_sentra_runtime_effect_boundary.py`: cancelamento de solicitante conserva exclusão até retorno físico; evidência tardia preserva estado incerto.
- Aceitação visual final: configurar pipeline, alternar máquinas sem reutilizar atividades da seleção anterior, executar uma etapa, aguardar confirmação, consultar evidência e revisar plano sem iniciar efeito.

## Pendências do escopo integral

O worker é subordinado ao Core; esta ligação não instala Temporal/LangGraph como serviços independentes. Ainda faltam bindings de atividades Activepieces no produto, providers adicionais, reconciliação específica das atividades incertas e aceitação integral das integrações. Identidade, auditoria e datasets mantêm seus critérios completos. O redesenho visual está atribuído a um subagente dedicado por solicitação explícita do proprietário.
