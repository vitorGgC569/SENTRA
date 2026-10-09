# Como usar o SENTRA

O SENTRA é um único runtime local com várias formas de uso. Você não precisa
configurar um tunnel, uma API key ou uma instalação diferente para cada
interface.

A regra mental é:

```text
                         OpenAI Secure MCP Tunnel
ChatGPT / app MCP  ───────────────────────┐
                                         │
Terminal ───────┐                         ▼
                ├──► SENTRA local ───► MCP 127.0.0.1:8000
Maestri ────────┘          │
                           ├──► Model Gateway 127.0.0.1:17842 ─► Codex/Web Models
                           │
                           └──► Edge relay ─► extensão SENTRA ─► aba Web existente
```

## Primeira instalação: três passos

### 1. Install

Execute `SENTRA-Setup-<version>.exe` e escolha **Continue**. Se Tunnel ID + Runtime API key já estiverem preenchidos, o Setup instala e conecta em uma única rodada; se estiverem vazios, instala primeiro e para na etapa **Connect OpenAI**.

A instalação padrão usa opções seguras e não exige Git ou Docker. Essas
dependências são opcionais e podem ser instaladas sob demanda.

As opções de workspace, profile, filesystem scope, Git e Docker ficam em
**Advanced options**.

### 2. Connect OpenAI

O SENTRA precisa de duas informações para o Secure MCP Tunnel:

1. **Tunnel ID** no formato `tunnel_...`;
2. uma **Runtime API key Restricted** com **Tunnels: Read + Use**.

No Setup ou em **SENTRA Desktop → Quick Start**:

1. escolha **Open OpenAI Tunnels**;
2. crie ou selecione o tunnel e copie o Tunnel ID;
3. escolha **Open Runtime API Keys**;
4. crie a chave Restricted;
5. cole os dois valores;
6. escolha **Connect OpenAI & Start**.

A Runtime API key é protegida pelo Windows DPAPI. O SENTRA não precisa gravar
a chave em README, Git, arquivo de configuração em texto aberto ou argumento de
processo.

### 3. Ready

O Ready principal exige apenas o caminho necessário para ChatGPT/MCP:

```text
MCP       ✓
Tunnel    ✓
```

Edge, Web Models, Git, Docker e Remote Agent são capacidades adicionais e não
bloqueiam o primeiro uso.

---

## 1. SENTRA no terminal

Use esta superfície quando você quer trabalhar diretamente em um projeto local.

Em um checkout do repositório:

```powershell
.\sentra-cli.cmd
```

Em uma instalação empacotada, o Setup registra a pasta do SENTRA no
**PATH do usuário**. Abra um terminal novo e use:

```powershell
sentra-cli
```

Para subir, consultar ou reiniciar a suíte local sem abrir o Desktop:

```powershell
sentra service start
sentra service status
sentra service restart
```

A diferença é intencional: **`sentra-cli` é a interface conversacional de
trabalho**, enquanto **`sentra` é a CLI operacional/durável** para serviço,
Runs e swarms. Para diagnóstico direto, o executável conversacional continua em
`%LOCALAPPDATA%\SENTRA\Commander\sentra-cli.exe`.

Comandos úteis dentro de `sentra-cli`:

```text
/status            estado do runtime
/doctor            diagnóstico
/models            modelos disponíveis
/jobs              jobs em background
/job <id>          resultado de um job
/collab <objetivo> colaboração via Maestri
```

TEST, BUILD, LINT, TYPECHECK e BENCH podem ser disparados em background. O
terminal devolve um `ACK job=...` rapidamente e continua utilizável.

---

## 2. SENTRA dentro do ChatGPT

Esta superfície usa o **Secure MCP Tunnel**. A extensão Edge não é necessária
para o ChatGPT chamar tools locais do SENTRA.

Fluxo:

```text
ChatGPT
  ↓ app/plugin MCP
OpenAI Secure MCP Tunnel
  ↓
SENTRA MCP local
  ↓
filesystem / processos / Git / jobs / browser / Maestri / outras tools
```

Depois que o Desktop mostrar **Ready**:

1. abra a área de Apps/Plugins/Developer mode do ChatGPT disponível para o seu
   workspace;
