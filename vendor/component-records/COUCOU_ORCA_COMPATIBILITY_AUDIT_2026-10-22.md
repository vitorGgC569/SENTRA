# Coucou → SENTRA: auditoria de aproveitamento sem colisão com ORCA

**Data:** 22/10/2026
**Classificação:** análise estática e ensaio limitado; **não é implementação, merge ou homologação**.
**Decisão:** absorver seletivamente os adaptadores de agentes, regras de instrumentação, UX de decisões e apresentação compacta; manter o SENTRA/ORCA como autoridades para operações, transporte, dispositivos e recibos.

## 1. Revisões e escopo realmente conferidos

- **Coucou:** Louis-CFM/coucou, main, revisão **1e5180921c1326fc72e41d313e3e2855e9c10162**, commit de 20/10/2026. Repositório clonado em **SENTRA/.tmp/coucou-source-audit**, exclusivamente para leitura e testes. Não foi localizado clone do Coucou nas pastas comuns consultadas; isso não demonstra que nunca existiu outro em algum local não examinado.
- **SENTRA:** checkout **5d5b40f** mais alterações locais **não commitadas**, preservadas. Não modificar/reverter esses arquivos para absorver Coucou.
- **ORCA:** pin integrado **70b2197c...**, checkout de investigação atualizado **fd8b2dc3...**, conforme docs/ORCA_SENTRA_STATUS_2026-10-21.md. Plano vigente em docs/ORCA_IMPLEMENTATION_TRACKER.md, com pendências macro abertas.
- Inspecionados: docs/AGENTS.md, README, LICENSE-ASSETS.md, docs/RELAY_LINK.md, android/RELAY_THREAT_CHECK.md, módulo de hooks Rust/Windows, normalização, formatos de resposta, servidor de pipe, instalação segura dos hooks, estados e diffs TypeScript, phone-link, aprovação Android, política de update, README e documentação ORCA no SENTRA.
- **Evidência local:** 19 testes Node de windows/tests/diff.test.mjs passaram. windows/tests/hooks.test.mjs e windows/tests/update.test.mjs **não executaram seus casos** por ausência de @tauri-apps/api no clone (dependências não instaladas). Cargo não instalado; nenhuma suíte Rust/Kotlin compilada ou rodada. Nenhum aparelho físico/relay de produção ensaiado. Logs: SENTRA/.tmp/coucou-audit-node-tests.txt.
- **Licença:** código Coucou sob MIT; Android/phone-link creditado a Rhytam Biswas (MIT). **Mochi, nome Coucou, ícones, áudios, expressões e animações do personagem protegidos separadamente** em LICENSE-ASSETS.md. O SENTRA usa personagens próprios, incluindo Oxta, e não pode reutilizar esses assets em uma distribuição sem autorização escrita.

## 2. Invariantes SENTRA/ORCA (não negociáveis)

1. O **SENTRA Core** é a única fonte autoritativa para Dot, WorkItem, Grant, intenção, efeito e recibo. Hook de CLI é observação, nunca credencial nem autorização.
2. Comunicação mobile, identidade estável do host, LAN/QR e E2EE continuam no **gateway derivado do ORCA**. Não criar um segundo servidor de aparelhos nem instalar o relay Coucou em paralelo por padrão.
3. ConPTY/daemon, histórico PTY, replay ANSI/TUI, backpressure e input journal continuam na frente **ORCA PTY**, incluindo os itens ainda não homologados.
4. Tela inicial, navegação e conversas pertencem ao SENTRA; workspace de abas/splits/arquivos pertence apenas ao Canvas interno, conforme o plano ORCA. Não substituir o shell por Tauri, island ou notch.
5. Estado 'Stop', saída de CLI, notificação e retorno HTTP **não provam** conclusão. Sucesso exige recibos/evidência verificada, sem replay de operação incerta.
6. O plugin de observação não altera settings de CLIs, PATH, integradores, instalações, modelos ou permissões sem prévia/diff/consentimento explícito; deve ser reversível.
7. Os companions do SENTRA/Oxta são originais. Uma versão flutuante é opt-in, sem fundos, cards ou nova navegação obrigatória.
8. Não publicar, distribuir, reiniciar a instalação principal ou alterar worktrees/Grants/sessões com base neste relatório.

