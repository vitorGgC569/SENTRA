#!/usr/bin/env python3
"""Builds runs/audit_batch.json: one grounded audit prompt per specialist role."""
import json
from pathlib import Path

PROJECT = Path(r"C:\Users\vitor\OneDrive\Desktop\TycoonCardAnimeRoblox")
OUT = Path(__file__).parent / "runs" / "audit_batch.json"


def read(rel):
    return (PROJECT / rel).read_text(encoding="utf-8")


def files_block(rel_paths):
    parts = []
    for rel in rel_paths:
        parts.append(f"### {rel}\n```lua\n{read(rel)}\n```")
    return "\n\n".join(parts)


COMMON_HEADER = """Você é um especialista Luau/Roblox trabalhando num jogo real: um tycoon de
cartas anime (estilo "gacha + fábrica/esteira + plots + upgrades"), rodando
via Rojo. O objetivo é deixar o jogo PROFISSIONAL e JOGÁVEL, no mesmo nível de
qualidade/completude de jogos populares do gênero (ex: sistemas de pacote na
esteira, praça central, torre infinita, fusão/criação de cartas, ganho
offline, leaderboard).

REGRA IMPORTANTE: não use nomes ou personagens de animes reais (Naruto, One
Piece, etc.) em conteúdo novo que você criar — isso é risco de marca
registrada. Se notar isso em dados existentes, aponte no relatório, mas não é
sua tarefa corrigir agora. Foque em MECÂNICA e CÓDIGO, não em arte (arte será
resolvida separadamente).

Esta é uma sessão persistente: vou continuar te mandando mensagens de
acompanhamento nesta mesma conversa, então você pode manter contexto entre
rodadas.

Por enquanto, isto é uma AUDITORIA, não peça pra implementar nada ainda.
"""

FORMAT_FOOTER = """
FORMATO DA RESPOSTA:
Liste os problemas encontrados, numerados, cada um com:
1. [Título curto]
   - O que está errado / faltando
   - Por que importa (impacto no jogador ou no negócio)
   - Direção de correção sugerida (1-2 frases, sem código ainda)

Ordene por prioridade (mais crítico primeiro). Seja específico e cite nomes
de função/arquivo. Não precisa ser exaustivo sobre estilo de código; foque em
bugs reais, funcionalidades quebradas/órfãs, exploits e gaps de gameplay.
"""

roles = {}

# ---------------------------------------------------------------------------
roles["Server-Economia"] = COMMON_HEADER + f"""
SUA ÁREA: sistema de economia de cartas (rolagem de gacha, criação de carta,
upgrade de nível, grade/nota).

{files_block([
    "src/Server/CardService.luau",
    "src/Shared/CardGradeService.luau",
    "src/Shared/PackData.luau",
    "src/Shared/CardData.luau",
    "src/Shared/TraitData.luau",
])}

JÁ SEI (não precisa redescobrir, mas pode aprofundar):
- CardData usa nomes de animes reais como flavor text (campo Anime) — risco
  de marca, fora do seu escopo corrigir agora, só mencione.
- FuseCards é um RemoteEvent declarado em NetworkEvents mas não existe
  NENHUMA função de fusão de cartas em CardService, nem handler no servidor.
  Avalie se vale a pena desenhar esse sistema (fusão de cartas duplicadas em
  uma mais forte é comum no gênero).

Além disso, procure por: exploits na rolagem de raridade/trait, edge cases em
UpgradeCardLevel (custo pode ficar negativo/travado?), falta de cap/validação
em CreateCardInstance, e qualquer inconsistência entre CardData/PackData/TraitData.
""" + FORMAT_FOOTER

