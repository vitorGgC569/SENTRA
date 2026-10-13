# Prévia visual solicitada pelo usuário

Em 11/10/2026, o usuário pediu abrir a frontend nova do Prisma apenas para
ver seu estado, sem interação nem expectativa de funcionalidade. Essa instrução
autorizou materializar o bundle necessário para exibi-la; não liberou testes,
lint, benchmarks, QA ou homologação das outras frentes.

Foram executados `npm install --ignore-scripts --no-audit --no-fund` e
`npm run build` em `sentra_canvas/desktop_ui`. Package-lock e assets locais
foram gerados a partir das fontes atuais de Prisma e Tessela. O build emitiu
avisos de peers TipTap 3.31.4 versus pins 3.31.3 e tamanho de chunks; isso
permanece trabalho de empacotamento, sem afirmação de aceitação.

A abertura encontrou um SyntaxError em `tool_exposure.py` na declaração de
`publication`; Pacto corrigiu a quebra de linha em seu ownership. A segunda
abertura iniciou a janela nativa `SENTRA`, PID 47408, HWND 27529178, em
11/10/2026 às 06:40:12, com a superfície materializada `desktop.html`.

Estado isolado: `.tmp/integral-ui-preview/state/canvas`. O projeto SENTRA foi
associado por seu caminho existente, sem copiar recursos, iniciar modelos ou
reattach de terminais de trabalho. O launcher de prévia vive em
`.tmp/integral-ui-preview/open_preview.py`; os metadados sem credenciais estão
em `window.json` no mesmo diretório. A janela permanece aberta para o usuário.

Isso comprova a geração e abertura da prévia solicitada, não a validação
funcional, a fidelidade visual aceita ou a implementação integral do objetivo.
Nenhum gate final foi liberado.
