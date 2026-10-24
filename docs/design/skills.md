# Skills de design do SENTRA

Instaladas em 23/10/2026 com a skill oficial `skill-installer` do Codex, por
download dos repositórios originais, incluindo os arquivos de apoio. Não foi
necessário executar o inicializador npm da UI/UX Pro Max: a skill completa foi
instalada diretamente para o Codex.

| Skill | Fonte | Pasta instalada |
| --- | --- | --- |
| UI/UX Pro Max | https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/main/.claude/skills/ui-ux-pro-max | `~/.codex/skills/ui-ux-pro-max` |
| Impeccable | https://github.com/pbakaus/impeccable/tree/main/.agents/skills/impeccable | `~/.codex/skills/impeccable` |
| Frontend Design (Anthropic) | https://github.com/anthropics/skills/tree/main/skills/frontend-design | `~/.codex/skills/frontend-design` |

As instruções foram lidas e usadas na avaliação desta conversa. A descoberta
automática pelo catálogo do Codex fica disponível no próximo turno. O arquivo
`sentra_canvas/desktop_ui/AGENTS.md` registra o uso destas skills para próximos
trabalhos no frontend, sem copiar instruções externas para o código do produto.

## Responsabilidades

1. UI/UX Pro Max: consultar padrões e critérios de qualidade para a stack real;
   definir componentes e tokens a partir do contexto do SENTRA.
2. Frontend Design: avaliar especificidade e propor uma identidade coerente.
3. Impeccable: revisar composição e experiência, conferir os achados e priorizar.
4. Navegador/Playwright: observar o resultado renderizado e validar interações.

Não tratar as três skills como três temas visuais simultâneos. A direção da
interface deve ser única, e critérios de acessibilidade devem ser mensurados.
As consultas automáticas de design system feitas nesta avaliação sugeriram
estruturas de marketing incompatíveis com a aplicação; elas não foram adotadas
nem persistidas como design system. Foram aproveitadas as orientações de UX e
da stack React pertinentes à revisão.

Vercel Web Design Guidelines e uma skill separada de Playwright não foram
instaladas: as três skills solicitadas são as da tabela. A inspeção visual usou
os controles de navegador/Playwright já disponíveis no ambiente.

## Reinstalação

Executar o instalador oficial já fornecido pelo Codex:

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" --repo nextlevelbuilder/ui-ux-pro-max-skill --path .claude/skills/ui-ux-pro-max --name ui-ux-pro-max
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" --repo pbakaus/impeccable --path .agents/skills/impeccable --name impeccable
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" --repo anthropics/skills --path skills/frontend-design --name frontend-design
```

O instalador não sobrescreve uma pasta de skill já existente. Os hashes dos
`SKILL.md` instalados e as contagens de arquivos estão registrados na evidência
local `.tmp/design-audit-20261023/skills-installed.json`.
