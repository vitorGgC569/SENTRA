# Incorporação integral — núcleo e Canvas

Esta frente é implementação em andamento do objetivo completo dos37 projetos. Não declara conclusão integral nem validação dos provedores externos. Os testes abaixo foram escritos para a bateria final e não foram executados pelo coordenador nesta etapa.

## Código integrado nesta frente

- A reserva de Operation registra o vínculo de WorkItem/principal/máquina/capability na autoridade durável existente.
- `begin_machine_effect` marca a fronteira física em transação e verifica Operation, fence, lease e Run antes do I/O.
- `CentralEffectContext` exclui a máquina por lock do sistema operacional entre processos e renova o lease durante chamadas bloqueantes. Cancelar o waiter não libera o lock da thread que continua executando.
- Uma máquina com efeito iniciado e resultado incerto permanece indisponível para nova operação até reconciliação; a expiração do lease não equivale à prova de encerramento do efeito.
- Resultados são preservados como bytes no Artifact registry existente e verificados por digest e vínculo à intenção. Status pode ser recuperado após criar outro host, sem reabrir o provider.
- Saídas explicitamente solicitadas podem ser copiadas para o armazenamento durável antes de liberar a publicação, preservando evidência mesmo se a cópia do workspace mudar depois.
- `DurableInteropGate` injeta essa autoridade nos adapters ACP/A2A/MCP/OpenHands/conectores. `CentralInteropAdapter.bind_provider` liga handlers configurados; sem binding continua negando despacho.
- `CentralExecutorFactory.register_execution` liga executores reais, com principal/WorkItem/Run e contextos propagados para as threads. Registro de inventário continua separado de grant.
- `MachineHost` mantém um event loop próprio para os locks assíncronos usados pelas diferentes threads HTTP do Canvas.

## Fluxo do produto

O Canvas nativo tem o controle “Máquinas e documentos”, ligado às rotas reais de configuração, preparação de tarefa, execução e consulta. A interface configura máquina por agente, limita origens de browser e cria tarefa/capabilities escolhidas pelo proprietário. Os tokens de agentes não podem configurar máquinas nem criar esses grants.

As operações de documentos usam caminhos autorizados no workspace e publicação independente do arquivo de origem. Navegador usa contexto isolado e observações com referências/revisões validadas pelo provider. Os providers foram implementados pela frente de executores e permanecem sujeitos à validação final da ligação completa.

As seguintes rotas exigem o bearer do proprietário do Canvas:

| Rota | Função |
|---|---|
| GET `/api/center/machines?ws=...` | Inventário configurado do workspace |
| POST `/api/center/machine/configure` | Documentos ou browser, agente e perfis de rede escolhidos |
| POST `/api/center/task/prepare` | WorkItem e grants específicos escolhidos pelo proprietário |
| POST `/api/center/execute` | Despacho com identidade persistente, tarefa e capability |
| GET `/api/center/operation?ws=...&operation_id=...` | Resultado/evidência persistidos, inclusive após reinício |

O CLI usa o mesmo caminho por `CANVAS|machine_list`, `CANVAS|machine_execute` e `CANVAS|machine_observe`. A sessão real determina o agente e workspace; o comando não fornece autoridade do proprietário. A identidade da operação deriva da identidade persistida do comando, para impedir reenvio acidental com o mesmo request. O lock geral do Canvas não fica retido durante o I/O de uma máquina.

## Correções relacionadas

- A resolução de caminhos escolhe o grant mais específico antes de verificar sua permissão. Uma raiz ampla com escrita não ignora uma subraiz somente leitura.
- O CLI verifica `PatchManager.success`; contexto de patch incompatível não é apresentado como patch aplicado.

## Aceitação a executar ao final

| Cobertura | Evidência exigida |
|---|---|
| Reserva antes de efeito | Arquivo real produzido somente depois do evento de admissão física no mesmo ledger |
| Recuperação | Novo adapter/host retorna os mesmos dados registrados sem repetir I/O |
| Concorrência | Outro processo Python não adquire o lock da máquina em uso |
| Timeout | Worker mantém exclusão e lease após cancelamento do waiter |
| Autorizações | Grant revogado, identidade alterada ou workspace diferente impedem nova operação |
| Integridade | Alteração do artefato impede retorno de sucesso baseado nele |
| Produto | Canvas HTTP real transforma CSV e consulta seu resultado, com entrada preservada |
| Evidência de saída | Bytes capturados e registrados por operação permanecem verificáveis separadamente do workspace |

Comandos planejados, após completar as frentes e integrações:

```powershell
python -m pytest tests/unit/test_sentra_runtime_effect_boundary.py tests/unit/test_canvas_machine_documents_integration.py
python -m pytest tests/unit tests/integration tests/failure_injection
```

Também será necessário executar os testes JS, aceitações de browser/Windows em ambientes reais, build/instalação e os gates de cada requisito dos37 projetos. Passar os testes centrais acima não demonstra incorporação integral.

## Limites ainda presentes

A exclusão física desta implementação vale para dispatchers que compartilham o estado central neste host. Não demonstra fencing de serviços em outros computadores. Serviços remotos precisam de sua própria fronteira confiável, idempotência e consulta de estado.

Reconciliação que apenas recupera um resultado persistido não resolve um efeito externo cujo retorno nunca chegou. Ainda será implementada observação específica do provider e ligação dos recibos de conclusão tardia. Cancelamento não presume rollback.

O bootstrap oferece documentos/browser e bindings explícitos de OpenHands, Daytona e Guacamole. O inventário configurado é persistido em namespace do ControlPlane; na recuperação o Canvas verifica novamente workspace, caminho e agente. Restaurar configuração não abre sessão externa nem cria grant. A colaboração tem callbacks reais, processo supervisionado e edição no Canvas; a telemetria tem fila limitada, batching, retenção e retries. Esses incrementos permanecem sujeitos à aceitação final. Fluxos distribuídos, identidade, provas e benchmarks continuam em implementação na matriz integral.

Observações reconhecidas pelo host usam um canal de admissão separado, mantendo a exclusão física por máquina. Assim, a existência de um efeito remoto incerto não impede consultas de diagnóstico; isso não libera a operação incerta nem autoriza repetir uma escrita. Flags fornecidas pelo agente e descrições de ferramentas não classificam uma operação como observação. Consulta não afirma que uma operação original foi reconciliada.
