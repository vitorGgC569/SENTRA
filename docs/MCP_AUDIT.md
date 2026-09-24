# SENTRA MCP — auditoria comparativa com Remote Desktop Commander

Data da auditoria: 2026-09-20.

A comparação abaixo usa a superfície MCP do Remote Desktop Commander disponível na sessão de implementação e a superfície testada do SENTRA MCP.

| Área | Remote Desktop Commander | SENTRA MCP | Resultado |
|---|---|---|---|
| listar diretório | list_directory | sentra_list_directory | equivalente |
| ler arquivo paginado | read_file | sentra_read_file | equivalente |
| múltiplos arquivos | read_multiple_files | sentra_read_multiple_files | equivalente |
| metadados | get_file_info | sentra_file_info | equivalente |
| busca nome/conteúdo | start_search/get_more/stop | sentra_search | SENTRA é síncrono e bounded; menos lifecycle |
| criar diretório | create_directory | sentra_create_directory | equivalente |
| mover/renomear | move_file | sentra_move_file | equivalente |
| escrever | write_file | sentra_write_file | equivalente |
| edição cirúrgica | edit_block | sentra_edit_block | equivalente, contagem determinística |
| terminal persistente | start_process | sentra_start_process | equivalente + owner/cwd confinement |
| output incremental | read_process_output | sentra_read_process_output | equivalente |
| stdin incremental | interact_with_process | sentra_interact_process | equivalente |
| sessões | list_sessions | sentra_list_sessions | equivalente |
| terminar sessão | force_terminate | sentra_terminate_session | equivalente |
| listar processos | list_processes | sentra_list_processes | SENTRA lista somente managed/owned |
| kill PID | kill_process | sentra_kill_process | SENTRA é mais restritivo: managed + owner |
| config runtime | get/set_config_value | config env/CLI + capabilities resource | deliberadamente sem mutação remota |
| dispositivos remotos | list_devices/ping/who_am_i | não implementado | lacuna da camada remota |
| desligar agente remoto | shutdown | não implementado | depende da futura camada multi-device |
| PDF especializado | write_pdf | não implementado | fora do escopo de engenharia local |
| usage/telemetria | get_usage_stats/recent calls | audit JSONL + OMA evidence | abordagem diferente |
| repository Git | não é foco central | sentra_repo_* | vantagem SENTRA |
| testes registrados | terminal genérico | sentra_repo_test | vantagem SENTRA |
| OMA runs/events/handoff | não | sentra_oma_* | vantagem SENTRA |
| quality/promotion separation | não | CANDIDATE_READY != APPLIED | vantagem SENTRA |
| resources/prompts MCP | dependente do servidor | capabilities/project/run + sentra_operator | vantagem SENTRA |

## Conclusão funcional

Para o objetivo local do SENTRA — engenharia de software auditável em uma máquina — a camada MCP cobre filesystem, busca, terminal persistente e processos com controles mais restritivos de ownership e PID, além de adicionar repository/OMA.

As lacunas em relação ao Remote Desktop Commander não são da camada local solicitada:

1. pareamento/relay multi-device remoto;
2. administração remota do agente/dispositivo;
3. operações especializadas de documentos, como PDF.

Essas três áreas devem ser tratadas como uma camada `sentra_remote_agent` separada, com autenticação forte e threat model próprio. Não é seguro adicioná-las como atalhos ao MCP local.

## Segurança observada

SENTRA adiciona controles que não devem ser relaxados para copiar a ergonomia do Commander:

- allowed roots não vazias;
- paths privados/runtime bloqueados;
- junction/symlink escape testado no Windows;
- argv estruturado e shell=False;
- cwd confinado;
- env sensível removido;
- output flooding bounded;
- owner por sessão;
- kill somente de PID managed/owned;
- tree cleanup no Windows testado;
- lifecycle MCP chama shutdown;
- queue/OMA observacional sem promoção.

## Próximos passos opcionais para paridade remota

Se for desejado transformar o SENTRA também em um produto remoto equivalente ao Commander:

- agente local pareado por device id;
- relay autenticado e criptografado;
- leases/heartbeats;
- escopo por usuário/device;
- OAuth para o MCP remoto;
- autorização por tool;
- multi-device routing;
- remote audit/telemetry;
- kill switch e revogação.

A camada local atual deve permanecer independente dessa futura camada remota.
