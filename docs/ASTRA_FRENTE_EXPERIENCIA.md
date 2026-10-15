# ASTRA — frente de experiência e renderização

Implementação candidata para revisão/integração pelo coordenador. O objetivo integral do ASTRA continua fora do escopo desta frente. Nenhum broker, conta, configuração do Codex ou serviço instalado foi reiniciado/alterado. O bundle global e a matriz principal continuam com o coordenador.

## Entregas

- `shell-markdown.jsx`: lexer GFM com listas aninhadas, listas numeradas preservando início, tarefas, tabelas com cabeçalhos, citações, ênfase, referências, código selecionável e copiar por teclado/mouse. HTML bruto fica texto; links admitem apenas HTTP(S) sem credenciais; imagens Markdown viram links explícitos, evitando carregamento remoto implícito. O componente inteiro e blocos concluídos usam memoização; `sentra-ui` continua no renderer limitado já existente e sua interação prepara rascunho.
- `shell-message-window.jsx` + `shell-conversation.jsx`: DOM limitado acima de 80 mensagens carregadas, alturas observadas e espaçadores, busca sobre todo o conjunto carregado, modo completo explícito para leitura assistiva/busca nativa. Preserva âncora em inserções anteriores, novas mensagens e alternância completo/otimizado. Mantém o botão para voltar ao fim. A pesquisa posiciona o primeiro resultado no topo. O log não anuncia cada mutação da janela; uma região curta anuncia resposta disponível.
- `shell-computer-resize.jsx` + `shell-dot-computer.jsx`: arrastar borda ou usar setas/Home/End/Shift para ajustar o painel; largura persiste localmente, respeita espaço do chat e cede ao layout estreito/expandido. O controle só muda apresentação.
- `shell-home-resume.jsx` + `shell-navigation.js`: continuar contexto existente e consultar conversas que exigem atenção. Preferências locais são conferidas contra o projeto, Space e conversa canônicos; uma preferência antiga não oferece conversa removida/de outro projeto nem substitui identidade do Dot. Nenhuma consulta reenvia tarefa.
- `shell-polish.css`: tabelas/código, foco, metadados do chat em 12 px, estados de histórico, Home e controle de largura. Movimento reduzido desativa animações/transições/rolagem suave.

Integração indispensável no `shell-app.jsx`: **somente import de `HomeResumePanel` e uma composição antes de `shell-home-start`**. As alterações anteriores no arquivo foram preservadas. `package.json` e raiz de `package-lock.json` passam a declarar diretamente `marked` **17.0.6**, versão já presente como dependência transitiva; não houve atualização geral de pacotes.

## Verificação executada

Comando: `python -B tests/qa/astra_experience_browser.py`. O script abre Vite isolado em porta temporária e Chromium, testa componentes de produção com dados sintéticos, encerra seu próprio processo e não chama modelos/contas/serviços produtivos. Fixture: `sentra_canvas/desktop_ui/qa/experience.html` + `.jsx`.

Recibo: `.tmp/astra-experience-qa/report.json`.

- 1.000 mensagens sintéticas: **13 nós de mensagem inicialmente / 21 no meio**, com acesso ao modo completo. Inserção no início/fim e alternância completo/otimizado mantiveram a âncora.
- Listas, tabelas, código, clipboard Unicode, referência, HTML/URL perigosos inertes e identidade DOM do código concluído durante deltas: aprovados.
- Painel: mouse, teclado, reload com largura salva: aprovados.
- Conversa: busca, vazio, nova mensagem sem puxar leitura, voltar ao fim: aprovados.
- Home: continuar abre conversa canônica e consultar abre a conversa incerta sem reenvio: aprovado.
- 390 px, 720 px e CSS zoom 200%: sem overflow horizontal. Modo escuro e movimento reduzido renderizados. Árvore acessível salva em `conversation-aria.txt`.
- React Profiler **de desenvolvimento**, 30 deltas em cerca de 20 mil caracteres: valor p95 por commit no recibo. **Não comprova a meta de 300 ms adaptador→pintura nem carga com modelos reais.**
- Zero `pageerror` no ensaio.

Capturas inspecionadas: `markdown-1440.png`, `markdown-390.png`, `conversation-markdown-390.png`, `conversation-dark-390.png`, `conversation-css-zoom-200.png`, `home-390.png`, `home-1440.png`, `history-window-1440.png`, `computer-resized-1440.png`, todas em `.tmp/astra-experience-qa/`.

Build Vite isolado: `.tmp/astra-experience-build/`, log `.tmp/astra-experience-build.log`, exit **0**. **Não escrevi em `sentra_canvas/static` nem no manifesto global.** Persistem avisos anteriores de scripts clássicos e chunk principal grande.

Regressão direcionada: **35 testes JavaScript aprovados** (navigation, resume scope, UI schema/reply, live feed, cadence). Suíte JS completa: **113 aprovados / 1 falhou**, log `.tmp/astra-experience-node.log`. A falha está em `shell-update-icon-contract.test.mjs:16`: espera o cleanup inline `endCanvasMaintenance...`; o código atual usa `finishUpdateAttempt()`, que esta frente não modificou. Coordenador deve revisar esse contrato com os testes de atualização; a falha não foi escondida nem relaxada aqui.

## Limites e continuidade

- Falta revisão do coordenador e regeneração/publicação do bundle global, seguida de QA integrado no Canvas instalado.
- A árvore acessível e teclado foram verificados automaticamente; validação manual com NVDA/leitor de tela e zoom nativo do WebView permanece pendente. CSS zoom é evidência de layout, não homologação de todas as tecnologias assistivas.
- Virtualização reduz nós/layout; dados já carregados continuam em memória. Busca é explícita sobre mensagens carregadas; o histórico integral existente segue no menu de pesquisa.
- O painel nativo, VM, imagem real, autenticação, Federation, instalação limpa e ensaios de carga real não foram substituídos por este QA de apresentação.