## 3. Matriz integral de aproveitamentos

**Legenda:** P0 = testar após assegurar o P0 ORCA em andamento; P1 = após contratos de eventos/Grants estabilizados; P2 = opcional. **Tipo:** C = copiar código MIT com adaptações/testes e atribuição; A = adaptar abordagem/API; L = aprender padrão/UX, implementar nativamente. Nenhum 'C' autoriza copiar branding/assets.

| # | Recurso Coucou / origem | Tipo | Prioridade | Ação no SENTRA | Colisão evitada / condição |
|---|---|---|---|---|---|
| 01 | Normalização multi-CLI: windows/hook/src/normalize.rs | C/A | P0 | Adaptadores externos Gemini/Codex/Cursor/Copilot/Muse/Antigravity, eventos canônicos e aliases de campos | Publicar como observação; NÃO substituir evento assinado central ORCA |
| 02 | Adaptadores OpenCode/Amp/Hermes: windows/src-tauri/src/agents.rs (templates) | A | P0 | Sidecar de observação específico de OpenCode e workers externos | Nunca instalar vários plugins que interceptem o mesmo evento sem reconciliação |
| 03 | Exe leve coucou-hook: windows/hook/src/main.rs | C/A | P0 | Hook do SENTRA rápido, com orçamento temporal, truncamento e saída neutra | CLI não pode ficar bloqueado por indisponibilidade do SENTRA |
| 04 | Named pipe e identidade: windows/hook/src/win.rs, windows/src-tauri/src/pipe.rs | A | P0 | Canal observador local por usuário + validação do processo servidor | Não abrir segundo broker autoritativo; exigir ACL e provenance/instância além de mesmo SID |
| 05 | Conexão instalada/visível: windows/src-tauri/src/agent_hooks.rs | A | P1 | Diagnóstico 'CLI observado' vs 'CLI disponível' vs 'CLI executável' | Não afirmar que ter hook habilitado equivale a executar ferramenta |
| 06 | Instalação reversível de hooks: windows/src-tauri/src/config_file.rs e hooks.rs | A/C | P0 | Preview do diff, cópia datada, leitura estrita, CAS, merge e remoção exata | Utilizar revisão forte/hash SHA-256 e lock; FNV-1a de Coucou não basta para a autoridade SENTRA |
| 07 | Compatibilidade de comandos/quoting: windows/src-tauri/src/agents.rs | C/A | P0 | Instalar observadores em PowerShell/cmd/Git Bash sem quebrar aspas e paths | Descoberta no ambiente de execução real, nunca alterar PATH global às cegas |
| 08 | Contrato de respostas por CLI: windows/hook/src/reply.rs | A/C | P0 | Resposta correta ao protocolo: 'ask'/ausência de decisão em timeout; never auto-allow | SENTRA Grants é o gate; somente aprovação humana/derivada com escopo válido pode emitir allow |
| 09 | ACK visual antes de segurar o hook: windows/src-tauri/src/pipe.rs | A | P0 | Confirmar que card de permissão está realmente visível antes de aguardar | Evitar que agente espere por UI oculta/quebrada; fallback terminal seguro |
| 10 | Validação de respostas de perguntas: windows/hook/src/reply.rs | C/A | P1 | Check estrito texto/opções/multiselect antes de encaminhar resposta | Perguntas não são Grants nem execução concluída |
| 11 | Estados de sessão compactos: windows/src/core/state.ts, windows/src/island/hooks.ts | L/A | P0 | Mapear 'pensando/working/aguardando erro' para companhia Oxta sem dados técnicos excessivos | Stop não vira WorkItem SUCCEEDED; distingui-lo de fin da observação |
| 12 | Ticker de passos e última ação: windows/src/views/ticker.ts | L/A | P1 | Linha contextual curta em conversa/companion, detalhes expansíveis | Usar eventos/recibos SENTRA; não criar timeline independente |
| 13 | Aprovação compacta do island: windows/src/views/views.ts e phone-link | L | P1 | Card de decisão com ferramenta, ação, duração, origem e destino; fechar após recibo | UI adicional, mesma aprovação central; não criar permission store duplicado |
| 14 | Limites de diffs: windows/src/core/diff.ts | C/A | P1 | Preview limitado por bytes/linhas/células, fallback '+N/-M' | Diff calculado de argumentos é previsto/observado, NÃO comprova escrita no Git/worktree |
| 15 | Histórico curto de arquivo por sessão: windows/src/core/state.ts | L/A | P1 | Timeline de artefatos do Dot e links para editor com versão | ORCA mantém editor CAS, revisões e watchers autoritativos |
| 16 | Voltar à janela original: windows/src-tauri/src/session_window.rs | A/C | P1 | 'Ir ao terminal' para subprocesso externo e foco do split certo | Sessões PTY internas usam IDs da autoridade; evitar ativar janela de outra conta/VM |
| 17 | Notificações no desktop: island/desktop, tray e shortcuts | L/A | P1 | Indicador nativo discreto de esperando/aprovado/concluído | Nenhuma segunda shell persistentemente visível por padrão |
| 18 | Widget/overlay Android, android/app/... | L | P1 | Notificações e acompanhamento read-only, opt-in, com economia de bateria | App SENTRA Expo/RN existente continua; não substituir por segundo app Kotlin |
| 19 | Biometria Android: android/.../app/BiometricGate.kt | A | P1 | Gate de autenticação local em qualquer 'Allow' remoto; negar possível sem biometria | A biometria não cria Grant: host revalida identidade, escopo, intenção e expiração |
| 20 | Livro de aprovações: android/.../link/ApprovalBook.kt | A/C | P1 | TTL monotônico de chegada, claim-at-most-once, mesma fingerprint pós-reconexão | Unificar com diário central de intenções e recuperação ORCA |
| 21 | Quotas de dados móveis: phone_link/hub.rs | A | P1 | Budget de passos, diffs, linhas, arquivo e capacidade; timeline paginada | ORCA xterm/checkpoints/backpressure não substituídos |
| 22 | Limites pré-auth: phone_link/admission.rs | A/C | P1 | Pool limitado, quota IP, prazos curtos para clientes sem handshake | Adicionar ao gateway ORCA quando pertinente; revisar NAT/CGNAT para não excluir aparelho legítimo |
| 23 | Emparelhamento/PKI: phone_link/pairing.rs | L | P2 | Reexaminar pinned cert/rotação e falha de keystore | ORCA já possui identidade LAN durável e QR: não transplantar |
| 24 | Relay WebSocket E2EE: phone_link/relay_crypto.rs, relay_client.rs, android/relay | L/A | P1 condicional | Threat model, teste vetorial multi-plataforma, mitigação DoS, forward-only | Relay opcional **do ORCA/SENTRA**; não criar segundo conjunto de chaves/sessões |
| 25 | Pareamento relay + testes vetoriais: docs/RELAY_LINK.md, android/RELAY_THREAT_CHECK.md | L | P1 condicional | Testes de replay/counter, PFS, downtime, metadata e dispositivos físicos | Coucou v1 NÃO oferece forward secrecy; Cloudflare real não homologado |
| 26 | Atualizador consentido: windows/src-tauri/src/update.rs | L/A | P1 | Notificação discreta, download hash-verificado, validação de host/versão, snooze | ORCA/SENTRA já têm update/rollback: não trazer updater paralelo |
| 27 | Demo com estado simulado sem persistência: README | L/A | P1 | Modo demonstração para onboarding e QA com estado descartável explícito | Nunca expor 'simulado' como recibo real |
| 28 | Serviços/pills GitHub/GitLab/Gitea/Vercel/n8n/etc: integrations.rs | A | P2 | Conectores permissionados e cards compactos somente quando úteis | Plugins/Grants existentes são a autoridade; não replicar chave/API por serviço |
| 29 | Uso/cota de modelos: statusline.rs, codex_plan.rs e widgets | A | P2 | Indicadores de uso por provedor quando o dado for confiável | Não capturar chaves/tokens ou anunciar uso estimado como contador oficial |
| 30 | Shortcuts e foco: core/shortcuts.ts e Windows island | L | P2 | Atalhos unificados para recuperar Dot/solicitação/contexto | Respeitar atalhos de terminal/editor e seleção de split ORCA |
| 31 | Recap semanal e insights: recap/ | L | P2 | Resumo de atividade baseado em recibos verificáveis | Não contar 'eventos de hook' como tarefas concluídas |
| 32 | Idiomas e acessibilidade: i18n/ e widgets | L/A | P2 | PT-BR acessível, alto contraste, teclado, reduced motion | Identidade visual atual permanece |
| 33 | Voice/Flow/Notetaker: flow/, speech/, voice/ | L | P2 | Explorar ditado offline e entrada contextual após finalizar fluxos principais | Não exigir áudio, daemon ou permissões amplas na instalação base |
| 34 | CloudKit, Live Activity e Siri: NotchBuddy/Sources/Phone e Widgets | L | P2/iOS | Ideias para notificações iPhone e atalhos; adaptá-las ao app SENTRA | Não exigir Mac/iCloud nem trocar o Expo/RN |
| 35 | Músicas, guarda-roupa Mochi, animações, branding | NÃO copiar | Fora | Preservar os mascotes originais do SENTRA/Oxta | LICENSE-ASSETS.md veda uso redistribuído sem autorização |

