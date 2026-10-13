# SENTRA — Relatório delegado: geração nativa ChatGPT Web → Edge/relay → Canvas
**Data:** 2026-10-12  
**Frente:** GERACAO_NATIVA_CHATGPT  
**Computador:** OGrandeOxta, Desktop Commander online  
**Checkout:** `C:\Users\vitor\OneDrive\Desktop\SENTRA`  
**Resultado:** implementação local + testes aprovados; prova real do site ChatGPT **NÃO obtida**. Não promover automaticamente a produção.

## Escopo e proteção do checkout
- `git status --short` foi inspecionado ANTES das edições. Já havia dezenas de modificações (inclusive em service-worker.js, conversation-evidence.js, relay.py e manifest.json) e diversos arquivos novos, devido às demais frentes em paralelo. Edições cirúrgicas preservaram o conteúdo preexistente; novos arquivos apenas nesta frente.
- Sem `git reset`, `checkout`, `clean`, `commit`, `push`, `rebase`; sem reiniciar aplicativo, relay ou extensão; sem invocar Send/Web submit, alterar Grants ou tocar VMs, terminais, ciclo de vida ou smart UI.
- Não houve alterações em chats/Dots reais, WorkItems existentes, discos/VMs, operações com efeito incerto, leases ou fences originais. Fixtures criaram dados descartáveis em tempdirs.
- GPT-6 nesta conversa; a seleção de **esforço High não é verificável pelo conector**. Desktop Commander e OGrandeOxta estavam disponíveis.

## Auditoria do caminho produtor/consumidor
- `sentra_core/generated_media.py`: consumidor/validador legado de resposta de provedor (MIME PNG/JPEG/PDF, SHA256, base64 canônico, bytes reais, armazenamento criptografado de 64 KiB, identidade de chamada de provedor iniciada). Esse caminho NÃO pode ser usado diretamente para WebSend `websend_`: o Web relay utiliza outra autoridade e outra persistência. Arquivo auditado e não editado.
- `sentra_canvas/shell_generated_media.py`: exige autorização de conversa/escopo, manifesto protegido, recibo confirmado e operação `SUCCEEDED` para leitura. Alterado pontualmente para consumir também a tabela nova de mídia Web; não confunde com imagens geradas por código/texto.
- `sentra_canvas/desktop_ui/src/shell-generated-assets.jsx`: já verifica tamanho, MIME e SHA256, usando `apiBinary` autenticado, URL de objeto local e download. Auditado e não editado.
- `edge_extension/service-worker.js`, `conversation-evidence.js`: produtor Web originalmente ausente, apesar de já haver observações parent/assistant vinculadas ao documento e request_id.
- `native_bridge/relay.py`, `web_send.py`, `web_evidence_ingress.py`, `browser/streaming.py`: auditados. O relay registra recibo original e frame com prova independente; streaming conserva apenas texto. Mantidos fences, lease original, recibos e ausência de replay de efeitos.

