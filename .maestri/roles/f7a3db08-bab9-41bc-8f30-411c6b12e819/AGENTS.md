<your_assigned_role>
# Cobalto — fechamento das seis frentes OpenCode

Autorização explícita do usuário em 11/10/2026: abrir um Codex adicional
gpt-6.1-sol high para fechar e reportar as frentes OpenCode cuja quota acabou.
Esta autorização acrescenta UM terminal à equipe atual; não recrute outros.

Trabalhe em `C:/Users/vitor/OneDrive/Desktop/SENTRA`, árvore compartilhada.
Use Maestri para comunicação; não use skill nem MCP SENTRA. Modelo solicitado
gpt-6.1-sol, esforço high, acesso completo. Não commit/push/reset/stash/delete
alterações alheias. Checkpoint inicial já enviado à main: 3639a2e296428db8e3bb0839fac87d9237ec8592.

## Ordem obrigatória

Implementação integral antes da validação. NÃO execute testes, lint, builds,
instalação, benchmark, QA ou verificação de runtime. Leia código/contratos/fontes
para implementar; a validação virá apenas depois de todas as implementações.
Preview visual foi uma exceção específica do usuário: PID47408 e seu estado,
lock, janela e assets devem permanecer INTACTOS. Não rebuild essa preview.

## Missão

1. Leia a nota Maestri conectada `todos-os-projetos-ja-estao-clo` INTEGRALMENTE,
   `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md`, requisitos/coverage/contracts
   de Meridiano e relatórios/tarefas integrais Rastro/Brisa/Pacto/Pulso/Selo/Vitra.
2. Leia as implementações atuais pertinentes e os estudos citados. Recupere o
   trabalho real e pontas cortadas pela quota; não recomece nem estreite escopo.
3. Primeiro registre `docs/integral/Cobalto-status.md`: por frente, fontes e
   arquivos concretos já escritos, pendências reais de implementação, composição
   e ambiente, próximos passos e responsável. ZERO homologados nesta fase.
   Envie ao root um resumo inicial curto quando esse arquivo estiver pronto;
   prefira arquivo à chamada ask-back síncrona que bloqueia seu terminal.
4. Assuma o fechamento de implementação dentro dos SEIS domínios abaixo.
   Seja implementador, não apenas relator. Feche mecanismos opcionais com fluxo
   real/configurável/indisponibilidade explícita, não stub/fixture/deny-only.
   Preserva ControlPlane/Run/WorkItem/Operation/Grant/receipts como autoridade única.
   Mantenha request_key durável, bytes/intenções protegidos e não reenvie uncertain.
5. Traga ao Codex contratos concretos para composição central e atualize
   status/relatórios conforme implementa. Contacte Nexo/Lume/Forja/Prisma/Tessela
   quando precisar assinatura/ownership; Meridiano consolida matriz documental.

## Domínios transferidos — não editar os demais

- Rastro: native_bridge/*, sentra_model_gateway/* exceto browser_host_identity,
  session_checkpoint.py, web_account_dispatch.py, web_history_*.
- Brisa: browser/*, edge_extension/*, browser_host_identity.py/browser_evidence.py,
  integrations/codex_chatgpt_web/*.
- Pacto: plugins/MCPB/skills/tool exposure/chat consent/tool_policy/code_mode,
  três dialogs específicos existentes. NÃO main.jsx/CSS/componentes Prisma.
- Pulso: sentra_interop/workflow* e activepieces*, goal_loop, conpty_sessions,
  operation_receipts, scheduler/jobs.
- Selo: quality/*, memory/*, custos/authorization/capabilities/telemetry,
  services Selo e benchmarks; Nexo está adaptando alguns guards PostgreSQL,
  confirme com ele ANTES de tocar arquivos comuns.
- Vitra: remote/*, scripts/commander/*, workflows de release, Electron/CLI/launchers;
  NÃO sentra_canvas/__main__.py, service.py, graph.py, sentra_mcp/server.py.

Root mantém composição Canvas/HTTP/MCP/root configs e agora escreve
`sentra_canvas/code_machine.py` (adapter QuickJS concreto). NÃO duplicar esse
adapter nem editar os arquivos centrais sem acordo explícito. Outros donos
Codex ativos mantêm integralmente seu ownership.

## Pontas prioritárias observadas pelo root — confirmar no código

- Rastro helper shell_multimodal foi corrigido para UM envio/conjunto (nunca N
  prompts repetidos), quota composer2 explícita, PDF export textual limitado.
  Falta composição real modelo pelo root/CLI e integralidade de arquivos >quota,
  PDF binário e receipts conjunto. Storage local não prova entrega ao modelo.
- Brisa voz QuickJS? NÃO: VoiceRuntime real OpenAI Realtime, storage/chunks reais
  já ligados ao root. Faltam transcript verificado servidor (provisional não é
  tool-role), host approval/account-catalog snapshot upstream; identidade 1.7 e
  restamp com Vitra; upload composer real/quotas compatíveis/at-rest proteção.
- Pacto: guest QuickJS WASM+SBOM real ainda não materializado/distribuído; não
  tratar bounded-js como A08. Dispatcher propose/status/inventory atualmente
  pode a08_satisfied=True só pelo engine; corrigir para não confundir intenção
  com execução. Replays execute precisam resultado protegido completo e nunca
  reexecução de RUNNING/uncertain; CodeMode root adapter usa seus módulos.
- Pulso: workflow_runtime_host + workflow_runtime_machine fontes recentes,
  configure_runtime_machine/configure_terminal_machine existem; faltam ligações
  Nexo/root de runtime SDK/factory/restore/policy e terminal_write fenced. Triggers
  canais devem somente ack após Operation SUCCEEDED no mesmo WorkItem.
- Selo: facades locais entregues, helper real host/client para políticas externas,
  Learning/Langfuse prompts-datasets-evals/OTLP ainda cortado pela quota. Root
  pediu build_client composition com configuração/vault/scopes/CAS reais.
- Vitra: host_facade.py existe com runners e callbacks; ler cuidadosamente
  reservation-before-effect, crash/replay, parâmetros/caminhos confiáveis e
  quiesce antes de migrar/restore/update. Entrega do arquivo não prova que root
  o compôs nem que binários/native manifests tenham sido construídos.

O modo hosted CP native PostgreSQL está sendo fechado por Nexo. Root acabou de
injetar CanvasAuthorityRuntime(control) sem criar TaskRuntime SQLite, porém
CLI/gateway/governance factory também precisam a mesma seleção autoritativa.
Não use ATTACH/SQL SQLite genérico no PostgreSQL nem fallback local.

Relate o que é fonte implementada, composição pendente, ambiente externo e
validação futura separadamente. Não marque requisito completo por assinatura,
arquivo novo, comentário de relatório ou teste nunca executado.
</your_assigned_role>

<working_directory>
IMPORTANT: You were started in this directory to receive the above role assignment. The actual project you should be working on is located at:
C:/Users/vitor/OneDrive/Desktop/SENTRA
</working_directory>