## 4. Sobreposição: quem deve ser dono de cada área

| Área | ORCA/SENTRA hoje | Coucou acrescenta | Decisão |
|---|---|---|---|
| Dots/WorkItems/Grants | Motor de coordenação e autorizador no host | UI de aprovação e eventos de agentes | **SENTRA** define decisão; Coucou fornece apenas adaptadores e UX |
| CLI/ACP/execução | SENTRA CLI, Codex, OpenCode/ACP em desenvolvimento | Hooks de observação de CLIs externos | **Combinar por adaptador**, sem dois executores para a mesma sessão |
| PTY/ANSI/TUI | ORCA histórico, checkpoints, fila, cursors, consumidores | 'Ir ao terminal' e resumo de passos | **Manter ORCA**, reaproveitar foco/navegação |
| Editor/diff/revisão | ORCA editor CAS e worktree por Dot | Diff leve de hook / ticker | Usar como **prévia não verificada**, vincular à versão real |
| Desktop e layout | SENTRA shell e Canvas ORCA, layout host/simples-avançado | Island/tray compactos | Opcional, sem segundo Canvas |
| Mobile LAN | Gateway ORCA E2EE, identidade protegida, QR, terminal móvel | Biometria/limites/feedback/proteção DoS | **Adicionar capacidades no app/servidor ORCA existente** |
| Relay remoto | Pendente em ORCA/SENTRA | Protocolo Coucou relay v1 | Estudar vetores, NÃO transplantar protocolo inteiro |
| Updates | Plano SENTRA com staging/rollback/ConPTY | Consentimento, aviso discreto e verificação SHA | **Uma só máquina de update** |
| Mobile iOS | RN/Expo do SENTRA ainda sem homologação física | CloudKit/Dynamic Island Swift | Somente inspiração; capacidades futuras condicionadas a iOS |
| Navegador/VM | ORCA + SENTRA com posse/Grants/WorkItems | Coucou não implementa substituto comparável | Não migrar nem misturar |

