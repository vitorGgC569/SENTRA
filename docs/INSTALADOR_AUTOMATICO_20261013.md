# Instalador automático, identidade Dot e executável de acesso

Atualizado em 13/10/2026. Trabalho realizado depois da auditoria das 18 frentes.

## Entregue no código

- Instalação com ação principal **Instalar e configurar**. Campos de chaves, pastas e ferramentas opcionais ficam recolhidos.
- Janela nativa do Windows, tema escuro inicial, botão explícito para alternar para claro sem reconstruir o formulário nem perder campos.
- Dot azul original de 512 × 512 pixels, renderização proporcional ao DPI e ICO existente com tamanhos de 16 a 256 pixels. Setup, Canvas, painel de controle, launcher e bandeja usam a identidade Dot.
- Manifesto SHA-256 do conteúdo do Setup, conferência de arquivos e espaço antes da cópia. O arquivo do cliente de túnel passa a ser incluído no pacote final; downloads na máquina de build têm repetição limitada e cache verificado.
- Instalações simultâneas são serializadas. Reabrir Setup não encerra sessões em andamento; atualização em uso continua dependendo do caminho coordenado de saída do aplicativo.
- Registro de etapa em `installer-progress.json`, sem credenciais. Reparação reaplica os arquivos e reutiliza o download; não se trata de uma transação completa com retomada em qualquer instrução.
- Falha de saúde dos serviços não vira conclusão de 100%. Repetir a verificação não recopia arquivos nem interrompe sessões.
- Túnel obrigatório para concluir a preparação para GPT6-WEB. O Edge reutiliza a automação existente de túnel/chave, com autorização no formulário, armazenamento protegido e verificação. Login e verificações da conta continuam exigindo o usuário quando o provedor solicitar.
- Renderer Electron incluído escolhido automaticamente pelo Canvas empacotado. O cliente não precisa instalar Python/Node para abrir essa interface.
- `install-next.ps1` agora chama o Setup completo, em vez de montar uma distribuição incompleta dependente de Python no PATH.
- Launcher Windows compilado, com recurso de ícone Dot e subsistema gráfico, para criar `SENTRA.exe` na área de trabalho. Na distribuição, ele resolve a instalação registrada e abre `sentra-canvas.exe`, mantendo todos os demais componentes juntos na pasta instalada. A publicação/reparação/desinstalação do launcher verifica a propriedade e o hash do arquivo.

## Executável criado neste computador

`C:\Users\vitor\OneDrive\Desktop\SENTRA.exe`

É um launcher nativo de aproximadamente 149 KiB, vinculado explicitamente à cópia de desenvolvimento em `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Abre a interface nativa existente, com o mesmo broker. Foi executado com retorno 0 e a janela SENTRA existente permaneceu disponível. **Este arquivo não é uma distribuição portátil do produto nem contém a VM.** Nesta máquina, ele usa o Python já instalado; o launcher de release utiliza exclusivamente o aplicativo empacotado.

Compilações isoladas: `.tmp/automatic-launcher/sentra-launcher.exe` (release) e `.tmp/desktop-development/sentra-launcher.exe` (checkout atual). O recibo do arquivo publicado está em `.tmp/desktop-development/desktop-launcher.json`.

Em 13/10/2026, `python -B scripts/commander/build_windows.py --phase launcher` compilou o fonte `scripts/commander/desktop_launcher.cs` para `dist/sentra-launcher.exe`. Não foi cópia de outra máquina nem dos executáveis em `.tmp`. O binário tem 151552 bytes, SHA-256 `c6d4550debe63e382565de1eaf7357715183c1fbb088bedb9e26e7bb619c7c05`, subsistema gráfico e sete recursos de ícone. Não embute o caminho deste checkout. O selo `build-provenance-launcher.json` não foi gravado: a conferência existente recusou a árvore porque outros fontes mudaram durante a compilação (`orchestrator/quality_gate.py` e `sentra_executors/uia_guest_worker.py`; na repetição, `sentra_marketplace/surface.py`). Essa recusa não foi desligada e nenhum recibo foi inventado.

## Validação

### Integração Codex e túnel obrigatório

- O Setup não considera o MCP local suficiente: exige saúde do túnel, credenciais aceitas pela projeção de onboarding e ausência de reautenticação pendente. O modo silencioso retorna 2 quando a conexão necessária não está verificada, inclusive sem Tunnel ID na linha de comando. Credenciais já salvas continuam sendo reutilizadas.
- `sentra_remote/codex_setup.py` prepara o pacote local `sentra-commander@sentra-local` na pasta de estado, registra marketplace/plugin pelos comandos oficiais do Codex e confirma instalação, ativação e uma chamada MCP real a `sentra_health`.
- O plugin existente com endpoint compatível é preservado. Um plugin desativado ou apontando para outro endpoint exige revisão; configurações, políticas de aprovação e cache do usuário não são sobrescritos diretamente. Codex ausente ou incompatível é pendência explícita, com pacote preparado para nova tentativa.
- Depois de abrir o Edge autorizado, o Setup acompanha a conexão por até dez minutos, sem iniciar outra inscrição a cada consulta. Após o limite, permanece disponível a nova verificação.
- Túnel verificado deixa o assistente em 95%, com autorização na conta do ChatGPT pendente. O link interno `sentra://chatgpt-plugin` abre a orientação e copia somente o identificador do túnel. Uma chamada local não comprova instalação no ChatGPT; essa etapa não foi automatizada nem validada na conta real nesta rodada.
- O teste de integração usa o Codex real, um MCP separado em porta temporária e perfil/home isolados. Confere instalação repetível, preservação do modelo e execução real de `sentra_health`. Nunca usa uma chamada local como comprovação de autorização da conta.
- Nesta rodada, 122 testes relacionados passaram, incluindo a integração real do Codex/MCP e retomada do instalador (`.tmp/installer-required-tunnel-tests.log`). Os conjuntos de automação OpenAI/Edge também passaram durante a validação, com páginas sintéticas, sem criar chaves na conta real.

