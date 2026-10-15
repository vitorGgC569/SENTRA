# Build isolado do SENTRA

O build usa uma cópia verificável das entradas do produto. Sessões, credenciais,
`node_modules` e artefatos antigos não são fontes de produto. Dependências nativas
continuam selecionadas e verificadas separadamente; o selo de fontes não as aprova.

## Interface e cópia das fontes

Na raiz do checkout, reconstrua o bundle antes de criar a cópia:

```powershell
npm run build --prefix sentra_canvas/desktop_ui
python -m scripts.commander.source_snapshot C:/SENTRA-build/release-candidate/source
python -m scripts.commander.source_snapshot C:/SENTRA-build/release-candidate/source --verify
```

O destino deve ser novo e ficar fora do checkout. A cópia falha se as entradas
mudarem durante a captura. Não há mesclagem com um candidato anterior. O arquivo
`source-snapshot.json` lista os hashes; o build confere o selo antes de compilar e
antes de emitir proveniência. Os caches gerados posteriormente não alteram o selo.

O manifesto React associa o resultado às fontes, scripts, arquivos públicos,
lockfile e configuração do Vite usados na compilação. Alterar essas entradas
exige novo `npm run build`; ter apenas hashes válidos do JS/CSS não basta.

## Componentes

HCS usa o checkout limpo de hcsshim na revisão registrada em
`sentra_quality/approved_sources.json` e a versão exata de Go exigida pelo módulo:

```powershell
python -m scripts.commander.build_hcs C:/SENTRA-build/release-candidate/hcs --go C:/toolchains/go1.26.8/go/bin/go.exe
```

O builder arquiva a revisão selecionada, copia o helper, resolve/verifica módulos
no diretório isolado e compila com `-trimpath` e build ID vazio. O manifesto em
`artifact/manifest.json` inclui binário, fontes, compilador, módulos e licenças.
O teste automático de JSON inválido não cria nem executa containers.

QuickJS usa o SDK identificado em `sentra_code_mode/guest/licenses/PROVENANCE.json`:

```powershell
python -m scripts.commander.build_quickjs C:/SENTRA-build/release-candidate/quickjs --sdk C:/toolchains/wasi-sdk-34.0-x86_64-windows
python -B tests/qa/astra_quickjs_runtime.py C:/SENTRA-build/release-candidate/quickjs/artifact
```

O builder copia o guest e seus avisos legais. O driver verifica o tarball fixado,
aplica somente as transformações delimitadas, compila, inspeciona o ABI e emite
WASM/SBOM/proveniência/licenças. O resultado não importa WASI. CPU, memória, fuel,
tempo, cancelamento e respostas reais são verificados separadamente no ensaio.
Os probes desse ensaio não autorizam ferramentas de sistema.

O RustDesk precisa do cliente modificado com `sentra-desktop-control-v1`, revisão
fixada, submódulos, dependências, licenças e manifesto do build real. O emissor
`native_peer_gate_patch` só produz um patch revisável; não certifica um binário.
Normalizar CRLF não relaxa as âncoras de versão ou a recusa de source drift.

## Candidato Canvas

Selecione o registro existente de Wasmtime somente no processo de build e execute
o builder da cópia. Use diretórios de dist/work/spec próprios do candidato:

```powershell
$env:SENTRA_BUILD_RUNTIME_PINS_FILE = 'C:/SENTRA-build/host-runtime-pins-wasmtime.json'
python C:/SENTRA-build/release-candidate/source/scripts/commander/build_windows.py --phase canvas --dist C:/SENTRA-build/release-candidate/dist --work C:/SENTRA-build/release-candidate/work --spec C:/SENTRA-build/release-candidate/spec
python -B tests/qa/astra_frozen_canvas.py C:/SENTRA-build/release-candidate/dist/sentra-canvas.exe
```

A seleção acima não grava variáveis persistentes do Windows. O registro deve
cobrir a versão, DLLs e licenças realmente instaladas. A comparação dos hashes
não substitui a aprovação do pin pelo responsável pelo release.

O ensaio do executável cria estado separado, verifica autenticação, assets,
SSE e persistência de workspace após reinício e encerra apenas os brokers que
ele iniciou. Não lança janela nem chama provedores de modelos.

## Setup integral

O Setup continua exigindo todos os executáveis com provas do mesmo conjunto de
fontes, Web Models atualizado, Electron, os três componentes nativos, manifestos
e licenças. Instale as dependências de build fixadas no ambiente isolado apropriado;
os SDKs, npm e clones upstream não são transportados pelo selo das fontes Python.
Reconstruir o bundle dentro de uma cópia já selada altera suas entradas e exige
uma nova captura.

Depois da compilação, ainda são obrigatórios assinatura real do publicador,
instalação limpa, atualização/rollback, tarefa real, reinício e retomada no
produto instalado. Não publicar candidatos de componente como release integral.
