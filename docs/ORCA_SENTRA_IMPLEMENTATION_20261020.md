# ORCA no SENTRA — implementação experimental

Atualização de 21/10 após o pull: [estado consolidado, login/LAN e pendências](ORCA_SENTRA_STATUS_2026-10-21.md).

Estado: **integração experimental em desenvolvimento, não homologada para substituir a instalação atual**.
Base SENTRA: `07df23c`. ORCA fixado em `70b2197c97b164b16c618736a107967295e5af92`.
Atualização: 21 de outubro de 2026. Identificador e hashes: `vendor/orca/validation-build.json`.

## Abrir a prévia

A prévia isolada usa o componente real do workspace com um adaptador de dados de demonstração. Não acessa contas, serviços, cookies ou máquinas do SENTRA instalado.

```powershell
cd C:\Users\vitor\Desktop\SENTRA\sentra_canvas\desktop_ui
npm run preview:orca
```

Abra `http://127.0.0.1:5200/desktop-assets/qa/orca-workspace.html`.

Experimente os controles de divisão no cabeçalho de cada painel, arraste abas, maximize/restaure, abra Arquivos e alterne o tema pelo cabeçalho da prévia. O layout persiste apenas na chave desta demonstração. Ferramentas sem serviço retornam indisponibilidade explícita.

O código integrado fica atrás da preferência `sentra-orca-workspace-enabled`. Na versão compilada com este código, o Canvas anterior oferece “Experimentar abas e painéis”; “Canvas anterior” reverte a apresentação. A instalação em execução e seus bundles não foram substituídos. A navegação principal e o gateway de conversas Web permanecem os existentes.

Build de avaliação sem modificar os arquivos estáticos de produção:

```powershell
npm run build:orca-validation
```

Saída: `sentra_canvas/desktop_ui/.tmp/orca-workspace-build/`.

## Componentes entregues nesta etapa

| Frente | Implementação e evidência | Limite atual |
|---|---|---|
| Origem e licença | Oito módulos ORCA de E2EE copiados integralmente; onze origens de adaptação identificadas; MIT preservada | Inventário de dependências não equivale a aprovação jurídica de distribuição |
| Workspace | Árvore de divisões e gesto de redimensionamento adaptados do ORCA; abas, foco, teclado, arraste, maximização e preferência experimental | Avaliação visual e operacional com os dados do usuário ainda pendente |
| Serviços | Arquivos e revisão existentes, mapa em aba, terminais, navegador Playwright, computador e atividade. Transporte CDP adaptado e validado com Chromium 151 | A interface de navegador apresenta observação semântica, sem espelhar a página inteira. Avaliação visual com serviços do usuário ainda pendente |
| Identidade | Inventário com Dot e host, terminais de agentes e ferramentas; abas de computador vinculadas ao Dot escolhido | O inventário ainda usa consultas periódicas; assinatura unificada de eventos retomável não foi entregue |
| Recibos | Projeção que separa aceitação, entrega, observação, conclusão e incerteza; consultas de envio existentes | Não substitui os recibos centrais nem homologa todos os provedores |
| PTY separado | Daemon loopback, token DPAPI, identidade de runtime, ledger idempotente e cache agregado de 16 MiB | Opt-in; histórico do daemon é volátil e não sobrevive à morte do daemon/Windows |
| PTY funcional | Testes reais ConPTY, deduplicação, reconexão e reinício do Canvas mantendo o mesmo processo | O teste de reinício usa shell `cmd.exe`; revalidação da conexão de agentes CLI com o broker reiniciado ainda pendente |
| Atualização do daemon | Drenagem explícita, recusa de novas sessões e parada apenas com zero processos vivos | Substituição de executável e assinatura do instalador ainda não homologadas |
| Git | `git-worktrees` no MachineHost, Grants/WorkItems existentes, lock por repositório, base exata e manifests persistentes | Sem commit/merge/push; recuperação manual em caso de drift; editor/agent working directory ainda não passa automaticamente a usar a worktree |
| ACP | OpenCode `1.19.3` fixado, processo real, criação, estado e load após reabrir transporte pelo controle central | Geração com modelo, pedido de permissão, interrupção e queda durante geração ainda não homologados |
| Mobile | Aplicativo React Native/Expo Android/iOS, chave no SecureStore, conexão E2EE LAN e aprovações escopadas | Bundles JS/Hermes; não são APK/IPA assinados |
| Mobile funcional | Conversas existentes, arquivos, atividade, decisões do coordenador, comandos de terminal, navegador e tela da VM | Terminal com saída textual e comando explícito; sem emulador completo, streaming contínuo ou teclado remoto completo |
| Entrada remota | Identidade do dispositivo na posse central e epoch; ponteiro mobile usa tap atômico no host com liberação em `finally`, inclusive após falha de confirmação | Teclado remoto e arraste não são expostos pelo mobile. Tap e reconexão ainda exigem validação em VM e aparelho físicos |
| P2 | Nenhuma infraestrutura nova ativada | Relay, notificações push remotas, SSH e adaptações GitHub/Linear continuam pendentes |