## Alterações de código
1. **`edge_extension/conversation-evidence.js`**: extrai exclusivamente `image_asset_pointer` canônico com `file-service://file-…` em partes da mensagem *assistant* comprometida no React/Fiber; exige associação ao único filho da mensagem do usuário com `metadata.request_id`, rota e documento. Retorna `assets` junto ao frame. Rejeita objetos não suportados, ID não canônico, URLs de Markdown, repetição de IDs, tool outputs e pais ambíguos.
2. **`edge_extension/service-worker.js`**: após observação autenticada de resposta final `ANSWERED`, realiza GET de somente uma URL montada internamente, `https://chatgpt.com/backend-api/estuary/content?id=<file-id>`, com `redirect:'error'`, `cache:'no-store'`, credenciais do próprio origin e aceitando PNG/JPEG. Não segue links fornecidos pela página. Revalida aba, documento, epoch, worker, job, token do lease e request_id antes de cada etapa. Limita 4 imagens/turno, 8 MiB/imagem, calcula SHA256 e MIME, transmite blocos de até 64 KiB ao relay. A assinatura do frame inclui IDs de arquivos, não só texto. Latch de finalização impede tratar upload incompleto como resposta entregue ao Canvas; recuperação é somente de observação, nunca novo Send.
3. **`native_bridge/web_generated_assets.py`** (novo): persistência protegida via `JobStore._seal/_unseal` (DPAPI/keyring), manifestos, conjunto esperado de file IDs, chunks e estado finalizado. Verifica Grant/WorkItem/Run/Operation obtidos exclusivamente do binding host, worker/lease original, extension source/collector, request_id, documento/epoch, recibo exato, assistente final independente, formato e integridade byte a byte com `validate_asset`. Replay idêntico é idempotente; colisão de identidade ou bytes divergentes é recusada. `finalize` responde com recibo `type: sentra.generated_asset`, transport, IDs de operação/conversa/mensagem, tamanho, SHA256 e MIME; não expõe base64 no recibo.
4. **`native_bridge/relay.py`**: routes autenticadas `/jobs/generated-asset/chunk` e `/jobs/generated-asset/finalize`, body estrito e origem `chrome-extension://` com bearer existente; conteúdo de browser sem origin/bearer não é confiável. `/jobs/response-frame` aceita `native_file_ids` na mesma prova da resposta assistente e mantém compatibilidade com o frame texto anterior.
5. **`sentra_canvas/shell_web.py`**: `observe` aguarda a finalização de **todos** os arquivos declarados antes de publicar a operação final. Sem todos os bytes confirmados, não publica mídia nem resposta final; conserva necessidade de reconciliação sem reenvio.
6. **`sentra_canvas/shell_generated_media.py`**: publicação de manifestos Web somente sob `websend_` `ANSWERED`, recibo host existente, owner/Run/WorkItem/Operation/Dot correspondentes; leitura delegada ao armazenamento nativo por operação e ao gate atual de mensagem confirmada.
7. **`edge_extension/manifest.json`**: atualizado somente `sentra_source_hash` para o conteúdo-fonte efetivo. Valor calculado e conferido: `e0e6da8358b595cd6c823e228bdad7072d310fc98ea9d48f0ef91fc84085303f`. Não houve reload/ativação forçada.

## Evidências e recibos de execução no OGrandeOxta
- Processo de teste Desktop Commander **PID 28472**, executado realmente via `start_process` e consultado com `read_process_output`, **exit code 0**, runtime **41.37s**. Comandos: `python -m py_compile native_bridge/web_generated_assets.py native_bridge/relay.py sentra_canvas/shell_generated_media.py sentra_canvas/shell_web.py`, `node --check edge_extension/service-worker.js`, `node --check edge_extension/conversation-evidence.js`, `node --test tests/unit/web_native_evidence.test.cjs` e `python -m pytest -q tests/unit/test_web_native_generated_assets.py tests/unit/test_shell_generated_media.py tests/unit/test_sentra_cos_web_relay_authenticated_routes.py tests/unit/test_sentra_cos_web_v2_http_ingress.py tests/unit/test_sentra_cos_web_r6_full_cycle.py tests/unit/test_shell_web_preview.py`.
- Saída real: **3 testes JavaScript passaram (0 falhas, 91.4209ms)**; **33 testes Python passaram (0 falhas, 39.70s)**. `py_compile` e `node --check` terminaram sem erro.
- JS com VM de teste simula React committed Fiber: associação parent/assistant, exclusão de URLs/Markdown e de tool role, child incorreto, pointer não canônico ou duplicado.
- Python unit/integrado usa PNG real produzido por Pillow em tempdir **(NÃO imagem do site)**; cobre DPAPI no disco, hash de chunks, rejeição de URL externa, MIME e caminho falsos, source/worker/lease/document/epoch divergentes, Grant revogado, ownership isolado, replay idempotente e conflito, conjunto de imagens incompleto/UNCERTAIN, HTTP relay efêmero com Origin/bearer 401/403, `finalize` metadata e leitura via endpoint **real** `/api/shell/generated-media` do Canvas com 200 para mesma conversa e 401/403 para escopo inválido.
- `git diff --check -- edge_extension/service-worker.js edge_extension/conversation-evidence.js edge_extension/manifest.json native_bridge/relay.py`: **exit 0**. Advertências Git sobre normalização CRLF/LF são informativas; nenhuma operação de checkout foi efetuada.
- Verificação `extension_source_identity(...)` comparada com `manifest.sentra_source_hash`: `BUILD_MATCH=True`.

