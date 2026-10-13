# SENTRA — Delegado: ciclo de vida seguro dos Dots (2026-10-12)

## Contexto, escopo e segurança

- Execução real via Desktop Commander no dispositivo **OGrandeOxta**, branch `main`, projeto `C:\Users\vitor\OneDrive\Desktop\SENTRA`.
- `git status --short` foi inspecionado antes da edição: checkout compartilhado com muitas modificações rastreadas e arquivos ainda não rastreados. Os arquivos da frente já existiam como não rastreados. Não houve reset, checkout, clean, commit, push ou rebase.
- Não foram reiniciados o aplicativo, relay, Edge ou VirtualBox. Nenhum Dot real, conversa real, VM ou VDI foi excluído. Os testes criaram somente projetos isolados em diretórios temporários, com uma reserva VM sintética e um vínculo remoto sintético.
- Nenhum segredo foi lido para este relatório ou incluído nele.
- O esforço `High` no seletor do modelo não é verificável por esta execução; o Desktop Commander efetivamente estava online.

## Arquivos da frente alterados

1. `sentra_canvas/shell_dot_retirement.py` (novo): inventário com escopo owner/projeto/Space/root; arquivos locais e registros de intenções persistentes; idempotência e recibos.
2. `sentra_canvas/shell_dot_lifecycle.py`: encaminha preflight para o inventário, expõe `dot_archive_local` e `dot_restore_local`, inclui `archived_local` nas preferências e impede mover Dots entre grupos ativo/arquivado.
3. `sentra_canvas/desktop_ui/src/shell-dot-context-menu.jsx`: pré-verificação expandida, confirmação digitada, arquivamento local/restauração com recibo e avisos explícitos sobre a retenção.
4. `sentra_canvas/desktop_ui/src/shell-app.jsx`: distingue o estado arquivado na lista de Dots, reconsulta preferências após sucesso e impede abrir uma nova conversa pela navegação arquivada.
5. `sentra_canvas/desktop_ui/src/shell-bridge.js`: inclui as duas ações locais na allowlist e no diário de mutações recuperáveis por `request_key`.
6. `tests/unit/test_shell_dot_lifecycle.py`: regressões com fixtures para dependências de Dot filho, histórico remoto sintético, Grants, confirmação/snapshot, idempotência, restauração e turno `UNCERTAIN`.

Nenhum arquivo de instalador, smart UI, mídia, infraestrutura de terminal, browser/Edge ou implementação da VM foi editado nesta frente.

## Comportamento implementado

- O preflight passa a conferir toda a árvore de Dots de um root, não apenas conversas do root: conversas, vínculos remotos ChatGPT, provider bindings, turnos `queued/running/uncertain`, WorkItems centrais paginados, Grants ativos dos agentes, terminais, links internos/externos do grafo, tarefas Canvas e configuração de VM.
- O retorno diferencia `blockers` de exclusão definitiva de `archive_blockers` para um marcador de organização **somente local**. Retorna contagens, política de retenção e impressão digital do snapshot sem expor tokens.
- `dot_archive_local` exige `request_key` durável, nome exato do Dot e snapshot atualizado. Recusa se houver WorkItems ou Grants ativos, terminais ativos, turnos pendentes/incertos, tarefas Canvas ativas ou VM configurada.
- `dot_restore_local` reverte apenas o marcador. As duas mutações são transacionais e deixam resultados persistidos por intenção. Nova chamada com a mesma chave/mesmo payload devolve o mesmo recibo; colisões de intenção são negadas. Pedidos simultâneos com outras chaves não duplicam a transição do estado já arquivado.
- Conversas, mensagens, Grants, WorkItems, vínculos Web, VM e VDI ficam preservados. A interface não afirma que o ChatGPT foi arquivado ou que o Dot foi fisicamente excluído.
- O `dot_delete_unavailable` continua como veto explícito e intencional: não há contrato atestado end-to-end que assegure fechamento de sessões, revogação, arquivo remoto e remoção de discos do Dot correto.

## Testes e evidências reais

- Comando no OGrandeOxta: `python -m pytest -q tests/unit/test_shell_dot_lifecycle.py --disable-warnings --maxfail=1`.
  Resultado final: **8 passed in 22.49s** (HTTP Shell real do fixture, SQLite temporário).
- Comando: `python -m pytest -q tests/unit/test_shell_dot_features.py tests/unit/test_shell_dot_vm.py --disable-warnings --maxfail=1`.
  Resultado: **26 passed in 80.54s**; não foi necessário iniciar VirtualBox real.
- Teste específico do caminho de arquivo local: `python -m pytest -s -q tests/unit/test_shell_dot_lifecycle.py::test_archive_local_is_fenced_by_authority_and_receipted_after_fixture_cleanup --disable-warnings`.
  Resultado: **1 passed in 4.24s**. Recibos reais do teste, emitidos e persistidos na base de fixture:
  - Arquivamento local: `dot-local-596dbdff3ec576cd2d5d99587354b850`
  - Restauração local: `dot-local-5587145e46d5672d8098bd2bdb13cdcc`
  - O teste comprovou reenvio da mesma intenção sem novo efeito, rejeição de chave com intenção diferente, rejeição de nome incorreto/snapshot obsoleto e presença contínua do Dot em `dot_list`.
