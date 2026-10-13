# SENTRA — Rodada 2, prova E2E dos terminais dos Dots (12/10/2026)

## Declaração de resultado

**PARCIAL, NÃO APROVADO COMO E2E DE INFERÊNCIA.** Três CLIs distintas foram iniciadas como processos ConPTY Windows de verdade em um Canvas isolado, e três handoffs foram enviados. Cada envio ficou ligado a WorkItem e Operation centrais reais e a evidência criptografada de transcrição. O Dot coordenador GPT-6 High recebeu um turno real, mas nenhuma resposta de assistente ou recibo terminal de modelo foi observada; a consolidação final não aconteceu. **Não confundir transporte com inferência/conclusão.**

Conector usado: Desktop Commander, dispositivo autorizado OGrandeOxta, ID `4932aeae-074e-4815-9b3b-5998734a7235`. Checkout compartilhado `C:\Users\vitor\OneDrive\Desktop\SENTRA`; `git status` inicial contava 566 entradas alteradas/untracked. Nenhum checkout/reset/clean/commit/push/rebase. Não interrompidos processos existentes, relay ou app, nem removidos Dots, VMs ou conversas reais. Somente sessões ConPTY criadas pelos próprios testes isolados foram encerradas.

## Correções reais desta rodada

1. `sentra_canvas/store.py`: corrigido bloqueio E2E real `ValueError: shell not allowed`; o allowlist de `Store.create_terminal` agora inclui `opencode`. Antes dessa correção, SENTRA CLI e Codex abriam, mas OpenCode falhava mesmo estando instalado.
2. `sentra_canvas/dot_tool_receipts.py` (novo): reserva antes da escrita física uma Operation `canvas.dot_cli_handoff` e um WorkItem central determinísticos, vinculados por owner/projeto/request_key; registra terminal/handoff/Dot/Space e cursor anterior ao envio. Usa `ShellHostRequests` já existente para impedir segundo efeito da mesma intenção. Depois da escrita, Operation vira `WAITING_EXTERNAL` e WorkItem continua `RUNNING`: sem supor resposta. A leitura pelo Canvas projeta estados centrais, cursor e SHA-256 da transcrição protegida, sem expor prompt/transcrição bruta ou alegar ACK de modelo. Perda/fecho de handle sem confirmação provoca transição conservadora para `UNCERTAIN` e `BLOCKED`, sem retry.
3. `sentra_canvas/shell_dot_canvas.py`: adicionado vínculo aos recibos centrais, getter de entregas e verificação do *handle realmente possuído* antes de reutilizar/fechar uma sessão. Após restart, terminal persistido sem handle é marcado `detached`, não tratado como ativo. Handoffs criam WorkItem/Operation antes de enviar. Fecho explícito classifica handoffs não confirmados como incertos.
4. `sentra_canvas/desktop_ui/src/shell-dot-canvas.jsx`: cada Dot agora exibe WorkItem, Operation, estado central, comprimento e SHA da transcrição por ferramenta, explicitando `resultado NÃO comprovado` quando só houve transporte.
5. `tests/unit/test_dot_canvas_tool_routing.py`: adicionada regressão de sessão `detached`, além dos testes pré-existentes de isolamento, idempotência e lançador Windows.
6. `tests/qa/sentra_dot_canvas_e2e_20261012.py` (novo): programa reproduzível para criar Canvas temporário, Dot coordenador e três Dots worker reais, abrir CLIs, fazer links dirigidos, enviar prompts únicos e não destrutivos, registrar hashes e recibos CP e encerrar somente os processos que o próprio script criou. Conta assistant/Operation do coordenador sem fabricar resposta. Não faz retransmissão de inferência incerta; teste de replay de handoff usa somente chave com `sent` já confirmado. Os logs brutos das CLIs permanecem protegidos pelo Store no TEMP.

## Recibos reais (exemplo da última prova integrada)

Evidência isolada `C:\Users\vitor\AppData\Local\Temp\sentra-dot-e2e-20261012-4fo2vmzp\evidence.json`.

| Ferramenta | PID ConPTY próprio | Handoff | WorkItem central | Operation central |
|---|---:|---|---|---|
| SENTRA CLI | 48508 | `a72141134a5b4317a10732e7edc7078e` | `WI-dotcli-65ca3cf233e78d843dcc3057ec7201b3` | `op-dotcli-65ca3cf233e78d843dcc3057ec7201b3` |
| OpenCode | 3240 | `d51b8023abe940d5965ca3ffb0e25e1f` | `WI-dotcli-c9926486414a5d55daf7d484b042c93d` | `op-dotcli-c9926486414a5d55daf7d484b042c93d` |
| Codex CLI | 31612 | `550b5513b95e40228ebc71403fad020f` | `WI-dotcli-8c412d9d45c5e4f07feac53cae89606b` | `op-dotcli-8c412d9d45c5e4f07feac53cae89606b` |

