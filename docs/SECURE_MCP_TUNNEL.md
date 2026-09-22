# Secure MCP Tunnel — configuração do zero

Este guia conecta o SENTRA MCP local ao ChatGPT ou a outro produto OpenAI compatível sem publicar o servidor MCP na internet.

> Segurança: nunca coloque API keys, `tunnel_id` privados, tokens, arquivos DPAPI, perfis locais ou logs sensíveis no Git. Use os placeholders deste guia literalmente até substituí-los apenas no ambiente local.

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

  & .\.sentra\tunnel-client\tunnel-client.exe run `
    --profile sentra-local `
    --profile-dir .sentra\tunnel\profiles `
    --health.listen-addr 127.0.0.1:0
} finally {
  Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue
  if ($bstr -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
  $secure.Dispose()
}
```

O `tunnel-client run` precisa permanecer saudável durante descoberta do app e chamadas MCP.

## 10. Health, readiness e UI local

O tunnel-client expõe localmente:

- `/healthz`: processo saudável;
- `/readyz`: pronto e conectado para encaminhar trabalho;
- `/metrics`: métricas operacionais;
- `/ui`: painel local de administração.

Use a URL de health impressa pelo cliente. Exemplo conceitual:

```powershell
Invoke-WebRequest http://127.0.0.1:PORT/healthz -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:PORT/readyz -UseBasicParsing
Start-Process http://127.0.0.1:PORT/ui
```

Não exponha a UI local externamente sem uma necessidade operacional deliberada.

## 11. Conecte o túnel ao ChatGPT

1. Confirme que o túnel está associado ao workspace ChatGPT correto na Platform.
2. No ChatGPT, habilite o **Developer mode** quando disponível para seu plano/workspace.
3. Abra **Plugins**.
4. Use o botão para adicionar/criar um app no modo de desenvolvedor.
5. Em **Connection**, escolha **Tunnel**.
6. Selecione o túnel listado ou informe o `tunnel_id` quando a interface permitir.
7. Conclua a criação/conexão do app.

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

## 13. Rotação e revogação

Se uma Runtime API key for exposta:

1. revogue-a imediatamente na OpenAI Platform;
2. crie uma nova chave com as permissões mínimas;
3. substitua somente o arquivo DPAPI local;
4. reinicie o tunnel-client;
5. confirme `doctor`, `/healthz` e `/readyz`;
6. pesquise o histórico Git e logs para garantir que o segredo não permaneceu em artefatos.

Não tente “corrigir” uma chave vazada apenas removendo-a de um commit novo. Se ela chegou ao histórico remoto, considere-a comprometida.

## Referências oficiais

- OpenAI Secure MCP Tunnel: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- OpenAI MCP servers: https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- OpenAI Help — API keys: https://help.openai.com/en/articles/4936850
- OpenAI Help — API projects: https://help.openai.com/en/articles/9186755
- OpenAI Help — Developer mode and MCP apps in ChatGPT: https://help.openai.com/en/articles/12584461
