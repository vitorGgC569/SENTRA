# SENTRA quality — gate de procedência externa

Este módulo faz uma verificação de procedência para incorporações opcionais de projetos externos. É somente leitura: não clona, instala, executa ou ativa código terceiro.

## Verificações

- Compara o manifesto de trabalho third_party/SENTRA_SOURCES_MANIFEST.json com a cópia independente sentra_quality/approved_sources.json.
- Confirma revisão Git de 40 caracteres, origem HTTPS GitHub, árvore de arquivos rastreados sem alteração e índice Git.
- Ao atestar um arquivo, rejeita caminhos que escapem do repositório ou que não pertençam ao Git, e calcula SHA256 do conteúdo.
- Falha em caso de clone, origem, revisão, manifesto ou arquivo inválidos; não há downgrade.

## Comandos, executados na raiz SENTRA

python -B -m sentra_quality verify-all
python -B -m sentra_quality verify daytona
python -B -m sentra_quality attest daytona libs/sdk-python/src/daytona/_sync/sandbox.py
python -B -m pytest -q tests/unit/test_sentra_quality_source_gate.py

## Restrições

- Os pins foram congelados do inventário de pesquisa; sua presença no arquivo approved_sources.json NÃO significa segurança auditada nem aval do usuário. Requer revisão de diff antes de virar gate de release.
- Um checkout íntegro não prova que o upstream GitHub não tenha sido comprometido.
- O status Git de arquivos rastreados não avalia objetos soltos, mas o comando attest rejeita a promoção deles.
- Este gate não executa Grype, SBOM, antivírus, análise de licenças nem testes de isolamento. Precisam de etapas próprias.
- O third_party é ignorado no Git principal. O lock independente pertence à árvore SENTRA e deverá ser rastreado para evitar que um manifesto local adulterado altere os pins sem revisão.
- Nunca tornar esses projetos dependências obrigatórias do instalador apenas porque estão clonados.
