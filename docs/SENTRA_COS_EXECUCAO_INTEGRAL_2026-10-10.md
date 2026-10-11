# Execução integral da incorporação Chat On Steroids

O escopo permanece nas 13 frentes e 21 subfrentes de
`SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md` e no arquivo de
requisitos fornecido pelo usuário. Não usar testes antigos para afirmar aceite
das capacidades novas. Validar somente depois da implementação integral.

O usuário instruiu usar PowerShell e edição direta, sem MCP SENTRA e sem
agentes Web. A tentativa anterior de apoio heterogêneo terminou em conflito
de identidade de turno e não foi repetida.

## Alterações de código nesta rodada — ainda sem validação

- `browser_evidence.py`: cadastro explícito de coletor por extensão/principal/
  workspace/build; nonce curto por documento; identificação exata de request
  e mensagem; quarentena persistente de ownership conflitante, sem trocar dono;
  estados de página e espera de aprovação, sem conceder grants.
- `conversation-evidence.js`: leitor MAIN restrito, caminho React efetivamente
  committed, branches coerentes com a rota, campos primitivos. Licença MIT do
  algoritmo adaptado acompanha a extensão em `COS-NOTICE.txt`.
- Relay instalado, Control Plane, filtro de chamadas MCP e Canvas ligados aos
  mesmos registros. Canvas oferece cadastro/revogação do coletor. Duas abas
  não podem limpar o estado pendente de aprovação uma da outra.
- `web_delivery.py`: projeção durável de not_sent/pending/unconfirmed/sent no
  SQLite existente do relay; chave de entrega e fingerprint, recibo por ID de
  mensagem, exclusão de mensagens incertas da retransmissão e conflito de
  entrega ativa por conversa. Resultados expõem a evidência separadamente.
- Envio ChatGPT limitado a um efeito de submit. Sem trocar para form/Enter após
  clique incerto. O content script conserva a tentativa por job; o SW publica
  recibo com a identidade de mensagem. Sem recibo exato, a entrega é incerta.
- `skill_library.py`: snapshots protegidos de SKILL.md/recursos, checksum,
  import local, Git local por SHA integral e GitHub archive por SHA integral,
  bounds de bytes/arquivos e rejeição de links/paths privados, revisões
  imutáveis, revogação, ativação explícita por WorkItem/agente/workspace.
  Contexto oferece metadados; disclosure lê apenas a revisão ativada. Sem
  executar scripts, alterar cwd ou criar grants. Painel no Canvas integrado.
- `tool_exposure.py`: reserva global de tool names, inclusive desativados;
  tombstones impedem redirecionamento de chamadas cacheadas; até 256 tools e
  250.000 bytes de schemas; integração no handshake de workers e registro MCP.
- Novos testes de identidade/replay/conflitos/approval, entrega/restart/recibos
  e exposição global escritos para a fase final. Não executados.

## Trabalho obrigatório restante

1. Completar observação real da conta/modelos/efforts/Automatic, connector proof
   com schema remoto e refresh, logout/troca de conta, UI/CLI e fail-closed quando
   os shapes mudarem. O leitor atual cobre apenas branches com IDs primitivos
   explícitos; não equivale à cobertura integral de todos os renderers Web.
2. Completar MCPB: adapter MCP real stdio/HTTP, instalação supervisionada,
   OAuth, health/restart, atualização/revogação/uninstall, WorkItem/Operation/
   Grant no ponto de efeito e publicação seletiva. O staging e o host existentes
   não são ainda o ciclo completo. Colisões não provam execução MCPB.
3. Compact & Resume Web A→B: criar/alocar alvo sob operação autorizada, entregar
   resumo com recibo exato, preflight/claim/commit/publish/reconcile e preservar
   contexto/Run/WorkItem/worker. A transação local anterior continua distinta.
4. História Web protegida por message ID/revisão, anexos/artifacts/chunks,
   quotas, índice incremental opt-in protegido, export Markdown Web.
5. Code Mode QuickJS WASM restrito, API de dois consentimentos, editor/PDF/
   diff/watch com revisão e escrita via gate, receipt summaries, GC seguro,
   Goal/Loop/streaming de processos e updater coordenado.
6. Completar UX/keyboard/docks/reduced motion, setup/repair, proveniência e
   inclusão dos novos arquivos no build. Atualizar o source hash da extensão
   durante materialização final: a assinatura atual no manifest é anterior às
   alterações e não deve ser publicada como válida.
7. Só então executar as suítes, testes de integração/E2E, build, acessibilidade,
   WebView2, primeira instalação/Setup/MSI e assinatura. Evidência de conta real
   e assinatura deve ser real; não fabricar homologação a partir de fixtures.