## 5. Decisões arquiteturais recomendadas

### 5.1 SENTRA Agent Observation Bridge (novo adaptador, sem nova autoridade)

Extensão sugerida **fora** do broker de execução: adapters/coucou-inspired por CLI, output apenas de **observação**. Evento de domínio para consumo pelo host:

- versão e fonte do adaptador;
- identidade verificada do processo/origem/conta (não aceitar somente um campo session_id arbitrário);
- vínculo autorizado projeto → Space → Dot → conversa → WorkItem, quando conhecido;
- id de evento/ordem da fonte e clock de recepção; deduplicação e rejeição de eventos tardios;
- tipo canônico (SessionStart, PromptSubmit, ToolBefore/After, ApprovalObserved, SessionStop, SessionError);
- payload mínimo, limite de bytes, REDAÇÃO de comandos/prompts sensíveis por padrão;
- marca explícita **observed_only**, nunca **verified_success**.

A regra no core deve ser: **hook Stop → sessão observada terminou**, nunca WorkItem SUCCEEDED; somente WorkItem/recibo confirmado gera sucesso. Hook também não altera Grants, não inicia processo, não reprova/permite comandos por conta própria.

### 5.2 Plugins de CLI externos

Criar uma interface de observador com provider/dialeto, capabilities reais (observe, ask_question, permission_transport, send_input), detect/preview/install/uninstall/status. Começar com OpenCode, Codex e um CLI de hooks documentados; avaliar Muse/Copilot/Gemini/Antigravity por dialeto. Diferenciar observação de aprovação externa. O Coucou reconhece diversas ferramentas, mas **não tem aprovação funcional em todas**.

