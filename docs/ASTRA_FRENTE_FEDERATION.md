# ASTRA — execução real por Federation

Esta frente avançou a delegação além da aritmética. O código fonte agora aceita
um plano explícito e delimitado, executa suas etapas no `MachineHost` da
instalação receptora e devolve um artefato verificável, sujeito à revisão. Não
há homologação do Setup/VM nem inferência de modelo nesta evidência.

## Contrato implementado

`PeerGateway.delegate(node, scope, task)` continua aceitando texto para o
fallback aritmético e também aceita:

```json
{
  "schema": 1,
  "objective": "Criar e verificar uma entrega remota",
  "steps": [
    {
      "machine_kind": "workspace-files",
      "capability_id": "workspace:file.write",
      "arguments": {"action": "write", "path": "entrega.txt", "content": "Entrega"}
    },
    {
      "machine_kind": "workspace-files",
      "capability_id": "workspace:file.read",
      "arguments": {"action": "read", "path": "entrega.txt"}
    }
  ]
}
```

O plano não fornece owner, principal, Grant, WorkItem, raiz nem backend. O host
seleciona uma única máquina configurada do tipo/capacidade para o Dot receptor.
Não configura máquinas nem concede permissões como consequência do pedido.
Cada etapa tem WorkItem e Operation próprios, usa o registro central, o Grant
da capacidade, orçamento e fencing físico existentes. O WorkItem agregado e
os filhos chegam a `IN_REVIEW` somente com recibos duráveis de sucesso. A
aprovação encerra os filhos e o agregado, sem executar novamente as etapas.

Os Grants de Federation e da máquina são independentes. A autoridade adicional
de Federation é um callback criado pelo gateway no host e encaminhado a
`MachineHost` → `CentralExecutorFactory` → gate e `CentralEffectContext`. É
revalidada em cada checkpoint físico e na captura do resultado, junto à
política original da máquina. O callback não é um campo do protocolo ou dos
argumentos. Apenas restringe a autorização existente. Factories próprias que
ainda não implementam esse contrato são recusadas nesse caminho.

`effect_executed` informa uma etapa comprovadamente executada; em uma falha
incerta pode ser `null`. `executed` mantém a semântica anterior de entrega
revisada/concluída, acompanhado de `review_approved`. Uma resposta preparada
para revisão não é apresentada como conclusão aprovada.

No Canvas, o listener recebe o executor do Dot e do Run selecionados no host.
`network_delegate` aceita o plano e `network_reconcile` consulta/reconcilia um
intent existente. Identificadores e cursores do protocolo não autorizam
reenvio. Escopos remotos de espaço/documento não são alargados para projeto
quando falta uma correspondência local explícita.

## Recuperação e isolamento

- Pareamento, revogação e journal persistem com proteção do sistema
  operacional, vinculados ao owner e à identidade da instalação. Há gravação
  atômica, `fsync` e exclusão entre processos. A projeção legada em texto é
  migrada em lugar; não pode restaurar pins que não possuía.
- Uma instalação reiniciada apresenta seus peers como desconectados até uma
  nova observação assinada; essa observação não retoma tarefas automaticamente.
- O intent é registrado antes dos efeitos. Se a cópia do recibo no journal
  ficou para trás, a reconciliação observa o resultado central já persistido.
  Intent conhecido sem prova final é `pending`, nunca prova de ausência.
- Revisão e reconciliação verificam o peer original, escopo, tarefa e Grants
  atuais. Um terceiro peer pareado não pode ler nem aprovar a tarefa de outro.
  Respostas assinadas precisam corresponder ao destino, tipo e intent enviados.
- Revogar o pareamento pede cancelamento das etapas ativas. Revogar o Grant de
  Federation durante uma etapa impede o próximo checkpoint, mesmo mantendo
  ativos os Grants da máquina. Efeito já publicado permanece incerto, com sua
  evidência preservada e sem repetição.
