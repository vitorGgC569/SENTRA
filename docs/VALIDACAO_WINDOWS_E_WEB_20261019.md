# Validação de Windows e modelos Web — 19/10/2026

O SENTRA continua em desenvolvimento. A validação é vinculada à versão e ao
cenário executado, e não à presença de modelos em um catálogo.

## Resultados observados

| Componente e cenário | Resultado |
| --- | --- |
| Setup r16 em Windows limpo, em máquina virtual | Instalação dos 14 executáveis, interfaces Setup/Desktop, atalhos e ciclo de serviços verificados. |
| Firefox com extensão privada assinada 0.1.2, no mesmo teste | Instalação persistente, Native Messaging e operação DOM de teste verificados. |
| Atualização r16 no usuário Windows existente | Configuração protegida preservada e conexão existente restabelecida. |
| Atualização do componente Web r18 sobre os executáveis nativos r16 | Arquivos atualizados conferidos; os 14 executáveis nativos foram preservados. |
| GPT-6 Instant (Web) no Codex, com o conector SENTRA | Listagem do projeto retornou ao Codex em aproximadamente 38 segundos. |
| Continuidade no mesmo chat | Listagem de `root:1/docs` retornou ao Codex em aproximadamente 18 segundos. |
| Leitura limitada no mesmo chat | Leitura de 30 linhas de `root:1/README.md` e explicação do projeto retornaram ao Codex em aproximadamente 27 segundos. |

Os testes reais de Web acima solicitaram apenas leitura. Não validam escrita,
execução de comandos, todas as contas, todos os modelos do catálogo nem rollback
integral. A validação de um novo instalador completo é registrada separadamente,
com o hash desse artefato; o resultado do r16 não é transferido a outro pacote.

## Uso do conector

Use o nome **SENTRA**. O cadastro deve reutilizar o túnel e a configuração existentes.
A sessão do ChatGPT precisa estar autenticada e permitir o uso da ferramenta.
Para um teste de leitura, especifique o workspace, o arquivo e o limite, por exemplo:

> Use SENTRA para ler somente as primeiras 30 linhas de README.md no workspace
> root:1 e explicar a finalidade do projeto. Não altere arquivos.

Uma tentativa anterior de leitura foi recusada pelas configurações de segurança
do ChatGPT. O pedido limitado acima foi aceito depois, sem mudança de permissões.
A causa exata daquela recusa não foi confirmada; isso não representa desativação
das revisões de segurança para chamadas futuras.

## Conversas antigas

Uma conversa antiga do navegador não pôde ser reaberta durante o teste. O envio
foi interrompido antes de submeter uma nova tarefa. A validação r18 foi concluída
em uma cópia isolada do chat do Codex, com uma nova conversa do navegador.
Se o histórico externo de uma conversa não estiver mais disponível, inicie um
novo chat e informe novamente a tarefa. Não force a repetição de uma solicitação
cujo envio ou resultado esteja incerto.

## Evidências da entrega

Os relatórios de compilação, hashes, instalação e testes reais acompanham a pasta
de saída da entrega. Eles indicam o pacote testado e distinguem instalação limpa,
atualização no usuário existente e operações reais com a conta conectada.
Relatórios anteriores continuam preservados como histórico.

## Nova verificação no usuário existente — 20/10/2026

Após reabrir SENTRA Desktop, Codex Web GPT e autenticar a conta, o modelo
GPT-6 Instant (Web) concluiu uma leitura de 20 linhas do `root:1/README.md`
em aproximadamente 34 segundos. No mesmo chat, uma listagem sem recursão de
cinco itens de `root:1/docs` retornou em aproximadamente 18 segundos.
Ambas as respostas chegaram ao Codex, com conclusão e transporte confirmados
pelo gateway. Nenhum arquivo foi alterado por esses testes.

O Setup inicialmente recusou a interface porque o Chromium havia criado um
`debug.log` na pasta `sentra-electron`: os 79 arquivos declarados no manifesto
estavam presentes e tinham os hashes esperados, mas o inventário encontrou
esse arquivo extra. O log foi preservado fora da instalação; a verificação
estrita de integridade permaneceu habilitada. Depois disso, a verificação
executada pelo usuário avançou para a etapa de conexão. Esta recuperação
pontual não constitui uma correção permanente da localização dos logs.

Uma tentativa de retomar o chat antigo retornou conflito de identidade e não
foi repetida automaticamente. Os dois testes bem-sucedidos acima usaram uma
cópia nova do chat. A validação continua restrita a leitura e listagem no
usuário existente; o pacote completo r18 não foi homologado em Windows limpo,
e a troca dos executáveis nativos por esse instalador não foi comprovada.
