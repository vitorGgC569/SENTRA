# SENTRA — Start Here

Este é o caminho mais curto para instalar, conectar e entender **onde o SENTRA aparece**.

A regra principal é simples:

> **Instale uma vez, conecte a OpenAI uma vez e escolha a superfície que faz sentido para a tarefa.**

Você não precisa configurar Git, Docker, Edge, Web Models e Maestri para começar.

---

## 1. Instalação em três etapas

### Etapa 1 — Install

Execute o `SENTRA-Setup-<versão>.exe`.

O botão **Tutorial em vídeo** do instalador abre um guia local com dois vídeos
(túnel e conector) e as instruções da chave, mesmo antes de instalar os componentes.

O Setup instala os componentes por usuário e registra:

- SENTRA Desktop;
- MCP local;
- Secure Tunnel client;
- SENTRA CLI;
- Web Models / Codex Web GPT;
- protocolo `sentra://`;
- inicialização do Desktop;
- pasta de instalação no **PATH do usuário**.

Depois de abrir um **novo terminal**, estes comandos ficam disponíveis de qualquer pasta:

```powershell
sentra-cli
sentra service status
```

`sentra-cli` é o agente interativo.  
`sentra` é a CLI operacional para serviços, durable runs e swarms.

Git e Docker são opcionais e só precisam ser instalados quando uma tarefa realmente exigir essas capacidades.

### Etapa 2 — Connect OpenAI

Abra **SENTRA Desktop → Quick Start**.

Você precisa informar apenas:

1. **Tunnel ID** — formato `tunnel_...`;
2. **Runtime API key** com permissões **All** e sem expiração.

Para automatizar essa etapa, expanda a conexão ChatGPT no Setup e marque a
autorização de configuração completa no Edge. Entre na sua conta quando solicitado.
A instalação local não autentica contas externas: numa máquina limpa, os agentes
com IA precisam de Codex CLI instalado e conectado ou de login num provedor Web.

Use os botões:

- **Open OpenAI Tunnels**
- **Open Runtime API Keys**

Depois clique:

**Connect OpenAI & Start**

A Runtime API key é protegida com **Windows DPAPI**. O SENTRA não precisa manter a chave em plaintext no repositório ou na pasta de instalação.

### Etapa 3 — Ready

O estado básico de pronto é:

```text
MCP      ✓ Ready
Tunnel   ✓ Ready
```

Quando esses dois itens estão saudáveis, o ChatGPT já pode alcançar o MCP local através do Secure MCP Tunnel.

Edge, Docker, Git, Remote Agent e Web Models são capacidades adicionais; eles não bloqueiam o primeiro uso.

---

## 2. As superfícies do SENTRA

### A. SENTRA Desktop

Use para:

- instalar/configurar;
- conectar OpenAI;
- executar Doctor;
- acompanhar MCP/Tunnel/Edge/Web Models;
- autorizar workspaces;
- configurar políticas;
- abrir recursos avançados.

Fluxo normal:

```text
SENTRA Desktop
  → Quick Start
  → Connect OpenAI
  → Ready
```

Configurações avançadas ficam escondidas atrás de **Show advanced**.

---

### B. SENTRA no terminal

Para conversar diretamente com um agente:

```powershell
sentra-cli
```

Primeiros comandos úteis:

```text
/status
/doctor
/models
/help
/jobs
```

Operações demoradas, como testes e builds, retornam um ACK rapidamente:

```text
ACK job=job-... state=QUEUED operation=TEST
```

A CLI é liberada enquanto o trabalho continua em outro processo.

Consulte depois:

```text
/jobs
/job job-...
```

Para operações do runtime/durable core:

```powershell
sentra service status
sentra service start
sentra service restart
sentra run list
sentra swarm list
```

---

### C. SENTRA dentro do ChatGPT — app/plugin MCP

Este caminho serve para **o próprio ChatGPT chamar tools do seu computador**.

Topologia:

```text
ChatGPT
   │
   │ Secure MCP Tunnel
   ▼
SENTRA MCP 127.0.0.1:8000
   │
   ├─ arquivos/workspaces
   ├─ processos/jobs
   ├─ Git
   ├─ browser
   ├─ Maestri
   └─ demais tools SENTRA
```

O MCP continua local/loopback. O tunnel-client cria a conexão HTTPS de saída.

Depois que Quick Start estiver Ready:

1. abra o ChatGPT;
2. abra Plugins/Apps/Developer mode, conforme a interface disponível;
3. conecte o tunnel do SENTRA;
4. abra uma conversa nova para carregar o catálogo MCP;
5. faça um smoke com `sentra_health`.

Se uma conversa antiga mostrar menos tools do que `sentra_health`, reconecte o app ou abra uma conversa nova. O catálogo de tools pode ficar em cache por conversa.

---

### D. Codex + Web Models / Codex Web GPT

Este caminho resolve outro problema:

> usar **ChatGPT Web e Gemini Web como modelos dentro do Codex/SENTRA**.

Topologia:

```text
Codex
  │
  ▼
SENTRA Gateway 127.0.0.1:17842/v1
  │
  ├─ ChatGPT Web
  └─ Gemini Web
```

