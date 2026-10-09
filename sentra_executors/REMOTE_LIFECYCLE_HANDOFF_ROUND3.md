# Handoff da rodada 3 — Daytona / Guacamole / RustDesk

2026-10-09. Implementação em arquivos próprios; **testes preparados, não executados**.
Nenhum serviço foi instalado, iniciado ou conectado nesta rodada. O código do
RustDesk foi preparado para um build próprio; não foi compilado. Este arquivo
complementa a reavaliação37 sem alterar os documentos anteriores ou o núcleo.

## Fontes utilizadas

Seções 08, 13, 14 e 15 de
`docs/SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md`.
Revisões registradas no catálogo existente, não verificadas em runtime aqui:

| Clone | Revisão registrada | Fonte do comportamento incorporado |
|---|---|---|
| Daytona | `fc98a5032c04e13de737b8d4d45dd2c7e5d1291a` | `libs/sdk-python/src/daytona/_sync/process.py`, `_sync/sandbox.py`, `handle/pty_handle.py`, `_utils/stream.py` |
| guacamole-client | `38e8cb8ff5cd1fbd4c08a1a5d94340c37741230b` | `ConfiguredGuacamoleSocket.java`, `guacamole-common-js/.../Client.js`, `Tunnel.js`, `Parser.js`, `SessionRecording.js` |
| guacamole-server | `ae12b8e51aa6287d0eca7a50c6cac04af4a71590` | `src/libguac/protocol.c`, `recording.c`, `src/guacd/man/guacd.8.in`, Dockerfile e plugins RDP/VNC/SSH |
| RustDesk | `1d4abd0258bb6678cdd5e2abe3a2af59fd3d7dbe` | `src/client.rs::secure_connection`, `common.rs::decode_id_pk*`, `core_main.rs`, `flutter/windows/runner/main.cpp`, `flutter/lib/common.dart` |

