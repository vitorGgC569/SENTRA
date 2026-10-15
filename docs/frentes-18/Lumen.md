# Lumen — frentes 8 e 9

Data: 2026-10-12. Checkout: `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Sem commit, push, reset ou clean.

## Escopo

Frente 8: Home com Dots recentes, projetos em execução, aprovações, entregas, falhas, busca, estado vazio e retorno à última superfície de trabalho. Canvas com planejamento, execução, espera, revisão, conclusão, falha e operação incerta, com responsável, dependência, progresso, recibo e próximo passo. Painel do computador do Dot com visão, posse do teclado, terminal, arquivos, desempenho, cópia importada e energia. Falha autoexplicativa, sem reenvio. Tokens de design no shell.

Frente 9: ícone do Dot, atalho, identidade de barra de tarefas, instância única e recuperação de janela no display Electron, instalador de desktop distinto do Commander, e versão instalada distinta de atualização de dados e de compilação local da interface.

O protocolo Python do shell não foi alterado. `uninstall.ps1` não foi executado. Nenhum Dot, VM, VDI, conversa, `.sentra` ou `.oma` foi apagado.

## Código neste checkout

- `sentra_canvas/desktop_ui/src/shell-home-board.js`, `shell-home-board.jsx`: Home sobre o payload `home` já existente.
- `sentra_canvas/desktop_ui/src/shell-navigation.js`: última superfície de trabalho. A Home não apaga essa memória.
- `sentra_canvas/desktop_ui/src/shell-canvas-state.js`, `shell-dot-canvas.jsx`: sete fases, legenda e apresentação da tarefa.
- `sentra_canvas/desktop_ui/src/shell-failure.js`, `shell-failure.jsx`: motivo e consulta. `resend` permanece falso.
- `sentra_canvas/desktop_ui/src/shell-computer-status.js`, `shell-computer-status.jsx`, `shell-dot-vm.jsx`: estado do computador dentro do painel já existente.
- `sentra_canvas/desktop_ui/src/shell-updates.js`, `shell-app.jsx`: três comandos. Dados só consultam. Código local usa `check_code_updates` / `apply_code_updates`. Versão instalada não consulta dados nem compila.
- `sentra_canvas/desktop_ui/src/shell-design-tokens.js`, `desktop.css`: escala usada pelas superfícies novas.
- `sentra_canvas/desktop_ui/src/qa/lumen-flow.html`, `lumen-flow.jsx`: harness de interface. Não entra no entry de produção.
- `sentra_electron/policy.cjs`, `main.cjs`, `SENTRA-DOT.ico`: lock, restauração de bounds, ícone do Dot com fallback `SENTRA.ico`. O AUMID do display continua `SENTRA.Desktop.Electron`.
- `scripts/commander/stage_electron.py`: o pacote staged exige e copia `SENTRA-DOT.ico` junto de `SENTRA.ico`.
- `installer/windows/install-desktop.ps1`: instala fora de `.sentra`, `.oma`, `dot-vms` e `virtualbox`. Não apaga dados. Mesma versão não reescreve. Versão diferente exige `-Upgrade` e conserva `installation_id`.

## Teste unitário executado agora

Comando, a partir dos arquivos do checkout:

```text
node --test sentra_canvas/desktop_ui/test/shell-navigation.test.mjs sentra_canvas/desktop_ui/test/shell-home-board.test.mjs sentra_canvas/desktop_ui/test/shell-canvas-state.test.mjs sentra_canvas/desktop_ui/test/shell-failure.test.mjs sentra_canvas/desktop_ui/test/shell-computer-status.test.mjs sentra_canvas/desktop_ui/test/shell-updates.test.mjs sentra_canvas/desktop_ui/test/shell-design-tokens.test.mjs
```

Resultado: **19 passed, 0 failed**, `duration_ms 409.5931`.

```text
node --test sentra_electron/test/desktop-identity.test.cjs sentra_electron/test/policy.test.cjs
```

Esses dois arquivos passaram dentro do lote de 5 testes Electron abaixo. Eles não abrem janela: cobrem bounds, papel da instância, ícone candidato, AUMID distinto e handoff de loopback. Isso não é a janela nativa do Dot e não é o atalho do usuário.

## Prova física contemporânea

Instalador, em diretório temporário sob `%LOCALAPPDATA%\SENTRA-lumen-install-test`, apagado ao fim. Não usou `-Launch`, não chamou `uninstall.ps1` e não gravou o Desktop real:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File installer/windows/test-desktop-install.ps1
```

Resultado: `SENTRA_DESKTOP_INSTALL_OK installation_id=e099a431-f1da-42a3-9ed6-1fbba03d3a83`.