- Certificados novos usam issuer distinto por chave e AKI/SKI. Isso corrige a
  escolha de CA errada pelo OpenSSL quando vários peers têm certificados
  próprios. Identidades existentes não são rotacionadas silenciosamente.

## Correção encontrada na integração de arquivos

O executor de arquivos já publicava o arquivo real, mas a captura central só
reconhecia `arguments.output`; esse executor usa `arguments.path` relativo.
O resultado acabava `UNCERTAIN` após a publicação. Agora um resolver injetado
pelo registro do host usa o mesmo binding e os mesmos `AuthorizedPaths` da
execução. Ele não aceita uma raiz por argumentos, verifica o arquivo solicitado
e preserva a captura por hash dos bytes publicados. Uma falha depois da
publicação continua `UNCERTAIN` e não autoriza nova escrita.

Também foi corrigido o nome da variável no diagnóstico de erro de indexação
de experiência em `MachineHost._dispatch` (`oid`).

## Evidência reproduzível

```powershell
python -B tests/qa/astra_federation_task.py
```

O ensaio usa dois processos Python, diretórios de estado, identidades e Control
Planes independentes. O receptor executa uma escrita e uma leitura reais de
UTF-8 pelo executor de arquivos, com mTLS e frames assinados. O recibo é perdido
de propósito; o receptor encerra, reinicia e preserva o pareamento. A observação
recupera o mesmo resultado, mantendo o mtime do arquivo e as mesmas três
Operations (agregada + duas etapas). A revisão conclui os três WorkItems. Um
novo pedido após a revogação da capacidade de escrita é recusado.

Relatório: `.tmp/astra-federation-qa/report.json`. O campo `evidence_state`
identifica os estados, journals e artefatos efetivos preservados pelo ensaio.
O relatório declara expressamente `installed_setup=false`,
`windows_guest=false` e `model_inference=false`.

A regressão ampliada passou em **55 testes**. Depois dos últimos ajustes de
validação de recibos, reconciliação de mensagens e bridge do Canvas, os **25
testes afetados foram executados novamente e passaram**. Esses conjuntos se
sobrepõem. O bridge comprovou também a tarefa de arquivos entre projetos de
IDs diferentes, mantendo o escopo solicitado e o projeto receptor distintos.

Regressão desta frente:

```powershell
python -B -m pytest tests/unit/test_federation_machine_tasks.py tests/unit/test_workspace_files_durable_capture.py tests/unit/test_sentra_runtime_effect_boundary.py tests/unit/test_sentra_executors_central_integration.py tests/unit/frentes/wren/test_federation_executor.py tests/unit/frentes/wren/test_fronts_15_18.py tests/unit/frentes/wren/test_shell_federation.py -q --tb=short --disable-warnings -p no:cacheprovider
```

Inclui recibo perdido, reinício, lacuna entre commit central e journal,
duplicação, Unicode, escopo/tarefa divergentes, terceiro peer, revogação local
e remota de revisão, revogação de Federation antes/depois da publicação,
pareamento revogado em etapa ativa, caminhos fora da raiz e falha de captura
depois da publicação. Os testes antigos receberam agentes reais e leitura
protegida conforme a autoridade atual; as políticas não foram relaxadas.

## Arquivos desta entrega

Novos: `sentra_federation/task_runtime.py`,
`tests/unit/test_federation_machine_tasks.py`,
`tests/unit/test_workspace_files_durable_capture.py`,
`tests/qa/astra_federation_task.py`, este documento.

Alterados: `sentra_federation/executor.py`, `gateway.py`, `identity.py`,
`journal.py`; `sentra_canvas/shell_federation.py`;
`sentra_runtime/effect_boundary.py`, `machine_host.py`;
`sentra_executors/central_integration.py`, `workspace_files.py`;
`tests/unit/frentes/wren/test_fronts_15_18.py` e
`tests/unit/frentes/wren/test_shell_federation.py` e
`tests/unit/test_sentra_runtime_effect_boundary.py`.

## Revogação no fim da execução e na entrega (15/10)