- Comando: `python -c "...ast.parse(...)"` para os dois módulos Python e teste: **AST_OK 3**.
- Comando: `node --check sentra_canvas/desktop_ui/src/shell-bridge.js`: saída sem erros.
- Regressão de segurança: fixtures confirmam que uma conversa remota sintética do Dot filho permanece visível no preflight; um turno em estado `uncertain` bloqueia arquivo local e nenhuma ação de reenvio é executada.
- Nenhum recibo real de remoção remota, revogação produtiva, desligamento de VM ou exclusão VDI foi produzido: essas operações **não foram executadas**.

## Pendências e limites explícitos

1. **Arquivamento ChatGPT remoto:** a integração encontrada suporta `DELETE_CHAT` mas não um protocolo verificado de `ARCHIVE_CHAT` com identidade, resultado e recibo independente. Não confundir uma marca local com uma confirmação de provedor.
2. **Fechamento/revogação central:** falta compor uma sequência journaled de encerramento de sessões, confirmação de WorkItems terminalizados, revogação dos Grants corretos e reconciliação de leases/fences. O arquivo local exige ausência de autoridade ativa; não modifica essa autoridade.
3. **VM/VDI do Dot certo:** não existe nesta frente um protocolo testado que resolva VM UUID, marker, base folder e VDI exclusivamente da reserva do root, faça desligamento autorizado, valide identidade e retenção, e emita recibo de remoção. Nada físico foi apagado.
4. **Exclusão definitiva:** permanece bloqueada mesmo para Dot vazio. Excluir linhas de SQLite isoladamente criaria órfãos no plano central, em conversas remotas, grafo, histórico ou VM.
5. **Construção frontend:** o pacote local não dispunha de `esbuild` instalado (`Cannot find module 'esbuild'`); não foi executado build JSX/UI nem prova visual no aplicativo ativo. Evitou-se instalar dependências ou gerar assets compartilhados. Alterações JSX foram verificadas por leitura de fonte, não por build.
6. **Ponta a ponta física:** prova segura concluída até HTTP e bancos de fixtures; prova de interface instalada, archive remoto e retirada física de VM/VDI **não** concluída, pois exigiria recursos reais e contratos não disponíveis.

## Política de retenção implementada

Arquivo local preserva dados indefinidamente até ação autorizada explícita. Não existem timers de exclusão, limpeza oportunista ou reciclagem automática. Para exclusão definitiva futura, exigir consentimento humano específico do Dot e dos recursos exatos, journal durável por fase, recibo atestado para cada provedor e cada recurso físico, validação de owner/projeto/root/Space, e reconciliação de `UNCERTAIN` por observação sem repetir efeitos. Limpeza local somente **depois** da comprovação remota e central.


---

## Continuação solicitada em 2026-10-12 — fechamento de autoridade e auditoria de VDI

### Alterações adicionais verificadas

- **Novo:** `sentra_canvas/shell_dot_authority_retirement.py`. Introduz `dot_retire_authority_close`, `dot_retire_authority_status` e `dot_retire_authority_reconcile`, todos limitados a owner/projeto/Space/root. O primeiro exige nome exato, frase literal `ENCERRAR AUTORIZACOES`, snapshot atualizado e `request_key` durável. A ação não executa se houver conversa ChatGPT remota vinculada, binding de provedor, VM reservada, tarefas/turnos/Operations pendentes ou `UNCERTAIN`, ou link externo.
- Cada efeito é registrado **antes de executar** em `shell_dot_authority_steps` e só vira `confirmed` depois de consulta ao estado central. Efeitos aplicados e cujo ACK se perdeu permanecem `uncertain`; reenvio da mesma chave retorna o diário sem repetir a execução. `dot_retire_authority_reconcile` apenas observa o estado alcançado, sem repetir efeitos ou pular passos ainda `pending`.
- Em escopo autorizado, encerra **terminais exclusivos do Dot**, coloca seus agentes em `WAITING` na autoridade durável, revoga Grants do agente associado, cancela WorkItems ativos de sua árvore e preserva WorkItems já terminalizados. Confere novamente recursos residuais antes de afirmar que a autoridade atual foi fechada. O fechamento não constitui bloqueio permanente contra uma **nova concessão futura** por outro serviço: antes da exclusão final ainda seria indispensável uma fence de admissão abrangente e atômica.
- **Novo:** `sentra_canvas/shell_dot_vm_retirement.py`. `dot_vm_retire_preflight` verifica, sem mutações, UUID v5 determinado por owner/projeto/root, marcador `SENTRA-DOT`, pasta proprietária, configuração VBox, estado `poweroff`, caminhos/UUIDs de discos VDI e dependências/symlinks. Não classifica localização de disco como prova de exclusividade global: falta comprovar ausência de referências por outras VMs. A ação não fecha máquina nem retira discos ou reservas.
- `sentra_canvas/shell_dot_retirement.py` também consulta **todas as operações centrais paginadas** pertinentes aos agentes/WorkItems, bloqueando inclusive `UNCERTAIN` não refletido na fila local; snapshot liga os estados das operações/agents e atualiza o diagnóstico. `shell_dot_lifecycle.py` roteia as novas ações sem alterar o protocolo global.
- `shell-dot-context-menu.jsx` recebeu confirmação dupla para encerramento da autoridade, auditoria de VM e botão de reconciliação **somente por observação** de `UNCERTAIN`. `shell-bridge.js` trata ações de leitura separadamente da mutação retida em `sessionStorage`. Nenhum `sentra_mcp`, `edge_extension`, `native_bridge`, instalador, mídia, ferramenta de terminal ou executor VirtualBox de outra frente foi editado.

