# Design da interface do SENTRA

Para trabalhos de interface nesta pasta, consulte as três skills solicitadas pelo
usuário em 2026-10-23. Elas estão instaladas no ambiente Codex em
`$CODEX_HOME/skills` (na configuração padrão, `~/.codex/skills`):

1. `ui-ux-pro-max/SKILL.md`: fundamentar componentes, padrões UX,
   acessibilidade, espaçamento e tokens. Executar a busca pela localização real
   da skill, verificar a adequação dos resultados ao produto e à stack React.
2. `frontend-design/SKILL.md`: formular uma direção visual própria do SENTRA,
   coerente com o uso de conversas, agentes, arquivos e terminais.
3. `impeccable/SKILL.md`: revisar hierarquia, composição, clareza, consistência
   e os estados da interface; consultar a referência correspondente à tarefa.

Ler as skills antes de aplicá-las. Se não estiverem disponíveis, consultar
`../../docs/design/skills.md` para as fontes e comunicar a limitação.
Aplicá-las em etapas, com uma única direção visual explícita; resultados de
busca são sugestões e não substituem o contexto real nem instruções do usuário.

## Validação e contexto

- Esta é uma aplicação de trabalho (modo Operate). Priorizar o trabalho atual,
  leitura, orientação e previsibilidade. Uma recomendação de landing page não
  deve virar automaticamente uma tela do aplicativo.
- Examinar componentes, CSS e a interface renderizada antes de propor alterações.
  A entrada principal é `src/main.jsx`, com o shell em `src/shell-app.jsx`.
- Usar a prévia existente (`npm run preview:orca`, configuração
  `vite.orca-preview.config.js`) para inspeção isolada. A entrada é
  `/desktop-assets/qa/orca-workspace.html?view=home`. Os dados são fixtures:
  capturas não comprovam execução, conectividade ou persistência reais.
- Conferir Home, conversa, Canvas e um diálogo relevante, nos temas claro e
  escuro e nas larguras desktop e estreita. Inspecionar teclado, foco, overflow
  e legibilidade, documentando o que foi efetivamente verificado.
- Preservar sessões, PTYs, permissões, confirmações, rascunhos e contratos de API.
  Mudanças visuais não autorizam relançar sessões ou modificar o backend.
- Consolidar regras existentes quando apropriado: evitar acrescentar mais uma
  camada de overrides para corrigir conflitos de estilos.
- Encerrar serviços temporários de avaliação e informar limitações da validação.

Diagnóstico inicial e prioridades: `../../docs/design/interface-audit-2026-10-23.md`.
