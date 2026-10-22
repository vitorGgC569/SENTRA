# Workspace: SSH, conectores e caminhos guest

Revisão de código em 22/10/2026. Complementa `OPEN_ITEMS_AUDIT_2026-10-22.md`.
Não é homologação de conta externa, servidor SSH ou VM física. A UI ficou
congelada nesta rodada; nenhuma tela ou fluxo de configuração foi acrescentado.

## Estado e caminho existente

| Frente | Implementação existente | Dependência e lacuna restantes |
|---|---|---|
| SSH | `MachineHost.configure_session(kind='guacamole')` e `GuacamoleBinding(protocol='ssh')`; mesma sessão/posse/Grant/recibo usados por RDP/VNC. | Host guacd e plugin SSH, destino/usuário, verificação da identidade SSH e segredos do proprietário. Falta homologar servidor real, configuração guiada e arquivos remotos; não existe montagem SSH do explorador local. |
| GitHub | `ConnectorAccounts`, OAuth, `ConnectorHost`, `ConnectorReadExecutor` e `configure_connector_read`; leituras delimitadas de repositório e arquivo, conta/projeto/pacote/WorkItem vinculados. | Consentimento real, conta/token no vault, repositórios permitidos, pacote local fixado e opt-in nativo de rede. O workspace ainda não tem configuração guiada dessa conta nem revisão de issues/PRs pelo conector. Publicação Git usa seu próprio remoto Git revisado, não prova acesso à API GitHub. |
| Linear | Não há provider Linear em `sentra_connectors.accounts.PROVIDERS`, origem Linear em `sentra_connectors.http.HOSTS`, OAuth ou operação nativa Linear. | Conta/organização e autorização externas. Pode usar `configure_interop(kind='mcp')` existente com servidor autenticado explicitamente aprovado, endpoint e ferramentas permitidas; falta fornecer e homologar essa configuração. Não anunciar Linear disponível por apenas listar seu nome. |
| Guest/VM | `virtualbox_project` copia snapshot delimitado, verifica SHA no guest e emite recibo central. O registro do Dot guarda `last_project_import`; coordenador, ferramentas e terminal escolhem esse caminho no guest. | VirtualBox, Guest Additions, credenciais e sistema persistente precisam estar configurados e verificados. Importação é cópia em um sentido, não sincronização. O editor/explorador Git local continua restrito ao worktree/projeto host; não acessa automaticamente o filesystem guest. |

## Correções locais desta rodada

- `MachineHost.restore` agora encaminha configurações protegidas
  `optional_connectors-*` para `restore_connector_read`, após a verificação de
  escopo e identidade da máquina já existente. O helper revalida conta/projeto,
  política e pacote fixado. Restaurar somente recompõe o adaptador: não cria
  Grant, não lê bearer, não faz OAuth nem contata o provedor. Antes, o helper
  existia, mas o caminho normal de reinício recusava esse tipo de máquina.
- `project_vm_execution` agora projeta também o recibo SUCCEEDED de
  `project.import.reconcile`. Antes, confirmar explicitamente uma cópia incerta
  não registrava o diretório para os consumidores guest.
- O mapeamento novo preserva `vm_id`, reconciliação e ausência de sincronização.
  A projeção recusa recibo de outra VM; a leitura recusa mapeamento com identidade
  explícita diferente do registro atual. Registros legados sem `vm_id` mantêm
  compatibilidade no registro existente. Nenhuma cópia/processo é disparado pela
  projeção ou leitura do mapeamento.

## Reutilização sem outro sistema de autoridade

SSH deve permanecer no adaptador Guacamole configurado pelo host, usando
`secret_refs` e transporte guacd TLS fixado (ou loopback local explícito).
Prontidão de guacd não atesta a identidade do guest. Credencial e host SSH
exigem configuração e ensaio próprios; não foram inferidos do host local.

GitHub deve usar `configure_connector_read` no limite nativo autenticado,
`AccountBinding` e pacote aprovado; o renderer não escolhe caminhos, principal,
Grant ou URL. O inventário e catálogo de WorkItems existentes apresentam a
máquina depois dessa configuração. A superfície genérica de capacidades
opcionais não configura automaticamente a conta GitHub.

Linear pode reutilizar o MCP existente, com executável/argumentos fixados e
consentimento de processo, `provider_id`, endpoint quando aplicável, ferramentas
permitidas e `secret_ref`/`environment.secret_refs`. Cada ferramenta continua
precisando do WorkItem/Grant central. A configuração de servidor/conta não foi
fornecida nesta rodada; não houve conexão, instalação ou concessão automática.

Arquivos do guest exigem um adaptador de leitura/escrita remota com caminho,
versão/hash e recibos próprios, usando a VM e o WorkItem já vinculados. Até
existir, o editor host não deve ser apresentado como editor do diretório guest.
O snapshot exclui `.git`; ele não transporta a identidade do worktree Git nem
autoriza publicar alterações de volta. Sincronização e publicação precisam de
decisão explícita e prova de conteúdo atual, sem reenviar efeitos incertos.

## Evidência

`adapter-continuity.xml`: **66 passaram, 2 pulados**, 33,17 s, cobrindo
`test_workspace_adapter_continuity.py`, `test_astra_connectors_central.py`,
`test_dot_canvas_tool_routing.py` e `test_virtualbox_project.py`. São testes
locais com SQLite/DPAPI/limite central reais e transportes guest/provedor
controlados. Não provam conta GitHub/Linear, servidor SSH nem VM externa reais.
Os dois pulados são o shim OpenCode fora do PATH de teste e symlinks não
permitidos pelo token Windows. `mypy-adapters-final.log`: 0 erros, limite 0.
Resultados em `.tmp/closure-workspace/`; não somar reruns sobrepostos.