**Estado: implementação em andamento, não homologada.** Não houve testes,
build final, commit/push nem substituição do aplicativo instalado nesta rodada.


## Retomada independente após 503 (10/10) — evidências desta conversa

O incidente de resposta foi diagnosticado sem alterar a conta, cookies ou credenciais:
o serviço Gateway 17842 e o upstream Web Models 17841 responderam 200 em /healthz,
com um erro de catálogo upstream 502 intermitente recuperado. Um turno **real**
`python -B -m sentra_cli --model sentra/chatgpt-web/auto --prompt 'Responda apenas:
SENTRA_OK' --no-auto-start --timeout 35 --max-tool-rounds 1` retornou
`SENTRA_OK` e exit 0, SEM retry de uma requisição incerta. Isto **não comprova**
que a falha 503 intermitente foi solucionada para todas as sessões do Codex.

### Incrementos novos efetivos

- `sentra_mcp/server.py` + `tool_exposure.py`: reserva fail-safe de nomes
  first-party separada dos limites de *publicação de plugins*. Falha de
  reserva não encerra o MCP, e status de reserva é exposto em /healthz;
  collisions entre core e providers continuam proibidas quando a reserva
  passa. Regressão original `test_server_fingerprint_tracks_actual_registered_schema`
  corrigida (35 testes de MCP passaram).
- `native_bridge/job_store.py`: transaction `BEGIN IMMEDIATE` antecede
  reconciliação de expirados e um `_expire(commit=False)` evita commit
  intermediário; proteção contra duplicação `unconfirmed` permanece.
  Teste específico envia após expiração sem erro de transação aninhada.
- `browser_evidence.py` + `relay.py`: estados observados de aprovação
  humana/generação/logout/frescor bloqueiam **novos** envios para conversas
  ChatGPT conhecidas, inclusive no polling ANTES de atribuir nova lease.
  A observação nunca cria grant e sem evidência a API legada permanece;
  não confundir com prova pública estável do DOM Web.
- `stage_electron.py`: inventário SHA-256 de **todos** os arquivos Electron,
  com verificação pré e pós-cópia, limite de arquivos/bytes, notices Chromium.
  Dry run validou 77 arquivos da runtime Electron 44.0.0.
  `build_windows.py` insere payload assinado de exibição no Setup;
  `installer.py` instala/computa ownership; `release_assets.py` garante
  que o **MSI**, além do Setup, leva a mesma pasta íntegra.
  `release-commander.yml` incluiu npm ci/test e assinatura condicional da
  runtime display (não há assinatura local; certificado ainda não verificado).
- `tests/unit/test_sentra_cos_skill_library.py` exercita imports imutáveis,
  revogação, origem Git fixada e negação de links, dados privados e caminhos.

### Validação e limitações

Executados 25 passed/1 skipped das novas superfícies, 35 passed de MCP, 15
passed de políticas browser/outbox/namespace/staging, 13 passed dos testes
mais recentes de relay e MSI staging, build React Vite concluído, Node
Electron 2 passed, fingerprint/copy de 77 arquivos. Não somar contagens
de suites sobrepostas como número de testes únicos. A suíte unitária completa
foi iniciada e precisa de veredito específico separado.

Ainda **não** demonstrados: OAuth MCPB completo/ativação pelo work item
com provider real stdio e HTTP; refresh do plugin na conta ChatGPT; continuação
A→B com recibo externo; quota real da conta; Code Mode QuickJS, editor
com gate de escrita/PDF, autorização dupla API; prova de Chrome extension
em conta real, instalação Windows limpa e assinatura Authenticode.
Não marcar 34/34 como implementados ou homologados.


### Regressão integral e correção do manifesto da extensão

Uma varredura completa `python -B -m pytest tests/unit -q` terminou com
**2026 passed, 39 skipped, 3 failed** em 508,95s. Os três erros foram:
`test_extension_bootstrap_pairs_without_bearer_in_bootstrap_file`,
`test_relay_extension_version_endpoint` e
`test_manifest_source_hash_matches_extension_files`: todos devidos ao
`edge_extension/manifest.json` manter o hash antigo depois das mudanças de
código do Codex. O comando oficial `stamp_extension_identity` atualizou
`sentra_source_hash` para
`b5180db58a50e29927fa020eb4c6a41adddad06b19d126b44ac1d4d5da42203f`
sobre os sete arquivos do contrato. A suíte específica com os três
módulos envolvidos passou **48 passed**, e outra rodada de validação
de extensão passou **34 passed**. O teste de identidade está consistente,
`git diff --check` passou. Os testes de Git skills totalizam 2 passed/1
skipped somente porque criação de symlink requer privilégio no Windows;
teste do commit SHA Git real passou.

