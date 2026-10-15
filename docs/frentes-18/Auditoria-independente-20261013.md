# Auditoria das 18 frentes — 13/10/2026

> Registro do estado anterior ao trabalho no instalador. As correções posteriores de instalação, visual e executável de acesso estão em [INSTALADOR_AUTOMATICO_20261013.md](../INSTALADOR_AUTOMATICO_20261013.md). Em particular, o `install-next.ps1` descrito abaixo foi substituído depois desta auditoria; isso não fecha a homologação integral da frente.

**Conclusão: 0/18 frentes demonstradas como integralmente concluídas. Há implementação útil e testes passando; há também funcionalidades ainda substituídas por demonstrações locais, integração incompleta e ausência de prova no produto instalado.** Isso não significa que todo o trabalho seja descartável ou fictício.

Avaliação independente do checkout em `0c08d0665dbb51f3f99525eed6e3e1cb83b7a4ec`, com alterações locais, em 13/10/2026, aproximadamente 10:29–10:35, horário de São Paulo. Referência de escopo: diagnóstico enviado pelo usuário, incluindo o inventário de 18 frentes. Dossiês dos agentes foram usados como relatos, conferidos por leitura dos caminhos de implementação e testes. Não foi executada uma homologação física completa.

## Resultado verificável

| Verificação executada nesta auditoria | Resultado |
| --- | --- |
| `python -B -m pytest tests/unit/frentes -q --tb=short --disable-warnings -p no:cacheprovider` | **140 passaram**, 75,10 s |
| Testes existentes de `test_dot_tool_dispatch.py`, `test_native_app.py`, `test_sentra_cli.py`, `test_sentra_electron_stage.py`, `test_sentra_shell_live_preview.py` | **64 passaram, 3 falharam**, 38,98 s |
| `node --test sentra_canvas/desktop_ui/test/*.test.mjs sentra_electron/test/*.test.cjs tests/unit/frentes/iris/native-image-guard.test.cjs` | **63 passaram, 4 falharam, 1 ignorado** |
| Reprodução local do executor federado | Uma instrução matemática é devolvida literalmente como entrega e aceita pelo verificador de recibo |
| Bancos SQLite abertos com `mode=ro` e `query_only=ON` | 168 Operations `UNCERTAIN`; 33 entradas `running` na fila do shell; 120 WorkItems `RUNNING` |

São **267 testes aprovados, 7 falhas e 1 ignorado**, dentro dos conjuntos selecionados. Não é o resultado da suíte inteira do repositório. Os testes das frentes usam sobretudo diretórios temporários, executores injetados e comunicação loopback: validam contratos relevantes, mas não comprovam instalação limpa, três CLIs dentro da VM ou trabalho em dois computadores.

Os números do banco incluem histórico de outras rodadas. Não provam que todos os registros estejam travados nem que tenham sido produzidos pelos 14 terminais. Nenhuma operação incerta foi repetida ou alterada para gerar esta avaliação.

## Bloqueadores confirmados no código

### 1. Federação transmite uma tarefa, mas o executor ainda não a resolve

Em `sentra_federation/executor.py:18`, `result_document()` coloca `task` diretamente em `result.deliverable`. Em `execute_delegation()`, esse JSON é gravado como artefato e o Quality Gate recebe `passed=True`; não há chamada de modelo ou ferramenta para resolver o objetivo nesse caminho.

Reprodução sem rede, sem modelo e sem dados do usuário:

- Entrada: `Calcule 17 * 19 e entregue o resultado numerico.`
- Entrega produzida: a mesma frase, em vez de `323`.
- `verify_result_receipt()` aceita o documento quando o hash e os campos estão consistentes.

A integridade do transporte existe; a execução inteligente do trabalho remoto ainda precisa ser implementada. Nem uma prova em duas máquinas fecharia essa lacuna sozinha. Referências: `sentra_federation/executor.py:18`, `:35`, `:76`, `sentra_federation/gateway.py:772`.

### 2. O despacho do trio ainda usa processos do host

`execute_dot_tool_dispatch()` admite `placement`, mas chama `execute_non_interactive_tool()` sem um executor de guest. Este resolve executáveis locais e usa `subprocess.run(..., cwd=workspace)` no host. O adaptador `compose_dot_tool_dispatch()` também não repassa `placement` ou `guest_process` para a execução, usando o padrão `host`.

Validar um dicionário com PID/hash de guest não transporta a execução para a VM. Faltam o executor efetivo no guest e a demonstração das três inferências com revisão/conclusão. Referências: `sentra_runtime/dot_tool_dispatch.py:64`, `:340`, `:763`; `sentra_canvas/dot_tool_runner.py:68`, `:315`.

