# SENTRA OS / EXEC-001 / Sprint 3x3 Fase 3

Data: 2026-10-09. Escopo exclusivo `sentra_executors/`,
`tests/unit/test_sentra_executors_*.py`. Somente **três novas** fatias;
nao reimplementa Windows UIA/Daytona/Playwright MCP da Fase 1/2.

Todas as APIs foram executadas via `ExecutorRegistry` REAL e
`PolicyDecision` tipado nos testes; callbacks, runsc e WinHCS externos
foram substituidos por fixtures declaradas. **Nenhum serviço real remoto
executado; nao chamar isto de E2E de producao.**

## 1. gVisor OCI / runsc opt-in

**Codigo:** `gvisor_runsc.py`
(`RunscLease`, `RunscBinding`, `validate_oci_bundle`,
`RunscExecutor`, `PinnedRunscRunner`, `declare_runsc_machine`).

- Contrato OCI conservador: bundle/rootfs + config.json limitados,
  sem symlink/junction, path absoluto, executavel existente pinned por
  SHA-256; manifest `ociVersion=1.0.2`; root `rootfs` readonly,
  sem hooks, mounts, annotation ou outros campos inesperados.
- Processo **apenas** `/bin/true`, uid/gid 65534, args e env fixos,
  noNewPrivileges=True, capabilities Linux vazias; seis namespaces
  pid/network/mount/ipc/uts/user, recursos pids=16, memory=128MiB.
  Sem host mount, `curl`, shell arbitrario ou outbound.
- Lease tipado `lease_id` + fence positivo + expiry monotonic:
  `lease_reader` injetado rechecado no momento do efeito.
- `inspect_bundle`: preflight no-I/O externo, digest de config.
  `state`: consulta runtime pinado, ID allowlisted.
  `create`: desabilitado por padrao no executor; requer
  `allow_create=True`, policy real em Registry + adapter,
  runner instalado em Linux, `PinnedRunscRunner(approved=True)`,
  binario fixado por SHA256 e caminho absoluto. CLI usa
  `--root=<state_root> --network=none create --bundle <bundle> <id>`.
  `cleanup` so para ID registrado por ESTE executor após create
  e `delete` apenas uma vez. Registro UNCERTAIN local bloqueia
  retry se create/delete/status falha.
- `test_sentra_executors_gvisor_phase3.py`: **subprocess real**
  `sys.executable -I -B <script_fixture_runsc.py>`, script
  criado em tmp pytest, argv OCI sob runsc sintatico; NAO e binario
  runsc real. Testes de create/state/delete, no duplicate sends,
  revogacao, path traversal, rede/exec/mount/capability escape,
  digest errado, symlinks (skip se SO negar criar), preflight e
  cleanup nao gerenciado.
- Nao houve install/runsc real; host de teste Windows, runsc
  requer Linux/isolamento e approval operacionais.

**Status:** [E2E FIXTURE SUBPROCESS] aprovado;
[E2E REAL RUNSC/OCI] bloqueado.

**P0:** host Linux apto e isolado, attestacao de binario/build
e bundle/base image confiavel, root filesystem legitimo,
protecao de rede em nivel OS, logs redigidos, fencing duravel
ControlStore, recursos do kernel via containerd/runsc atestado.

## 2. hcsshim / typed WinHCS boundary

**Codigo:** `winhcs_boundary.py`
(`HCSBinding`, `HCSBoundaryExecutor`,
`declare_winhcs_machine`).

- Requisicoes sao OperationRequest `action=status/terminate`
  e ID `sentra-lab-...` e `image_digest=sha256:...`
  exatos, registrados na Capability. Provider tipado injetado
  explicitamente oferece `status(id)`, `terminate(id)`
  e opcional `create(id,digest)`. Sem API WinHCS real auto-import.
- `create` fora de actions padrao; mesmo com capability
  exige `allow_create=True` e `approve_create(id,digest) is True`
  de callback confiavel. Ausencia de provider e platform
  diferente de win32 falham fechados; nenhuma elevacao/exec
  shell/processos pessoais. Status de retorno restrito a
  running/stopped/terminated, sem JSON arbitrario do host.
- `terminate`: consulta status antes, guarda recurso terminado,
  repeticao com novo operation_id nao executa terminate de novo.
  Falha ambigua -> UNCERTAIN no primeiro submit, no novo
  submit a chamada de efeito e bloqueada ate reconciliacao externa.
- `test_sentra_executors_hcs_phase3.py`: Registry e grant reais,
  WinHCSFixture local tipado status/create/terminate. Testa
  kill idempotente, create nao aprovado, image digest/CID spoof,
  policy denial, host nao Windows/SDK ausente, resultado malformado,
  timeout UNCERTAIN.
- **Nao executou** hcsshim em Go, containerd ou HCS Windows;
  nao houve container criado/terminado no host.

**Status:** [E2E FIXTURE HCS] aprovado;
[E2E REAL WINHCS] bloqueado.

**P0:** bridge Go assinada com identidade de Host Compute Service,
isolationType verificado (Hyper-V versus process isolation),
approvals e journal persistidos, recursos e tenant scoped, VM
descartavel e OS authorization. **Process-isolated Windows container
NAO equivale a escritorio pessoal isolado.**

## 3. WindowsAgentArena / OSWorld v2 / WindowsWorld selecionado

**Codigo:** `tk_benchmark.py` (`BenchCase`,
`TkBaseline`, `OwnTkBenchmark`, `BenchmarkStep`,
`BenchmarkReport`, `BASELINE_VERSION=sentra-tk-lab-v1`).

