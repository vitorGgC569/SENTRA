# GATE-5 — matriz de absorcao Machine Runtime (EXEC-001)

Escopo: comparacao **estatica** dos clones em third_party, com codigo local
especifico inspecionado. Nenhum clone executado, servidor iniciado, binario
copiado ou dependencia instalada. Uso pessoal/com amigos nao afasta obrigações
de licenca e atribuicao. Esta frente nao alterou sources de terceiros.

## A. Reuso concreto de UFO, pywinauto e Daytona

| Componente / evidencia no clone | Funcao concreta | Reuso limitado no SENTRA | O que deliberadamente NAO absorver |
|---|---|---|---|
| UFO: ufo/automator/ui_control/inspector.py, BackendFactory.create_backend, UIABackendStrategy.get_desktop_windows e find_control_elements_in_descendants | Varre desktop, encontra controles por atributos e backend UIA/Win32 | Reaproveitar **conceito** de control_type/automation_id sob PID/HWND declarado. O adapter existente faz resolucao restrita a janela e revalida owner | Nao enumerar desktop inteiro, nem publicar titulos/listas de janelas a agentes nao autorizados |
| UFO: ufo/automator/ui_control/controller.py, ControlReceiver.atomic_execution / click_input / click_on_coordinates / drag_on_coordinates | Despacha nomes de metodos UIA dinamicamente; permite coordenadas e mouse global | Manter dispatch fixo somente read_window_title, read_text ou invoke previamente autorizados | Nao importar dispatcher generico, pyautogui.FAILSAFE=False, click/drag arbitrarios; insuficiente como limite de seguranca |
| UFO: ufo/automator/action_execution.py, ActionExecutor._control_validation / execute | Confere is_enabled/is_visible e seleciona controle para acao | Rechecagem de enabled/visible no invoke, além de PID, HWND, titulo, id/tipo de controle | Nao reaproveitar delegacao de permissao do agente, nem permitir seletores ambiguos ou elementos fora da janela |
| pywinauto: pywinauto/windows/application.py, Application(backend='uia').connect(process=PID), app.window(handle=HWND) | Conecta aplicativo por PID e janela | PywinautoUIABackend ja usa estes metodos e checks de info.process_id/handle; import apenas ao executar | Nao executar Application.start, nem anexar por melhor match de titulo ou aplicativo pessoal |
| Daytona SDK: libs/sdk-python/src/daytona/_sync/daytona.py, Daytona.get(id), create(), delete(), stop() | Controle de sandbox | DaytonaSDKBackend usa get(id) para exec; Sprint 3x3 adicionou DaytonaSandboxLifecycle com get/create(snapshot params)/delete estritamente sob policy e aprovacao independente, somente recursos gerenciados | Proibido provisionar/excluir automaticamente, administrar snapshots ou parar recursos de terceiros |
| Daytona SDK: libs/sdk-python/src/daytona/_sync/sandbox.py, Sandbox.process, fs, computer_use | Ferramentas remotas, processos e GUI | Somente Sandbox.process.exec de comando literal allowlisted, com timeout e hash de resultado; dependência opcional | Nao expor fs/ssh/computer_use diretamente ou bytes de output ao Canvas |
| Daytona SDK: libs/sdk-python/src/daytona/_sync/process.py, Process.exec(command, cwd, env, timeout) | Comandos shell na sandbox | Passar apenas command exato e timeout; sem cwd/env livres | Nao permitir input gerado dinamicamente por LLM, variaveis de ambiente arbitrarias, nem exec no host |

**Decisao de design:** a API nova sentra_executors/discovery.py declara
Machine e Capability a partir de bindings explicitamente fornecidas
(`declare_windows_machine`, `declare_daytona_machine`). Ela nao descobre
processos em execucao, enumera janelas, consulta APIs Daytona nem concede
permissoes. `MachineDeclaration.register(registry)` usa o
ExecutorRegistry real; a descoberta so retorna capabilities cadastradas.
As instancias continuam sem autoridade na ausencia de PolicyDecision real.

### Caminho laboratorial read-only

`plan_read_only_tk_lab(...)` requer titulo SENTRA-UIA-LAB-*, PID/HWND
positivos e policy callback explicita. Ela constroi capability fixa
`lab.read_window_title`, com somente a acao read_window_title.
A funcao **nao abre janela, nao verifica processo, nao executa UIA**.
O teste opt-in tests/unit/test_sentra_executors_uia_lab.py e responsavel
por criar um processo Tk descartavel, confirmar que o HWND pertence
ao PID filho (inclusive via lab_discovery.discover_owned_tk_lab), passar
os dados ao builder, submeter pelo ExecutorRegistry real e encerrar a
janela. Exige SENTRA_UIA_LAB_RUN=1 e SENTRA_UIA_LAB_VM_CONFIRMED=1.
O backend repete a verificacao de escopo. A flag nao comprova isolamento OS.

Sem pywinauto ou quando nao for laboratorio interativo autorizado,
o teste da GUI real fica SKIP. Prova com backend fake so demonstra
contrato, nao conexao real ao Windows UIA.

