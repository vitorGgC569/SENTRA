# SENTRA — primeira instalação, Canvas React/WebView2, CLI e app MCP

**Estado:** implementação/QA em 09/10/2026, sobre `main` no checkpoint `e4b3968` com alterações locais ainda sem release. **Não é um instalador estável homologado**. A orientação abaixo descreve os componentes que devem estar presentes quando a release passar em todos os gates.

## Objetivo do onboarding

Instalar uma vez, configurar uma vez e chegar à interface principal em poucos passos, sem editar arquivos de configuração, rodar comandos Python, abrir portas inbound ou copiar bearer tokens.

O Setup carrega os executáveis locais, o runtime do MCP, o cliente de túnel verificado por SHA-256, o SENTRA CLI, o Canvas WebView2, o runtime Web Models/Electron, a extensão Edge empacotada e a documentação. A instalação por usuário registra atalhos, `sentra://`, PATH e desinstalação/atualização. O **atalho principal SENTRA** deve abrir o **Canvas React Flow/Radix/Lucide/xterm**; o painel SENTRA Desktop permanece disponível para Quick Start, Doctor e políticas.

O Canvas é independente da conexão ChatGPT: o usuário pode abrir Canvas/CLI sem conectar um túnel. Usar **modelos de IA reais** requer autenticação num provider compatível (Codex autenticado ou catálogo Web/Gateway autenticado); capacidades externas requerem seus próprios serviços e autorizações.

## Primeiro uso sugerido

1. Executar o Setup Windows **assinado** da release e instalar os componentes por usuário. Não chamar de release um `sentra-canvas.exe` compilado isoladamente.
2. Abrir **SENTRA** (atalho na área de trabalho → Canvas); abrir **SENTRA Desktop** (menu Iniciar) para Quick Start, adicionar um workspace e rodar Doctor.
3. Clicar **Open SENTRA Terminal** no Quick Start ou abrir terminal e executar `sentra-cli`. Digitar `/model`: é mostrada lista **numerada e selecionável** dos modelos anunciados pelo Gateway mais Codex autenticado, com marcação do selecionado. Digitar o número; 0/cancelar mantém o atual. `/model list` e `/models` são consultas sem mudar modelo; `/model <id>` escolhe o ID explicitamente; `/effort low|medium|high|xhigh` controla apenas Codex.
4. Para conectar o **SENTRA ao ChatGPT como app/plugin MCP**, escolher no Quick Start a conexão guiada ChatGPT. Configurar/verificar o Secure MCP Tunnel e a chave de Runtime por uma ação explicitamente aprovada; o Windows protege segredos com DPAPI. O botão `Connect OpenAI & Start` verifica o MCP e o túnel, e quando o estágio está pronto abre automaticamente a etapa **Finish in ChatGPT**. Copia-se somente o Tunnel ID, nunca a chave.
5. No ChatGPT, o titular da conta **revisa, cria/conecta e autoriza** o app/plugin SENTRA nas configurações de plugins/apps disponíveis para sua conta. Essa autorização **não** pode ser concedida por um instalador Windows nem inferida de um túnel local saudável. Conferir uma chamada MCP autorizada de ponta a ponta para marcar a conexão como operacional. O Setup/Doctor deve distinguir `local ready`, `tunnel online` e `ChatGPT plugin authorized`.
6. Para tarefas de navegador que exijam a **extensão Edge**, usar o guia de extensão. Os arquivos são incluídos no Setup; até publicação assinada na Edge Add-ons, o usuário precisa aprovar Developer Mode → Load unpacked. Isso é independente do app/plugin MCP do ChatGPT.
7. VPN Hamachi/Radmin, Docker, Daytona, Guacamole, RustDesk e serviços de identidade/auditoria permanecem opcionais: instalar somente com consentimento, configuração e disponibilidade da infraestrutura. Não prometer dois PCs conectados na instalação básica.

## Integridade do pacote e arquivos obrigatórios

`scripts/commander/build_canvas.py::validate_desktop_bundle` exige `sentra_canvas/static/desktop.html`, `desktop-assets/manifest.json`, `desktop.js`, `desktop.css` e `bootstrap.js`. O build falha se os SHA-256 não corresponderem ao manifesto, houver nomes de asset não permitidos ou a página não carregar o bootstrap correto. O build Windows inclui `sentra-canvas.exe` e `sentra-cli.exe` no payload junto com `sentra-mcp.exe`, `sentra-desktop.exe` e demais ferramentas.

`sentra_remote/windows_integration.py` cria o atalho `SENTRA.lnk` para `sentra-canvas.exe` e mantém `SENTRA Canvas.lnk` e `SENTRA Desktop.lnk` no menu. `sentra_remote/desktop.py` fornece `Open SENTRA Canvas` e a configuração de primeiro uso; `sentra_remote/installer.py` devolve estados independentes `canvas` e `chatgpt_plugin`. `chatgpt_plugin.ready_to_install` **não** significa `installed` ou `authorized`.

Não copiar credenciais do usuário para artefatos, GitHub, logs ou README. Não modificar o broker instalado enquanto houver terminais ConPTY ativos.

## Evidências e pendências reais em 09/10/2026

