# Relatório de implementação — SENTRA Canvas (07/10/2026)

## Resultado

Criado pacote independente **sentra_canvas** que executa em Windows, sem Maestri,
e gerencia workspaces, terminais ConPTY, agentes SENTRA CLI independentes,
equipes, tarefas assíncronas, namespace persistente, API local autenticada,
auditoria pesquisável e interface desktop aberta em janela Edge.

O novo pacote usa o SENTRA CLI já presente, não cria marca Maestri nem copia
seus arquivos. Não foi feita alteração em módulos do instalador, onboarding,
segurança de configuração ou release que estavam sob edição paralela.

## Código criado

- sentra_canvas/__init__.py
- sentra_canvas/__main__.py
- sentra_canvas/terminal.py
- sentra_canvas/store.py
- sentra_canvas/service.py
- sentra_canvas/namespaces.py
- sentra_canvas/instance_lock.py
- sentra_canvas/Iniciar-SENTRA.cmd
- sentra_canvas/static/index.html
- sentra_canvas/static/app.css
- sentra_canvas/static/app.js
- tests/unit/test_sentra_canvas.py
- tests/e2e/test_sentra_canvas_ui.py
- docs/SENTRA_CANVAS.md
- Este relatório

Artefatos de execução não versionados (.sentra/canvas/): SQLite da aplicação
e screenshot de E2E em evidence/canvas-e2e.png.

## Baseline e validações

1. Antes das alterações: testes existentes SENTRA CLI + Model Gateway:
   87 passed, 38.66 s.
2. Após implementação principal: testes do Canvas + E2E do Edge, mais
   regressão SENTRA CLI e Gateway: **98 passed, 53.50 s**.
3. Após renomeação, duplicação, busca de auditoria, fechamento seguro:
   testes específicos Canvas + E2E: **13 passed, 16.00 s**.
4. Windows ConPTY real testado com três processos CMD simultâneos, input
   individual, saída incremental, resize e encerramento.
5. Dois processos CLI SENTRA independentes iniciados em PTYs, com saída do CLI
   observada. **Não houve demonstração de modelo autenticado/respondendo**
   nesta entrega; processos vivos não são tratados como modelo pronto.
6. Playwright Edge real: criação de 2 workspaces, 3 terminais, comando de
   saída real, 3 agentes, time com coordenador+2 trabalhadores e tarefa de
   teste; evidência de screenshot.
7. Segurança validada: token ausente/incorreto, host/origin impróprios,
   isolamento de workspace, idempotência de tarefas e checagens de nomes/paths.
8. Node --check app.js e Python compileall sem erros.
9. Nenhum git reset/checkout/stash ou limpeza em massa. Mudanças locais
   preexistentes foram preservadas e novas alterações são isoladas.

## MVP implementado versus objetivo integral

Implementado: interface funcional, dois ou mais workspaces, >=3 terminais,
>=2 processos SENTRA CLI, equipe, tarefa assíncrona com provider de teste,
persistência e reabertura correta, auditoria, isolamento via API e ausência
de dependência operacional do Maestri.

Parcial: delegação real a modelo via SENTRA CLI está programada e requer
aprovação, mas **não foi certificada com credenciais externas**. A governança
OMA ainda não executa o job dessa nova UI; os jobs Canvas usam sua própria
fila local simplificada. Nenhum comportamento de modelo deve ser inferido.

Não implementado integralmente: sandbox de processos / ACL granular,
transcript persistente e reattachment de ConPTY, multiusuário real, terminal
com emulador TUI/ANSI completo, pausa/reexecução durável OMA, aprovações
governadas, integração MSI/atualizador e catálogo live de modelos. Recursos
máximos de CPU/RAM por processo também requerem próxima etapa.

## Próximas prioridades

- Integrar API de jobs e governança existente, em vez da fila local Canvas;
  fluxo coordenador-trabalhadores com verificação independente real.
- Acoplar um emulador terminal de verdade (por exemplo, xterm.js após revisão
  de dependência/licença), histórico de saída redigido e persistente.
- Associar workspace a repositórios externos autorizados com confirmação,
  sandbox isolada, arquivos permitidos e políticas por agente/ferramenta.
