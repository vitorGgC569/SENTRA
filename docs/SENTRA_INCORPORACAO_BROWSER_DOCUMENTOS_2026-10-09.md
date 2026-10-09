# SENTRA — Incorporação de navegador e documentos

Data: 2026-10-09. Workspace compartilhado: `C:/Users/vitor/OneDrive/Desktop/SENTRA`.

Esta é a continuação da primeira onda do objetivo integral dos 37 projetos. Não representa conclusão desse objetivo. A revisão atual implementa redirects por salto, frames/shadow DOM, captura limitada, verificadores determinísticos, providers de recálculo/OCR e exclusão de publicação entre processos. **Por instrução do usuário, nenhuma validação foi executada nesta continuação.** Os testes ficam preparados para o coordenador executar ao final da implementação integral.

## Arquivos desta frente

- `sentra_executors/playwright_browser.py`: NetworkProfile, PlaywrightBrowserBinding, PlaywrightBrowserBackend, PlaywrightBrowserExecutor, declare_playwright_browser_machine.
- `sentra_executors/documents.py`: DocumentBinding, FormulaRecalculationBinding, OCRBinding, DocumentExecutor, transform_table, compare_tables, compare_excel_artifacts, verify_artifact, evaluate_acceptance, declare_document_machine.
- `sentra_executors/rpa.py`: AuthorizedPaths, OutputPathLock, atomic_output, OwnedProcessHandle, run_owned_worker, DOCUMENT_WORKER_SCRIPT, dependency_versions, effect_checkpoint, DiagnosedExecutor, ExecutorFailure.
- `tests/unit/test_sentra_executors_playwright_browser.py`, `test_sentra_executors_documents.py`, `test_sentra_executors_rpa.py`.
- Este documento.

Importar diretamente dos módulos. Esta frente não edita `_base.py`, `central_integration.py`, runtime, interop, qualidade ou Canvas. `browser_lab.py` permanece intacto. Os contratos de autoridade/Artifact registry são os existentes e os acrescidos pelo coordenador; não há outro banco ou controle de grants neste código.

## Fontes e dependências

Foram confrontados os trechos relevantes dos três estudos de 08/10 (`SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA`, `SENTRA_THIRD_PARTY_REUSE`, `SENTRA_OS_GATE5_ABSORCAO`) e da reavaliação de 09/10. As adaptações são implementações próprias sobre providers reais, não uma importação integral das suítes externas.

| Fonte / pin do manifesto | Código inspecionado | Incorporação |
|---|---|---|
| playwright-mcp `b8b4183e099f136cbec0388a6088d4aa2f6b9685` | index.js:18, src/README.md, package.json | Contextos isolados, ações estruturadas e evidência; o clone delega createConnection a playwright-core/lib/coreBundle e não contém o executor completo |
| rpaframework `7a419fb7a7bdc02ac7531328a3d8e308ef2bcc0c` | RPA/Excel/Files.py:194, :316, :624, :1853; Excel/Application.py | Fórmula versus cache, edição sem GUI, lifecycle de aplicação Excel para provider opcional |
| mesmo rpaframework | RPA/Tables.py:1667, :1692 | Conversões, filtros, agrupamento e projeção determinísticos |
| mesmo rpaframework | RPA/PDF/keywords/document.py:588, :649, :706 | Texto e seleção de páginas com índice iniciado em 1 |
| windowsworld `fbccd464f94fec9e284e139f97bf96d0b192f580` | desktop_env/evaluators/metrics/table.py:184, :239 | Comparação CSV/tabelas e propriedades de workbook por artefato esperado |
| osworld-v2 `acdd3493808e716825975b0f0208194bb2faf3c3` | evaluation_examples/task_class/generated_task_utils.py:57 e aggregate_scores | Composição, short-circuit e resultado por critério; sem replay/postconfig no host |

