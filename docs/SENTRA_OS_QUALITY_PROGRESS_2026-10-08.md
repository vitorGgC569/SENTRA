# SENTRA OS — quinta frente: procedência e gate de incorporação

Data: 8 outubro 2026. Implementada sem sobrescrever módulos exclusivos das outras três conversas.

## Entrega

- sentra_quality/source_gate.py — inspeção somente leitura de origem Git, commit fixado, árvore rastreada e candidato de arquivo para incorporação.
- sentra_quality/approved_sources.json — lock independente (37 pins) gerado do inventário pesquisado; é candidato a revisão/versionamento no SENTRA, NÃO aprovação humana nem certificado de segurança.
- sentra_quality/__main__.py — CLI: verify-all, verify <projeto>, attest <projeto> <arquivo>.
- sentra_quality/README.md — documentação e limitações.
- tests/unit/test_sentra_quality_source_gate.py — testes negativos de manifesto malicioso, URL inválida, Git origin divergente, checkout alterado, arquivo não rastreado, traversal e double tamper.

## Validação comprovada

- Testes locais de source gate: 24/24 passaram.
- Regressão cruzada: 101 testes Python passaram (quality, runtime, executores, interoperabilidade, boundary de colaboração, autorização e governança).
- Após os follow-ups, uma suíte complementar com os testes novos dos outros integrantes passou com 36 casos aprovados e 1 pulado (teste opcional de laboratório), e o Hocuspocus/Yjs passou com 10/10 testes Node (read-only, revogação pré-persistência, quotas e sincronização).
- CLI verify-all: 37/37 clones auditados e sem divergência de commit, origem ou arquivos rastreados.
- Arquivo Daytona libs/sdk-python/src/daytona/_sync/sandbox.py atestado por SHA256: 586ee4f6d2f0c7f4d7491adb762ebaa095bb08952c0949e7564f2c5b62a7d8bc; commit fc98a5032c04e13de737b8d4d45dd2c7e5d1291a.

## Limites e próximos gates

- Grype/SBOM/assinaturas de artefatos, dependências transitivas, vulnerabilidades, atribuições de licença e sandbox em produção NÃO foram avaliados por essa ferramenta.
- O arquivo de pins foi congelado automaticamente e ainda deve ter seu diff revisado e ser versionado antes de ser fonte confiável de um release.
- Nenhum clone é instalado, executado, copiado para o núcleo ou empacotado automaticamente.
- Não conectar o gate ao CI enquanto third_party for ignorado sem bootstrap reproduzível e origem confiável.
- A futura aprovação de um módulo precisará de prova isolada de execução, teste de autorização por operação e avaliação de atualização.

## Acompanhamento das três conversas originais

- EXEC-001 recebeu follow-up sobre ExecutorRegistry, policy, concurrent operation e UIA real com app de laboratório.
- CRIT-002 recebeu follow-up sobre ACP stdio E2E com fixture, cancelamento, autorização e ToolHive/MCP.
- CRIT-003 recebeu follow-up sobre logs temporários, atualizações Yjs, privilégios, revogação e reconexão.
- O acompanhamento automático verifica periodicamente arquivos/testes e comunica somente mudanças relevantes; falhas de envio não devem ser reenviadas cegamente.

Relatórios complementares: docs/SENTRA_OS_FINAL_GAP_ASSESSMENT.md e docs/SENTRA_OS_SPRINT_CONTRACT_V1.md.