### 3. O instalador Next não é um pacote autossuficiente

`installer/windows/install-next.ps1:78` copia uma seleção de pacotes e gera um launcher que depende de `python` no PATH (`:130`). Não inclui, nessa seleção, módulos como `orchestrator`, `native_bridge`, `sentra_executors`, `sentra_cli` e `sentra_model_gateway`, embora caminhos do produto os importem. Por exemplo, o despacho importa `orchestrator`, e o relay usa `native_bridge`.

Isso é uma limitação concreta desse instalador, não uma afirmação de que inexista qualquer outra infraestrutura de distribuição no repositório. A presença de arquivos, um atalho ou HTTP 200 dos assets não comprova funcionamento em Windows limpo. Também falta demonstrar atualização e rollback de uma instalação real.

### 4. Os novos conectores ainda são um pacote local de demonstração

`skills/optional_connectors/local_invoke.py:5` recusa rede e retorna `{"value": "local-connector"}`. `sentra_marketplace/connectors.py` encaminha a execução padrão para esse arquivo. Os nomes GitHub, Drive, OneDrive, Microsoft 365 e Slack não comprovam integração com essas contas.

Há valor nas permissões, validação de pacotes e proteção contra repetição. Falta o comportamento útil de cada integração e sua ligação com autenticação, falhas e interface.

### 5. Arquivamento remoto permanece explicitamente ausente

`sentra_canvas/shell_dot_retirement.py:193` informa `archive_scope: local_projection_only` e `remote_archive_verified: False`. O fluxo conserva as conversas remotas. Portanto, arquivar localmente não atende ao critério de arquivar de fato no provedor.

### 6. Parte da entrega multimodal nova não está ligada à extensão

`edge_extension/native-image-guard.js` possui testes próprios, mas suas funções só aparecem no próprio módulo e nesses testes. O manifesto e o service worker não o carregam. Existem outros mecanismos anteriores de coleta e armazenamento de imagens; a ausência dessa ligação não significa ausência de toda a infraestrutura multimodal. Continua faltando comprovar o percurso real até os bytes e a imagem exibida no Canvas.

### 7. A memória persiste dados, mas isso não fecha planejamento e retomada

O shell cria `LiveDotSession`, carrega um registro e expõe apenas `present` nesse ponto (`shell_runtime.py:247`). Ao publicar a resposta, salva os primeiros 500 caracteres como objetivo/resumo, com `steps: []` (`:493`). Isso demonstra persistência, mas não um plano executável, recuperação completa do contexto ou handoff entre provedores.

### 8. Código no disco não equivale ao código carregado

O broker PID 6836 estava iniciado desde **12/10/2026 às 15:58:47**. `shell_runtime.py`, `service.py` e `dot_tool_dispatch.py` foram alterados em 13/10. `service.py` é importado no início do broker; reabrir só a janela, como feito anteriormente para o visual, não recarrega esse módulo Python.

A auditoria não reiniciou esse serviço. O estado de operações pendentes exige reconciliação antes de uma atualização coordenada. Não há evidência de que todas as novidades no disco estejam presentes no processo que o usuário utiliza.

## Situação de cada frente