Na rodada anterior foram inspecionados dois ambientes: bundle do app com openpyxl 3.1.5, pypdf 6.10.0 e sem Playwright Python; Python 3.12 do WindowsApps com Playwright 1.62.0, pypdf 6.19.0 e Chromium instalado em `C:/Users/vitor/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe`. O bundle Node traz Playwright 1.62.1, que não substitui o provider Python. O clone MCP declara 1.64.0-alpha-1790635538000; não é o pacote executado por estes adapters. Nenhuma dependência foi instalada por esta frente.

O provider Python inspecionado fica em `C:/Users/vitor/AppData/Local/Packages/PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0/LocalCache/local-packages/Python312/site-packages/playwright/`. Nesta continuação foram lidos os contratos CDP de `driver/package/types/protocol.d.ts`, incluindo redirectedRequestId, Target attachments, Fetch.continueResponse, Fetch.takeResponseBodyAsStream e IO.read. Não houve execução desses novos caminhos.

| Provider | Requisito / pin | Pré-requisito adicional |
|---|---|---|
| Playwright Python | mínimo 1.51.0; pin do projeto 1.62.0 | Chromium compatível, CDP Fetch/Target/SystemInfo e processo retido por handle/pidfd |
| openpyxl | mínimo/pin 3.1.5 | Inspeção, edição e verificação XLSX; não calcula fórmulas |
| pypdf | mínimo 6.10.0; pin do lock existente 6.19.0 | PDF com texto embutido e seleção de páginas |
| Excel COM | pywin32 instalado; lock existente 312 | Excel instalado/ativado em Windows; psutil >=5.9 no host para excluir PIDs já existentes |
| LibreOffice | instalação com UNO calculateAll/storeAsURL; configurar Python com pyuno | Executável soffice absoluto; perfil e pipe UNO exclusivos por worker; versão efetiva ainda deve ser registrada na aceitação |
| OCR | PyMuPDF >=1.24 no Python configurado; Tesseract instalado | Executável absoluto e traineddata do idioma; Pillow/font somente para a fixture de aceitação |
| Publicação | Python stdlib | File locks Windows msvcrt ou POSIX flock; hardlink para no-overwrite; caminho sob posse do host |

Ausência de pacote/executável ou impossibilidade de estabelecer ownership resulta em diagnóstico FAILED/UNCERTAIN, conforme o efeito já ocorrido. Não há provider simulado, instalação automática, recálculo via openpyxl ou sucesso OCR sem chamar Tesseract.

