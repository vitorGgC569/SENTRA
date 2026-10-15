# Sable — frentes 14 e 17

Data: 2026-10-12. Checkout: `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Sem commit, push, reset ou clean.

## Escopo

Frente 14: conectores, skills e plugins opcionais, com recibo e falha explícita. Deny-only não fecha a capacidade. Plugin não concede Grant a si mesmo. Conteúdo externo não substitui instrução superior.

Frente 17: marketplace e modelos visuais locais especializados, opt-in, com indisponibilidade explícita quando o modelo ou o pacote não está presente.

Efeito admitido exige Run, WorkItem, Operation e Grant já emitido pelo host. O módulo não chama `grant`. Recibo `UNCERTAIN` não é reenviado.

## Código neste checkout

- `sentra_marketplace/`: política allow contra deny-only, cerca de conteúdo, pin de pacote local, gate com recibo, catálogo, conectores conhecidos e disclosure de skill.
- `local_model/visual.py`: modelo visual local opt-in. Qwen de texto não substitui visão. Sem pacote ou sem runtime visual, a resposta é indisponibilidade.
- `sentra_code_mode/optional_surface.py` e `build_fenced_tool_map(..., exposure=)`: deny-only não devolve mapa vazio como se a superfície estivesse fechada. Ferramenta com `self_grant` é recusada.
- `skills/optional_connectors/SKILL.md`: texto de dados. Não executa e não concede Grant.

Não houve download, socket de conector, nem carga de pesos.

## Teste unitário executado agora

Comando, na raiz do checkout:

```text
python -B -m pytest tests/unit/frentes/sable/test_fronts_14_17.py -q --tb=short
```

Resultado: **12 passed in 4.12s**.

O teste usa `AuthorizationService` num sqlite temporário do pytest. O Grant de host é criado pelo teste, fora do gate. O gate recebe um proxy cuja chamada `grant` falha. Isso não é operação do Control Plane do usuário, não é Run de Dot e não é prova física.

Cobriu, entre outros: deny-only não invoca e não marca a capacidade como fechada; opt-in ausente fecha o uso; manifesto ou identidade de plugin não concede Grant; skill hostil continua dado e não troca a instrução superior; retorno de Grant pelo efeito é ignorado; pacote ausente e hash divergente falham explícito; `UNCERTAIN` e falha de executor não são reenviados; catálogo e conector exigem pacote local e opt-in; pacote que declara `grants` é recusado; modelo visual ausente, runtime ausente e cliente de texto ficam indisponíveis; inferência de double de teste permanece `inference_homologated: false`.

## Prova física contemporânea

Sonda somente leitura neste checkout, sem criar pacote e sem rede:

- `LocalVisualModel.readiness(None)` → `VISUAL_MODEL_NOT_OPTED_IN`, `inference_homologated: false`.
- Pacote `local_model/packs/visual` → `MODEL_PACKAGE_ABSENT`, `package_present: false`.
- Catálogo `sentra_marketplace/catalog` → `CATALOG_ABSENT`.
- Conector `github` → `CONNECTOR_PACKAGE_ABSENT`.

Isso observa a indisponibilidade real no disco de hoje. Não homologa chamada a GitHub, Drive, OneDrive, Microsoft 365 ou Slack, nem geração visual.

Lapidação: cada sonda de ausência carrega `absence_probe: true` e `connector_real`, `network`, `visual_weights` e `quickjs` em falso. Deny-only continua sem fechar a capacidade. Plugin continua sem conceder Grant. Estas marcas não são homologação.

Corte seguinte, ainda sem homologação: um conector opcional em processo, sem rede, executa uma função local e o recibo traz `connector_real: true`. Pacote ausente continua no selo de ausência. Não há conector externo, QuickJS no guest nem pesos de imagem.

O arquivo local `skills/optional_connectors/local_invoke.py`, quando presente, é a função executada e o recibo cita esse caminho. Se o arquivo não existe, o motivo continua `PACKAGE_ABSENT` e `connector_real` fica falso. Isso não homologa conector externo.

Selo de ausência não fecha conector, skill, plugin, automação, marketplace nem visão (`closed_by_absence: false`). O caminho útil é o Grant do host em `AuthorizationService.authorize`, a execução do arquivo local e o artefato JSON do recibo. A interface já existente para skill continua `center_skill_library`; esta frente não editou o shell. Não homologado.

Identificação neste checkout, sem presumir bloqueio geral de rede: `github.com:443` acessível. Runtimes importáveis: `torch`, `onnxruntime`, `PIL`. Ausentes: `diffusers`, `open_clip`, pesos em `local_model/packs/visual`, catálogo em `sentra_marketplace/catalog`. Visão pede pesos locais ou um download concreto do pacote. Conectores externos pedem conta concreta (GitHub, Google, Microsoft, Slack), não um banimento de rede. Nenhum download e nenhum login foram feitos.

## O que não está homologado

- Nenhuma chamada real de conector externo.
- Nenhum pacote de marketplace instalado a partir da rede. O catálogo não baixa.
- Nenhuma inferência visual com pesos e runtime presentes. Não há bytes de imagem, MIME nem SHA-256 de saída.
- O double de runtime no teste unitário não é modelo especializado em execução.
- O sqlite do teste não é o estado `.sentra` do usuário. Não houve Operation central ao vivo, VM ou WorkItem de produto fora do teste.
- Code Mode opcional foi decidido em memória. Não houve execução QuickJS nem efeito de ferramenta no guest.
- `UNCERTAIN` foi injetado por exceção de teste, não por um worker que caiu no host.

Teste antigo, fixture ou ACK não entra como homologação. Esta rodada não repete operação `UNCERTAIN` já registrada em outro fluxo.

## Leitura do Keel

O primeiro marco foi entregue ao Keel. Na leitura registrada em `docs/frentes-18/Keel.md`, o pytest da frente foi visto de novo (`12 passed in 5.27s`, exit 0) e o par não foi fechado. As sondas de ausência continuam sem homologar conector, rede, visão, Operation central ou QuickJS. Esta frente permanece em turno.
