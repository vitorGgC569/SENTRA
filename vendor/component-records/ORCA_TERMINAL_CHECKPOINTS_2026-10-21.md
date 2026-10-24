# Checkpoints de terminal ORCA no SENTRA — 21/10/2026

Esta rodada implementa restauração do estado do emulador no caminho experimental
do daemon. O plano integral continua em aberto. O SENTRA instalado foi aberto
pelo atalho a pedido do usuário; a janela `SENTRA Desktop` foi identificada.
Os builds de avaliação permanecem separados da instalação.

## Código aproveitado e adaptação

- 28 arquivos exatos do ORCA no pin `70b2197c`, incluindo módulos de headless,
  serialização, cursor absoluto, modos, Unicode, OSC, cauda de escape e o patch
  do serializer. Origem, hashes e MIT em
  [provenance](../integrations/orca-terminal/provenance.json).
- Pacote próprio `integrations/orca-terminal`, com dependências fixadas e build
  isolado. O inventário agora verifica essas cópias contra blobs Git do pin,
  além dos oito módulos de transporte e das onze origens de adaptação anteriores.
- Worker Node de observação por stdio, sem API de escrita em PTY, credenciais,
  store global ORCA ou listener de rede. Artefato e fontes são conferidos antes
  da inicialização. Ausência/falha do runtime desabilita a capacidade explicitamente.
- Extensão SENTRA para os registradores salvos dos dois buffers: atributos SGR,
  charset e hyperlinks. O ensaio de retorno do buffer alternativo revelou perda
  da cor salva no buffer normal; a correção preserva ambos. A integração usa
  APIs internas auditadas das versões xterm fixadas e exige nova avaliação ao
  atualizar essas dependências.

## Persistência e apresentação

- Esquema SQLite 2: eventos de saída e resize têm sequência ordenada; checkpoints
  e transcrições recebem proteção do sistema operacional. Histórico antigo é
  preservado e identificado como sem geometria ordenada.
- Quota agregada de 16 MiB de **payload cifrado** compartilhada entre chunks e
  checkpoints; metadados SQLite são adicionais. Um checkpoint maior que a quota
  é recusado sem apagar a transcrição para tentar fazê-lo caber.
- Fila de 4 MiB agregados e 512 KiB por sessão inclui saída em gravação e eventos
  de resize. Saturação invalida a alegação de frame coerente e indica lacunas.
- Espelhos limitados a 32 e a dois milhões de células lógicas agregadas. Isso
  não é uma medição/garantia de RSS. Após término e confirmação da drenagem do
  leitor, o espelho é descartado conservando o checkpoint.
- Até 500 linhas de scrollback por espelho/checkpoint, reduzidas se necessário
  para respeitar 512 KiB do frame. A UI indica quando esse histórico é limitado.
  Paginação do histórico bruto anterior ainda não foi integrada ao workspace.
- Endpoint de leitura autenticado `/api/terminal/checkpoint`, com escopo do
  recurso validado no Canvas e no daemon. Não concede autoridade de execução.
- O pool restaura buffers, cursor, modos e cauda de escape, bloqueando entrada
  e respostas automáticas do emulador durante a restauração. Filas de entrada
  de uma conexão anterior são invalidadas por epoch.
- Geometria sem cobertura, sequência perdida ou runtime indisponível produzem
  pendência/erro explícito ou imagem parcial; não recebem sucesso aparente.
- Após morte do daemon, a recuperação permanece somente leitura e não inicia
  um processo. Observar um histórico não comprova continuidade física.

## Evidência e limites de aceite

Os ensaios incluem ConPTY/DPAPI reais, morte e reinício de daemon de teste,
consulta HTTP autenticada, recusa sem token e recusa de terminal de outro
workspace. O efeito no arquivo temporário permanece exatamente uma vez.

Testes de xterm comparam células, cores, largura Unicode, cursor, modo ativo e
continuação após escape incompleto. Executam em Node sem DOM/janela/navegador;
não constituem inspeção visual. A conferência visual nova continua pendente,
assim como carga prolongada com TUIs reais, backpressure por consumidor e
empacotamento do runtime no instalador.

Comandos de preparação e limites adicionais:
[README do pacote](../integrations/orca-terminal/README.md).

Não houve homologação física Android/iPhone, assinatura de pacotes, publicação,
substituição de bundles instalados ou turno completo de modelo nesta rodada.

## Resultado reproduzível

- **46 testes Python passaram**, com os percursos móveis de aceitação habilitados
  (`SENTRA_MOBILE_ACCEPTANCE=1`), sem testes ignorados nesse lote.
- **142 testes Node desktop** e **quatro do engine** passaram. As repetições
  durante os ajustes não são somadas a esses totais.
- Dois builds desktop isolados concluíram, com os avisos já existentes de scripts
  legados e tamanho do bundle. Os testes não comprovam fidelidade visual.

Build experimental: `sentra-orca-experimental-80aaff652255`.
O manifesto registra também os chunks e assets dos dois builds desktop isolados,
o engine/manifest de terminal e os bundles móveis de avaliação existentes.
As exportações móveis não foram refeitas nesta rodada sem alterações no app.
Conferência final: 121 fontes, 261 saídas e nenhum hash divergente.
