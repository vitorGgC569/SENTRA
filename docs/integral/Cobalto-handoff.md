# Cobalto — handoff após redistribuição Codex

11/10/2026. `REDISTRIBUICAO_CODEX.md` supera o takeover dos seis domínios.
Cobalto fica **Brisa + Rastro**. Nenhuma validação executada; preview intacta.

## Prisma / Pacto — arquivo já editado

`sentra_code_mode/dispatcher.py` foi o ÚNICO arquivo de um domínio agora
transferido alterado por Cobalto. Não editei runtime guest, composição,
CodeMachine root, dialogs, nem os arquivos de Pulso/Selo/Vitra.

Mudanças entregues em fonte (sem execução):
- Propose retorna `a08_satisfied=False`; status verifica estado SUCCEEDED;
  inventory deixa flag falsa e expõe execution_state, evitando contar engine
  como execução A08. Docstring bounded-js agora explicitamente interim.
- Tabela `code_mode_execution_bindings`: owner/operation/request_key/intent
  imutáveis, resultado completo protegido por `_encode` da autoridade existente.
- Reserva de binding + execution RUNNING + proposta RUNNING na MESMA
  transação ANTES de iniciar guest. Namespace lock `BEGIN IMMEDIATE` usa o
  dialeto explícito Nexo no PG; não introduz ATTACH/fallback.
- Replay RUNNING/outro estado não terminal retorna UNCERTAIN, nunca reexecuta.
  Proposal já iniciada não admite outra execução com key nova.
- Replay SUCCEEDED recupera resultado completo `_decode`, revalida
  owner/proposal/operation/digest/tamanho. Legado sem resultado protegido
  falha com reconciliação explícita, não reexecução.
- `_finish_execution` persiste protected_result e SUCCEEDED na mesma
  transação; watchdog timeout coloca cancel_flag antes de abandonar a thread.

Pontas abertas para Prisma fechar por leitura/implementação:
- `status._a08_execution` ainda aceita linhas SUCCEEDED históricas com digest
  sem consultar resultado protegido; alinhar com `_receipt` antes de afirmar
  execução verificada. Inventory conservador sempre false pode ser enriquecido.
- `dispatch(propose+execute)` ainda cria proposal nova a cada chamada; replay
  global operation/key é recusado pelo binding, mas não retorna resultado via
  lookup antes da proposta. Root usa `CanvasCodeMachine` próprio: preservar.
- `_finish_execution` fica após o bloco try; falha de persistência deve deixar
  RUNNING/UNCERTAIN e jamais autorizar replay. Rever sem esconder esse estado.
- Guest/wasmtime/distribuição seguem pendências reais; não construídos.
- Nova tabela DDL não substitui testes concorrência/cancel/replay futuros.

## Lume / Pulso, Forja / Selo, Tessela / Vitra

Nenhum código desses três domínios alterado. Leituras de
workflow_runtime_host/runtime_machine/channel_triggers/conpty,
quality/langfuse_eval e remote/host_facade ocorreram, sem execução.
Observações para donos: facade Vitra atualmente executa `_mutate` antes de
selar journal e contém `repair` que retorna sucesso sem runner real;
Pulso runtime_host/triggers ainda abrem SQLite de projeção diretamente;
Selo eval local não prova cliente/export Langfuse. Conferir no código atual.

## Brisa / Rastro permanecem Cobalto

Arquivos já alterados: `browser/attachments.py`, `browser/voice.py`;
novos `browser/protected_assets.py`, `browser/realtime_sideband.py`.
São implementações EM ANDAMENTO: completar scope/checkpoints/reserva e
transcript/sideband antes de entregar composição final ao root/Prisma.
`docs/integral/Cobalto-status.md` guarda baseline inicial das seis frentes;
suas quatro frentes transferidas agora são responsabilidade dos novos donos.
CLI/anexos: coordenar `sentra_cli/*` com Tessela, sem editar seus arquivos.
