# Dot ↔ Canvas ↔ VM — integração e evidências de 14/10/2026

Esta nota descreve o avanço desta rodada; não equivale à homologação física da VM, da instalação Windows ou da federação.

## Implementado no código

- sentra_canvas/shell_dot_canvas.py: o terminal do guest agora usa Session real do Canvas com saída recuperável e persistente. Linhas concluídas são enviadas pelo fluxo autorizado dot_vm_execute → guest.run. Resultado incerto não é marcado como sucesso, nem repetido automaticamente.
- A abertura de terminal exige uma única conversa do Dot vinculada a um WorkItem de VM. Zero ou múltiplos vínculos retornam bloqueio explícito, sem fallback ao shell do host.
- sentra_executors/virtualbox_vm.py: guest.run resolve o VirtualBox GuestControl pelo registro confiável e somente com Guest Additions runlevel 2/3, mantendo a autoridade central.
- sentra_canvas/shell_dot_vm.py: status apresenta guest_control.ready, runlevel e motivo de indisponibilidade sem divulgar segredos.
- sentra_canvas/desktop_ui/src/shell-dot-vm.jsx: estado do canal visível. Quando a VM física já existe, vincular a conversa não emite outro provisionamento.

## Verificações

- 102 testes Python selecionados passaram no Windows autorizado. Nova repetição de 21 testes do roteamento também passou.
- Vite compilou o frontend para o diretório isolado .tmp/guest-ui-build-20261014, sem publicação dos assets na UI ativa.
- git diff --check dirigido passou.
- Docker não disponível para execução isolada do SENTRA; testes locais via Desktop Commander sem mudar sua política.
- O SENTRA MCP está conectado e responde.

## Host e VM verificados somente em leitura

- Uma VM VirtualBox registrada como Windows 10 (64-bit), 2 vCPU e 4096 MiB, com VDI e ISO anexados; VMState=aborted.
- Cadastro protegido do SENTRA contém um registro correspondente com provisioning_status=installation_started e zero conversas vinculadas a WorkItem.
- Windows.iso existe em Isos. Nenhum Windows instalado, Guest Additions, desktop ou instalação limpa foi confirmado.
- Nenhuma VM/VDI foi iniciada, clonada, apagada ou reinstalada. Nenhuma Operation UNCERTAIN foi repetida.

## Aceite físico restante

1. Pelo computador da conversa pretendida do Dot, vincular a VM existente sem reprovisionar. Confirmar WorkItem, Grant, proprietário e posse de teclado.
2. Reconciliar o histórico original de instalação antes de admitir um novo efeito. Iniciar somente uma operação nova, nunca repetir a chave incerta.
3. Observar desktop Windows e Guest Additions runlevel 2/3 através do Canvas.
4. Enviar uma instrução curta ao guest via terminal do Canvas e conferir Operation SUCCEEDED, witness guestcontrol, stdout recuperado, persistência e ausência de execução substituta no host.
5. Executar o SENTRA Setup completo em Windows limpo; testar instalação, MCP, túnel, atualização e retomada por artefatos e recibos.
6. Homologar federação entre duas instalações com paridade de identidade, transmissão e execução útil. A federação atual só resolve aritmética delimitada; outros objetivos ainda não são prova de executor cognitivo remoto.

## Limitações

- O código novo ainda não foi carregado no broker/UI ativa: não reiniciar sem reconciliação.
- Terminal guest usa comandos por linha, não um PTY remoto persistente. Modelos de longa duração exigem execução assíncrona durável/streaming e prova real.
- Múltiplas conversas autorizadas para o mesmo Dot exigirão seleção explícita do vínculo.


## Execução real em 14/10 — diagnóstico e bloqueio de autoridade