# ---------------------------------------------------------------------------
roles["Server-Progressao"] = COMMON_HEADER + f"""
SUA ÁREA: progressão do jogador (upgrades, rebirth, leaderboard, persistência
de dados).

{files_block([
    "src/Server/UpgradeManager.luau",
    "src/Server/RebirthManager.luau",
    "src/Server/LeaderboardManager.luau",
    "src/Server/PlayerDataStore.luau",
    "src/Shared/UpgradeData.luau",
])}

JÁ SEI (não precisa redescobrir, mas pode aprofundar):
- RebirthManager.Rebirth() existe e funciona isoladamente, mas NÃO há
  RemoteEvent "Rebirth" registrado em NetworkEvents, nenhum handler no
  MainServer chamando essa função, e nenhum botão de UI a aciona. É um
  sistema morto/inacessível. Proponha como conectar (nome do remote, onde
  entra no fluxo, validações necessárias no servidor).
- UpgradeData tem campo RobuxCost em alguns upgrades (ex: LuckBoost = 19)
  mas não há nenhum caminho de compra via Robux implementado em lugar
  nenhum do projeto (isso é mais do time de Client-Gameplay, mas avise se
  achar algo do lado servidor que falte, ex: ProcessReceipt de
  MarketplaceService).

Além disso, procure por: race conditions no PlayerDataStore (leitura/escrita
concorrente), perda de dados em crash/kick, falta de retry/backoff adequado,
custo de upgrade que nunca fica inatingível vs. infinito, e se o sistema de
leaderboard atualiza de forma eficiente (a cada 30s ele salva E lê pra TODOS
os jogadores - isso escala bem com muitos players simultâneos?).
""" + FORMAT_FOOTER

# ---------------------------------------------------------------------------
roles["Server-Mundo"] = COMMON_HEADER + f"""
SUA ÁREA: mundo do jogo (plots 3D, esteira/conveyor, praça, remotes centrais
do servidor) + avaliar a criação de um sistema de missões (Quests) do zero.

{files_block([
    "src/Server/PlotManager.luau",
    "src/Server/ConveyorManager.luau",
    "src/Server/PlazaManager.luau",
    "src/Server/MainServer.server.luau",
    "src/Shared/QuestData.luau",
])}

JÁ SEI (não precisa redescobrir, mas pode aprofundar):
- QuestData.luau define 3 missões (OpenPacks, ReachGradeS, PlaceCards) mas
  NÃO existe nenhum "QuestManager" no servidor, nenhum RemoteEvent de
  progresso de missão, e nenhuma UI (isso será feito pela sessão
  Client-Gameplay). Proponha o desenho de um QuestManager.luau novo: como
  rastrear progresso por jogador, quando persistir (via PlayerDataStore),
  que RemoteEvents são necessários.
- ConveyorManager.SpawnPackOnConveyor roda automaticamente em loop (via
  ConveyorManager.CreateConveyorForPlot) SEM cobrar Cash nenhum — ele gera
  pacotes de graça periodicamente, mesmo quando o BuyPack (via loja) cobra
  normalmente. Confirme se isso é intencional (mecânica idle passiva "sua
  fábrica produz sozinha") ou se deveria ter algum custo/limite, e documente
  a intenção.
- Nos RemoteEvents em MainServer, avalie falta de validação: PlaceCard não
  valida se invIndex é um índice válido além de checar se o card existe;
  não há debounce/rate-limit em nenhum remote (um cliente malicioso pode
  spammar BuyPack, SellCard etc. em loop apertado).

Além disso, procure por: bugs na geração dos plots (posições podem colidir
entre múltiplos jogadores?), falhas na esteira quando o jogador sai do jogo
no meio da animação (tween.Completed ainda tenta dar carta pro player que
saiu?), e falta de anti-exploit nos remotes que você tem acesso.
""" + FORMAT_FOOTER

# ---------------------------------------------------------------------------
roles["Client-Nucleo"] = COMMON_HEADER + f"""
SUA ÁREA: shell de UI principal (navegação, menu esquerdo, som, ponto de
entrada do cliente).

{files_block([
    "src/Client/UIController.luau",
    "src/Client/NavigationUI.luau",
    "src/Client/HotbarUI.luau",
    "src/Client/LeftMenuUI.luau",
    "src/Client/SoundController.luau",
    "src/Client/MainClient.client.luau",
])}

JÁ SEI (não precisa redescobrir, mas pode aprofundar):
- HotbarUI.updateDisplay mostra sempre os 4 primeiros itens de
  playerData.Inventory (ordem bruta do inventário), não os cards realmente
  "equipados"/colocados nos pedestais (PlacedCards). Avalie se o hotbar
  deveria refletir PlacedCards em vez de Inventory bruto, e proponha a
  correção.
- LeftMenuUI tem botões fixos: Loja, Índice, Melhoria, Itens, Pronto. Não
  existe nenhum botão para "Renascer" (Rebirth) nem para "Missões" (Quest) —
  ambos sistemas existem ou serão criados no lado servidor mas não têm
  entrada na UI. Avalie onde encaixar esses botões nesse menu.

Além disso, procure por: badges com contadores fixos hardcoded (ex: "Pronto"
sempre mostra badge "3" e "Loja" sempre "1", independente do estado real —
deveriam refletir dados reais como UnclaimedRewards), falta de feedback
visual ao clicar, e problemas de responsividade (tamanhos fixos em pixels
que podem quebrar em telas menores/mobile).
""" + FORMAT_FOOTER