O cliente guacd implementa o protocolo público de comprimento em caracteres
Unicode, UTF-8, `select/args/connect/ready` e negociação `VERSION_*` conforme
[protocolo oficial](https://guacamole.apache.org/doc/gug/guacamole-protocol.html).
Os parâmetros dos plugins dependem do serviço instalado, conforme a
[configuração oficial](https://guacamole.apache.org/doc/gug/configuring-guacamole.html).
O plano OSS RustDesk usa `hbbs/hbbr` e as portas nativas descritas na
[implantação oficial](https://rustdesk.com/docs/en/self-host/rustdesk-server-oss/docker/).
Não há implementação de um protocolo RPC RustDesk inventado.

## Arquivos desta rodada

Novos:

- `sentra_executors/identity_sessions.py`: escopo, ownership persistido, intent reservado, cursor e exportação.
- `sentra_executors/daytona_sessions.py`: backend SDK real, bindings e declaração própria.
- `sentra_executors/remote_guacamole.py`: transporte TCP/TLS guacd e operações por sessão.
- `sentra_executors/remote_guacamole_tunnel.py`: WebSocket Guacamole com dispatcher central obrigatório.
- `sentra_executors/remote_guacamole_viewer.js`: viewer e playback com a biblioteca Guacamole real fornecida pelo host.
- `sentra_executors/remote_rustdesk.py`: launcher nativo próprio com ownership e pinning exigido.
- `sentra_executors/remote_rustdesk_build.py`: gerador de patch revisável, sem aplicar alterações ao clone.
- `sentra_executors/remote_rustdesk_gate.rs`: gate de identidade no handshake nativo e watchdog de lease.
- `sentra_executors/remote_deployment.py`: Compose/argv reais, declarativos, sem executar implantação.
- Este handoff e os três arquivos de testes listados abaixo.

Alterações pontuais:

- `sentra_executors/daytona.py`: checkpoints antes do acesso e comando SDK.
- `sentra_executors/daytona_lifecycle.py`: checkpoints antes de discover/status/create/get/delete.
- `sentra_executors/remote_readonly.py`: checkpoints e deadline total de leitura.
  Seu transporte HMAC de laboratório continua distinto dos providers reais.

## Integração central

Todos os executores novos herdam o `GuardedExecutor` vigente por `SessionExecutor`.
Usam `OperationRequest`/`OperationResult`; não alteram `_base.py` nem
`central_integration.py`. Construção das declarações pelo host:

```python
from sentra_executors.identity_sessions import SessionJournal
from sentra_executors.daytona_sessions import (
    DaytonaConnectionConfig, DaytonaSessionBinding, declare_daytona_session_machine,
)
from sentra_executors.remote_guacamole import GuacamoleBinding, declare_guacamole_machine
from sentra_executors.remote_rustdesk import RustDeskPeerBinding, declare_rustdesk_machine

# journal_paths deve apontar para storage protegido do host. artifact_paths deve
# permitir apenas os outputs do WorkItem; não dê escrita do journal ao agente.
journal = SessionJournal(host_journal_absolute_path, journal_paths)
declaration = declare_daytona_session_machine(
    machine_id=host_machine_id, owner_principal_id=factory.agent_id,
    bindings=(configured_daytona_binding,), journal=journal, policy=None,
)
factory.register_execution(declaration)  # instala a policy central real
request = factory.dispatch_request(
    run_id=run_id, work_item_id=work_item_id, machine_id=host_machine_id,
    capability_id=configured_daytona_binding.capability_id,
    operation_id=fresh_operation_id, arguments={"action": "session.list"},
)
result = await factory.submit(run_id=run_id, request=request)
```

O mesmo registro vale para `declare_guacamole_machine()` e
`declare_rustdesk_machine()`. Os argumentos comuns das declarações são
`machine_id, owner_principal_id, bindings, journal, policy, backend=None`.
`backend` injetado existe para teste explícito; não demonstra transporte real.
Sem policy válida, o adapter direto nega execução. Não usar um lambda permissivo
como configuração de produção.

`SessionScope` inclui **machine/principal/capability/work_item**. Trocar WorkItem,
capability ou binding invalida a sessão; não existe handoff implícito. A ligação
ao Run vem de cada despacho central. O SQLite não concede grants e não substitui
o journal de Operations do centro. Guardar o journal, configurações, runtime
RustDesk, manifest e bundle em diretórios protegidos do host, separados dos
outputs autorizados ao agente. Ownership de OS/subprocessos exige esses controles
do host; diretórios temporários e mocks não são prova de isolamento.

Antes de cada I/O composto há `effect_checkpoint()` via ContextVar central. O
cliente Daytona instala também checkpoints em cada HTTP request gerado pelo SDK.
A exclusão física/renovação de lease fica no worker do `_base` atual. Timeout do
waiter **não** é prova de processo remoto interrompido. `UNCERTAIN` não autoriza
repetição de create/stdin/command; usar leitura/reconciliação explícita.

O centro deve classificar as novas leituras para seus budgets/observações: kinds
`daytona_session`, `guacamole`, `rustdesk`; ações `session.list`, `sandbox.read`,
`sandbox.reconcile`, `pty.read`, `command.read`, `read`, `recording.read`.
`read` RustDesk também renova o lease nativo: não é uma observação passiva para
fins de autorização. `reattach`, exports e input continuam operações admitidas.

## Daytona

`DaytonaConnectionConfig(api_url, target, credential, allowed_sdk_versions,
pty_handle_sha256, request_timeout_seconds=8)` exige endpoint explícito HTTPS
(HTTP somente loopback numérico), callback de credencial e pins revisados.
Não usa credenciais/endpoint/região implícitos do ambiente.
`DaytonaSessionBinding(capability_id, connection, paths, ...)` configura inventory,
snapshot, allowlist de comandos, stdin, timeout, budgets e auto-stop/archive/delete.

| Ação | Argumentos além de `action` | Efeito |
|---|---|---|
| `session.list` | `limit?` | IDs próprios persistidos; não afirma estado remoto atual |
| `sandbox.create` | nenhum | snapshot confiável, privado, rede bloqueada, labels próprios |
| `sandbox.read` | `session_id` **ou** `inventory_sandbox_id` | observação SDK real, inventário fixado pelo host |
| `sandbox.reconcile` | `session_id` | recupera ID após create incerto por labels; não recria nem confirma a Operation original |
| `sandbox.start/stop/delete` | `session_id` | somente sandbox criado por este escopo; nunca o emprestado |
| `pty.create` | `session_id` do sandbox, `rows?/cols?` | PTY persistente com ID gerado pelo backend |
| `pty.reattach` | `session_id` do PTY | verifica resource real e reconecta; registra gap |
| `pty.read` | `session_id, after?, wait_seconds?` | WS real, deadline de polling, saída/código de saída real se conhecido |
| `pty.write` | `session_id, text` | stdin autorizado, até 8192 bytes, sem registrar o conteúdo |
| `pty.resize` | `session_id, rows, cols` | resize SDK real |
| `pty.disconnect` | `session_id` | fecha stream local e preserva shell remoto |
| `pty.cancel` | `session_id` | solicita kill do PTY remoto e fecha stream próprio |
| `command.create` | `session_id` do sandbox | sessão de comando com ID próprio |
| `command.execute` | `session_id, command` | um comando allowlisted assíncrono por sessão |
| `command.read` | `session_id, after?, wait_seconds?` | stdout/stderr via WS oficial, não snapshot HTTP ilimitado |
| `command.input` | `session_id, text` | stdin do comando vinculado, autorizado separadamente |
| `command.cancel` | `session_id` | delete da sessão SDK, terminando seus comandos |
| `evidence.export` | `session_id, output` absoluto `.json` | snapshot do journal recebido, sem garantia de completude |

Dependencies: distribuição instalada `daytona` em versão **exata** aprovada pelo
host, `httpx`, `httpx-ws`, `wsproto`, `urllib3` compatíveis com essa versão. O clone
Python anuncia `0.0.0-dev`; isso não prova instalação. A fonte estudada requer
httpx 0.28.x e httpx-ws >=0.7,<1. O SHA256 de `PtyHandle` instalado é obrigatório,
pois o receive bounded usa internals revisados e evita `wait(timeout)` que só
verifica tempo depois de receber dados. APIs privadas divergentes são unsupported.
Não preencher o pin com o hash do clone sem comprovar qual pacote foi instalado.

O serviço Daytona precisa oferecer API/toolbox/PTY WS e inventory privado com
`network_block_all=True`, ou snapshot confiável para provisionamento. As flags são
**relatos do provider**, `attested_isolation=False`. Não há nesta rodada previews,
montagem de volumes, restore/snapshot de processo ou perfil de egress liberado.

## Guacamole

`GuacamoleBinding` fixa host/porta guacd, protocolo `rdp/vnc/ssh`, parâmetros do
target, CA, SHA256 do certificado DER, versões e canais. Credenciais vêm de
callback `secrets` separado; não entram no frontend, parâmetros persistidos ou
recording. TLS verifica CA/hostname **e** pin. Sem TLS só loopback numérico,
sem alegação de autenticação do daemon. guacd `ready` não prova login/identidade
do desktop; evidencia apenas o tunnel. View-only exige `read-only` anunciado pelo
plugin; se indisponível, falha explicitamente.

Ações: `session.list(limit?)`, `open`, `read(session_id, after?, wait_seconds?)`,
`reattach(session_id)`, `write(session_id, opcode, args)`, `close(session_id)`,
`recording.export(session_id, output)`, `recording.read(session_id, after?)`.
`open` não aceita endpoint/remote ID. Reattach usa somente `$id` já vinculado,
dependendo de o guacd ainda manter a conexão; não inventa replay. Close encerra
o tunnel próprio, não afirma logout/destruição do desktop remoto.

Input: `key/mouse/touch` precisam constar em `allowed_input`. Sync/ack/nop são
controles de transporte. Clipboard, upload/download, drive, audio/video e pipes
ficam desabilitados/rejeitados; mouse e display podem fazer parte da saída visual.
Sessões view/control são bindings/escopos distintos: elevar o privilégio de uma
sessão existente precisaria de um handoff central, que não está implementado.

`GuacamoleTunnelServer(dispatch=..., allowed_origins=(host_ui_origin,), port=8766)`
usa `websockets>=15,<17` com API sync. `issue(...)` é host-only, **após** autorizar
Run/WorkItem e a sessão local; gera ticket single-use com TTL máximo 60 segundos.
`serve()` só abre listener em 127.0.0.1 quando chamado explicitamente; configurar
origins da UI, usar seu context manager e `serve_forever()` em thread do host.
O callback **síncrono** `dispatch(ticket, arguments)` deve:

1. Conferir `ticket.principal_id == factory.agent_id` e a associação da sessão
   autorizada antes de emitir ticket; não aceitar identidade do frontend.
2. Encaminhar para o loop central via `asyncio.run_coroutine_threadsafe()`.
3. Criar `fresh_operation_id`, `factory.dispatch_request(...)` com
   `ticket.run_id/work_item_id/machine_id/capability_id`, depois `await factory.submit(...)`.
4. Retornar `OperationResult` real. Não retornar dicionário de sucesso fabricado;
   se timeout/UNCERTAIN, não reenviar a entrada automaticamente.

Cada leitura/input passa por esse despacho. Cursor gap ou revogação encerra o
viewer. Fechamento tenta close central; se a policy já não admitir close, o host
deve executar teardown do backend próprio, sem usar essa limpeza para emitir
nova entrada remota. `backend.shutdown()` fecha só seus sockets. O host deve
ligar revogação/encerramento do Run a esse teardown; registro sozinho não cria
um monitor automático de revogação para conexões ociosas.

`liveViewer(Guacamole, scopedURL, container)` renderiza display usando
`Guacamole.Client`; não conecta keyboard/mouse implicitamente. Host monta a
biblioteca guacamole-common-js real e publica este módulo. `offlineRecording(...)`
oferece play/pause/seek usando `SessionRecording`; o tunnel de playback não tem
endpoint e não envia input. Rejeita eviction inicial e gaps. A captura é local ao
stream recebido; não contém chunks ainda em trânsito, nem garante gravação íntegra.
Aceitação visual de playback e wiring da UI continuam pendentes para o núcleo.

Deployment: `guacd_native_command(...)` usa os flags reais `-f -b -l -C -K`.
`guacd_compose(image="guacamole/guacd@sha256:...", certificate_file=...,
private_key_file=...)` devolve Compose com TLS e porta publicada só em loopback.
É JSON compatível com Compose; o host salva/aplica posteriormente. Não foi
executado. Certificado deve ter SAN do hostname do binding; chave deve ser
legível pelo usuário guacd no container. A fonte clonada é 1.6.1; negociar 1.6.0
não é prova de qual build do daemon está implantado. Fixar imagem/JS/versão e
demonstrar o plugin remoto em aceitação.

## RustDesk

`RustDeskPeerBinding` aceita alias/peer ID do **inventário do host**, SHA256 da
chave de identidade Ed25519 do peer, servidor/chave root rendezvous, executável
absoluto/hash, manifest de build, runtime root e paths. Request não pode fornecer
peer ID, chave, endpoint, PID ou executável. `open`, `read`, `reattach`, `close`,
`evidence.export` e `session.list` são as ações. Nenhuma sessão é adotada por PID
após restart do host. Reattach só retoma processo ainda retido pelo próprio backend.

O CLI stock pode delegar a GUI existente e não oferece a garantia de pin exigida:
ele é **unsupported** nesta binding. `native_peer_gate_patch(source_root)` gera
diff/source hashes revisáveis, sem tocar no clone; cada âncora deve aparecer uma
vez. Aplicar em checkout de build próprio do host na revisão aprovada e executar
o build nativo Flutter normal com submódulos/dependências reais. O patch insere:

- perfil privado antes de `global_init`, servidor/root explícitos e watchdog;
- recusa de filhos service/install com ambiente herdado, evitando abrir outra GUI implicitamente;
- argumentos Flutter da conexão própria, sem delegação stock via IPC;
- no runner Windows, bloqueio de delegação a outra janela existente;
- verificação do ID/root e SHA256 da chave de peer na `secure_connection` nativa;
- recusa da ausência de identidade verificada e fallback sem conexão segura;
- recibo local somente após handshake nativo verificado, antes do login desktop.

Gate usa os verificadores e protocolo nativos de RustDesk; não calcula assinatura
RustDesk por conta própria. O hash esperado é o da chave de identidade do peer,
**não** o de `id_ed25519.pub` do servidor hbbs. Ambos os valores precisam de
provisionamento confiável do host. Um manifest host-owned deve conter:

```json
{
  "extension": "sentra-peer-gate-v1",
  "source_revision": "revisao-real-do-build",
  "stock_cli_supported": false,
  "executable_sha256": "sha256-real-do-launcher",
  "bundle_sha256": {
    "librustdesk.dll": "sha256-real-da-biblioteca-instrumentada",
    "client.exe": "sha256-real-do-launcher"
  }
}
```

No Linux, incluir binário/bibliotecas/dados efetivamente carregados. No Windows,
DLL é obrigatória. Host deve pin/arrolar o bundle completo e impedir escrita nele;
manifest/hash não são atestação remota. Processos são retidos por handle de kernel
e, no Windows, job com kill-on-close. Lease local curto (default 3s, máximo 5s)
é renovado por operação central autorizada; native watchdog encerra por expiração.
É instrumentation local do build próprio, não grant independente.

Open comprova apenas o recibo do handshake do native build. Read retorna
`identity_last_verified=True`, **`current_transport_state="UNKNOWN"`**: processo
vivo/recibo antigo não provam peer ainda online. `desktop_login_asserted=False`,
`control_api_available=False`. Reconexão nativa passa novamente pelo pin; o
recibo inicial não é usado como prova de estado atual. **Ainda faltam** build e
aceitação reais, integração de callbacks/frame/login/controle por canal e gravação
nativa revisada. Não publicar RustDesk como executor operacional de desktop só
com este launcher/manifest ou com testes unitários.

`rustdesk_server_compose(image=...@sha256:..., data_directory=..., relay_address=...,
bind_address=...)` gera configuração OSS hbbs/hbbr com diretório de keys persistido,
21115/TCP, 21116/TCP+UDP, 21117/TCP e interface explícita. Não publica portas web.
O clone do cliente não contém automaticamente servidor implantado, pares
configurados nem aprovação de login do peer.

## Evidência, cursores e aceitação posterior

Cursor é sequence local de bytes ingressados, com `epoch`, `first_sequence`,
`gap`, `more` e hashes. Não é offset remoto. Reconnect marca gap; não afirma
reprodução/deduplicação remota. Retenção é limitada por sessão (default 16MiB e
10000 eventos). Listas/páginas/polls são limitados. O histórico de sessões/intents
precisa de política de archive/retention do host; não há GC automático global.

Export chama `rpa.atomic_output` existente: lock real cross-process por caminho,
publicação sem overwrite por promoção exclusiva, verificação antes de publicação
e **`current_effect_context.capture_output` imediatamente após publicar, antes de
liberar o lock**. Evidence devolve `artifact_id/resource_uri` quando central
presente. Falha de captura depois de publicar é UNCERTAIN; não há sucesso durável
falso. Standalone só informa arquivo/hash local. Não foi alterado `rpa.py` nesta
rodada. Originais são preservados quando verificação/publicação exclusiva falha.

Testes preparados para o main executar na validação integral:

```powershell
python -m pytest tests/unit/test_sentra_executors_remote_sessions_round3.py tests/unit/test_sentra_executors_daytona_sessions_round3.py tests/unit/test_sentra_executors_rustdesk_sessions_round3.py
```

Sem flags, testes de provider real são skip explícito, não sucesso simulado.
Fixture TCP Guacamole verifica framing/gate; **não** prova guacd/desktop. Byte
fixtures RustDesk nunca são lançadas. A validação central também deve demonstrar
revogação durante I/O, UNCERTAIN sem replay, captura Artifact/restart, lease expirada
e propriedade exclusiva com outras máquinas/agentes.

Para aceitação real posterior, configurar env **no ambiente de teste**:

- `SENTRA_DAYTONA_ACCEPTANCE=1`; API_URL, TARGET, API_KEY, SDK_VERSION, PTY_SHA256,
  SANDBOX_ID com prefixo `SENTRA_DAYTONA_`. Teste cria/usa/mata seu PTY; não deleta
  sandbox emprestado. Prerequisito shell com printf no sandbox autorizado.
- `SENTRA_GUACD_ACCEPTANCE=1`; HOST, CERT_SHA256, CA_FILE, PROTOCOL,
  PARAMETERS_JSON, PORT opcional e SECRETS_JSON separado com prefixo
  `SENTRA_GUACD_`. Deve receber instruções reais de display, não só `ready`.
- `SENTRA_RUSTDESK_ACCEPTANCE=1`; EXECUTABLE, EXECUTABLE_SHA256, BUILD_MANIFEST,
  PEER_ID, PEER_SHA256, SERVER, SERVER_KEY com prefixo `SENTRA_RUSTDESK_`.
  Requer desktop gráfico/native bundle instrumentado e peer real provisionado.
  Teste exige receipt/pin/reattach/close e rejeita pin errado; não afirma login,
  controle, vídeo ou isolamento do desktop.

Ao habilitar uma flag sem configuração completa, o teste falha. Nenhum desses
comandos/flags foi executado nesta rodada.
