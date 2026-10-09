# SENTRA MCP — auditoria comparativa com Remote Desktop Commander

Data da revisão: 2026-09-28.

Este documento substitui o snapshot de 2026-09-20. A comparação separa a superfície
MCP local, a camada remota e recursos deliberadamente fail-closed; uma capability
existir no código não significa que ela esteja habilitada na superfície padrão.

## Estado validado nesta revisão

O MCP source-tree ativo anunciou protocolo `2026-07-28`, capability v4 e 77 tools
nas superfícies padrão `core + developer + browser`. As superfícies
`oma`, `remote` e `admin` continuam disponíveis, mas não são expostas por padrão.

| Área | Estado atual do SENTRA |
|---|---|
| filesystem | leitura, escrita, edição cirúrgica, move/delete, roots allowlisted |
| processos | sessões persistentes, output/stdin incremental, PID managed/owned e limites |
| repository | leitura, busca, diff, testes registrados e workspaces aprovados |
| documentos | inspeção/leitura e `sentra_write_pdf` |
| browser | Edge/Playwright fail-closed; Edge principal sem criação arbitrária de tabs |
| execução durável | Runs/Operations, idempotência, eventos, checkpoints, cancel/reconcile |
| jobs | detached, BUILD exclusivo por workspace, recuperação por principal autenticada |
| Context Bus | cursor por scanned sequence; mensagens filtradas não travam progresso |
| governança | autorização, budgets, work items, routines, secrets, plugins e execution workspaces |
| remoto | pairing/device tokens, ACL por tool, leases, revoke/rotate, contratos e estado UNCERTAIN |
| atualização | HTTPS/loopback, SHA-256, ZIP traversal guard, Authenticode e rollback |

## Diferenças deliberadas em relação ao Commander

O SENTRA não tenta reproduzir permissividade de um terminal remoto genérico. Processos
e filesystem continuam presos a workspace/política; kill só alcança processos
gerenciados; non-loopback MCP exige configuração OAuth; grants remotos são auditáveis.
Wildcards de ACL continuam suportados, mas dispositivos que usam `*` ou prefixos
wildcard são marcados como `broad_acl=true`.

A camada remota deixou de ser “futura”: ela existe como subsistema separado do MCP
local e é surface-gated. Isso preserva a fronteira de confiança em vez de transformar
o MCP local em um atalho administrativo.

## Incidente de tunnel de 28/09

Durante dogfood real, MCP, relay e tunnel chegaram a usar state-roots diferentes.
O runtime agora persiste uma autoridade `install_dir -> state_dir` fora do próprio
state-root, valida instance-id/token antes de adotar serviços e mantém singleton
global por Tunnel ID.

Também foi observado um tunnel com processo local saudável enquanto o Control Plane
respondia `401 token_invalidated`. O produto passa a classificar isso como
`REAUTH_REQUIRED`; o watchdog não reinicia indefinidamente uma credencial revogada.
Falhas transitórias recebem grace period e backoff antes de restart do tunnel, e o
startup aguarda MCP autoritativo antes de criar um novo tunnel-client.

## Edge e observabilidade

A extensão usa identidade version/build/source-hash, heartbeat próprio independente
de controllers e `recovery-guard.js` autônomo. Assim, `workers_online=[]` pode
representar extensão saudável e ociosa. Catches que afetam persistência, reload,
reinjeção ou alarms reportam telemetria; probes/cleanup puramente best-effort podem
continuar fail-soft.

## Release e supply-chain

CI e release usam Actions pinadas por commit SHA, exigem inputs críticos rastreados,
instalam Python com `--require-hashes`, usam um lock com hashes SHA-256 e baixam
Bun 1.4.0 por URL de release fixa com SHA-256 verificado. Builds Windows publicam
estado não sensível em `.tmp/build-windows-status.json` além do lock privado.

## Pendências que ainda exigem evidência externa

Não marcar produto como integralmente fechado apenas pelo source. Ainda são gates:
checkout/commit limpo contendo todos os inputs staged, release E2E assinado, dogfood
live da extensão 1.6.52 no Edge principal e execução sandbox quando Docker estiver
disponível. Falha externa não deve ser convertida em sucesso simulado.
