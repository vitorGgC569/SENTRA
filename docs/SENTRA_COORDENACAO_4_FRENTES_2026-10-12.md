# SENTRA — Registro de frentes paralelas (2026-10-12)

## Convenções
Checkout compartilhado: `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Quatro conversas foram iniciadas via extensão autenticada do ChatGPT no Edge com solicitação de GPT-6 High, Desktop Commander real, testes e relatórios, sem reset/commit/push e sem reenviar operação incerta. A seleção GPT-6/High foi verificada na interface antes dos envios. O relay de entrega informou `DELIVERY_UNCONFIRMED` após alguns envios; cada prompt foi posteriormente **observado na respectiva página**, não reenviado. Observação da página não significa recibo do relay nem conclusão do trabalho.

| Frente | Conversa | Estado desta checagem |
|---|---|---|
| P0 Debian persistente | https://chatgpt.com/c/6accdf33-3818-83e9-bc3f-3a5765de32d1 | Prompt visível; guia fixa; entrega em andamento |
| P0 Terminais | https://chatgpt.com/c/6accdfe8-a9b8-83e8-abe3-7489f6bc2f4d | Prompt visível; guia fixa; entrega em andamento |
| P1 Exclusão/arquivamento Dots | https://chatgpt.com/c/6accdfff-a738-83e9-b50c-2aa3a396db7a | Prompt visível; guia fixa; entrega em andamento |
| P1 Imagens nativas | https://chatgpt.com/c/6acce016-b418-83e9-a963-478c8a70f346 | Prompt visível; guia fixa; entrega em andamento |

Verificação final por UI Automation do Edge mostrou `Fixado` para quatro títulos independentes: UUID DMI Debian, Integrar terminais SENTRA Canvas, Implementação do arquivamento seguro e Implementação geração nativa web. Não foram alteradas outras abas.

## P2 executada por esta conversa

- `sentra_executors/virtualbox_project.py`: corrige destino de `guestcontrol copyto` para diretório remoto e verifica a cópia via SHA-256 com o nome UUID exato do TAR.
- `tests/unit/test_virtualbox_project.py`: contrato do fluxo e bloqueio de guest não autenticado, mantendo estado físico intacto.
- `sentra_canvas/desktop_ui/src/shell-interactive-ui-schema.js`: validación JSON limitada (versão 1) com elementos text, metric, progress, table, choice, checklist; rejeição de HTML/JS/URL/tool calls como elementos, tamanhos e contagens limitados.
- `sentra_canvas/desktop_ui/src/shell-interactive-ui.jsx` e `.css`: painel declarativo de controles locais, sem execução de ferramenta, rede ou operação física.
- `sentra_canvas/desktop_ui/src/shell-markdown.jsx`: reconhece blocos `sentra-ui` e mantém código visível quando JSON inválido.
- `sentra_canvas/desktop_ui/test/shell-interactive-ui.test.mjs`: testes de validação e isolamento.

Teste final P2: 4 testes Python aprovados, 1 ignorado; 2 testes Node aprovados; Vite build concluído em `.tmp/sentra-smart-ui-validation-20261012` com aviso não fatal de bundle grande.

**Não homologado fisicamente:** transferência ao guest exige Debian persistente com Guest Additions/guestcontrol verificados pela frente P0. O build P2 ainda não foi reiniciado/deployado na instância ativa — não interromper operações de agentes paralelos.

## Coordenação / limites

1. Não renomear, fechar, ou reenviar prompts nos quatro chats.
2. Antes de considerar uma frente pronta, exigir relatório `docs/SENTRA_DELEGADO_<FRENTE>_2026-10-12.md`, diffs escopados, testes e recibos reais (quando possível).
3. Operações `UNCERTAIN` ou exclusão física (Dots/VMs/VDIs/ChatGPT) exigem reconciliação/autorizações específicas; não repetir ou simular conclusão.
4. Não reiniciar o Control Plane ou VMs durante operações ativas.
