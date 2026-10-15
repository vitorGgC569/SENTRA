# SENTRA — intervenção P0 de disponibilidade (14/10/2026)

## Resultado factual e limites

- Diagnóstico executado no checkout do host OGrandeOxta, pasta Desktop/SENTRA, sem reset, commit, push ou alterações em grants/workitems.
- Gateway inicial (PID 12060) respondia ao healthz, mas o watchdog estava IDLE. Dois reinícios controlados foram realizados SOMENTE quando os contadores de turnos e leases eram zero, usando drain e resume. O último gateway ativo depois das correções é PID 35996; supervisão HEALTHY, healthz HTTP 200, upstream (Web Models v6.1.1) continua ativo e não foi reiniciado.
- O Canvas foi recompilado e seu broker reiniciado por sentra_canvas.native_refresh.apply_all. Último broker observado PID 35876, /api/health ok, frontend_stale=False, hashes de desktop.js, desktop.css e bootstrap.js conferem com manifest.json. O WebView aberto precisa de reload para mostrar o novo bundle.
- **A falha do provedor remoto não está resolvida.** No último conjunto de 5.000 registros de auditoria do gateway, os encaminhamentos tiveram HTTP 200: 27; HTTP 503: 411; HTTP 502: 3; HTTP 507: 3 e um status desconhecido. O relatório sanitizado da janela de 30 minutos examinada indicou 61 respostas, 59x503, 1x502, 1x200 (98,4% 5xx). Amostras de 503 tinham header CF-Ray ...-GRU repassado pelo upstream local (:17841) após o gateway receber e encaminhar a solicitação. A origem exata dentro da infraestrutura Cloudflare/provedor não é observável pelo host.
- A saúde de /healthz é diferente da saúde de uma inferência. O novo campo `inference_health` contém estado OBSERVING/HEALTHY/DEGRADED, contagens de 5xx nos últimos cinco minutos e percentual. Ele começa OBSERVING após restart até haver cinco amostras e não desencadeia replay.
- Gateway envia `X-SENTRA-Request-ID` nos encaminhamentos para vincular cliente, `model.gateway.received`, `model.gateway.upstream_5xx` (com CF-Ray validado) e `model.gateway.forwarded`. Não salva conteúdo, cookies, prompts ou bearer do usuário nesta trilha.
- Envio de prompt e operações UNCERTAIN jamais são automaticamente repetidos; enviar novamente requer reconciliação explícita e autoridade original.

## Arquivos alterados para P0/P1 parcial

- sentra_model_gateway/gateway.py — watchdog para CLI; backlog de 64; cabeçalho Request ID; correlação com CF-Ray e fases de erros; contador de inferências independente de liveness.
- sentra_remote/desktop.py — inicia/encerra watchdog mesmo quando o gateway é criado pela interface, mostra degradacão de inferências separadamente.
- sentra_canvas/desktop_ui/src/experience/cadencia/stream-beat.js — preserva conteúdo em espera/confirmação/reconexão.
- sentra_canvas/desktop_ui/src/shell-live-feed.js — reconciliação da prévia por identidade, sem vazar texto entre operações nem declarar sucesso.
- sentra_canvas/desktop_ui/src/shell-conversation.jsx — mantém prévia ao perder um GET, limpa ao trocar de conversa; polling de histórico ativo aumentado de 500 para 1400ms; prévia permanece 350ms.
- sentra_canvas/shell_live.py — revisão de conteúdo para distinguir uma nova rodada de geração da perda temporária da prévia.
- sentra_canvas/desktop_ui/scripts/materialize.mjs — manifesto de bundle escrito por substituição atômica e retries limitados de bloqueio temporário do Windows/OneDrive.
- scripts/gateway_503_report.py — relatório somente leitura e sanitizado da auditoria.
- .sentra/recovery/apply-gateway-p0-20261014.ps1 — roteiro de restart que aborta se houver turno/lease ativo. **Não executar sem verificar o estado atual**.

## Verificações executadas

- Gateway: 64 testes Python aprovados após alterações de telemetria (inclui testes de erro e SSE).
- Fault injection isolada: 1 teste adicional aprovado; produtor fecha SSE após delta sem evento terminal, cliente não vê confirmação e gateway não repete POST. Não foi executado um kill real do navegador/VM em operação de usuário.
- Gates existentes de release/upgrade: 22 testes Python aprovados, sem gerar novo instalador ou assinar release.
- Interface: 22 testes JS aprovados antes de alterar polling; os casos de recuperação e nova rodada foram incluídos.
- Prévia Python: 10 testes específicos aprovados, incluindo mudança de rodada na mesma operação.
- Teste sintético local com 10 streams SSE concorrentes: 10/10, p50=120ms, máximo/p95 de amostra=151ms; **não é medição do provedor remoto e não prova disponibilidade de 10 inferências reais**.
- Build Vite, materialização do frontend e verificação SHA256 do bundle concluídos.
- Últimos /healthz verificados: gateway status ok, ready true, supervisor HEALTHY, inference_health OBSERVING (sem novas amostras desde segundo restart); upstream accepting_turns true.
- Instalação distribuída ainda não foi atualizada: native_executable_stale=True, installed_version_changed=False.

## Comando de diagnóstico sem reenvio

Na raiz do checkout:

```powershell
python scripts/gateway_503_report.py --since-minutes 30 --error-limit 12
```

O diagnóstico não gera prompts nem aciona modelos. Usar `X-SENTRA-Request-ID` e `cf-ray` como evidência de suporte de upstream.

## Riscos e pendências por prioridade

1. **Ainda crítico** — erro 502/503 vem do Web Models/Cloudflare no caminho de inferência mesmo quando healthz está verde. Examinar o runtime Web Models e infraestrutura do provedor, comparar conexão direta e sessão, não transformar falha remota em sucesso local e não repetir envios incertos. Considerar procedimento de suporte com IDs/cf-ray e horários UTC.
2. **P0 ainda não homologado** — testes de interrupção real do produtor, navegador e host com turnos ativos, incluindo comprovação de não duplicação em incidente de produção. Não realizar kills com operações de usuário em andamento.
3. **P1 parcial** — reduzimos polling de snapshots de histórico, mas SSE multiplexado com cursor durável, eventos ordenados e recuperação de lacunas ainda não foram implementados. Não declarar metas p95<=300ms de exibição sem medições reais.
4. **P1 pendente** — testes de 10 inferências reais e 20 clientes de equipe, sujeito a rate limits e disponibilidade dos modelos.
5. **P1 pendente** — gerar um instalador novo e validar instalação limpa/assinatura, atualização/rollback e proveniência dos artefatos; fonte local atualizada não substitui Setup.
6. **P2/P3 pendentes** — Federation geral, permissões entre instalações, conectores reais e demais frentes do plano Astra.

## Proteções preservadas

- Processo Web Models (porta 17841), MCP, túnel, CLI, contas e VMs permaneceram ativos; sem modificação de tokens ou políticas.
- Reinício de gateway foi bloqueado em uma tentativa por turno ativo, e só executado quando comprovadamente ocioso.
- Não houve reenvio de solicitação 503 ou de turnos UNCERTAIN.
- O checkout compartilhado permaneceu sem commit/reset/push.
