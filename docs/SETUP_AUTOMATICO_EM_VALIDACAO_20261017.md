# Setup automático — validação em andamento em 17/10/2026

O objetivo continua sendo uma instalação completa pelo Setup, com dependências
incorporadas e configuração pelo DOM usando a sessão existente do navegador.
**As verificações registradas ainda não comprovam uma instalação limpa homologada.**
Este checkpoint antecede o empacotamento final do novo Setup. Há componentes reais
compilados e verificados separadamente, descritos abaixo; o estado do candidato
deve ser conferido também nos relatórios e manifestos que acompanham seu build.

## Alterações verificáveis no código

- A saúde local permite começar o cadastro da conta em uma instalação nova.
  Antes, a ausência do cadastro impedia alcançar a própria etapa de cadastro.
- O Setup executa o cadastro pelo navegador dentro do seu processo de instalação,
  em vez de delegá-lo a uma janela do Desktop. O caminho silencioso
  `--silent --browser-setup` também espera o cadastro e verifica novamente os
  serviços antes de retornar sucesso. O driver Playwright integra o build do Setup.
- O cadastro testa a proteção de credenciais antes de criar recursos na conta e
  recupera configuração anterior antes de criar outro túnel/chave.
- O Setup também testa proteção e leitura de uma credencial descartável antes
  dos downloads, cópia de componentes ou alteração da instalação. Falha preserva
  arquivos e configuração existentes, sem iniciar navegador ou serviços. O
  relatório silencioso usa o motivo fixo `credential_protection_unavailable`,
  sem propagar diagnósticos privados. A atualização coordenada offline conserva
  sua verificação adiada para o usuário do reinício. O teste é repetido antes
  dos efeitos na conta; entradas descartáveis do keyring são removidas.
- Conexões CDP locais já publicadas por Edge, Chrome, Brave, Vivaldi, Chromium,
  Opera e Opera GX são descobertas sem ler cookies ou copiar perfis. A sessão
  existente recebe somente uma nova aba do Setup; finalizar fecha essa aba,
  preservando o navegador e as abas anteriores. Conexões ambíguas não são escolhidas.
- Sem conexão DOM disponível, o caminho assistido anterior continua identificado
  como um perfil do Setup que exige login. Isso **não atende ainda** ao requisito
  de aproveitar automaticamente qualquer perfil normal já autenticado.
- `--report-file caminho.json`, com `--check` ou `--silent`, gera evidência por
  eixos fixos sem incluir credenciais nem respostas brutas do provedor. Verificação
  adiada, login pendente e falha nunca são apresentados como homologação.
- Bloqueio de instalação, journal, backup e restauração usam caminhos Win32
  estendidos onde necessário. Uma falha de Setup restaura os arquivos originais,
  conserva identidade e mantém os snapshots anteriores.
- O bundle React foi reconstruído. Os arquivos de texto selados usam LF, inclusive
  avisos de licenças oriundos do npm, para preservar seus hashes no clone Windows.
- A dependência Wasmtime 49.0.0 está fixada no lock e no manifesto Windows AMD64,
  com hashes do DLL e da licença verificados contra o wheel oficial. Seleção
  divergente de versão, licença ou biblioteca nativa é recusada antes do build.
- O build do Web Models materializa explicitamente o Electron fixado após instalar
  os pacotes; uma instalação interrompida não pode deixar um runtime ausente
  escondido por uma mensagem de dependências já instaladas. Seus downloads usam
  cache dentro da área de build, inclusive no electron-builder.
- O display Electron retorna falha se o renderizador cair ou o Canvas não carregar.
  Antes, a rejeição de `loadURL` podia encerrar o processo com sucesso.
- O Setup instala e executa `healthcheck.cjs` contra o próprio display de produção,
  em perfil novo e com páginas sintéticas locais. Exige renderização real,
  isolamento Node/contexto, sandbox, segurança Web, sessão efêmera, bloqueio de
  pop-up e de requisição a outro servidor local. Hashes precedem a execução;
  retorno 0 sozinho não é aceito. A evidência tem nonce e o ticket deve ter sido
  consumido. Timeout encerra somente a árvore descartável por Job do Windows.
  Falha impede sucesso, abertura da interface e criação de recursos na conta,
  inclusive no modo silencioso. Reparo repete essa verificação sem reinstalar.