### Testes concluídos na máquina autorizada

1. `python -m pytest -q tests/unit/test_shell_dot_lifecycle.py tests/unit/test_shell_dot_features.py tests/unit/test_shell_dot_vm.py --disable-warnings --maxfail=1`: **41 passed in 116.11s**. Verificadas rotas HTTP reais do fixture, revogação de Grants, cancelamento de WorkItems, posse exclusiva de terminal, retenção do Dot, isolamento de outro Dot, colisão de `request_key`, stale snapshot, `UNCERTAIN` central, perda de ACK após efeito e reconciliação estritamente observacional; testes VM somente com VBox sintético/arquivos temporários.
2. `python -m pytest -s -q tests/unit/test_shell_dot_lifecycle.py::test_authority_closure_reconciles_and_preserves_dot --disable-warnings`: **1 passed in 3.61s**. Recibo real **de fixture**, persistido no banco temporário: `dot-authority-3bf6b37632147f0c834aaa27d20ac2e8`, contendo 3 passos `confirmed`.
3. Compilação Vite real sem alterar o app instalado: comando `vite build --outDir <TEMP>/sentra-dot-build-e9da41891dd5478e917ff401d2613081 --emptyOutDir`: **✓ built in 2.02s**, 2.383 módulos transformados. Assets foram gerados **somente em diretório temporário**, não em `sentra_canvas/static/desktop-assets`. Avisos não fatais sobre scripts HTML não importados e tamanho do bundle.
4. Nenhum Dot real, conversa ChatGPT real, VM, VDI ou reserva real foi encerrado, arquivado ou excluído. Os efeitos centralizados ocorreram exclusivamente em Dots criados nos testes temporários. Não houve restart, commit ou push.

### Limites intransponíveis nesta execução sem modificar componentes compartilhados

**Arquivamento remoto ChatGPT:** a extensão e o protocolo instalados só oferecem `DELETE_CHAT` / `DELETE_CONVERSATION`, que aplica `is_visible: false`; **isso não é `ARCHIVE_CHAT` nem comprovação de `is_archived`**. Não foi emitido recibo de arquivo remoto. Requer primitiva verificada, com identidade de conversa + conta, confirmação independente e journal/fence por chamada. Os arquivos `edge_extension/service-worker.js`, `edge_extension/content-script.js`, `native_bridge/protocol.py` e transporte pertencem a outras frentes/alterações preexistentes do checkout compartilhado; não foram sobrescritos.

**Retirada física VirtualBox/VDI:** o executor `VM_ACTIONS['vm:manage']` atual permite `shutdown`, mas **não tem capacidade central para `unregistervm --delete`**. A inspeção de UUID/caminho não garante exclusividade de um disco anexado. Não se executou comando VBox destrutivo sem capacidade de efeito central, ausência verificada de compartilhamento, aprovação humana de VM/VDI específica e recibos de exclusão. Reserva permanece intacta.

**Exclusão definitiva de Dots:** `dot_delete_unavailable` permanece. Mesmo a execução bem-sucedida de `dot_retire_authority_close` fecha a autoridade corrente, **não** remove Shell Entities, Canvas, mensagens, vínculos Web, trabalho histórico ou VDI. Integrar arquivo remoto, cancelamento/revogação com fence de admissão para impedir regrants, retirada centralizada da VM e limpeza local atestada é trabalho pendente. Nunca classificar um estado `UNCERTAIN` como ausência de efeito.

### Conclusão

Esta continuação entrega o encerramento **condicionado e comprovável** de terminais, Grants e WorkItems exclusivamente em fixtures, mais a verificação restritiva de VM/VDI e o build da interface. Não declara entregue o arquivamento remoto ou a exclusão física que a infraestrutura ainda não sustenta. Isso é intencional para manter a exigência de não causar exclusão de outro Dot, conversa ou disco durante um checkout concorrente.