**Não apresentar a suíte integral como 2065/2065 aprovada:** ela não foi
reexecutada depois da atualização do hash; o aceite atual é de *reparo dos
três defeitos identificados*, confirmado pelos 48 testes direcionados.
Build React Vite completou com avisos de scripts clássicos e chunk >500 KiB.
A inspeção visual completa, a instalação limpa Setup/MSI e a assinatura de
todos os artefatos permanecem pendentes.


### Fechamento adicional do lote de validação

Após o gate de aprovação também no `poll` da fila, a suíte integrada de
`test_commander_release.py`, `test_build_canvas.py`,
`test_build_payload_provenance.py`,
`test_sentra_canvas_installer_bundle.py`,
`test_sentra_electron_stage.py`,
`test_sentra_cos_browser_evidence.py` e
`test_sentra_cos_web_delivery.py` terminou **70 passed**.
O comportamento comprovado no laboratório inclui não conceder lease enquanto
a aba está em aprovação humana, permitir outro chat na fila e retomar
sem repetir job quando o navegador volta a estado `idle`.
A assinatura Electron neste checkout está `NotSigned` e a execução Windows
completa de Setup/MSI recém-compilado não ocorreu. A CI foi ajustada, mas
não há pipeline remoto verde e nem aceite 34/34.

## Continuação da integração: MCPB no Control Plane e produtividade Canvas

### MCPB 0.3 com governança real, sem autorização automática
- `sentra_mcp/services/plugin_bundles.py`: adiciona leitura validada de manifesto
  MCPB 0.3 (nome, versão, publisher, server type e entry_point), inventário
  de arquivos seguro e SHA-256 do pacote, registro SQLite idempotente em
  `plugin_bundle_registrations`, desativação com persistência. O arquivo
  `.mcpb` original é retido no estado do SENTRA sob `.archives/<SHA>.mcpb`
  e seus arquivos extraídos são comparados byte a byte antes do registro;
  não depende da permanência do arquivo no workspace.
- `sentra_mcp/services/control_plane.py`: `bundle_list/stage/inspect/register/disable`
  são operações do próprio ControlPlaneService, com auditoria `bundle.register`
  / `bundle.disable` no GovernanceService. Registrar cria plugin sem
  `worker`, grants, verified_methods ou effective_capabilities.
- `sentra_canvas/service.py` e `__main__.py`: rotas existentes do Canvas
  passaram a chamar esses métodos centrais; POST exige bearer e aprovação
  explícita para alterar cadastro, com listagem owner/workspace-scoped.
- `sentra_canvas/desktop_ui/src/plugin-bundles-dialog.jsx`: importar,
  inspecionar o manifesto, registrar e desativar diretamente na única UI.
- **Limite consciente**: o PluginWorkerHost nativo usa `sentra.handshake`
  próprio, mas um MCPB padrão exige protocolo MCP stdio. Ainda falta
  vincular o cliente MCP stdio existente a work item, durable admission,
  grants, supervisão e sandbox reais antes de permitir **execução**. OAuth,
  atualização, remoção definitiva e sincronização do ChatGPT também pendem.
  Não há alegação de que registrar o MCPB instala ferramentas no ChatGPT.

### G10/A18 — edição de arquivos com revisão
- `sentra_canvas/project_review.py`: preview SHA-256, diff de conteúdo
  proposto, caminho confinado ao workspace, arquivos privados/link proibidos,
  verificação UTF-8 e limite 128 KiB. Gravação protegida com lock entre
  processos, releitura e CAS de revisão, temporário+fsync e replace atômico.
- `sentra_canvas/service.py`: revisão fornece ticket imprevisível, de uso
  único, válido por 300s, vinculado a workspace/path/revisão origem/digest da
  proposta. Não persiste texto em segredo nem permite reutilizar o ticket
  após tentativa de salvar. Limite de 128 propostas em memória.
- `sentra_canvas/__main__.py`: GET read-only; POST `preview_edit` sem
  mutação; POST `save` exige bearer, `approve=True` e token da revisão
  exata. Tokens e aprovação não são concedidos por MCP/tool/agent.
- `sentra_canvas/desktop_ui/src/project-review-dialog.jsx`: código, Git diff,
  textarea de edição, revisão visual, checkbox de confirmação e salvamento
  por SHA. CSS minimalista em `desktop.css`.

