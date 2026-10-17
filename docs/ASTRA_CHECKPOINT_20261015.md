# SENTRA — checkpoint do repositório em 15/10/2026

Este documento registra o checkout completo no momento da pausa solicitada pelo usuário, incluindo alterações locais anteriores à última frente. O commit é um checkpoint de desenvolvimento, não um release homologado. Naquele momento, os três subagentes foram interrompidos e o objetivo integral ficou pausado. Este relatório foi completado com as contagens históricas em 17/10/2026.

## Contagem do checkpoint

- Checkpoint medido: `42870dcd50a2476b2f3b52b3c36bd27d86f9496c`.
- Base anterior: `0c08d06`.
- Arquivos alterados no checkpoint: 592.
- Linhas adicionadas: 70676.
- Linhas removidas: 9107.
- Arquivos binários sem contagem de linhas: 3.
- Inventário por arquivo: [ASTRA_CHECKPOINT_20261015.tsv](ASTRA_CHECKPOINT_20261015.tsv).

As contagens são o diff Git de `0c08d06` para `42870dc`, incluindo testes, documentação e assets gerados versionados. Não equivalem a linhas escritas exclusivamente por um agente nem ao tamanho total do projeto. O TSV lista os 592 arquivos desse diff histórico; este relatório e o TSV só foram adicionados posteriormente.

## Alterações por área

| Área | Arquivos | Adições | Remoções | Binários |
|---|---:|---:|---:|---:|
| (raiz) | 5 | 193 | 136 | 0 |
| browser | 4 | 1128 | 1120 | 0 |
| deploy | 1 | 62 | 62 | 0 |
| docs | 51 | 5928 | 301 | 0 |
| edge_extension | 7 | 523 | 32 | 0 |
| installer | 6 | 632 | 139 | 0 |
| integrations | 1 | 48 | 0 | 0 |
| local_model | 2 | 111 | 2 | 0 |
| memory | 3 | 346 | 12 | 0 |
| native_bridge | 4 | 173 | 19 | 0 |
| orchestrator | 18 | 2933 | 49 | 0 |
| repository | 2 | 135 | 135 | 0 |
| scripts | 35 | 2902 | 465 | 0 |
| sentra_canvas | 161 | 12744 | 627 | 2 |
| sentra_cli | 11 | 515 | 101 | 0 |
| sentra_code_mode | 16 | 1062 | 33 | 0 |
| sentra_collab | 3 | 350 | 2 | 0 |
| sentra_connectors | 7 | 985 | 0 | 0 |
| sentra_core | 3 | 73 | 5 | 0 |
| sentra_electron | 5 | 186 | 29 | 1 |
| sentra_executors | 22 | 3881 | 112 | 0 |
| sentra_federation | 10 | 2713 | 0 | 0 |
| sentra_marketplace | 10 | 1323 | 0 | 0 |
| sentra_mcp | 18 | 3023 | 2902 | 0 |
| sentra_model_gateway | 1 | 124 | 8 | 0 |
| sentra_quality | 6 | 1555 | 1 | 0 |
| sentra_remote | 18 | 1316 | 459 | 0 |
| sentra_runtime | 5 | 707 | 68 | 0 |
| skills | 3 | 102 | 0 | 0 |
| tests | 154 | 24903 | 2288 | 0 |

## Trabalho registrado

