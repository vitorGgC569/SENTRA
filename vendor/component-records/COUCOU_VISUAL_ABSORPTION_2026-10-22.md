# Coucou visual absorption — contrato de implementação (22/10/2026)

**Decisão:** absorver o vocabulário visual e de interação do Coucou (MIT) no shell do SENTRA, usando exclusivamente os Dots/Oxta originais. Nenhum asset, personagem, som, ícone ou animação do Mochi/Coucou é copiado. Código MIT pode ser adaptado com atribuição; a autoridade continua no SENTRA/ORCA.

**Escopo desta rodada:** quatro frentes visuais independentes, sem tocar no trabalho não commitado de terminal input receipts. Não há commit, push, reinstalação ou alteração de hooks.

## 1. Invariantes

1. O host SENTRA continua sendo a única fonte de status, aprovação, recibo e conclusão. Nenhuma animação pode declarar sucesso sem `execution.verified === true` ou recibo confirmado.
2. Aprovação externa não cria Grant. Cartões apenas transportam a decisão para as APIs existentes (`coordinator_approval_reply`, `access_approve`, `access_reject`).
3. A ilha flutuante é opt-in, sem criar navegação paralela. Ela observa e leva às superfícies existentes.
4. `prefers-reduced-motion` desliga movimento contínuo. Companions pausam quando fora da viewport/aba oculta.
5. Nada de `position: fixed` cobrindo o terminal, o editor ou diálogos. A ilha respeita `z-index` abaixo de modais e acima do chrome.
6. Sem dependências novas. React + CSS + `lucide-react` existentes.
7. Não alterar `terminal-pool.js`, `terminal-input-*`, `terminal-checkpoint.js`, `service.py` ou testes de terminal.

## 2. Frentes e propriedade de arquivos

### Frente 1 — Ilha / presença do Oxta (coordenador)

Arquivos novos:
- `sentra_canvas/desktop_ui/src/shell-island.jsx`
- `sentra_canvas/desktop_ui/src/shell-island.css`
- `sentra_canvas/desktop_ui/src/shell-island-state.js`
- `sentra_canvas/desktop_ui/test/shell-island-state.test.mjs`

Modifica:
- `shell-app.jsx` (montagem, toggle, dados)
- `shell-polish.css` (apenas tokens/ajustes globais da ilha, se necessário)
- `test/workspace-ux.cjs` (asserção obsoleta do mascote `<img>` → `<canvas>`)
- `scripts/commander/orca_build_manifest.py` (entrada dos novos assets, ao final)

### Frente 2 — Decisões compactas (subagente A)

Arquivos novos:
- `sentra_canvas/desktop_ui/src/shell-decisions.jsx`
- `sentra_canvas/desktop_ui/src/shell-decisions.css`
- `sentra_canvas/desktop_ui/test/shell-decisions.test.mjs`

Modifica:
- `sentra_canvas/desktop_ui/src/shell-approval-notifications.jsx` (usar os novos cartões, mantendo o export e o polling)

Não modifica `shell-app.jsx`, `shell-permission-cards.jsx`, `shell-conversation.jsx`.

### Frente 3 — Conversa com presença (subagente B)

Arquivos novos:
- `sentra_canvas/desktop_ui/src/shell-chat-visuals.jsx`
- `sentra_canvas/desktop_ui/src/shell-chat-visuals.css`
- `sentra_canvas/desktop_ui/test/shell-chat-visuals.test.mjs`

Modifica:
- `sentra_canvas/desktop_ui/src/shell-conversation.jsx` (somente apresentação: header, ticker, pills, thinking, composer)

Não modifica `shell-app.jsx`, `shell-mascot.jsx`, `dot-companion-*`, `terminal-*`.

### Frente 4 — Hub, recap e drop (subagente C)

Arquivos novos:
- `sentra_canvas/desktop_ui/src/shell-hub.jsx`
- `sentra_canvas/desktop_ui/src/shell-hub.css`
- `sentra_canvas/desktop_ui/src/shell-drop-overlay.jsx`
- `sentra_canvas/desktop_ui/src/shell-drop-overlay.css`
- `sentra_canvas/desktop_ui/src/shell-hub-state.js`
- `sentra_canvas/desktop_ui/test/shell-hub-state.test.mjs`

Modifica: nenhum arquivo existente. A integração no shell é feita pelo coordenador.

## 3. Linguagem visual compartilhada

- Superfícies: vidro escuro translúcido no tema dark (`rgba(22,23,26,.86)` + `backdrop-filter: blur(18px)`), vidro claro no light (`rgba(255,255,255,.88)`), raio 18–26px, borda `1px` de baixa opacidade, sombra em duas camadas.
- Acento: âmbar do Oxta (`#F7A85C`) para presença; verde (`#34c759`) só para conclusão verificada; vermelho (`#ff453a`) para falha; azul (`#6cc3ff`) para informação.
- Tipografia curta: título 13–15px/600, meta 11–12px, sem parágrafos dentro da ilha.
- Pills: altura 26–30px, raio 999px, ícone 13–15px, no máximo 2 linhas.
- Botões: primário claro no dark e escuro no light; secundário fantasma; foco visível de 2px.
- Movimento: entrada com `transform: translateY(-6px) scale(.98)` + opacity, 160–220ms; nada de loop infinito fora do companion; `prefers-reduced-motion` remove transições e animações.
- Não usar imagens do Coucou. O mascote é sempre `<DotMascot>`.

## 4. Contratos de componente

### Frente 2 — `shell-decisions.jsx`

