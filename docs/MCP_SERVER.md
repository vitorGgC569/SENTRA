# SENTRA MCP Server

O SENTRA agora expõe suas capacidades locais como um servidor Model Context Protocol (MCP) usando o SDK Python oficial v2.

## Estado e transportes

- Protocolo declarado: MCP `2026-07-28`.
- Transporte padrão: `stdio`.
- Transporte remoto/local opcional: `streamable-http`.
- HTTP usa `127.0.0.1:8000` por padrão.
- SSE não é exposto pela configuração SENTRA.
- O servidor usa lifecycle MCP para encerrar todos os processos filhos gerenciados no shutdown.
- A superfície padrão é `core + developer + browser`; `oma`, `remote` e `admin` só entram quando explicitamente habilitadas (ou com `--surface all`).
- MCP HTTP `2026-07-28` é single-exchange/stateless: recursos persistentes do SENTRA usam uma sessão de aplicação opaca criada por `sentra_session_open`.

Instalação:

```powershell
cd C:\path\to\SENTRA
python -m pip install -r requirements.txt
python -B -m sentra_mcp
```

Streamable HTTP local:

```powershell
python -B -m sentra_mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Endpoint: `http://127.0.0.1:8000/mcp`.

## Segurança padrão

O MCP não concede acesso global ao computador por padrão. `allowed_roots` é uma allowlist explícita de workspaces/projetos e começa somente com a raiz do SENTRA. Novos roots podem ser solicitados pelo agente, mas só entram em vigor após aprovação local do operador.

Proteções principais:

- traversal, drive/UNC/device paths e escapes por link são bloqueados;
- `.git`, `.oma`, `runs`, `browser_profiles`, credenciais e arquivos de chave não são acessíveis pelas tools genéricas de filesystem;
- leitura/escrita/output/processos possuem limites configuráveis;
- terminal usa argv estruturado e `shell=False`;
- `cwd` de processos é confinado ao workspace selecionado;
- o teto de privilégio de processo é `sandbox < workspace < unrestricted` e o cliente nunca pode pedir um modo mais privilegiado que o configurado no servidor;
- o default é `process_mode=workspace`: execução ocorre em Linux Docker, com rede `none`, rootfs read-only, capabilities removidas, `no-new-privileges`, usuário 65532, limites de CPU/memória/PIDs e apenas o workspace aprovado montado;
- `sandbox` usa snapshot copy-on-write descartável; `workspace` usa o root aprovado; `unrestricted` é host e precisa ser autorizado explicitamente pelo operador;
- se Docker/isolamento não estiver disponível, `workspace` e `sandbox` falham fechados; nunca há fallback implícito para host;
- variáveis contendo TOKEN, SECRET, PASSWORD, API_KEY, COOKIE e variáveis Python de injeção são removidas dos filhos;
- IDs persistentes (process/search/browser/sandbox/job/research) são owner-scoped; em HTTP MCP 2026-07-28 o owner vem de um `session_token` assinado localmente, e outro token não pode acessar esses IDs;
- `kill_process` só aceita PID registrado pelo próprio ProcessService;
- shutdown encerra a árvore de todos os processos gerenciados;
- mutações de filesystem/processos são auditadas sem registrar conteúdo/argumentos sensíveis;
- OMA é observacional: não existe tool MCP de promoção/aplicação de candidato.

Os bloqueios de comandos são guardrails e não substituem uma sandbox de SO. Para código não confiável, use a camada Docker/sandbox do SENTRA.

## Configuração

Variáveis de ambiente:

| Variável | Padrão |
|---|---|
| `SENTRA_MCP_ALLOWED_ROOTS` | raiz SENTRA |
| `SENTRA_MCP_BLOCKED_COMMANDS` | comandos destrutivos padrão |
| `SENTRA_MCP_MAX_READ_BYTES` | 8 MiB |
| `SENTRA_MCP_MAX_WRITE_BYTES` | 8 MiB |
| `SENTRA_MCP_MAX_OUTPUT_BYTES` | 2 MiB |
| `SENTRA_MCP_MAX_PROCESSES` | 4 |
| `SENTRA_MCP_PROCESS_MODE` | workspace |
| `SENTRA_MCP_SANDBOX_IMAGE` | oma-sandbox:local |
| `SENTRA_MCP_SANDBOX_CPUS` | 2.0 |
| `SENTRA_MCP_SANDBOX_MEMORY_MB` | 2048 |
| `SENTRA_MCP_SANDBOX_PIDS` | 256 |
| `SENTRA_MCP_SURFACES` | core,developer,browser |
| `SENTRA_MCP_HOST` | 127.0.0.1 |
| `SENTRA_MCP_PORT` | 8000 |
| `SENTRA_MCP_AUDIT_LOG` | .sentra/mcp-audit.jsonl |
| `SENTRA_MCP_TRANSPORT` | stdio |
| `SENTRA_MCP_ALLOW_NON_LOOPBACK` | false |

CLI equivalente:

```text
--transport stdio|streamable-http
--host HOST
--port PORT
--allowed-root PATH              (repetível)
--blocked-command NAME           (repetível)
--max-read-bytes N
--max-write-bytes N
--max-output-bytes N
--max-processes N
--process-mode sandbox|workspace|unrestricted
--sandbox-image IMAGE
--sandbox-cpus N
--sandbox-memory-mb N
--sandbox-pids N
--surface core|developer|browser|oma|remote|admin|all  (repetível)
--audit-log PATH
--allow-non-loopback
```

Não use `--allow-non-loopback` para publicar o servidor diretamente na internet. Adicione autenticação/TLS em uma camada apropriada ou use um túnel MCP seguro.

## Tools

### Core

- `sentra_health`
- `sentra_session_open`

No HTTP MCP 2026-07-28, chame `sentra_session_open` uma vez por conversa. O token opaco retornado é assinado pelo SENTRA, expira (24 h por padrão) e deve ser enviado como `session_token` nas tools que mantêm IDs entre chamadas. Reconectar o HTTP com o mesmo token preserva o owner; abrir outra sessão gera outro owner. O token não substitui OAuth: quando OAuth está ativo ele também fica vinculado ao principal autenticado.

### Filesystem

- `sentra_list_directory`
- `sentra_read_file`
- `sentra_read_multiple_files`
- `sentra_file_info`
- `sentra_search`
- `sentra_create_directory`
- `sentra_move_file`
- `sentra_delete_path`
- `sentra_write_file`
- `sentra_edit_block`

### Terminal / processos

- `sentra_start_process`
- `sentra_read_process_output`
- `sentra_interact_process`
- `sentra_list_sessions`
- `sentra_terminate_session`
- `sentra_list_processes`
- `sentra_kill_process`

`sentra_start_process` aceita string ou argv, timeout, `cwd`, `workspace`, `mode` e imagem confiável opcional. O argumento `owner` é apenas um rótulo adicional namespaced sob a sessão real; em HTTP moderno, `session_token` é obrigatório para o ciclo de vida persistente.

### Repository

- `sentra_repo_workspaces`
- `sentra_repo_read`
- `sentra_repo_search`
- `sentra_repo_tree`
- `sentra_repo_symbol`
- `sentra_repo_status`
- `sentra_repo_diff`
- `sentra_repo_test`

As tools de repositório reutilizam `repository.CommandGateway` e aceitam um seletor opcional `workspace` (`root:0`, `root:1`, ...). Sem seletor, `root:0` continua sendo o SENTRA para compatibilidade. `sentra_repo_workspaces` lista a allowlist ativa e informa quais roots parecem repositórios Git. Não existe endpoint de shell arbitrário no adapter. `sentra_repo_test` executa somente a operação TEST registrada.

#### Workspaces dinâmicos e permissões

`WorkspaceRegistry` é a autoridade para grants em runtime. `allowed_roots` de configuração é apenas bootstrap estático. O agente pode solicitar, mas nunca autoaprovar:

1. `sentra_request_workspace(path, alias, permissions, lifetime)`;
2. permissions: `read`, `read+write` ou `read+write+execute` (write/execute implicam read);
3. lifetime: `session`, TTL como `24h`/ `7d`, ou `permanent`;
4. aprovação local: `python -m sentra_remote.admin approve-workspace <request_id>`;
5. remoção: `sentra_request_remove_workspace` + a mesma aprovação local.

`sentra_request_allowed_root` permanece somente como alias de compatibilidade para um grant permanente `read+write+execute`. Grants `session` pertencem ao `session_token` da conversa; TTL expira automaticamente; roots aninhados usam o root mais específico. `workspace_id` é estável (`config:N`/`ws:...`), enquanto `root:N` é apenas um selector efêmero.

### Jobs assíncronos

- `sentra_test_start`
- `sentra_job_start` (`TEST|LINT|TYPECHECK|BUILD|BENCH`)
- `sentra_job_status`
- `sentra_job_wait`
- `sentra_job_result`
- `sentra_job_cancel`
- `sentra_list_jobs`

Jobs persistem independentemente do timeout curto do connector. `wait` é limitado a 25 s por chamada; a operação continua no servidor e pode ser consultada depois. Cancelamento propaga para a operação registrada e cleanup de container/processo.

### Documentos estruturados

- `sentra_document_info`
- `sentra_read_document`: PDF, DOCX, CSV, Parquet, JSONL e ipynb
- `sentra_write_pdf`

### Browser e research

Browser unificado: `sentra_browser_open/tabs/navigate/extract/screenshot/click/type/close`. Edge é reservado a `chatgpt.com`; Playwright atende URLs gerais sob a política SSRF. Para `chatgpt.com`, tanto `backend="auto"` quanto `backend="edge"` são **principal-Edge-only**: se o bridge do perfil instalado não estiver disponível, a chamada falha fechado e nunca abre/faz fallback para um perfil Playwright separado. Para research no Edge, a extensão usa o **perfil em que foi instalada** e mantém **no máximo uma referência controladora** a uma aba ChatGPT já existente e inativa. Ela nunca cria ou fecha abas; se não houver uma aba segura para adotar, o job permanece sem controller até expirar/falhar de forma explícita. `CHAT_START` envia e devolve `conversation_id`/URL sem esperar a geração; `CHAT_COLLECT` volta depois pelo ID. Assim vários chats podem gerar no servidor enquanto a única aba adotada alterna entre IDs, sem manter uma aba por subagente. `sentra_browser_tabs` separa `tabs` de `edge_bridge`: `tabs: []` com `edge_bridge.state="IDLE"` significa bridge saudável e controller lazy não adotado por ociosidade; não deve ser interpretado como desconexão.