- O registro local do plugin tem um componente offline com o executável oficial
  do Codex CLI 0.163.0, sem modificação, licença Apache e NOTICE. O ZIP original
  e o executável extraído têm SHA-256 fixado; o Setup verifica novamente os
  arquivos antes de copiar e antes de executar. O componente serve somente aos
  comandos de registro do plugin. Ausência ou alteração exige reparo e não usa
  outro CLI encontrado no PATH para esconder o problema.

## Evidências e limites

A regressão de instalação, empacotamento, recuperação e conexão DOM executa
testes com arquivos reais e testes com Edge e Brave reais usando login sintético
local. Esses testes comprovam a preservação da sessão e da aba original; não acessam
uma conta OpenAI real. Os testes de transporte de runtimes usam fixtures e não
comprovam os componentes de distribuição.

Uma resolução com `--ignore-installed --require-hashes` encontrou `cryptography`
transitivo sem pin, que estava oculto por um ambiente de desenvolvimento já
preenchido. A versão 50.0.2 e o hash do wheel Windows foram fixados. O lock corrigido
foi instalado por completo em **outro ambiente virtual inicialmente vazio**;
`pip check` terminou sem conflitos. Nesse ambiente, a regressão dirigida teve
**167 aprovados, sem falhas nem skips**, incluindo os contratos Web/Electron,
19 testes do protocolo/ciclo de vida da verificação do display e oito casos
novos da verificação antecipada de credenciais. Isso prepara e verifica o build;
não significa que o usuário final terá de instalar Python ou npm.

Após acrescentar o componente de registro offline, 77 testes focados passaram,
incluindo registro e reutilização reais do plugin com o CLI incorporado e um
servidor MCP isolado. O teste incorporado deixa somente System32 no PATH e usa
um diretório Codex descartável. Não modifica a configuração pessoal e não
comprova autorização em uma conta OpenAI. A suíte mais ampla de 114 casos teve
107 aprovados e sete falhas: quatro de DPAPI neste logon, uma de acesso ao
diretório do usuário e duas em fixtures antigas de Desktop. Essa execução
também permanece registrada; não é apresentada como aprovação integral.
A regressão integrada seguinte teve 196 aprovados, sem falhas nem skips, com
um aviso de depreciação do `msilib`. O teste adicional do Brave passou: a suíte
DOM teve 20 aprovados, incluindo Edge 155.0.4283.62 e Brave 155.1.97.59. São perfis
descartáveis com CDP publicado, sem prova de uso do perfil comum do usuário.

Componentes compilados nesta etapa:

- **QuickJS:** WASM real com ABI inspecionada, hashes e licenças do upstream
  conferidos. Os 11 casos da QA de runtime passaram, incluindo execução, Unicode,
  isolamento do host, limites de memória/resultado/CPU/tempo, exceções e cancelamento.
  O guest tem SHA-256 `5de70c4c7140aa43fbff39c8d53e261573e9df857a44cb5c3d0ff6412a57b9a6`.
- **HCS:** ponte Windows compilada da revisão aprovada de hcsshim, com módulos Go
  verificados e smoke test de rejeição de entrada malformada. Não há prova de
  criação/execução de VM por esse resultado.
- **RustDesk instrumentado:** as quatro fases de geração, compilação nativa,
  isolamento e Flutter concluíram. A interface produziu 91 arquivos com hashes;
  a DLL principal tem 39.805.952 bytes e SHA-256
  `91b7da1a8d1a9f4bc30a26cce70d8476ece828274d7a52575e90609e50ed000a`.
  A DLL carregou no Windows e retornou ABI 1 pelo símbolo SENTRA. Dois perfis
  mantiveram configuração, logs e IPC isolados; a tentativa de escapar do perfil
  foi recusada. Os imports dos 15 binários foram inventariados sem dependência
  estática ausente nem runtime VC++ externo ao pacote. Esses resultados não
  comprovam conexão remota, controle de desktop ou instalação pelo Setup.
  A materialização terminou com 1.379 arquivos, 771 dependências inventariadas
  e arquivo de fontes de 670.154.695 bytes. A QA conferiu todos os arquivos do
  componente e as 72.368 entradas do arquivo de fontes. A revisão de distribuição
  continua pendente no manifesto, com 74 itens; não há declaração de homologação.