## Limites, riscos e pendências abertas
1. **Prova ponta a ponta do ChatGPT Web real PENDENTE.** Não houve nova geração de imagem no site, captura autenticada de arquivo real da sessão, nem recibo externo `sentra.generated_asset` de produção até o Canvas. Não confundir testes de fixture binária/HTTP local com prova Web real. Nenhuma operação `UNCERTAIN` foi repetida.
2. O endpoint de download permitido é *restrito a um único padrão* e deliberadamente bloqueia redirects, HTML, MIME inesperado, pointers diversos e URLs arbitrárias. **Não foi validado contra uma imagem nativa real da versão atual do site.** Se o ChatGPT usar outro endpoint ou redirect obrigatório, o sistema falhará fechado e será necessário verificar a rota real e o respectivo modelo de autenticação, sem afrouxar a segurança.
3. A estrutura React `image_asset_pointer` pode evoluir. Uma resposta assistente com parte não reconhecida não será atribuída como imagem gerada, por decisão explícita de fail-closed.
4. O build Edge não foi reiniciado/ativado. Manter instalação atual sem efeito; após coordenação humana e janela segura, validar bootstrap/collector source hash e testar geração nativa positiva com Run/WorkItem/Grant e conta física atestada, imagem final, receipt da operação, download e leitura no Canvas.
5. O fluxo Web-native implementado aceita PNG/JPEG (máx. 8 MiB por arquivo; até 4 por resposta), preservando PDF no consumidor de provedor anterior; não se afirma suporte Web-native a outros formatos nem URLs externas.
6. Sem conclusão de rollout de produção. Identidade física/modelo/effort e browser host independente ainda precisam estar disponíveis no teste real. **High não verificável nesta conversa.**

**Síntese:** implementação e testes locais concluídos; **entrega ponta a ponta pelo site ainda não demonstrada**. A ausência de prova positiva não foi convertida em confirmação nem em tentativa de reenvio. 

## Complemento — tentativa real de homologação em produção (12/10/2026)

**Solicitação:** executar a pendência de homologação nativa ChatGPT Web → Edge → relay → arquivo no Canvas. **Resultado da tentativa:** o preflight de produção falhou fechado, antes de qualquer nova mensagem/geração. **Não há recibo positivo de geração real do site** e não deve ser inferido de testes anteriores.

### Provas efetivas em serviços de produção
- Desktop Commander confirmou **OGrandeOxta online** e o checkout real. `git status --short` foi consultado antes de agir; código de outras frentes permanece compartilhado e inalterado por esta rodada.
- Relay vivo em `127.0.0.1:8765/health`, autenticado via bearer para operações protegidas. Resposta observada: `ok=true`, `submitted=39`, `completed=19`, `failed=20`, `queued=0`, `leased=0` no primeiro snapshot. Os totais são do relay histórico, **não** representam novas operações desta rodada.
- Heartbeat real da extensão: `online=true`, `sw_version=1.7.0`, `sw_build_id=sentra-edge-1.7.0-durable-r28`, `sw_source_hash=e0e6da8358b595cd6c823e228bdad7072d310fc98ea9d48f0ef91fc84085303f`. Esse hash **corresponde** ao código-fonte da extensão no checkout.
- `workers_online=[]`: **nenhuma aba ChatGPT adotada como worker** no instante da consulta. O Edge estava aberto, mas não foi detectada uma janela ChatGPT; a inspeção CDP local `127.0.0.1:9222` estava indisponível. Não foi criada/navegada/fechada nenhuma aba por este agente.
- O broker Canvas principal foi verificado pelo segredo protegido do próprio broker em memória, **sem revelar token**: `pid=42984`, `port=56561`, arquivo de endpoint `.sentra/canvas/broker.json`, `runtime_id_verified=true`. Esse broker é distinto da outra instância `pid=37316`, `port=56287`, com estado em `.tmp/qa-checkpoint-20261009/compiled-canvas-state2` (não apropriada como prova de produção).
- O endpoint autenticado `/api/workspaces` retornou 3 projetos. Consultas **read-only** `/api/shell/bridge` com `action=home`, sem expor conteúdo de chats: 3/3 retornaram `attachments.model_delivery_available=false` e `model_delivery_reason='binary_relay_not_configured'`. As três Runs estavam em `RUNNING`, portanto NÃO foi reiniciado o broker para forçar configuração; tampouco foi configurado um observer não atestado.
- O contrato `ShellWebRuntime` exige `web_relay.enabled`, modelos aprovados e callbacks de conta física e assistente independentes (`account_attestor` e `assistant_observer`). O broker atual não oferece esse transporte e não existe rota de HTTP com autoridade para injetar observers arbitrários — esse bloqueio é intencional.

