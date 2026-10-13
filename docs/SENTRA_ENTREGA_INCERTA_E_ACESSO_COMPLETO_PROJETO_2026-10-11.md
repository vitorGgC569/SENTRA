# SENTRA — diagnóstico de entrega incerta e acesso completo protegido ao projeto

## Incidente e causa confirmada

A tela do Dot testegpt6 mostrou `Resultado ainda não confirmado`. A leitura **sem reenvio** do ControlPlane confirmou que `op-31efbee967464cb2531015d47f0854dc` está no estado `UNCERTAIN` com código `shell_provider_unconfirmed`, sem recibo definitivo de resposta. A arquitetura separa resposta física do modelo de mero evento de envio, portanto o aviso não pode ser removido por aparência. Outra operação informada pertencia a escopo diferente e foi corretamente negada (403).

O Dot testegpt6 tem máquina de arquivos configurada, mas somente um WorkItem `RUNNING` com capability `workspace:file.read`. **Não** havia permissão comprovada de escrita, exclusão ou terminal. A autorização do ChatGPT Web dentro da própria interface do provedor não equivale a um Grant da máquina SENTRA.

## Implementação

- `sentra_canvas/service.py::shell_delivery_inspect` e rota GET `/api/shell/delivery`: inspeção autenticada, só leitura, ligada a projeto/Space/conversa/Operation, baseada no `canvas_shell_queue` e status durável do ControlPlane. Retorna indicação de confirmação física, códigos seguros e mensagem de diagnóstico, sem enviar ao modelo, criar efeito ou reutilizar uma solicitação incerta.
- `shell-conversation.jsx`: botão **Consultar diagnóstico sem reenviar** nas mensagens incertas, mostrando a causa projetada a partir do registro protegido.
- Seletor novo **Acesso completo ao projeto · protegido**, além de conversa, leitura e manipulação de arquivos. Aprovação explícita prepara duas máquinas distintas, quando ainda não existem: `workspace-files` (ler/escrever/excluir) e `terminal` (iniciar/ler/escrever/fechar terminal ConPTY). Cada máquina exige WorkItem independente, capability explícita, autorização registrada e verificação pós-escrita.
- `center_configure_machine`, `center_prepare_task`, `center_file_work_items`, `center_revoke_files`: suporte adicional ao terminal, com identidade da conversa e do Dot validada pelo servidor e Grants retidos no ControlPlane. Nenhum Grant ou WorkItem novo foi criado para o usuário nesta implementação.
- A lista **Trabalhos do Dot** agora distingue terminal de arquivos. A revogação consulta os WorkItems autorizados da conversa para não esquecer Grants antigos quando há upgrades (por exemplo, leitura → escrita).
- Mensagens de aprovação deixam explícito que este é **acesso ao projeto, não acesso irrestrito à máquina**, e que o transporte do ChatGPT Web ainda precisa encaminhar chamadas de ferramenta reconhecidas. O terminal permanece submetido às revisões, fencing, grants e escopo de execução existentes.

## Evidências

- `python -B -m pytest -q -p no:cacheprovider tests/unit/test_sentra_file_workitems_ui_api.py tests/unit/test_sentra_shell_live_preview.py tests/unit/test_sentra_terminal_ui.py` → **16 passed**.
- `npx vite build` para diretório de stage → êxito; `npm run build` para diretório servido → êxito.
- Broker parado por endpoint owner-auth somente após checagem de ausência de operações ativas entre as 50 recentes. Instância nova: PID **43960**, porta **65149**, health OK.
- GET `/api/center/task/files` para testegpt6 → HTTP 200, WorkItem de arquivo com capability somente de leitura.
- GET `/api/shell/delivery` de operação incerta pertencente à conversa → HTTP 200, `status:UNCERTAIN`, `reason_code:shell_provider_unconfirmed`, `automatic_retry:false`. Outra operação não vinculada à conversa → 403.
- SHA-256 de `desktop.js` e `desktop.css` servidos coincide com o manifesto.
- Nova janela nativa SENTRA aberta: PID **36372**. Janelas anteriores preservadas, sem descartar rascunhos.
- Backup de assets anteriores: `.tmp/sentra_access_assets_backup_20261011`.

## Limites de homologação

A função de autorização completa foi implementada e coberta por testes de escopo, mas **não foi exercitada com Grants reais no Oxta**, pois o clique de confirmação pertence ao usuário. Também **não foi executado um comando shell nem arquivo no Oxta** nesta rodada. Mesmo com as duas máquinas autorizadas, as chamadas só são executáveis se a rota do modelo emitir diretivas de ferramentas aceitas e puder atravessar o adapter host; o relay GPT Web direto não ganha ferramentas nativas apenas pela permissão. Continuam necessários testes ponta a ponta da concessão real, da execução autorizada e da revogação após uso.

Sem reset, commit ou push. O estado de operações `UNCERTAIN` foi preservado e não houve reenvio automático.
