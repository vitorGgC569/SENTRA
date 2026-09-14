# Integração Docker e primeiro piloto — 2026-09-12

## Resultado

Docker Desktop/WSL2 Linux operacional. O controlador continua no Windows;
somente os comandos de validação selecionados executam no container.
Imagem local construída: `oma-sandbox:local`.

ID usado nas evidências:
`sha256:dca9e4e2fcb47d57769fbedb1700a8aab0edf5957b93705fc58f83a1fc8b5420`.

## Alterações desta etapa

- `workspace/docker_runner.py`: cliente no endpoint local, imagem fixada por ID,
  snapshot filtrado temporário somente leitura, usuário 65532, rede desligada,
  capacidades removidas, no-new-privileges, seccomp padrão, 1 CPU, 512 MiB,
  64 processos e `/tmp` de 256 MiB. Saída limitada pelo runner existente;
  timeout/cancelamento removem o container exato. Nenhum fallback ao host.
- `sandbox_runtime/Dockerfile` e `requirements.txt`: imagem de ferramentas;
  nunca constrói Dockerfile ou instala dependências de um candidato.
- `scripts/prepare_docker.py`: construção explícita e smoke real de isolamento.
- `orchestrator/verification.py`: executor selecionável e lista permitida de
  caminhos de patch; o candidato não pode editar o harness fixo do piloto.
- `orchestrator/engine.py`, `runtime.py`, `configuration.py`: encaminhamento do
  backend; validação de candidato, conjunto integrado e promoção usam a mesma
  imagem. Backend, imagem e política de validação são fixados na run e conferidos
  na retomada/promoção. Configuração vem do operador, não do modelo.
- `repository/gateway.py`, `registry.py`, `workspace/tool_gateway.py`: comandos
  registrados respeitam o backend configurado; leituras continuam diretas.
- `self_improvement/engine.py`: ciclo encaminha as opções ao mesmo OMA.
- `repository/policy.py`: controle Docker, imagem e harness do piloto protegidos.
- `workspace/paths.py`: `.claude` e `.docker` excluídos dos snapshots; validação
  de tipo do caminho antes de construir PureWindowsPath.
- `main.py`, `config.yaml`: `--sandbox docker`, `--sandbox-image` e doctor Docker.
  Compatibilidade: o modo host ainda exige `--trust-workspace` na CLI.
- `scripts/prepare_self_improvement.py` e
  `self_improvement/fixtures/prompt_integrity.test.cjs`: repositório mínimo novo,
  baseline executada em Docker, harness fixo e tarefa única com um reparo máximo.
- `tests/unit/test_docker_runner.py`: configuração, escopo, argv, snapshots,
  falhas, ausência de fallback, cleanup, gateway e proveniência.
- `tests/integration/test_docker_sandbox_live.py`: containers reais, timeout,
  cancelamento e demo/promoção Docker; modo host e testes diferentes recusados
  na promoção de uma run Docker.
- `pytest.ini`: coleta limitada a `tests`; referências em `Auxiliares` e artefatos
  de pesquisa não são importados pelo pytest padrão.
- `README.md`, `docs/alignment-plan.md` e este registro: instruções e limites.

## Evidências

- Smoke em container real: sem privilégios, sem escrita no código/rootfs,
  tentativa TCP externa bloqueada, credenciais de teste e socket Docker ausentes,
  CapEff zero, NoNewPrivs ativo e seccomp ativo; cleanup confirmado.
- Demo `.oma/demo-bb172443`, run `run-80547fc16347`: `CANDIDATE_READY`, 2/2 tarefas,
  gateway direto ao worker, testes reais em Docker. Modelos **roteirizados**.
- Suíte local inicial: 185 passed / 6 skipped em 104,37 s.
- Rodada focada com Docker real e integração/CLI: 22 passed em 25,26 s.
- Regressão final com `OMA_DOCKER_TESTS=1`: **189 passed / 3 skipped em 120,66 s**.
  A coleta padrão agora funciona sem incluir os repositórios auxiliares.
- Sintaxe: 149 arquivos Python, zero erros; harness JS passa em `node --check`;
  `git diff --check` sem erros (avisos de conversão CRLF do Git não são falhas).

## Piloto real: falha explícita, não autoaperfeiçoamento concluído

Repositório novo:
`.oma/self-improvement/prompt-integrity-f5a36203/repository`.
Branch local `codex/prompt-integrity`, sem remoto e sem commit automático.
Configuração do operador fica fora do repositório exposto aos workers.

Baseline real: **15 casos; 6 aprovados e 9 falhando**. O código atual aceita
truncamento em 1016 caracteres, sufixos residuais e substituição do último caractere,
pois a verificação de fill compara apenas um prefixo. O harness também exige
verificação integral antes das rotas botão/formulário/Enter.

Relay reiniciado com o token existente; doctor confirmou autenticação e dois
workers. STATUS_PROBE retornou send_available=true, sem banner, SW/CS 1.3.9.
Isso não provou envio: a primeira chamada ao planner falhou com
`SUBMIT_FAILED: tried=[no-buttons-found,form-error,enter]`, composer_len=3317,
stop_visible=false, account_cap=null. Run final `FAILED`, 0 tarefas, sem candidato.
Não há conversa concluída comprovada nesta tentativa; consumo ficou registrado
como incerto no orçamento. Nenhum retry em massa nem 200 conversas disparadas.

Auditoria da falha:
`repository/runs/prompt-integrity/handoff.json`, relativo ao diretório do piloto.

## Limites e próximo passo

O Docker removeu o bloqueio de infraestrutura. O bloqueio atual é o envio do
bridge no DOM real do ChatGPT. É necessário diagnosticar o formulário/botão antes
de repetir o piloto. Não confundir presença do composer com envio aceito.
A extensão ativa e o clone antigo `autoaperfeiçoamento` não foram alterados.

Containers reduzem risco, mas não equivalem a uma VM nem provam segurança contra
exploração do kernel. Configuração/imagem e o controlador precisam ser confiáveis;
os nomes de arquivos privados não constituem detecção universal de segredos.
Se o controlador for encerrado abruptamente ou o daemon perder conexão, a
remoção pode não ocorrer; inspecione containers `oma-check-*` individualmente.
Scripts legados não ganham isolamento automaticamente. A imagem usa intervalos
de versões no build; repetibilidade da run vem do ID da imagem já construída,
não de garantia de rebuild idêntico. Críticos e testes não provam correção total.

As restrições de execução seguem as opções documentadas em
[Docker container run](https://docs.docker.com/reference/cli/docker/container/run/)
e os limites de confiança descritos em
[Docker Engine security](https://docs.docker.com/engine/security/).