## B. Lacunas de isolamento e ordem de integracao futura

| Sistema / arquivo inspeccionado | Problema que realmente resolve | Aplicacao ao SENTRA | Custo ou risco | Decisao |
|---|---|---|---|---|
| Windows VM / usuario reduzido (recurso do SO, NAO fornecido por UIA) | Isolar dados pessoais, identidade/token e efeitos de processos desktop | Critico antes de rodar GUI de terceiros; exigir escritorio isolado, sessao e ACL | Complexidade de VM, imagem, credenciais, desktop interativo | **P0 pre-requisito** a WindowsUIA nao confiavel |
| hcsshim/README.md, Win HCS/HNS + containerd shim | Lançamento/isolamento de Windows Containers via host compute; nao um desktop humano interativo completo | Opcional para jobs Windows headless, nao substitui desktop UIA interativo | Windows container host/Hyper-V, images, privilegios, footprint | **P1**, apenas caso haja casos de container Windows efetivos |
| gvisor/README.md, OCI runsc, kernel de aplicacao Linux | Reduçao da superficie de kernel de cargas Linux isoladas | Opcional para Linux container do lado Daytona/worker | Linux kernel, runsc e stack OCI; nao roda Win32/UIA | **P1 Linux** se executar codigo nao confiavel; nao resolve Windows desktop |
| guacamole-server/README (guacd/libguac), guacamole-client/README (web HTML5) | Visualizar e interagir com escritorio remoto via RDP/VNC/SSH | Somente gateway de sessao remota opt-in do Canvas, autenticado e isolado | Proxy, protocolo, sessao, web auth, stream de pixels e clipboard, revogacao | **P2** apos identidades, grants e instancias remotas |
| rustdesk/README.md (cliente remoto Rust, relay/rendezvous) | Acesso remoto assistido/unattended a maquinas | Alternativa a Guacamole, nao necessidade cumulativa | NAT traversal, consentimento, relays, exposicao desktop | **P3 alternativa**; escolher um so transporte por caso |
| playwright-mcp/README.md (MCP+Playwright accessibility snapshot) | Automacao DOM de paginas Web, diferente de UIA de aplicacao desktop | Usar executor browser existente e host MCP autorizado; nao duplicar pywinauto | Navegador, cookies, origem/site, tool permissions e sandbox | **P1 browser**, sob propriedade de interop/browser, NAO de EXEC-001 |

### Controles que os clones nao fornecem automaticamente

- UIA com PID e HWND restringe o alvo pretendido, mas **nao aplica ACL de SO**.
  PID/HWND podem ser reutilizados; um provedor UIA hostil pode mentir;
  aplica-se TOCTOU e riscos de observacao de campos sensiveis.
- Machine discovery deve separar **capability anunciada**, **estado
  observado**, **atestado de isolamento** e **grant de operacao**.
  Uma Machine declarada nao e uma Machine attested; inventario nao autoriza.
- No SDK Daytona, sandbox.public=False e network_block_all=True sao
  propriedades retornadas via API, NAO provas criptograficas da rede ou
  de runtime. Os fake clients nao demonstram atestacao.
- ExecutorRegistry atualizado em GATE-5 registra fingerprint canonico
  e snapshot de request e rejeita replay com arguments mutaveis alterados.
  O teste negativo permanece ativo, sem xfail. Ainda faltam deduplicacao
  *multi-processo*, fencing no ponto do efeito e reconciliação após restart.
- Depois de timeout ou cancelamento, uma thread/exec remoto pode continuar;
  o estado UNCERTAIN nao interrompe o efeito. A UI nao pode exibir sucesso
  falso nem reexecutar silenciosamente.
- Guacamole/RustDesk sao meios de controle/visualizacao, **nao** fazem
  autorizacao SENTRA nem isolam apps por si so. Playwright MCP necessita
  de policy e isolamento de browser; nao fornece Win UIA.
- Ativar serviços externos exige avaliacao de licenca, arquitetura,
  autenticação/SSL, logs e revogacao; nenhuma ativacao nesta frente.

## C. Resultado e gating

Arquivos de prova:
- tests/unit/test_sentra_executors_discovery.py: inventario sem I/O,
  laboratorio read-only e integracao com Registry real (backend fake).
- tests/unit/test_sentra_executors_uia_lab.py: GUI real Tk+pywinauto,
  opt-in e sem tocar apps pessoais; pula se prerequisitos faltarem.
- tests/unit/test_sentra_executors_gate3.py: gates de revogacao,
  timeout, concorrencia, mutacao/replay (agora regressao positiva).

Referencias complementares: README.md, SPRINT3X3_HANDOFF.md e
INTEGRATION_HANDOFF_GATE3.md neste diretorio. Sprint 3x3 adicionou
UIA discovery exata por PID/HWND, ciclo de vida Daytona opt-in
(aprovacao dupla, nao repetir UNCERTAIN) e ReadOnlyUIAWorkflow
(RPA Tasks/UFO patterns, sem importar codigo upstream).
E2E Daytona remoto e isolamento Windows efetivo continuam NAO validados.
