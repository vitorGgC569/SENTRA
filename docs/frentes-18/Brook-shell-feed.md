# Contrato do feed do shell para Cadencia e Lumen

Origem: Brook, 2026-10-13. Consumidores: Cadencia (movimento) e Lumen (integração visual).
Este arquivo não altera `desktop_ui`. Não é recibo e não fecha frente.

## O que o feed é

`ShellLivePreviews.view` devolve a prévia nativa do turno. O renderer em `shell-conversation.jsx` já mostra `livePreview.activity` e o texto parcial. Brook não edita esse renderer.

Campos estáveis:

| Campo | Valor | Uso |
| --- | --- | --- |
| `authoritative` | sempre `false` | Não promover, não concluir, não autorizar |
| `partial` | sempre `true` | O texto pode crescer; não é a resposta final |
| `closes_trio` | sempre `false` | Não é Run, WorkItem, Operation, Grant nem recibo |
| `activity` | rótulo curto | Estado visível do momento |
| `content` | prosa já mostrada, sem `[[` | Não repetir o prefixo na animação |
| `status` | `generating`, `idle` ou `preview_unavailable` | `idle` não é sucesso. `preview_unavailable` não é `idle` e não é fase `planning` |

`unit_gate` não aparece no feed. `process_exit` 0 não é fase e não é `READY_FOR_PROMOTION`.

## Rótulos que a animação pode seguir

| Fase escrita pelo CLI | `activity` | Movimento permitido |
| --- | --- | --- |
| nenhuma ainda | `Aguardando modelo` | Ainda não é `Coordenando` |
| `coordinating` | `Coordenando` | Começar antes do primeiro delta. Uma vez por anúncio. O `content` só está vazio porque ainda não houve delta |
| delta de texto | `Recebendo resposta` | O `content` do view é a prosa acumulada. O sufixo novo é a diferença. Delta só de espaço não troca o rótulo, mas entra no `content` |
| `tool_call` | `Executando ferramenta ` mais até 48 caracteres ASCII | O nome fica no rótulo. Argumento, caminho e Grant não entram |
| `tool_result` | `Resultado da ferramenta recebido` | Sem o texto do resultado |
| `provider_submitted` | `Aguardando ChatGPT` | Espera. O produtor zera o `content` neste evento |
| `response_complete` | `Confirmando entrega` | Ainda não é recibo |
| `delivery_uncertain` | `Entrega incerta. Não reenvie.` | Parar. Não repetir o efeito. Corresponde à fase de canvas `uncertain` |

A fase de canvas `uncertain` já diz: não há confirmação e não se reenvia. O feed não cria outra fase. `status: idle` não é a fase `planning`. `Coordenando` é que pode abrir o compasso inicial.

## O que não fazer

- Não tratar o texto parcial como resposta final do Flint.
- Não animar saída 0, `unit_gate` ou `Confirmando entrega` como trio fechado.
- Não reenviar quando a atividade for entrega incerta.
- Não desenhar o mesmo delta duas vezes. O produtor já cortou o prefixo mostrado.
- Não ler o feed como permissão de efeito. A autoridade continua no shell autenticado e nos recibos do Flint.

## Quando a prova produtora existe

Só com OpenCode autenticado e com a cadeia já presente: Run `RUNNING`, WorkItem `IN_REVIEW`, Operation `SUCCEEDED`, Grant próprio e recibo verificado, `execution_uncertain` false. Login do Codex não basta. Até lá `tests/qa/brook_cli_producer_gate.py` retém o turno e não chama o CLI.