### G10 — texto paginado de PDF, sem renderização
- `pdf_text_page` usa o `pypdf` já dependência do projeto para prévia
  textual read-only de um PDF autorizado, página a página. Até 4 MiB, 200
  páginas e 32 KiB de texto de retorno. Não expõe filesystem arbitrário,
  edita PDF, carrega extensões ou declara OCR/renderização; páginas
  digitalizadas sem texto exibem uma ressalva explícita na UI.
- Rota `/api/center/project-review?action=pdf_text&page=N` mantém bearer,
  escopo de workspace e validação de extensão/caminho. Testes de 2 páginas
  com PDF criado em memória por pypdf, travessia, paginação e isolamento HTTP.

### Evidências do lote
- MCPB centralizado, testes de Canvas/governance: **23 passed** na revisão
  do facade.
- Regressão de 11 módulos (Canvas HTTP, editor/browser/outbox/MCPB,
  exposição/ChatAccess, máquina e broker): **56 passed, 1 skipped**.
- Casos pós-revisão de editor e MCPB: **18 passed, 1 skipped**.
- Testes PDF, editor, explorer: **8 passed, 1 skipped**.
- O teste HTTP de negação anônima do Canvas apresentou um WinError 10053
  intermitente numa corrida longa (73 passed,1 skipped,1 failed), mas
  **1 passed** isolado e **17 passed** no subgrupo em repetição. Isso
  não é evidência de solução definitiva para transportes intermitentes.
- Build React Vite e materialização das alterações concluídos; warnings
  de scripts clássicos/chunk JS grande persistem. `git diff --check`
  e compilação Python foram executados sem erros nesta etapa.
- Ainda **não** homologado: 34/34 de E2E, execução MCPB padrão com grants e
  sandbox, OAuth/Web Model provas externas, Compact&Resume Web A→B, PDF
  visual nativo integral, Code Mode, Setup/MSI limpos e assinatura. Sem
  publicação nem commit global das mudanças pré-existentes do checkout.


### Revisão final deste turno
O teste combinado final após integração dos três fluxos (MCPB no Governance
real, editor owner-reviewed e prévia textual PDF), segurança browser/outbox,
Canvas HTTP, máquina, broker e governança encerrou com **63 passed,
1 skipped, 0 failed** em 20,99s. `git diff --check` exit 0,
`compileall` dos módulos alterados sem erros e Gateway Web Models com
`ready=True`, upstream `ok`, catálogo `ready`. React Vite build
materializado (warnings de bundle/scripttags conhecidos).
Não há certificação de compatibilidade com todos os manifestos MCPB nem
homologação dos modelos sob conta remota. Esta é uma tranche integrada e
testada do checkout, não uma afirmação de entrega integral 34/34.

### Continuação após configurar agendamento — admissão de MCPB stdio vinculada ao WorkItem
- `MCPBBundleCatalog.launch_spec`: novo preflight de pacote MCPB 0.3 já
  registrado, íntegro, owner/workspace vinculados, somente Python, sem
  interpolação de ambiente, user_config, shell, flags extras ou dependências
  automáticas. Constrói executable/argv/cwd absolutos e hash de argv, digest
  do entry_point comparado com o archive de origem imutável no momento do
  preparo. Não dispara processo nem ativa método/plugin.
- `ControlPlaneService.bundle_activation_plan`: consulta Run e WorkItem
  centrais, verifica ligação a workspace e estado de execução; exige grant
  `mcp:launch` real do `AuthorizationService` via `BoundWorkItemPolicy`.
  Retorna um candidato com `policy_constraints` pinados, contendo explicitamente
  `ready_to_execute=False`, `durable_operation_reserved=False`,
  `worker_started=False`. Esta etapa é apenas admissão de plano, sem
  autorização para chamar MCPStdioClient fora de DurableInteropGate.
- Python Microsoft Store neste host usa alias de WindowsApps que falha
  `Path.resolve(strict=True)` com WinError 1920; o plano assinala
  `interpreter_target_verified=False` sem alegar pin real do destino
  ou habilitar execução neste ambiente.
- Testes novos `tests/unit/test_sentra_cos_mcpb_activation_plan.py`:
  sem grant => deny, grant WorkItem legítimo => plano exato sem efeito,
  revogação => deny, desativação => deny, shell/argv/env/segredo => deny.
  5 passed novos; rodada MCPB junto com importação/registro: 17 passed.
  Regressão com Canvas HTTP, Governance e editor: **28 passed, 0 failed**.
  `py_compile` concluído, `git diff --check` sem erro; Gateway
  ready=true e upstream=ok neste instante.
