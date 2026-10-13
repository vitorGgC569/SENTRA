# Root — fechamento do coordenador conversacional

Contrato em implementação, sem validação; preview preservado.

Root cria token `shell:<parent_operation_id>` somente no subprocesso atual e
confere protected queue, provider binding, Run/WorkItem/Operation/agent/process
a cada chamada. Root compõe `execute_coordinator_intent` antes de qualquer
legado. Metadata creation não inicia CLI/modelo de filhos.

Nexo (seus arquivos): necessário callback opcional
`runtime.message_capabilities(project_id,owner,dot,conversation,refs)->list[str]`
em `shell_coordinator.message_send`, passado a `_authority(required_capabilities)`.
Root devolve declarações coordinator para role coordinator, sem grants; em
admissão descendente fenced delegate/handoff devolve `model:invoke` também.
O helper coordinator precisa exigir cap presente nas requirements do parent
mesmo quando lista vazia; BoundWorkItemPolicy genérica hoje aceita vazio.
Root não editará seu arquivo sem acordo.

Root callback delegate/handoff criará conversa/message pelo MESMO cp.shell,
com contexto servidor `current_effect_context` indicando parent coordinator.
Isso cria WorkItem/Operation próprios com model:invoke declarado. Worker root
exige Grant model:invoke do ASSIGNEE filho antes de criar subprocesso; ausência
fica waiting_approval, nunca bootstrap via owner shortcut.

User bridge root expõe turn_permission_list/grant/revoke no escopo de WorkItem
e Dot canônicos. Capacidades exatas coordenador/model:invoke/web:send/web:attach,
sem owner/principal/Grant IDs enviados. Revoke seleciona capability, resolves
grants servidor. Journal request_key antes dos efeitos; contexto/proposta não
concede nada. UI explícita fica com Prisma, CLI documentação com Tessela.

Prisma: root nomes ações acima; payload list {space_id,conversation_id,work_item_id?};
grant/revoke {space_id,conversation_id,work_item_id,capabilities:[nomes exatos],
ttl_seconds?}. Grant explicitamente limitado a esse WI, retorno scoped Grant
projection, sem request auto-aprovado ou auto replay de tool/turno. Requiredcaps
do WI podem ser lidas para mostrar pendência real. Root envia schema final após
implementar; nenhum rebuild da preview.

Tessela/CLI: `SENTRA_CANVAS_AGENT_SCOPE=shell` novo server env; nesse escopo não
ensinar create_terminal/legacy bootstrap. Use
`[[CANVAS|coordinator_intent|{"kind":...,campos canônicos}]]`, persistent key
atual e retorno receipts. `context` informa Dot/conversation/space/agent e
conexões dirigidas. Children requerem sua própria admissão/Grant; request_key
uncertain não reexecuta. CanvasBridge generic JSON-value já transmite essa ação.

Pausa/cancel do próprio Run ou Dot revoga intencionalmente parent live fence;
Nexo deve registrar ACK metadata dessa transição com policy de cleanup/intenção
terminal apropriada, mantendo negação de qualquer efeito posterior.

## Fonte root materializada

`shell_actor.py::ShellActorService`: token novo com deadline/epoch volátil,
original protected queue e provider binding conferidos. Contexto canônico e
Dots dirigidos na Space atual; mutation central antes do legado. create_dot
somente metadata + conexão; delegate/handoff fazem conversation_create e
message_send sob fence, filho aguardando Grant model:invoke. Nenhum Grant criado
pelo coordenador. Worker revalida Grant/agent pause/assignee durante execução e
revoga token no finally. Shell CLI recebe token novo + SCOPE=shell.

`shell_permissions.py`: três ações acima registradas; schema single-turn real
`{project_id,space_id,conversation_id,dot_id,agent_id,work_item_id,
operation_id,work_item_state,operation_state,capabilities:[{capability,allowed,
source,has_turn_grant}],grant_created:false}`. Antes de primeira mensagem,
work_item_id:null e capabilities:[] sem cap inventada. Mutações incluem
permission_operation_id/receipt_id próprios de alteração de metadados e
permission_change_recorded/grant_created/automatic_retry:false. Envelope bridge
continua {ok,value,request_key}. Não há token/bearer nem Grant ID mutável browser.

Nexo já compôs message_capabilities e parent requiredcaps explícitas; callbacks
terminais self-pause/cancel fazem ACK metadata fenced distinto. Prisma montou UI
consumindo schema real por leitura; Tessela implementou prompt/bridge shell scope.
Fontes conectadas, sem comprovação runtime nem fechamento por relato.

### Fence de modelo no CLI — Tessela

Root revalida model:invoke antes de criar processo e a cada .25s enquanto espera;
isso não substitui o checkpoint imediatamente antes de cada HTTP do provider.
Em `_approved_provider_context`/before-call do CLI, usar autoridade configured
de UsageLedger e WorkItem canônico. Se required_capabilities inclui model:invoke,
require Grant do assignee agente, scope work_item, local_owner=False; estado
atual de Run/WI/Operation/assignee também em todo before-call/tool. Nunca aceitar
flags de bypass nem Grant herdado do coordenador. Nexo emite cápsula de estado;
identidade e DSN não vêm do renderer. Pais owner-message não ganham esta
capability por acaso; filhos a declaram via callback CP. Sem substituir check
físico por contador/post-usage; não fazer modelo/teste para validar agora.

### Pacto/A08 compostos root

`service.py` registra PACTO_ACTIONS/READS e dispatch_pacto_product; mutações
passam por ShellHostRequests central antes do callback. Não duplicar center.
`code_machine.py` evidence A08 exige cap execute + ok + a08_satisfied +
execution_verified todos explícitos e status confere receipt/hash central.
Source/wasm existence não implica execution_verified. Learning/Selo resolver
concreto continua pendência root separada, não store SQLite independente.

### Ajustes centrais exatos adicionais

Nexo: `complete_control_mutation` allowlist precisa incluir
turn_permission_grant e turn_permission_revoke. Root escreve shell_receipts
kind control_mutation + request_key e Workmetadata shell_action/request_key,
Operation audit SUCCEEDED com target_work_item_id, sem alegar execução de modelo.
Não vou editar governance.py reservado. Não trocar action por coordinate fictício.

Prisma: receipt retornado pertence a permission_operation_id, não operation_id
do turno original. UI OperationReceipt deve usar permission_operation_id,
permission_work_item_id e permission_operation_state=SUCCEEDED, e manter o
estado original no painel de trabalho. control_mutation_only/external_completion
explicit false distinguem concessão de inferência. Nenhuma alteração de preview.

Forja: leitura atual SeloHostFacade._context/veto e CentralReferences.snapshot
comparam run.workspace (PATH absoluto do Canvas) a workspace_id (ID lógico).
Precisa separar workspace_root/path host derivado de workspace_id canônico e
conferir metadata.workspace_id do WI. Learning Pacto exige ID projeto, nunca
substituir ambos por path só para passar. Constructor build_client pode receber
workspace_root host-only e atualizar guard; root fornecerá os dois canônicos.
Callback de identidade/root roles continua separado, sem issuer de Grants.