Exportar:
```js
export function decisionFingerprint(item)      // string estável, sem segredos
export function decisionExpiry(item, now)      // { expiresAt, remainingMs, expired }
export function summarizeDecision(item)        // modelo de apresentação seguro
export function useDecisionInbox({ bridge, projectId, inlineConversationId, pollMs })
export function DecisionCard({ decision, busy, onDecide, onOpenConversation })
export function DecisionStack({ decisions, ... })
export function ShellDecisionCenter({ bridge, projectId, inlineConversationId, onOpenConversation })
```

Requisitos:
- Reutilizar `coordinator_approval_list` / `coordinator_approval_reply` com `request_key` estável por `(approval_id, answer)`; uma decisão só é liberada após confirmação; erro incerto mantém o cartão e oferece “consultar sem repetir”.
- Estado expirado (`activity !== 'active'`) desabilita autorizar e oferece dispensar/rejeitar.
- Mostrar ferramenta/capability, resumo, comando ou diff **limitado** (máx. 12 linhas / 1.200 caracteres), origem (conversa/space), validade e botão “Ver conversa”.
- Botão “Autorizar” só quando `activity === 'active'`; nunca “sempre permitir” sem regra durável.
- `DecisionStack` deve funcionar embutido na ilha (compacto) e como centro flutuante.
- Acessibilidade: `role="region"`, `aria-live="polite"`, foco visível, botões com rótulos completos.

### Frente 3 — `shell-chat-visuals.jsx`

Exportar:
```js
export function chatPresenceModel({ dot, messages, livePreview, connectionState, busy })
export function ChatPresence({ dot, model, onOpenCanvas, onOpenDot })
export function ChatTicker({ items, muted })
export function ChatEventPill({ kind, label, detail })
export function ChatThinking({ dot, label })
```

Requisitos:
- Header compacto com DotMascot, nome, estado real, modelo e “abrir Canvas”; sem duplicar ações existentes.
- Ticker de até 4 passos derivados de mensagens/eventos já carregados; nada de polling novo.
- Pills para tool/approval/uncertain/receipt somente quando o dado existir na mensagem.
- `chatPresenceModel` deve ser puro e testável; estados: idle/listening/thinking/working/waiting/error/done, com `verified` obrigatório para done.
- Não alterar o protocolo de envio, o stream, o journal ou a ordem de mensagens. A edição em `shell-conversation.jsx` deve ser mínima e cercada por comentários `// Coucou visual layer`.

### Frente 4 — `shell-hub.jsx` / `shell-drop-overlay.jsx`

Exportar:
```js
export function hubSections({ home, dots, events, project, models })
export function activityRecap(events, { now, days })
export function ShellHub({ open, onClose, home, dots, events, project, models, onEditDot, onNavigate, onTools })
export function ShellDropOverlay({ active, files, onClose })
```

Requisitos:
- Hub em modal largo com navegação lateral: **Visão geral**, **Companions**, **Atividade**, **Integrações**, **Sobre**. Visual Coucou hub, dados reais somente leitura.
- “Visão geral”: run state, Dots ativos, aprovações pendentes, capacidades; nunca inventar conclusão.
- “Companions”: grade com os 17 `DOT_MASCOTS`, preview grande do selecionado, nome/descrição e botão “Editar Dot” (via callback).
- “Atividade”: recap dos últimos 7 dias a partir de `events` + recibos, agrupado por dia, com contagem de eventos e estados; rotular como “observação”, não produtividade oficial.
- “Integrações”: pills read-only para modelos/provedores/capacidades já presentes; sem capturar chaves.
- “Sobre”: versão, nota de que o visual foi inspirado no Coucou (MIT) e que os personagens são originais do SENTRA.
- Drop overlay: aparece só durante drag de arquivos, mostra o Dot ativo e “Solte para anexar”; não intercepta clique; `pointer-events:none` fora do cartão; fecha ao sair.
- Nenhuma chamada de escrita. O hub só lê props e chama callbacks.

## 5. Integração reservada ao coordenador

- `shell-app.jsx`: montar `<ShellIsland>` e `<ShellHub>`, toggle “Ilha do Oxta”, callbacks de navegação, `<ShellDropOverlay>` no host da conversa.
- `shell-conversation.jsx`: o subagente B integra diretamente; o coordenador revisa e ajusta.
- `shell-approval-notifications.jsx`: o subagente A integra diretamente; o coordenador valida no shell.
- `main.jsx`: só o coordenador importa CSS global, se necessário.
- `scripts/commander/orca_build_manifest.py`: só o coordenador adiciona os novos arquivos.

## 6. Testes e aceitação

- Cada frente adiciona um teste Node puro em `sentra_canvas/desktop_ui/test/` e roda:
  `node --test test/<arquivo>.test.mjs`
- A frente 2/3/4 não roda build global nem `npm install`.
- Aceitação visual: `pebble-preview` ou harness local, tema dark e light, 1280×900 e 660×720, sem erros de console, sem overflow horizontal, `prefers-reduced-motion` sem loops.
- `node --test test/` completo só no final, pelo coordenador.

## 7. Atribuição

O visual é inspirado no Coucou (Louis-CFM/coucou, MIT). Código adaptado deve manter um comentário curto de origem no topo do arquivo. Não copiar `LICENSE-ASSETS.md` do Coucou, personagens, nomes, ícones, sons ou animações do Mochi.


## 8. Fechamento da revisão

A implementação entregue habilita a ilha por padrão, com opção persistida de
ocultar; essa decisão substitui o termo opt-in da especificação inicial. A revisão
final corrigiu consulta de aprovação que ainda reenviava a resposta, adicionou
seletores duráveis, impediu falsa conclusão por recibo de entrega e corrigiu erros
de alvo de evento. Consulte [o relatório final](COUCOU_INTEGRATION_REVIEW_2026-10-22.md)
para evidências e pendências. A implementação em fonte está consolidada; nova
homologação visual e bundle correspondente seguem pendentes, sem substituir a
instalação principal.