### Recibo de preflight reproduzível
Foi criado `scripts/commander/qa_native_asset_production_probe.py` como **somente leitura**: utiliza `read_endpoint` protegido, autentica o broker em memória, consulta o health do relay, compara o hash da extensão ao checkout e verifica a disponibilidade do relay na projeção `home` de cada projeto; imprime apenas contagens, estados e tags de projeto com hash, nunca tokens/prompts.

Execução real no Desktop Commander: processo **PID 53028**; `read_process_output` reportou **exit code 1** (preflight reprovado). Fragmentos essenciais:
```json
{"canvas_broker":"verified","pid":42984,"port":56561,"runtime_id_verified":true}
{"relay_live":true,"relay_queued":0,"relay_leased":0,"extension_online":true,"extension_build_matches_checkout":true,"online_workers":0}
{"project_tag":"96438791c6","status":"readable","relay_ready":false,"relay_reason":"binary_relay_not_configured"}
{"project_tag":"97c4eb092e","status":"readable","relay_ready":false,"relay_reason":"binary_relay_not_configured"}
{"project_tag":"680ceb4239","status":"readable","relay_ready":false,"relay_reason":"binary_relay_not_configured"}
{"production_native_asset_admission_ready":false,"real_image_generation_attempted":false,"real_generated_asset_receipt_verified":false}
```

### Desbloqueios necessários — sem criar autoridade fictícia
1. Compor o **Canvas broker principal** com `web_relay` habilitado no host, modelos aprovados e *observadores físicos reais* de conta, modelo/effort e mensagem assistente; o mecanismo atual do Canvas falha fechado sem isso. Não modificar Grants nem fazer injeção HTTP de callbacks. Identificar também a convivência com o relay independente que já ocupa a porta 8765, antes de qualquer implantação/restart; não interromper operações existentes.
2. Ter uma aba `chatgpt.com` existente, autenticada e elegível à adoção, reconhecida no heartbeat como `workers_online`. Nunca presumir autenticação a partir do título da janela, rota, DOM ou somente heartbeat da extensão.
3. Só após passar os dois gates, criar **um NOVO** WorkItem/Operation de QA explicitamente autorizado e uma única geração nativa, com pre-send fence/lease e recibo durável. Capturar bytes reais, checar ids de request/parent/assistant/conversa/operação, SHA256/MIME/tamanho, registro protegido e GET autenticado em `/api/shell/generated-media`; comparar hash dos bytes retornados. Qualquer perda de ACK/UNCERTAIN deve permanecer *observe-only* — sem reenviar.
4. Homologar a rota atual de conteúdo `/backend-api/estuary/content?id=...` **contra uma geração do site** antes de marcar produção aprovada. Se o serviço usar URL ou autenticação diferente, corrigir sob origem estritamente permitida sem confiar em URL arbitrária e sem remover o bloqueio de redirects.

**Estado final desta rodada:** estrutura e build da extensão ativos, relay alcançável e broker protegido alcançável. **Produção E2E não executável com a composição atual**; preflight formalmente bloqueado, sem gerar imagem, sem recibos de arquivo reais, sem reinícios ou reenvios. Não considerar a homologação concluída.

## Rodada complementar — tentativa de resolver transporte, worker e geração nativa

**Data:** 2026-10-12 (OGrandeOxta, Desktop Commander). Escopo único: Chrome/Edge native image producer ↔ relay ↔ Canvas. Nenhum processo de produção foi interrompido.

### Diagnóstico estrutural verificado (não é apenas ausência de heartbeat)

1. **Relay legado de produção não está composto com o controle autenticado.** O processo ativo na porta `8765` foi identificado em runtime como `python.exe -B main.py --relay`. O caminho `main.py:serve_relay()` instancia `RelayServer(..., token=..., db_path=..., extension_dir=...)` **sem** `authenticated_control` e **sem** `assistant_observer`. Em `native_bridge/relay.py`, isso mantém `state.web_send=None` e `state.generated_assets=None`; as rotas `/jobs/generated-asset/chunk|finalize` negam a operação com schema/gate, de forma deliberada. A extensão pode estar pareada e online sem capacidade de emitir `sentra.generated_asset` autenticado. Não substituir esse fato por um mock de proveniência.
2. **Canvas broker real não configurado.** Endpoint principal do broker confirmado com token DPAPI em memória: PID **48400**, porta **62862**. Três projetos com Runs `RUNNING` retornam `attachments.model_delivery_available=false` e `model_delivery_reason=binary_relay_not_configured`. O método `Canvas.attach_shell_relay_observers` existe para composição host-only, mas nenhuma inicialização da instância ativa o chama. `SENTRA_SHELL_CONFIG_FILE` não foi composto nesse broker. Atribuir `web_relay.enabled=true` sem conta e host observer físico não seria suficiente e enfraqueceria o gate de admissão; por isso não foi feito.
3. **Worker Edge é preguiçoso por desenho, não morto.** `edge_extension/service-worker.js:omaTick` só adota aba já aberta, inativa e de provedor suportado após `queued>0 || leased>0 || activeJobs`. Portanto `workers_online=[]` quando a fila está vazia não prova defeito. O preflight read-only foi corrigido para registrar `worker_adoption=lazy_on_pending_job` e **não exigir** worker residente quando fila está vazia.

