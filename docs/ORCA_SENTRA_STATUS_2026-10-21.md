# ORCA → SENTRA: estado após a nova checagem e o pull

Data: 21/10/2026. Implementação experimental, com a migração integral ainda aberta.

**Checkpoint de código em 22/10:** vínculo de worktrees ao agente, arquivos,
comandos e novos terminais; revisão de conflitos em pasta descartável; 97 testes
Python únicos, 152 Node e um renderer aprovados. O ensaio com três modelos continua
pendente: a última execução terminou com categoria `quota` do provedor. Não houve
reenvio incerto. [Detalhes](ORCA_WORKTREE_EXECUTION_2026-10-21.md).
A janela citada abaixo conserva seu build anterior; este checkpoint não substituiu
a instalação nem publicou um setup novo.

Avaliação atual: janela **SENTRA · Orquestração**, com estado próprio e build
`sentra-orca-experimental-cffb8f3284b3`. [Entrega mais recente: estados formais, Acesso completo e
recuperação de tarefa com dois Dots](SENTRA_FULL_ACCESS_ORCHESTRATION_2026-10-21.md).

Acesso completo prepara os acessos derivados no host. Passaram 79 regressões
Python, 151 Node e dois renderers. O roteiro com modelo real usou uma seleção
full, zero Grants manuais, dois Dots criados pelo coordenador, arquivos reais,
pausa no checkpoint, reabertura do broker e consolidação verificada na conversa.
O plano integral e a homologação física dos celulares permanecem abertos.

As rodadas anteriores estão documentadas em [Modo Simples](ORCA_SIMPLE_MODE_2026-10-21.md),
[terminal móvel/LAN](ORCA_MOBILE_TERMINAL_2026-10-21.md),
[PTY/CLI](ORCA_PTY_CLI_RECOVERY_2026-10-21.md) e
[checkpoints](ORCA_TERMINAL_CHECKPOINTS_2026-10-21.md). As matrizes abaixo foram
atualizadas para refletir a entrega mais recente.

## 1. Revisões e escopo

- SENTRA: `07df23c45f605a056ece92d51f6e34e133e28012` mais alterações locais.
- ORCA originalmente incorporado: `70b2197c97b164b16c618736a107967295e5af92`.
- Checkout de análise atualizado por `git pull --ff-only origin main` na branch
  `codex/sentra-upstream-review` para `fd8b2dc3a7c557be940e635327f461229cef1644`.
- A comparação local contém 100 commits e 1.322 arquivos modificados desde o pin.
  Foram lidos os assuntos dos commits e módulos/patches selecionados. Isso não
  constitui revisão integral de todas as linhas desses 1.322 arquivos.
- O código de transporte já incorporado continua fixado no pin original. As
  adaptações posteriores têm registro próprio em `vendor/orca/upstream-review.json`.
- A Home e a navegação SENTRA permanecem. O workspace ORCA ocupa somente o
  Canvas interno do Dot e continua experimental.