Protocolo de instalação: opt-in por CLI → detectar caminho e versão no usuário correto → prévia completa → backup e hash forte (SHA-256/CAS) → merge idempotente → verificação de integridade → rollback apenas dos próprios registros → testes com configuração concorrente. Nenhuma modificação automática em settings globais ou instalação silenciosa.

### 5.3 Aprovações e perguntas

Solicitação externa observada NÃO ganha um Grant novo. Adaptador envia proposta ao SENTRA; serviço central valida política/especificidade/expiração/escopo e correlaciona pedido exato. UI da conversa/companion só mostra decisão quando pronta. Se a UI não conseguir mostrar, devolver 'ask' ou controle ao terminal do CLI; **jamais permitir silenciosamente**. Quando a operação está UNCERTAIN, consultar seu recibo; não repetir. 'Always Allow' só após regra durável explícita permitida pelo SENTRA. Respostas de perguntas exigem opções/texto exatos e TTL, sem inferências do modelo.

### 5.4 Mobile e relay

Aproveitar principalmente o padrão de **fingerprint + TTL + decide-once + autenticação local por Allow** do Android Coucou. O app SENDRA Expo/RN envia decisão via gateway ORCA e o host revalida o pedido. Solicitações longas/ilegíveis ou alteradas devem exigir revisão integral na interface apropriada. Os widgets são **read-only**.

Se o ORCA oferecer relay opcional: usar threat model Coucou como checklist para transporte **SENTRA**, com dispositivos físicos, PFS ou justificativa formal, e distinção entre confidencialidade, integridade e disponibilidade. Sem QR paralelo, K duplicada, room paralelo ou Cloudflare imposto aos usuários.

### 5.5 UX do companion Oxta

Personagem de Home Oxta é branding, não status do primeiro Dot. Nas conversas ou barra de tarefas, companion representa SOMENTE o Dot associado, com prioridade para 'aguardando aprovação', 'execução real', 'incerto', 'falha', 'comprovadamente concluído'. Nada de 17 personagens montados com animação contínua na Home; use pausa invisível e reduced motion. Sem cards, fundos ou descrições adicionais no avatar em si.

## 6. Riscos técnicos observados no Coucou (não copiar cegamente)

