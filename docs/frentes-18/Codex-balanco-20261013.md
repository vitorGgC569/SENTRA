# Balanço das frentes em 13/10/2026

Nenhuma das 18 frentes está homologada. Este documento separa implementação, evidência relatada pelos agentes e prova de produto que continua pendente. Os testes históricos abaixo não foram todos reexecutados nesta recuperação da interface.

## Recuperação solicitada pelo usuário

- Referência visual: commit GitHub `cf960e92aa087aa7e82485dc1de7671cc6f09543`.
- A Home voltou à apresentação antiga, com os PNG originais dos Dots. CSS e importações do redesign foram retirados da apresentação ativa; o trabalho anterior permanece no backup e nos arquivos de evidência.
- Não houve reset do checkout. Alterações não visuais foram preservadas. O backup está em `.tmp/codex-visual-restore-20261013-085536/`.
- O conjunto completo de apresentação foi instalado em um diretório de assets com versão própria, com HTML trocado por último. Não houve mistura deliberada de JS novo com CSS antigo.
- Verificação privada da Home em 1440, 768 e 390: PNG antigos, sem SVG de mascote, sem despejo de tokens `message.uncertain`, sem estouro horizontal e sem erro de API/JavaScript.
- Foi corrigido um defeito do lançador Electron: o parâmetro `surface` era acrescentado depois de `#token`, contaminando o bearer. A composição agora preserva o token no fragmento. Cinco testes de política/identidade passaram.
- Leitura autenticada do broker existente confirmou Oxta com **6 Dots, 42 conversas e 6 Spaces**. Não houve criação para substituir dados, exclusão ou replay.
- O lançador temporário utilizado inicialmente não era reconhecido pelo mecanismo de foco da janela nativa. A janela foi reaberta com o comando oficial `pythonw -m sentra_canvas --ui native --surface desktop`. Um segundo lançamento saiu com código 0 e manteve a mesma janela, sem iniciar outro broker.
- O broker PID 6836 permanece em execução. Reabrir o display não carregou as mudanças Python no broker e não constitui homologação das APIs recentes.

## Implementações e lacunas