Fontes: [ORCA consultado](https://github.com/stablyai/orca/tree/fd8b2dc3a7c557be940e635327f461229cef1644),
[comparação das revisões](https://github.com/stablyai/orca/compare/70b2197c97b164b16c618736a107967295e5af92...fd8b2dc3a7c557be940e635327f461229cef1644).

## 2. O que aproveitamos, com os limites atuais

“Implementado” abaixo descreve código existente. A homologação Windows instalado,
Android/iPhone físicos e distribuição assinada é uma etapa própria.

| Frente | Aproveitamento existente | O que falta |
|---|---|---|
| Origem e licença | Oito módulos E2EE e 28 arquivos de terminal copiados; onze origens de adaptação em nove destinos; MIT e inventário preservados | Revisar licenças não declaradas e a composição final dos pacotes |
| Abas e splits | Abas compactas, divisões horizontais/verticais, resize por ponteiro/teclado, mover abas, maximizar/restaurar, foco e explorador | Paridade completa de menus/atalhos, arraste para dividir nas bordas, busca rápida e avaliação visual com dados reais |
| Identidade visual | Moldura `OpenDotsShell` existente; identidade SENTRA e CSS do workspace delimitado; redução uniforme de opacidade do split sem foco | Nova avaliação visual da rodada; fidelidade completa aos exemplos ORCA ainda não homologada |
| Mapa | Canvas anterior acessível numa aba e pela opção de voltar à apresentação anterior | Avaliação de fluxos mistos mapa/workspace |
| Layout | Árvore validada, escopo por usuário/projeto/Space/Dot, persistência protegida no host com revisão, layouts por modo, raízes estáveis e IDs de recursos existentes | Sincronização entre dispositivos, recuperação de órfãos e orçamento de montagem |
| Subagentes e sessões | Inventário real, nomes de tarefa, estado principal, painel contextual e colaboração coordenador/filho com modelo real e cinco recibos | Homologação completa de vários colaboradores e dispositivos; UX de criação/encerramento e sessões órfãs |
| Contrato | Tipos compartilhados de escopo, inventário, recursos, recibos, capacidades e cursores | Assinatura sequenciada/retomável; negociação produtiva de todas as capacidades. O workspace ainda faz polling |
| Recibos | Diário protegido SENTRA; `delivery_projection` agora chamada pelo inventário e pela consulta; consulta por intenção original | Estender às famílias restantes de efeitos/provedores; decisões de acesso e coordenação já têm recuperação por consulta |
| Reconciliação desktop/mobile | Persistência antes do envio; seletor/hash compartilhado; consulta sem reenvio; estados RUNNING/UNCERTAIN permanecem pendentes; exclusão entre janelas | Completar demais operações e ensaios de concorrência/queda do conjunto |
| Daemon PTY | ConPTY separado, loopback autenticado, ledger, cache limitado, histórico e drenagem; cliente CanvasBridge reconecta com a mesma sessão/PID | Empacotamento/atualização segura no instalado e homologação prolongada; turno real de modelo no CLI passou nesta rodada |
| Histórico PTY | SQLite protegido, fila limitada, lacunas e checkpoints do emulador com buffers/cursor/modos/geometria; morte/reinício real do daemon e histórico somente leitura | Conferência visual/carga prolongada de TUIs, paginação, backpressure por consumidor e distribuição do runtime |
| ACP/OpenCode | Dialeto adaptado; OpenCode 1.19.3 fixado; criar/consultar/carregar sessão por processo real e controle central | Geração real, aprovação, cancelamento, desconexão durante turno e demais dialetos |
| Worktrees | Git real por Dot/WorkItem, registro central por conversa/Run, arquivos e comandos vinculados, novo ConPTY na pasta correta, previews escopados e ensaio de conflitos sem publicação | Editor, aceite completo de três modelos, revisão de arquivos novos/binários, mapeamento guest, limpeza e publicação estruturada |
| Coordenação | Observação de convergência distingue tarefas encerradas de tarefas bem-sucedidas; checkpoints SENTRA preservados | Ampliar transições/gates/checkpoints transacionais e concorrência. O ensaio de dois Dots cobre retomada no checkpoint, sem provar recuperação de qualquer efeito em andamento |
| Arquivos/revisão | Explorador, arquivos em abas de leitura e acesso aos serviços de revisão/diff existentes | Editor completo, conflito de edição, save condicionado à versão, revisão por linhas, previews e watchers agrupados |
| Navegador | Serviços Playwright existentes, observação semântica, sessões autorizadas, recibos e correção CDP | Página gráfica compartilhada, Design Mode, persistência/migração de perfis do browser de trabalho e homologação visual |
| Computador | Serviços VM existentes, posse central com identidade/epoch e tap atômico com release no host | Teclado/arraste completos e ensaios em VM/aparelhos físicos |
| Mobile | App Expo/RN próprio Android/iOS; E2EE ORCA; SecureStore; pareamento aprovado; conversas, arquivos, atividade, decisões, VM e xterm offline com checkpoints, leitura incremental e entrada central sem replay | Homologação nativa, assinatura de eventos, navegação hierárquica completa, rascunhos persistentes e controles remotos completos |
| LAN e autenticação móvel | Identidade estável, endereço conferido, seleção IPv4, recuperação do broker e atualização de endereço sem novo pareamento; detalhes na seção 3 | Descoberta LAN/mDNS, DHCP automático, redes reais Android/iPhone, VPN/IPv6 e testes de suspensão no sistema operacional |
| Remoto | Bases de federação SENTRA preservadas | Adaptações SSH, relay E2EE opcional, push e conectores GitHub/Linear |
| Distribuição | Builds desktop isolados e exportações JS/Hermes Android/iOS | Instalador/daemon e APK/IPA assinados; recuperação, migrações, distribuição e ativação gradual homologadas |

Oito cópias integrais: `e2ee-crypto`, `mobile-e2ee-v2-contract`,
`mobile-e2ee-v2-framing`, `mobile-e2ee-v2-node-key-schedule`,
`paired-e2ee-node-primitives`, `paired-e2ee-primitives`,
`paired-e2ee-v2-client-session` e `paired-e2ee-v2-key-schedule`.

As onze origens e seus destinos estão individualizadas no
[relatório anterior](ORCA_SENTRA_REAUDIT_2026-10-21.md#9-inventário-integral-da-origem-reaproveitada).
Onze origens não significam onze componentes oficiais transplantados integralmente.

## 3. Melhorias implementadas depois do pull: login e LAN

### Identidade e continuidade de autenticação

Aplicado o princípio da
[identidade de autenticação estável do ORCA](https://github.com/stablyai/orca/commit/60b8eb4a6f87ffde45f2bbf623aac8cb77ecfd72):

1. A chave do host é protegida pelo sistema e independe de runtime, IP e convite.
   O formato antigo de `mobile-key.protected` é adotado em lugar; chave danificada
   causa erro explícito, sem criar silenciosamente outra identidade.
2. No celular, a identidade do pareamento usa chave do host e projeto/Space/Dot.
   Dois computadores no mesmo IP em momentos diferentes não se tornam a mesma conta.
3. “Atualizar endereço mantendo pareamento” conserva credencial, chave do celular
   e escopo. O novo endereço só é salvo após handshake com a chave original e
   consulta autenticada ao inventário.
4. O gateway recebe a nova porta/credencial do broker por pipe privado, após o
   supervisor conferir seu descritor e saúde. A sessão E2EE e o pareamento ficam
   preservados; pedidos incertos não são repetidos.
5. Uma confirmação de claim perdida pode ser consultada por até 120 segundos,
   apenas pelo mesmo dispositivo criptográfico. Revogação remove esse recibo;
   expiração do recibo não expira a credencial já aprovada.
6. Callbacks e timeout de uma conexão aposentada não alteram a conexão nova.
   O retorno ao primeiro plano retoma autenticação/leitura, sem executar comandos
   pendentes. A posse de entrada continua sujeita à liberação e expiração centrais.

Essas mudanças tratam autenticação/continuidade do mobile. O login dos modelos
Web continua sob o gateway/launcher SENTRA existente; cookies e credenciais de
modelos não são entregues ao celular. A migração gráfica de perfis do browser de
trabalho, equivalente ao recurso ORCA, ainda não está concluída.

### Endereço LAN e pareamento

Adaptado o critério de
[endereços realmente atendidos pelo listener](https://github.com/stablyai/orca/commit/c7f722bbdf6bf45217fc3b7264590fd293a73236):

- `--bind auto` escolhe IPv4 privada, priorizando nomes de interfaces sem indícios
  de virtualização. Adaptadores virtuais reconhecidos pelo nome exigem escolha
  explícita; ausência de interface apropriada retorna erro. Isso não é uma
  certificação do hardware da placa.
- O gateway fica associado ao IP escolhido, sem abrir implicitamente em todas
  as interfaces. Não anuncia IPv6 quando só atende IPv4.
- Metadados e chave nova usam gravação atômica.
- Antes de emitir convite, o host confere a identidade e o endpoint do listener
  por uma leitura de saúde sem enviar credenciais.
- O modal mostra conexão/endereço e diferencia broker reiniciando, gateway
  indisponível e loopback. Loopback não é oferecido pela UI como QR para celular.
- Um gateway supervisionado encerra seu listener se perder o pipe do supervisor.
- IPv6, VPN/overlay e descoberta automática de mudança de IP não foram habilitados.

O ensaio local comprova o protocolo e o reinício; não comprova acesso pelo Wi-Fi,
firewall e políticas de segundo plano dos dois aparelhos.

## 4. O que mais podemos aproveitar e aprender

Além das oportunidades já catalogadas na segunda checagem:

| Aprendizado | Aplicação proposta no SENTRA | Estado/prioridade |
|---|---|---|
| Login independe de runtime/IP/pareamento | Manter a identidade durável e adotar o armazenamento antigo após atualização, com isolamento por dono | Aplicado ao pareamento; browser gráfico pendente · P0/P1 |
| Autosave precisa coordenar todas as abas do mesmo arquivo físico | Identidade por host+caminho; pausar saves durante descarte Git; salvar só contra versão de disco conhecida | Novo detalhe de aceite do editor · P1 |
| Conclusão pertence a um turno identificado | Hooks/eventos atrasados, repetidos ou de subagente não podem emitir nova conclusão do Dot principal | Coordenação e futuros avisos · P0/P1 |
| Retomada usa a conversa comprovada no registro durável | Conservar a conversa permanente do Dot; não selecionar thread só pelo nome ou pedido do cliente | Web já tem vínculos; ampliar ACP/CLI · P1 |
| Hierarquia precisa ser validada na autoridade com cache frio | Impedir ciclos em relações entre Dots/worktrees mesmo quando a UI não carregou todos os ancestrais | Revisar gates atuais · P1 |
| Listas precisam ter custo limitado sem esconder resultados da busca | Paginação/janela de hosts, sessões e histórico; busca continua alcançando itens fora da janela | Remoto e grandes projetos · P1/P2 |
| Acesso headless deve oferecer os mesmos recursos autorizados | Arquivos/documentos/mobile não podem depender de uma janela desktop montada | Contratos e gateway · P1 |
| Descoberta de executável deve usar o mesmo ambiente da execução | Atualizar diagnóstico de PATH e versão sem iniciar uma segunda execução nem mudar diretório/conta silenciosamente | ACP, CLI e instalador · P1 |
| Foco precisa ser uniforme em camadas retidas | Terminal, editor e chat recebem a mesma indicação de split ativo | Opacidade adaptada; avaliação visual pendente · P1 |
| Re-pareamento não deve criar outra página no browser | Desktop/mobile anexam ao mesmo recurso autorizado, mantendo cookies no host | Browser gráfico pendente · P1 |

Fontes examinadas para os novos detalhes:
[autosave e descarte](https://github.com/stablyai/orca/commit/546304fa118ee106436cde2d12dd57ea823ae185),
[conclusão por turno](https://github.com/stablyai/orca/commit/fc8439e05f1eceb33e7178214725de408c5d73ca),
[retomada de conversa](https://github.com/stablyai/orca/commit/7dfcfbf7356b0a34f12d4c3d2b48d4a2a7dcfdd5),
[ciclos com cache frio](https://github.com/stablyai/orca/commit/505d6719c075eb0344dac86867a4e4030e970a1d),
[lista limitada de hosts](https://github.com/stablyai/orca/blob/fd8b2dc3a7c557be940e635327f461229cef1644/src/renderer/src/components/host-picker/bounded-host-list.ts),
[descoberta de executável](https://github.com/stablyai/orca/blob/fd8b2dc3a7c557be940e635327f461229cef1644/src/main/codex/codex-structured-launch-resolution.ts),
[foco dos splits](https://github.com/stablyai/orca/commit/fd8b2dc3a7c557be940e635327f461229cef1644).

Continuam recomendados os 16 aproveitamentos anteriores: snapshots ANSI/TUI,
backpressure por consumidor, recursos órfãos, página compartilhada, orçamento de
montagem, capacidades reais, rascunhos por sessão, gestos/callbacks obsoletos,
watchers agrupados, revisão por linhas, abertura rápida, Design Mode, escrita
atômica/esquemas, comprovante do prompt inicial, caminhos remotos indisponíveis
e compatibilidade de build. Seus critérios estão na
[segunda checagem](ORCA_SENTRA_REAUDIT_2026-10-21.md#4-novos-aproveitamentos-recomendados).

Design Mode foi confirmado na documentação oficial. Sua extração técnica não
foi homologada nesta rodada; não é anunciado como código já integrado.

## 5. Correções ao relatório anterior e confiança na entrega

- `delivery_projection` deixou de ser apenas helper: há chamadas produtivas
  no inventário e na reconciliação. O diário agora protege a intenção original.
- Na checagem inicial, o histórico PTY era código sem validação. A rodada
  posterior PTY/CLI ensaiou persistência e recuperação real; checkpoints completos
  de TUI continuam pendentes.
- Na abertura desta checagem, o manifesto anterior identificava 68 fontes e sete
  outputs. Os sete outputs conferiam, mas três fontes estavam adiante do build
  (`pty_client.py`, `pty_daemon.py`, `service.py`) e `pty_history.py` não constava.
  Isso foi registrado como código em desenvolvimento, sem atribuir homologação.
- Uma divergência de hash no CSS de origem era exclusivamente LF/CRLF. O
  inventário agora calcula hashes dos blobs Git do pin, independentemente do
  checkout e de `core.autocrlf`. As oito cópias mantêm igualdade byte a byte.
- Os 917 registros de dependências incluem desenvolvimento/plataformas opcionais;
  não representam 917 bibliotecas efetivamente distribuídas.
- Não há percentual único justificável para a migração. UI experimental,
  backend ensaiado e aplicativos físicos são níveis de evidência diferentes.

## 6. Avaliação local e pendências de aceite

Validação desta rodada:

- **13 testes Python passaram**, incluindo DPAPI real no Windows, identidade do
  listener, claim/escopo/revogação, posse de entrada e dois percursos cifrados
  com Canvas HTTP real. Um deles reinicia o broker com o supervisor real e
  conserva a mesma conversa e o mesmo pareamento.
- **8 testes Node do transporte passaram**, incluindo troca de broker/endereço,
  callbacks aposentados, host impostor recusado e uma única transmissão do
  efeito cuja confirmação foi perdida.
- **10 testes Node do desktop passaram** para layout, bridge e diário.
- Tipos de app/transporte, dois builds desktop isolados e exportações Hermes
  Android/iOS concluíram. Permanecem avisos de bundle grande/scripts legados
  no Vite e resolução de compatibilidade de `@noble/hashes/crypto.js` no Metro.
- Build identificado: `sentra-orca-experimental-ed3a36245581`. O manifesto inclui
  as novas fontes e registra sete outputs; a inclusão de `pty_history.py` dá
  rastreabilidade, sem lhe atribuir os testes de LAN desta rodada.
- A conferência visual nova continua pendente: a tentativa anterior de acessar
  a aba foi recusada pela política do navegador e não foi contornada.
- Os testes usaram estado temporário, sem trocar bundles estáticos de produção
  ou reiniciar sessões instaladas. Não ficaram gateways de teste em execução.

Prévia visual separada:

```powershell
cd C:\Users\vitor\Desktop\SENTRA\sentra_canvas\desktop_ui
npm run preview:orca
```

Abrir `http://127.0.0.1:5200/desktop-assets/qa/orca-workspace.html`.
A prévia usa dados simulados, sem contas ou processos reais.

Gateway para uma instância experimental real, iniciado explicitamente:

```powershell
python -m sentra_canvas.mobile_host --state <estado-do-Canvas-experimental> --bind auto --node <node.exe-absoluto>
```

Se necessário, usar `--bind <IPv4-desta-máquina>`. O comando confirma a
disponibilidade do broker e mantém sua identidade já protegida. O processo
precisa permanecer em execução. A UI principal instalada não foi substituída.

Para desenvolvimento móvel na mesma rede, o app tem o comando `start:lan`.
O build de desenvolvimento/Expo apropriado e as permissões de rede/câmera
dos aparelhos continuam necessários; Hermes exportado não é APK/IPA.

Próxima ordem de trabalho: concluir PTY/CLI e eventos; completar Canvas real;
fechar ACP/worktrees; testar LAN nos dois aparelhos; empacotar e assinar;
ampliar SSH/relay/conectores. O acompanhamento integral continua em
[ORCA_IMPLEMENTATION_TRACKER.md](ORCA_IMPLEMENTATION_TRACKER.md).