O script criou `installation.json` com `kind=installed_update`, `code_reload=false`, `data_refresh=false` e sem `frontend_stale`. Copiou `SENTRA-DOT.ico`. O atalho no diretório temporário apontou para o executável fictício e a descrição foi `SENTRA`. A mesma versão devolveu `apply:false` e manteve o id. `0.9.0` sem `-Upgrade` foi recusado e não mudou o marcador. `-Upgrade` para `0.2.0` manteve o id. Caminhos com `.sentra`, `.oma` e `virtualbox` foram recusados. O id acima existiu só nessa árvore temporária e foi removido com ela. Não é uma instalação nesta máquina.

Display Electron, processo real com ticket descartável e Canvas de fixture em `127.0.0.1`:

```text
node --test sentra_electron/test/isolation.test.cjs
```

O lote `desktop-identity` + `policy` + `isolation` deu **5 passed, 0 failed**, `duration_ms 1712.6624`. O teste de isolamento exige `SENTRA_ELECTRON_ISOLATION_OK`, sandbox, sessão não persistente e pop-up negado. Não exercitou uma segunda instância nem leu o ícone da barra de tarefas.

Build de produção do desktop, único `npm run build` desta frente:

```text
npm run build
```

em `sentra_canvas/desktop_ui`. Vite 8.3.4 concluiu em 6.33s e o materialize gravou `sentra_canvas/static/desktop-assets/`. O `desktop.js` e o `desktop.css` gerados contêm `Dots recentes`, `Atualizar código local`, `Versão instalada`, `Operação incerta`, `Você tem o teclado`, `shell-home-board` e `shell-phase-legend`.

Interface, no Edge headless 154, página `http://127.0.0.1:4178/src/qa/lumen-flow.html` servida do fonte com `vite --base /`. Não é o shell do broker. Cliques reais no DOM:

- Continuar registrou `continue:canvas`.
- O primeiro Dot recente, Nara, registrou `dot:d2`.
- O projeto em execução registrou `space:s1`.
- Abrir a aprovação registrou `approval:c1`.
- A busca `zzzz-sem-resultado` mostrou o vazio; a busca `Nara` deixou Nara e tirou Atlas.
- Consultar estado registrou `failure:consult resend=false`. Dispensar removeu o aviso.
- Atualizar dados: `reload=false install=false compile=false`.
- Atualizar código local: `reload=true install=false compile=true`.
- Versão instalada: `apply=false`. O aviso foi: "A versão instalada só muda pelo instalador do Windows. Este comando não atualiza dados nem recompila a interface. Não há marcador de versão instalada nesta janela. A troca fica no instalador e não mexe em dados, VMs ou conversas."
- A legenda mostrou 7 fases. A tarefa ficou `data-resend=false`.
- Em 1280 px as colunas da Home foram três faixas; em 390 px, uma faixa.

O log não contém `resend=true`.

## O que não está homologado

- O shell de produção não foi clicado contra um projeto, o broker, um Dot ou uma VM. O harness usa fixture.
- Pausar, desligar, assumir teclado, terminal real e cópia para o guest não foram executados. A faixa de estado foi conferida com dados de fixture. Os botões já existentes do painel não foram acionados.
- A segunda instância Electron e a restauração física da janela não foram lançadas. `recoverBounds` e `instanceRole` são teste unitário. A janela nativa do Dot e o mutex `Local\SENTRA.Dot.Native.Window` já existiam em Python e não foram reexecutados.
- O stage copia `SENTRA-DOT.ico` no teste unitário do payload. Não houve publicação do instalador Windows nem conferência do ícone na barra de tarefas do pacote instalado. No fonte, o display procura `SENTRA-DOT.ico` e cai para `SENTRA.ico` se o arquivo não estiver ao lado de `main.cjs`.
- O instalador não foi aplicado ao Desktop, ao Menu Iniciar nem a uma máquina limpa. O AUMID foi gravado no atalho temporário; o teste leu alvo e descrição, não releu a propriedade de AUMID.
- A janela não lê `installation.json`. O botão de versão não aplica bits. `apply:true` aparece no teste unitário de `versionDecision` e na escrita temporária do `-Upgrade`.
- Smart UI não foi refeito. Nenhuma operação UNCERTAIN foi reenviada. Nenhuma prova que apaga Dot, VM, VDI ou conversa foi tentada.

## Aditivo de 2026-10-13

A rede de Dots entra na superfície pelo renderer `presentNetwork` / `NetworkSurface`, schema 1, a partir de `sentra_federation/network_view.py`. A janela mostra Dot, convite, conversa, Canvas e bind. `physical_proof`, `vpn_is_authorization`, `public_bind`, `database_exposed` e `image_installer` ficam falsos mesmo se o documento pedir o contrário. A tela não escuta, não autoriza e não serve banco. Dois processos no loopback não são duas máquinas. O protocolo Python do shell não foi alterado, então o payload `home` ainda não traz o documento vivo: sem `home.network` a rede aparece vazia. Não homologado.