| Frente / responsável | O que avançou | Evidência disponível | O que falta para fechar |
| --- | --- | --- | --- |
| 1 / Flint | Despacho vivo, retenção da resposta do coordenador, revisão de lanes e finalização do trio com recibos. Integração em shell runtime/actor. | Portão e testes de despacho; admissão artificial e runner injetado continuam explicitamente sem inferência física. | Três inferências reais autorizadas, com processos, recibos centrais e revisão no produto. |
| 2 / Marlin | Reconciliação observacional da instalação Debian; ponte de verificação com credencial do registro, sem senha no argumento. | Instalação Debian já observada; testes de bootstrap e contratos. As duas consultas posteriores ficaram UNCERTAIN, sem Operation central SUCCEEDED. | Verificação contemporânea central bem-sucedida. Não repetir as duas chaves antigas nem reinstalar a VM. |
| 3 / Marlin | Contrato de importação por pasta absoluta e chave nova, com ligação ao botão do shell. | Testes de importação/ponte, sem prova de cópia nova no guest. | Importação real após verificação central confirmada e recibo dos arquivos. O tar antigo permanece preservado. |
| 4 / Iris | Primeiro input pelo SemanticUIAExecutor, PID vinculado ao motor; caminho de worker gráfico no guest. | 13 testes Python e captura real do greeter Debian 1280×800; nenhum teclado ou mouse enviado nessa captura. | Sessão gráfica desbloqueada e execução de Computer Use real autorizada, com recibo. |
| 5 / Pylon | Reconciliação de família/incidente ligada a Run, conversa e Grant; observa sem reexecutar efeito. | Testes de ciclo de vida e planos observacionais. | Percurso real de recuperação e reinício do produto, sem replay ou exclusão indevida. |
| 6 / Iris | Guardas de imagem nativa e preservação do coletor/service worker. | Três testes Node; coletor identificado, hash preservado. | Bytes reais da imagem e entrega nativa confirmada. O websend incerto não foi repetido. |
| 7 / Pylon | Diário diferencia fase explicitamente comprovada antes da admissão de efeito possível. Exceção sem marcador permanece UNCERTAIN, phase null, sem retry. Diagnóstico sanitizado. | Três testes do ShellHostRequests. | Código carregado e comportamento real de recuperação. Nenhuma correção em massa da fila/leases foi feita. |
| 8 / Lumen | Shell Home/Canvas/Computador, navegação, recibos, rede e opcionais; sucessivas correções de colisão, foco, menu e agrupamento. A apresentação foi revertida a pedido do usuário. | Capturas contra API real e aceites parciais de bytes específicos; rollback visual verificado. | Homologação dos fluxos de produto completos. Capturas de apresentação não provam execução de VM, rede ou modelos. |
| 9 / Lumen + Latch | Identidade de janela/ícone e pacote copiado, launcher relativo à própria árvore, marcador de instalação. | Testes de stage/instalador e HTTP 200 de assets na árvore temporária. | Instalação limpa, dependências independentes do host, ícone/atalho/taskbar, atualização e rollback reais. |
| 10 / Flint | Admissão de provedores e requisitos do trio; distingue login de inferência. Memória exige fonte native_process e auditoria selada. | Regressões corrigidas; Codex login observado. OpenCode sem integração autenticada no último relato. | Autenticação concreta de todos os runners e execução real; Antigravity não interativo ainda sem contrato provado. |
| 11 / Nimbus | LiveDotSession persiste plano/contexto/sessão e isola outro Dot. Memória do despacho depende do recibo real do runner. | Teste com outro processo Python reabrindo o diretório. | Persistência e handoff nas sessões reais, após reinício do processo do produto. |
| 12 / Nimbus + Marlin | Atribuição de processos Canvas/terminal/VM, admissão por orçamento, preparação autorizada de mudança com recibo/rollback; contrato resource.cap. | Cinco testes selecionados e teste de recusa sem autoridade. Nenhuma VM real teve CPU/RAM/cap alterados. | Invocação pelo executor central, medição atribuída completa e efeito autorizado em ambiente adequado. |
| 13 / Quartz + Flint | Auditoria v2 do final do runner com modelo real, hashes de entrada/saída, tool, Grant e lease/fence reais. Admissão determinística não sela. | Testes de auditoria/recibo e correção da regressão que salvava sessão cedo demais. | Decisão viva deste host percorrendo todo o ledger de produção. |
| 14 / Sable | Pacote local optional_connectors executável, Grant existente, recibo com caminho e replay sem efeito duplicado. API do shell deriva identidade do host e fixa o registro de pacotes. | 16 testes do corte local; dois testes da API/contrato. | Conector externo com conta e execução real no produto, automação/plugin úteis e recibos centrais. |
| 15 / Wren + Lumen | API de equipes/rede no mesmo Control Plane; convite/revogação/conversa/delegação/revisão com WorkItem, Operation e lease. | Contratos e testes loopback. Leitura não cria identidade nem abre listener. | Integração carregada e visível, contas/escopos reais e uso confirmado. |
| 16 / Quartz + Latch | Licença, cinco documentos comerciais, diagnóstico e arquivos de auditoria incluídos no install-next; versão 1.0.0. | Diagnóstico do pacote sem omissões previstas, closes_front_16 false. | Percurso instalado completo, pacote autossuficiente e validação de suporte/licenças no ambiente limpo. |
| 17 / Sable | Marketplace/modelos/conectores com leitura sem opt-in, registro fixo de pacote e autoridade derivada; ausência permanece explícita. | Pacote local útil e contratos; torch/onnxruntime/PIL importáveis no relato. | Catálogo instalado, pesos visuais, imagem real inferida, QuickJS no guest e opt-in produtivo autorizado. |
| 18 / Wren + Latch + Lumen | Delegação entre dois processos com artefato JSON, hash conferido, revisão e reconciliação sem segundo efeito; identidade persistida no disco. | Sete/oito testes de loopback conforme o corte. | Dois computadores físicos autorizados, pareamento, VPN real e efeito remoto confirmado. VPN não substitui autorização. |

