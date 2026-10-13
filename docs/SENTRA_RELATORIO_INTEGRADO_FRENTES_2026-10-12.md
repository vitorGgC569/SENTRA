# SENTRA — Validação integrada das cinco frentes (12/10/2026)

## Escopo e segurança

Execução real via Desktop Commander no OGrandeOxta, checkout `C:\Users\vitor\OneDrive\Desktop\SENTRA`. As frentes delegadas P0 Debian, P0 Terminais, P1 Dots e P1 Imagens entregaram relatórios independentes em `docs/SENTRA_DELEGADO_*.md`. A frente P2 foi executada diretamente nesta conversa.

Checkout compartilhado preservado: nenhum reset, checkout, clean, commit, push ou rebase; nenhuma VM, VDI, Dot, conversa ou conteúdo de usuário excluído. Nenhuma operação `UNCERTAIN` foi reenviada. Ações físicas sobre VMs não foram executadas. Reinícios de relay e backend foram precedidos por verificação de ausência de operações ativas.

## P2 — interface inteligente real: CONCLUÍDA

1. `sentra_canvas/desktop_ui/src/shell-interactive-ui-schema.js`: parser declarativo limitado, seguro, sem HTML/JS/hook ou ferramentas; também aceita resposta integral `sentra-ui` seguida de JSON em único code span, conforme resposta observada de GPT real.
2. `sentra_canvas/desktop_ui/src/shell-interactive-ui.jsx`, `.css`, `shell-markdown.jsx`: métricas, texto, progresso, tabelas, escolhas e checklist em interação **somente local**.
3. `sentra_canvas/desktop_ui/test/shell-interactive-ui.test.mjs`: **3 passed** (inclui recusa de comandos, propriedades extras, IDs duplicados e conteúdo inesperado).
4. `npm run build`: Vite **2383 módulos**, materialização de `static/desktop-assets` e `desktop.html` na instância ativa, sem alteração dos dados do usuário.
5. GPT Web real: conversa QA `conversation-7bba7abb9191d2d4578b82d16800539b` do Dot `testegpt6`, operação original `op-84460014444c4d0976977fd414942971`; histórico protegido `completed`, 2 mensagens, 0 chamadas incertas. O GPT-6 gerou JSON válido com `metric/progress/table/choice`. A resposta foi validada pelo mesmo parser usado no Canvas.
6. Homologação real no Microsoft Edge headless, usando o Canvas instalado e a conversa original do GPT: **1 métrica, 1 progresso, 1 tabela, 4 opções, interação local confirmada, 0 erros JS**. Desktop 1440×920: `.tmp/qa-sentra-gpt6-real-smart-ui-render-20261012.png`. Mobile 390×844: `.tmp/qa-sentra-gpt6-real-smart-ui-mobile-20261012.png`; `window.innerWidth=390`, `document.documentElement.scrollWidth=390` (sem overflow horizontal).

**Limite:** interface inteligente *de apresentação*, não um aplicativo arbitrário ou novo mecanismo de ferramentas. Ações no host continuam exigindo protocolo WorkItem/Grant separado.

## P2 — copiar projetos completos: RECURSO IMPLEMENTADO; PROVA HOST→VM BLOQUEADA

- `sentra_executors/virtualbox_project.py`: `VBoxManage guestcontrol copyto --target-directory` corrigido para diretório destino e validação SHA-256 usando o nome exato do arquivo `<uuid>.tar` copiado.
- `tests/unit/test_virtualbox_project.py`: **4 passed, 1 skipped**, incluindo controles de isolamento e rejeição de guest não verificado.
- Prova com arquivos reais do repositório: snapshot do diretório `sentra_canvas/desktop_ui/src` com **69 arquivos**, **2.032.231 bytes** de origem, TAR real **2.088.960 bytes**, SHA-256 verificado, sem links e sem exclusões. Arquivo local `.tmp/p2-real-project-snapshot-20261012.tar`. **Isso não significa que a VM recebeu os arquivos.**
- Verificação read-only dos **dois VDIs reais** por `verify_guest`: ambos `owned_disk_not_verified_partitioned`, `installed_os_verified=False`, `desktop_ready_verified=False`. Não foi enviado arquivo à VM nem contornado o fail-closed. A instalação persistente é bloqueio da frente P0 Debian.

## Agentes delegados — execução comprovada e lacunas