Abra no Desktop:

**Show advanced → Web Models**

Fluxo:

1. **Abrir interface Web**;
2. conclua o login Web quando necessário;
3. **Conectar Codex**;
4. reinicie o Codex;
5. **Verificar conexões**.

### Importante: um único tunnel

Em builds gerenciados pelo SENTRA, o **SENTRA é a autoridade do tunnel**.

O Codex Web GPT mostra **Managed by SENTRA** e:

- não cria um segundo tunnel;
- não guarda outra Runtime API key;
- reutiliza o estado e o tunnel do SENTRA;
- pode abrir **SENTRA Quick Start** caso a conexão ainda não esteja pronta.

Não configure “Codex tunnel” e “SENTRA tunnel” separadamente.

---

### E. Plugin/extensão Edge no navegador

A extensão Edge **não é o Secure MCP Tunnel**.

Ela é o atuador de navegador usado quando uma tarefa precisa operar uma aba Web real.

```text
SENTRA
  │
  ▼
relay local
  │
  ▼
extensão Edge
  │
  ▼
aba ChatGPT/Gemini já aberta
```

Use quando quiser:

- automação de ChatGPT Web;
- automação de Gemini Web;
- Web Models;
- fluxos que dependem da sessão autenticada do navegador.

No produto instalado, abra:

**Quick Start → Open Edge extensions**

A extensão é pareada pelo fluxo local do SENTRA. Não copie secrets/bearer tokens manualmente para ela quando estiver usando o fluxo atual do produto.

O SENTRA prefere adotar uma aba elegível existente no Edge principal e falha fechado quando não há uma aba segura disponível.

---

### F. Maestri + múltiplos SENTRAs

O Maestri permite que um SENTRA mestre coordene outros terminais SENTRA.

Exemplo:

```text
SENTRA (mestre)
  ├─ SENTRA-Implementation
  ├─ SENTRA-Review
  └─ SENTRA-Docs
```

A integração direta do MCP pode:

- listar terminais;
- recrutar/abrir SENTRAs;
- enviar prompt + Enter;
- consultar a saída;
- conectar agentes;
- fechar terminais.

O terminal manager é protegido contra fechamento acidental.

Para iniciar colaboração pelo SENTRA CLI:

```text
/collab <objetivo>
```

---

## 3. Qual superfície devo usar?

| Quero... | Use |
|---|---|
| conversar com SENTRA rapidamente | `sentra-cli` |
| iniciar/parar runtime ou ver durable runs | `sentra` |
| deixar ChatGPT acessar meu MCP local | Secure MCP Tunnel + app/plugin MCP |
| usar ChatGPT/Gemini Web dentro do Codex | Web Models / Codex Web GPT |
| controlar uma aba autenticada no navegador | extensão Edge |
| coordenar vários agentes/terminais | Maestri |
| configurar/ver saúde de tudo | SENTRA Desktop |

As superfícies podem coexistir. Elas não são substitutas umas das outras.

---

## 4. Smoke test de 60 segundos

### Terminal

```powershell
sentra-cli
```

Depois:

```text
/status
```

### Runtime

```powershell
sentra service status
```

### ChatGPT/MCP

No ChatGPT, após conectar o app:

```text
Use sentra_health.
```

Confirme que o contrato retorna `tool_count`, `schema_hash` e build identity.

### Codex/Web Models

No Desktop:

```text
Web Models → Verificar conexões
```

Confirme:

- Gateway ready;
- rota Codex aponta para SENTRA;
- catálogo de modelos carregado.

### Edge

No Desktop/Doctor, confirme que relay/extensão estão conectados quando essa capacidade estiver habilitada.

---

## 5. Se algo não funcionar

| Sintoma | Ação |
|---|---|
| Tunnel não conecta | Quick Start → revise Tunnel ID/Runtime API key → Connect OpenAI & Start |
| Runtime key invalidada | crie nova Restricted key e reconecte |
| ChatGPT mostra catálogo antigo | reconecte o app ou abra nova conversa |
| Codex não mostra modelos Web | Web Models → Conectar Codex → reinicie Codex |
| Gateway offline | Desktop → Start / Doctor |
| Edge não aparece | confira extensão habilitada e relay local |
| build/test demora | use `/jobs` e `/job <id>`; não espere o job no mesmo turno |
| worker Maestri não responde | `/maestri check <nome>`; workers têm deadline e não devem bloquear o mestre |

---

## 6. Segurança em uma frase

- Runtime API key: DPAPI;
- MCP: loopback;
- Tunnel: conexão HTTPS de saída;
- workspaces: autorização explícita;
- ações destrutivas: confirmação;
- Edge: adoção controlada/fail-closed;
- secrets: nunca no Git/log público.

Veja também:

- [Quick Start](QUICKSTART.md)
- [Secure MCP Tunnel](SECURE_MCP_TUNNEL.md)
- [SENTRA CLI](SENTRA_CLI.md)
- [Web Models](WEB_MODELS.md)
- [MCP Server](MCP_SERVER.md)