## Trabalhos adicionais

| Responsável | Entrega | Limite atual |
| --- | --- | --- |
| Latch | install-next copia runtime, Canvas, assets, ICO, LICENSE, documentos comerciais e parte de sentra_quality; CMD inicia da árvore copiada; handshake loopback preserva UNCERTAIN. | Python/pywebview/WebView2 e pacotes do host ainda são dependências. HTTP de assets não prova o produto completo instalado. Sem SENTRA-Setup.exe homologado em Windows limpo. |
| Brook | Stream do CLI ligado a one-shot, REPL e continuação; deltas e diretivas uma vez; UNCERTAIN mantém exit 3; exit 0 não sela trio. | Testes de stream/one-shot, sem trio físico. Não altera o broker. |
| Pebble | SVGs/poses/motion, working somente com execução validada pelo host; reduced-motion e PNGs preservados. | A apresentação ativa voltou aos PNG antigos. Os módulos e provas do trabalho anterior permanecem preservados. |
| Orbe | Direção visual e especificações; agrupamento, contagem honesta de registros versus envios, composição de Home/Canvas/Computador. | Protótipos/spec não equivalem à superfície servida nem a redesign aprovado. |
| Vitra | Crítica independente de pixels, hashes e larguras; detectou colisões, foco cortado, menu e limites da semântica exibida. | Aceites estritos por conjunto de bytes. Nenhum aceite de homologação integral. |
| Cadencia | Módulos de movimento, feedback, teclado/loading e stream; oito testes. | Importação visual nova retirada no rollback; trabalho preservado, sem alegar integração atual. |
| Keel | Coordenação dos cinco pares, reexecução de testes e manutenção de dossiês/matriz aberta. | Não executa a prova física faltante em nome dos donos. |
| Codex | Integrações do shell, auditoria de leituras com possíveis efeitos, candidatos separados, recuperação visual/dados e correção do handoff Electron. | Broker antigo permanece; mudanças de Python no disco não são prova de código carregado. |

## Instalador e prova Windows solicitada

O avanço confirmado é o pacote copiado com launcher independente do checkout e os arquivos comerciais/auditoria previstos. Continua pendente a instalação efetiva do SENTRA por um Dot na sua VM Windows, com Run, WorkItem, Operation, Grant e recibo do guest. Teste unitário, instalação no host ou loopback não substituem essa prova.

Na última leitura, as três VMs registradas eram Debian; nenhuma foi convertida ou reinstalada. Há `Isos/Windows.iso`. A escolha do destino Windows foi perguntada ao usuário: nova VM descartável ou Windows existente identificado. Não há autorização inferida para converter as VMs protegidas.

O preflight local do contrato `validate_desktop_bundle` aceitou os arquivos presentes, em leitura, sem iniciar build. PyInstaller, pywebview, cryptography e pydantic estão disponíveis no host; isso não prova que estarão empacotados ou disponíveis no guest. A prova de instalação Windows continua pendente.

## Coordenação e proteção de estado

A tentativa de reconectar Maestri encontrou o pipe ativo, mas recebeu HTTP 403 por trial encerrado/workspace bloqueado. Não houve bypass, impersonação do terminal anterior ou criação de agentes duplicados. Portanto, o estado atual de todos os terminais não foi confirmado nesta recuperação.

Nenhuma operação UNCERTAIN foi repetida. Não foram apagados Dot, VM, VDI, conversa ou diretórios de estado. A separação entre leitura observacional e reconciliação/admissão permanece necessária: alguns handlers GET/read podem alterar autoridade, e o candidato de Canvas/Computador não recebeu uma captura limpa por contorno da guarda.
