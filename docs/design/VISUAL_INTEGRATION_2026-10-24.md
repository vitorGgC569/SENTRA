# Integração local do novo visual — 24/10/2026

## Entrega

O visual aprovado foi incorporado à entrada de produção `desktop.html`,
compilado no executável Windows e aplicado à instalação local do SENTRA.
A janela instalada foi aberta e conferida com os Dots, projetos e conversas
existentes. Não depende do servidor Vite nem da API fictícia de avaliação.

Permanecem o preto/grafite neutro, as ações azuis, o Início centrado na conversa,
os mascotes animados e a navegação Início/Conversas/Assistentes/Espaços.
Conversa, Canvas, documentos, formulários e barra externa usam os componentes
existentes; a proposta de reorganização arquitetural continua somente documental.

## Homologação realizada

| Verificação | Resultado |
|---|---|
| Suíte da interface | 265 testes passaram |
| Integração e integridade selecionadas | 59 testes Python passaram |
| Novos contratos do Início | 3 testes Python passaram |
| Build de produção e integridade dos assets | Passaram |
| Detector Impeccable nos componentes conferidos | Nenhuma ocorrência |
| Executável empacotado | Broker autenticado e JS/CSS verificados por SHA-256 |
| Terminal Windows real no executável | Entrada entregue ao ConPTY; segunda janela recusada sem transferência |
| Anexos no backend real | Upload em chunks, conteúdo e SHA-256 conferidos; escopo entre conversas rejeitado |
| Navegação interativa real | Início → conversa → Canvas → conversa; rascunho preservado |
| Apresentação | Claro/escuro; janela desktop 1440×900 e estreita 390×844 |
| Formulário estreito | Novo Canvas aberto e cancelado; rascunho preservado |
| Instalação local | 208 arquivos atualizados com backup; aplicativo aberto e conferido |

O primeiro envio feito pela interface real criou uma única conversa e um único
pedido. O provedor selecionado estava indisponível: o estado ficou incerto,
visível na conversa e no Canvas. Não houve repetição nem troca automática de
modelo. O teste automatizado de mensagem estaciona explicitamente o scheduler;
ele comprova admissão/persistência, não inferência.

As verificações de terminais também cobrem a integração local anterior do
controle de entrada: identidade por janela no desktop, origem autenticada no
gateway móvel, recebimento durável e consulta de confirmação sem reenvio.
Isso não homologa todos os fluxos de posse no aplicativo móvel nem encerra as
pendências de confiabilidade prolongada descritas no registro geral.

## Artefato e recuperação

- Canvas: `132552794` bytes.
- SHA-256: `247e68aeec4304d7bd08a07b55f1a41e4293eff9d9cae4ffffe1c7dd121888ed`.
- Manifesto de assets: `e8150be1016fd8fcca0bea0b8c4a54b1c14150738cbb0257aa36d4c1bde817ba`.
- Selo do snapshot de fontes: `828e7f3af731e161cc2010447235f6c6fe4669d6fe17e269bfd54ac39e66e5ba`.
- Backup local: `.tmp/visual-integration-20261024/installed-backup/patch.json`.
- Evidências e resultado estruturado: [integration/](evidence/2026-10-24/integration/).

O Windows redireciona os arquivos da instalação nesta sessão para
`%LOCALAPPDATA%/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/SENTRA/Commander`.
Foi usada a pasta física verificada, sem alterar as regras de segurança dos
validadores de caminho. O diretório de dados continua `~/.sentra`.

A aplicação do patch recusaria um broker ativo. Os componentes nativos foram
conferidos contra os pins do executável antes da atualização. O backup contém
hashes anteriores e posteriores e os arquivos substituídos. Para recuperar,
fechar a interface e conferir ausência de broker/terminais ativos antes de
restaurar esses arquivos; não substituir executáveis em uso.

## Limites do aceite

Esta entrega homologa a integração visual local e os contratos exercitados.
**Ainda não representa homologação funcional integral do produto.**

- Não foi obtida resposta confirmada de um modelo externo. O catálogo não é
  prova de acesso, e o Dot existente com Grok permanece sem acesso verificado.
- Não foram testados Android/iPhone físicos, VPN, múltiplos monitores,
  tecnologias assistivas nem todas as combinações de ferramentas/modelos.
- Não foi publicado Setup/tag/release novo, nem executada instalação limpa,
  atualização e rollback em máquina independente ou assinatura Authenticode.
- O CI não foi investigado nesta etapa, conforme a prioridade do usuário.
- Os avisos existentes de tamanho do chunk e scripts clássicos no Vite permanecem.

As janelas e servidores temporários de conferência são encerrados ao final;
a instalação atualizada permanece aberta para avaliação do usuário.
