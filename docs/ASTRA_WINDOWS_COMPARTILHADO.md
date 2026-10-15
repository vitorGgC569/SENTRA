# SENTRA — Windows compartilhado e isolamento de Dots

Data: 15/10/2026. Candidato de engenharia, sem provisionamento ou mudança na VM existente.

**Recomendação:** preparar uma única imagem Windows limpa e versionada, usar discos diferenciais por Dot ou por domínio de confiança e manter apenas uma ou duas VMs ligadas, conforme RAM disponível. Isso compartilha a instalação base em disco e separa os kernels dos guests. Para tarefas confiáveis sem GUI, uma VM com usuários limitados pode ser uma modalidade mais econômica, explicitamente com kernel compartilhado e console serializado. Não atende à exigência de isolamento completo entre código hostil.

Antes de escolher a modalidade operacional, continua necessário concluir o Windows em ambiente autorizado, verificar o desktop persistente, instalar Guest Additions e comprovar GuestControl com Operation e recibo no Canvas. A evidência anterior de Windows Setup não comprova esses passos. Nenhum disco, conta ou VM foi alterado nesta frente.

## Mapa do código inspecionado

| Código | Capacidade real | Limite relevante |
|---|---|---|
| `sentra_executors/virtualbox_vm.py` | Binding do host fixa UUID e marcador; status e console conferem identidade; screenshot usa framebuffer COM; teclado e mouse usam o console da VM. `guest.run` exige executor comprovado de guest e não substitui por shell do host. | Framebuffer/input não selecionam uma sessão Windows por Dot. A configuração atual fornece uma conta por binding/configuração; não há contrato integrado de seleção de SID/perfil por Dot em VM compartilhada. |
| `sentra_executors/guest_execution.py` | Credenciais vêm de configuração confiável; senha por stdin, limites de tempo, validação de placement e Guest Additions. | Iniciar um processo com outro usuário não comprova acesso à sessão gráfica correta, nem estabelece isolamento de kernel. |
| `sentra_executors/virtualbox_project.py` | Snapshot explícito do projeto, limites, recusa links/reparse e exclusão de credenciais comuns; transferência delimitada ao guest. | Não é sincronização implícita nem mecanismo de ACL entre usuários. Novas áreas privadas precisam de configuração e provas próprias. |
| `sentra_executors/input_control.py` | Posse durável no ControlStore, CAS por epoch, transferência humano/agente e verificação do WorkItem/Grant. O recurso VirtualBox é hash de `virtualbox:<vm_id>`. | Dois aliases de Dots na mesma VM não podem receber recursos de teclado independentes. Posse não concede capability e não substitui a autorização imediatamente antes do efeito. |
| `sentra_runtime/effect_boundary.py` e `machine_host.py` | Registro de máquina por proprietário; exclusão, lease/fence e Grant central; terminal Canvas exige adaptador configurado e cercado pelo controle central. | Um terminal do host, stdout sintético ou processo de preparação não comprova execução Windows no guest. Não criar um agendador local concorrente da autoridade central. |
| `sentra_executors/windows_guest.py`, `windows_guest_deployment.py`, `uia_semantic.py` | Caminho Hyper-V explicitamente configurado e descartável; worker interativo limitado; identidade de processo e desktop com sessão, hash e MachineGuid. | Não é provisionador genérico multiusuário VirtualBox. Metadados graváveis pelo agente não são autoridade de identidade; o backend revalida identidade real. |
| `sentra_executors/guest_process.py` | Processo e árvore de filhos delimitados por runner/Job e checkpoints. | O próprio código esclarece: posse da árvore de processos não é sandbox de SO. |
| `scripts/commander/clean_install_plan.py` | Plano de verificação do Setup, backup, instalação limpa, doctor e desinstalação em VM descartável. | Emite plano com `homologated: false`; não comprova instalação executada. Flags descritas precisam ser aceitas e verificadas pelo Setup candidato. |
| `sentra_federation/task_runtime.py` e `tests/unit/test_federation_machine_tasks.py` | Tarefas tipadas de máquina e testes entre duas instalações/processos, com mTLS, arquivos, recibos e recuperação/revogação. | Não equivale a Setup instalado e Federation homologada dentro do Windows da VM. Identidades pareadas e credenciais não podem ser copiadas para a imagem base. |

Não foi encontrado, nas áreas de executor/runtime inspecionadas, um provisionador integrado de linked clones nem um serviço completo de usuários Windows por Dot. A capacidade existente deve ser estendida com bindings confiáveis; não basta acrescentar `--username` vindo da interface ou do modelo.

## O que pode ser isolado em uma VM

