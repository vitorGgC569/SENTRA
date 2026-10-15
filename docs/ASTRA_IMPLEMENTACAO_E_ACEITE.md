# Plano ASTRA: implementação e evidências

Objetivo integral: Desktop e equipes, identidade Dots/Canvas, 10 fluxos por host e
20 usuários de equipe. As etapas abaixo não são encerradas pela existência de um
módulo ou por um teste simulado. A rota nativa recuperada do Codex deve continuar
direta; esta implementação não altera configuração, credenciais ou processos dela.

## Matriz de aceite

| ID | Entrega | Evidência exigida | Situação |
|---|---|---|---|
| P0.1 | Continuidade em espera, confirmação, desconexão e nova rodada | Casos de regressão + percurso visual | Correções existentes; validação integrada em andamento |
| P0.2 | Instalação reproduzível atual | Componentes/pins aprovados, assinatura, hashes, proveniência e instalação limpa | Três componentes compilados/materializados; binding instalado aprovado em EXE de QA; revisão legal RustDesk, Setup, assinatura e homologação pendentes |
| P1.1 | Feed contínuo autenticado, multiplexado e durável | HTTP real, cursor, isolamento, fragmentação, duplicação, compactação e retomada | Implementado e verificado em ambiente isolado; rollout instalado pendente |
| P1.2 | Geração independente da janela | Ingestão sem consumidor e retomada após restart do broker | Ingestão e replay implementados; homologação de restart completa pendente |
| P1.3 | Latência e recuperação | p95 adaptador → tela <=300ms, feedback <=100ms e reconexão <=15s após serviço pronto | Ensaio instrumentado 10/20 passou: 239,98–252,65 ms; após refs 243,61 ms. Host isolado, provedores e aplicativo instalado pendentes |
| P1.4 | Capacidade | 10 inferências reais e 20 usuários reais, com quotas/isolamento | 20 leitores de 10 fluxos HTTP locais testados; inferência/equipe reais pendentes |
| P1.5 | Percurso instalado completo | Instalar, autenticar, criar Dot, executar, verificar, reiniciar e retomar | Pendente |
| P2.1 | Federation com executor útil | Tarefa real entre instalações, artefato/revisão e recuperação | Executor tipado integrado a MachineHost/ControlPlane; dois processos reais com arquivo, revisão, restart e revogação; duas instalações Windows/Setup pendentes |
| P2.2 | Equipes e colaboração | Contas, escopos, revogação, conflitos e desconexão em dispositivos reais | Pendente |
| P2.3 | Visual e acessibilidade | Navegação, Home, chat, Markdown, computador redimensionável, Canvas, assets, teclado/zoom/leitor de tela | Home/Markdown/virtualização/redimensionamento e QA visual entregues; cache/tail integrados; leitor de tela e percurso instalado completos pendentes |
| P3.1 | Conectores úteis | GitHub e Drive com autenticação/expiração/revogação/erros reais | Pendente |
| P3.2 | SDK e modelos opcionais | Extensão útil e inferência com pesos reais | Pendente |
| P3.3 | Operação | Backup/restauração, migrações, update/rollback, suporte sanitizado | Homologação integrada pendente |

## Contrato do feed

- `GET /api/shell/stream?project_id=...`, bearer no cabeçalho; cursor em
  `Last-Event-ID`. Uma conexão por janela/projeto, até 32 leitores locais.
- `snapshot`: cursor e descritores limitados; o cliente relê o snapshot da
  conversa visível. Um cursor expirado ou inválido para o estado atual recebe reset.
- `shell`: sequência, conversa, operação, base da alteração, texto novo e fase.
  Um delta só é aplicado sobre a mesma operação e sequência-base. Lacunas exigem
  snapshot; não são compensadas reenviando uma mensagem.
- `GET /api/shell/stream/head` exige projeto, espaço e conversa exatos e retorna
  o snapshot protegido já persistido, junto da sequência.
- Os snapshots/eventos são projeções de apresentação no namespace `shell` do
  armazenamento existente. Não criam outra autoridade de Run/Operation/Grant.
