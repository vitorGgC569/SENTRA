# Objetivo completo do produto — auditoria de conclusão

O objetivo ativo inclui todos os itens abaixo. Uma etapa concluída não reduz o
escopo. Testes simulados, testes de containers e execução cognitiva real são
evidências diferentes. Nenhum item está concluído só por existir um módulo.

| ID | Requisito | Evidência necessária | Estado inicial desta continuação |
|---|---|---|---|
| P01 | Bridge confiável | Prompt integral, confirmação de envio, UI/cota/incerteza distintas; nenhum reenvio incerto | SUBMIT_FAILED no último piloto; diagnóstico e correção em andamento |
| P02 | Melhoria real pequena | Worker real lê via gateway; patch proposto, crítica/reparo, 15 testes fixos passando e handoff | Baseline 9/15 falhas; ainda sem candidato real |
| P03 | Recuperação real repetível | Interromper/retomar, queda do relay, zero duplicação de mensagem ou aplicação parcial | Cobertura local parcial; falta prova integrada real |
| P04 | Melhoria mensurável | Baseline/candidato comparáveis, regressões, latência, consumo e incerteza identificados | Baseline e evidências presentes; comparação integrada pendente |
| P05 | Segurança operacional | Docker padrão, segredos revisados, cleanup após crash, transações duráveis | Docker opcional testado; demais fronteiras incompletas |
| P06 | Experiência operacional | Início simples, doctor, acompanhamento, pausa/cancelamento e aprovação/revisão | CLI parcial; fluxo de operação unificado pendente |
| P07 | Contexto da central | Canal estruturado para candidatos e bloqueios, entrega idempotente e rastreável | Handoff em arquivos; importação manual |
| P08 | Memória de projeto | Conhecimento validado entre runs, proveniência, validade e conflitos | Modelos de dados existem; integração pendente |
| P09 | Escala comprovada | Carga progressiva com métricas, limites e falhas; separar simulado/live | Sem validação que autorize alegar 200 conversas operacionais |
| P10 | Pesquisa competitiva | Hipóteses/experimentos/seleção por evidência integrados ao OMA; referências avaliadas | Auxiliares clonados; busca integrada/licenças pendentes |
| P11 | Distribuição/manutenção | Instalação reproduzível, versões, CI, atualização/compatibilidade verificadas | Sem entrega reproduzível completa |

Ordem de execução: estabilizar e medir P01; concluir P02/P03; integrar P04–P08;
provar P09; integrar P10; fechar P11 e repetir auditoria requisito por requisito.
Falha externa não autoriza simular um sucesso nem enfraquecer testes/políticas.

## Revisão de 13/09 — prioridade: cinco assentos persistentes

A tabela acima preserva o retrato inicial desta continuação, não uma alegação
de ausência de trabalho posterior. O usuário reportou novos pilotos e um
candidato pronto com regressão de versão; esses resultados exigem auditoria dos
artefatos antes de alterar P02 para concluído.

Nesta revisão foram corrigidos em P01/P03: pacing por mensagem (incluindo gateway),
assentos canônicos, bloqueio durável de envio incerto, falhas de disco explícitas,
proteção entre processos e validação de identidade/provider. P06 ganhou status
somente leitura das conversas. Prova local com modelos roteirizados; não houve
novos prompts reais. Detalhes em [conversas persistentes](fixed-conversations.md).

MASTER_QUEUE, limitador global entre runs, reconciliação operacional de envios
incertos e prova live repetível continuam abertos. Nenhum requisito completo
do produto deve ser marcado concluído apenas por esta revisão.

## Revisão de 28/09/2026 — fechamento de brechas de runtime/release

Esta revisão substitui, para operação atual, os estados históricos da tabela inicial:
o MCP source-tree ativo anuncia contrato compacto (77 tools nesta validação), o
runtime local passa a persistir uma autoridade `install_dir -> state_dir`, e o
startup do tunnel exige MCP autoritativo pronto antes de criar um novo processo.
MCP/relay/tunnel foram unificados no mesmo state-root durante dogfood real.

O incidente de disponibilidade foi diagnosticado até a causa upstream:
`tunnel-client` inicializava MCP/poller, porém o Control Plane respondeu
`401 token_invalidated`. O produto agora distingue esse caso como
`REAUTH_REQUIRED`; reiniciar indefinidamente não é recuperação válida.
Jobs desacoplados preservam owner de conversa, mas registram a principal
autenticada para recuperação por uma nova sessão da mesma principal.

A extensão 1.6.52/durable-r27 mantém `recovery-guard.js` autônomo, reinjeção em
tabs abertas, heartbeat da própria extensão independente do pool de controllers e
telemetria dos catches que afetam estado/recovery. A identidade é fail-closed por
version/build/source-hash. Build Windows publica estado legível em
`.tmp/build-windows-status.json`.

CI/release agora falham quando inputs críticos não estão rastreados, GitHub Actions
estão pinadas por SHA, Bun 1.4.0 é baixado do release fixo e conferido por SHA-256,
e `requirements.lock.txt` possui hashes SHA-256 em todas as 76 dependências;
instalação usa `pip --require-hashes`.

P11 ainda exige um commit/checkout limpo contendo todos os inputs já adicionados ao
índice e a execução do release E2E assinado. Docker permanece dependência externa
para execução em modo workspace/sandbox e estava indisponível no host nesta revisão.