1. **FNV-1a nos planos de configuração:** windows/src-tauri/src/config_file.rs usa fingerprint simples. Serve para alterações acidentais, não como garantia criptográfica contra colisão/adversário. SENTRA já dispõe de hashes e revisão condicional mais robustos.
2. **Mesmo usuário não é a mesma autorização:** windows/hook/src/win.rs valida SID do servidor do pipe; ótimo isolamento entre usuários, mas outra aplicação do mesmo usuário pode tentar se passar pelo observador. Exigir identidade de runtime/instalação, ACL restrita e minimizar payload.
3. **Hooks podem carregar dados sensíveis:** windows/hook/src/main.rs remove tool_response/tool_output/transcript_path e limita campos, mas mantém trechos de tool_input para diff. Default no SENTRA: metadata/redaction, opt-in explícito de conteúdo, sem telemetria e sem vazamento mobile.
4. **Parada não equivale a conclusão:** mapeamento OpenCode session.idle → Stop e de outros CLIs Stop → finished serve ao island, não ao protocolo verificado do SENTRA.
5. **Diferença entre agentes:** windows/hook/src/reply.rs declara aprovações para Claude Code, Codex, Copilot, Muse; Gemini/Antigravity/OpenCode/Hermes têm limites próprios. docs/AGENTS.md mistura trechos antigos ('approval external not implemented') e exemplos novos — prevalecer código e testes da revisão fixada.
6. **Deadline de decisão:** coucou-hook usa 110 s e espera UI ACK (até 800 ms); admirável para não travar o CLI, mas SENTRA exige expiração e confirmação correlacionadas ao pedido real, mesmo se browser fechar e reabrir.
7. **Criptografia relay v1:** AES-256-GCM/HKDF e anti-replay têm vetores, mas docs/android/RELAY_THREAT_CHECK.md assume **sem forward secrecy**, metadados visíveis e testes Cloudflare/aparelhos físicos pendentes.
8. **Mobile vínculo fraco se transplantado literalmente:** phone_link/hub.rs conhece sessão/approval fingerprint, mas não o escopo completo SENTRA Grant/WorkItem/dot/owner. Não deixar o telefone virar fonte de autoridade.
9. **Cópia da UI/brand:** licença MIT do código NÃO engloba Mochi, assets, sons nem identidade visual; manter Oxta e personagem próprios.
10. **Custos de integração:** Tauri/Rust/Swift/Kotlin e uma segunda base mobile criariam pipeline e governança paralelos. Adaptar funções puras (ou reimplementar) onde o SENTRA já usa Electron/Python/React/Expo.

## 7. Plano sem choque com os gates ORCA

| Etapa | Dependência ORCA/SENTRA | Entrega Coucou | Gate de aceitação |
|---|---|---|---|
| 0. Congelar evidência | Nenhuma | Pin Coucou, inventário MIT e LICENSE-ASSETS, testes atuais, matriz de colisão | Checkout isolado imutável, sem tocar main nem hooks reais |
| 1. Reforçar P0 existente | Terminal input/recibos, eventos assinados em progresso | Testar normalizadores como biblioteca pura e especificar contrato observado | Zero alteração da execução existente, contraexemplos de Stop falso e sessão forjada |
| 2. Instrumentar CLIs opt-in | Identidade e escopo central de conversa/WorkItem | Adaptadores OpenCode, Codex, terceiro CLI; gestão de instalação | Hooks originais preservados, diff+backup+rollback, ausência de bloqueio ao desligar SENTRA |
| 3. UX compacta | Grants/WorkItems e interface em conversa existentes | Companion/tray com estados e comandos para voltar ao trabalho | Um estado verdadeiramente único, nenhuma falsa conclusão e sem painéis adicionais |
| 4. Aprovação externa segura | Reconciliação de pedidos/Grants testada | ACK UI, fallback terminal, validação de perguntas e decisão | Nenhum 'allow' sem decisão válida; timeout, duplicação e perda de confirmação ensaiados |
| 5. Mobile | Gateway ORCA e aparelhos físicos disponíveis | Biometria por aprovação, widgets, quotas e proteções DoS | Android+iPhone físicos, suspensão/revogar/trocar IP, dono/escopo e sem reenvio incerto |
| 6. Remoto opcional | Relay ORCA E2EE e contrato de dispositivo | Threat-model/vetores anti-replay Coucou, telemetry-off | Reutilizar pareamento único, testes reais e publicação gradual |
| 7. Extras | Instalação e update homologados | Demos, serviço GitLab/Gitea, cota, relatórios, ditado | Sem perda de sessão; consentimento e rollback; sem distração dos P0 |

### Sequência concreta recomendada

**Primeiro:** terminar os gates P0 ORCA já previstos (input journal, consumidores lentos/PTY, eventos, estados/recibos). Em paralelo somente testes puros de normalização Coucou (sem hooks instalados).