- **PENDÊNCIA CRÍTICA:** planejar não significa executar MCPB. A próxima
  etapa deve instalar o adapter real stdio+HTTP sob DurableInteropGate com
  fencing, leases e supervisão de processo, grants individuais por ferramenta,
  observabilidade e recuperação de crash. Não liberar automaticamente
  pacote sem sandbox confiável e comprovada.

### Continuação da manhã 10/10 — primeira execução MCPB stdio em contêiner real

Foi ligado o caminho host-only `ControlPlaneService.bundle_call_tool` ao
`CentralInteropAdapter.protocol_gate` e ao `DurableInteropGate.execute` com
autoridade `CentralDurableIntentAuthority` sobre Run/WorkItem/Operation reais.
A ferramenta `mcp:<nome>` só inicia seu efeito após grants reais e independentes
`mcp:launch`, `mcp:list` e `mcp:<nome>`, registro ativo do MCPB e hash de
conteúdo conferido. A mesma Operation/idempotency_key não reexecuta após
reserva concluída; evidência guardada no SQLite central. A revalidação ocorre
no ponto de efeito e durante initialize/discover/call, inclusive quando um
dos três grants é revogado.

Novo `sentra_mcp/services/mcpb_sandbox.py` executa MCP stdio JSON-RPC
dentro de um contêiner Linux Docker *uma vez por Operation*: imagem **local
imóvel por image ID sha256** configurada pelo operador em
`SENTRA_MCPB_SANDBOX_IMAGE_ID`, CLI Docker confiável pinado, `--pull=never`,
`--network=none`, `--read-only`, usuário 65534, cap-drop ALL,
no-new-privileges, limites CPU/RAM/PIDs, pacote revisado montado somente
para leitura, tmpfs restrito, sem shell/env/credenciais do Windows.
`MCPStdioClient` fala com o subprocesso; o método está exposto apenas pela
fachada central Python, **não** é um novo executor ou endpoint HTTP.
Uma instância MCP não sobrevive entre Operations. O encerramento consulta
o Docker e força remoção do contêiner de nome aleatório se necessário;
falha de cleanup indica resultado incerto.

Validação real (host Windows Docker Desktop/Linux, imagem local
`oma-sandbox:local` pinada pelo digest sha256 para teste; fixture autoral
inofensiva): initialize, tools/list e tools/call rodaram pelo stdio;
tentativa de escrita em `/bundle` e de conexão externa foram bloqueadas;
`Operation` ficou `SUCCEEDED` no SQLite; nova chamada com mesma identidade
retornou `duplicate`, sem novo envio; grant revogado impediu outro call.
Teste sem imagem configurada/sem mcp:list/sem mcp:echo negou antes de criar
uma Operation. `tests/unit/test_sentra_cos_mcpb_sandbox_execution.py`:
2 testes novos; regressão combinada dos 6 arquivos (MCPB staging,
registro, admissão, stdio, centro real, sandbox) **23 passed, 0 failed**.
`compileall` dos módulos alterados passou, `git diff --check` sem erro
(aviso CRLF existente). Inspeção `docker ps -a --filter name=sentra-mcpb-`
sem contêiner remanescente. Não houve commit ou push.

**Limites / não homologado:** requer Docker Desktop/Linux confiável e
imagem Python local pinada explicitamente (imagem usada nos testes não é
ainda imagem oficial de distribuição auditada); dependências opcionais,
protocolos MCPB Node/HTTP/OAuth, atualização/rollback/uninstall e UI de
administração do servidor em execução não foram implementados aqui.
Queda abrupta do host antes do finally ainda precisa de reconciliação de
contêiner órfão e investigação de efeito incerto, com testes de crash.
A execução Docker local NÃO prova que plugin/ferramentas aparecem nem
funcionam na conta ChatGPT Web ou que o instalador final contém Docker.
`launch_spec` continua preflight sem executar diretamente, e
`MCPStdioClient.launch` sem o gate durável não é usado neste fluxo.
A auditoria histórica 0/34 E2E integral continua NÃO revogada por 23
testes locais; não atualizar contagem global por presunção.

#### Regressão cruzada final desta execução
A regressão conjunta (14 módulos: execução Docker MCPB, editor/PDF, importação/registro MCPB, browser evidence/outbox/ChatAccess/connector, namespace, Canvas HTTP, máquina/broker e governança) encerrou com **65 passed, 1 skipped, 0 failed**, 25,47s. Os 23 testes do fluxo MCPB/interoperabilidade são outra seleção com sobreposição, portanto **não somar 23 + 65**. Sem suite integral nova, sem instalação limpa nem assinatura. Código preservado localmente, sem commit/push.
