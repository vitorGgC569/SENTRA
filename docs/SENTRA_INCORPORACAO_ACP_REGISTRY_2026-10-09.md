# SENTRA — incorporação ACP e Registry, primeira onda

Data: 2026-10-09. Workspace compartilhado: `C:/Users/vitor/OneDrive/Desktop/SENTRA`.

Esta entrega amplia as frentes `agent-client-protocol` e `acp-registry` da reavaliação dos 37 projetos. O objetivo integral dos 37 permanece em andamento. Foram consultados a reavaliação de 09/10, a auditoria integral, o estudo de reaproveitamento e a matriz Gate 5 de 08/10. Nenhum reset, commit, novo chat ou alteração de módulos de outra frente é necessário para consumir esta entrega.

## Fontes efetivamente inspecionadas

- `third_party/agent-client-protocol`, HEAD `8c4b8faff61055db8308d4c5dfc49b48b4d3a134`: `schema/v1/schema.json`, `schema/v2/schema.json`, schemas unstable, structs `agent.rs` e `tool_call.rs` de ambas as revisões e documentação de initialization, session setup, config e tool calls.
- `third_party/acp-registry`, HEAD `f44424b681c13cb0f43fdbd743530498921d0d92`: `agent.schema.json`, `.github/workflows/registry_utils.py` e descriptors reais codex-acp, antigravity-acp e fast-agent.

O v2 deste snapshot é draft e exige opt-in `supported_versions=(1, 2)` ou `(2,)`. O padrão continua `(1,)`. O descriptor e um checksum do catálogo não são prova de confiança independente no pacote.

## Arquivos desta frente

| Arquivo | Implementação |
|---|---|
| `sentra_interop/acp.py` | Métodos JSON-RPC reais de lifecycle/config, negociação, escopo, prompt por revisão e hook físico central |
| `sentra_interop/acp_local.py` | Supervisor com reattach explícito, novos métodos e ledger local existente preservado |
| `sentra_interop/acp_session.py` | Mapeamento SQLite de sessão, recibos locais antirreplay e projeção de updates |
| `sentra_interop/acp_process.py` | Grupos POSIX e Windows Job Object kill-on-close; processo Windows suspenso até vincular ao job |
| `sentra_interop/registry.py` | Descriptors completos, múltiplas variantes e plano do catálogo versionado |
| `sentra_interop/registry_install.py` | Seleção por plataforma, validação de env/argv/pins e planos sem execução |
| `sentra_interop/acp_verified.py` | Vínculo opcional entre plano binary e manifesto local com autenticação HMAC independente |
| `tests/unit/test_sentra_interop_acp_lifecycle.py` | Fixture stdio explícita v1/v2, restart/reattach, negativos e descendentes reais |
| `tests/unit/test_sentra_interop_registry_install.py` | Descriptors dos clones, pins, env, diagnósticos e verificação de plano instalado |

## Contrato de sessão e autorização

O host constrói `ACPSessionAdapter(gate, transport, workspace=..., store=..., provider=..., local_session_id=..., supported_versions=...)`. `store` é opcional; quando usado, o ID local precisa ser explícito. O banco de `ACPSessionStore(database, workspace=...)` fica dentro do workspace. A conexão deve ser nova após falha de initialize; a negociação não é repetida implicitamente no mesmo transporte.

As operações recebem os contratos existentes `OperationRequest`, `OperationResult` e `DispatchOutcome`. Cada capability deve ser anunciada pela `Machine` e concedida pelo gate existente. Os argumentos têm igualdade exata com a tabela; campos extras são recusados. Diretórios precisam existir dentro do workspace e são normalizados antes da comparação. A sessão vincula principal, machine e work item: um pedido de outro escopo não reutiliza sua conexão.

| API | Capability | `request.arguments` | Wire |
|---|---|---|---|
| `open(request, cwd=...)` | `acp:session` | `{"cwd": normalized_cwd}` | `session/new` |
| `resume(request, session_id=..., cwd=...)` | `acp:resume` | `{"session_id": id, "cwd": normalized_cwd}` | `session/resume` |
| `resume(..., load_history=True)` | `acp:load` | mesmos argumentos de resume | `session/load`, somente v1 com `loadSession: true` |
| `reattach(request)` | `acp:resume` | ID e cwd do binding persistido | resume do mesmo ID, sem fallback |
| `list_sessions(request, cwd=None, cursor=None)` | `acp:list` | `{"cwd": normalized_cwd_or_null, "cursor": cursor_or_null}` | `session/list`, uma página por operação |
| `close_session(request)` | `acp:close` | `{"session_id": bound_id}` | `session/close` |
| `delete_session(request, session_id=...)` | `acp:delete` | `{"session_id": id}` | `session/delete`; tombstone persistido |
| `set_config_option(request, config_id=..., value=...)` | `acp:config` | `{"session_id": bound_id, "config_id": id, "value": value}` | `session/set_config_option` |
| `set_model(request, model_id=...)` | `acp:config` | mesma estrutura de config, ID da única opção `category: model` | `session/set_config_option` |
| `set_mode(request, mode_id=...)` | `acp:mode` | `{"session_id": bound_id, "mode_id": id}` | `session/set_mode`, somente v1 e modo anunciado |
| `prompt(request, text)` | `acp:prompt` | `{"session_id": bound_id, "text": text}` | `session/prompt` |
| `cancel(request)` | `acp:cancel` | `{"session_id": bound_id}` | notificação `session/cancel` |