1. **Desktop e navegação:** abertura canônica de conversas, paginação, proteção contra respostas atrasadas após troca de projeto e separação entre confirmação da operação e entrada efetiva no chat. Markdown, tabelas, código copiável, busca, retorno ao trecho recente, virtualização, mascotes com fallback e painel de computador redimensionável. Build de interface materializado com manifesto e hashes.
2. **Cache:** LRU somente em RAM, oito conversas, 4 MiB, cinco minutos e últimas 50 mensagens. Projeção visual sem tokens, permissões, recibos ou autoridade; leitura recente em um snapshot e paginação anterior recuperável. Invalidação descarta respostas anteriores à perda de acesso, inclusive originais completos e exportações.
3. **Streaming:** journal protegido, persistência anterior à publicação, feed multiplexado, sequência/cursor, retomada e deduplicação. Estado de espera, confirmação, interrupção e reconexão preserva conteúdo sem transformar prévia em sucesso ou autorizar reenvio. Checkpoints de turno e memória protegida preservam rascunhos.
4. **Conteúdo longo:** blocos imutáveis reutilizados por hash, referências paginadas, integridade por página e corpo, retenção e orçamento explícito de 8 MB. Leitor completo da prévia em texto simples, cancelamento, timeout, proteção contra seleção atrasada e virtualização. Texto legítimo como `[[wiki]]` é preservado; argumentos de diretivas estruturadas ficam ocultos.
5. **Execução e recuperação:** reserva de operação evita trabalhadores duplicados bloqueados pela mesma conversa. Teste com dez TaskProcess/Windows Jobs reais e CLI sintética verificou dez produtores, vinte leitores, crashes, JSON incompleto, preservação de drafts/referências e ausência de relançamento após restart.
6. **Extensão e integração Web:** persistência de jobs, identidade, outbox e cursores; retomada de worker e navegador em observação. QA de encerramento normal e crash completo do Chromium temporário. Correções de transporte, projeção de assets e identidade versionada da extensão. Diagnóstico da recuperação do gateway preservado na documentação.
7. **Federation:** identidade, pareamento, mTLS, frames assinados, journal e tarefas tipadas ligadas ao executor real/Control Plane. Grants, WorkItems, Operations, artefatos, revisão e reconciliação sem replay. Revalidação após última etapa, publicação e antes do TLS; tratamento de revogação tardia, duplicatas e recibo de revisão perdido. QA com dois processos independentes.
8. **VM e controle do Dot:** execução diferenciada entre host/guest, GuestControl, framebuffer, input com posse/fencing, bootstrap e diagnóstico. Identidade exata do VDI, candidato e inscrição de armazenamento com proprietário autenticado, CAS e ativação por recibo canônico. Validadores de isolamento/recursos Windows; base compartilhada e clones continuam proposta.
9. **Intervenção Windows real:** disco e backup preservados; um Shift+F10 virtual, uma pausa/retomada autorizada e capturas canônicas. Setup avançou de 72% para 73% e o console WinPE abriu. `tasklist` foi digitado e Enter enviado uma vez, sem saída confirmada. Posse do teclado devolvida. Nenhum reset ou nova inscrição real do disco.
10. **Semântica das provas:** captura comprova framebuffer, sem declarar desktop ou Windows instalado. Compatibilidade de recibos antigos normaliza a projeção ao modelo sem reescrever o histórico protegido.
11. **Runtime e distribuição:** pins de Wasmtime e componentes, build de QuickJS/WASI, bridge HCS, RustDesk nativo/Flutter, manifestos, hashes, SBOM/fontes e proveniência. Seleção por pins incorporados, validação de bytes e suporte a caminhos longos do Windows. Probe empacotado real validou seleção sem variáveis do checkout e recusou adulteração. Setup integral ainda pendente.
12. **Plataforma e frentes adicionais:** alterações locais de orquestração, budgets, memória por Dot, colaboração/equipes, marketplace, conectores, superfície de modelo visual, instalação e diagnóstico de qualidade estão preservadas. Presença no checkout não comprova integração, autenticação real ou homologação de cada capacidade.

## Evidências e limites

- Interface: 145 testes JavaScript, 14 cenários do leitor longo e 12 cenários de abertura/chat aprovados nas execuções registradas.
- Leitor longo: 5.439.505 caracteres, 84 páginas, até 11 páginas no DOM nas amostras; cancelamento/timeout sem prompt ou retry.
- Cadastro de disco/VM: 76 testes; captura/CLI/persistência: 33 testes. Os conjuntos se sobrepõem a outras suítes e não devem ser somados como total global.
- Streaming: ensaio controlado anterior mediu p95 de 248,85 ms; a recuperação inicial de corpos longos para vinte leitores chegou a 14.875 ms. A proposta para reduzir esse custo ainda não foi implementada.
- Federation: regressões dirigidas e QA entre dois processos; a última continuação de recuperação de revisão registrou 40 testes aprovados.
- Runtime: componentes e probe empacotados não comprovam instalação limpa, assinatura, atualização, rollback ou controle remoto RustDesk.
- Os testes com produtores sintéticos não equivalem a dez inferências reais ou vinte identidades de equipe. Os relatórios temporários continuam locais; as descrições e harnesses ficam versionados.

## Pendências preservadas

1. Windows concluído, desktop persistente, Guest Additions, GuestControl e comando com stdout/recibos no Canvas.
2. Consolidar/aplicar as fontes recentes ao runtime efetivamente usado pela janela e repetir a validação instalada.
3. Instalador integral com todos os executáveis no mesmo snapshot, componentes/proveniência, assinatura, instalação limpa, atualização e rollback.
4. Liberação de distribuição RustDesk: V2 ainda tem apontamentos; suplemento MIT esclarece coleta, mas concessões de quatro repositórios e gates de distribuição permanecem sem fechamento.
5. Otimização de replay longo, inferências reais, vinte usuários, suspensão do Windows, falhas combinadas e validação PostgreSQL.
6. Federation instalada host/guest, exposição de reconciliação/tarefa estruturada na UI e restauração de listener/descoberta/reconexão autenticada. Auditoria encontrou lacunas; propostas não aplicadas.
7. Provisionamento econômico com discos diferenciais e isolamento efetivo por Dot; colaboração completa, conectores com contas reais, inferência visual local, backup/restauração e operação de atualização.

## Arquivos locais fora do checkpoint

ISOs de instalação, novos metadados gerados em `.maestri/roles`, cópias locais `visual-rollback-*`, estado/credenciais, `.tmp`, builds e dependências permanecem no disco e não são adicionados ao Git. Arquivos dessas áreas já rastreados anteriormente não foram removidos. A varredura automática de padrões de segredo não encontrou achados nos arquivos candidatos; isso não é uma certificação de segurança ou revisão integral de todas as mudanças.