A auditoria reproduziu uma falha real: revogar `federation.delegate` após as
duas etapas de arquivo, enquanto o agregado aguardava registro, ainda permitia
receber `result_ready=true` e o documento. Evidência anterior à correção:
`.tmp/fed-final-authority-2f068285/report.json`. Esse intent não foi repetido.

Agora `task_runtime.py` revalida o callback instalado pelo host após a última
etapa, antes da escrita do agregado, antes e depois do registro do artefato e
antes de submetê-lo à revisão. Perder autoridade nessa fase mantém as etapas
concluídas, conserva a evidência já capturada e registra o agregado como
`UNCERTAIN`, sem publicar o documento no recibo. Não há callback vindo do wire.

`gateway.py` revalida pareamento, Grant e associação de equipe após serializar
o frame e imediatamente antes de `TLS.sendall`. A checagem cobre também leitura
por reconciliação e respostas de revisão. A perda tardia fecha o canal como
incerto: não responde com uma falsa declaração de que nenhum efeito ocorreu.
Uma duplicata de delegação conhecida e do mesmo peer, recusada após perder
autoridade, também permanece incerta em vez de afirmar `executed=false`.
O resultado já persistido no receptor continua disponível para observação
autorizada. Um resultado já transmitido não pode ser recolhido; o checkpoint
não torna a revogação e a escrita no socket uma transação atômica.

A revisão revalida a autoridade antes de cada decisão/transição dos filhos,
depois do último filho e antes de concluir o agregado e gravar os recibos.
Uma interrupção preserva decisões já persistidas. Reiniciar e revisar o mesmo
intent conclui apenas o estado restante, sem executar novamente os adaptadores.

Nove novos casos verificam esses limites com mTLS e escrita/leitura reais:
revogação de Grant e pareamento após a última etapa, após captura do agregado,
antes do envio TLS e revogação de revisão após o último filho, após conclusão
do agregado e na entrega. Eles verificam restart, duplicatas, artefato privado,
três Operations e mtime inalterado. Os testes antigos de revogação foram
ajustados para esperar conexão incerta e consultar o recibo somente no receptor.

O ensaio de dois processos também passou novamente em
`.tmp/fed-guard-qa/report.json`, com estado isolado preservado em
`.tmp/fed-guard-qa/state-6de989420ed74fee9dabb95a0cd9383b`. Operation agregada:
`op-fedtask-774077860d8764a3b01c3e75cabb0297`; SHA-256 do artefato:
`47263c584f4543957026d161804dfc051efaa8bcd2c9324aa58deb5308f65377`.
Os três WorkItems chegaram a `COMPLETED`; não houve reescrita após o restart.
Após a correção adicional da recusa de duplicatas, o mesmo ensaio passou em
`.tmp/fed-guard-qa-final/report.json`, Operation
`op-fedtask-71b3b2195da1791986a963e882a61fa3`, artefato
`57b5af01e66e51e19d8910df1467deda6b2c221f841575757c9e384d371a4e6c`.
Esse ensaio geral e os testes de timing são evidências distintas. Nenhum prova
instalação pelo Setup, Windows guest ou inferência de modelo.

Arquivos desta correção: `sentra_federation/task_runtime.py`,
`sentra_federation/gateway.py`, `tests/unit/test_federation_machine_tasks.py` e
este documento. Não foram alterados `MachineHost`, `effect_boundary` ou os
candidatos RustDesk congelados.

Regressão ampliada: **65 testes aprovados**, relatório JUnit
`.tmp/fed-guard-regression.xml`. Após o ajuste da duplicata, os dois arquivos
diretamente afetados passaram novamente em **33 testes**; o resultado final está em
`.tmp/fed-guard-final.xml`. Os conjuntos se sobrepõem.

```powershell
python -B -m pytest tests/unit/test_federation_machine_tasks.py tests/unit/frentes/wren/test_fronts_15_18.py -q --tb=short --disable-warnings -p no:cacheprovider
python -B tests/qa/astra_federation_task.py --output .tmp/fed-guard-qa-review
```

## Continuidade da revisão após perda de recibo