`supports(method)` informa suporte negociado. No v1, list/resume/close/delete exigem objetos não nulos em `agentCapabilities.sessionCapabilities`; `{}` anuncia suporte, `true`, `false`, ausência e `null` não. Load usa a capability booleana específica. No v2, `capabilities.session` precisa ser um objeto: new/list/resume/close/prompt/cancel são baseline desse surface; delete continua opcional. O schema contém uma descrição abreviada do baseline, mas os structs e a documentação de lifecycle definem list/resume/close como obrigatórios para o surface v2. Não se presume que v1 anuncie os mesmos métodos.

Config admite escolhas `select` simples ou agrupadas e `boolean`. Valores devem constar das escolhas anunciadas e boolean não aceita inteiro. A resposta de config substitui a lista inteira, que pode mudar conforme a seleção. O schema efetivo usa `id` na opção e `configId` no pedido. Não existe `session/set_model` em nenhum dos quatro schemas deste clone: esse método não é enviado. No v2, seletores de modo também devem usar config quando anunciados.

`ACPLocalLifecycle(..., local_session_id=..., provider=...).start(..., reattach=True)` lança um novo processo autorizado e usa o binding para retomar a sessão remota existente. São necessários novos IDs de operação/key para launch e resume. Com `reattach=False`, uma associação existente impede criar outra sessão com o mesmo ID local. Para compatibilidade, sem `local_session_id` o supervisor conserva seu ledger anterior e permite criação explicitamente nova com outra operação; não infere que work item seja identidade de sessão. O supervisor oferece os demais métodos acima; `close()` limpa o transporte e apenas desanexa localmente. Para encerramento remoto, usar `close_session` antes de `close()`.

## Prompt, updates e durabilidade

No v1, sucesso de prompt inclui `stopReason` e preserva `_meta` quando enviado. Cancel enviado continua `UNCERTAIN` até confirmação remota; uma resposta `stopReason: cancelled` converte o resultado do prompt para `CANCELLED`.

No v2, o resultado do prompt é `{"messageId": ..., "completionConfirmed": false}` e preserva `_meta`. `SUCCEEDED` confirma apenas a inserção da mensagem na conversa remota. Não confirma término ou sucesso da tarefa. O consumidor deve continuar lendo `updates()` e consultar `adapter.state.foreground` para `running`, `requires_action` e `idle`/`stopReason`. A notificação idle pode chegar antes ou depois da resposta do prompt. Cancel não produz conclusão simulada.

`adapter.state` projeta tool calls, config, modos v1, comandos, uso/custo e informações de sessão. Os eventos brutos continuam disponíveis no iterador. Tool calls são informacionais e não autorizam ferramentas no SENTRA. Uso/custo reportado pelo provider é preservado com sua moeda e metadata, sem estimar valores ausentes.

- v1 segue `Option` e `ToolCall.update` do clone: campo ausente ou `null` não substitui o valor anterior; coleções concretas substituem, `[]` limpa. `tool_call_update` requer a tool inicial.
- v2 segue `MaybeUndefined` e `apply_update`: ausente preserva, `null` limpa explicitamente e fica `None` na projeção, concreto substitui. O primeiro update pode criar a tool. `content`/`locations` substituem arrays completos; `tool_call_content_chunk` acrescenta um item na ordem recebida. Substituição posterior descarta chunks anteriores; chunks posteriores partem da nova coleção.
- Revisão negocia o conjunto permitido de eventos. v2 admite mensagens, state, terminais informacionais e plan_update; v1 não recebe esses eventos como se fossem seu próprio schema.
- Contagem de tools, tamanho de projeção, linhas de transporte, fila e IDs pendentes possuem limites. Projeção de tools/config/uso não é uma transcrição durável.

