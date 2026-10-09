# Secure MCP Tunnel — configuração do zero

Este guia conecta o SENTRA MCP local ao ChatGPT ou a outro produto OpenAI compatível sem publicar o servidor MCP na internet.

> Segurança: nunca coloque API keys, `tunnel_id` privados, tokens, arquivos DPAPI, perfis locais ou logs sensíveis no Git. Use os placeholders deste guia literalmente até substituí-los apenas no ambiente local.

## Antes de começar: o que este guia resolve

Use este guia quando quiser que **o próprio ChatGPT chame as tools locais do SENTRA**. O fluxo é:

```text
ChatGPT → Secure MCP Tunnel → SENTRA MCP local
```

Isso é diferente de **Web Models**, que conecta o Codex ao Gateway local para usar ChatGPT/Gemini Web como modelos, e também é diferente da **extensão Edge**, que só permite ao SENTRA operar uma aba já aberta no navegador.

Se o seu objetivo é apenas usar `sentra-cli` no terminal, você não precisa configurar Tunnel, Web Models ou Edge.

## Caminho recomendado no produto instalado

Para uso normal no Windows, você não precisa executar manualmente os blocos PowerShell deste documento. No **SENTRA Desktop → Quick Start**:

1. **Open Platform Tunnels** → crie/selecione o `tunnel_...`.
2. **Open Runtime API Keys** → crie uma chave Restricted com **Tunnels: Read + Use**.
3. Cole Tunnel ID + Runtime API key e clique **Connect OpenAI & Start**. O Desktop protege a chave com DPAPI e inicia os serviços.
4. No ChatGPT, conecte o túnel como **app/plugin MCP** em Developer mode.
5. Faça o smoke test com `sentra_health` e, para tools stateful, `sentra_session_open`.

O Desktop mantém o MCP em loopback, protege a Runtime API key com DPAPI e supervisiona uma única instância do tunnel-client. As seções abaixo continuam sendo o runbook detalhado para desenvolvimento, diagnóstico e recuperação manual.

**Não confunda os dois bridges:** Secure MCP Tunnel = **ChatGPT ↔ MCP local**. Extensão Edge = **SENTRA ↔ aba Web existente** para workflows de navegador e Web Models. Instalações atuais pareiam a extensão com o relay local por prova install-local; não é necessário copiar um bearer token para a extensão.

### Topologia do primeiro uso

```text
ChatGPT app/plugin
      │
      │ HTTPS de saída / Secure MCP Tunnel
      ▼
SENTRA MCP 127.0.0.1:8000
      │
      ├── filesystem / processos / jobs / repos / OMA
      └── browser tools ──► relay local ──► extensão Edge ──► aba já aberta

Codex ──► SENTRA Gateway 127.0.0.1:17842/v1 ──► Web Models (ChatGPT/Gemini Web)
```

Portanto, para apenas chamar tools locais a partir do ChatGPT, **Tunnel + MCP bastam**. A extensão Edge é opcional e entra somente quando uma tool precisa atuar no navegador. O caminho Codex/Web Models é outra superfície: ele aponta o Codex para o Gateway local e não deve apontar diretamente para o sidecar upstream.

## 1. Pré-requisitos

- Windows 10/11 e Python 3.11+.
- SENTRA instalado com `python -m pip install -r requirements.txt`.
- Uma conta/organização da OpenAI Platform com acesso a Tunnels.
- Permissão **Read + Manage** em Tunnels para criar/editar o túnel.
- Permissão **Read + Use** em Tunnels para executar o `tunnel-client` ou selecionar o túnel ao criar um app.
- ChatGPT Developer mode habilitado quando o uso for pelo ChatGPT.
- Saída HTTPS permitida para `api.openai.com:443` (ou `mtls.api.openai.com:443` quando mTLS estiver configurado).

A disponibilidade e as permissões de MCP no ChatGPT dependem do plano/workspace. Consulte a documentação atual da OpenAI antes de distribuir o acesso.