Referências de API: [CDP Fetch](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/), [CDP Target](https://chromedevtools.github.io/devtools-protocol/tot/Target/), [Playwright BrowserContext](https://playwright.dev/python/docs/api/class-browsercontext), [Excel CalculateFullRebuild](https://learn.microsoft.com/en-us/office/vba/api/excel.application.calculatefullrebuild), [LibreOffice parâmetros de startup](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html). A antiga route.continue_ não intercepta todos os saltos HTTP; a revisão atual usa Fetch.requestPaused, cujo contrato anuncia cada request de redirect.

## Navegador: lifecycle, rede e escopo

Chromium é lançado pelo próprio backend. Cada sessão tem contexto descartável separado; não há perfil/cookies/storage_state do usuário, proxy pessoal, attach remoto, extensão, downloads ou importação de sessão. A API sync roda em actor dedicado e herda o ContextVar da autoridade central. O host encerra o backend com shutdown(); cada contexto tem close autorizado.

**Escopo de sessão:** machine_id + owner_principal_id + capability_id + work_item_id. Outra tarefa do mesmo agente não pode usar session_id/ref/diagnóstico da tarefa anterior. Não há handoff implícito: uma autorização explícita de transferência precisaria de implementação própria. O bootstrap deve manter o mesmo backend somente enquanto esse escopo estiver válido.

NetworkProfile declara offline, loopback numérico ou allowlist de origens HTTP(S) exatas. Métodos padrão GET/HEAD; métodos mutáveis são opt-in do host. `max_redirects` padrão 8, configurável de 0 a 20. Cada salto, inclusive alteração de método feita pelo Chromium em 301/302/303/307/308, passa pelo mesmo teste de origem, método, tipo, contador e deadline. Request além do limite é bloqueado antes do envio. URL final, resolução de recursos relativos, cookies e CORS permanecem sob comportamento nativo do Chromium; não se cumpre uma URL inicial com bytes da URL final.

O backend usa CDP interno apenas no browser lançado. Target auto-attach pausa páginas, OOPIFs e workers, instala Fetch e libera o target depois do checkpoint. Targets desconhecidos, popups e excesso de targets são encerrados em vez de navegar sem policy. Service workers e websockets continuam bloqueados. Auth challenge é cancelado; credenciais do usuário não são obtidas por heurística.

A política não é firewall/VM. Tráfego normal não é bufferizado por um proxy Python. `max_response_bytes` limita corpo capturado, não todo o RSS/tráfego do Chromium. Captura com body altera a latência de entrega das respostas selecionadas e pode bloquear uma resposta que exceda o limite; isso é opt-in explícito. Falta validar a revisão atual nas versões efetivas de Chromium/CDP do host.

## Observação e ações em frames/shadow DOM

`observe` enumera frames reais e atribui frame_id estável enquanto o Frame existe. Cada frame tem document_id e dom_revision. A observação inclui parent_frame_id, URL redigida, shadow_path dos elementos, revisão por frame e referências a ElementHandles reais. Refs são vinculadas a observation_id + page_id + revision + mapa de revisões dos frames. Frame separado/renavegado, alteração de shadow root/DOM, nova observação e ação mutável invalidam as refs. role/name/frame_id opcionais restringem adicionalmente a identidade.

Locators Playwright atravessam **shadow roots abertos**. O init script observa mutações desses roots, inclui roots declarativos na varredura limitada e registra input/change. Roots fechados são contados quando criados pelo attachShadow instrumentado e não são apresentados como acionáveis. Não há acesso simulado ao conteúdo de roots fechados. A revisão é frescor de observação, não autoridade contra página JavaScript hostil.

A varredura tem limite de frames, nós/candidatos e elementos; texto atravessa nós com orçamento antes de retornar pelo protocolo. Em vez de capturar um dump de acessibilidade ilimitado e truncar depois, esta revisão fornece semantic_summary limitado e metadados DOM de role/labels, explicitamente marcados como aproximação. Não se afirma equivalência a um accessibility tree completo. Password read é recusado.

| Ação | Argumentos além de action |
|---|---|
| open | profile; retorna session_id/page_id |
| navigate | session_id, url; DOMContentLoaded, deadline e rede por salto |
| observe | session_id; frames, revisões, elementos e semantic_summary |
| click/read | session_id, observation_id, page_id, revision, element_ref; role/name/frame_id opcionais |
| fill | Mesmas refs + text; somente campo editável suportado |
| screenshot | session_id, output PNG absoluto autorizado; viewport fixo 1280×800 |
| network | session_id, profile previamente declarado; invalida refs; não desfaz requests já enviados |
| evidence | session_id, after_sequence opcional; buffer limitado por eventos **e bytes** |
| diagnostics | session_id opcional; somente sessões do escopo/WorkItem; cache acessível sem esperar o actor |
| capture.start | session_id; orçamento/tipos do binding confiável |
| capture.stop | session_id, output JSON absoluto; exporta corpos reais e proveniência limitada |
| close | session_id; exige exportar captura pendente antes de fechar |

## Captura limitada e diagnóstico

PlaywrightBrowserBinding configura max_frames=32, max_dom_candidates=10000, max_elements=100, max_text_chars=32768, evidence_events=200, max_evidence_bytes=256 KiB, max_capture_bytes=8 MiB, max_capture_records=200, max_capture_seconds=60 e capture_resource_types=(xhr,fetch), além de timeout/action timeout. Limites não são argumentos do agente.

Uma captura ativa intercepta response apenas para os tipos escolhidos. Fetch.takeResponseBodyAsStream + IO.read obtêm chunks de até 64 KiB e o próximo byte além do orçamento detecta excesso **antes** de guardar o corpo completo. Não se chama getResponseBody/route.fetch para receber corpos arbitrariamente grandes. São devolvidos ao browser os bytes efetivamente lidos, mantendo a URL nativa. Em excesso/timeout, a resposta é abortada e a captura registra failed/timeout; não se exporta truncamento como corpo completo bem-sucedido.

Respostas com Content-Encoding não identity são preservadas sem alteração e registradas como capture_skipped_encoding; esta revisão não presume se o stream do build CDP é comprimido ou descomprimido. O JSON exportado conta esses skips e marca completeness_asserted=False. Não é um HAR completo. Streaming/SSE, media e websocket não são capturas suportadas. Corpos e imagens são dados privados, acessíveis somente pelo Artifact registry autorizado.

Console padrão guarda hash/tipo; texto é opt-in. Evidence omite query, fragment, credenciais, headers, cookies e corpos. Captura de body existe somente no arquivo solicitado. Diagnósticos mostram estado, último action, orçamento consumido, targets guardados, frames, cursor, deadline e restart_required. Estado fechado permanece no cache limitado. Não há chamada de página necessária para consultar o buffer após navegação abortada.

O backend retém um handle de kernel do PID de seu Chromium, obtido de SystemInfo; não mata processos por nome nem PID reutilizado. Watchdogs interrompem CDP/IO.read bloqueados encerrando esse browser próprio. Isso desconecta **todas as sessões daquele backend**; o host deve encerra-lo e criar outro, sem replay automático. Deadline e operação UNCERTAIN não prometem rollback de efeitos remotos. Renderers/RSS de conteúdo hostil ainda requerem sandbox de processo/VM; os limites aqui são de captura, transporte e tempo do provider.

## Publicação entre processos e Artifact registry

AuthorizedPaths usa raízes absolutas existentes/resolvidas e permissões separadas de leitura/escrita; prefixos semelhantes, ADS e device paths não autorizam acesso. Caminhos resolvidos devem permanecer dentro da raiz. O host deve possuir as árvores para evitar substituição de diretórios/junctions por terceiros entre syscalls.

`atomic_output` adquire **OutputPathLock por caminho resolvido**, independente de agente/máquina. Windows usa byte-range lock msvcrt; POSIX usa flock. O arquivo de lock fica em `.sentra-output-locks/<sha256-do-caminho-normalizado>.lock` junto ao destino, com timeout/checkpoints. Esses pequenos arquivos persistem intencionalmente: remove-los pode criar duas autoridades de lock para o mesmo destino.

Dentro do lock: checar overwrite, produzir temporário, verificar conteúdo, limitar bytes, fsync via handle gravável, verificar novamente scope/checkpoint e promover. Sem overwrite, usa os.link atômico e falha se outro criador ganhou; nunca existe()+replace. Com overwrite=True, usa os.replace depois da verificação. Falha preserva input e destino existente; filesystem sem hardlink/locking suportado falha explicitamente.

**Ainda dentro do mesmo lock, imediatamente após publicação**, se current_effect_context existir, chama `context.capture_output(path, expected_sha256=sha, max_bytes=...)`. O helper central verifica output da request e guarda bytes no Artifact registry existente sob owner/run/operation. Evidence retorna artifact_id, resource_uri e durable_capture=True. Falha de captura após publicar resulta em UNCERTAIN `output_published_capture_failed`, com identidade/digest da cópia workspace já publicada. Não se rotula como rollback. Standalone sem contexto central retorna somente path/digest e não afirma durabilidade.

## Documentos e verificadores

DocumentBinding mantém XLSX, CSV/TSV e PDF determinísticos, limites de input/expansão/linhas/colunas/páginas/texto, mais backends opcionais e max_acceptance_criteria=32.

| Ação | Argumentos |
|---|---|
| excel.inspect | input, sheet opcional, value_mode formulas/cached_values, janela de linhas |
| excel.transform | input/output XLSX, cells, sheet opcional, overwrite opcional |
| table.inspect | input CSV/TSV, limit opcional |
| table.transform | input CSV/TSV, output CSV/TSV/JSON, conversions/filters/sort_by/group_by/sums/select |
| pdf.inspect/pdf.text | input PDF; pages opcional para texto |
| pdf.extract_pages | input/output PDF, pages em ordem explícita, overwrite opcional |
| artifact.verify | input atual, expected absoluto, metric table/bytes/pdf/excel, options, expected_sha256 opcional; output JSON opcional |
| acceptance.evaluate | criteria com id/actual/expected/metric/options/digest opcional; conjunction and/or/avg/sum, short_circuit, threshold, output JSON opcional |
| excel.recalculate | input/output XLSX, backend declarado, expected_cache não vazio, overwrite opcional |
| pdf.ocr | input PDF, output JSON, backend declarado, pages opcionais, overwrite opcional |

Input nunca pode ser output, inclusive por hardlink. Reports também não podem sobrescrever actual/expected. Expected artifacts precisam existir dentro dos read_roots; fixture ausente/provider indisponível é erro explícito, não score zero disfarçando impossibilidade de avaliar.

Verificadores são read-only, sem getters de desktop, replay pyautogui ou postconfig. CSV/TSV/JSON com cabeçalhos únicos preservam duplicações; ordenação pode ser ignorada explicitamente. Conversão numérica/tolerância/strip/case são opt-in. Tolerância numérica com ordem ignorada exige keys únicas para evitar pareamento ambíguo. O comparador Excel por grid não pressupõe headers e pode comparar propriedades públicas de estilo, além de células/sheets. PDF compara contagem/dimensões e texto quando solicitado; não demonstra fidelidade visual ou assinatura digital.

Cada resultado tem passed, score, digest de atual/esperado e diferenças limitadas. and exige todos, or aceita algum; avg e sum são agregações explícitas. O upstream OSWorld usa média também em parte do caminho chamado and; aqui and é propositalmente lógico. Short-circuit identifica NOT_EVALUATED; não atribui sucesso a critérios não executados. Operation SUCCEEDED significa que a avaliação rodou/publicou seu relatório; **passed=False continua rejeitando o artefato**. O caller central deve consumir passed, não apenas o estado operacional.

Fórmulas e caches são distintos. openpyxl sempre retorna recomputed=False. Cached values podem faltar/estar stale, inclusive nos verificadores. Recursos XLSX que o roundtrip não preserva (macros, slicers, objetos/links externos) são recusados na transformação pertinente; não se promete fidelidade de aplicação Office.

## Recálculo e OCR reais, opcionais

FormulaRecalculationBinding(name, owner_principal_id, engine, python_executable, executable, timeout_seconds) escolhe excel ou libreoffice. OCRBinding(name, owner_principal_id, tesseract_executable, python_executable, language, dpi, max_pixels, timeout_seconds) escolhe Tesseract/PyMuPDF. Backends de outro principal são recusados. Timeout de provider exige margem dentro do timeout do DocumentBinding.

O host cria cópia privada do input em diretório temporário autorizado; provider nunca abre o original para salvar. Worker recebe JSON por stdin só depois de entrar no Job Object Windows (kill-on-close) ou process group POSIX próprio. Canal de resultado e mensagens são limitados; stderr não vaza credenciais. Parent revalida checkpoint entre fases e envia ACK antes de abrir/calcular/salvar/renderizar/OCR. Timeout encerra somente recursos próprios.

Excel usa DispatchEx, anuncia seu PID via Hwnd e espera ACK. O parent recusa PIDs Excel existentes no baseline e retém handle do processo novo antes de permitir workbook I/O. Macros/events/alerts e update de links são desativados. CalculateFullRebuild espera CalculationState concluído e salva XLSX. Se criação COM travar antes de anunciar PID, não é seguro matar processos Excel encontrados por heurística: resultado é UNCERTAIN de ownership desconhecido, com reconciliação necessária. Nenhuma instância existente é anexada/encerrada.

LibreOffice usa perfil exclusivo, pipe UNO exclusivo, Hidden, NEVER_EXECUTE macros, NO_UPDATE links; chama calculateAll e storeAsURL. Não usa o perfil/sessão da instalação aberta do usuário. Exige Python com UNO disponível; ausência retorna dependency_missing_pyuno.

`expected_cache`, por exemplo `{ "Data!B1": 10 }`, deve apontar fórmulas existentes no input. A saída é reaberta com data_only=True e comparada aos valores esperados antes da promoção; só então recomputed=True. Isso comprova as células pedidas e a execução do engine, não compatibilidade de todas as funções Excel/LibreOffice. Links/macros são recusados; funções externas/voláteis e diferenças de dialeto exigem critérios próprios.

OCR usa PyMuPDF para renderizar páginas com DPI e pixels limitados **antes de criar o bitmap** e chama o executável Tesseract real sobre PNG temporário. Idioma vem do binding; traineddata precisa estar instalado. Tempo/processo/bytes de texto são limitados. JSON por página registra ocr_performed=True; não promete precisão perfeita nem PDF pesquisável ou substituição do documento original. Output verificado é capturado no mesmo registry central.

## Integração com o host central

```python
from sentra_executors.playwright_browser import NetworkProfile, PlaywrightBrowserBinding, declare_playwright_browser_machine
from sentra_executors.documents import DocumentBinding, FormulaRecalculationBinding, OCRBinding, declare_document_machine
from sentra_executors.rpa import AuthorizedPaths

paths = AuthorizedPaths((input_root,), (output_root,))
calc = FormulaRecalculationBinding('calc', factory.agent_id, 'libreoffice',
    python_executable=uno_python, executable=soffice_executable, timeout_seconds=60)
ocr = OCRBinding('scan', factory.agent_id, tesseract_executable,
    python_executable=ocr_python, timeout_seconds=60)
docs = declare_document_machine(machine_id='documents', owner_principal_id=factory.agent_id,
    bindings=(DocumentBinding('documents.files', paths, timeout_seconds=90,
        recalculation_backends=(calc,), ocr_backends=(ocr,)),), policy=factory.policy)
browser = declare_playwright_browser_machine(machine_id='browser', owner_principal_id=factory.agent_id,
    bindings=(PlaywrightBrowserBinding('browser.web', (
        NetworkProfile('offline'), NetworkProfile('site', 'allowlist', (chosen_origin,), max_redirects=8)
    ), artifact_paths=paths),), policy=factory.policy)
factory.register_execution(docs)
factory.register_execution(browser)
request = factory.dispatch_request(run_id=run_id, work_item_id=work_item_id,
    machine_id='documents', capability_id='documents.files', operation_id=operation_id,
    arguments={'action':'excel.recalculate','input':input_xlsx,'output':output_xlsx,
               'backend':'calc','expected_cache':{'Data!B1':10}})
result = await factory.submit(run_id=run_id, request=request)
# Browser: Operations distintas open -> navigate -> observe -> action por ref.
# Usar o MESMO WorkItem para a sessão. Exportar capture.stop antes de close.
# No teardown autorizado do host:
browser.adapter.backend.shutdown()
```

Run/WorkItem/grants/required_capabilities e dispatch durável continuam na factory. register_inventory é somente descoberta. Captura/output usam current_effect_context do coordenador, propagado ao actor; checkpoint/lease/exclusão de máquina são contratos centrais. Estes modules não concedem autorização a flags fornecidos pelo chamador.

## Aceitação preparada, sem execução nesta revisão

Na versão anterior houve 28 casos distintos aprovados entre dois ambientes, incluindo Chromium loopback, e um caso de symlink não executado. **Esses resultados são históricos: não validam a revisão CDP/frames/workers/locks/verifiers atual.** A continuação obedeceu à ordem de implementar primeiro e deixar a validação integral ao coordenador; não executou testes, compiler/AST, providers ou inspeções de runtime.

Comandos para o coordenador executar quando encerrar a implementação:

```powershell
$acceptPython = 'C:/Users/vitor/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $acceptPython -m unittest discover -s tests/unit -p test_sentra_executors_documents.py -v
& $acceptPython -m unittest discover -s tests/unit -p test_sentra_executors_rpa.py -v
$browserPython = 'C:/Users/vitor/AppData/Local/Microsoft/WindowsApps/PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0/python.exe'
$env:SENTRA_PLAYWRIGHT_ACCEPTANCE = '1'
& $browserPython -m unittest discover -s tests/unit -p test_sentra_executors_playwright_browser.py -v
Remove-Item Env:SENTRA_PLAYWRIGHT_ACCEPTANCE
```

Recálculo real é opt-in por `SENTRA_RECALC_ACCEPTANCE=1`, `SENTRA_RECALC_ENGINE=excel|libreoffice`, `SENTRA_RECALC_PYTHON=<Python-com-pywin32-ou-UNO>` e, para LibreOffice, `SENTRA_LIBREOFFICE_EXECUTABLE=<soffice-absoluto>`. OCR real é opt-in por `SENTRA_OCR_ACCEPTANCE=1`, `SENTRA_TESSERACT_EXECUTABLE`, `SENTRA_OCR_PYTHON`; a fixture precisa PyMuPDF/Pillow/font, e `SENTRA_OCR_TEST_FONT` pode selecionar o font do ambiente. Executar o conjunto documents no Python que reúna os requisitos do teste, mantendo os providers configurados separadamente.

Flag real habilitado transforma pré-requisito ausente em falha; flag desabilitado é skip, nunca prova de execução externa. Os testes unitários de ContextVar/capture_output usam probes nomeados explicitamente; não substituem prova do journal/Artifact registry central.

Casos preparados: redirect permitido com URL final/JS relativo, loop e origem recusada, OOPIF entre 127.0.0.1 e 127.0.0.2, input/button em frame e shadow root, referência stale, isolamento por WorkItem, corpo real capturado, orçamento que falha sem truncamento bem-sucedido, diagnóstico pós-close, corrida de dois processos sobre o mesmo output, falha preservando original, captura durável sob lock, CSV/Excel/PDF esperados, composite short-circuit, recálculo cache real e OCR de PDF escaneado real.

## Lacunas e próxima integração

1. Executar validação integral ao final, especialmente CDP recursivo/OOPIF e watchdog no Chromium efetivo; nenhum sucesso novo foi afirmado nesta revisão.
2. Integrar bootstrap/UI/grants/WorkItems e testar Canvas -> factory -> provider -> Artifact registry -> verificador, inclusive recuperação depois de modificar workspace/reiniciar host.
3. Instalar/configurar providers no ambiente efetivo; Excel/LibreOffice/UNO/Tesseract/PyMuPDF novos ainda não foram exercitados por esta frente.
4. Captura comprimida/SSE/media, acesso a closed shadow roots, downloads e HAR completo exigem implementação específica. Handoff de sessão entre WorkItems não existe; abrir contexto novo é o comportamento atual.
5. Persistência/reattach de sessões de browser, fidelidade Office/OCR, funções de planilha externas e sandbox rígido de CPU/RSS continuam como integrações próprias. Erro/timeout/incerteza nunca autoriza replay automático.
