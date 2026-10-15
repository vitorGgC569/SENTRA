# Nimbus — frentes 11 e 12

Data da rodada: 2026-10-12. Checkout: `C:\Users\vitor\OneDrive\Desktop\SENTRA`.
Nenhum commit, push, reset, clean ou rebase. Nenhum VM, VDI, Dot, conversa, `.sentra` ou `.oma` foi apagado. `virtualbox_*.py` não foi editado. Relay, backend, Edge e VMs não foram reiniciados. A suíte inteira e `npm run build` não rodaram.

## Frente 11 — memória, plano e contexto do Dot

Memória, plano e contexto ficam gravados por `owner` + `dot_id` e voltam quando outro processo abre o mesmo diretório.

- `memory/dot_scope.py`: SQLite `dot_memory.sqlite3`. Chave `(owner, dot_id, kind, key)` com `kind` em `memory`, `plan` e `context`. CAS por revisão, SHA-256 do corpo, teto de 64 KiB. Plano e contexto têm campos fechados. O retorno traz `authorizes_effects: false`.
- `orchestrator/memory.py`: `DotSessionMemory` grava plano, contexto e um snapshot da sessão (mensagens recentes, tarefas, conhecimento do run e cache lexical). Um segundo objeto no mesmo diretório restaura só aquele Dot.
- `orchestrator/program_memory.py`: `dot_id` grava ADR, lições e candidatos em `memory/dots/<dot_id>/`. O store do workspace não lê essa pasta. Outro Dot não vê os registros.
- `memory/protected_store.py`: `dot_id` opcional entra na chave. Sem `dot_id`, a chave antiga por WorkItem permanece.

Nada disso cria Run, Grant, lease ou efeito.

## Frente 12 — CPU e RAM sem travar a máquina

Medição e admissão. Nenhum caminho mata processo, muda prioridade, desliga VM ou chama `modifyvm` / `controlvm`.

- `orchestrator/resources.py`: classifica canvas, terminal e VM. `ResourceCeiling` deixa reserva de RAM (padrão 2048 MB) e teto de RAM/CPU abaixo de 100%. `evaluate_admission` recusa trabalho que comeria a reserva, o teto da superfície ou a CPU já quente. A sonda ao vivo abre só imagens de VM, canvas e do host do Windows Terminal. Não abre cada `python.exe`, `powershell.exe`, `cmd.exe` ou `conhost.exe`.
- `orchestrator/budgets.py`: `HostResourceBudget` reserva RAM e CPU por Dot e superfície. A reserva sobrevive num arquivo. Depois de um crash ela continua contando, para não admitir a mesma RAM duas vezes. O snapshot de um Dot não lista o id de outro Dot.
- `orchestrator/rate_governor.py`: `HostResourceGovernor.observe` devolve uma espera de no máximo 2 segundos e não dorme. Um valor recarregado do disco também fica limitado a 2 segundos.
- `orchestrator/compute_policy.py`: `clamp_for_pressure` impede a entrada de validadores extras enquanto a RAM ou a CPU do host está quente. A política original não é alterada.
- `sentra_executors/vm_resources.py`: `apply_authorized_cap` lê o contexto central, chama `checkpoint`, confere capability `vm:manage`, ação `resource.cap`, owner, UUID, estado e carga. Sem `controlled_proof` e `workload_inspected` no intent reservado, não chama o cliente. Com essa prova, chama `VirtualBoxClient.run("controlvm", ..., "cpuexecutioncap")` e grava recibo e rollback. Quatro strings não autorizam. Este teste usa `runner` injetado, não o `VBoxManage` do host.
- `orchestrator/memory.py`: `LiveDotSession` grava e recarrega plano, contexto e sessão. Um processo novo no mesmo diretório recupera a sessão.
- `orchestrator/resources.py`: `admit_surface` liga a medição ao orçamento. `attribute_processes` atribui canvas, terminal e VM, inclusive o UUID que já estiver na linha de comando. A sonda lê no máximo 32 shells além das imagens de VM e canvas.

## Teste unitário executado agora

Comando, na raiz do checkout:

```
python -m pytest tests/unit/frentes/nimbus tests/unit/test_program_memory.py tests/unit/test_compute_policy.py tests/unit/test_budget_admission.py tests/unit/test_resource_registry.py tests/test_memory_and_cache.py tests/unit/test_closeout_invariants.py -q --tb=short
```

Resultado: **57 passed in 9.65 s**.

Os 14 testes novos estão em `tests/unit/frentes/nimbus/`. Cobrem reabertura do store, isolamento entre Dots, revisão, plano/contexto/sessão, orçamento persistente, admissão que recusa excesso, governador que não dorme, congelamento de escalação e cliente falso de VM em que toda chamada `metrics` vai com `physical=False`. Os outros 43 são testes já existentes dos módulos tocados; também passaram.

Isso não é prova física de reinício do aplicativo nem de mudança de uma VM registrada.

## Prova física contemporânea

Leitura só de host, depois dos testes, por `read_host_snapshot()`. Não houve `VBoxManage`, não houve mudança de prioridade e não houve término de processo.

- RAM do host: 31853 MB no total, 6559 MB disponíveis, carga 79%, 12 CPUs.
- `cpu_percent` da amostra: nulo. A medição de percentual de CPU exigiria duas amostras com espera; a biblioteca não dorme para fabricar esse número.
- Processos abertos pela sonda: 29. Classificados como VM: 10, com cerca de 351,9 MB de working set somados e 4975 s de tempo de CPU acumulado. Canvas classificado: 0. Terminal classificado: 0.

Os 10 processos de VM foram reconhecidos pelo nome da imagem no host. Essa leitura não confere UUID, marcador, Dot ou `showvminfo`. Não é telemetria do convidado.

## O que não está homologado

- Aplicar execution cap, memória ou CPU numa VM registrada. O plano é recomendação. Nenhuma VM real foi modificada.
- `metrics query` contra as VMs Debian deste host. O teste usou cliente falso. Falha de métrica no cliente falso não vira segunda tentativa física.
- Atribuir RSS do Canvas nesta máquina. A amostra não viu um `electron.exe` cujo caminho contivesse SENTRA.
- Atribuir terminais SENTRA nesta máquina. Sem linha de comando, `python.exe` e `powershell.exe` ficam de fora da sonda de propósito.
- Percentual instantâneo de CPU do host.
- Reinício do processo do Canvas ou do desktop que o usuário abre. A sobrevivência foi um segundo objeto Python no mesmo SQLite ou JSON.
- Efeito real com Run, WorkItem, Operation, Grant e recibo. Estes módulos não emitem esse efeito e marcam `authorizes_effects: false`.
- A amostra de 79% de RAM não homologa que o restante do SENTRA deixe de pressionar a máquina.
