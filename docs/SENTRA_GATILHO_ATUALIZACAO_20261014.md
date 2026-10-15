# SENTRA — aviso automático de atualização de código
Data: 14/10/2026

## Objetivo

Notificar mudanças efetivas no checkout local diretamente na barra superior do Canvas, no estilo de aplicativos desktop com aviso **Atualização disponível**, sem disparar instalação, reload, reenvio de prompt ou encerramento de serviços automaticamente.

## Implementado

1. A janela nativa `WindowControls.check_update_notification()` agora oferece uma leitura somente de status, sem devolver tokens ou caminhos. O código compara a data de alteração do frontend com o último bundle, e o backend atual com a janela e com o início do broker autenticado.
2. O Canvas expõe `runtime_started_at_ns` em `/api/health` autenticado para evitar perder mudanças realizadas antes de a janela ser aberta enquanto um broker antigo persistia.
3. A interface verifica a cada 90 segundos quando visível, ao voltar o foco, após retorno da janela ao primeiro plano e após `pywebviewready`. Não compila ou reinicia automaticamente.
4. Quando necessário, aparece uma opção na barra superior e um banner discreto com **Atualizar agora** e **Mais tarde**. A dispensa da revisão fica registrada em `sessionStorage`; novo código muda a revisão e reabre o aviso.
5. Alterações apenas da interface usam o fluxo existente `check_code_updates -> apply_code_updates`, com aprovação. Alterações em Python usam o `check_full_updates -> apply_full_updates` coordenado, com proteção do ledger e confirmação explícita, preservando CLIs, VMs e sessões externas.
6. Para janela nativa aberta com o bridge antigo, existe fallback de detecção **apenas da interface** por `check_code_updates` já existente. O novo método nativo completo é carregado na próxima abertura do aplicativo.
7. Executáveis congelados/instalados não exibem uma atualização de código como se fosse uma nova versão assinada: um instalador com manifestos de assinatura e rollback ainda requer pipeline específico.

## Arquivos

- `sentra_canvas/native_refresh.py` — classificador read-only da atualização local.
- `sentra_canvas/native_app.py` — bridge nativa e baseline de código.
- `sentra_canvas/__main__.py` — marca do início do broker autenticado.
- `sentra_canvas/desktop_ui/src/shell-update-trigger.js` — classificação visual e compatibilidade.
- `sentra_canvas/desktop_ui/src/shell-app.jsx` — monitor e ação opt-in.
- `sentra_canvas/desktop_ui/src/desktop.css` — apresentação.
- `tests/unit/test_native_update_trigger.py` e `sentra_canvas/desktop_ui/test/shell-update-trigger.test.mjs`.

## Homologação e operação

- Testes isolados Python e JavaScript foram aprovados, incluindo trabalho sobre uma janela aberta depois de o broker antigo ter iniciado.
- O frontend foi compilado pelo atualizador seguro `native_refresh.apply`; status `built` e `frontend_stale=False`.
- Em seguida `native_refresh.apply_all` confirmou `local_code_updated`, `broker_restarted=True`, `installed_version_changed=False`.
- O último broker autenticado retornou `runtime_started_at_ns`, e os hashes de `desktop.js`, `desktop.css` e `bootstrap.js` conferiram com `manifest.json`.
- Nenhum commit, push, reset ou reinstalação de versão assinada foi executado.
- A janela atualmente aberta precisa ser recarregada; para que o **novo método nativo** esteja presente, reabrir o aplicativo uma vez. Depois disso a verificação é automática.

## Pendências distintas

- Não é um mecanismo de atualização pela internet: não baixa releases, não instala pacotes assinados e não faz rollback de um novo instalador.
- Polling de 90 segundos é intencionalmente leve, não é file watcher em tempo real.
- O fluxo de instalação de futuras versões binárias deve contar com manifesto autenticado, assinatura, transação, atualização externa ao executável e rollback.