O binding durável guarda ID local/remoto, provider, principal, machine, work item, cwd, revisão e estado. Recibos guardam hashes do pedido, IDs/key, método e estado. Não guardam prompt, tool input/output, configurações, tokens ou transcript. `receipt(operation_id)` mostra IN_FLIGHT como UNCERTAIN após recuperação e não envia RPC. Criação IN_FLIGHT/UNCERTAIN também bloqueia uma tentativa de substituição usando outra key para o mesmo ID local. Binding conhecido pode ser retomado explicitamente; associação apagada permanece como tombstone.

Os recibos ACP complementam a prevenção local de replay; não concedem autoridade e não substituem o journal central. Quando o adapter recebe gate com `physical_context`, somente o journal desse gate registra as operações; o store ACP mantém a associação de sessão, sem gravar um segundo recibo de efeito. Não há reattach por PID, repetição automática de prompt, fallback de resume para new, nem reconhecimento fictício de conclusão quando o transporte cai.

## Fronteira física central e processos

`ACPStdioTransport.launch` mantém os requisitos anteriores: executável absoluto existente, argumentos/cwd iguais ao pedido, política com paths/roots e hash de argv, journal reserve antes do efeito, nova decisão após spawn e cleanup se houver revogação/falha. `env` não vazio segue recusado e o filho não herda tokens.

Depois de `await gate.journal.reserve(request)`, quando o host oferece `gate.physical_context(request)`, launch obtém esse `CentralEffectContext` e usa `run_async` para o spawn real. O checkpoint é executado antes da criação efetiva do processo e, no Windows, antes de retomar sua thread. O journal injetado continua recebendo finish/status/evidência. A implementação não adiciona uma autoridade de operações para esse caminho central.

Gates locais não precisam desse método. Há `launch_hook(effect_factory)` opcional, callable fornecido somente pelo host confiável. Um contexto ativo também é reconhecido via `current_effect_context`. O contexto físico fornecido pelo gate tem precedência. Escritas no pipe verificam checkpoint quando dentro de contexto central. Cancel também usa `physical_context` após sua reserva, pois seu caminho de notificação não chama `gate.execute`. Prompt v1 cancelado retorna resultado terminal ao gate central para persistir CANCELLED uma única vez.