- O snapshot e seu evento são gravados na mesma transação antes da publicação.
  A janela de eventos é compactada em 2.048 entradas por proprietário/projeto;
  o snapshot atual permanece. Eventos antigos não são uma API de arquivo completo.
- Encerrar um leitor não cancela o produtor. Confirmação chega apenas depois de
  registrar a mensagem pelo caminho verificado existente. A interface consulta
  o histórico canônico para substituir sua prévia.
- Heartbeat 10s, silêncio máximo 30s, reconexão de leitura com jitter e teto 15s.
  401/403 interrompem a reconexão; versões antigas usam os endpoints de prévia.
- Rollback de interface: preferência local `sentra_shell_stream=off` usa o
  percurso de consulta existente. Nenhuma ação mutante é repetida pelo feed.

## Medição e limites atuais

O evento local de interface `sentra:stream-metric` mede recebimento do fragmento
até um frame posterior ao render, sem conteúdo ou credenciais. Ele não mede o
tempo total desde o adaptador, nem prova p95 da rota remota. Ensaios de carga
locais não equivalem a inferência com o provedor ou colaboração em duas máquinas.

Markdown e virtualização foram ampliados e verificados posteriormente (ver a
atualização de 15/10 abaixo). Continuam pendentes persistência dos rascunhos do
compositor além da sessão da janela e a matriz completa de interrupções reais.

## Evidência desta implementação — 14/10/2026

- Regressão Python selecionada: **47 aprovados** em 73,50s. Escopo:
  `test_shell_stream_journal`, `test_sentra_shell_live_preview`,
  `test_shell_runtime_turn_memory`, `test_conversation_persistence`,
  `test_sentra_runtime_canvas_center_http`, `test_canvas_web_peer_transport`,
  `test_shell_delivery_diagnostics` e `test_sentra_cos_web_history_protected`.
- Interface: **96 testes JS aprovados**, incluindo parsing SSE fragmentado,
  Unicode, repetição, lacunas, reset durante leitura concorrente e renovação de
  autorização compartilhada. Os números são dos conjuntos selecionados, não da suíte inteira.
- `npm run build` concluiu e materializou o bundle. Permanecem avisos de tamanho
  do bundle e scripts estáticos existentes; otimização de carregamento segue aberta.
- QA Chromium com CanvasServer real, dados temporários e produtor sintético:
  SSE conectado; texto preservado na confirmação; snapshot recuperado ao reabrir
  a janela; zero consultas de prévia legada após conexão; sem overflow a 390px,
  sem erros JavaScript e fallback visível ao bloquear os assets dos mascotes.
- A publicação sintética até o DOM levou **125ms em uma amostra**. Isso não é
  p95, não inclui um modelo real e não fecha P1.3.
- O ensaio de capacidade usa **20 leitores HTTP e 10 conversas com Operations
  temporárias existentes**, sem chamar modelos. Não fecha P1.4.
- O ledger web agora mantém uma janela de 512 observações e continua recebendo
  revisões posteriores; o teste com **600 revisões** valida o conteúdo mais recente,
  compactação e recusa de conflitos/reordenação. Revisões compactadas não são
  substituídas silenciosamente pela versão mais recente.
- A publicação de previews do runtime consulta o binding de fila da conversa na
  mesma transação. Fragmentos de uma operação antiga não substituem o turno atual.
- Dois ajustes de regressão: o fixture de inspeção passou a registrar o agente
  no Run, como exige a política; o teste de peers espera a transação do histórico,
  pois o fragmento de terminal pode chegar antes do commit. A autorização de
  produção não foi afrouxada.

Artefatos locais: `.tmp/astra-stream-python.log`, `.tmp/astra-stream-node.log`,
`.tmp/astra-stream-ui-build.log` e `.tmp/astra-stream-qa/report.json`, com capturas
em 1440px e 390px. `tests/qa/astra_stream_browser.py` reproduz o ensaio sem conta/modelo.

O preflight inicial de distribuição está em `.tmp/astra-release-readiness.json`.
A seleção de pin e os candidatos posteriores estão descritos abaixo; o preflight
inicial não representa essas novas compilações. Não foi produzido um novo Setup
integral ou alterada a rota nativa recuperada do Codex. O objetivo permanece ativo.