Referências oficiais: [plugins locais](https://developers.openai.com/plugins/build/plugins) e [Secure MCP Tunnels](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

### Modelos WEB e respostas longas

- A distribuição já prevê o diretório `web-models`, launcher e manifesto. Corrigido o Desktop para consumir `web-models-enabled` e iniciar esse runtime; antes, o marcador era escrito sem efetivar o autostart nesse caminho.
- A conclusão do Setup agora exige `payload_complete`, `ready`, `catalog_ready` e `turn_ready` do runtime WEB. O botão **Abrir Web Models · entrar na conta** permite abrir a interface instalada. Presença de arquivos não é tratada como login ou inferência bem-sucedida.
- Consulta real, somente leitura, ao `/healthz` local em 13/10/2026 retornou gateway pronto, catálogo com 11 entradas e upstream aceitando turnos. Incluiu `sentra/chatgpt-web/gpt-6`, `gpt-6-instant`, GPT-5.6 e Gemini. Isso é disponibilidade declarada pelo runtime atual, não comprovação de acesso efetivo a todos os modelos. “Chefe” é papel do agente, não licença/modelo separado.
- Espera padrão do CLI/provedor: 1.800 segundos; teto da execução Canvas: 3.600 segundos. O caminho binário/anexos também deixou de encerrar a observação em 180 segundos e renova a concessão de execução enquanto espera. Cancelamento continua interrompendo a observação.
- Fragmentos grandes agora são divididos integralmente em linhas JSONL limitadas, inclusive Unicode. A prévia mantém uma janela móvel de 131.072 caracteres, com teto de 500.000 caracteres enviados à prévia. O histórico confirmado não depende desses limites visuais.
- O texto anterior permanece visível durante a espera da próxima rodada. O primeiro fragmento da nova resposta substitui a prévia anterior.
- `response.completed` encerra a leitura e recupera sufixo final ausente dos deltas. `[DONE]`, cancelamento ou `response.incomplete` sozinhos não confirmam entrega. Não há repetição automática da requisição incerta.
- Checkpoints de resposta são protegidos pelo armazenamento existente, vinculados ao dono e ao turno. São gravados após 4.096 caracteres ou um segundo de novos fragmentos, e também ao sair do iterador. Podem recuperar a prévia após interrupção, mas nunca viram contexto confirmado, recibo ou execução de ferramenta. Encerramento abrupto do processo pode perder bytes posteriores ao último checkpoint.
- **193 testes passaram** na rodada final: streaming longo/Unicode, conclusão/incompletude, persistência, isolamento de proprietário, cancelamento, instalação e recuperação. Log: `.tmp/web-streaming-final.log`. O teste de fechamento do consumidor distingue explicitamente delta parcial de resposta já confirmada; o mock anterior assumia que o primeiro delta era a conclusão.
- O preflight do pacote atual continua falhando: `.tmp/installer-web-payload-check.json`. A cópia `dist/web-models` é anterior à revisão atual do patch e precisa ser reconstruída junto com o pacote; o runtime ativo não foi substituído durante os testes.

### Tentativa real e correção do gateway

A primeira tentativa real isolada, com GPT-6 WEB, entregou 120 itens e cerca de 22,8 mil caracteres. Entretanto, terminou como `uncertain`, com `response stream ended before completion`; o checkpoint protegeu o texto. Evidência local: `.tmp/web-stream-live-result.log` e banco em `.tmp/web-stream-live-state`.

O gateway tinha um caminho que detectava o cabeçalho `response.completed` em um fragmento TCP e encerrava a conexão antes de encaminhar o restante do evento. Além disso, uma janela de apenas 8 KiB podia perder o cabeçalho de um evento final grande. Agora todos os caminhos SSE remontam eventos completos (limite de 2 MB por evento), e a detecção de conclusão usa esse evento inteiro. A leitura continua incremental por evento; não espera a resposta inteira antes de transmitir os deltas.

Um teste HTTP real local reproduz o cabeçalho separado do corpo final de 200 KB, com Unicode e múltiplos chunks. A rodada adicional de gateway/conclusão/streaming passou com **89 testes** (`.tmp/web-terminal-gateway-tests.log`); há sobreposição com os 193 anteriores, portanto esses totais não devem ser somados. A tentativa posterior em gateway isolado foi bloqueada pelo runtime com `SENTRA physical browser lease rejected: HTTP 409`; não foi forçada, repetida nem declarada bem-sucedida. O gateway de produção ativo não foi reiniciado/substituído, e a confirmação ponta a ponta no runtime atualizado continua pendente. Evidência: `.tmp/web-stream-fixed-result.log`.

Na continuação, o impressor do CLI deixou de descartar um fragmento só porque a mesma frase já tinha aparecido. A conversa também deixa de apagar a prévia quando o estado é `interrupted`: o texto parcial permanece visível com “Entrega incerta. Não reenvie.”, sem sucesso e sem reenvio. O bundle em `sentra_canvas/static/desktop-assets` foi reconstruído. Nesta rodada passaram **78** testes Python (`test_orchestrated_stream`, `test_web_long_stream`, `test_sentra_model_gateway`, `test_sentra_shell_live_preview`) e **17** testes Node da prévia. Não substituem a confirmação WEB ao vivo.

### Capturas e divulgação

As capturas reais estão em [`media/2026-10-13`](media/2026-10-13): Home, Canvas e prévia do Setup. A prévia foi executada com a ação principal desativada, sem instalar ou alterar contas. O README identifica essa diferença.

O arquivo de divulgação, sem narração e sem marca d’água, está em [`media/2026-10-13/sentra-apresentacao.mp4`](media/2026-10-13/sentra-apresentacao.mp4). Texto em movimento, música original e, no encerramento, o perfil ao lado de `vitorGgC569/SENTRA`.

### Rodadas anteriores

- 174 testes passaram na etapa de automação inicial, incluindo os conjuntos de conexão OpenAI e teste de seletores em um Edge real com páginas sintéticas, sem acessar a conta do usuário. Log: `.tmp/installer-automatic-verified.log`.
- Depois das alterações de identidade e publicação do launcher, 124 testes de instalador, build, propriedade de arquivos, interface nativa, ícones e atalhos passaram. Log: `.tmp/installer-dot-tests.log`.
- 3 testes adicionais passaram: proteção de executáveis alheios; recuperação de publicação interrompida; compilação e execução de um launcher real com caminhos Unicode/espaços, argumentos e sete recursos de ícone. Não são apenas testes de strings do código.
- Após o ajuste do ícone da bandeja, 47 testes relacionados passaram novamente. Log: `.tmp/installer-desktop-verified.log`.
- A prévia nativa foi inspecionada no Windows, com o Dot e a troca escuro → claro → escuro. A prévia não executa instalação.
- Parser do PowerShell validou o wrapper `install-next.ps1`; `git diff --check` não apontou problemas de espaços.

Os conjuntos acima se sobrepõem e não devem ser somados como testes únicos. Não houve instalação completa em um Windows limpo nem login real no provedor nesta rodada.

## O que ainda impede entregar o Setup completo

O diretório `dist` atual não está apto a uma nova distribuição:

1. Contém `sentra-launcher.exe`, compilado do repositório como descrito acima. Não contém `sentra-canvas.exe`.
2. Não contém os componentes materializados QuickJS/HCS/RustDesk nem `runtime-components.json` exigidos pelo build integral. Os hashes desses artefatos seguem nulos em `sentra_remote/pending_provenance.json`.
3. O pacote Python `wasmtime` não está instalado neste ambiente, e `SENTRA_BUILD_RUNTIME_PINS_FILE` não aponta para versão, bibliotecas nativas e licenças aprovadas.
4. Não há `build-provenance-*.json`. O selo do launcher foi recusado porque a árvore mudou durante a compilação. Os demais executáveis já presentes em `dist` também continuam sem recibo do código atual.

O comando `python -B -m sentra_remote.installer --check` continua falhando, como deve. Nesta rodada a falha restante é só `sentra-canvas.exe`, com `ok` false e `verified` false. Evidência: `.tmp/installer-payload-check-after-launcher.json`. O resultado anterior, em que o launcher também faltava, permanece em `.tmp/installer-current-payload-check.json`. Os controles de distribuição não foram removidos. Isso não é um Setup completo, não instala Wasmtime, QuickJS, HCS ou RustDesk, não homologa instalação em Windows limpo e não fecha a frente comercial.

As limitações de VM, conectores e federação descritas na auditoria não são corrigidas por um novo launcher ou instalador. A interface pode abrir as áreas existentes sem que todas as capacidades estejam concluídas.