| Gate | Evidência | Aceite |
| --- | --- | --- |
| Modelo selecionável | 16 testes focados de `/model`/Codex/effort | PASS no código fonte |
| Canvas + instalação guiada + on-boarding | 33 testes focados; bundle SHA-256 verificado | PASS no código fonte |
| Tests unitários Python (nova rodada de 09/10/2026) | **1.962 PASS; 0 FAIL; 37 SKIP; 0 ERROR** | **PASS** |
| Python failure + integration | 183 PASS; 10 SKIP | PASS nesse recorte |
| Colaboração JS | 54 PASS | PASS local |
| Canvas binário antigo de QA | ~110,9 MB em `.tmp/qa-checkpoint-20261009/canvas-dist-fixed` gerado **ANTES** do seletor/atalhos e validação obrigatória atual | STALE; precisa rebuild |
| MSI/Setup full, assinatura, Edge/WebView2, primeira instalação limpa, reinstalação e desinstalação | Não executados/homologados sobre esta árvore | **PENDENTES** |
| ChatGPT app/plugin conectado na conta de terceiro | Requer a autorização explícita da conta; não é possível side-load automático | **PENDENTE por usuário** |
| 37 projetos externos | Matriz individual no checkpoint; vários módulos parciais, infra externa incompleta | **NÃO 37/37 aceitos** |

A CI da branch tem um gate de whitespace do commit `e4b3968` ainda vermelho, e a suíte Python unitária não está verde. O release oficial exige `git` limpo, assets rastreados, testes integrais, assinatura Authenticode e artefatos verificáveis. **Não publicar Setup/MSI como estável antes dessas etapas.**

Referências: [README](../README.md), [Start Here](START_HERE.md), [SENTRA CLI](SENTRA_CLI.md), [Zero Config](ZERO_CONFIG_SETUP.md), [CI/CD](CI_CD.md), [Release](RELEASE.md), [checkpoint](SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md), [QA](SENTRA_COLABORACAO_RECONCILIACAO_QA_2026-10-09.md).

## QA do primeiro uso: resultado complementar (09/10/2026)

- `/model` testado em **CLI congelado real** `.tmp/qa-first-install-20261009/dist/sentra-cli.exe`: executável de 106.589.615 bytes; com entrada interativa `/model -> 1 -> /effort high -> /exit`, exit **0**, menu numerado visível, seleção aceita, esforço atualizado, terminal fechado sem stderr. O mesmo fluxo já havia passado no CLI Python.
- `sentra-canvas.exe` congelado de 110.887.441 bytes em `.tmp/qa-first-install-20261009/dist/`: processo de QA isolado respondeu `HTTP 200` para `/desktop.html`, `/desktop-assets/desktop.js`, `desktop.css`, `manifest.json`, `/api/workspaces`; Chromium renderizou `.react-flow`, título `SENTRA Desktop`, 28 botões, nenhum erro JS/HTTP e token removido do fragmento. O workspace limpo não tinha nós/terminais, como esperado. Screenshot local `.tmp/qa-first-install-20261009/frozen-react-canvas.png`. Shutdown gracioso HTTP 200 solicitado somente ao broker de QA.
- O Build Canvas agora valida `desktop.html` + manifesto SHA-256 antes do empacotamento; os testes de alterações/tamper e bundle incompleto passaram.
- Suite focada CLI+Canvas+instalador+release+onboarding: **76 passed, 1 deprecation warning** (msilib, Python 3.13), exit 0.
- A pipeline de release verifica que o guia de primeiro uso acompanha o Setup e o MSI. O processo de instalação retorna estados `canvas` e `chatgpt_plugin` distintos: o último marca `requires_account_authorization=True`, sem fingir `installed`.
- Estes **dois EXEs de QA não formam um Setup completo**: faltam os demais executáveis de payload, runtime Electron, arquivo pinado do túnel, build completo pós-ajustes de instalador, MSI/Setup e testes E2E de instalação/desinstalação. `build_installer` recusa prova de build de fontes anteriores; será necessário rebuild dos 13 executáveis após um novo checkpoint.
- A suíte unitária Python global foi **corrigida e está verde** (1.962 passed, 37 skipped, 0 failed/error); o gate histórico de whitespace de `e4b3968` continua vermelho. Não subir tag/release nem afirmar instalação automática na conta ChatGPT até o aceite integral, assinatura e novo checkpoint rastreado.

## Referência oficial de conexão ChatGPT

O fluxo público atual da OpenAI é **ChatGPT → Plugins → Adicionar (+) →
Add custom MCP server → Connection: Tunnel → selecionar/fornecer Tunnel ID →
revisar autorização → criar/instalar o plugin**. A interface pode variar por
conta, política de workspace e autorização do administrador. O instalador
local **não pode** conceder permissão de plugin à conta nem presumir que a
organização liberou `Tunnels Read + Use`.

- [OpenAI: adicionar servidor MCP customizado](https://developers.openai.com/api/docs/guides/custom-mcp-server)
- [OpenAI: Secure MCP Tunnel e associação ao workspace ChatGPT](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [OpenAI: Plugins no ChatGPT](https://help.openai.com/pt-br/articles/20001256-plugins-no-chatgpt-e-no-codex)
