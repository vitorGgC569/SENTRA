# SENTRA — streaming progressivo e modos de acesso (2026-10-11)

## O que foi implementado

1. **Streaming nativo do SENTRA CLI**: `sentra_cli/agent.py` transmite fragmentos do adaptador `chat_stream` em vez de esperar `''.join(...)`. O parser de apresentação retém diretivas `[[TOOL|...]]` incompletas para que nunca apareçam como comandos no chat. O conteúdo definitivo e o journal protegido continuam sendo consolidados apenas quando o turno é encerrado.
2. **Projeção efêmera no Canvas**: `sentra_cli/shell_live_preview.py`, `sentra_canvas/shell_live.py` e `sentra_canvas/shell_runtime.py` publicam somente texto de prévia e etiquetas de atividades (`tool_call`/`tool_result`) por um arquivo temporário proprietário do runtime, com nonce aleatório, limites de bytes e exclusão no fim do turno. Nenhum dado de preview recebe autoridade para executar ações. Não reenvia chamadas incertas.
3. **API autenticada**: `GET /api/shell/live` exige Bearer do Canvas e IDs válidos de projeto, Space e conversa. A resposta é `status: generating`, `partial: true`, `authoritative: false` ou `status: idle`; o endpoint não admite ferramentas nem operações.
4. **Exibição incremental no Dot**: `shell-conversation.jsx` consulta a projeção de forma periódica, adicionando um rascunho visível com avatar e atividade em andamento. Resposta definitiva continua vindo do journal normal após recibo, nunca do preview.
5. **Seletor simples de acesso**: a conversa oferece `Perguntar antes de executar` (sem grant automático), `Consultar arquivos do projeto` (capability somente leitura) e `Executar no projeto` (leitura, escrita e exclusão, sempre limitado ao projeto). Autorizações e revogações exigem confirmação explícita e usam WorkItem e Grants do ControlPlane. Isto **não é** acesso irrestrito a todo computador.
6. **Canvas compilado**, serviço principal reiniciado mantendo estado, nova janela nativa aberta.

## Provas e limites

- Testes isolados: `python -B -m pytest -q -p no:cacheprovider tests/unit/test_sentra_shell_live_preview.py tests/unit/test_sentra_terminal_ui.py` → **9 passed**.
- Build: `npm run build` no `sentra_canvas/desktop_ui` → êxito, manifest/assets atualizados (aviso já conhecido de bundle grande).
- Verificação HTTP real: projeção GET de conversa Oxta retornou 200/`idle`; conversa inválida retornou HTTP 403; `desktop.js` e `desktop.css` corresponderam aos SHA-256 do manifesto.
- Broker final: porta `65149`, estado `.sentra/canvas` preservado, janela nativa anterior encerrada, nova janela aberta.
- **Não** foi enviado prompt real ao GPT-6, nem criado/editado/excluído arquivo no Oxta, nem concedidos Grants do usuário. A transmissão progressiva integrada com o modelo real ainda precisa ser testada numa conversa autorizada.
- **Importante**: turnos do Dot que passam pela rota CLI nativa têm prévia textual quando o provedor emite fragmentos. A rota `ShellWebRuntime.execute` do relay ChatGPT Web ainda observa uma resposta final atestada, sem uma API de token-deltas verificáveis; por isso não foi fabricado falso streaming e tal rota permanece final-only. O plugin/autorizações do ChatGPT são separados do ControlPlane do SENTRA.
- A opção inicial de perguntar não implementa pop-up automático por ferramenta. Enquanto o fluxo de consentimento granular com pedidos tipados do modelo não for integrado, operações reais exigem escolha de um escopo e confirmação do usuário na interface.
- Sem `git reset`, `git commit` ou `git push`; modificações de outros agentes preservadas.

## Próximos passos técnicos

- Relay Web: transportar eventos parciais autenticados/document/turn-bound e originais via canal tipado com revisão e prova de origem. Não derivar chamadas de ferramentas de prosa não confiável.
- Granularidade de aprovação: `ask-per-action` real deve criar pedidos pendentes por operação e exigir confirmação no host, com escopo de caminho, capability, WorkItem, TTL, efeito e risco.
- E2E em CLI/Canvas com provedor real: observar 3+ deltas antes do final, ferramenta real com status e recibo, cancelamento, reload, controle de identidade e inexistência de duplicação em casos incertos.