- **Web Models:** build completo da revisão aprovada e do patch registrado,
  72 testes Bun e 9 testes Node aprovados, typecheck e produção Vite concluídos.
  O payload inclui Bun e os 112 pacotes de runtime, além de Electron 41.10.7.
  O validador de proveniência do launcher aceitou o resultado.
- **Display Electron 44.0.0:** 79 arquivos reais empacotados e validados por hash,
  incluindo a verificação executada pelo Setup. A execução real dessa verificação
  iniciou o processo e retornou `display_probe_failed`, código 4. Não comprovou
  abertura da interface e não foi convertida em sucesso por metadados ou mocks.
  O teste de janela com sandbox continua falhando neste processo Windows: os
  subprocessos de renderização/GPU não iniciam, com status `0xc0000135`; o próprio
  Chromium registra também a falha DPAPI. Não se removeu o sandbox para aprovar o teste.
- **Auxiliar de atualização:** EXE de 117.981.143 bytes compilado com PyInstaller;
  `--help` executou fora do repositório com PATH sem Python. A proveniência
  pertence ao momento desse build; alterações posteriores exigem nova compilação
  para o candidato final. Esse auxiliar isolado não constitui um Setup.

O `--check` anterior executado a partir do código retornou 2 por payload incompleto:
identifica os outros 13 executáveis ausentes. Separadamente, continuam ausentes
o componente RustDesk materializado e a composição `runtime-components.json`,
exigidos para o build integral. Depois desse checkpoint, RustDesk foi compilado,
materializado e verificado; os três runtimes foram compostos com 10 arquivos de
QuickJS, 25 de HCS e 1.380 de RustDesk, incluindo o manifesto do componente.
A release pública de 08/10 foi inspecionada por leituras HTTP limitadas do índice
do arquivo PyInstaller; não contém os componentes QuickJS/HCS/RustDesk necessários.
O candidato mais recente documentado é um rascunho privado. A tag remota mais
recente foi conferida: `installer-preview-20261015-42870dc`, tag anotada que aponta
para `42870dcd50a2476b2f3b52b3c36bd27d86f9496c`. A tag preserva código, sem incluir
as partes binárias do Setup. O conector GitHub agora está disponível, mas a conexão
atual tem apenas leitura do repositório; consultar a release de 15/10 retorna 404.
A listagem autenticada mostra somente a release pública anterior, de 08/10.
O Git local está funcionando. Os fontes RustDesk e o submódulo aprovado foram
preparados em uma área isolada, receberam o patch de instrumentação e passaram
na validação dos sete arquivos nativos. Isso não é uma compilação do componente.
O arquivo informado em Downloads foi inspecionado: é um ZIP de fontes da tag,
com 16.159.569 bytes e 2.282 entradas, sem executáveis nem partes do Setup.
Seu SHA-256 é `55825ee57eedfbaed0727c5e51dacb4e543fdc63b962cba20c8019292f3d8c7b`.

Rust 1.75.0, Flutter 3.24.5, libclang 15.0.6.1, gerador Flutter Rust Bridge 1.80.1
e vcpkg na revisão aprovada foram preparados na área de build. Os arquivos
baixados tiveram seus hashes oficiais conferidos; Rust, Flutter, o gerador e
vcpkg executaram a consulta de versão. `flutter pub get --offline` passou depois
de preparar 32 junctions para plugins dentro do cache selecionado. O builder
agora respeita `PUB_CACHE` também na preparação dessas ligações; a regressão do
builder e dos links reais teve 15 aprovados, sem falhas ou skips.

Após a instalação feita pelo usuário, o Build Tools
2022 17.14.42 apareceu completo, com MSVC, CMake, ATL e Windows SDK 10.0.22621.0,
sem reinicialização pendente. A compilação e execução de um programa Rust nativo
no ambiente `vcvars64.bat` passaram com código 0. O bloqueio de compilador acima
foi resolvido. A compilação integral do RustDesk foi concluída nas etapas seguintes.
O gerador concluiu e produziu cinco arquivos com prova de entradas e saídas.
`cargo-expand` 1.0.95 foi compilado e instalado. A falha TLS nativa do contexto
foi contornada preparando 1.033 crates oficiais, cada um conferido pelo SHA-256
do lock, além dos repositórios Git fixados. Cargo resolveu 991 pacotes com
`--locked --offline`; não se desativou a validação TLS.
Todas as instalações solicitadas ao vcpkg terminaram com sucesso, incluindo
FFmpeg, AOM, libvpx, libyuv, Opus e JPEG. O catálogo instalado registra 19 entradas
de pacotes/features. As fases nativa, de isolamento e Flutter passaram. A
materialização com fontes correspondentes e inventário de licenças foi verificada.
O coletor respeita `PUB_CACHE`; a regressão cobre o cache configurado e o padrão,
mantendo a recusa de fontes externas à seleção autorizada. A conferência real
cobriu 214 pacotes e 19.760 arquivos Dart. A composição dos runtimes passou.
Não foram usados binários fictícios nem removidos os gates para gerar um pacote
incompleto. Web Models e o auxiliar recém-compilado não têm assinatura Authenticode.

