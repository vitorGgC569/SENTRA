# SENTRA CLI — compositor centralizado (2026-10-11)

## Implementação

- `sentra_cli/terminal_ui.py`: novo compositor interativo para consoles Windows que suportam VT. Tela inicial centralizada vertical e horizontalmente; logomarca SENTRA estilizada em blocos, subtítulo discreto, campo de prompt em painel escuro com barra azul lateral, modelo/provedor/esforço com hierarquia cromática e dicas de comandos.
- Editor sem dependências externas, baseado em `msvcrt.getwch`, com cursor, Home/End, inserção, Backspace/Delete, histórico de prompts nas setas e responsividade ao redimensionamento após interação. Nunca executa ferramentas/grants por conta própria.
- `sentra_cli/repl.py`: REPL interativo usa o novo compositor quando stdin/stdout são console com VT, preservando `Console.input` em terminais redirecionados, não interativos ou sem VT.
- Histórico temporário da conversa renderizado acima do compositor, limitado aos últimos 12 registros e truncado para preservar responsividade. Saídas de comandos existentes continuam disponíveis e são mostradas no histórico compacto.
- Entrada `--prompt`/`--prompt-stdin` e comandos/sessões/modelos/razão continuam no caminho anterior. Sem importação obrigatória de bibliotecas TUI.

## Evidência

- `python -B -m pytest -q -p no:cacheprovider tests/unit/test_sentra_terminal_ui.py`: **5 passed**.
- `ast.parse` dos arquivos `terminal_ui.py` e `repl.py`: aprovado.
- `python -B -m sentra_cli --version`: `sentra-cli 1.1.0`.
- Revisão ampliada de 71 testes da CLI: **67 passed, 4 failed**. Falhas em `test_browser_host_ready_adopts_compatible_existing_launcher`, `test_responses_stream_enforces_absolute_deadline`, `test_chatgpt_web_rejected_preflight_error_is_concise_and_not_uncertain`, `test_wait_browser_host_turn_ready_waits_through_session_refresh`: rotas de `ModelClient`/browser host fora desta revisão visual, a investigar separadamente.
- A nova tela interativa foi verificada por saída ANSI/cálculo de geometria e simulação de teclado, **não por captura real de um console visível do usuário**.
- `sentra.cmd` global aponta para `sentra-cli.cmd` deste checkout; para carregar o módulo Python atualizado o operador deve sair do terminal antigo (`/exit`) e iniciar `sentra` novamente.
- Sem commit/push, sem reiniciar serviços, sem builds do frontend e sem alterar o workspace Oxta nesta rodada.

## Notas de segurança e ergonomia

A edição do prompt elimina sequências de controle, não interpreta texto como comando de ferramenta sem o mecanismo existente e mantém comportamento fail-closed fora de console compatível. Uma tentativa de abrir um CMD auxiliar pelo agente remoto não criou uma janela visível; seus processos de teste foram encerrados e a sessão CLI original do usuário foi preservada.
