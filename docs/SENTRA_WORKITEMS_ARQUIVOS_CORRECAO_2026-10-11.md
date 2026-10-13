# SENTRA — correção do NameError e gerenciamento de WorkItems de arquivos

## Incidente reproduzido na interface
O usuário confirmou permissões de arquivos na conversa do Dot testegpt6 e o Canvas mostrou `NameError: operation failed`. A máquina de arquivos estava registrada no projeto Oxta, mas a lista de trabalhos ativos para essa máquina estava vazia.

## Causa
`sentra_canvas/service.py::center_prepare_task` usava `closing(...)` sem importação no escopo do método. A configuração separada da máquina concluía, mas o preparo do WorkItem falhava antes de finalizar a autorização.

## Alterações
- Adicionada importação de `contextlib.closing` ao serviço.
- Criado endpoint owner-auth, read-only `GET /api/center/task/files?ws=...&conversation_id=...`. Ele valida a identidade da conversa, resolve o Dot no servidor, filtra tarefas por Workspace, Run, Agent, Machine e Conversation e mostra capacidades apenas após a política de autorização do ControlPlane. Chamadas de uma conversa desconhecida retornam 403.
- Painel `Trabalhos do Dot` na própria conversa: lista de trabalhos, estado, seleção, atualização, detalhes de leitura/escrita/exclusão, acesso ao botão já existente de autorização/revogação.
- A autorização agora consulta os trabalhos existentes após o POST e só apresenta sucesso quando o backend confirma os Grants. Em caso de acknowledgement perdido, consulta a lista antes de qualquer nova tentativa, sem repetir mutações automaticamente.
- A preparação de novo WorkItem detecta trabalhos parciais ainda ativos; não duplica Grants nem operações. Trabalhos incompletos precisam de revisão/revogação humana.
- A interface possui fallback read-only via catálogo `/api/center/machines` durante a troca de versões do broker.

## Validação
- `tests/unit/test_sentra_file_workitems_ui_api.py`: cobertura de escopo de conversa/agent, separação de Grants e ausência de duplicações após preparo incompleto.
- `tests/unit/test_sentra_shell_live_preview.py`, `tests/unit/test_sentra_terminal_ui.py`: suítes relacionadas.
- **13 passed** na suíte combinada.
- `npm run build`: frontend compilado com êxito quando o broker estava parado para evitar lock do Windows no desktop.css.
- Broker reiniciado graciosamente após confirmar ausência de operações `RUNNING/QUEUED/PENDING/STARTING/WAITING_EXTERNAL` dentre as operações consultadas.
- Instância final: porta local `65149`, PID `51064`. Rota válida `/api/center/task/files` para testegpt6 retornou HTTP 200, `machine_configured: true`, `items: []`; conversa inválida retornou 403. SHA-256 dos assets servidos coincide com o manifesto.
- Nova janela nativa SENTRA iniciada no PID `51204`. A janela anterior PID `23516` foi preservada, para não descartar o rascunho aberto no usuário.
- **Não foram criados WorkItems ou concedidos Grants no Oxta**. O usuário deve confirmar novamente pelo modal da nova interface. Nenhum teste de escrita/exclusão do workspace foi efetuado.
- A exposição de ferramentas no relay do ChatGPT Web é uma integração distinta; a autorização do WorkItem não equivale a prova de ferramenta nativa disponível dentro do modelo.

## Restrições
Sem commit/push/reset ou reexecução de efeitos incertos. O incidente NameError é corrigido no código e a descoberta read-only foi provada via HTTP real; a execução de uma autorização completa no ambiente Oxta ainda depende do clique explícito do usuário.
