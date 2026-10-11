# SENTRA Windows — evidências de release-candidate (09/10/2026)

Este arquivo descreve validações realizadas na máquina autorizada **OGrandeOxta**, repositório `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Base Git `main@e4b3968` com patches locais AINDA NÃO commitados; não se trata de uma tag/release pública. Todo instalador gerado nesta sessão é **QA não assinado**, restrito a ensaios isolados.

## Código e testes

| Suíte | Resultado | Execução |
| --- | --- | --- |
| Python `tests/unit` integral | **1962 passed, 37 skipped, 0 fail, 0 error** | 486.19s |
| Python `tests/failure tests/integration` | **183 passed, 10 skipped, 0 fail** | 143.56s |
| JavaScript `npm test --prefix sentra_collab` | **54 passed, 0 fail** | ~3s |
| Total confirmado | **2199 aprovados, 47 ignorados, nenhuma falha** | Suítes distintas, não uma só execução pytest |
| MSI/builder contratos focados | **54 passed, 1 warning** após alterar atalhos e docs | `test_sentra_canvas_installer_bundle.py`, `test_commander_release.py`, `test_build_canvas.py`, `test_installer_resume_failures.py` |

Os antigos **36 fails/1 error** do checkpoint foram corrigidos: handles SQLite abertos no Windows, IDs de origem dos benchmarks, reserva de lease para consultas/reconciliação, cancelamento de subprocessos ACP, testes antigos de UI e de RustDesk clone drift; autorização MCP de pasta explícita read-only não foi afrouxada.

## Payload Windows e Web Models

- `python scripts/commander/build_windows.py --phase payload` terminou exit **0**, 13/13 executáveis presentes na árvore `.tmp/release-candidate-20261009/dist`, com `build-provenance-payload.json` contendo SHA256 dos binários e 451 entradas das fontes. O `sentra-canvas.exe` usa React Flow/Radix/Lucide/xterm/WebView2 e manifesto SHA256 estático validado. O `sentra-cli.exe` inclui o menu numérico `/model`.
- Pacote Web Models/Electron copiado para staging QA: **6098 arquivos, 554607532 bytes**, `win-unpacked/Codex Web GPT.exe`, licença e runtime manifest; `integration-build.json.patch_sha256` é igual ao SHA256 do patch upstream pinado.
- `tunnel-client-v0.0.14-windows-amd64.zip` local, 27824988 bytes, SHA256 bateu com `sentra_remote.installer.TUNNEL_SHA256`.
- Depois do primeiro payload, dois defeitos de release foram corrigidos: `build_msi.py` agora associa atalhos do menu Iniciar e área de trabalho ao `sentra-canvas.exe` (painel separado) e `release_assets.py::build_staging` inclui `SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md`. Isso exige **segunda passagem do payload** para manter a prova de proveniência coerente, e ela foi iniciada.
- Schema MSI testado com fixture isolado: `msilib` compilou MSI de QA de 86.016 bytes; banco Windows Installer contém `SENTRA_App_Shortcut` e `SENTRA_Desktop_Shortcut` apontando para `[#sentra_canvas.exe]` e `SENTRA_Control_Center_Shortcut` apontando para `[#sentra_desktop.exe]`. Extração `msiexec /a` no diretório temporário terminou **exit 0** e extraiu 24 arquivos. Não instala registros do MSI no usuário.

## Instalação, ChatGPT e assinatura

O Setup conecta **MCP local + túnel** e conduz ao app/plugin ChatGPT, mas a aprovação final em **Plugins → Add custom MCP server → Tunnel** é sempre ação da conta/administrador ChatGPT. Nenhum túnel funcional pode provar que o app foi instalado e autorizado em outra conta. O Edge Add-ons também requer publicação/revisão própria; o pacote local inclui a extensão para instalação guiada. Docker, Codex/provider autenticado, hardware e serviços opcionais não se tornam prontos só por estarem na mídia.

**Assinatura de produção BLOQUEADA nesta máquina:** não há `signtool.exe` no PATH/Windows SDK identificado nem certificado Authenticode com chave privada disponível em `Cert:\CurrentUser\My` ou `Cert:\LocalMachine\My`. A release pública exige certificado legítimo, acesso ao signtool, timestamp e os segredos do GitHub Actions com permissões corretas. Não gerar assinatura enganosa/autossinada para fingir homologação de software distribuível.

O Git `HEAD e4b3968` ainda contém whitespace que reprova `git show --check HEAD`; a árvore tem patches locais não commitados. Nunca declarar o job remoto `CI required` verde sem novo checkpoint revisado, reexecução da CI e assinatura.

## Próximas validações do candidato

1. Aguardar segunda passagem `--phase payload` e confirmar hash/provenance dos 13/13 binários em código final.
2. Gerar `SENTRA-Setup.exe` via `--phase installer` do mesmo staging; validar hashes antes de criar release assets.
3. Gerar MSI, ZIP, SBOM, checksums via `release_assets.py` usando o ZIP pinado do túnel.
4. Instalar EXE Setup em **pasta/state temporários** com `--no-system-registration --no-launch --stop-after-doctor`; validar arquivos reais, rodar CLI empacotado com `/model`, iniciar Canvas WebView2 isolado, verificar janela e HTTP, desmontar com desinstalação e verificar ausência de resíduos. Script preparado em `.tmp/release-candidate-20261009/qa_first_install.py`.
5. Validar MSI por extração administrativa isolada `msiexec /a`, ler Shortcut/File table e hashes; testar instalação MSI interativa e migração/rollback **apenas numa VM descartável**, nunca sobre instalação principal ativa.
6. Rerodar CI required num commit revisado, assinar e testar pacotes com publisher legítimo; nenhuma etapa 5/6 pode ser substituída por testes de unidade.

Status atual: **código verde, compilações e homologação do instalador EM ANDAMENTO; assinatura pública não disponível**.

## Rodada adicional — Setup congelado e primeira instalação isolada (09/10/2026, ~20h BRT)

- Segunda passagem do payload **SUCCEEDED/exit 0**: 13/13 EXEs; auditoria independente comparou os 451 hashes de fontes com o build-provenance-payload.json (**0 divergências**) e os SHA-256/tamanhos dos 13 EXEs (**13/13 corretos**).
- build_windows.py --phase installer **SUCCEEDED/exit 0**, após 242,18s; gerou .tmp/release-candidate-20261009/dist/SENTRA-Setup.exe com **1.715.691.928 bytes**. build-provenance-installer.json registra SHA-256 a9182000cec1a9e442ed2af9a7724a4a4d4f6b31776c96261ac3fd6f3c363679. É **QA não assinado**, não distribuição.
- Primeira instalação isolada do Setup, em .tmp/release-candidate-20261009/clean-install/Commander, com --no-system-registration --no-launch --stop-after-doctor, retornou **exit 0** em 36,55s. Conferidos executáveis, documentação, Edge, Web Models e marcador. CLI **real instalado**: /model -> 1 -> /effort high -> /exit, exit 0, menu/seleção/esforço/encerramento presentes, stderr 0. Canvas instalado respondeu **HTTP 200** e serviu o bootstrap React.
- **Aceite E2E NÃO PASSOU:** a verificação de janela nativa retornou native_top_level_window=false. O teste original considerava apenas dois PIDs; a árvore PyInstaller observada incluía outro descendente. A ausência de janela NÃO foi comprovada: a fixture foi ajustada para reconciliar PIDs descendentes antes de inspecionar HWND e precisa de nova execução.
- **Uninstall assíncrono:** sentra-installer.exe --uninstall retornou exit 0, mas somente **agendou** sentra-update-helper cleanup; a fixture antiga verificou o diretório prematuramente. Depois da limpeza, permaneceram quatro avisos/licenças em licenses/tunnel-client/, pois o marcador owned_files não os incluía. Corrigido na **fonte** sentra_remote/installer.py para registrar os avisos extraídos e no QA script para aguardar a limpeza real e relatar resíduos. Também ajustados o ícone de desinstalação e o relançamento pós-update para priorizar Canvas. Testes focados de instalador/Canvas/recovery: **22 passed, 1 warning, exit 0**; git diff --check exit 0 (somente avisos CRLF).
- **IMPORTANTE:** as correções de fonte acima ocorreram **depois** do build do Setup de 1,7 GB. Portanto, esse EXE e a prova de proveniência estão agora **STALE** frente à árvore atual. Antes de novo E2E e de gerar MSI/ZIP/SBOM, reconstruir payload 13/13 + Setup com hashes novos, executar QA de instalação/desinstalação com janela WebView2 e limpeza concluída. Não publicar nem assinar como release. Broker principal/ConPTY não foram reiniciados; nenhum registro do Windows foi alterado pelo QA.

- Tentativa posterior de iniciar a recompilação obrigatória do payload 13/13 foi **bloqueada pelas verificações de segurança da ferramenta**. Não houve tentativa de contorno. Nenhum rebuild pós-correções foi iniciado nesta etapa; o candidato antigo permanece obsoleto e não distribuível.

## Identidade visual oficial SENTRA — logotipo aprovado (09/10/2026)

Foi incorporado o **arquivo aprovado pelo proprietário**, sem redesenho ou
mudança de estilo: `C:\\Users\\vitor\\Downloads\\SENTRA-LOGO.png`.
A cópia versionável `sentra_canvas/assets/SENTRA-LOGO.png` tem SHA-256
idêntico ao original (`1fa463f62b41112fb473041c3ae6ebcee0879994b2c8303a04d835a33dc6df9b`).

- `sentra_canvas/assets/SENTRA.ico`: ícone Windows oficial, frames 16,
  24, 32, 48, 64, 128 e 256 px (gerador determinístico:
  `scripts/commander/build_brand_icon.py`).
- `sentra_canvas/static/sentra-logo.png`: favicon/UI de 256px. A API local
  entrega `/sentra-logo.png` como `image/png`; o React Canvas apresenta
  a mesma marca discretamente e a superfície legada também a utiliza.
- `scripts/commander/build_windows.py::_build` incorpora o ícone como
  recurso PE no `sentra-canvas.exe`, `sentra-desktop.exe` e
  `sentra-human.exe` e leva a imagem original dentro do runtime.
- `sentra_canvas/native_app.py` e `sentra_canvas/native_brand.py` aplicam
  ambos `WM_SETICON` (grande e pequeno) **somente** ao HWND nativo da
  própria instância WebView2, evitando ícones divergentes na barra de tarefas.
- `sentra_remote/windows_integration.py` e `build_msi.py` já criam o
  atalho `SENTRA` apontando ao Canvas, cujo recurso de ícone passa a ser
  este símbolo. A bandeja/ícone Tk do painel de controle também usam a marca.
- Frontend atualizado com `npm --prefix sentra_canvas/desktop_ui run build`
  e manifesto SHA256 novamente validado.
- Testes de contrato, geração e rota do ícone: `5 passed`; regressão
  inicial junto a build/atalhos: `11 passed`.
- Build de QA `.tmp/qa-brand-20261009/dist/sentra-canvas.exe`:
  **exit 0**, **111268348 bytes**, recurso PE extraído pelo Windows
  (`embedded_icon_count=1`). No smoke de janela nativa, um novo
  HWND `SENTRA` do processo de QA apresentou `WM_GETICON` grande e
  pequeno não nulos, `desktop.html` HTTP 200. Broker temporário
  encerrado por `/api/runtime/shutdown`, HTTP 200.
- A identidade visual será vista nos atalhos criados após **novo Setup/MSI**.
  Os executáveis de produção anteriores não foram modificados nem suas
  sessões reiniciadas; a release integral ainda exige recompilar todo o
  payload com o ícone e cumprir a assinatura/homologação pendentes.

## Revisão de proveniência da marca — 09/10/2026, ~21h35 BRT

- Auditoria estática identificou que `scripts/commander/build_windows.py::_source_fingerprint` incluía `.ico`, mas **não** os dois PNGs oficiais usados no pacote (`sentra_canvas/assets/SENTRA-LOGO.png` e `sentra_canvas/static/sentra-logo.png`). Isso permitiria reaproveitar prova de payload antigo após alteração somente desses PNGs. Nenhum artefato foi promovido.
- Correção cirúrgica: ambos os caminhos agora participam do SHA-256 de fontes do payload, sem incluir capturas de QA/evidências não distribuídas. Teste negativo em `tests/unit/test_build_payload_provenance.py` verifica os dois hashes e detecta mutação do favicon.
- Validação local sequencial: `python -B -m pytest -q -p no:cacheprovider tests/unit/test_build_payload_provenance.py tests/unit/test_build_canvas.py --disable-warnings` → **9 passed, 0 failed, exit 0**, PID 32880, 0,82s pytest. Não equivale a rebuild.
- A marca oficial também foi incorporada ao Canvas e ao ícone PE conforme evidências anteriores. O Setup de 1,7 GB e os 13 EXEs anteriores continuam **STALE e NÃO homologados**, agora também por essa correção de proveniência e pelos assets da marca. O rebuild de payload foi anteriormente bloqueado pela segurança da ferramenta; não se tentou contornar, e não houve instalação, assinatura, commit ou publicação.

## Proveniência do frontend React — revisão adicional (09/10/2026, ~22h BRT)

- Auditoria de `scripts/commander/build_windows.py::_source_fingerprint` revelou que as extensões de origem rastreadas incluíam `.js`, mas **não `.jsx`**, embora o frontend principal use `sentra_canvas/desktop_ui/src/main.jsx`, `nodes.jsx` e outros componentes JSX. Uma alteração somente nesses arquivos poderia manter o fingerprint antigo, sem invalidar um payload cujo bundle estático não tivesse sido reconstruído.
- Correção restrita ao builder de release: a lista de extensões rastreadas agora inclui `.jsx`, `.ts`, `.tsx` e `.svg`, preservando a exclusão de `node_modules`, `dist`, `build` e evidências PNG não distribuídas. Novo teste `test_release_provenance_tracks_react_jsx_sources` confirma que `main.jsx` é registrado com SHA-256 e sua mutação altera a prova.
- Execução real sequencial: `python -B -m pytest -q -p no:cacheprovider tests/unit/test_build_payload_provenance.py tests/unit/test_build_canvas.py --disable-warnings` -> **10 passed, 0 failed, exit 0**, PID 29612, 2,01s pytest. Não houve recompilação de payload/Setup nem alteração do broker instalado.
- Consequência: os 13 EXEs e o Setup de 1,7 GB anteriores permanecem **STALE**, também por esta alteração na proveniência. O rebuild integral anteriormente bloqueado pela ferramenta **não foi repetido nem contornado**. Não há MSI/Setup homologado ou assinado; validação nativa WebView2 e desinstalação limpa do novo candidato continuam pendentes.

## Proveniência do Web Models — revisão adicional (09/10/2026, ~23h50 BRT)

- Auditoria estática identificou duas entradas reais do build que não participavam do fingerprint de release: `scripts/integrations/Build-CodexChatGPTWebRuntime.ps1` (pasta fora do conjunto rastreado) e `integrations/codex_chatgpt_web/sentra-upstream.patch` (extensão `.patch` ausente). O instalador verificava o hash do patch contra `integration-build.json`, mas não cobria o script de construção no mesmo fingerprint de fontes.
- Corrigido `scripts/commander/build_windows.py::_source_fingerprint` para rastrear `scripts/integrations` e `.patch`. Adicionado teste negativo `test_release_provenance_tracks_web_models_builder_and_patch`, comprovando inclusão SHA-256 e invalidação após mutação de ambos os arquivos.
- Execução focada sequencial na raiz do repo: `python -B -m pytest -q -p no:cacheprovider tests/unit/test_build_payload_provenance.py tests/unit/test_build_canvas.py --disable-warnings` → **11 passed, 0 failed, exit 0**, PID 40408, 1,80s pytest. A primeira invocação, fora da raiz, não encontrou os testes; foi corrigido apenas o diretório de trabalho, sem alterar código.
- Não houve rebuild de payload/Setup, instalação, assinatura, commit ou publicação. O build integral anteriormente bloqueado por segurança não foi contornado. Os 13 EXEs e o Setup antigo permanecem **STALE / QA não homologado**; o novo fingerprint exigirá nova compilação legítima. Broker instalado e sessões ConPTY preservados.

## Proveniência dos avisos legais e onboarding — 10/10/2026, ~00h50 BRT

- Auditoria do empacotamento identificou entradas distribuídas ainda não cobertas por `_source_fingerprint`: arquivos `.txt`/`.md` de avisos legais no Edge, Canvas e Electron; licenças sem extensão do xterm/addon-fit; e o guia obrigatório de primeira instalação, incluído em `docs/` no Setup. Alterações nesses arquivos não invalidavam a prova de origem anterior.
- Correção restrita a `scripts/commander/build_windows.py`: inclusão de `.txt`/`.md` nas extensões rastreadas e dos três caminhos explícitos (duas licenças sem extensão e guia de primeira instalação). Teste novo `test_release_provenance_tracks_packaged_notices_licenses_and_onboarding` verifica os seis arquivos e detecta mutação de cada um.
- Primeira execução do teste novo: **11 passed, 1 failed**, devido à expectativa de bytes LF em arquivo temporário Windows que normalizou CRLF. Corrigida apenas a fixture para comparar SHA-256 dos bytes reais do arquivo. Reexecução sequencial `python -B -m pytest -q -p no:cacheprovider tests/unit/test_build_payload_provenance.py tests/unit/test_build_canvas.py --disable-warnings`: **12 passed, 0 failed, exit 0**, PID 30172, 0,90s pytest.
- Nenhum rebuild do payload/Setup foi iniciado: a tentativa anterior de recompilação integral permanece bloqueada por segurança, sem contorno. Os 13 EXEs e Setup anteriores continuam **STALE, não assinados e não homologados**. Não houve instalação, reinício do broker, alteração de ConPTY, commit ou publicação.

## Cobertura integral da documentação distribuída — 10/10/2026, ~01h40 BRT

- Auditoria estática confirmou que `build_installer` inclui **todo** `docs/` no Setup via `--add-data`, mas `_source_fingerprint` rastreava apenas o guia de onboarding. Outros arquivos realmente distribuídos — `docs/RELEASE.md`, `MASTER_QUEUE.example.json`, vídeos `.mp4` e capturas `.png/.jpg` de `docs/onboarding_media/` — podiam mudar sem invalidar a prova de origem do payload.
- Alteração cirúrgica em `scripts/commander/build_windows.py`: acrescentado o rastreamento de **todos os arquivos regulares de `docs/`**, independentemente da extensão, coerente com o empacotamento integral existente. Novo teste `test_release_provenance_tracks_entire_packaged_docs_tree` em `tests/unit/test_build_payload_provenance.py` cobre Markdown, JSON, MP4 e PNG com mutação de bytes.
- **VALIDAÇÃO NÃO EXECUTADA:** a tentativa direta de executar `python -B -m pytest -q -p no:cacheprovider tests/unit/test_build_payload_provenance.py tests/unit/test_build_canvas.py --disable-warnings` foi **bloqueada pelas verificações de segurança da ferramenta**. Não se repetiu o comando por outros meios. As duas alterações permanecem **não homologadas**; não afirmar nova contagem de testes nem promover artefatos.
- A inclusão de `docs/` completo torna atualizações de documentação durante o build uma mudança de fonte detectável; congelar a árvore para reconstrução e verificar os testes antes de publicar. Os 13 executáveis e o Setup antigos permanecem STALE, sem assinatura. Nenhuma instalação, rebuild, reinício de broker/ConPTY, commit ou publicação nesta rodada.
