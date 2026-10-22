# Recuperação PTY e CLI — rodada de 21/10/2026

Registro histórico: a limitação de snapshots desta rodada foi parcialmente
superada pela [rodada seguinte de checkpoints](ORCA_TERMINAL_CHECKPOINTS_2026-10-21.md).
A capacidade agora depende da disponibilidade comprovada do runtime experimental;
avaliação visual, carga real e implantação permanecem abertas.

Classificação da rodada anterior: progresso verificado em login/LAN. Esta rodada
avança o P0 de execução durável; o objetivo integral permanece aberto.

## Histórico persistente de terminal

O daemon já tinha um cache volátil e um diário de efeitos. O histórico acrescentado
agora tem testes e integração com a recuperação real do Canvas:

- Saída ANSI/Unicode protegida pelo sistema em SQLite, com esquema versionado e
  recusa de versão futura. Não há transcrições em texto puro no banco.
- Quota de 16 MiB para o conteúdo cifrado dos chunks; metadados e estruturas do
  SQLite têm orçamento adicional. Essa quota não é uma promessa de arquivo total
  de 16 MiB nem de uso total de RAM de 16 MiB.
- Fila de gravação de 4 MiB agregados, com limite de 512 KiB por sessão,
  incluindo o item em gravação. O cache de saída em memória continua limitado
  a 16 MiB agregados, separadamente da fila e do armazenamento persistente.
- A leitura ConPTY enfileira saída sem esperar disco/criptografia/consumidores.
  Excesso descarta trechos com lacunas explícitas; o maior backlog é escolhido
  antes das sessões pequenas. Os limites são de payload, não medições de RSS.
- Corrigida a leitura que podia avançar além de um trecho ainda pendente de
  gravação. Cursor observado, cursor persistido e perda conhecida são distintos.
- Depois da morte do daemon, o inventário identifica `history_restored`, com
  `process_live=false` e `restoration_creates_process=false`. O Canvas reabre o
  histórico em leitura e recusa entrada nessa sessão histórica.
- A chave original de criação continua no ledger. Repeti-la após a troca do
  runtime retorna incerteza e não inicia outro processo.
- Parada segura exige drenagem, zero processos vivos, término do leitor de saída
  e flush do histórico. Uma falha mantém o daemon disponível para observação.
- Uma falha de observação não inicia um daemon substituto enquanto a trava do
  sistema comprova que outro processo ainda é dono daquele estado.

Estado de persistência apresentado: `pending`, `saved`, `gap` e `failed`.
Gravação pendente não é exibida como falha; histórico parcial não recebe aviso
duplicado de falha de gravação. Lacuna vazia ou cursor recuado também invalida a
imagem anterior do terminal. A aba do workspace indica histórico somente leitura.

**Limite:** isso persiste/reproduz saída ANSI. Ainda não é o checkpoint completo
de emulador ORCA com buffers normal/alternativo, estado do cursor, modos,
redimensionamento, hyperlinks e restauração fiel de TUI. A capacidade
`ansi_tui_snapshots` permanece explicitamente falsa. O final não confirmado é
identificado como tal; histórico recuperado não comprova processo sobrevivente.

## Reconexão do cliente CLI ao broker

- Um registro protegido por dono/workspace/terminal guarda a credencial limitada
  do terminal. A reserva é anterior ao lançamento físico.
- A recuperação exige inventário autenticado de um daemon vivo, a mesma sessão,
  hash do token de bootstrap, PID e runtime. Um registro reservado pode ser
  concluído pela prova da criação; um registro ativo não aceita outro processo.
- O descritor entregue ao CLI contém apenas metadados e assinatura HMAC. Não
  contém a credencial nem o bearer administrativo do Canvas.
- Cada novo pedido consulta o descritor assinado, confere workspace e identidade
  de criação do processo do broker, e só então usa a porta atual. PID reutilizado
  ou descritor alterado é recusado. Falha não provoca tentativa na porta antiga.
- O transporte faz uma transmissão. Mudar o endpoint não repete um pedido cuja
  confirmação foi perdida.
- Encerrar o terminal revoga o registro e remove seu descritor. Shells de turno
  e workers não recebem recuperação ampla de credenciais; filhos dos provedores
  não herdam o arquivo/token/porta de controle do terminal anfitrião.
- O servidor continua aplicando as verificações existentes de agente, sessão,
  grafo, WorkItem e Grants. A recuperação do transporte não concede autoridade.

Compatibilidade: a extensão depende da capacidade `agent_binding_proof` do
daemon. Um daemon antigo não recebe suporte fictício nem é encerrado para ser
atualizado. O recurso permanece no caminho experimental `SENTRA_PTY_DAEMON=1`.

## Evidência desta rodada

- Lote P0/CLI: **41 testes Python passaram**. Lote de regressões móveis/recibos:
  **20 passaram**. Depois do ajuste final de leitura limitada do descritor,
  seis testes do lote P0 foram repetidos e passaram; não são seis testes únicos
  adicionais. **14 testes Node** do desktop passaram.
- Builds desktop integrado/visual em diretórios isolados concluíram.
  Build registrado: `sentra-orca-experimental-dd1a15aecf6b`.

- Ensaios reais Windows: ConPTY, DPAPI, cliente CLI em processo separado,
  reinício de broker mantendo PID, morte/reinício do daemon e recuperação apenas
  histórica. O efeito no arquivo de teste permaneceu exatamente uma vez.
- O cliente separado usa o `CanvasBridge` produtivo dentro de um processo Python.
  Isso verifica o transporte usado pelo CLI, sem chamar modelo. Não homologa um
  turno completo de agente com provedor, ferramentas e geração de modelo.
- A credencial limitada continuou recusada na rota administrativa do broker.
- Cenários de falso host/processo, mudança de scope, revogação, fila saturada,
  escrita sem proteção, disco limitado e schema futuro foram cobertos.
- Regressões móveis cobrem novamente o supervisor real, pareamento, escopo,
  revogação e reconciliação de intenções.
- Os builds do desktop continuam em `.tmp`, sem substituir estáticos de produção.
  A conferência visual permanece pendente; o bloqueio anterior da política do
  navegador não foi contornado.

## Pendências preservadas

1. Snapshots completos ANSI/TUI e homologação com aplicações de tela inteira.
2. Backpressure por consumidor, streaming retomável e medições de carga real.
3. Turno completo do SENTRA CLI com modelo, ferramentas, aprovação e reconexão.
4. Drenagem/negociação no executável instalado e atualização assinada do daemon.
5. Demais famílias de recibos, contrato de eventos, layout no host, workspace,
   ACP/worktrees, mobile físico, SSH/relay/conectores e distribuição.

O checklist integral continua em [ORCA_IMPLEMENTATION_TRACKER.md](ORCA_IMPLEMENTATION_TRACKER.md).