## 2. Configure as permissões de Tunnels na organização

As permissões do Secure MCP Tunnel são de **organização**, não de projeto. Na OpenAI Platform:

1. Abra **Settings → Organization → People → Roles**.
2. Para quem executará o tunnel-client, use/crie uma função com **Tunnels: Read + Use**.
3. Para quem criará ou editará túneis, use/crie uma função com **Tunnels: Read + Manage**.
4. Se a mesma pessoa também executar o daemon ou conectar o app do ChatGPT, inclua também **Use**.
5. Prefira atribuir a função por grupo quando houver vários operadores.

Não conceda **Manage** ou permissões de Admin API key ao daemon de runtime sem necessidade.

## 3. Crie a Runtime API key

Na OpenAI Platform:

1. Abra **Settings → Organization → API Keys** (Runtime API keys).
2. Clique em **Create new secret key**.
3. Dê um nome identificável, por exemplo `sentra-tunnel-runtime`.
4. Escolha **Restricted**.
5. Habilite somente **Tunnels: Read + Use**.
6. Crie a chave e copie o segredo imediatamente.

A chave secreta completa só é exibida no momento da criação. Se ela for perdida, gere outra e revogue a anterior.

Use `CONTROL_PLANE_API_KEY` para `tunnel-client doctor` e `tunnel-client run`. Não use `OPENAI_ADMIN_KEY` nem uma chave administrativa para o daemon de longa duração. Não cole a chave em README, YAML rastreado, argumentos persistidos, issues, commits ou screenshots.

## 4. Crie o túnel na Platform

1. Abra **Settings → Organization → Tunnels** na OpenAI Platform.
2. Crie um novo endpoint de túnel MCP.
3. Associe a organização da Platform que administrará o túnel.
4. Se o ChatGPT for usar o túnel, associe também o workspace ChatGPT correto.
5. Copie o identificador retornado no formato `tunnel_...`.

Guarde o identificador localmente. Ele não é substituto da API key e não concede acesso sozinho.

## 5. Baixe o tunnel-client oficial

Use o link de download exibido em **Platform → Tunnels** ou a versão pública mais recente do repositório oficial `openai/tunnel-client`.

Coloque o executável em um diretório local ignorado pelo Git:

```powershell
New-Item -ItemType Directory -Force .sentra\tunnel-client | Out-Null
# copie o binário oficial para:
# .sentra\tunnel-client\tunnel-client.exe
& .\.sentra\tunnel-client\tunnel-client.exe help quickstart
```

Não fixe uma URL de versão antiga em automações permanentes e não versione o binário baixado.

## 6. Armazene a Runtime API key localmente

A opção recomendada no Windows é proteger o segredo com DPAPI, vinculado ao usuário do Windows que executará o tunnel-client.

Crie uma pasta local ignorada pelo Git:

```powershell
New-Item -ItemType Directory -Force .sentra\tunnel | Out-Null
$secure = Read-Host "Cole a Runtime API key" -AsSecureString
$secure | ConvertFrom-SecureString |
  Set-Content .sentra\tunnel\runtime-key.dpapi -Encoding UTF8 -NoNewline
$secure.Dispose()
```

O repositório já ignora `.sentra/`. Confirme antes de continuar:

```powershell
git check-ignore .sentra/tunnel/runtime-key.dpapi
git ls-files .sentra
```

O primeiro comando deve indicar que o arquivo é ignorado; o segundo não deve listar arquivos locais de tunnel.

Nunca use algo como `$env:CONTROL_PLANE_API_KEY = "sk-..."` em scripts que serão commitados. O exemplo da documentação oficial é útil para sessões efêmeras, mas o SENTRA deve carregar o segredo apenas em memória no momento da execução.

## 7. Inicie o SENTRA MCP local

Em um terminal no diretório do SENTRA:

```powershell
python -B -m sentra_mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

O endpoint privado esperado é:

```text
http://127.0.0.1:8000/mcp
```
Não use `--allow-non-loopback` para publicar este endpoint na internet. O Secure MCP Tunnel existe justamente para manter o MCP privado e usar somente conexão HTTPS de saída.

## 8. Inicialize um perfil do tunnel-client

Carregue temporariamente a chave DPAPI para a variável esperada pelo tunnel-client:

```powershell
$encrypted = Get-Content .sentra\tunnel\runtime-key.dpapi -Raw
$secure = ConvertTo-SecureString $encrypted
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)

  & .\.sentra\tunnel-client\tunnel-client.exe init `
    --sample sample_mcp_remote_no_auth `
    --profile sentra-local `
    --profile-dir .sentra\tunnel\profiles `
    --tunnel-id YOUR_TUNNEL_ID `
    --mcp-server-url http://127.0.0.1:8000/mcp `
    --control-plane-api-key-ref env:CONTROL_PLANE_API_KEY `
    --health-listen-addr 127.0.0.1:0 `
    --force
} finally {
  Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue
  if ($bstr -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
  $secure.Dispose()
}
```

Substitua somente `YOUR_TUNNEL_ID` pelo identificador criado na Platform. Não escreva a API key no comando.

## 9. Doctor e execução

Carregue a Runtime API key do DPAPI somente pelo tempo de vida do processo. O wrapper abaixo remove a variável de ambiente ao sair:

```powershell
$encrypted = Get-Content .sentra\tunnel\runtime-key.dpapi -Raw
$secure = ConvertTo-SecureString $encrypted
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)

  & .\.sentra\tunnel-client\tunnel-client.exe doctor `
    --profile sentra-local `
    --profile-dir .sentra\tunnel\profiles `
    --explain

  # O tunnel persistente deve ser iniciado exclusivamente pelo supervisor
  # singleton do SENTRA. Ele também migra o layout DPAPI legado sem expor a chave.
  & .\scripts\commander\Start-SENTRA-Singleton.ps1
} finally {
  Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue
  if ($bstr -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
  $secure.Dispose()
}
```

O supervisor singleton do SENTRA mantém exatamente um `tunnel-client` saudável durante descoberta do app e chamadas MCP; não inicie uma segunda instância manualmente.

## 10. Health, readiness e UI local

O tunnel-client expõe localmente:

- `/healthz`: processo local saudável;
- `/readyz`: dependências locais/readiness do cliente satisfeitas; **não trate
  esse código sozinho como prova de polling aceito pelo Control Plane**;
- `/metrics`: métricas operacionais;
- `/ui`: painel local de administração.

O SENTRA também correlaciona os logs da sessão atual do tunnel. Se o Control Plane
responder `401 token_invalidated`, o status do produto é
`control_plane=REAUTH_REQUIRED` e `ok=false`, mesmo que o endpoint local ainda
pareça saudável. Esse estado é terminal para a credencial: o supervisor não entra
em restart-loop; rotacione a Runtime API key e reconfigure o mesmo `tunnel_id`.

Use a URL de health impressa pelo cliente. Exemplo conceitual:

```powershell
Invoke-WebRequest http://127.0.0.1:PORT/healthz -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:PORT/readyz -UseBasicParsing
Start-Process http://127.0.0.1:PORT/ui
```

Não exponha a UI local externamente sem uma necessidade operacional deliberada.

## 11. Conecte o SENTRA como app/plugin MCP no ChatGPT

1. Confirme que o túnel está associado ao workspace ChatGPT correto na Platform.
2. No ChatGPT, habilite o **Developer mode** quando disponível para seu plano/workspace.
3. Abra **Plugins/Apps** (o rótulo pode variar conforme a versão do cliente).
4. Use a opção para adicionar/criar um app MCP em modo de desenvolvedor.
5. Em **Connection**, escolha **Tunnel**.
6. Selecione o túnel listado ou informe o `tunnel_id` quando a interface permitir.
7. Conclua a conexão e abra uma conversa nova antes do primeiro smoke test.

