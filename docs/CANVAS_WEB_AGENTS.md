# SENTRA Canvas — coordenação de modelos Web

## Contrato funcional

Os terminais do SENTRA Canvas são processos ConPTY reais com sessões de conversa isoladas. Cada nó de agente seleciona explicitamente um modelo, e links são dirigidos: uma ligação A -> B autoriza A a encaminhar uma mensagem para B. Para comunicação em ambos os sentidos, crie também B -> A. Não existe acesso implícito a outros workspaces.

Um SENTRA CLI autorizado no Canvas pode emitir as diretivas:
- `[[CANVAS|create_agent|nome|modelo|papel]]` — cria outro agente/CLI e conecta o nó ao solicitante.
- `[[CANVAS|create_terminal|nome|modelo]]` — cria um terminal independente conectado.
- `[[CANVAS|connect|origem|destino]]` — liga nós autorizados.
- `[[CANVAS|create_team|nome|coordenador|ids_separados_por_virgula]]` — cria equipe.
- `[[CANVAS|dispatch|id|mensagem]]` — faz entrega única, com identidade persistente.
- `[[CANVAS|check|id]]` — consulta histórico do destinatário e recibos do handoff.

### Confirmação de entrega e de inferência

O estado `status=sent` prova somente escrita no terminal. A confirmação separada `receipt_status` distingue:
- `pending`: enviado, ainda não reivindicado pelo CLI destinatário.
- `running`: o CLI destinatário reivindicou a mensagem e está processando.
- `answered`: o turno do modelo terminou sem erro informado pelo provedor.
- `tool_completed`: uma diretiva CLI local foi processada; **não** comprova inferência.
- `failed`: o CLI observou falha determinística no turno.
- `uncertain`: o transporte, a execução, ou a confirmação são inconclusivos.

Apenas o token de capacidade do terminal destinatário pode reivindicar ou concluir seu handoff. A verificação usa o workspace e o conteúdo exato da entrega, sem inserir marcadores no prompt que o modelo recebe. Confirmações são idempotentes. Uma falha depois do envio nunca provoca repetição automática. Fechamento do terminal ou reinicialização do Canvas convertem recebimentos inacabados em `uncertain`.

No Canvas, a seção **Atividade e auditoria > Mensagens entre agentes** mostra os recibos. O `check` dirigido também traz `handoffs` com o estado de resposta.

### Testes automatizados executáveis

```powershell
python -m pytest -q tests/unit/test_canvas_cli_coordination.py tests/unit/test_canvas_web_peer_transport.py
python -m pytest -q tests/unit/test_sentra_cli.py tests/unit/test_sentra_cli_model_effort.py tests/unit/test_sentra_cli_browser_host.py
node --check sentra_canvas/static/native.js
```

O teste `test_canvas_web_peer_transport.py` utiliza **dois CLIs reais via ConPTY** e um Gateway Responses SSE de teste isolado. Comprova mensagens bidirecionais, histórico persistido, recrutamento originado em um turno de modelo, criação de links, despacho, recibos e propagação de falhas. O provedor de teste é **simulado**, não uma inferência real do ChatGPT ou Gemini.

### Condição para produção

A rota `sentra/chatgpt-web/auto` utiliza o modelo padrão da conta, inclusive quando uma sessão Free só apresenta `Pensar`. Ela não declara família GPT ou High e tem orçamento de contexto conservador. Os modelos GPT-6 explícitos continuam exigindo confirmação do seletor. Em instalações sem Codex autenticado, novos CLIs/agentes selecionam Auto como padrão.

A conta autenticada no **ChatGPT Web Models** deve realmente oferecer o modelo e o esforço solicitados. Estar online e ver `sentra/chatgpt-web/gpt-6` no catálogo **não** garante que o ChatGPT Web concedeu acesso. Na superfície temporária com apenas botão **Pensar** e sem seletor verificável, o upstream rejeita antes do envio com `chatgpt_model_controls_unavailable`. Não é correto apresentar essa rejeição como sobrecarga ou alterar silenciosamente GPT-6 High para outra família.

A autenticação do OpenAI Platform para o Secure MCP Tunnel **é independente** da sessão ChatGPT dentro do Browser Host. É necessária uma sessão ChatGPT com acesso efetivo ao modelo para um teste de inferência real.

O modelo proprietário de cada agente também deve estar autenticado para que a conversa aconteça entre modelos Web reais; os testes simulados não dispensam esse requisito.

### Seletor de modelos e atualização da instância em execução

O Canvas consulta `GET /api/models` com autenticação local. O endpoint consulta `/v1/models` do Gateway com a credencial autorizada do próprio SENTRA CLI, retorna somente nomes e marca `model_access_verified=false`. A lista é auxiliar; o nível GPT-6 High continua sujeito aos controles do ChatGPT Web. Se o Gateway não estiver acessível, o Canvas não inventa disponibilidade.

Mudanças Python (`service.py`, `graph.py`, `agent.py` e rota `/api/models`) são carregadas **apenas quando um novo processo do Canvas/CLI é iniciado**. Não reinicie um broker com terminais ativos sem planejar a retomada: o encerramento de ConPTY perde o processo interativo, mesmo mantendo histórico persistente. A reinicialização segura atualiza o banco para a versão 4 e recupera as entregas pendentes como incertas, sem reenvio automático. Testes em broker isolado não significam que o broker principal foi atualizado a quente.