Os três têm `handoff.status=sent`, `work_item_state=RUNNING` e `operation_state=WAITING_EXTERNAL` no momento da projeção; `model_result_verified=false` e `task_completed=false`. Os respectivos SHA-256 da saída **após** o cursor de admissão foram registrados no `evidence.json`. O marcador SENTRA apareceu no texto do terminal, mas pode ser eco de entrada; os outros modelos também não apresentaram recibo verificável. Isso **não** é uma prova de inferência/autenticação. O script relatou `owned_processes_exited=true` após fechar os próprios processos.

Dot coordenador real da mesma prova: `model=sentra/chatgpt-web/gpt-6`, `effort=high`, `conversation_id=conversation-e222edc4c8592fb7ec92ec21a6a8dc8d`, `work_item_id=work-d0c815a53e70e07d53b0898a9259c244`, `operation_id=op-d13a19e8f3dcf077ca5cc79c69a2c296`. Turno do usuário aceito; `operation_state=RUNNING`, `work_item_state=RUNNING`, `assistant_message_count=0`, `model_completed_receipt=false` após observação. Nenhuma decisão/composição/completion foi afirmada.

## Validações executadas

- Primeira prova transport-only isolada: SENTRA + Codex abriram, OpenCode falhou com `shell not allowed`. Corrigido e repetido: **três CLIs iniciaram, três handles próprios encerraram**.
- Três provas posteriores com mensagens únicas e sem ferramentas, todas com `status=inference_unconfirmed`; os arquivos JSON foram retidos em TEMP. Nenhuma operação incerta antiga foi reexecutada.
- `python -m pytest -q tests/unit/test_dot_canvas_tool_routing.py tests/unit/test_shell_dot_features.py`: **17 passed in 26.81s** no último ciclo.
- `python -m py_compile` para adaptadores, store, recibos, Dot canvas e QA: exit 0.
- `vite build --outDir %TEMP%\sentra-dot-canvas-e2e-ui-validation`: build real passou em 1.92s, exit 0; assets publicados não tocados. Avisos não bloqueantes sobre scripts externos e bundle.
- `git diff --check` nos arquivos rastreados alterados: sem falhas.
- Prova anterior desta frente: **18 testes** de coordenação/Canvas passaram; nova rodada não sobrescreveu essas regressões.

## Impedimentos concretos para chamar de E2E completo

1. O primeiro turno do coordenador GPT-6 High foi aceito, mas **nenhuma mensagem de assistente nem Operation `SUCCEEDED`** foi observada. Autenticação/relay/permissão de inferência não foram comprovadas neste runtime isolado; não se deve creditar decisão autônoma do Dot.
2. A integração `CanvasBridge` em turnos shell aceita `coordinator_intent` somente nos tipos de intent do Control Plane. Esse contrato admite handoff para **conversa de Dot**, mas **não** fornece um intent de agente admitido/fenced para iniciar/instruir diretamente OpenCode/Codex/SENTRA CLI via terminal. O botão UI de owner é um caminho diferente; associar a chamada do proprietário ao planejamento do modelo seria falsificar autonomia. Implementar o novo intent precisa de revisão coordenada de Grants, WorkItems, autorização do agente e fences no runtime central; não alterado porque é checkout compartilhado com outras frentes.
3. Os CLIs em modo interativo recebem bytes ConPTY, mas **não emitem recibo de modelo automaticamente vinculável** no contrato atual de handoff. O eco do prompt é insuficiente; não é possível concluir WorkItems sem nova interface de recibos assinados/correlacionados, não só parsing de tela.
4. O OpenCode está configurado para `opencode/muse-spark-1.3-contributor-free#high` e listado em `opencode models`, porém inferência autenticada High não comprovada. Codex instalado, modelo selecionado e autenticação também não comprovados. Antigravity permanece GUI sem CLI/API de agente verificada.
5. Não há garantia de High nas tarefas legadas de `canvas.delegate`: recebem modelo de agente, sem opção própria `--effort high` no executor compartilhado. A sessão SENTRA separada foi configurada como High, mas não comprova aplicação desse esforço pelo backend do provedor.
6. Os WorkItems de teste não foram artificialmente marcados `COMPLETED`. Resultado de coordinator `RUNNING` após encerramento permanece pendente para reconciliação na cópia isolada. **Não** reiniciar/reexecutar nem reutilizar IDs ou efeitos incertos.

## Critério objetivo para aprovação posterior

No mesmo Run/projeto e mesmo Dot root com permissões válidas: (1) operação de conversa do coordenador `SUCCEEDED` com resposta real e modelo/esforço verificados; (2) intent do **próprio agente coordenador**, e não UI de proprietário, admitido por Grant e fence direcionando as 3 CLIs; (3) recibos de inferência genuínos, correlacionados por Operation+WorkItem+request_key e sem duplicidade, com resultados legíveis; (4) só após Quality Gate/validação, promover WorkItems de `RUNNING` a revisão e `COMPLETED` conforme política; (5) coordenador consome os três resultados e publica consolidação verificada. Nenhum desses passos finais foi declarado concluído nesta rodada.

As mudanças da rodada ficaram apenas no checkout atual; não foram publicadas no aplicativo que estiver aberto. Não tocar no instalador VirtualBox, smart UI, ciclo de vida, ConPTY executor compartilhado, relay e sessões alheias.