| Nº | Frente | O que existe | O que impede concluir |
| --- | --- | --- | --- |
| 1 | Orquestração dos três CLIs | Despacho, gates, recibos e revisão | Executor do guest e trio real consolidado no aplicativo |
| 2 | Provisionamento Debian/Windows | Scripts Debian, avanço/verificação, contratos Windows e botões | Criação limpa integral pela UI e Windows instalado/utilizável; relato Debian anterior não fecha ambos |
| 3 | Importação/sincronização | Snapshot filtrado, hashes, importador e ação na UI | Cópia contemporânea comprovada no guest com recibo central; sincronização completa não demonstrada |
| 4 | Computer Use | Posse de input, executor semântico e worker | Tarefa gráfica real no guest, entrada e verificação pós-ação; captura de greeter não basta |
| 5 | Ciclo de vida | Pausa/retomada, arquivo local, planos/recibos | Arquivamento remoto e retirada completa de família/VM/VDI sem órfãos, com recuperação comprovada |
| 6 | Imagens nativas | Admissão, armazenamento/validação e guardas de incerteza | Integração do guard novo e prova real de bytes/MIME/hash/renderização |
| 7 | Recuperação/E2E | Planejador observacional e diário que preserva UNCERTAIN | Recuperação efetiva no produto após incidentes; observar pendência não a resolve |
| 8 | Desktop/Canvas/Smart UI | Interface ativa refinada, componentes e evidências visuais | Unificar variantes/testes, fluxo completo de estados, acessibilidade e Smart UI no produto |
| 9 | Instalador/atualização | Infraestrutura existente, Next, launchers, ícones e instância única | Pacote completo, dependências automáticas, instalação limpa, atualização e rollback reais |
| 10 | Provedores/CLIs | Catálogo, admissão e runners | Auth/inferência comprovada em todos os caminhos, fallback e contrato Antigravity; regressão selecionada não está verde |
| 11 | Memória/planejamento | Persistência por Dot e teste entre processos | Recuperação útil do conteúdo/etapas no modelo, planejamento, handoff e reinício real do produto |
| 12 | Recursos/VMs | Medição, orçamento e caminho `resource.cap` protegido | Aplicação/efeito reais, atribuição completa e medição de desempenho sob carga; não é correto dizer que o código só recusa |
| 13 | Observabilidade/segurança | Auditoria, autorização, sanitização e testes adversariais | Cadeia viva de decisão a efeito e revisão, falhas/carga reais e cobertura conjunta; não é auditoria independente de segurança completa |
| 14 | Conectores/skills/automações | Gates e invocação de pacote local | Conector externo útil, skill/plugin e automação completos pela interface |
| 15 | Colaboração/contas/sync | TeamDirectory, escopos, convites e testes | Fluxos de contas, sincronização e revogação entre usuários reais no produto |
| 16 | Comercial/documentação/suporte | Licença, manuais, diagnóstico e política local | Percurso instalado de suporte/distribuição; documentos não fecham operação comercial |
| 17 | Marketplace/modelos visuais | Catálogo/opt-in, hashes e contrato de runtime visual | Catálogo/pacotes úteis e inferência com pesos reais; um callable injetado não fornece o modelo |
| 18 | Federação | Identidade, mTLS, pareamento, recibos, loopback e projeção UI | Executor útil em vez de eco, duas instalações reais, Canvas compartilhado e reconciliação em rede real |

Todas permanecem parciais diante do escopo integral. Algumas têm infraestrutura significativa; outras ainda estão na base inicial da funcionalidade.

## Falhas dos testes: interpretação correta

As quatro falhas Node são de apresentação: ordem de elementos Canvas/Computador, bloco de tokens de um redesign anterior e propriedade `execution` dos mascotes. Parte desses testes inspeciona texto JSX/CSS e está desalinhada com o rollback e a lapidação posterior. Não são, isoladamente, prova de quatro falhas visíveis. Também não é correto atribuí-las automaticamente ao trabalho dos terminais Grok: este checkout inclui nossas mudanças visuais anteriores.

As três falhas Python estão em `tests/unit/test_sentra_cli.py`:

- `test_browser_host_ready_adopts_compatible_existing_launcher`;
- `test_responses_stream_enforces_absolute_deadline`;
- `test_chatgpt_web_rejected_preflight_error_is_concise_and_not_uncertain`.

Nos dois últimos, `invalid model namespace` interrompe o teste antes do comportamento esperado. Não comparei essas falhas com uma execução limpa do commit base; classifico-as como falhas atuais da verificação, sem afirmar que os agentes as introduziram.

## Quantidade de código e autoria

O diff rastreado contém **5.250 linhas adicionadas e 536 removidas em 86 arquivos**. Há ainda **251 arquivos novos de código/testes/scripts, totalizando 19.954 linhas**, excluindo `.maestri` e `Isos` desse segundo levantamento. Isso mistura várias rodadas e inclui testes e nossa lapidação visual; não representa uma medição das linhas produzidas exclusivamente pelos 14 terminais. Não há base para atribuir tudo ao Grok.

## Próxima entrega recomendada

Priorizar um percurso executável em instalação limpa: instalar → abrir → criar Dot → preparar ambiente → importar projeto → executar tarefa → verificar entrega → reiniciar e retomar. Para cada etapa, conservar a versão, o ambiente, o teste e a evidência do resultado. Só então ampliar a prova para três CLIs, Windows, rede e conectores.

O usuário priorizou, após esta auditoria, um instalador automático e uma primeira experiência com o mínimo de intervenção. Essa é a próxima frente de implementação. Os bloqueadores acima devem permanecer explícitos; automatizar o instalador não transforma capacidades parciais em funcionalidades concluídas.

Evidências locais: `.tmp/audit-frentes-20261013/evidence.json` e `.tmp/audit-frentes-node-20261013.log`. A auditoria não alterou código de produto, não reiniciou o broker e não executou modelos, reinstalações, exclusões ou operações remotas reais.