## Marco posterior: fontes, binários e bibliotecas nativas

- `scripts/commander/source_snapshot.py` copia apenas entradas de produto para
  um diretório novo e verifica os hashes antes/depois da cópia. Não leva sessões,
  credenciais ou caches. Um selo é escrito apenas após verificar o conjunto e
  o conteúdo copiados; o build recusa alterações no candidato e vincula seu
  recibo ao hash do selo. Isso não substitui assinatura ou revisão das fontes.
- A impressão digital inclui agora Code Mode, fontes Rust, scripts `.mjs`,
  fontes tipográficas, mídia e licenças sem extensão efetivamente empacotadas.
- O build React registra suas entradas antes do Vite e confere novamente antes
  de materializar. O manifesto contém os hashes das fontes/lockfile/scripts/
  arquivos públicos e de todos os chunks/assets emitidos pelo Vite. O build
  Python recusa um bundle válido que pertença a fontes diferentes.
- O pin existente em `.tmp/host-runtime-pins-wasmtime.json` foi selecionado
  somente no processo de build. DLL e licença da instalação 49.0.0 conferiram
  com os hashes registrados. Não se inferiu aprovação de release dessa comparação.
- HCS: `scripts/commander/build_hcs.py` usa Go 1.26.8 e uma cópia arquivada da
  revisão aprovada `ab8249e8a1110ff5f052d3710fe57f29c45503d3` de hcsshim.
  O executável de 10.307.584 bytes foi compilado em diretórios distintos e
  apresentou o mesmo SHA-256 `1ccf302e5b03bf49dfb689fea4f3367262ff6bb352b0674b1119368f853cbf4e`.
  O manifesto tem 24 arquivos verificados, avisos de 16 módulos, licença Go e
  licença SENTRA. O teste de protocolo rejeitou JSON inválido sem acionar HCS.
  **Criação/execução/encerramento de containers reais continuam pendentes.**
- QuickJS: a compilação real identificou e corrigiu alvo WASI obsoleto, ausência
  de `dtoa.c`, include setjmp não utilizado, rotas residuais de libc para relógio/
  descritores, pilha linear insuficiente e perda da mensagem na classificação
  de exceções. As rotas residuais dão trap local; o ABI continua recusando
  qualquer import que não seja `env.sentra_host_call`.
- `scripts/commander/build_quickjs.py` constrói em cópia isolada e verifica as
  fontes usadas. O pacote inclui SBOM, licença QuickJS e avisos legais fixados
  para wasi-libc/compiler-rt do SDK 34. A materialização exige esses avisos e
  inspeciona o WASM real, em vez de confiar somente no texto do manifesto.
- Guest final: 1.192.692 bytes, SHA-256
  `5de70c4c7140aa43fbff39c8d53e261573e9df857a44cb5c3d0ff6412a57b9a6`.
  **11 ensaios passaram em Wasmtime real**: aritmética, Unicode/ausência de
  APIs do host, ferramenta recusada, loop infinito, limites de resultado e
  memória, aleatoriedade recusada, exceção JS, CPU do worker, watchdog de tempo
  e cancelamento com worker ativo. Os callbacks são probes locais; isso não
  comprova ferramentas reais pelo Control Plane ou o percurso instalado.
- RustDesk: o emissor de patch agora normaliza CRLF preservando o hash dos
  bytes originais. O patch foi aplicado numa cópia separada da revisão aprovada
  `1d4abd0258bb6678cdd5e2abe3a2af59fd3d7dbe`, com hbb_common em
  `229b904508364c8997aad0fb5af57effac859f60`. A compilação foi concluída em
  15/10; conexão real entre peers permanece pendente. Os checkouts originais
  de RustDesk/hcsshim permaneceram limpos.

## Evidência do executável Canvas

O candidato em `dist-sealed-ui/sentra-canvas.exe` foi executado como broker
real, com workspace/estado separados e sem janela ou inferência. O ensaio
`tests/qa/astra_frozen_canvas.py` comprovou:

- HTTP 401 sem autenticação;
- 126 assets servidos pelo executável com hashes conferidos;
- abertura SSE antes e depois de reiniciar o broker;
- workspace preservado no reinício e nova identidade de runtime;
- encerramento dos dois brokers de QA pelo endpoint autenticado.

Isso testa o componente compilado, **não uma instalação limpa, o Desktop
completo, a retomada de uma geração ativa ou o pacote integral de release**.
O início frio levou 6.953ms em uma amostra; não é um benchmark p95.

Regressão selecionada deste marco: **67 aprovados, 1 ignorado e 4 subtestes
aprovados** em 8,63s. O ignorado é a aceitação nativa de peer RustDesk, ainda
sem o cliente/servidor real. Logs e relatórios: `.tmp/astra-release-provenance-tests.log`,
`.tmp/astra-frozen-qa/report.json`, `.tmp/astra-quickjs-runtime.json` e
`.tmp/astra-sealed-ui-build.log`.

Os artefatos ficam fora do checkout, em
`%LOCALAPPDATA%/SENTRA/Build/astra-20261014-223255`; o local está registrado em
`.tmp/astra-build-candidate.json`. `dist-sealed-ui`, `hcs-final/artifact` e
`quickjs-current/artifact` são candidatos de componentes, sem promoção
para a instalação em uso. O Setup integral e o restante da matriz ficam abertos.

## Build nativo RustDesk e validação dos componentes

O build por fases em `scripts/commander/build_rustdesk.py` reconstrói o patch
esperado a partir da revisão aprovada, confere os submódulos e compara as fontes
antes/depois de cada fase. A bridge Flutter/Rust foi gerada de fato com Rust
1.75.0, Flutter 3.24.5 e flutter_rust_bridge_codegen 1.80.1. A localização do
Clang 15.0.6.1 agora é explícita para o ffigen. Plugins Flutter usam junções
verificadas dentro do cache selecionado, sem habilitar Developer Mode.

A compilação da biblioteca nativa e do bundle Flutter foi concluída. Isso não
comprova sessão remota ou release instalado. Os registros ficam no diretório
`rustdesk-build` do candidato externo ao checkout. Os arquivos originais de
`third_party/rustdesk` continuam preservados.

O empacotamento agora inspeciona cabeçalhos PE32+/AMD64 e exige na DLL RustDesk
o export local `sentra_desktop_control_abi_v1`, além dos pins do bundle. Recusa
um export encaminhado a outra biblioteca. Esses controles são inspeção de
estrutura, não prova de execução. **14 testes passaram** para essas validações,
incluindo fixtures sintéticas explicitamente identificadas. O executável HCS
real também passou na inspeção PE.

`tests/qa/astra_rustdesk_abi.py` prepara uma prova separada de carregamento da DLL
e chamada do símbolo num processo com timeout, conferindo fontes e hash do
build antes da chamada. O ensaio foi executado com sucesso na DLL real em 15/10:
ABI versão 1, 234 ms em uma amostra. Não substitui autenticação com um peer ou
controle de desktop real.

## Integração atual — 15/10/2026

- O bundle visual anterior foi validado e aberto como SENTRA Desktop pelo
  launcher oficial. O broker foi atualizado pelo fluxo guardado, após confirmar
  ausência de operações Canvas e de trabalho no relay. Serviços Codex, gateway
  e Web Models permaneceram ativos. Isso não atualizou o Setup instalado.
- A leitura canônica `conversation_get` resolve conversas fora da primeira
  página e preserva seleção após atualização. Consultas de envio usam
  `message_request_status`, nunca repetem `message_send` e não confundem ACK
  persistido com conclusão do modelo. A QA do chat passou em 12 cenários.
- Cache privado RAM de oito conversas/4 MiB de UTF-8/cinco minutos e tail de
  50 mensagens integrados; não guardam recibos, Grants ou pendências. A QA
  React/HTTP comprovou uma leitura inicial, paginação integral de 123 mensagens,
  adoção explícita de uma janela distante, prévia antes da leitura e limpeza
  após 403. Cache não confirmou nem reenviou um envio pendente de texto igual.
  São dados sintéticos; a última prévia levou 80,62 ms no harness, não p95 instalado.