2. adicione/conecte o app MCP usando **Tunnel**;
3. escolha o tunnel configurado no SENTRA;
4. abra uma conversa nova;
5. faça o primeiro smoke com `sentra_health`.

Para tools stateful, o cliente abre uma sessão com `sentra_session_open`.

O Tunnel ID e a Runtime API key pertencem ao SENTRA. O Codex Web GPT não deve
criar uma segunda autoridade de tunnel.

---

## 3. SENTRA no Codex com Web Models

Esta superfície permite ao Codex usar modelos Web gerenciados pelo SENTRA.

Abra:

**SENTRA Desktop → Show advanced → Web Models**

Fluxo normal:

1. **Abrir interface Web**;
2. concluir o login Web quando necessário;
3. **Conectar Codex**;
4. reiniciar o Codex;
5. **Verificar conexões**.

A rota correta é:

```text
Codex
  ↓
SENTRA Model Gateway
http://127.0.0.1:17842/v1
  ↓
Codex Web GPT / ChatGPT Web / Gemini Web
```

O Codex não deve apontar diretamente para o sidecar upstream em
`127.0.0.1:17841`.

O executável **Codex Web GPT** é um componente gerenciado pelo SENTRA. O usuário
não deve precisar configurar um segundo Tunnel ID ou uma segunda Runtime API key
nele.

---

## 4. SENTRA como plugin/extensão no navegador

A extensão Edge é uma superfície diferente do Secure MCP Tunnel.

Use-a quando o SENTRA precisa operar uma aba Web real, por exemplo ChatGPT ou
Gemini Web.

No **SENTRA Desktop → Quick Start**:

1. escolha **Open Edge extensions**;
2. habilite **Developer mode**;
3. escolha **Load unpacked**;
4. selecione a pasta `edge_extension` mostrada pelo SENTRA.

A extensão se conecta ao relay local usando a identidade da instalação. Não
cole bearer token manualmente.

O comportamento esperado é adotar uma aba elegível já aberta no Edge principal,
usá-la temporariamente e falhar de forma fechada quando não houver uma aba segura
disponível. O fluxo normal não deve criar várias janelas ou abas extras.

---

## 5. SENTRA no Maestri

O Maestri é a superfície para colaboração entre vários terminais/agentes.

Um terminal SENTRA pode ser o maestro e abrir outros SENTRAs:

```text
SENTRA master
   ├── SENTRA worker A
   ├── SENTRA worker B
   └── SENTRA worker C
```

O SENTRA MCP também expõe controle direto do canvas Maestri por
`sentra_maestri`:

- `status` / `list`;
- `recruit`;
- `send`;
- `check`;
- `connect`;
- `dismiss`.

Workers usam timeout curto e cancelamento direcionado do turn para não ocupar
slots do browser indefinidamente. Trabalho longo de ferramentas deve virar job
assíncrono.

---

## O que o usuário precisa lembrar

| Quero… | Uso |
|---|---|
| Trabalhar num projeto pelo terminal | SENTRA CLI |
| Fazer o ChatGPT executar tools no meu PC | Secure MCP Tunnel + app/plugin MCP |
| Usar ChatGPT/Gemini Web dentro do Codex | Web Models / Model Gateway |
| Controlar uma aba real do navegador | extensão Edge |
| Coordenar vários agentes/terminais | Maestri |

Tudo parte da mesma instalação SENTRA.

## Diagnóstico rápido

Se algo não funcionar, cheque nesta ordem:

```text
1. SENTRA Desktop → Quick Start
2. Doctor
3. MCP
4. Tunnel
5. capacidade específica: Web Models / Edge / Maestri
```

No terminal:

```text
/status
/doctor
/jobs
```

Se o problema for a Runtime API key, crie uma nova chave Restricted com
**Tunnels: Read + Use** e use **Connect OpenAI & Start** novamente.

Para detalhes do tunnel, veja [SECURE_MCP_TUNNEL.md](SECURE_MCP_TUNNEL.md).
Para detalhes da CLI, veja [SENTRA_CLI.md](SENTRA_CLI.md).
Para Web Models, veja [WEB_MODELS.md](WEB_MODELS.md).