## Execução durável

`SENTRA_PTY_DAEMON=1` habilita a composição experimental para uma **nova** instância do Canvas. Não altera processos já abertos. Sem a variável, o caminho anterior permanece ativo.

O daemon usa o ConPTY existente e só escuta em loopback. O descritor fica no estado do Canvas, em `pty-host/pty-endpoint.json`, com segredo protegido por DPAPI. Não entregue esse descritor à interface, a agentes ou ao mobile.

Métodos administrativos do cliente Python `PtyDaemonClient`:

- `health`: comprova conexão e versão; `coverage=handshake` não comprova PTY funcional.
- `self_test`: executa um comando fixo em ConPTY; relata `process_execution` e declara que entrada não foi testada por esse diagnóstico.
- `inventory`: enumera processos com identidade do runtime.
- `drain`: impede novas sessões, preservando as existentes e suas escritas.
- `stop_when_idle`: exige drenagem e nenhum processo vivo; não mata terminais para atualizar.
- `cancel_drain`: volta a aceitar novas sessões.

Um pedido físico é registrado antes do efeito. Repetição com a mesma chave e conteúdo recupera o resultado; conteúdo diferente é recusado. Interrupção sem confirmação vira incerta. Reiniciar o daemon não recria sessões históricas. O cache informa cursor, limite e lacunas; não é um registro persistente de todo o terminal.

## Mobile LAN

O gateway é um sidecar explícito. Abrir o workspace não inicia um listener de rede. Ele deve apontar para uma instância experimental do Canvas que contenha `/api/mobile/rpc`, não para um broker antigo instalado.

```powershell
python -m sentra_canvas.mobile_host --state <estado-do-Canvas-experimental> --bind <IPv4-LAN-deste-PC> --node <caminho-absoluto-node.exe>
```

Dependências: `integrations/orca-mobile/transport` e `integrations/orca-mobile/app`, cada uma com `package-lock.json` próprio. Com as dependências instaladas:

```powershell
cd integrations/orca-mobile/app
npm run start
```

Fluxo:

1. No workspace experimental, abra **Mobile** e gere o convite temporário.
2. No aplicativo, escaneie o QR ou cole o convite.
3. No desktop, confira a identidade e aprove o dispositivo para o Dot/Space corrente.
4. Operação remota e decisões de aprovação são opções separadas no pareamento; Grants e posse continuam obrigatórios.
5. No aplicativo, consulte a aprovação e selecione uma conversa existente. Reconexão é explícita.
6. Revogue no desktop para impedir novos pedidos imediatamente.

O convite expira em dois minutos e só é consumido uma vez. A credencial de dispositivo tem identidade própria, escopo exato e validade de 30 dias. Chaves e credenciais ficam no armazenamento seguro do telefone; cookies e segredos dos modelos não saem do host. O gateway substitui a identidade declarada pelo cliente pela chave comprovada na sessão criptográfica.

E2EE usa os módulos ORCA v2 fixados, com contadores e rejeição de replay. Não habilita relay. Pedidos na fila de uma conexão encerrada são descartados; efeitos já despachados permanecem sujeitos a recibo/reconciliação. O app grava a identidade de envios antes de transmitir e bloqueia nova tentativa enquanto houver resultado incerto no recurso. Consultar um recibo não reenvia mensagens.

## OpenCode fixado

