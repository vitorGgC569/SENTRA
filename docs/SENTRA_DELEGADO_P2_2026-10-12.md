# SENTRA — P2: projetos na VM e interface inteligente
Data: 2026-10-12

## Responsabilidade / checkout compartilhado

Esta frente foi executada enquanto as frentes P0 VM, P0 terminais, P1 ciclo de Dots e P1 imagens nativas foram delegadas em quatro conversas separadas do ChatGPT. Nenhum reset, checkout, commit, push ou rebase. Não reiniciei aplicações, relays ou VMs. Não alterei arquivos de execução das outras frentes.

## Entrega A: projeto completo host → VM

**Código:** `sentra_executors/virtualbox_project.py` e `tests/unit/test_virtualbox_project.py`.

- Corrigido o destino de `VBoxManage guestcontrol copyto`: `--target-directory` recebe diretório remoto, não um caminho de arquivo `.tar`.
- SHA-256, extração e limpeza no convidado utilizam agora o nome *exato* do tar de origem, gerado aleatoriamente para a importação. Antes, a implementação tentava verificar o inexistente `snapshot.tar` após copiar `<UUID>.tar`.
- Preservados os guards do implementador original: diretório do projeto autorizado, rejeição de symlinks/junctions/hardlinks, exclusão de arquivos sensíveis, limites de 100.000 arquivos e 2 GiB, arquivo derivado de snapshot e controle de acesso pelo WorkItem da VM.
- Adicionados testes de contrato da cópia, verificação SHA-256/extracão com o nome real e bloqueio da operação quando `installed_os_verified=False`.
- **Prova real host→guest pendente.** A importação só pode ser executada numa VM Debian persistente cuja identidade foi verificada, e a instalação física é responsabilidade da frente P0. Não foi contornado esse pré-requisito nem iniciado efeito físico.

## Entrega B: UI inteligente declarativa do Dot

**Código:**
- `sentra_canvas/desktop_ui/src/shell-interactive-ui-schema.js`
- `sentra_canvas/desktop_ui/src/shell-interactive-ui.jsx`
- `sentra_canvas/desktop_ui/src/shell-interactive-ui.css`
- `sentra_canvas/desktop_ui/src/shell-markdown.jsx`
- `sentra_canvas/desktop_ui/test/shell-interactive-ui.test.mjs`

- Mensagens do Dot podem conter um bloco ```sentra-ui` com documento JSON schema versão `1`. Quando é válido, o Canvas rende cartões de métrica, texto, progresso, tabelas, opções e checklist; caso inválido, conserva o bloco como código visível.
- Limites explícitos: 32 KiB/documento, 36 elementos, tamanho de texto e número de linhas/colunas/opções limitados, IDs únicos.
- React escapa todo texto. Não aceita HTML, JavaScript, iframes, URLs embutidas, código de ferramenta, hooks, submit, rede ou escrita de estado do host.
- Controles de escolha e checklist são **locais à visualização** e não disparam ferramentas/ações externas. Uma UI agente executável demandará protocolo separado com Grants, WorkItems e recibos.
- Testes rejeitam objetos de ação, campos extras, IDs inválidos, HTML embutido como campo, progresso fora do limite, excesso de bytes e duplicidade.

### Exemplo simples

```sentra-ui
{"version":1,"title":"Progresso","elements":[{"type":"metric","label":"Tarefas","value":"4/5"},{"type":"progress","label":"Conclusão","value":80},{"type":"choice","id":"details","label":"Exibir","options":["Resumo","Detalhado"]}]}
```

## Testes da rodada

- `python -B -m pytest -q -p no:cacheprovider tests/unit/test_virtualbox_project.py`: 4 passed, 1 skipped.
- `node --test sentra_canvas/desktop_ui/test/shell-interactive-ui.test.mjs`: 2 passed.
- `npx vite build --outDir '../../../.tmp/sentra-smart-ui-validation-20261012' --emptyOutDir`: concluído com sucesso, apenas aviso de bundle grande.
- `git diff --check` restrito aos arquivos desta frente: aprovado.
- Build isolado em `.tmp/`, não foi feito deploy/restart em tempo de operação de outros agentes.

## Pendências e limites

1. Necessária VM persistente Debian instalada e `guestcontrol` validado para importar projeto **de verdade**.
2. UI renderiza documentos seguros; ainda não existe geração automática do schema pelo GPT com UX de edição/cópia e ações autorizadas.
3. Validar UI em conversa real do Canvas após deploy seguro com o sistema sem operações ativas.
4. Não confundir UI local de escolhas com execução de ações no host: esta diferença é intencional.


## Adendo de homologação real e deploy — 12/10/2026

- **Canvas atualizado na instância ativa:** `npm run build` concluiu e materializou assets em `sentra_canvas/static/desktop-assets`. Backend do Canvas reiniciado em janela sem operações ativas; novo broker na porta 62862.
- **GPT-6 Web real:** conversa `conversation-7bba7abb9191d2d4578b82d16800539b` concluiu com JSON `sentra-ui`, sem `UNCERTAIN`; o renderer passou a aceitar também a variante com uma única crase envolvendo o JSON, mantendo schema restrito.
- **QA visual ponta a ponta:** Playwright Microsoft Edge usou a conversa GPT-6 real no Canvas instalado. Desktop 1440×920 e mobile 390×844; métricas, barra, tabela e seleção interativa conferidos, 0 pageerrors, mobile sem rolagem horizontal. Evidências `.tmp/qa-sentra-gpt6-real-smart-ui-render-20261012.png` e `.tmp/qa-sentra-gpt6-real-smart-ui-mobile-20261012.png`.
- **Snapshot de projeto real:** 69 arquivos da pasta `sentra_canvas/desktop_ui/src`, TAR 2.088.960 bytes e SHA-256 conferido, sem importação ao guest. `verify_guest` dos dois VDIs retornou `owned_disk_not_verified_partitioned`, ou seja, instalação não atestada. Transferência física segue bloqueada corretamente.
- **Regressão de cinco frentes:** 149 passed, 1 skipped (Python); 3 passed (Node media); 3 passed (Node UI). Relatório central em `docs/SENTRA_RELATORIO_INTEGRADO_FRENTES_2026-10-12.md`.