Uma conta limitada é um principal de segurança para autorização de recursos. SID distinto, ACL de diretório e credenciais individuais permitem separar dados por usuário quando o acesso é corretamente configurado. A avaliação precisa verificar grupos e privilégios efetivos: uma conta administrativa com token filtrado pelo UAC não deve ser tratada como usuário limitado. Fontes: [contas locais](https://learn.microsoft.com/en-us/windows/security/identity-protection/access-control/local-accounts), [controle de acesso](https://learn.microsoft.com/en-us/windows/security/identity-protection/access-control/access-control), [funcionamento do UAC](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/user-account-control/how-it-works).

O kernel, serviços e recursos globais continuam compartilhados. Diretórios privados não isolam rede, portas locais, disponibilidade do sistema ou uma vulnerabilidade privilegiada. Windows mantém namespaces por sessão e também objetos globais; essas distinções precisam aparecer na política do produto. Fonte: [namespaces de objetos do kernel](https://learn.microsoft.com/en-us/windows/win32/termserv/kernel-object-namespaces).

A GUI requer identidade adicional. Uma window station contém clipboard e desktops, e somente a station interativa recebe teclado/mouse; sessões RDS têm suas próprias stations interativas. Desktops também possuem controles de acesso, e o desktop seguro é distinto. Portanto, `user_sid` diferente e `guest.run` bem-sucedido não comprovam isolamento de clipboard, janela ou input. A inferência específica para o SENTRA é que o console físico VirtualBox atual precisa de fila e posse única, com identidade da sessão ativa verificada antes do input. Fontes: [window stations](https://learn.microsoft.com/en-us/windows/win32/winstation/window-stations), [desktops](https://learn.microsoft.com/en-us/windows/win32/winstation/desktops).

Não há proposta de patch de RDP. Windows Enterprise multi-session admite sessões concorrentes, mas a Microsoft não permite sua execução em produção fora do Azure Virtual Desktop; não é uma edição de uso local genérico. Windows Server RDS é uma alternativa diferente, com infraestrutura de licenciamento e CALs por usuário/dispositivo conforme o cenário. Nenhuma destas opções foi provisionada. Fontes: [FAQ multi-session](https://learn.microsoft.com/en-us/azure/virtual-desktop/windows-multisession-faq), [RDS CAL](https://learn.microsoft.com/en-us/windows-server/remote/remote-desktop-services/rds-client-access-license).

## Comparação prática

| Critério | Uma VM + usuários limitados | Imagem base + linked clones |
|---|---|---|
| Disco | Uma instalação e perfis/workspaces por usuário. | Uma cadeia base congelada e diferenças por clone. Não copia uma instalação inteira por Dot. |
| RAM | Um kernel; bom para tarefas confiáveis sem GUI. | RAM por clone ligado; ligar por demanda e limitar concorrência. |
| Fronteira de segurança | ACL/processo/credenciais, com kernel compartilhado. Administrador da VM alcança outros usuários. | Kernel por guest; host/hipervisor e infraestrutura continuam sendo parte da confiança. |
| GUI com executor atual | Um console; fila, posse central e transferência explícita. Trocar usuário não pode expor o desktop anterior. | Um console por VM; um ou dois clones ativos podem executar GUI sem disputar o mesmo framebuffer. |
| Persistência | Arquivos, perfil de navegador, temp e estado do usuário, com ACL real. | Disco filho persistente por Dot; não restaurar snapshot automaticamente ao terminar uma tarefa. |
| Manutenção | Atualização afeta todos os usuários; falha de SO afeta todos. | Nova versão da base gera nova família; não reescrever pai de discos filhos existentes. Migração explícita do estado do Dot. |
| Licença | Direitos de uso/acesso dependem da edição e contrato. | Economia de disco não concede direitos de executar/acessar VMs adicionais. |

Oracle documenta que linked clones usam discos diferenciais dependentes da origem; full clones copiam os discos dependentes. Novos MACs devem ser usados quando as máquinas coexistirem. Discos filhos precisam dos pais, e restore/delete/merge de snapshots têm implicações de persistência, tempo e espaço temporário. Não usar o mesmo disco Windows gravável em vários guests nem escolher um modo immutable com autoreset para dados persistentes. Fontes: [clonagem e snapshots](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/working-with-vms.html), [armazenamento e discos diferenciais](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/storage.html).

Exemplo **estimado**, não medido: instalação base de 40 GiB, 20 Dots e diferença média de 2 GiB por clone resultam em aproximadamente 80 GiB para base + diferenças. Vinte cópias completas só da instalação base seriam 800 GiB, antes dos dados de trabalho. Uma VM com perfis de 1 GiB usaria aproximadamente 60 GiB. Esses cenários têm garantias diferentes; diferenças podem crescer, e backup, merge, metadados e reservas ficam fora da estimativa. Em host de 16 GiB com reserva de 8 GiB e orçamento de 4 GiB por VM, o limite calculado é duas VMs ativas. É orçamento, sem garantia de desempenho.

Verificar os direitos da edição e do programa de licenciamento antes de transformar o número de Dots em instâncias Windows. Não inferir licença a partir da ativação técnica ou da existência de um VDI. Fonte: [orientação Microsoft para desktops Windows virtuais](https://www.microsoft.com/licensing/guidance/Windows-11-Licensing-for-Virtual-Desktops).

## Base mínima implementada nesta frente

`sentra_executors/windows_dot_isolation.py` pode ser importado, planejar e recuperar evidências sem comandos Windows ou APIs VirtualBox. A entrada explícita `collect_windows_probe` solicita uma execução via MachineHost e não foi invocada na VM existente:

- `WindowsDotAccount` e `validate_account_layout`: UUID canônico, SID local dedicado, conta delimitada, referência opaca de credencial, caminhos privados; recusa aliases, reutilização de referência de credencial, diretórios sobrepostos e ambiguidades de caminho. A referência é ocultada do `repr`, mas não é um cofre nem prova de que dois handles apontam para senhas diferentes.
- `GoldenImage`, `CloneIdentity` e `validate_clone_layout`: bloqueiam base não preparada e clones que reutilizam VM, disco gravável, instalação, MachineGuid ou MAC. Conferem o pai imediato declarado. A cadeia real, hashes e ausência de segredos devem ser comprovados pelo host; booleans declarados não fazem attestation.
- `estimate_resources`: estimativa simples de disco e limite de VMs ativas por RAM; inclui flags explícitas de que não é medição nem cálculo de licenças.
- `console_resource_id` e `assess_console_possession`: usam o mesmo recurso físico do `InputControl` atual; verificam projeção fresca de holder, máquina, agente, WorkItem, epoch e expiração. Não adquirem posse, não concedem Grant e não substituem `effect_checkpoint` antes do efeito.
- `account_probe_script`: gera fonte PowerShell para coleta autorizada no guest, com nonce e parâmetros em JSON/base64. Consulta SID/token, grupos, privilégios, perfil registrado, MachineGuid, sessão, ACL e ancestrais reparse. Para canários descartáveis já existentes de outro usuário, tenta abrir um handle de leitura sem ler conteúdo. `missing` e `error` não equivalem a `denied`. Não cria contas, arquivos ou tarefas, não habilita autologon e não altera permissões.
- `assess_account_probe`: recusa administrador, privilégios sensíveis, ACL ampla/não protegida, reparse, identidade/nonce errados, evidência duplicada ou ausente e canários legíveis. Retorna sempre `authorization_granted=false`, `isolation_homologated=false` e `gui_session_verified=false`. É validação estrutural; JSON apresentado por um agente não é prova de execução.
- `prepare_windows_probe`: resolve o registro protegido do Dot e a conversa com WorkItem, verifica conta/VM/assignee/Run e o Grant atual, e prepara um comando fixo com nonce. Não cria Grant nem Operation. SID, MachineGuid e diretórios precisam de inscrição independente pelo host; não são descobertos em JSON fornecido pelo modelo.
- `collect_windows_probe`: aceita MachineHost real do mesmo proprietário e máquina VirtualBox registrada. Usa o dispatch atual, com suas políticas, leases, fences, posse humana e verificação de Guest Additions. Se a Operation já existe, somente recupera; não envia o comando novamente.
- `recover_windows_probe`: lê o recibo pelo `CentralDurableIntentAuthority`, exige hash da intenção exata e resultado no artefato protegido e verificado. Recusa resultado antigo, alteração de configuração/Grant, resultado host, estado incerto, JSON duplicado e artefato adulterado. Nenhuma saída do chamador é recebida como prova. Atestar que um comando foi recebido do guest não equivale a homologar isolamento do SO.

Limites deliberados: as ACLs avaliadas são das raízes privadas, não uma auditoria recursiva de cada arquivo; regras de deny e acesso efetivo podem produzir recusas conservadoras; canários precisam de existência confirmada por operação independente. ACL por SID não prova isolamento de processos, rede ou kernel. Nenhum probe foi executado no host ou guest; o teste apenas fez parse estático com o parser PowerShell instalado.

## Integração proposta ao responsável pelo runtime

Sem mudanças em `virtualbox_vm.py`, MachineHost, effect boundary ou configuração produtiva nesta entrega:

1. Manter um registro confiável proprietário → Dot → VM UUID → SID/conta → referências de credencial e diretórios. A interface solicita uma modalidade; não escolhe senha, SID, sessão, clone pai ou VM arbitrária.
2. Para compartilhamento, resolver a conta desse registro dentro do host ao construir o executor. Serializar GUI pelo recurso físico existente; suspender input se a sessão/usuário ativo não estiver comprovado. `GuestControl` comprova processo, e um worker interativo separado comprova sessão/desktop antes de qualquer ação gráfica.
3. Submeter o probe como `guest.run` pelo ControlPlane. Guardar hash do comando, nonce e bindings junto à Operation. Confirmar sucesso/placement/stdout e recibo canônico antes de chamar a avaliação. Não reutilizar a saída de um probe após reinício ou troca de identidade.
4. Para clones, preparar uma cópia de trabalho descartável, nunca executar Sysprep no VDI original. Seguir o fluxo suportado de imagem generalizada; preparar credenciais e identidade SENTRA depois da clonagem, ou instalar o pacote sem inicializar credenciais/pareamento na base. Sysprep não substitui a limpeza dos segredos da aplicação. Fonte: [generalização de imagem Windows](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/sysprep--generalize--a-windows-installation?view=windows-11).
5. Implementar ação tipada de provisionamento no executor autorizado: pai/snapshot/hash fixados, novo UUID/MAC/filho, configuração de rede delimitada e nenhuma pasta/clipboard/drag-and-drop/USB do host implícita. Registrar cada efeito e reconciliar resultado incerto antes de repetir. O módulo atual apenas valida inventário; não realiza esse provisionamento.
6. Medir a cadeia real de discos, hashes e tamanho dos deltas; testar backup/restauração com todos os pais. Guardar versão da família de imagem e impedir delete/merge destrutivo enquanto houver dependentes.

## Aceite ainda pendente

Em ambiente descartável e via ControlPlane autorizado: desktop Windows persistente → Guest Additions/GuestControl → duas contas limitadas e canários privados → negação cruzada comprovada em ambas as direções → sessão/clipboard/input de GUI corretamente cercados → reinício/expiração/revogação sem execução fora do Grant → Setup atualizado com doctor/serviços/persistência → identidade nova da instalação e Federation com tarefa útil, artefato e recibos entre host e guest instalado.

Para modalidade clone, adicionar duas VMs derivadas da mesma base, identidade/credenciais distintas, ausência de compartilhamentos implícitos e reinício com persistência dos filhos. Não considerar os testes de duas instâncias no host como conclusão dessa homologação Windows. O release nativo/Setup pertence à frente de distribuição e não foi alterado aqui.

## Evidência reproduzível desta entrega

`python -m pytest tests/unit/test_windows_dot_isolation.py tests/unit/test_windows_dot_isolation_probe.py tests/unit/test_guest_execution.py tests/unit/test_input_automatic_acquisition.py -q`

Resultado combinado atualizado: **126 testes aprovados**. Os casos Windows usam inventários/stdout sintéticos; parser PowerShell real sem execução do probe; ControlPlane SQLite, MachineHost e artefatos DPAPI reais em diretórios temporários para validar posse, revogação, recuperação e adulteração. Não há afirmação de teste físico de isolamento a partir dessas fixtures. Não foram feitos boot, instalação, criação de contas, alteração de VDI, atualização de bundle ou reinício de serviços.

## Inspeção atual da VM vinculada, 15/10

Inspeção via bridge Canvas autenticada e endpoints da central existentes, com credencial loopback mantida privada. Foram usados `home`, listas/get de conversa, `dot_vm_status`, framebuffer e uma Operation de `vm:observe diagnostics`. Não houve `vm:manage`, `vm:guest`, posse nova ou input.

| Item | Evidência atual |
|---|---|
| Dot / VM | `testegpt6`, root `dot-7634e5106b837733bcb932682ad2e14a`, UUID `b1a7b455-5800-414f-b095-e923c49efb6c`. |
| Vínculo efetivo | Conversa `conversation-f42bcb1cf644616d782be80662f52cf0`, WorkItem `vm-b91f8efe86fe568b83a0b118e05bb20b`, máquina `canvas-virtualbox_vm-6fa88b7f0a53f5c72c212631`. A conversa antiga `conversation-7bba7abb9191d2d4578b82d16800539b` retorna `conversation_authorized=false`; não usá-la como autoridade de execução. |
| Central | Run e WorkItem `RUNNING`; WorkItem declara `vm:observe/manage/input/guest`. Isso é requisito, não prova de quatro Grants válidos. `vm:observe` foi efetivamente admitido e conferido pelo executor nesta inspeção; status de input indica `grant_status=granted`. Os demais Grants devem ser reavaliados antes do efeito pretendido. |
| Posse de input | Último holder humano, epoch 7, `live=false`, TTL restante 0. Uma antiga transferência humana não autoriza uma nova tecla hoje. |
| VM | `running`, 2 vCPU, 4096 MiB; `installation_started`. |
| Tela atual | Windows Setup: cópia concluída, **preparando arquivos para instalação em 72%**. Não é desktop Windows. |
| Continuidade | Captura nova `.tmp/astra-windows-current-frame.png`, SHA-256 `49ea2b78c9bfe74d9a4c6abd1eaa086168a078198fc00c6a3d7dc0b25092e10c`, idêntica às capturas `.tmp/windows-install-check-now.png` e `.tmp/windows-install-check-20261014-1551.png` de 14/10. Não há progresso visual demonstrado entre elas. |
| GuestControl | Runlevel 0, `guest_additions_unavailable`, canal de comandos indisponível. Instalação verificada e desktop verificado permanecem falsos. |
| Diagnóstico canônico | Operation `op-shell-f78bb1cacc019dc0c3d3cf702ce638ee7e910dfa`, `SUCCEEDED`, recuperada também por `/api/center/operation`. Backend `hyperv_nem`, fallback de virtualização presente, log vinculado à VM, sem reboot automático. |
| VDI atual | `system-localiso2.vdi`, UUID `b423c056-076a-4d06-8623-4b81cee08b08`, capacidade 68.719.476.736 bytes, arquivo 9.881.780.224 bytes. Última modificação observada há aproximadamente 68.700 segundos na coleta. É observação de metadata, não integridade transacional do Windows instalado. |
| Backup preservado | `system-pre-windows-setup-20261014.vdi.backup`, 2.864.709.632 bytes, mesmo UUID/capacidade. SHA-256 recalculado em leitura: `c464d01be7cb8ac86140a1b9ec253631daf9806f4b7533799dd315929e8535eb`, igual ao registro anterior e estável durante a leitura. Não foi registrado nem montado. |

O MCP Commander tem principal distinto do Canvas: o WorkItem não apareceu nesse escopo e a listagem de Grants dele ficou vazia. Isso não demonstra ausência do WorkItem/Grant do Canvas; o endpoint Canvas autenticado comprovou o vínculo e o diagnóstico. Não houve alteração de proprietário ou ampliação de autorização. `/api/center/machines` retornou HTTP 500 nesta inspeção; não foi usado como evidência positiva de Grants.

**Próxima ação concreta:** diagnóstico adicional somente leitura de logs atuais e atividade da VM para distinguir espera do instalador, bloqueio de I/O e problema de virtualização. Os mesmos pixels e a ausência de modificação recente do VDI justificam investigar uma interrupção, mas não determinam a causa. Não reenviar o antigo pause (houve 403 registrado), não repetir boot/teclas nem iniciar outra instalação a partir desse sintoma.

Depois desse diagnóstico, o responsável pela integração coordena uma intervenção nova e delimitada pelo ControlPlane, com Grant e posse atuais, preservando o backup. Ao chegar a OOBE/desktop, confirmar boot pelo disco, instalar Guest Additions e executar o probe sob identidade inscrita. Só então avançar ao Setup atualizado e à tarefa Federation host ↔ guest instalado, com instalação/serviços/reinício/autenticação e recibos próprios.

**Bloqueio adicional de integração encontrado:** `virtualbox_installation.owned_storage` atualmente espera o arquivo `system.vdi` e um disco base sem pai, enquanto este VDI usa `system-localiso2.vdi`. O parser `inspect_vdi` declara suporte apenas a base dinâmica VDI v1.1, sem discos diferenciais. Portanto, antes de homologar `installation.verify` neste legado ou habilitar linked clones, é necessário estender a resolução confiável de armazenamento e validar a cadeia de pais. Não renomear o disco nem relaxar as verificações para fazer o teste passar. Nenhum desses arquivos centrais foi modificado nesta entrega.

## Continuação P0: logs reais e binding estrito de armazenamento

Na continuação, `virtualbox_installation.py` recebeu um gancho pequeno e estrito para `storage_binding`, implementado no novo `sentra_executors/virtualbox_storage_binding.py`. O caminho anterior, sem essa configuração, mantém a exigência de `system.vdi`. Nenhuma configuração produtiva foi modificada: o novo caminho exige inscrição pelo host após revisão e ainda não foi ativado na VM existente.

### Evidência adicional de execução sem progresso

O registro XML do VirtualBox foi lido e filtrado pelo UUID conhecido da VM; o arquivo `.vbox` foi conferido com o mesmo UUID antes da leitura de seus logs. O diretório de configuração real está em `.sentra/durable/dot-vms/...`, enquanto o VDI ativo está em AppData. O registro contém outros VDIs antigos, que não foram tratados como alvo nem alterados. O binding candidato usa apenas o disco realmente anexado ao SATA 0/0, conferido pelo cliente VirtualBox existente.

O `VBox.log` atual identifica VirtualBox **7.2.20 r175154**, host Windows 11 build **26200.9711**, Memory Integrity ativa e processo **17228**. Os seguintes fatos foram observados:

- NEM informa `Snail execution mode is active`; o backend é Hyper-V/NEM, confirmado também pelo diagnóstico central anterior.
- O relógio virtual registra três abandonos de catch-up: aproximadamente **700,75 s**, **664,20 s** e **409,56 s**, somando **1.774,50 s**. Uma solicitação de modo TSC foi ignorada por incompatibilidade do host/VM.
- A busca dirigida no log atual não encontrou `VERR_`, Guru Meditation ou erro/falha/timeout de AHCI/VDI/AIOMgr. Isso não prova ausência de falha dentro do Windows Setup.
- O processo 17228, identificado no cabeçalho do log da VM, acumulou **3,09375 s de CPU em uma janela de cerca de 3 s**, com **zero bytes adicionais de leitura e escrita de arquivo** nos contadores do processo. Não foi confundido com as outras instâncias VBoxHeadless.
- O log continua registrando avisos periódicos de rede do backend, que não constituem progresso do instalador. A imagem de 72% e o VDI permanecem sem progresso observado.

A última gravação registrada do VDI foi em **14/10 às 18:06:25 UTC**, aproximadamente **42 segundos após** o terceiro abandono de catch-up registrado no log, às 18:05:44 UTC. É correlação temporal, não identificação da thread/erro do Windows. Inventário sanitizado com hash do log fonte: `.tmp/astra-windows-log-diagnosis.json`.

**Conclusão delimitada:** a condição de baixo desempenho e distorção temporal NEM está comprovada; a VM consome CPU sem I/O útil observado. Essa é uma hipótese forte para o bloqueio, mas a causa do ponto exato de 72% ainda não está fechada sem logs Panther/estado do processo Setup no guest. Não há base para afirmar corrupção do VDI ou para refazer a instalação. Oracle documenta problemas de desempenho na coexistência com Hyper-V, e o upstream tem relato de stalls NEM em Windows 11 25H2; o relato não prova que este seja o mesmo bug. Fontes: [guia Oracle 7.2, problemas conhecidos](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/EN-VBOX-7-2-USER.pdf), [upstream #837](https://github.com/VirtualBox/virtualbox/issues/837), [orientação Microsoft sobre coexistência](https://learn.microsoft.com/en-us/troubleshoot/windows-client/application-management/virtualization-apps-not-work-with-hyper-v).

Não foi proposta nem realizada desativação de Memory Integrity, Hyper-V, Credential Guard ou mudança no boot do host. Uma troca futura de hipervisor pode ser avaliada em cópia descartável; não é uma migração implícita do VDI original.

### O binding implementado

`storage_binding_candidate` faz somente leitura usando o cliente VirtualBox que já confere UUID/marcador, a configuração `.vbox` exata e a anexação real. Ele exige um único disco base dinâmico VDI v1.1, SATA 0/0, sem pai, caminho local em uma raiz específica e sem symlinks/junctions/hardlinks. A capacidade e o UUID do cabeçalho precisam coincidir com o anexo e com a reserva.

O registro candidato fixa VM, hash do marcador, `.vbox`, raiz, caminho exato do VDI, UUID, capacidade, slot e identidade do arquivo (device/inode). Acrescenta fingerprint de campos imutáveis do cabeçalho/UUID/geometria. **Esse fingerprint não é hash dos dados Windows:** uma instalação gravável precisa alterar seus setores e seu mapa de blocos; `guest_data_integrity_verified` permanece falso. A identidade do arquivo e a estabilidade da leitura são conferidas antes/depois, incluindo recusa de troca do arquivo por outro com os mesmos bytes/UUID.

O gancho de `owned_storage` aceita somente um envelope completo vindo da configuração protegida do host, com fingerprint correspondente e referência de Operation de aprovação. Um candidato solto (`applied=false`) não é esse envelope, e falha de validação não causa fallback ao disco antigo. A referência de aprovação é metadado de proveniência: o responsável por persistir o registro precisa conferir a Operation real de inscrição; o helper não transforma uma string em autorização nem expõe um endpoint público para aprovar JSON.

**Clones diferenciais continuam recusados.** O novo código não relaxa o parser para filhos nem alega validar uma cadeia inexistente. Para habilitá-los depois, será necessário fixar e verificar todos os pais imutáveis por conteúdo, UUID/vínculos e localização, mantendo uma folha gravável com identidade própria.

Candidato real, **não aplicado**: `.tmp/astra-windows-storage-candidate.json`, SHA-256 do registro **`b307ba8d67b4e2d6f14fce62d437e6c53f971ab1c12fff78c070fbeeb775a8f3`**, UUID do VDI **`b423c056-076a-4d06-8623-4b81cee08b08`**, fingerprint estrutural **`87907108f084d019247493a07b8ec405fe015cb99d4dbc043d925eb639eccb58`**. A coleta desse candidato não criou inscrição nem Operation de aprovação e não afirma ter desbloqueado a versão carregada do runtime.

Antes de ativar: a integração do host deve persistir o envelope por uma ação de configuração autorizada e auditada, vinculada ao proprietário/WorkItem/VM, conferir a referência canônica de aprovação e ocultar `storage_binding` da projeção pública de campos da VM. Não usar escrita SQL avulsa, aprovação gerada pelo modelo ou o recibo de simples diagnóstico como aprovação de mudança. Esse wiring de inscrição permanece para revisão do responsável pela integração.

### Próxima intervenção proposta para revisão

1. Revalidar VM, conversa vinculada, WorkItem e Grants atuais; registrar a captura e o candidato exato de armazenamento. A posse antiga expirada não autoriza input novo.
2. Se aprovado pelo responsável, obter posse humana temporária e enviar **uma única** combinação Shift+F10 pelo ControlPlane (`input.key`, set 1: `[42,68,196,170]`). Essa ação solicita o console de diagnóstico WinPE e preserva a instalação; não é reset. Observar uma captura nova antes de digitar qualquer comando. Recibo de input enviado não comprova que o guest processou a tecla.
3. Somente com prompt confirmado, executar leituras delimitadas de `tasklist` e dos logs Panther nas localizações reais do WinPE/volume Windows, usando o caminho de input existente. Não fornecer comandos antecipadamente a uma tela cuja identidade ainda não foi confirmada. Resultado incerto não permite repetir teclas/comandos.
4. Se não houver resposta, revisar uma nova pausa/retomada delimitada pelo CP como experimento reversível de agendamento. Antes, reconciliar o registro anterior de pause/403 e verificar Grant `vm:manage`; não reenviar sua chave nem usar VBoxManage fora da central. Pausa/retomada não tem eficácia demonstrada e precisa de capturas/atividade antes e depois. Reinício, troca de CPU/hipervisor e boot por outra mídia ficam para decisão posterior com evidência adicional.

Nenhuma dessas intervenções físicas foi executada nesta continuação. Após o Setup voltar a avançar: OOBE/desktop → boot persistente → Guest Additions/GuestControl → inscrição da identidade limitada → probe com recibo → Setup SENTRA atual e validação de serviços/reinício/autenticação → Federation host/guest com tarefa e artefato.

### Verificação ampliada

Comando: `python -m pytest tests/unit/test_windows_dot_isolation_storage.py tests/unit/test_virtualbox_installation.py tests/unit/test_virtualbox_bootstrap.py tests/unit/test_windows_dot_isolation.py tests/unit/test_windows_dot_isolation_probe.py tests/unit/test_guest_execution.py tests/unit/test_input_automatic_acquisition.py -q`

Resultado: **185 aprovados, 1 ignorado**. O ignorado é a criação de symlink, sem privilégio disponível; não foi solicitada elevação. Casos de hardlink e substituição durante leitura foram efetivamente executados. Os VDIs dos testes são pequenos arquivos sintéticos temporários. A regra foi também exercitada contra a VM real apenas para gerar o candidato sem aplicação. `git diff --check` dirigido passou. Não foram editados `virtualbox_vm.py`, MachineHost, effect boundary ou configurações produtivas.

## Continuação: inscrição autenticada e aprovação canônica

Foi implementado `sentra_executors/virtualbox_storage_enrollment.py`. Nesta fase, **nenhum candidato real foi inscrito** e nenhum input foi enviado. O módulo oferece os callbacks e o dispatcher para o responsável conectar ao serviço autenticado; `service.py` e `__main__.py` não foram alterados nesta frente.

### Contrato das ações

Ambas usam o endpoint existente autenticado `POST /api/shell/bridge`, ação externa `dot_vm_execute`, seletores exatos de projeto/espaço/Dot/conversa e `request_key` durável:

```json
{"action":"storage.candidate"}
```

É a ação interna de observação, com Grant `vm:observe`. Resolve somente a raiz da VM configurada e o diretório SENTRA de AppData derivado pelo host. A resposta pública contém UUIDs, capacidade, slot e `candidate_sha256`; não contém caminho, file IDs, marcador, registro privado nem autorização. Raízes adicionais, quando necessárias, são dependências do host, nunca argumentos da interface/modelo.

```json
{"action":"storage.enroll","expected_candidate_sha256":"<64 caracteres hexadecimais minúsculos>"}
```

É a ação interna de metadados, com Grant `vm:manage` e **escopo nativo do proprietário autenticado**, vinculado ao hash revisado, projeto, raiz do Dot, conversa e Operation. Não aceita `approved`, `owner`, caminhos, file IDs ou um registro de aprovação enviado por JSON. O escopo não cria Grant e expira em 30 segundos. Um agente com `vm:manage` continua impedido de inscrever armazenamento sozinho.

`storage_enrollment_policy` restringe a política existente antes da reserva e em cada checkpoint. Revisão ausente ou de outro escopo é recusada antes do efeito. `enroll_owned_storage` exige o `CentralEffectContext` real do mesmo ControlPlane/proprietário, WorkItem ativo e marcador `effect_started`, recompõe o candidato atual e compara seu hash. Grava uma única configuração protegida por compare-and-swap do corpo anterior; alteração concorrente é preservada e causa recusa. Não modifica VM, anexo ou VDI.

O registro gravado fica **pendente de ativação** até sua própria Operation terminar em `SUCCEEDED`, com evidência protegida canônica. O callback `verify_owned_storage_approval` recupera o artefato pelo `CentralDurableIntentAuthority` e verifica proprietário, Run, máquina, capability, hash da intenção exata `storage.enroll`, hash do registro, UUIDs e escopo. Uma string de Operation, uma Operation de status, JSON solto, recibo incerto ou artefato adulterado não ativam o binding. Falha após o início do efeito conserva `UNCERTAIN` e exige reconciliação; não há repetição automática nem promoção por late return.

### Wiring para a revisão do responsável

1. Em `configure_virtualbox_machine`, manter `store.policy` e envolvê-la com `storage_enrollment_policy`, passando o ControlPlane, proprietário, projeto e root já derivados pelo host. Fazer isso antes de construir/registrar o executor.
2. Obter `enroll, verify = storage_enrollment_callbacks(...)` com esses mesmos seletores confiáveis e fornecê-los nos campos opcionais `VirtualBoxBinding.storage_enrollment` e `storage_approval`. Sem os callbacks, inscrição/ativação são recusadas.
3. **Somente no ramo do proprietário autenticado de `service.py.shell_bridge`**, quando a ação externa for `dot_vm_execute` e a ação interna for `storage.enroll`, usar `dispatch_owner_storage_enrollment(self._shell_dot_vm, project_id, params, request_key)` no lugar do dispatch direto. As outras ações mantêm o caminho existente.
4. Não instalar esse escopo em `ShellActor`, no dispatcher genérico do modelo ou em `DotVmServices.dispatch` compartilhado. Esse cuidado separa autenticação do proprietário de capability do agente. O helper reutiliza a resolução de escopo e o `ShellHostRequests` existentes; não há nova fila, journal de autoridade ou endpoint HTTP.
5. A chave `storage_binding` **já foi acrescentada** a `_VM_HIDDEN_KEYS` em `shell_dot_vm.py`; um teste executa a projeção pública real e confirma ausência do registro, caminhos e file IDs. Essa alteração é somente a ocultação; o wiring de fábrica/serviço acima ficou para revisão e integração do responsável.

### Arquivos centrais tocados nesta fase

- `virtualbox_vm.py`: ações tipadas `storage.candidate`/`storage.enroll`, validação exata do hash e dois callbacks opcionais no binding confiável.
- `virtualbox_installation.py`: mantém o gancho anterior em `owned_storage`; o novo caminho exige agora callback de aprovação canônica, sem fallback se a validação falhar.
- `shell_dot_vm.py`: somente inclusão de `storage_binding` na lista de campos privados nesta fase.

Não foram alterados MachineHost, effect boundary, `service.py` ou `__main__.py`. As diferenças maiores já existentes nos arquivos centrais não são todas desta frente; não foram revertidas nem substituídas.

### Evidência de integração

`tests/unit/test_windows_dot_isolation_enrollment.py` usa ControlPlane SQLite, VmStore, MachineHost, políticas, fences, lock de efeito, journal ShellHostRequests e artefatos DPAPI reais, com um cliente de hipervisor sintético e VDIs temporários. Verifica o transporte do escopo nativo entre threads, resultado canônico recuperável, autoaprovação bloqueada, revogação, posse humana, candidato trocado, alteração concorrente, falha após escrita, referência falsa/adulterada, repetição sem novo efeito e ausência de paths/file IDs na projeção pública real. Não é uma prova de inscrição executada na VM física.

Suíte combinada atualizada: **207 aprovados, 1 ignorado**, incluindo instalação/bootstrap/GuestControl/input/probes/storage. O ignorado continua sendo a criação de symlink sem privilégio; hardlink e corrida de substituição foram executados. `git diff --check` dirigido passou. O contrato de integração está pronto para review; a configuração produtiva permanece sem inscrição aplicada.

Verificações posteriores: **48 testes de `test_shell_dot_vm.py` e `test_shell_dot_computer.py` passaram**. Também passaram dois testes dirigidos da recusa antes do efeito quando os callbacks estão desabilitados e do percurso positivo com aprovação canônica. No binding padrão, `storage.enroll` é recusado na validação até os dois callbacks do host estarem configurados.

Revisão adicional da autoridade: inscrição e aprovação exigem Operation de mutação `sentra.machine`; uma Operation de observação ou cleanup não serve como aprovação. O contexto também exige Run atualmente `RUNNING`, incluindo leitura posterior do binding. **25 testes de inscrição passaram** após essa revisão. Dois deles exercitam admissão central real com classificação interna incorreta como observação/cleanup e comprovam ausência de escrita de configuração e de chamadas ao hipervisor sintético. Esse resultado dirigido complementa a suíte combinada anterior; não representa nova execução da VM física.

### Integração do responsável no host

O wiring pendente acima foi integrado em `shell_dot_vm.configure_virtualbox_machine`: a política restringe a política original e os dois callbacks recebem proprietário/projeto/root derivados do host. Em `Canvas.shell_bridge`, somente o ramo do proprietário autenticado instala o escopo para `storage.enroll`. `ShellActor` e `DotVmServices.dispatch` compartilhado não recebem essa autoridade. Não há flag `approved` aceita do renderer.

`tests/unit/test_shell_storage_enrollment_http.py` usa a fábrica de produção e o HTTP real: candidato público sem paths, 401 sem gravação, inscrição autenticada, recibo canônico, repetição da mesma chave sem novo efeito e leitura do plano com o binding aprovado. O dispatcher compartilhado com Grant de agente continua recusado, e flags extras são rejeitadas. Somente o hipervisor e o pequeno VDI são sintéticos; nenhuma chamada de mutação ao hipervisor ocorre.

Comando: `python -m pytest tests/unit/test_shell_storage_enrollment_http.py tests/unit/test_windows_dot_isolation_enrollment.py tests/unit/test_shell_dot_vm.py tests/unit/test_shell_dot_computer.py -q`

Resultado: **76 aprovados em 167,41 s**. Evidência em `.tmp/astra-storage-owner-http-tests.log`. Esse wiring ainda não foi aplicado ao broker instalado, nenhum candidato real foi inscrito e nenhum input ou disco real foi alterado. A inscrição futura exige revalidar o candidato e as autorizações atuais; o diagnóstico anterior não funciona como aprovação.

## Intervenção autorizada e observação real — 15/10, 14h UTC

Os parágrafos anteriores descrevem a entrega dos módulos antes das intervenções abaixo. Nesta continuação, somente input virtual e uma pausa/retomada foram efetivamente realizados pelo broker existente e pelo Control Plane; **o binding de armazenamento continua sem inscrição real**. Nenhum reset, reanexo, formatação, mudança de hardware ou alteração de hipervisor do host foi feita.

1. Captura canônica `op-shell-4d2ea738d73b396d7d23867468614f5853eebf20`: Setup ainda em 72%, hash `49ea2b78…`, Guest Additions runlevel 0. Posse humana antiga epoch 7 estava expirada.
2. Nova posse humana epoch 8; **um único Shift+F10**, Operation `op-shell-40d0ca3eb2d8adabdd76f8a000b73b294104e0c9`, `SUCCEEDED`. As duas capturas imediata/posterior ainda eram idênticas. Não se repetiu a combinação nem se digitaram comandos sem console. Posse devolvida ao agente, epoch 9.
3. O registro antigo `qa-win-stall-pause-e8465c61fb93408e9430fefda8334b5c` contém `AuthorizationRequired`, recibo incerto e nenhuma Operation canônica para sua identidade derivada. Evidência somente de leitura em `.tmp/astra-windows-pause-history.json`; não se alterou esse recibo nem se repetiu sua chave.
4. Novo experimento delimitado: pause `op-shell-ed0ae18d7b26d90c9b1adbf14aa480fee2834132` e resume `op-shell-5b88b41290ad1ce3492571ffaae8d84824a10731`, ambos `SUCCEEDED`, com estado `paused` verificado entre eles e `running` ao final. A captura seguinte mostrou **73%**, hash `33e1224c…`. Isso é avanço observado após o experimento; não demonstra que a instalação inteira voltou a progredir continuamente.
5. A observação seguinte `op-shell-0c9529082e84fdf2c43a464320530bebd3150a4e` mostrou o console WinPE `X:\Sources>`. Portanto o Shift+F10 anterior acabou sendo processado; não houve nova combinação. Seis observações delimitadas foram salvas em `.tmp/astra-windows-watch/report.json`.
6. Com o console confirmado, nova posse humana epoch 10. `tasklist` foi digitado uma vez (`op-shell-a407cd90d06cdd3d6b6cb2eaf9f422b14cc346ca`) e apareceu na captura. Enter foi enviado uma vez (`op-shell-4353e274d782d366902167dfd9c61e8bd10b873e`). As capturas seguintes ainda não exibiam saída nem novo prompt; **execução do comando no guest permanece não comprovada**. Não se repetiu Enter ou se digitou outro comando. Posse devolvida ao agente, epoch 11.

Houve um HTTP 500 numa captura concorrente ao observador; não se repetiu o input. Uma captura independente do mesmo período mostrou `tasklist` corretamente digitado, e as leituras seguintes funcionaram. A causa desse erro de captura ainda precisa de análise; o journal preserva a chave original.

Evidências: `.tmp/astra-windows-checkpoint/`, `.tmp/astra-windows-console/`, `.tmp/astra-windows-reschedule/`, `.tmp/astra-windows-watch/` e `.tmp/astra-windows-readonly-console/`. Journals registram intenção antes do transporte e conservam respostas; fases sem resposta exigem observação, não replay. Os scripts são diagnósticos locais, não substituem uma instalação homologada.

### Semântica da captura corrigida

O código novo de `VirtualBoxClient.frame` comprova `framebuffer_verified:true`, com `desktop_verified:false` e `installed_os_verified:false`. Uma imagem de BIOS, WinPE ou Setup não comprova desktop instalado. O CLI aceita o marcador antigo de captura para compatibilidade, mas normaliza sua projeção ao modelo para não afirmar instalação. Um marcador novo explicitamente recusado não ganha fallback pelo legado. A correção passou nos testes de captura/CLI/persistência (**33 aprovados**) e ainda precisa ser carregada pelo próximo broker; os recibos antigos não foram reescritos.
