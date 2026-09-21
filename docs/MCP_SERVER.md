# SENTRA MCP Server

O SENTRA agora expõe suas capacidades locais como um servidor Model Context Protocol (MCP) usando o SDK Python oficial v2.

## Estado e transportes

- Protocolo declarado: MCP `2026-07-28`.
- Transporte padrão: `stdio`.
- Transporte remoto/local opcional: `streamable-http`.
- HTTP usa `127.0.0.1:8000` por padrão.
- SSE não é exposto pela configuração SENTRA.
- O servidor usa lifecycle MCP para encerrar todos os processos filhos gerenciados no shutdown.

Instalação:

```powershell
cd C:\Users\vitor\OneDrive\Desktop\SENTRA
python -m pip install -r requirements.txt
python -B -m sentra_mcp
```

Streamable HTTP local:

```powershell
python -B -m sentra_mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Endpoint: `http://127.0.0.1:8000/mcp`.

## Segurança padrão

O MCP não concede acesso global ao computador por padrão. `allowed_roots` contém somente a raiz do SENTRA, salvo configuração explícita do operador.

Proteções principais:

- traversal, drive/UNC/device paths e escapes por link são bloqueados;
- `.git`, `.oma`, `runs`, `browser_profiles`, credenciais e arquivos de chave não são acessíveis pelas tools genéricas de filesystem;
- leitura/escrita/output/processos possuem limites configuráveis;
- terminal usa argv estruturado e `shell=False`;
- `cwd` de processos é confinado às `allowed_roots`;
- variáveis contendo TOKEN, SECRET, PASSWORD, API_KEY, COOKIE e variáveis Python de injeção são removidas dos filhos;
- sessões de processo exigem `owner` e outro owner não pode ler, escrever, terminar ou matar o processo;
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
--audit-log PATH
--allow-non-loopback
```

Não use `--allow-non-loopback` para publicar o servidor diretamente na internet. Adicione autenticação/TLS em uma camada apropriada ou use um túnel MCP seguro.

## Tools

### Core

- `sentra_health`

### Filesystem

- `sentra_list_directory`
- `sentra_read_file`
- `sentra_read_multiple_files`
- `sentra_file_info`
- `sentra_search`
- `sentra_create_directory`
- `sentra_move_file`
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

`sentra_start_process` aceita string ou argv, `owner`, timeout opcional e `cwd` opcional confinado.

### Repository

- `sentra_repo_read`
- `sentra_repo_search`
- `sentra_repo_tree`
- `sentra_repo_symbol`
- `sentra_repo_status`
- `sentra_repo_diff`
- `sentra_repo_test`

Essas tools reutilizam `repository.CommandGateway`. Não existe endpoint de shell arbitrário no adapter. `sentra_repo_test` executa somente a operação TEST registrada.

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
args = ["-B", "-m", "sentra_mcp", "--allowed-root", "C:\\Users\\vitor\\OneDrive\\Desktop\\SENTRA"]
cwd = "C:\\Users\\vitor\\OneDrive\\Desktop\\SENTRA"
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

Não exponha o modo HTTP authless do SENTRA diretamente na internet.

Referências:
- https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt
- https://developers.openai.com/api/docs/guides/tools-connectors-mcp

## Claude Desktop

Claude Desktop suporta servidores MCP locais e Desktop Extensions. Para desenvolvimento local, a configuração de servidor deve lançar:

```text
command: python
args: -B -m sentra_mcp --allowed-root C:\Users\vitor\OneDrive\Desktop\SENTRA
cwd: C:\Users\vitor\OneDrive\Desktop\SENTRA
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
  "args": ["-B", "-m", "sentra_mcp", "--allowed-root", "C:\\Users\\vitor\\OneDrive\\Desktop\\SENTRA"],
  "cwd": "C:\\Users\\vitor\\OneDrive\\Desktop\\SENTRA"
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
python -B -m pytest tests/integration/test_mcp_protocol.py -q
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
