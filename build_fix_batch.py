#!/usr/bin/env python3
"""Builds runs/fix_batch_1.json: focused implementation prompts for the top
blocker in each of 3 areas, sent as follow-ups in the same persistent
sessions from the audit round."""
import json
from pathlib import Path

OUT = Path(__file__).parent / "runs" / "fix_batch_1.json"

FOOTER = """
FORMATO DA RESPOSTA:
- Explique em 2-3 frases a abordagem escolhida.
- Depois, forneça o patch como um diff unificado dentro de um bloco
  ```diff ... ``` (formato --- a/caminho / +++ b/caminho / @@ ... @@).
- Se precisar criar um arquivo novo, mostre o conteúdo completo dele com o
  caminho claramente indicado, fora do bloco de diff.
- Não inclua nada fora do escopo pedido nesta mensagem.
"""

batch = {}

batch["Server-Progressao"] = f"""
Vamos implementar as correções mais críticas que você apontou na auditoria,
uma de cada vez. Comece por estas duas (são as que mais colocam progresso
real do jogador em risco):

1. [Falha de GetAsync não deve virar wipe] Em PlayerDataStore.LoadData(),
   hoje qualquer falha de leitura (fora do Studio, após esgotar as
   tentativas) faz sessionData[player.UserId] = deepCopy(DEFAULT_DATA), e o
   jogo segue normalmente — o próximo autosave grava esses defaults por
   cima do save real. Implemente: se a leitura falhar (não simplesmente
   "não existe save"), marque o jogador com um estado de falha e IMPEÇA
   qualquer SaveData() para esse jogador nesta sessão (não sobrescreva
   nada). Pode expulsar o jogador com uma mensagement clara, ou mantê-lo
   sem salvar progresso, mas nunca grave defaults por cima de um save que
   simplesmente não pôde ser lido.

2. [Race condition no load inicial] PlayerAdded chama LoadData(), mas
   GetData() também chama LoadData() se sessionData ainda não existir.
   Como GetAsync() faz yield, duas chamadas concorrentes podem pisar uma na
   outra. Implemente um estado por jogador (ex: "Loading" / "Loaded" /
   "Failed") com uma única operação de load compartilhada (ex: usando uma
   promise/coroutine única por jogador), de forma que chamadas concorrentes
   aguardem o mesmo load em vez de disparar leituras duplicadas.

Mantenha os nomes de função públicos existentes (LoadData, GetData,
SaveData, Init) para não quebrar quem já usa PlayerDataStore.
""" + FOOTER

batch["Server-Mundo"] = f"""
Vamos implementar a correção mais crítica que você apontou: a alocação de
plots quebrada em multiplayer.

Problema: em PlotManager.AssignPlot(), plotCount = #assignedPlots + 1, mas
assignedPlots é indexado por player.UserId (não é um array sequencial), então
# não reflete corretamente a contagem/próximo índice livre. Múltiplos
jogadores podem receber o mesmo plotCount e a mesma origin, ficando com
bases sobrepostas.

Implemente um allocator de slots real: uma lista/pool separada de índices de
plot disponíveis (ex: de 1 até um MAX_PLOTS razoável, ou crescente sob
demanda), que aloca o próximo índice livre para cada jogador e devolve esse
índice ao pool quando o jogador sai (Players.PlayerRemoving) — hoje não
existe nenhum teardown/liberação de plot, então adicione isso também
(destruir o Model, cancelar o conveyor daquele jogador, remover de
assignedPlots, e devolver o índice ao pool).

Mantenha assignedPlots como o mapa UserId -> Model para as demais funções
(GetPlot, RefreshPlotDisplay etc.) continuarem funcionando sem mudanças.
""" + FOOTER

batch["Server-Economia"] = f"""
Vamos implementar a correção mais crítica que sua auditoria encontrou: o
MinRarity dos pacotes sendo completamente ignorado na rolagem.

Problema: CardService.RollCard() sempre monta o pool a partir de
CardData.Cards inteiro, sem filtrar por PackData.MinRarity. Isso faz o
"Pacote Divino" (MinRarity = Lendário) entregar algo abaixo de Lendário em
~97% das rolagens — quebra o contrato do pack.

Implemente: RollCard deve construir o pool de cartas elegíveis respeitando
MinRarity do pack (ou seja, somente cartas cuja Rarity seja >= MinRarity
numa ordem de raridade bem definida — Comum < Incomum < Raro < Épico <
Lendário < Mítico < Divino < Caos), e só então aplicar os pesos/luck sobre
esse pool filtrado. Se o pool filtrado ficar vazio por algum motivo
(config inválida), caia para o comportamento atual como fallback seguro em
vez de travar.

Não mude a assinatura pública de RollCard (ainda deve receber player,
packId) nem o retorno (CardDef, TraitDef).
""" + FOOTER

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {OUT}")
for role, p in batch.items():
    print(f"  {role}: {len(p)} chars")