Depois disso, o ChatGPT chama o **MCP local do SENTRA** através do Secure MCP Tunnel. A extensão Edge não é necessária para a conexão MCP em si; ela só é necessária quando uma tool/workflow pede controle do navegador ou Web Models.

Se o túnel não aparecer, verifique primeiro a associação do workspace e a permissão **Tunnels: Read + Use**. Mudanças de função/permissão podem levar algum tempo para propagar.

## 12. Primeiro smoke test

Antes de chamar ferramentas pelo ChatGPT, valide em ordem:

```text
1. SENTRA MCP escutando apenas em 127.0.0.1:8000
2. tunnel-client doctor sem erro
3. /healthz = HTTP 200
4. /readyz = HTTP 200
5. tunnel-client run permanece ativo
6. app do ChatGPT mostra o túnel conectado
```

No primeiro uso pelo cliente MCP, chame `sentra_health`. Para recursos stateful em HTTP MCP 2026-07-28, abra uma sessão com `sentra_session_open` e reutilize o `session_token` apenas dentro daquela conversa.
Um smoke passivo recomendado para o SENTRA é:

```text
sentra_health
sentra_session_open
sentra_repo_status
sentra_read_file README.md
sentra_process_sandbox_status
sentra_list_jobs
sentra_browser_tabs
```

Para o browser, `tabs: []` junto com `edge_bridge.state = "IDLE"` pode ser o estado correto quando nenhum job adotou a aba principal do Edge.

### Atualização do catálogo MCP

`sentra_health` e `sentra_run(action="contract_manifest")` anunciam o contrato
canônico do servidor, incluindo `schema_hash`, `tool_count`, `tool_names` e
`build_id`. Compare esses valores com o catálogo carregado pelo cliente após
atualizações do SENTRA.

Se o servidor anunciar mais tools que uma conversa ChatGPT já aberta, não
reduza o servidor nem crie aliases duplicados para mascarar a diferença. O
catálogo MCP é carregado pelo cliente e uma conversa existente pode manter o
schema anterior. Depois de atualizar/reiniciar o MCP e o tunnel-client:

1. confirme `/healthz` e o `contract_manifest` novo;
2. reconecte/atualize o app SENTRA no ChatGPT quando necessário;
3. abra uma nova conversa para carregar o novo `tools/list`;
4. confirme que `tool_count` e `schema_hash` correspondem ao contrato do servidor.

Uma conversa antiga pode continuar funcional com o subconjunto de tools que
ela já carregou; isso não deve ser interpretado como ausência da implementação
no servidor.

## 13. Rotação e revogação

Se uma Runtime API key for exposta:

1. revogue-a imediatamente na OpenAI Platform;
2. crie uma nova chave com as permissões mínimas;
3. substitua somente o arquivo DPAPI local;
4. reinicie o tunnel-client;
5. confirme `doctor`, `/healthz` e `/readyz`;
6. confirme também o estado do Control Plane. `healthz=200` e até `readyz=200` não substituem a prova de polling upstream; `token_invalidated` deve ser tratado como `REAUTH_REQUIRED`, não como falha transitória para restart infinito;
7. pesquise o histórico Git e logs para garantir que o segredo não permaneceu em artefatos.

Não tente “corrigir” uma chave vazada apenas removendo-a de um commit novo. Se ela chegou ao histórico remoto, considere-a comprometida.

## Referências oficiais

- OpenAI Secure MCP Tunnel: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- OpenAI MCP servers: https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- OpenAI Help — API keys: https://help.openai.com/en/articles/4936850
- OpenAI Help — API projects: https://help.openai.com/en/articles/9186755
- OpenAI Help — Developer mode and MCP apps in ChatGPT: https://help.openai.com/en/articles/12584461