- Associação física verificada: UUID VirtualBox b1a7b455-5800-414f-b095-e923c49efb6c; Dot testegpt6, projeto Oxta. O registro anterior usa a chave artificial dot-windows10-validation, ao passo que o root canônico é dot-7634e5106b837733bcb932682ad2e14a. O cadastro original não possuía agent_id nem work_items.
- Conversa selecionada: conversation-7bba7abb9191d2d4578b82d16800539b, a mais recentemente atualizada daquele Dot. O broker autenticado consultou status da conversa: adoption_required=true; VMState=aborted; guest_control.ready=false; mesmo UUID físico; sem WorkItem.
- Adoção controlada implementada em VmStore.legacy/adopt_legacy e DotVmServices._configure: exige candidato único, valida UUID/description/hardware no hypervisor e move a reserva existente para o root canônico, preservando UUID, marcador, senha protegida, estado do provisionamento e VDI. Não cria nem reexecuta VM. Testes de adoção positiva e recusa de marcador divergente passaram.
- 105 testes Python direcionados aprovaram; git diff --check aprovado. Build completo da UI aprovado e materializado em sentra_canvas/static/desktop-assets e desktop.html.
- Broker autenticado atualizado via /api/runtime/shutdown com confirmação, seguido de connect_or_start; runtime anterior e novo foram distinguidos, o broker voltou operacional. Não havia terminais ou tarefas running na projeção de nenhum dos três projetos no momento da atualização.
- A chamada autenticada de dot_vm_configure que efetivaria a migração e criaria o WorkItem foi barrada pela segurança da ferramenta remota. NÃO executar caminho alternativo que burle esse bloqueio e NÃO declarar adoção realizada.
- Verificação posterior em banco read-only: permanece exatamente um shell_dot_vms, com chave dot-windows10-validation, agent_id ausente, zero WorkItems. VirtualBox segue VMState=aborted e sem running VM. Nenhuma instalação, boot, cópia, remoção ou teste de modelo físico foi executado nesta etapa.
- Próximo operador autorizado: abrir no SENTRA a conversa testegpt6 indicada, painel Computador do Dot → Configuração → Vincular esta conversa à VM; observar retorno de dot_vm_configure com o mesmo UUID, registro movido e WorkItem/Grants próprios. Comprovar a autorização e inspecionar o histórico de instalação antes de autorizar dot_vm_execute(start). Se a interface estiver desatualizada, recarregar a janela do SENTRA antes dessa operação. Não clicar em provisionar/criar outra VM e não reenviar Operations incertas.


## Botão Atualizar e uso imediato — 14/10, 11h

- Causa: a UI anterior executava somente npm/Vite e reload do WebView, mas o binário de desenvolvimento em dist/sentra-canvas.exe era de 13/10; backend PyInstaller permanecia inalterado. O estado frontend_stale=false não prova versão instalada atualizada.
- Novo WindowControls: check_full_updates / apply_full_updates e origem do checkout verificada mesmo quando o processo é frozen. Caso não exista checkout, exige pacote instalado assinado.
- Novo native_refresh.check_all/apply_all: distingue código local e executável instalado; aplica frontend se necessário; verifica Durable owner, relay e inventário de terminais/tasks do Canvas, não repete ações; reinicia somente broker via /api/runtime/shutdown autenticado, com mesma porta e prova de novo runtime_id e /api/health. Não derruba CLIs, VMs, MCP, browser relay, tunnel. Nunca diz ter instalado nova versão binária.
- O ícone principal Atualizar agora executa a rotina local diretamente; opção secundária mostra Atualizar dados, código da interface e versão instalada. Estado do resultado após reload é persistido em sessionStorage para aviso visível.
- Testes nativos de atualização foram adicionados em tests/unit/test_native_refresh_all.py. Testes Python e build Vite aprovados na rodada. Foi comprovado no host um apply_all real: status=local_code_updated; broker_restarted=true; frontend=unchanged; installed_version_changed=false. Mesmo endereço loopback preservado.
- Janela frozen antiga (dist/sentra-canvas.exe) foi fechada normalmente após preflight seguro, sem Stop-Process. Uma janela fonte foi aberta via pythonw -m sentra_canvas e confirmada por título SENTRA. Dados e VM preservados.
- A tentativa de compilar novo sentra-canvas.exe via scripts/commander/build_canvas.py --phase canvas falhou por require_wasmtime_pin: SENTRA_BUILD_RUNTIME_PINS_FILE ausente. Não contornar essa exigência de licença/assinatura/proveniência. Logo a **versão instalada** não mudou; o código-fonte e o broker estão atuais para QA físico.
- A vinculação física do registro legado Windows para o Dot continua sem WorkItem: não repetir provision nem escrever banco diretamente. A chamada de mutação remota foi bloqueada por segurança e deve ser feita pela interface autenticada admitida pelo usuário.