A extensão também observa UI transitória de “verificações adicionais” enquanto a geração está ativa. Quando o aviso de sistema/assistant-like é detectado, executa uma recuperação limitada `Stop → Continue`. Conteúdo dentro de mensagens do usuário é excluído da detecção, evitando disparo por texto citado no prompt.

Research:
- `sentra_research_start/status/wait/result/cancel`
- `sentra_list_research_runs`
- estratégias `single`, `parallel` e `mcts`.
- `mcts` é um **bounded MCTS-inspired beam search** (branches/depth/beam limitados), com judge separado e síntese; não é UCT completo.
- com `temporary=true`, todas as conversas criadas são removidas ao término/cancelamento, com retry limitado para gaps transitórios de worker READY.

### OMA / SENTRA

- `sentra_oma_health`
- `sentra_oma_runs`
- `sentra_oma_status`
- `sentra_oma_events`
- `sentra_oma_handoff`
- `sentra_oma_queue_status`
- `sentra_oma_reconcile_status`

A leitura de runs só aceita IDs validados e artifacts allowlisted em `runs/<run_id>`. Acesso genérico à `.oma` não é exposto.

## Resources

- `sentra://capabilities`
- `sentra://project/summary`
- `sentra://run/{run_id}/summary`

## Prompts

- `sentra_operator`

O prompt operacional reforça least privilege, owner de processos e a separação `CANDIDATE_READY != APPLIED`.

## Codex / ChatGPT Desktop

Clientes locais do Codex e o aplicativo ChatGPT Desktop podem adicionar um servidor MCP via UI escolhendo STDIO ou Streamable HTTP.

Exemplo `~/.codex/config.toml`:

```toml
[mcp_servers.sentra]
command = "python"
args = ["-B", "-m", "sentra_mcp", "--allowed-root", "C:\\path\\to\\SENTRA"]
cwd = "C:\\path\\to\\SENTRA"
startup_timeout_sec = 20
tool_timeout_sec = 120
```

Ou HTTP local:

```toml
[mcp_servers.sentra]
url = "http://127.0.0.1:8000/mcp"
startup_timeout_sec = 20
tool_timeout_sec = 120
```

Documentação OpenAI atual: https://developers.openai.com/docs/extend/mcp

## ChatGPT Web

O ChatGPT Web não conecta diretamente a um processo MCP local. Para um servidor local/privado, use o Secure MCP Tunnel da OpenAI; para um servidor público, use um endpoint MCP remoto protegido.

O passo a passo público para criar o túnel e a Runtime API key na OpenAI Platform, armazenar o segredo localmente com DPAPI, associar o workspace, executar `doctor`, validar `/healthz`/`/readyz` e fazer o primeiro smoke está em `docs/SECURE_MCP_TUNNEL.md`.

Não exponha o modo HTTP authless do SENTRA diretamente na internet e nunca versione a API key, o perfil local do tunnel-client ou arquivos DPAPI.

Referências:
- https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt
- https://developers.openai.com/api/docs/guides/tools-connectors-mcp

## Claude Desktop

Claude Desktop suporta servidores MCP locais e Desktop Extensions. Para desenvolvimento local, a configuração de servidor deve lançar:

```text
command: python
args: -B -m sentra_mcp --allowed-root C:\path\to\SENTRA
cwd: C:\path\to\SENTRA
```

Para distribuição amigável, o próximo empacotamento natural é uma Desktop Extension `.dxt/.mcpb` contendo esse comando/entrypoint.

Referência atual:
https://support.anthropic.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop

## Outros clientes MCP

Qualquer cliente MCP compatível pode usar uma destas duas formas:

STDIO:

```json
{
  "command": "python",
  "args": ["-B", "-m", "sentra_mcp", "--allowed-root", "C:\\path\\to\\SENTRA"],
  "cwd": "C:\\path\\to\\SENTRA"
}
```

Streamable HTTP:

```text
http://127.0.0.1:8000/mcp
```

## Testes

Testes MCP focados:

```powershell
python -B -m pytest tests/unit/test_mcp_core.py tests/unit/test_mcp_filesystem.py tests/unit/test_mcp_process.py tests/unit/test_mcp_sentra.py -q
python -B -m pytest tests/integration/test_mcp_protocol.py tests/integration/test_mcp_hardening_http.py -q
```

Regressão:

```powershell
python -B -m pytest tests/unit -q
python -B -m pytest tests/integration -q
python -B -m pytest tests/failure -q
python -B -m pytest tests -q
```

## Auditoria versus Remote Desktop Commander

Consulte `docs/MCP_AUDIT.md`.
