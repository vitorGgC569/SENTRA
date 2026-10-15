# ASTRA — leitura integral da prévia no Desktop

Implementação em código React e bundle candidato. `validate_desktop_bundle` conferiu 128 assets e 140 inputs de fonte após o build atual. As provas abaixo usam navegador e HTTP isolados, sem conta de provedor, prompt real ou instalação homologada.

## Comportamento

`ShellStreamContent` oferece **Ver prévia completa** quando o head contém uma referência recuperável. A janela continua mostrando o trecho mais recente enquanto o modal consulta uma versão imutável, identificada como **Prévia salva · ainda não confirmada**. Nova referência da mesma operação exige a ação explícita **Consultar prévia mais recente**. Nenhuma leitura confirma a Operation ou repete o envio.

O cliente consulta apenas `GET /api/shell/stream/content`, com autenticação pelo módulo privado existente. Valida escopo, identidade, limites, cursores em pontos de código Unicode, tamanho UTF-8, hash de cada página e hash completo. Uma página adulterada, referência expirada ou autorização recusada não devolve corpo parcial como se fosse completo. Não há retry do leitor.

O conteúdo é texto simples em elementos `pre`; HTML do modelo não é interpretado. O modal conserva as páginas somente em RAM e as descarta ao fechar, trocar conversa/operação ou perder autenticação. Leituras antigas não podem substituir uma seleção nova, mesmo quando o transporte entrega depois do abort. Após 30 segundos sem avanço, a consulta é abortada e o trecho da conversa permanece. Um novo progresso rearma esse prazo; não é um limite total de geração.

O histórico canônico e seu leitor `message_content` permanecem separados. O cache de conversas não guarda as páginas da prévia, referências, recibos ou autoridade. O modal usa virtualização acima de 80 páginas e restaura o foco ao botão de abertura quando continua no mesmo escopo.

`reconcileLivePreview` conserva texto e referência juntos em frames somente de estado. Uma janela deslocada ou uma referência nova pode ter menos unidades UTF-16 e ainda assim conter texto mais recente; nesse caso não se reutiliza o texto antigo por ser maior. A apresentação de cadência conserva o conteúdo já sanitizado pelo servidor, incluindo `[[wiki]]`, Unicode e colchetes literais. O backend/CLI usam `sentra_core.model_prose.prose_prefix` para mascarar somente os cabeçalhos estruturados da gramática CLI.

## Evidências

- `tests/qa/astra_stream_content_browser.py`: **14 cenários aprovados**, nenhum erro JavaScript. Inclui reconstrução Unicode e markup literal, foco, resposta atrasada, troca de operação/conversa, seleção explícita mais recente, 403/404/integridade, cancelamento antes dos cabeçalhos/durante corpo, perda de autenticação e timeout.
- Corpo grande: **5.439.505 caracteres em 84 páginas**, conferência dos trechos no início/meio/fim; máximo de **11 páginas no DOM** nas amostras da execução final. Leitura em 1,453 s nessa amostra local sintética; não é meta de latência nem medição de instalação.
- Silêncio no corpo: abort em **30,438 s**, sem retry, prompt ou alteração da prévia curta.
- `node --test test/*.test.mjs test/experience-cadencia/*.test.mjs`: **145 aprovados**, incluindo integridade da prévia, janelas Unicode e cancelamento do leitor canônico durante resposta/hash.
- `python -m pytest tests/unit/test_agent_prose_stream.py tests/unit/test_conversation_persistence.py -q`: **18 aprovados**. Executam o loop CLI real com provedor sintético, colchetes fragmentados, diretiva concluída uma única vez, argumentos incompletos ocultos inclusive em erro de provedor e transcript preservado.
- `tests/qa/astra_chat_turn_browser.py`: **12 cenários aprovados** após integração, incluindo criação/resposta perdida, conversa fora da primeira página, pendências, bridge nativa simulada e troca de projeto.

Relatórios: `.tmp/astra-stream-content-browser/report.json`, `.tmp/astra-ui-current-tests.log`, `.tmp/astra-agent-prose-tests.log` e `.tmp/astra-chat-turn-qa/report.json`. Capturas do leitor foram inspecionadas; não representam a janela produtiva atual.

## Limites

Ainda faltam publicação pelo caminho autorizado na janela instalada, retomada da autenticação nativa instalada, inferências simultâneas reais, suspensão do Windows e falhas combinadas. O limite recuperável de 8.000.000 bytes pertence ao backend; limites anteriores dos produtores continuam descritos em `ASTRA_STREAM_CONTENT.md`. Não se recuperam bytes que nunca chegaram a ser persistidos.
