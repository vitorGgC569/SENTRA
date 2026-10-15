# Arquitetura proposta: VM Windows persistente com um usuário por Dot

Data: 14/10/2026. Status: proposta técnica; nenhuma VM ou conta foi migrada nesta rodada.

## Topologia e objetivo

O modo atual usa VM exclusiva por Dot. Adicionar, de forma opcional e opt-in, o modo shared_windows_user: uma VM Windows persistente com UUID físico único, e uma conta local não-administradora separada para cada Dot. O Dot permanece associado à própria conversa, WorkItem, Grants, SID, perfil e diretório privado. Não alterar automaticamente os registros atuais.

SENTRA host/Canvas -> VM Windows compartilhada -> conta Dot A, conta Dot B, conta Dot C. Cada conta possui SID e perfil de usuário, workspace, credenciais, processo e recibos próprios. A VM tem uma máquina física e reserva de CPU/RAM compartilhadas, não uma VM criada para cada conta.

## Benefícios e limites

Reduz instalação repetida do Windows, VDI base, RAM fixa do sistema operacional e custos de provisionamento. A vantagem é maior em repouso ou com uso alternado. Não transforma uma máquina em recursos suficientes para 91 Dots simultâneos: todos compartilham CPU, memória, disco e atualizações do sistema. A VM passa a ser ponto único de falha.

Windows 10/11 cliente não deve ser tratado como servidor de múltiplos desktops gráficos interativos simultâneos. Compartilhar a VM implica serializar o desktop/console com um lease exclusivo, mesmo que vários processos CLI possam executar sob contas Windows distintas. Para desktops simultâneos independentes, avaliar Windows Server com RDS e licenciamento apropriado, sem alterações não suportadas no Windows cliente.

Isolamento por conta é inferior a isolamento por VM: contas compartilham kernel e administradores. Para plugins não confiáveis, instalações de driver, tarefas hostis ou ambientes multitenant sem confiança, manter VM dedicada ou clone descartável.

## Contratos de segurança

1. Mapeamento de identidade permanente: dot_id -> guest_account_id -> Windows SID atestado. Nomes visíveis não autorizam acesso.
2. Conta padrão sem administrador por Dot. ACL NTFS efetiva para perfil, workspaces, arquivos e credenciais; testes negativos de acesso cruzado.
3. Segredos protegidos por conta, autenticação individual e revogação. Nenhuma senha única compartilhada pelos Dots.
4. Cada vm:guest requer WorkItem, Grant vigente, fence, identidade Windows da conta e recibo do processo físico. Sem execução substituta no host e sem repetição automática de UNKNOWN/UNCERTAIN.
5. Separar machine_id (VM física) de guest_account_id (recurso lógico); orçamento global da VM agregado, cotas por Dot por Job Object, tempo, CPU, RAM e disco onde suportado.
6. Framebuffer e input.key pertencem ao lease exclusivo de desktop, com epoch e comprovação de mudança de usuário/limpeza de clipboard. Não permitir captura da tela de outro Dot.
7. Boot, shutdown, snapshot, Guest Additions, instalação global e modificação de hardware pertencem ao administrador da VM, não ao Grant individual de um Dot.
8. Exclusão de Dot arquiva e revoga só sua conta, processos e perfil mediante confirmação. Não apagar o disco da VM de todos.

## Clean install e Federation

A VM compartilhada deixa de ser limpa depois de configurada. Antes de instalar SENTRA, manter uma base Windows homologada e usar clone descartável com disco diferencial para testar Setup; não fazer rollback destrutivo de VM compartilhada em uso. Federation precisa de dois runtimes/identidades de SENTRA e comunicação real, preferencialmente host ↔ guest; duas contas dentro da mesma VM não substituem prova de rede entre máquinas independentes.

## Fases de implementação

0. Pré-requisito: concluir instalação Windows atual, Guest Additions e comando real Dot → Canvas → VM com saída e Operation SUCCEEDED. Hoje a VM está desligada com Windows.iso montada, sem Windows instalado comprovado.
1. Contrato de modo de execução: dedicated_vm (atual) vs shared_windows_user (novo), registro SharedVm/GuestAccount, SID, quotas, permissões e migração opt-in preservando registros antigos.
2. Serviço convidado confiável: criar contas sem administrador, conferir SID, criar workspace privado e ACL, gerenciar credenciais por conta. Registrar recibos reais.
3. Execução e posse: executar GuestControl/worker na conta Dot com WorkItem e fencing; renderizar terminal/saída persistente no Canvas; lease exclusivo de desktop e handoff serializado.
4. Restrições e interface: cotas de processos, Job Objects, priorização, suspensão por Dot sem desligar a VM para todos, UI por conta e status de disponibilidade.
5. Homologação física: dois Dots com SIDs e perfis diferentes, impossibilidade de leitura cruzada, tarefas CLI concorrentes dentro dos recursos disponíveis, desktop exclusivo, retomada pós-reboot, revogação e Federation em runtimes separados.

## Critérios de aceite

Recibos físicos identificando SID e guest_account_id, stdout de cada processo entregue à conversa correta, nenhum compartilhamento de segredos, estados incertos preservados sem replay e limites de recursos mensurados. Testes unitários não bastam; exigir provas reais e persistentes.

Esta rodada não criou contas, não alterou a VM, não instalou Windows, não modificou ACLs e não migrou os Dots. Apenas especificou a arquitetura futura, separada da correção do bearer na UI.