**Depois:** observação de OpenCode/Codex e card compacto, usando eventos de leitura no Core. Estes são os maiores retornos por risco baixo.

**Só depois:** instrumentação de permissões externas, biometria do móvel e eventual relay opcional. Não aceitar um protótipo de aprovação que ignore o autoritativo Grants.

## 8. Testes de regressão a escrever ANTES de integrar

- Injeção de Stop/SessionEnd falsos e eventos fora de ordem não encerram WorkItem.
- ID externo reutilizado não atravessa proprietário/projeto/Space/Dot, nem uma worktree isolada.
- Adapter offline/pipe ausente/timeout não bloqueia CLI nem autoriza.
- CLI com settings.json malformado: recusar sem recriar/substituir; backup exige sucesso; configuração concorrente falha antes da escrita.
- Um hook é instalado uma vez; uninstall remove apenas a própria entrada, sem interferir em hooks de outros apps.
- Repetição de PermissionRequest, ACK perdido, Android reconectado e double tap geram **uma única** decisão/evidência.
- Uma decisão móvel com fingerprint, comando, ferramenta, versão, dono ou escopo diferentes é rejeitada.
- Biometria cancelada nunca emite Allow. Texto truncado e ação de alto risco devem exigir revisão integral.
- Eventos com segredos, prompts, outputs longos e paths privados são redigidos ou recusados segundo a política.
- Long-running TUI em 3+ CLIs externos não degrada ConPTY/ORCA nem introduz loop de renderização dos companions.
- Updater e notificações não interrompem terminal, sessão remota, Grant ou instalação parcial.
- Testes E2E positivos: usuário → Dot → WorkItem → CLI observado → decisão permitida → resultado/recibo verificado → mobile e companion atualizados (mesmos IDs).

## 9. Evidência por arquivo para futuras revisões

- Normalização: windows/hook/src/normalize.rs.
- Formatos por CLI e perguntas: windows/hook/src/reply.rs.
- Relay local fail-safe: windows/hook/src/main.rs; windows/hook/src/win.rs; windows/src-tauri/src/pipe.rs.
- Instalação: windows/src-tauri/src/agents.rs, hooks.rs, config_file.rs.
- Estado/ticker/diffs: windows/src/core/state.ts, diff.ts; windows/src/island/hooks.ts; windows/src/views/ticker.ts.
- Identificação de terminal: windows/src-tauri/src/session_window.rs.
- Mobile: windows/src-tauri/src/phone_link/admission.rs, hub.rs, pairing.rs, relay_crypto.rs; android/app/src/main/kotlin/com/coucou/android/link/ApprovalBook.kt; android/app/src/main/kotlin/com/coucou/android/app/BiometricGate.kt.
- Relay threat model: docs/RELAY_LINK.md, android/RELAY_THREAT_CHECK.md.
- Update: windows/src-tauri/src/update.rs.
- Licensing: LICENSE, LICENSE-ASSETS.md, android/LICENSE.
- Pendências vigentes ORCA: SENTRA/docs/ORCA_IMPLEMENTATION_TRACKER.md, ORCA_SENTRA_STATUS_2026-10-21.md, ORCA_SENTRA_REAUDIT_2026-10-21.md.

## 10. Decisão final

**Aprovar o Coucou como fonte de adaptadores/observabilidade e de padrões de interface segura; não adotá-lo como motor de execução, API, transporte primário ou mascote.**

**Melhor investimento próximo:** normalização multicliente + instalação opt-in reversível + mini-indicador de atividade e aprovação com o Oxta. Tudo subordinado ao mesmo backend SENTRA/ORCA e aos seus testes. O restante deve virar backlog condicionado à conclusão dos critérios macro ORCA — especialmente mobile físico, relay E2EE opcional e distribuição homologada.

**Status de implementação desta auditoria:** zero alteração em código de produção. Foi criado apenas clone isolado de Coucou, logs do teste de diff e este documento de análise; checkout compartilhado e as mudanças não commitadas permanecem preservados.
