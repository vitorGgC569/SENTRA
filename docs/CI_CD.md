# SENTRA CI/CD — contrato de entrega (08/10/2026)

A cadeia de distribuição Windows é **fail-closed**: falha de teste,
integridade, dependência ou assinatura impede publicação. Todo arquivo
usado no build e nos testes do Canvas precisa estar **commitado**:
a CI verifica os caminhos no índice Git, não apenas no diretório local.

## Integração contínua

O workflow CI é acionado em push, PR, manualmente e semanalmente.
PRs não recebem credenciais de assinatura ou publicação. O token padrão
possui somente a permissão de leitura do repositório.

Os gates paralelos são:

- **Contract**: integridade de código-fonte, lock Python com SHA-256,
  arquivos obrigatórios rastreados, GitHub Actions fixadas por SHA,
  actionlint 1.7.12 instalado com SHA-256 e validação semântica dos workflows,
  patch upstream e empacotamento real de Canvas/CLI/Web Models.
- **Python**: três suítes obrigatórias no Windows com Python 3.12:
  tests/unit, tests/failure e tests/integration; checkout upstream fixado,
  dependências instaladas por hash e controle de regressão mypy.
- **Canvas**: sintaxe JS, física de cabos via Node, E2E com Edge real,
  Canvas WebView2 e ConPTY.
- **Web Models**: Bun 1.4.0 verificado por SHA-256, checkout upstream
  imutável, patch em worktree isolado, TypeScript, testes GPT-6/Auto/Gemini
  e compilação do renderer Electron.
- **CI required**: exige status success de todos os jobs; skipped e
  cancelled também bloqueiam o check final.

Configure o status **CI required** como verificação obrigatória da branch
padrão nas regras do GitHub. Não use credenciais reais de ChatGPT em PRs:
inferência com contas externas depende de autenticação fora da CI.

## Entrega contínua

O release Windows com tag vX.Y.Z exige igualdade com PRODUCT_VERSION.
Compila os executáveis, incluindo sentra-canvas.exe e sentra-cli.exe,
publica o payload Web Models Electron com patch pinado, exige certificado
Authenticode em tags estáveis, assina, constrói Setup + MSI + update ZIP,
CycloneDX SBOM, release-manifest.json e SHA256SUMS.txt, testa executáveis
e verifica instalação e desinstalação reais.

O job de build não tem permissão de escrita no GitHub. Um job separado,
publish-release, depende inteiramente do sucesso do build, baixa somente
o artifact daquela execução, revalida checksums e publica a release com
permissões temporárias contents: write e actions: read. Uma release já
existente não é sobrescrita. Workflow dispatch produz apenas candidato.

GitHub Secrets obrigatórios para a tag estável:
WINDOWS_CERTIFICATE_B64 e WINDOWS_CERTIFICATE_PASSWORD.
Opcional: WINDOWS_TIMESTAMP_URL. Nunca submeta PFX ou credenciais
de conta, Browser Host, OpenAI Platform ou runtime ao Git.

## Reprodução Windows

Execute no repositório, com dependências instaladas:

    python -B scripts/ci/verify_release_contract.py --verify-upstream
    python -B -m pytest -q tests/unit tests/failure tests/integration
    python -B scripts/check_mypy_baseline.py
    ./scripts/ci/test_canvas.ps1 -RequireEdge
    ./scripts/ci/test_web_models.ps1 -Bun ".sentra/toolchain/node_modules/bun/bin/bun.exe"

Para verificar os caminhos no índice Git, antes de publicar:

    python -B scripts/ci/verify_release_contract.py --require-tracked

O repositório possui modificações ainda não commitadas, que devem passar
por revisão e commit antes de esperar um workflow GitHub verde.
A configuração da branch protection, os certificados Authenticode e uma
execução verde da release no GitHub dependem de ações da conta proprietária.

## Critério de fechamento do produto

Ter CI/CD não prova, isoladamente, maturidade integral. Considerar como
release candidate somente após execução verde no GitHub, assinatura e
instalação em ambiente limpo, teste de upgrade/rollback, verificação de
segurança, integridade dos artefatos, controle de versões e critérios
funcionais ainda abertos. A esteira não implementa por si só sandbox/ACL
granular, isolamento de processos, emulação VT completa, reattachment
de terminais ou integração integral de governança OMA. Acessos Web
explícitos GPT-6/High ainda dependem de uma conta com permissões reais.

CI e builds isolados não devem reiniciar o Canvas principal com seus
terminais ativos.