- 132 testes JavaScript passaram após essa integração. O novo bundle passou
  na verificação de 128 assets e 138 entradas de fonte. Esse novo build não
  implica recarregamento automático da janela já aberta.
- Mais 21 testes backend de tail/consulta canônica/status HTTP/envio passaram.
  Navegação de leitura no broker real abriu a conversa com o bundle novo e
  zero erros JavaScript, sem criar conversa ou enviar prompt real.
- A QA MV3 usou Chromium 151, perfil temporário e relay efêmero: 503 preservou
  outbox; stop/wake destruiu o contexto JS e manteve cursor/identidade; restart
  inteiro preservou storage e cercou Web como observação; resultado durável
  foi entregue uma vez após ACK. O evento real nesse relaunch foi onInstalled,
  revelando cleanup ausente na recarga/atualização; a correção foi aplicada e
  22 testes JS relacionados passaram. Manifesto fonte atualizado para hash
  `051a2767f4a03fa7a1ef5dbb0f74c1b67e09745287a0bbbc19ff1b3c3301ab63`;
  22 testes de versão/protocolo passaram. Não houve reload da extensão ou
  bootstrap/credencial alterados na instalação em uso.
- RustDesk: native-proof, flutter-proof (91 arquivos) e profile-test-proof
  aprovados no candidato isolado. EXE SHA-256
  `d5b60dfa44ea22faee94d4928c3724ae367f9e858a8003be01e43887b1b53d7d`;
  DLL `2068711f65eeb6ab723491801a7eee0dadc68f736f8920fe853c1649cbfb5e3d`.
  Dois processos comprovaram perfis/config/log/IPC distintos; um terceiro
  recusou travessia. Materialização legal/SBOM, peers e instalação pendentes.
- A frente Windows entregou validador de contas, clones, console e probe de
  ACL/canários. O relatório `ASTRA_WINDOWS_COMPARTILHADO.md` diferencia usuários
  limitados com kernel/console compartilhados de base com discos diferenciais.
  101 testes relacionados passaram; nenhum probe real ou Windows instalado
  foi declarado por esses testes. A integração ao binding e os recibos do guest
  seguem em desenvolvimento.

Os três agentes permanecem nas frentes MV3/streaming, distribuição RustDesk e
Windows. O objetivo integral continua aberto, incluindo Setup assinado,
instalação limpa, aceite instalado de p95 <=300 ms, dez
inferências reais, vinte identidades de equipe e Federation entre instalações.

## Atualização posterior — componentes e conteúdo longo

Os componentes reais foram materializados em `runtime-staging-v1` fora do
checkout. Um snapshot novo alimentou o build real de `sentra-runtime-probe.exe`;
o programa congelado selecionou QuickJS/HCS/RustDesk sem ambiente de artefatos,
e recusou WASM modificado mesmo com manifests adjacentes repinados. Detalhes,
hashes, limites e comandos em `ASTRA_RUNTIME_INSTALADO.md`. Esse programa é QA,
não Setup nem componente que deva ser lançado ao usuário final.

O binding instalado e os caminhos longos Windows passaram na regressão de 67
testes (três ignorados, quatro subtestes). Os caminhos privados RustDesk acima
de 260 caracteres haviam exposto uma falha real; o acesso foi corrigido mantendo
recusa de device paths/ADS e os controles de raiz/hash.

O backend da prévia longa agora conserva referências imutáveis com blocos
protegidos/deduplicados. GET autenticado, escopo vivo, paginação Unicode e
integridade passaram em HTTP real; a interface ainda precisa seguir essas
referências. Contrato e limites em `ASTRA_STREAM_CONTENT.md`. O ensaio de carga
posterior às referências passou com p95 de 243,61 ms; a última rodada, com os
hashes finais, passou com 282,16 ms e retomada de 109 ms. Segue
sintético, com host compartilhado, e não encerra o aceite instalado.