### Prova real, somente leitura, de adoção da aba

Arquivo novo `scripts/commander/qa_native_worker_probe.py`:
- Autentica via o token existente `.oma/relay-token` **somente em memória** (nunca impresso). Antes de iniciar exige `queued=leased=0` e extensão online.
- Tenta uma única `BROWSER_ACTION extract`, com seletor `html` e apenas 1 caractere, sem digitar, clicar, navegar ou SEND_MESSAGE. O comando `approval_status` foi rejeitado pelo validador do relay antes de qualquer job, porque a lista `BROWSER_ACTIONS` atual ainda não o inclui; esses 400 foram observados e não marcaram nenhuma operação.
- Execução válida real Desktop Commander PID **4064**: `status=READONLY_SUBMITTED`, job com prefixo `job_528bdc77`. Retorno `status=OBSERVED`, `job_status=FAILED`, `browser_worker_seen=false` (não foi recebido resultado `COMPLETED`).
- A inspeção persistente do **mesmo job**, por `scripts/commander/qa_native_worker_inspect.py` em abertura SQLite **somente leitura** e DPAPI, comprovou: `state=FAILED`, `worker_claimed=True`, `may_have_sent=False`, erro `TAB_ERROR ...: content-script returned no result`. O worker foi de fato adotado e reivindicou o job, porém o content script não retornou resposta válida. Não há prova de conta ChatGPT válida nem de geração de imagem nessa aba.
- O job falhou terminalmente, não foi reenviado; `queued=0`, `leased=0`, final `failed=21`. O script não fecha/deleta aba nem retoca outros jobs.

### Resultado de engenharia e testes
- Corrigido o diagnóstico em `scripts/commander/qa_native_asset_production_probe.py` para não classificar workers lazy como indisponíveis na fila vazia. O gate verdadeiro permanece na composição autenticada do Canvas (e no transporte do relay).
- `py_compile` dos scripts da rodada: aprovado.
- `node --test tests/unit/web_native_evidence.test.cjs`: **3 passed**.
- `pytest -q tests/unit/test_web_native_generated_assets.py tests/unit/test_shell_generated_media.py`: **18 passed**; execução real no Desktop Commander PID **47036**, exit code 0.
- Preflight final executado diretamente no OGrandeOxta, PID **46664**: `READINESS_CODE=4`; `production_native_asset_admission_ready=false`, 3/3 projetos sem composição; extensão/relay online, hash confere, nenhum job pendente nem em lease.

### Pendências que **não podem** ser declaradas resolvidas

- **Transporte Canvas**: manter bloqueado até implementação de composição *host-owned* que conecte o broker principal à autoridade do relay, com `web:send` do WorkItem original, source pins e attestors reais de conta/modelo/effort e mensagem. Trocar o relay autônomo que já ocupa 8765 exige janela coordenada e prova de nenhum efeito ativo; não foi desligado no meio de Runs `RUNNING`.
- **Worker de aba**: o provisionamento/adoption funcionou, mas `BROWSER_ACTION extract` falhou porque o content script não devolveu resultado. Corrigir apenas após diagnosticar tab elegível e identidade do content script, sem reloading automático de uma conversa que possa ter geração manual em andamento.
- **Imagem de produção**: **não executada**, pois nem a autoridade do relay nem o broker principal passaram o gate. Não foram emitidos `sentra.generated_asset` de uma imagem nativa real, nem hash final do Canvas. Inventar uma suposta confirmação seria incorreto.

**Síntese:** provado o comportamento lazy e a adoção real do worker com falha identificada; scripts de diagnóstico corrigidos e regressões verdes. A integração nativa com Canvas **ainda não está homologada em produção**. Não realizar Send fora da autoridade central, não criar grant artificial e não reiniciar processos enquanto seus efeitos não estiverem quiescentes.