- Benchmark independente do framework clonado, so lab Tk
  `SENTRA-UIA-LAB-*`, acao `read_window_title`.
  Requests sao criadas pelo plano de laboratorio
  `plan_read_only_tk_lab`, passam por Registry+PolicyDecision
  reais. Nao abrem/juntam processos desktop na maquina pessoal.
- Contrato baseline `baseline_id`, versao estrita v1, case IDs
  exatos/ordenados, hash SHA-256 canonico de manifest;
  plano e ordem alterados sao rejeitados antes de executar.
- Métricas: numero de tarefas, success rate, policy denials,
  uncertain count, latencia media e individual (clock monotonic
  injetavel para fixture deterministica), replay idempotente
  sem novos efeitos, digests SHA da evidencia (nunca texto UIA
  bruto), JSON estável auditavel.
- `test_sentra_executors_benchmark_phase3.py`: fixture backend
  exclusiva janela Tk sintetica, registry e policy reais, relatorio
  deterministico, recusas, ID/versionamento de baseline, retry
  sem repeticao, backend failure e negativas de app pessoal.
- Nao importa executores/capturas destes benchmarks completos,
  nem baixa VM ou tarefa externa. O dataset/baseline e
  **proprio**, nao resultado comparavel aos placares OSWorld.

**Status:** [E2E FIXTURE Tk] aprovado;
[E2E BENCHMARK EXTERNO] nao realizado.

**P1:** VM Windows isolada com Tk filho real (testes opt-in
existentes), suites aprovadas de tarefas nao destrutivas,
baseline de varios builds, timeouts e logs assinados,
sem capturar apps pessoais.

## Matriz de upstream e licencas inspecionadas

| Clone em `third_party/` | Fonte concreta/padrao | Recorte incorporado, sem codigo copiado | Licenca de fonte |
|---|---|---|---|
| `gvisor` | `README.md` arquitetura OCI `runsc`; `runsc/cmd/create.go` flag `--bundle`, comandos `state.go`, `delete.go` | OCI manifest/CLI opt-in + validações próprias, NENHUM runsc instalado ou fonte vendorizada | Apache 2.0 (`LICENSE`) |
| `hcsshim` | `README.md` HCS/Containerd shim; `internal/hcs/system.go` CreateComputeSystem/OpenComputeSystem; `internal/hcs/v2/system.go` | Contrato provider Python fixture independente; NAO ponte WinHCS real Go | MIT (`LICENSE`) |
| `windows-agent-arena` | `README.md` BYOA `predict/reset`, VM benchmarks e UIA | Reprodutibilidade de own Tk baseline, sem VM do WAA | MIT (`LICENSE`) |
| `osworld-v2` | `README.md` releases de benchmark, trajetorias e scoring | Baseline versionado, metrica sucesso/denial (nao OSWorld real) | Apache 2.0 (`LICENSE`) |
| `windowsworld` | `README.md` etapas/checkpoints em fluxo multiapp Windows | Resultados por etapa e evidencia hash sobre Tk unico | Apache 2.0 (`LICENSE`) |

Nao copiar frameworks inteiros, nem gerar binarios desconhecidos,
nem reutilizar bibliotecas/conteudo protegidos sem compliance/
avisos NOTICE/LICENSE na futura distribuicao. Nenhum upstream foi
alterado. Cliente deve informar E2E fixture versus integracao real.

## Comando de aceite em PowerShell

```powershell
Set-Location 'C:\Users\vitor\OneDrive\Desktop\SENTRA'
$env:PYTHONDONTWRITEBYTECODE='1'
$tests=@(Get-ChildItem tests/unit -Filter 'test_sentra_executors_*.py' -File |
  Sort-Object Name | ForEach-Object {$_.FullName})
python -B -m pytest -p no:cacheprovider -q -rs -rx $tests
```

A ultima linha deste documento e a resposta de handoff devem
registrar numero exato da execucao FINAL sem inventar E2E externo.


## Evidencia FINAL executada no host autorizado (2026-10-09)

- Suite completa EXEC-001: **13 arquivos**, `214 passed, 4 skipped
  in 5.40s`, `EXECUTORS_EXIT=0`.
- Fase 3 isolada: `52 passed, 1 skipped in 1.02s`,
  `PHASE3_FOCUSED_EXIT=0`.
- O skip da Fase 3 ocorreu por ausencia de privilegio para criar
  symlink de diretorio no Windows; o controle de negacao de path
  permanece implementado, mas o teste de symlink real nao foi
  executado nesse host.
- Smoke extra de contratos/audit do nucleo (somente leitura):
  `21 passed in 0.22s`, `CORE_SMOKE_EXIT=0`.
- Host `Win32NT`; `runsc` nao encontrado no PATH. Nenhuma
  chamada WinHCS real realizada. Os comandos fixture em subprocesso
  executaram SOMENTE o Python de teste criado em tmp pytest;
  nao sao um container gVisor.
- Tres outros skips herdados de Fase 2/1: UIA/Tk real (2)
  e Playwright real (1) sob gates de VM/approval.
- Todos os arquivos proprios da Fase 3 permanecem UNTRACKED;
  sem reset/clean, sem commit. Nenhum modulo sentra_runtime,
  sentra_interop, sentra_collab, native Canvas ou auth foi editado.

Handoff ao COORDENADOR: manter estas fronteiras opt-in sem declarar
release. P0 autoridade de lease/fencing ControlStore **duravel**,
host Linux com gVisor auditado e bundle OCI completo aprovado,
HCS real somente em VM Windows descartavel com bridge Go assinada.
P1 ampliar benchmark com baseline multi-build e attestation; qualquer
expansao de GUI/desktop exige aprovacao de isolamento antes.