# ---------------------------------------------------------------------------
roles["Client-Gameplay"] = COMMON_HEADER + f"""
SUA ÁREA: telas de gameplay interativo (loja, inventário, stats, melhorias)
+ avaliar UI nova de missões (Quests).

{files_block([
    "src/Client/ShopUI.luau",
    "src/Client/InventoryUI.luau",
    "src/Client/StatsUI.luau",
    "src/Client/UpgradesUI.luau",
])}

JÁ SEI (não precisa redescobrir, mas pode aprofundar):
- BUG CONFIRMADO: em ShopUI.luau, o botão "buyRobuxBtn" (comprar pacote com
  Robux) é criado e estilizado mas NUNCA tem um `.MouseButton1Click:Connect`
  — não faz absolutamente nada quando clicado. A monetização via Robux dessa
  tela está completamente quebrada. O fluxo correto envolveria
  MarketplaceService:PromptProductPurchase com um Developer Product
  configurado no Studio, mais um handler ProcessReceipt no servidor.
- Mesmo problema em UpgradesUI: UpgradeData tem RobuxCost para alguns
  upgrades (ex: LuckBoost = 19 Robux) mas a UI de melhorias só mostra/liga o
  botão de compra com Cash, nunca com Robux.
- IndexUI.updateDisplay (não é sua área diretamente, mas repare) está vazio.
  Se quiser sugerir melhoria de exibição de progresso do jogador aqui, pode.
- VipBadge em StatsUI é só decorativo (não reage a clique nem reflete status
  real de VIP do jogador).

Além disso, procure por: StatsUI badge "VIP" sem função real, falta de
confirmação antes de "Vender Tudo" (ação destrutiva de uma tacada só sem
diálogo de confirmação), e qualquer outra ação de UI que pareça funcional
mas não está de fato conectada a um RemoteEvent.
""" + FORMAT_FOOTER

# ---------------------------------------------------------------------------
roles["Shared-Balance"] = COMMON_HEADER + f"""
SUA ÁREA: dados compartilhados, formatação, contrato de rede (não é UI nem
lógica de servidor, é a "camada de dados" usada por ambos os lados).

{files_block([
    "src/Shared/FormatUtils.luau",
    "src/Shared/NetworkEvents.luau",
    "src/Shared/QuestData.luau",
    "src/Shared/UpgradeData.luau",
])}

JÁ SEI (não precisa redescobrir, mas pode aprofundar):
- NetworkEvents declara os RemoteEvents "FuseCards" e não declara nenhum
  "Rebirth" nem nada relacionado a missões — outras sessões vão propor
  desenhos que provavelmente exigem novos remotes aqui (ex: "Rebirth",
  "ClaimQuest", "QuestProgress"). Pense em que contrato de rede seria
  necessário para dar suporte a Rebirth e Quests sendo desenhados por outras
  sessões, e proponha os nomes/assinaturas.
- QuestData tem só 3 missões fixas, sem nenhum sistema de repetição/rotação
  diária. Avalie se vale a pena.

Além disso, procure por: FormatUtils.FormatMoney tem algum bug de precisão
ou overflow em números muito grandes (o jogo trabalha com valores até
"Caos" ~1 bilhão+ com multiplicadores compostos, pode passar de Cent/1e69),
consistência de nomenclatura entre os campos de dados usados no cliente e
servidor, e qualquer duplicação de lógica de formatação/dados que poderia
virar uma função compartilhada.
""" + FORMAT_FOOTER

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(roles, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {OUT} with {len(roles)} roles")
for role, prompt in roles.items():
    print(f"  {role}: {len(prompt)} chars")