- **P0 Debian:** relatório `SENTRA_DELEGADO_DEBIAN_PERSISTENTE_2026-10-12.md`, 47 testes do agente; DMI UUID agora aceita duas serializações exatas; VDI 64 GiB ainda vazio, `launch-intent` antigo presente; boot persistente, XFCE, Guest Additions e autenticação guestcontrol **não comprovados**. Não repetir a instalação incerta.
- **P0 Terminais:** relatório `SENTRA_DELEGADO_TERMINAIS_2026-10-12.md`; integração de interfaces SENTRA/OpenCode/Codex, ConPTY real, 8 + 18 testes; modelo OpenCode Muse Spark `#high` configurado no comando. Inferência real do Muse e conclusão autônoma do WorkItem **não comprovadas**; Antigravity somente aplicativo GUI (sem API inventada).
- **P1 Dots:** relatório `SENTRA_DELEGADO_DOT_LIFECYCLE_2026-10-12.md`; arquivamento **local**, preflight abrangente, recibos idempotentes e testes. Exclusão real, arquivamento remoto ChatGPT, revogação/fecho operacional de todos os recursos e remoção VDI não estão integralmente homologados; nenhum recurso real excluído.
- **P1 Imagens:** relatório `SENTRA_DELEGADO_GERACAO_NATIVA_CHATGPT_2026-10-12.md`; produtor Edge, relay binário autenticado, armazenamento protegido e testes de origem/lease/hash/mensagem. **Sem imagem nativa gerada e capturada do site real**, portanto sem prova Web→Canvas.

## Regressão integrada

- Integração conjunta Python: **149 passed, 1 skipped**, em **211.04 s**; abrange 17 módulos de VM, importação, terminais, coordenação, lifecycle, shell/Web, generated media e relay.
- Node `tests/unit/web_native_evidence.test.cjs`: **3 passed**.
- Node `sentra_canvas/desktop_ui/test/shell-interactive-ui.test.mjs`: **3 passed**.
- Sintaxe `node --check` de `service-worker.js`, `conversation-evidence.js` e parser: aprovada.
- `git diff --check` em arquivos relevantes: sem erros; avisos de normalização CRLF informativos.

## GPT-6 High em quatro conversas

- As quatro conversas foram iniciadas e fixadas em janelas separadas do Edge.
- Captura de seletor **Alta (High)** foi verificada visualmente nas janelas de terminais, ciclo de vida e imagens. Evidências: `.tmp/qa-edge-high-selector-window-20261012.png`, `.tmp/qa-edge-high-arquivamento-20261012.png` e `.tmp/qa-edge-high-nativa-20261012.png`.
- Na conversa Debian, a captura `.tmp/qa-edge-high-DMI-20261012.png` não permitiu ler o esforço atual no menu; pedido High constava do prompt, mas **não foi possível atestar sua seleção individual**. Não alterar seletor sem confirmação.

## Deploy e saúde dos serviços

1. `npm run build` materializou o Canvas atualizado.
2. Relay antigo escutava na porta 8765, PID 51716. Após comprovar `queued=0`, `leased=0`, `workers_online=0` e workspaces sem operações, foi reiniciado; novo PID **47492**, `uptime=5.9s`, fila e leases vazios.
3. Backend do Canvas reiniciado somente pela GUI **dona do broker** (processo pai 50416, filho 42984), preservando outras GUIs do checkout. Nova GUI PID **18136** e broker na porta **62862** com HTTP 200.
4. Regressão Playwright do GPT UI real **passou novamente após restart**, além do teste mobile.
5. Center respondeu a três workspaces com 0 operações ativas; ambas as VMs permaneceram registradas e running.
6. Extensão `SENTRA Browser Bridge` instalada/ativa como pacote unpacked do checkout; `sentra_source_hash` e `sentra-bootstrap.json` correspondem à fonte. **A extensão em execução não foi comprovadamente recarregada com o service-worker novo**: janela Edge estava sem foreground autorizado e não foi feito clique cego. Relay atualizado não substitui esse passo.

## O que permanece necessário

1. Reconciliação humana da instalação Debian anterior e **nova operação física admitida** para instalar no VDI, conferir XFCE/Guest Additions/guestcontrol e importar projeto real. Não reaproveitar/reemitir operação incerta.
2. Recarregamento seguro e verificável da extensão em `edge://extensions` e **prova positiva de imagem nativa ChatGPT Web → receipt binário → Canvas**, sem URLs arbitrárias.
3. Homologar inferência OpenCode Muse Spark High e orquestração real GPT-6 High, WorkItems com conclusão atestada.
4. Completar contrato de exclusão definitiva/arquivamento remoto de Dots; nenhuma exclusão física sem aprovação específica.
5. Confirmar High no seletor da conversa Debian quando a interface permitir observá-lo.

**Não declarar essas cinco pendências como concluídas pelo resultado dos testes unitários.**