A proteção DPAPI falha no processo desta sessão, inclusive com entrada sintética.
O novo preflight real confirmou `credential_protection_unavailable` neste
contexto. Os imports PE normais e adiados dos sete binários do display foram
inventariados; esse inventário não comprova disponibilidade de cada biblioteca
no carregador do Windows nem inicialização do renderizador.
A consulta correta ao erro do Windows retorna 2. A permissão de acesso ao diretório
Microsoft/Protect foi concedida e o teste continuou falhando. Não foi introduzido
armazenamento de chaves em texto simples como alternativa. Os testes anteriores
de cadastro que dependem de DPAPI não passam neste ambiente.

O primeiro build integral parou no gate do Canvas: CSS e avisos do xterm tinham
conversão CRLF no checkout. Foram restaurados exatamente os bytes aprovados pelo
manifesto, com preservação por `.gitattributes`. PDFium 4.30.0, já exigido pelo
builder, foi incluído no lock principal e instalado pelo hash fixado. O build
integral agora confere esses insumos antes de compilar qualquer executável.

Os testes de transporte DOM usam os defaults do Playwright. A repetição com
`chromium_sandbox=True` falhou no Edge e atingiu o limite de tempo no Brave neste
contexto. Portanto, os testes anteriores não homologam perfis normais nem o
isolamento do navegador. A proteção do display de produção não foi removida.

O smoke dos primeiros 14 binários revelou import antecipado de GitPython em
`workspace.git_manager`, que impedia agente e MCP de iniciar sem Git no PATH.
O import foi movido para a operação de inspeção do repositório Git, protegida
pelo tratamento já existente. A inspeção de arquivos comuns não requer Git;
mutações Git continuam recusadas quando não há um repositório disponível.
Os binários precisam ser reconstruídos com essa correção antes da entrega.

## Trabalho ainda necessário para cumprir o objetivo completo

1. Reconstruir todos os executáveis e o Setup com os fontes finais. A seleção
   dos três runtimes já passou no executável congelado, sem Python, Node ou Git
   externos no PATH. A alteração do WASM e dos hashes adjacentes foi recusada.
   Isso comprova a seleção incorporada, sem comprovar uma instalação completa.
2. Implementar e distribuir a ponte DOM assinada para perfis normais. CDP já
   publicado é apenas um transporte disponível, não uma solução para todos os
   navegadores. Firefox ainda não tem um adaptador de sessão existente neste fluxo.
3. Validar cadastro com proteção Windows funcional, conta real, consentimentos
   exigidos pelo provedor e autorização real do plugin.
4. Executar o novo Setup em Windows limpo: instalação, primeiro uso, reinício,
   dependências ausentes do PATH, atualização, recuperação e desinstalação.
5. Homologar separadamente cada navegador/versão e assinar a distribuição.

Chrome não permite depurar seu diretório de perfil padrão pelo switch de depuração
desde a versão 136. Instalação de extensões no Chrome/Edge e assinatura no Firefox
têm requisitos próprios; não podem ser substituídos por uma alegação de que o
login foi reutilizado.

Fontes oficiais: [depuração do Chrome](https://developer.chrome.com/blog/remote-debugging-port),
[distribuição Chrome](https://developer.chrome.com/docs/extensions/how-to/distribute/install-extensions),
[distribuição Edge](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-manage-extensions-webstore),
[assinatura e distribuição Firefox](https://extensionworkshop.com/documentation/enterprise/enterprise-distribution/).
O CLI usa os [comandos oficiais de plugins](https://learn.chatgpt.com/docs/cli/reference)
e o [pacote oficial 0.163.0](https://github.com/openai/codex/releases/tag/rust-v0.163.0).