- Validar login e modelo via Model Gateway e integrar aos controles de UI.
- Consumir a entrada pública do Canvas no Setup/MSI em colaboração com a
  outra conversa, sem sobrescrever arquivos sob edição.

## Atualização de 07/10/2026 — aplicativo Windows independente

Foi implementada e executada uma janela própria do Windows via pywebview/WebView2, sem abrir janela de navegador, com barra de título minimalista, canvas infinito e nós conectáveis. O binário foi compilado com PyInstaller e iniciado como SENTRA.exe no computador Windows autorizado.

**Executável compilado:** `.sentra/canvas/native-dist/SENTRA.exe` (18.798.640 bytes). O inicializador `sentra_canvas/Iniciar-SENTRA.cmd` abre preferencialmente esse executável. A UI principal `native.html/native.css/native.js` inclui barra lateral, ferramentas flutuantes, zoom/pan, nós de terminais e agentes, equipes, notas, conexões, inspetor e auditoria. Os nós, layouts e conexões são transacionalmente persistidos no SQLite independente `graph.sqlite3`.

**Backend nativo:** Windows ConPTY permanece responsável pelos terminais reais. A inicialização de agentes pelo executável congelado usa o `dist/sentra-cli.exe` preexistente, em vez de tentar executar o próprio binário com flags de Python. A autenticação de modelo não foi validada neste teste da versão empacotada.

**Evidência:** a janela Windows compilada foi identificada pelo título `SENTRA` e foi aberta/maximizada no computador. Captura em `.sentra/canvas/evidence/native-live.png`. A E2E do canvas gráfico em Edge headless confirmou criação de recursos, saída ConPTY, conexão entre nós, zoom e persistência de arraste de nó.

**Regressão combinada:** 102 testes aprovados (57,82 s), incluindo testes existentes de SENTRA CLI e Model Gateway, contratos Canvas e ambos fluxos E2E. Compilação Python e checagem sintática JS aprovadas.

**Limites remanescentes:** ainda não existe paridade funcional completa com Maestri. A coordenação durável OMA, autorização granular/sandbox, catálogo autenticado, emulação VT completa, restauração de processos/PTYS, métricas avançadas e integração ao instalador/assinatura/publicação permanecem pendentes. O executável Windows foi gerado isoladamente, sem tocar nos módulos do instalador em edição concorrente.

## Integrações de 07/10/2026 — SENTRA CLI / Codex / Antigravity

Concluída a atualização do seletor Novo terminal com descoberta
dinâmica e permitida de executáveis, sessão SENTRA CLI e Codex
como terminais ConPTY reais e Antigravity como editor gráfico externo.

Os nós vinculados podem realizar handoff explícito de mensagens com
confirmação via POST /api/graph/handoff. Somente terminais SENTRA CLI
e Codex ativos podem receber, após validar aresta dirigida e workspace.
Nunca disparar via link automaticamente e nunca encaminhar a shells CMD.
O histórico fica persistido em graph.sqlite3.

Testes: 105 aprovados na regressão combinada (64,16 s); 4 aprovados
novamente após a correção de remoção de notas e handoffs. Dois
processos SENTRA CLI e um Codex simultâneos iniciados via ConPTY.
Codex exec real devolveu resposta esperada (código 0).
A chamada real ao modelo SENTRA CLI falhou com erro de
autenticação/provedor (código 1): não há confirmação de modelo
autenticado. Antigravity instalado como Electron, sem agente CLI
compatível identificado.

Executável Windows atualizado recompilado pelo Build-SENTRA.ps1
e aberto no computador em .sentra/canvas/native-dist/SENTRA.exe.
Verificação visual do seletor: opções SENTRA CLI, OpenAI Codex CLI
e Antigravity aplicativo externo presentes, default SENTRA CLI.
Captura em .sentra/canvas/evidence/native-cli-choices.png.
O Setup/MSI, Maestri e trabalhos de outras conversas não foram
alterados por esta entrega.

Pendências: renderizador VT/TUI completo para Codex, autenticação
do gateway SENTRA, interface programática oficial para agente
Antigravity e automação multiagente durável no OMA.
