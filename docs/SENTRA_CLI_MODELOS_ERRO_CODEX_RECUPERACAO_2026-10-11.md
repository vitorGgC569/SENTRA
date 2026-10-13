# SENTRA CLI — seletor de modelos, histórico e erro Codex nativo

## Relato do usuário
A CLI centralizada exibiu duas vezes `Native Codex turn failed ...`, depois listou `/models`, mas a digitação `5` foi tratada como prompt e recebeu `UncertainCall`. `/session` mostrou a conversa `f3613f9580c44a4bba986ab5dfd9ae0f` em estado `uncertain`, com chamada de provedor `bddaebc190c74cc1ad6c75da2aad3802`. A conversa foi preservada e **não** foi reenviada nem resolvida automaticamente.

## Implementação (checkout compartilhado)
- `sentra_cli/terminal_ui.py`: seletor nativo numerado centralizado, junto do input de escolha; usa geometria responsiva em vez de tabela Rich descartada na próxima limpeza de tela. Cor/contraste consistentes.
- `sentra_cli/repl.py`: `/models`, `/model` e `/model list` entram no seletor nativo; a próxima entrada `N` escolhe o índice sem despachar texto ao provedor; `0` cancela. `/model N` também resolve índice pelo catálogo. O histórico compacto deixa de tentar reimprimir tabelas/JSON completos; preserva mensagens e resumos curtos e mostra streaming como resposta parcial. `UncertainCall` apresenta recuperação segura, sem repetir efeitos. `/clear` abre sessão nova sem apagar a anterior, explicitado no texto da interface.
- `sentra_cli/agent.py`: removida duplicação de texto de erro do provedor durante projeção incremental, preservando o journal e o estado `uncertain`.
- `sentra_cli/codex_native.py`: falhas nativas categorizadas por classe conhecida (`rate_limited`, `authentication`, `quota`, `network_or_timeout`, `model_unavailable`, `sandbox_or_permission`, `unknown`) a partir do evento nativo, sem exibir mensagens brutas contendo tokens ou informações privadas.
- `/doctor codex`: comando somente de leitura para consultar caminho/versão, status de autenticação e quantidade de chamadas incertas na sessão atual.

## Diagnóstico da ocorrência específica
O comando `codex.exe` foi encontrado, a versão `0.162.1` foi observada e `codex login status` indicou autenticação ChatGPT. A ajuda pública de `codex exec` reconhece os flags usados pelo adaptador. Isso não comprova disponibilidade do serviço/modelo no momento da falha. O evento antigo registra `turn.failed`, mas não armazena um diagnóstico seguro detalhado; portanto a **causa física da falha antiga continua desconhecida**.

## Testes
- `python -B -m pytest -q -p no:cacheprovider tests/unit/test_sentra_cli_model_picker_20261011.py tests/unit/test_sentra_terminal_ui.py tests/unit/test_codex_native_provider.py tests/unit/test_sentra_shell_live_preview.py`: **22 passed**.
- Regressão ampla `test_sentra_cli.py`, `test_sentra_cli_model_effort.py`, `test_sentra_cli_browser_host.py`, `test_sentra_cos_cli_canvas_entrypoints.py`: **67 passed, 4 failed**. Falhas remanescentes em teste de browser launcher, deadline de Responses e preflight Web; não são uma nova chamada ao Codex nem comprovação da raiz desta ocorrência.
- Sintaxe Python analisada, `python -B -m sentra_cli --version` informa `sentra-cli 1.1.0`.
- Sem novo `codex exec`, sem alteração/limpeza da sessão incerta, sem `git reset/commit/push`. Não houve inspeção por captura visual de um console aberto na sessão do usuário.

## Uso
Sair do processo CLI atual com `/exit` e executar `sentra` novamente carrega os módulos Python atualizados. `/models` seguido de `5` apenas seleciona o modelo correspondente ao catálogo **atual**. Enquanto a conversa antiga estiver incerta, novas gerações nela permanecerão bloqueadas. `/session` exibe recibos; `/resolve <call> <done|not-run> <evidence>` só deve ser empregado com evidência real, nunca por suposição. `/clear` **abre uma conversa nova** sem excluir a antiga, caso o usuário escolha trabalhar numa nova sessão sem tentar repetir o mesmo envio incerto.
