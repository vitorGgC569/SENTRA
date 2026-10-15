# Homologação física Windows / SENTRA Setup / Federation — 2026-10-14

## Estado comprovado nesta rodada

- Máquina autorizada: OGrandeOxta; VM Windows UUID b1a7b455-5800-414f-b095-e923c49efb6c, Dot vinculado com WorkItem e Grants existentes.
- Lease central de VM: ausente na checagem anterior ao boot. Operação de consulta Windows incerta antiga foi reconciliada como FAILED e preservada, sem reenvio.
- Novo boot admitido no Canvas pelo fluxo autenticado dot_vm_execute(start), request_key win-install-start-429bb7d782294610976d861dbb7423c5.
- Recibo central novo: op-shell-0d91d21b6d0fe42058b2d29e941074edd1b383c4; resultado SUCCEEDED, VMState=running.
- Captura física salva em .tmp/windows-installer-boot-check-20261014.png; tela de BIOS mostra explicitamente 'Pressione uma tecla para iniciar do CD ou DVD...' e depois 'Sistema operacional não encontrado'. A mídia Windows.iso é inicializável, mas ninguém pressionou a tecla dentro da janela temporal do BIOS.
- GuestAdditionsRunLevel=0; instalação do Windows NÃO comprovada; nenhum guest.run possível antes do guest OS.
- Tentativa de obter o teclado humano autorizado pelo fluxo dot_vm_handoff foi bloqueada pelas configurações de segurança da ferramenta remota. Não foi contornada com VBoxManage ou mutação fora do Control Plane. Boot está na tela de erro aguardando restart/tecla.

## Readiness do pacote

- dist/SENTRA-Setup.exe: 1.593.729.548 bytes, 2026-10-01, Authenticode=NotSigned, sem versão FileVersion/ProductVersion. É um artefato antigo.
- dist/sentra-canvas.exe: 2026-10-13, anterior às correções de 2026-10-14.
- Não existem dist/runtime-components.json, dist/build-provenance-canvas.json e dist/build-provenance-setup.json; a última auditoria de payload e release consta como falha. Não declarar Setup atual pronto.
- Runtime Wasmtime requer versão, checksums dos arquivos nativos, licenças avaliadas e SENTRA_BUILD_RUNTIME_PINS_FILE; a configuração aprovada não existe nesta máquina. QuickJS/HCS/RustDesk ainda exigem componentes materializados e proveniência verificada.
- Não executar Setup antigo no host como substituto da instalação em VM Windows limpa.

## Próximo desbloqueio prático do BIOS

Com a VM ligada, abrir o display pela interface autorizada do usuário (VirtualBox) e usar a ação de Reiniciar/Reset; assim que aparecer 'Pressione uma tecla para iniciar do CD ou DVD', pressionar Espaço no console, antes de expirar. Não formatar, particionar ou instalar sobre dados antes de verificar VDI existente. A tela do Windows Setup é somente o primeiro checkpoint, NÃO uma prova de Windows instalado.

## Aceite necessário

1. Windows Setup iniciou a partir da ISO, com framebuffer e recibo; particionamento/instalação somente após preservação de dados e autorização.
2. Desktop Windows operacional e Guest Additions funcional (runlevel 2 ou 3), reboot com ISO e VDI reconciliados.
3. guest.run retorna stdout real pela conversa do Dot via Canvas, com Operation SUCCEEDED e recibos de guestcontrol, nunca host subprocess.
4. Pacote SENTRA Setup do checkout atual é compilado em host estável com todas as dependências, licenças, hashes, assinatura/aprovação de distribuição e preflight de payload verde.
5. Setup atual instalado no guest, serviço/túnel/MCP do guest confirmados; Federation testada com duas instalações e identidades reais, handshake, troca de tarefas/respostas e recibos. O resolvedor Federation existente não equivale a execução genérica de modelos remotos.

## BIOS Windows: proof by centrally authorized virtual keyboard, 2026-10-14

- `VirtualBoxClient.input` uses `console.Keyboard.PutScancodes` and works before Guest Additions.
- Separate admitted Ctrl+Alt+Del and Space Operations both returned `input_sent=true`, but did not hit the short DVD BIOS key window. They were not replayed.
- New narrowly scoped action `input.bios_dvd` in `vm:input` is fenced by `shell_actor`: Windows guest running, DVD-first boot and IDE ISO are required, no arbitrary input fields allowed. Under the human input lease it sends Ctrl+Alt+Del then temporally spaced Space keypresses, without touching the VDI.
- Regressions `tests/unit/test_vm_bios_dvd_input.py` and `tests/unit/test_shell_dot_vm.py`: **45 passed**. `git diff --check` passed.
- Active Canvas broker was restarted after safe idle preflight; `local_code_updated`, `broker_restarted:true` verified.
- Keyboard possession was renewed via `dot_vm_handoff(holder=human)` to `epoch=2`.
- The real one-shot action produced Operation `op-shell-97e5323b8dc18eff81b25b2f038dd1e6a9156461`, state SUCCEEDED, evidence `input_sent:true`, `automatic_retry:false`, `windows_setup_verified:false` (until separately observed).
- Physical screenshot `.tmp/windows-after-timed-central-bios-input-20261014.png` captured the **Windows Installation** language screen (Portuguese, Portuguese Brazil, ABNT, Avançar) in VirtualBox. Therefore BIOS optical boot actually succeeded.
- No partition was formatted, no VDI was replaced, Windows is not yet installed, Guest Additions remain unavailable. The Windows Setup GUI is ready for subsequent inspection and installation.