Uma segunda auditoria confirmou que a revisão podia estar `SUCCEEDED` no
Control Plane receptor enquanto o journal do remetente continuava `ADMITTED`.
A reconciliação respondia `already_settled` e não recuperava essa conclusão.
Os dois testes de reprodução falharam antes da correção.

O remetente agora grava `REVIEW_DISPATCHED` antes do envio e
`REVIEW_UNCERTAIN` quando perde a resposta. Uma nova decisão sobre esse intent
exige observá-lo primeiro. A observação valida o mesmo plano, documento,
identidade de operação/WorkItem e hash do artefato. Ela conserva a Operation
de entrega que já estava `SUCCEEDED`; não reinicia tarefas nem aprova etapas.
O receptor consulta o recibo central das tarefas estruturadas mesmo quando
seu journal ainda tem uma projeção antiga. Se a revisão realmente continua
pendente, a observação informa `review_pending=true`; terminar o restante
requer uma chamada explícita de revisão com autoridade atual.

Novos casos cobrem perda da resposta, falha da projeção depois do commit
central e interrupção antes do marcador de incerteza no remetente, incluindo
recriação do gateway remetente com o mesmo journal protegido. Durante essa
recuperação, qualquer nova chamada ao gravador de decisões faz o teste falhar.

Também foi ampliado o QA real de dois processos, com opção explícita:

```powershell
python -B tests/qa/astra_federation_task.py --output .tmp/fed-review-qa --lose-review-receipt
```

Esse percurso perdeu os dois recibos, reiniciou o processo receptor depois
da execução e novamente depois da revisão, e recuperou a conclusão apenas
por reconciliação. Resultado em `.tmp/fed-review-qa/report.json`: Operation
`op-fedtask-7ba58a8cc76dee31f687f1069e2890b6`, SHA-256 do artefato
`fea8a53162162c6e514819f53b41f3dc6a25c90c5c4a631b9798d1678dab0d6f`, três
Operations, três WorkItems concluídos e mtime preservado. O teste continua
declarando que não comprova Setup instalado, Windows guest ou inferência.

Arquivos adicionais desta continuação: `gateway.py`, o teste unitário desta
frente, `tests/qa/astra_federation_task.py` e este documento.

Regressão final desta continuação: **40 testes aprovados** em
`test_federation_machine_tasks.py`, `test_federation_executor.py`,
`test_fronts_15_18.py` e `test_shell_federation.py`.
JUnit: `.tmp/fed-review-recovery.xml`. Os conjuntos anteriores se sobrepõem.

## Trabalho ainda necessário para fechar P2

1. Planejamento em linguagem natural pelo Dot/coordenador e integração visual
   de uma tarefa remota completa. Texto não aritmético sem plano continua
   indisponível; o plano explícito acima não é apresentado como um planejador.
2. Adaptar as factories próprias de Code Mode/interop/workflow à autoridade
   adicional durante os efeitos antes de habilitá-las para esse protocolo.
3. Fluxos completos de equipes: associação de identidade remota a membro,
   permissões de tarefas/conversas/dispositivos, revogação e edição concorrente
   no aplicativo. Os testes de diretório/presentation existentes não os provam.
4. Validar o mesmo percurso entre o SENTRA instalado no host e o instalado no
   Windows guest, com artefato, reinício, desconexão e recibos dessas instalações.
5. Interface explícita de rotação dos certificados legados para topologias com
   vários peers, sem trocar identidades ou apagar pareamentos automaticamente.
6. Artefatos grandes por referência paginada. O contrato atual limita o plano
   a oito etapas/16 KB e os resultados inline a 20 KB, mantém a evidência
   original central e não faz truncamento silencioso. O journal protegido tem
   limite de 2 MB; exige política de compactação/exportação para uso prolongado.

Não houve reinício de serviços produtivos, alteração da rota do Codex,
instalação/promessa de promoção, commit ou publicação nesta frente. A prova
destaca avanços verificáveis; não fecha o objetivo integral do ASTRA.
