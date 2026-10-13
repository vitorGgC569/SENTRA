# Tessela — CLI composta ao contrato coordenador root

Fontes ajustadas; nenhum teste/build/install/lint/QA/rebuild/preview executado.
Referência: Codex-coordinator-contract.md. Relato Vitra/CLI completo e pendências
reais: Tessela-fechamento.md. Comunicação por arquivo, sem ask-back.

Root injeta SENTRA_CANVAS_AGENT_SCOPE=shell no subprocesso do Dot, junto do
token agent_control já bound ao parent Operation e à cápsula CP Nexo. CLI não
cria token, autoridade ou Grant e não propaga token Canvas aos filhos de
gateway/browser (authority_environment.py).

agent.py: prompt/context shell, identidades canônicas Dot/conversation/Space/
agent/conexões dirigidas via CANVAS context. Não ensina bootstrap legado;
directives com efeito local não contornam as máquinas/coordenador admitidos.
Goal mutations legadas ficam negadas no scope shell. History/goal/continuation
usam CP configured, sem instanciar store SQLite paralelo em hosted.

CanvasBridge.execute(raw_args,request_key):
`[[CANVAS|coordinator_intent|{...}]]` envia POST /api/agent/control com
{action:"coordinator_intent",workspace:<contexto existente>,
value:<JSON canônico>,request_key:<identidade persistente do tool call>}.
JSON bounded4000; kinds create_dot/create_team/connect/delegate/handoff/pause/
resume/cancel/reassign/pause_dot/resume_dot. Schema, alvos, tokens, parent caps,
grants e compose pertencem root/Nexo. Criação/dispatch legado é recusado nesse
scope. Retorno do servidor é preservado; ACK/metadata não vira conclusão externa.
PENDING/UNCERTAIN não autoriza nova identidade para repetir o efeito.

ShellBridge/operator /shell expõe turn_permission_list/grant/revoke.
Envelope usa project_id,space_id,conversation_id,request_key e extra
{work_item_id?,capabilities?,ttl_seconds?}; mutations exigem WorkItem e chave
estável. work_item_id permitido somente nesse conjunto; owner/principal/Grant/
Operation ID não vem do CLI. Mesmo journal protegido antes de POST; nunca
autorreplay de Grant/tool/turn. Não há directive de concessão ao modelo.
`/coordinate` exige JSON estruturado, sem interpretar prosa como autorização.

Pendências root: tokens shell:<parent_op>, fila/process binding e parent live
guards, execute_coordinator_intent antes de legado, intents/caps/Grant UI e
child admission model:invoke próprios. Nexo mantém message_capabilities e
exigência explícita de capability nas requirements do parent. Prisma mantém UI
scoped. Esses pontos não foram editados por Tessela nem declarados homologados.
