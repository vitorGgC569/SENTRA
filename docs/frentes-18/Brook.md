# Brook — stream visível do CLI

Implementador: Brook. Maestro: Grok high. Checkout: `C:\Users\vitor\OneDrive\Desktop\SENTRA`.
Registro: 2026-10-13.

O CLI não está homologado. Saída 0 não é sucesso do produto. `unit_gate` e `process_exit` não fecham o trio e não escrevem `READY_FOR_PROMOTION`.

## O que este corte alinha

O feed efêmero do shell passa a nomear coordenação e entrega incerta. A prévia continua sem autoridade.

- `sentra_cli/shell_live_preview.py` aceita as fases `coordinating` e `delivery_uncertain`.
- `sentra_canvas/shell_live.py` mostra `Coordenando` e `Entrega incerta. Não reenvie.` O `view` segue `authoritative: false`, `partial: true`, `closes_trio: false`.
- `sentra_cli/__main__.py` `stream_turn` avisa a fase uma vez, junto com o texto `coordinating`.
- `sentra_cli/repl.py` manda cada delta novo ao preview e, se a entrega já observada é `uncertain`, grava `delivery_uncertain` uma vez. Não há segundo turno.
- `sentra_cli/producer_gate.py` e `tests/qa/brook_cli_producer_gate.py` só leem autenticação. Não chamam `sentra-cli` e não enviam prompt.

Não foram editados `orchestrator/`, `providers/`, o recibo do Flint nem `sentra_canvas/desktop_ui/`.

## Prova desta rodada

Unitário, sem provedor:

- `pytest tests/unit/frentes/cli/test_orchestrated_stream.py`: 6 passed in 2.27s e 6 passed in 2.32s.
- `pytest tests/unit/test_sentra_shell_live_preview.py tests/unit/frentes/cli/test_producer_gate.py tests/unit/test_cli_private_stdin.py::test_real_private_input_writes_unicode_file` junto com o stream: 14 passed in 4.93s.

Prova produtora:

A leitura de 2026-10-13, sem prompt, foi:

- Codex `login status`: código 0, texto `Logged in using ChatGPT`. Isso é sessão, não recibo.
- OpenCode `auth list --standalone`: código 0, texto `No authenticated integrations`.
- Não havia cadeia Run `RUNNING`, WorkItem `IN_REVIEW`, Operation `SUCCEEDED`, Grant e recibo verificado com `execution_uncertain: false`.

`python tests/qa/brook_cli_producer_gate.py` saiu 3 e imprimiu `producer_turn: withheld`, bloqueios `opencode_unauthenticated` e `authority_chain_absent`, `prompt_sent: false`, `cli_invoked: false`. O turno produtor não rodou. Exit 3 dessa QA significa turno retido, não sucesso do produto.

## O que falta

Três inferências reais com recibos verificados, resposta de coordenador e promoção explícita. Enquanto o OpenCode não tiver integração autenticada e a cadeia de autoridade não existir, o portão continua fechado. `UNCERTAIN` não é reenviado.