`integrations/opencode/package-lock.json` fixa `opencode-ai@1.19.3`. O wrapper de validação usa diretórios próprios, sem herdar credenciais nem configurações do usuário, e o host fixa hashes do executável e arquivos de argumentos.

Teste opt-in, com o pacote oficial instalado em `integrations/opencode`:

```powershell
$env:SENTRA_TEST_OPENCODE='1'
python -m pytest tests/unit/test_opencode_pinned_real.py -q
```

Esse teste usa Grants reais no estado descartável, não inicia geração nem afirma homologação completa de ferramentas. A normalização de metadados OpenCode é uma adaptação do dialeto ORCA e não transforma exit code em conclusão de tarefa.

Referência de protocolo: [documentação oficial ACP do OpenCode](https://opencode.ai/docs/acp/).

## Proveniência reproduzível

```powershell
python scripts/commander/orca_inventory.py --source C:/Users/vitor/Desktop/orca-sentra-audit
```

O script exige o commit aprovado, verifica igualdade dos módulos copiados e produz `vendor/orca/provenance.json` e `vendor/orca/dependencies.json`. Inclui desenvolvimento e plataformas opcionais; pacotes sem licença declarada permanecem marcados como `UNDECLARED`. Os binários opcionais OpenCode exigem revisão de distribuição antes de entrar no instalador. Nenhum asset visual ou branding ORCA foi importado.

## Recuperação e critérios para ativar

- Voltar ao Canvas anterior só troca a apresentação. Fechar uma aba não encerra a sessão; encerramento físico exige ação própria.
- A migração de posse de entrada é aditiva, transacional e registra esquema 2. Reverter a preferência visual usa o mesmo host atualizado; não equivale a reverter o banco para um executável antigo.
- Layout restaurado referencia IDs existentes; recurso ausente é exibido como indisponível, sem recriação automática.
- Resultado incerto exige observação. Não limpar recibos/manifests para tentar executar novamente.
- O Chromium Playwright `151.0.7922.34` foi instalado para a validação. A incompatibilidade inicial de `Target.setAutoAttach` foi corrigida: auto-attach do browser usa `flatten`, o alvo permanece pausado durante a instalação de Fetch e um canal de página libera Runtime após comprovar o filtro. A suíte real passou em 16 testes e 4 subtestes; um caso de ausência de Playwright é corretamente ignorado porque a dependência está instalada. Outro teste real passou pelo bridge do workspace, comprovando observação, recibo central e bloqueio após revogação do Grant.
- Falha de pareamento ou perda da credencial: revogar no desktop e emitir novo convite. Não copiar cookies ou bearer do desktop para o celular.
- Nenhuma migração deve ser considerada concluída enquanto não houver validação Windows com dados reais, Android e iPhone físicos, limpeza de entrada após desconexão, fluxos ACP completos e builds nativos próprios. No mobile atual, botão pressionado e liberação pertencem ao mesmo efeito no host; quadros brutos de teclado e de botão mantido pressionado são recusados. Dois ensaios isolam sucesso e perda de confirmação após pressionar; ambos comprovam a tentativa de liberação, sem homologar a VM física.
- Assinatura Windows, ambiente Android/JDK/SDK, Mac/Xcode e credenciais Apple/Expo não foram configurados nesta etapa. Publicação em lojas e hospedagem do relay ficam para as etapas correspondentes.

As alterações foram mantidas no código e em saídas de avaliação separadas. Sessões, configurações e bundles da instalação em execução foram preservados.

## Validação registrada

- Lote do núcleo e regressões selecionadas: 44 testes Python passaram. Lote VM/mobile: 47 passaram, com sobreposição ao primeiro lote.
- OpenCode real, versão fixada: abertura, criação, consulta e retomada de sessão passaram pelo controle central.
- Chromium real: 16 testes, 4 subtestes e um teste adicional do bridge passaram; um teste de dependência ausente foi ignorado por não se aplicar.
- Transporte mobile: cinco testes passaram, incluindo WebSocket real local, chave do peer derivada da criptografia, replay e registro persistente contra repetição.
- Um teste adicional percorreu cliente criptografado, gateway Node e Canvas HTTP reais em loopback: convite, aprovação do dono, consulta limitada ao Dot e recusa após revogação passaram.
- Layout JavaScript: dois testes passaram; tipos mobile/transport e builds desktop/Android/iOS passaram.
- Inspeção visual da prévia: temas claro/escuro, abertura de documento, divisões, retenção ao maximizar e redimensionamento por teclado. Não equivale a auditoria completa de acessibilidade.
- Vite ainda avisa sobre scripts estáticos legados e tamanho do bundle; Metro usa resolução de compatibilidade para `@noble/hashes/crypto.js`. Os builds concluíram, mas otimização e revisão de empacotamento continuam pendentes.


## Correção de escopo visual — 21/10/2026

A Home, a barra lateral global, as páginas de projetos/Spaces/Dots e a conversa
mantêm o visual existente. A adaptação visual ORCA ocupa exclusivamente o
`CanvasWorkspace` montado no antigo ponto de `ShellDotCanvas`.

- A prévia agora renderiza o próprio `OpenDotsShell`, sem uma segunda Home.
- Dentro do Canvas: lista de subagentes/sessões, abas compactas, splits,
  maximização/restauração, explorador redimensionável, arquivos em abas e
  identidade do Dot/máquina por sessão.
- Abas e cores foram adaptadas de `SortableTab.tsx`, `tab-bar-surface.tsx`,
  `tab-width-rules.ts`, `FileExplorerRow.tsx` e `assets/main.css` do pin aprovado.
  Origem e hashes constam no inventário; o store global ORCA não foi importado.
- A leitura `workspace_inventory` foi acrescentada à allowlist de leituras do
  frontend; não gera uma intenção de mutação ou um reenvio.
- A prévia usa xterm real com transcrições fictícias identificadas. Não inicia
  terminais, agentes, autenticação nem serviços do aplicativo instalado.
- Configuração QA exclusiva: `npm run preview:orca`. O adaptador de fixtures é
  resolvido somente por `vite.orca-preview.config.js`; o build normal mantém
  o cliente API autenticado. `npm run build:orca-preview` gera saída em `.tmp`.
- Conferidos: Home/Canvas, leitura de README no explorador, maximizar/restaurar,
  proporções por teclado e manutenção dos terminais simulados. Cinco testes
  Node passaram, incluindo a classificação do inventário como leitura.

Esta é uma adaptação experimental do workspace, não uma homologação de todas
as telas/ações do ORCA nem dos aplicativos móveis. A instalação oficial e as
sessões existentes não foram substituídas.


## Execução do objetivo integral — recibos e recuperação, 21/10/2026

O objetivo integral e todos os aceites continuam registrados em
`docs/ORCA_IMPLEMENTATION_TRACKER.md`. Esta etapa acrescenta:

- `/api/shell/bridge` com a leitura `workspace_request_status`, que valida o Dot,
  Space e a impressão digital do pedido original e observa operações existentes.
- Migração aditiva/transacional para esquema 2 de `canvas_shell_host_requests`.
  A intenção original fica protegida pelo armazenamento do sistema; o renderer
  persiste apenas seletores, escopo e hash. Registros antigos seguem legíveis
  pelo caminho que fornece os campos originais; versões futuras são recusadas.
- Diário do workspace com persistência antes do envio, limites e exclusão mútua
  entre janelas. Reabertura e perda de transporte não viram um novo envio.
- Ações do Canvas e navegador ligadas ao diário e à consulta sem reenvio.
- Fingerprint canônico compartilhado entre desktop/mobile. O app mobile consulta
  operações incertas de máquina usando o mesmo endpoint e mantém seu escopo.
  Dispositivos antigos não recebem capacidades novas automaticamente: a consulta
  exige que ela esteja no pareamento aprovado.
- Inventário e consulta usam `delivery_projection`; `completion_scope=operation`
  deixa explícito que completar a operação não completa a tarefa do agente.
- Resposta persistida não encerra uma operação física RUNNING/UNCERTAIN ou em
  estado desconhecido. Só a observação conclusiva libera aquele pedido.

Os builds continuam em diretórios de avaliação; a instalação ativa e a Home
não foram substituídas. Histórico PTY, demais provedores/ações, ACP/Git completos,
mobile físico, remoto e distribuição assinada continuam abertos no tracker.