POSIX usa sessão/grupo dedicado e envia TERM, espera limitada e KILL ao grupo, inclusive quando o líder já saiu. Windows usa Job Object com `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; o filho nasce suspenso, é associado ao job e sua thread é retomada somente depois. Fechar o job encerra os descendentes associados. Não há shell/taskkill por string, apropriação de PIDs encontrados no sistema ou reutilização de PID persistido. Cancelamento/timeout do spawn acompanha o handle obtido tardiamente e limpa o processo possuído.

## Planos Registry

`ACPVersionedCatalog.from_index(..., schema_version=..., pinned_versions=..., channels=...)` exige pins explícitos. `catalog.installation_plan(agent_id, version=..., system=..., architecture=..., kind=None, available_dependencies=frozenset())` retorna `ACPInstallationPlan` imutável com hash do catálogo e fingerprint do plano. Também há `entry.installation_plan(...)` sem hash de catálogo.

Sistemas aceitos: windows/linux/darwin, com aliases win32/macos; arquiteturas x86_64/aarch64, com aliases AMD64/x64/arm64. Variantes binary usam o target exato. Se houver várias distribuições, `kind` é obrigatório. Ausência do target não faz fallback silencioso.

| Distribuição | Plano |
|---|---|
| binary | URL HTTPS sem credenciais, checksum opcional diagnosticado, executable relativo contido, args/env, etapas de download em staging/verificação/extração/validação independente |
| npx | nome npm validado, incluindo scope, `@versão` exata; argv `--yes -- package args`; dependências node/npx |
| uvx | requisito PyPI exato `package==versão`, normaliza spelling legado `@versão`; argv `--from package==versão -- command args`; dependência uvx |

Não se aceita latest, ranges, URL como package, flag como package, traversal, command de shell ou scripts `.cmd/.bat/.ps1/.sh` como executable binary. O plano npx Windows diagnostica que `npx.cmd` exige launcher nativo aprovado; ele não inicia um shell para contornar esse limite. O host informa as dependências disponíveis: essa lista não constitui detecção automática de instalação.

Env dos descriptors é validado sem herdar ambiente. Nomes reservados são recusados, com comparação sem distinguir caixa e rejeição de duplicates/keys inválidas/NUL. A lista deriva dos nomes/prefixos de upstream e acrescenta os namespaces SENTRA/Codex e diretórios de perfil Windows. O plano com env comum continua diagnosticando `ENVIRONMENT_REQUIRES_SEPARATE_ADMISSION`; launch não passa esse env implicitamente.

Diagnósticos incluem dependência ausente, checksum ausente, conteúdo de pacote não verificado, confiança independente e autorização de launch pendentes. `launch_ready` é sempre false para um plano de descriptor. As etapas são dados para revisão, sem downloads, instalação ou execução automática. Planejar ou falhar a verificação não substitui a configuração ativa do agente.

`ACPVerifiedResolver.resolve(..., installation_plan=plan, installed_directory=...)` pode vincular um plano **binary stable sem env** a um executável já instalado e a um manifesto HMAC com chave provisionada externamente. Confere ID/version, caminho/argv e hash do executable assinado. Além dos argumentos preexistentes de `acp:resolve`, o pedido inclui `plan_sha256` e `installed_directory` normalizado. O plano não autentica sozinho seu archive. Pacotes npx/uvx exigem inventário/assinatura independente do pacote e launcher aprovado antes de habilitar sua execução; essa confiança não foi inventada nesta onda.

## Aceitação e validação final

Os testes novos identificam seus doubles e fixtures. Os testes de stdio iniciam um servidor Python local do próprio harness; não comprovam execução de Codex, Antigravity ou fast-agent. O teste de artefato HMAC faz hashing de bytes inertes e não executa esse arquivo. O teste de processos inicia filhos reais somente para verificar cleanup.

Comandos PowerShell, na raiz do workspace:

```powershell
python -m pytest -q tests/unit/test_sentra_interop_acp_lifecycle.py tests/unit/test_sentra_interop_registry_install.py
python -m pytest -q tests/unit/test_sentra_interop_sprint3_acp.py tests/unit/test_sentra_interop_phase3_registry.py tests/unit/test_sentra_interop_contracts.py tests/unit/test_sentra_interop_gate5.py tests/unit/test_sentra_interop_e2e.py -k 'acp or registry'
python -m pytest -q tests/unit/test_sentra_interop_gate3.py -k acp
```

Critérios locais: uma única criação e um único prompt no trace mesmo após reinício; resume conserva ID e não faz new; scope errado/capability ausente não chegam ao método remoto; v2 distingue ack de idle; patch não perde campos omitidos; launch físico é obtido após reserve; filho e descendente são encerrados; descriptors Windows/uvx reais do clone geram planos exatos sem efeito externo; plano instalado só é aceito quando coincide com o manifesto independente e a política.

Resultado da validação final nesta frente:

- Rodada combinada dos oito arquivos acima com `-k 'acp or registry' --tb=short`: **104 passed, 34 deselected em 15,86 s**. Inclui gates reais de ControlPlane/SQLite, processo/stdin/stdout locais reais, cleanup de descendentes Windows, os 26 casos existentes de restart/cancel/timeout e os negativos de transporte Gate 3.
- Após acrescentar o negativo de `session/load` indevidamente anunciado no v2 e endurecer esse gate de revisão, `test_sentra_interop_acp_lifecycle.py`: **16 passed em 2,39 s**. Esse teste novo aumenta o conjunto selecionado em um caso.
- A rodada inicial encontrou 26 falhas de compatibilidade no supervisor por inferir ID local a partir de work item. A inferência foi retirada; a rodada combinada posterior passou. O mapeamento de sessão persistido exige `local_session_id` explícito, sem alterar a semântica anterior de criação explicitamente nova do supervisor.
- Não houve suite ampla do workspace durante implementação. Não foi executado provider externo, installer remoto ou download de pacote; os resultados acima não equivalem à validação desses componentes.

## Pendências para integração real

1. O host central deve injetar seu DurableInteropGate e anunciar/conceder as novas capabilities. `requests.py` ainda possui helpers de session/prompt; os demais pedidos podem ser construídos com `OperationRequest` diretamente até essa outra frente ampliar os helpers.
2. Registrar providers instalados/autorizados e escolher seu `provider`, ID local e revisão. Validar uma conversa real, retomar após reinício e confirmar opção/custo efetivamente suportados. Nesta entrega nenhum provider externo foi instalado ou iniciado.
3. Conectar projeções e a distinção ack/foreground ao Canvas. Não promover `messageId` para conclusão de WorkItem.
4. Implementar instalação governada em staging e promoção somente após validação de artefatos. Para npx/uvx, acrescentar confiança no pacote, inventário de dependências, launcher Windows e ambiente explicitamente admitido. O plano não substitui essa integração.
5. Continuam fora desta onda: autenticação/login ACP, elicitation, permissão interativa, I/O privilegiado de arquivos/terminais, MCP via agente, roots adicionais, fork e replay de história v2 por cursor. Requests iniciados pelo agente continuam recusados pelo transporte; terminais de updates são apenas informacionais. `session/load` v1 tem replay de mensagens explícito, sem executar novos prompts.
6. Reanexação significa preservar a identidade remota via resume, e não manter ou recuperar um processo local antigo. Para recuperar transcript/projeções após novo processo, integrar o stream à retenção autoritativa do SENTRA; conteúdo bruto não é persistido por este banco de associação.
