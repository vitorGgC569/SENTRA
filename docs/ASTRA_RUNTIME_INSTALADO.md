# ASTRA — seleção dos componentes no produto instalado

Estado em 15/10/2026: implementação e ensaio com executável congelado aprovados;
Setup integral, assinatura, instalação limpa e sessões remotas permanecem abertos.

## Problema resolvido

Copiar `runtime/quickjs`, `runtime/hcs` e `runtime/rustdesk` para a instalação
não bastava. QuickJS dependia de quatro variáveis de ambiente, e configurações
nativas exigiam caminhos/hashes manuais. Um manifesto editável ao lado do
programa também não pode declarar sozinho que seus próprios bytes são confiáveis.

`scripts/commander/runtime_bindings.py` verifica todos os arquivos materializados
e produz `sentra-runtime-pins.json`. O build embute esse arquivo em cada EXE
Python. O registro de proveniência vincula seu hash ao executável e às fontes;
mudança dos componentes durante o build impede a emissão de prova válida.

`sentra_remote/runtime_payload.py` aceita esse recurso somente em executáveis
congelados. Deriva a raiz da instalação de `sys.executable`, recusa links,
aliases, caminhos de outro componente e arquivos com hash divergente. Não
procura pins no workspace, diretório atual, marcador de instalação ou variável
de ambiente. A confiança do recurso depende da cadeia de distribuição e
assinatura do EXE; o teste candidato não afirma assinatura válida.

## Uso e autorização

- QuickJS conserva a configuração explícita por ambiente para operadores.
  Configuração parcial é erro, sem fallback silencioso. Sem essas variáveis,
  o executável instalado pode selecionar seu WASM/SBOM pelos pins embutidos.
  Checkouts de fonte continuam exigindo configuração explícita.
- A composição Code Mode e seu dispatcher usam esse resolvedor. O recurso não
  habilita uma máquina, não registra ferramentas nem concede Grants.
- Configuração RustDesk sem campos de build, ou com `runtime: installed`, usa
  os pins instalados. Escolha instalada não pode sobrescrever caminhos/hashes.
  O caminho existente confere todo o bundle e o copia para armazenamento privado.
  Persistem os pins selecionados, sem retarget automático de uma configuração
  existente ao reiniciar ou atualizar a instalação.
- HCS usa o helper instalado quando seus campos nativos são omitidos ou
  `runtime: installed` é solicitado. Camadas, uVM, comandos, escopo e recursos
  continuam explicitamente configurados. Não ativa HCS, inicia container ou
  eleva privilégio para tornar a configuração disponível.
- RustDesk usa o manifesto completo para proveniência e `bundle-manifest.json`
  para o executor; esse segundo arquivo continua limitado a 64 KiB.

## Build

Materializar os três componentes em uma raiz isolada antes de compilar payload
ou Setup. `build_windows.py --runtime-components <raiz>` seleciona essa raiz;
sem o argumento, usa `dist` quando já contém `runtime-components.json`.
As fases `all`, `payload` e `installer` recusam ausência dos componentes.

Fases isoladas de desenvolvimento podem continuar sem pins; seus EXEs não
satisfazem o gate do Setup integral. O Setup exige que cada EXE Python do payload
tenha prova das fontes atuais e do mesmo hash de pins dos componentes que serão
instalados. O launcher C# delega aos EXEs Python e não interpreta os componentes.

`--phase runtime-probe` compila um programa de QA somente leitura, fora de
`PAYLOAD_NAMES`; ele não é produto instalado nem substitui o Doctor completo.
O pin existente do SDK Wasmtime continua obrigatório no host de build.

## Correção de caminhos Windows

A integração real de MachineHost falhou com o manifesto privado em um caminho
de 274 caracteres: o arquivo existia, mas o acesso ordinário falhava. O acesso
interno agora usa a API de caminhos longos; a resolução devolve caminhos comuns
para as verificações de escopo. `AuthorizedPaths` continua recusando device
paths e ADS recebidos como argumento e verificando raízes/exclusões. O fluxo
RustDesk também verifica assets aninhados acima de 260 caracteres. Nenhuma
política global de caminhos ou Developer Mode foi alterada.

## Evidências

`runtime-staging-v1`, fora do checkout, reúne QuickJS (10 arquivos), HCS (25) e
RustDesk (1.380, incluindo o manifesto completo). Todos foram conferidos antes
de gerar os pins. O ensaio não concede aprovação legal por existência dos arquivos.

O snapshot `source-runtime-probe-v1` contém 1.567 entradas e 50.087.883 bytes.
O programa foi compilado de fato com PyInstaller 6.22.3 e executado nessa raiz:

```powershell
python -B tests/qa/astra_installed_runtime.py --staging <runtime-staging-v1> `
  --pins <runtime-pins-v1/sentra-runtime-pins.json> --report <relatorio.json>
```

Relatório: `.tmp/astra-installed-runtime.json`. Resultado positivo: executável
congelado, QuickJS com ABI/Wasmtime disponível e hashes dos três componentes
coincidentes. Resultado negativo: cópia isolada com WASM modificado e manifests
adjacentes repinados foi recusada. O diretório original não foi adulterado.

- EXE de QA: `d0ae983459bff29c44b74b257d72856bf577a14b6baacfb35f43860257f8a4fe`.
- Pins embutidos: `a53289555bd94943c0a761eeb3068d33e0ccc5dfcf82f021e9e8482e6f018f86`.
- Snapshot: `8e3dc38a07d603e358e1a93130b13da7b26a3bd96848528bb41a157a19552f32`.

Regressão: 67 testes aprovados, três ignorados e quatro subtestes aprovados em
19,61 s, incluindo MachineHost/SQLite reais sem criação de Grant ou Operation,
manifesto/bundle privado, Code Mode e limites de caminhos. Após estender o acesso
à materialização, 51 testes relacionados passaram, um ignorado, em 7,22 s.
Os testes usam arquivos nativos sintéticos onde explicitado e não os executam.

Limites: esse probe compila/verifica o módulo QuickJS, mas não executa uma tarefa
com ferramenta pelo Control Plane. Não inicia clientes HCS/RustDesk, autentica
peer, controla desktop, instala Setup ou testa atualização/rollback. A revisão
de licenças/fontes do RustDesk permanece aberta em candidato separado; não há
declaração de `legal_release_ready`, assinatura ou release homologado.
