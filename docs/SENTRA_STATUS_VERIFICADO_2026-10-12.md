# SENTRA — estado verificado em 12/10/2026

Este registro distingue implementação, teste unitário e execução real. O checkout é compartilhado; as alterações desta rodada não foram commitadas, publicadas ou limpas.

## Evidências reais já obtidas

- **Debian persistente do Dot Advanced:** VM `fcd974cf-ccdc-5636-b7af-2f96024d5dde`, disco próprio, boot pelo VDI, ISOs ejetadas, raiz `/dev/sda1` em ext4, LightDM e XFCE ativos. A verificação também passou pelo executor central (`op-shell-7326a0030be23e64e8ec85fbc7879f62e7c7c6d4`). O runbook tem recibos em `.sentra/durable/dot-vms/SENTRA-Dot-fcd974cfccdc5636/runbook-receipts/`.
- **Coordenador real e dois terminais:** GPT-6 Web em alto coordenou SENTRA CLI com GPT-6 Web em alto e OpenCode com `opencode/muse-spark-1.3-contributor-free#high`. Operação do coordenador `op-94baad8161fb6fd4b4423e6ac1aecdeb`: `SUCCEEDED` em 115,2 s, resposta final confirmada no diário protegido. Evidência em `.tmp/live-root-dispatch-a75f9a8c8b/report.json`.
- Os dois trabalhos filhos têm recibos de inferência real e ficaram em **IN_REVIEW**; esse teste não promoveu automaticamente os trabalhos para COMPLETED. Os processos dessa prova rodaram no host em um Canvas de QA isolado. Isso não comprova execução dos mesmos CLIs dentro da VM.

## Correções mais recentes

- Menu lateral implementado para editar, abrir Canvas, fixar, subir/descer e arrastar Dots, com preferência persistida e proteção contra aplicar duas vezes o mesmo movimento. A exclusão definitiva continua pendente; arquivamento local reversível não substitui a remoção solicitada.
- Correção do comando de cópia para a VM: removido o argumento `/bin/sh` duplicado no `guestcontrol run`. A tentativa física anterior continua preservada como UNCERTAIN, sem repetição. Falta uma prova real nova com conteúdo de projeto, além da seleção explícita de uma pasta do host.
- Na integração Web, revisões do DOM não são mais promovidas a deltas irreversíveis antes da confirmação final. Ainda é necessário conectar as prévias provisórias à conversa para obter streaming visual real sem corromper a resposta final.
- Descoberta e corrigida a divergência de filas: o relay standalone consumia `.oma/relay.sqlite3`, enquanto o Canvas admitia trabalhos em `.sentra/browser/relay.sqlite3`. O padrão agora é a fila do Canvas. Os registros antigos foram preservados, sem migração ou reenvio.
- O health do relay informa uma identidade derivada da fila real, sem expor o caminho. Os probes rejeitam um relay ligado à fila errada.
- O coletor da extensão instalada foi cadastrado pelo endpoint autenticado e atualizado para o hash da versão instalada. Esse cadastro não criou Grants de execução.
- Uma tentativa recusada antes do ACK de envio mantinha a referência da aba ocupada. A recuperação agora permite liberar somente essa referência quando os dois diários comprovam ausência de autorização de envio. Operações possivelmente enviadas continuam em observação e nunca são reenviadas por essa rotina.
- Adicionado o pedido explícito `/image` para usar o compositor Web sem anexos artificiais ou instruções para o plugin SENTRA gerar o arquivo. Por enquanto aceita conversas novas ou já vinculadas ao relay; uma conversa CLI existente é recusada antes de admitir o envio, preservando sua identidade. Essa rota precisa da prova física de entrega abaixo antes de ser considerada concluída.

## Validação recente

- 14 testes Python aprovados em dispatch, evidências dos runners e importação de projeto; um teste de symlink ignorado por indisponibilidade desse recurso no token Windows.
- 19 testes Python aprovados em composição do relay, identidade da fila e recuperação de referências, incluindo recusa de liberação se houver qualquer possibilidade de envio.
- 3 testes Node aprovados para a identidade e a origem de arquivos de imagem nativos.
- 13 testes Python aprovados em pedido nativo de imagem e projeção de mídia, incluindo preservação de conversas existentes. Novo build Vite concluído.
- O build da interface e os testes de buffer/ativos nativos da integração Web passaram na rodada anterior. Esses resultados não são uma prova de todas as funcionalidades do produto.

## Trabalho ainda necessário

1. Exclusão definitiva do Dot e sua família: arquivar de fato as conversas no ChatGPT, remover conversas e Canvas locais e retirar a VM/disco próprios com recibos de identidade e término. Impedir que a migração recrie um Dot retirado.
2. Acesso dos membros do Canvas à mesma VM exclusiva, com WorkItems próprios e uma única posse de entrada para o computador físico convidado.
3. Instalação automática integrada à interface na primeira criação. O Debian foi instalado de verdade pelo runbook, mas a interface ainda exige etapas manuais. Windows ainda necessita de validação com uma imagem instalável adequada.
4. Importação de uma pasta/projeto do host escolhido pelo usuário e prova física de transferência e leitura dentro do convidado.
5. Imagens: concluir uma prova de geração nativa → coleta autenticada → bytes verificados → Canvas. Cadastro, fila e transporte disponíveis não equivalem a imagem entregue.
6. Antigravity: existe integração para abrir o aplicativo, mas falta um contrato verificado para inferência não interativa. Não tratar uma janela aberta como um agente que respondeu.
7. Smart UI: componentes declarativos locais existem; falta validar o ciclo de interação e retorno ao agente. Isso não equivale à UI nativa completa do ChatGPT.

Os detalhes dos testes de imagem ficam em `.tmp/native-image-e2e-*.json`. Somente um relatório com `generated_asset_verified: true` comprova entrega do binário. `ADMITTED`, `UNCERTAIN_NO_RESEND` ou resposta sem binário não são sucesso de geração.

O teste com anexo de QA chegou ao ACK central de envio, mas terminou em `BINARY_UPLOAD_UNCONFIRMED` (`.tmp/native-image-e2e-a5b32606ff.json`). A operação ficou UNCERTAIN e não foi repetida. A presença desse ACK não prova que a mensagem foi enviada ou que uma imagem foi gerada. A nova rota `/image` foi criada justamente para dispensar esse anexo artificial; permanece pendente de prova física.
