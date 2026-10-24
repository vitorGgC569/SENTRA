# Estudo de lapidação da experiência do cliente — SENTRA

Data: 23/10/2026. Natureza: estudo e recomendações, sem implementação.

## Objetivo e hipótese de uso

Tornar mais fácil começar um trabalho, entender o que acontece, decidir quando
necessário, encontrar o resultado e retomar depois. A qualidade deve aparecer
na previsibilidade da experiência, na leitura e na redução de decisões desnecessárias.

Hipótese orientadora: o cliente quer obter um resultado com seus assistentes sem
precisar conhecer a arquitetura do SENTRA. Isso não significa que todos os
clientes sejam iniciantes; as funções avançadas continuam disponíveis conforme
a tarefa. A hipótese precisa ser validada com usuários reais.

Este documento amplia o [diagnóstico visual](interface-audit-2026-10-23.md) e
complementa a [análise estrutural](../architecture/STRUCTURAL_AUDIT_2026-10-23.md).
Não altera componentes, textos do aplicativo, fluxos, CSS, permissões ou backend.
Exemplos de textos e organização abaixo são propostas para avaliação.

## Evidências e limites

Foram reutilizadas as capturas e observações anteriores de Home, conversa,
Canvas e criação de Dot, incluindo desktop, largura estreita e Home clara.
Nesta etapa, a leitura do código ampliou a cobertura para permissões, documentos,
atividade/Hub, rede, ferramentas, modelos, plugins e skills.

Uma tela examinada por código não foi automaticamente validada ao vivo. Não
foram realizadas novas sessões com clientes, medição de tempo de tarefa, teste
de leitor de tela ou qualificação de instalação. Não há nova nota quantitativa
de usabilidade: as recomendações são baseadas em evidência e hipóteses explícitas.

As skills Impeccable, Frontend Design e UI/UX Pro Max orientam consistência,
composição e interação. Para esta aplicação de trabalho, familiaridade,
legibilidade e orientação têm prioridade sobre expressão decorativa.

## Diagnóstico central

O produto pede que o cliente compreenda vários conceitos antes de concluir uma
tarefa: projeto, Space, Dot, conversa, sessão, Canvas, máquina, modelo e trabalho.
Esses conceitos têm funções legítimas; a interface precisa revelá-los no momento
em que ajudam a decisão.

A lapidação deve concentrar-se em quatro perguntas, respondidas por cada tela:

1. Onde estou e a qual projeto este trabalho pertence?
2. O que posso fazer agora?
3. O que está acontecendo com o meu pedido?
4. O que acontece se eu continuar, sair ou cancelar?

## Jornadas prioritárias

| Jornada | Fricção observada ou deduzida do código | Direção proposta | Critério de facilidade |
| --- | --- | --- | --- |
| Primeiro uso | Projeto, Space, modelo e Dot introduzem dependências antes da primeira conversa | Orientação contextual com próximo passo e motivo do bloqueio | A pessoa encontra o que falta sem explorar configurações por tentativa |
| Começar um pedido | “Nova conversa” leva à lista de Dots | Abrir uma escolha contextual com destino claro, usando assistente já disponível quando aplicável | O rótulo anuncia a próxima etapa e o contexto escolhido permanece visível |
| Criar assistente | Personalização visual domina parte do formulário; modelo obrigatório está em outra aba; esforço usa valores técnicos | Priorizar nome, finalidade e modelo disponível; personalização e ajustes avançados em segundo plano | O usuário identifica campos essenciais e resolve um bloqueio junto ao campo correspondente |
| Acompanhar trabalho | Estados globais, de agente, conexão e entrega aparecem juntos | Um estado principal do trabalho, com escopo e próxima ação; detalhes locais por objeto | A pessoa identifica se deve esperar, responder, aprovar ou consultar |
| Aprovar ação | Perfis e detalhes apresentam termos internos e diferentes alcances | Resumo da ação, recurso afetado, alcance e duração; detalhes técnicos expandíveis | A pessoa consegue explicar o que está autorizando antes de decidir |
| Ver resultado | Recibo, resposta recebida, arquivo alterado e conclusão verificada podem competir visualmente | Resultado e artefatos próximos do trabalho; evidência proporcional ao que foi confirmado | A pessoa encontra a entrega e distingue resposta de tarefa concluída |
| Retomar depois | Home e catálogo de agentes competem com contexto recente | Trabalho recente e pendências primeiro, com título e contexto identificáveis | A retomada leva à tarefa correta sem precisar lembrar o nome do agente |
| Recuperar falha | Mensagens expõem termos como intenção, recibo e Canvas local | Problema, impacto e próxima ação em linguagem cotidiana | A pessoa recupera contexto sem duplicar um envio incerto |

As jornadas pressupõem recursos efetivamente disponíveis. Uma simplificação não
deve selecionar modelo sem autorização, criar sessão silenciosamente nem declarar
conexão ou execução sem confirmação do host.

## Organização de informação e navegação

### Hierarquia proposta

```text
Projeto atual
  Início
  Conversas
  Assistentes

Contexto do espaço selecionado
  Documentos e arquivos
  Área de trabalho
  Computadores conectados

Configurações
  Modelos e integrações
  Ferramentas e skills
  Preferências e informações do aplicativo
```

Esta é uma hipótese de agrupamento, não uma nova navegação implementada. Deve
ser comparada com o uso real: clientes que trabalham diariamente no Canvas podem
precisar da área de trabalho no grupo principal.

Projeto e Space devem continuar distintos quando representam escopos diferentes.
O agrupamento visual pode tornar essa relação clara sem obrigar a pessoa a
memorizar a estrutura. Evitar que um mesmo destino apareça com nomes diferentes
em lateral, cabeçalho, Hub e diálogo.

Atividade é contextual ao trabalho e pode ser aberta a partir dele. Recursos de
administração não precisam ocupar o mesmo nível de destaque que começar e retomar.
A barra superior deve concentrar contexto e ações globais; ferramentas da tarefa
ficam próximas do conteúdo correspondente.

### Divulgação progressiva

| Mostrar primeiro | Mostrar quando necessário | Manter em detalhes técnicos |
| --- | --- | --- |
| Tarefa, assistente, projeto e próxima ação | Modelo, anexos, arquivos e ferramentas pertinentes | IDs de Operation/Run/WorkItem, fingerprints, hashes e journal |
| O que será alterado e onde | Personalização de permissões | Identificadores internos de máquina e grants |
| Resultado, arquivos e pendências | Histórico completo e evidências adicionais | JSON e eventos de infraestrutura |
| Integração e sua disponibilidade | Configuração ou instalação que falta | Parâmetros de protocolo e diagnóstico do transporte |

Detalhes técnicos devem permanecer acessíveis para suporte e clientes avançados.
Um aviso importante de segurança ou incerteza não pode ser escondido como ruído.

## Recomendações por superfície

### Home

Mostrar retomada e pendências antes da apresentação da marca. Um cabeçalho
compacto pode informar projeto e ação principal. Trabalhos recentes precisam
de títulos, assistente, estado e informação temporal quando disponível.

Os personagens continuam ajudando no reconhecimento, em uma escala compatível
com a tarefa. Cartões só devem ocupar área significativa quando houver conteúdo
útil para comparar. Vários cartões com “Especialista” não explicam qual escolher.

Evitar transformar toda pendência em alerta: distinguir decisão do usuário,
trabalho em andamento, informação e falha que bloqueia o próximo passo.

### Assistentes e modelos

Explicar a função do assistente com uma frase concreta, aproveitando instruções
e papel existentes sem inventar especialidades. Na criação, tornar o modelo
necessário encontrável antes do envio e explicar como resolver indisponibilidade.

O campo Papel atualmente inicia com `specialist`; o seletor de esforço pode
exibir low, high e xhigh. O estudo recomenda rótulos compreensíveis, mantendo os
valores internos e mostrando apenas opções que o catálogo realmente suporta.
Não inventar preços, velocidade ou capacidade para facilitar a escolha.

Personalização do personagem pode ficar como uma etapa opcional ou seção
recolhível. A configuração do trabalho não deveria depender de percorrer uma
galeria extensa de personagens.

### Conversa

A conversa deve ser o lugar mais previsível do produto. Cabeçalho com assistente
e contexto; histórico com leitura confortável; compositor visível; ações sobre
arquivos e computador junto do conteúdo relevante.

Separar conexão da conversa, entrega da mensagem e execução da tarefa. Uma
mensagem recebida não comprova uma tarefa concluída. Quando houver uma falha,
preservar texto e contexto, mostrar a situação e oferecer a recuperação segura.

Novos recursos descobertos não deveriam mudar bruscamente a composição sem
necessidade. ConversationTools pode abrir automaticamente um terminal recém
observado; convém testar se isso ajuda ou surpreende. Uma indicação de recurso
disponível, com abertura pelo usuário, é uma alternativa a comparar.

O estado vazio deve explicar o que enviar. Evitar chamadas como “Uma conversa
que continua” quando não houver histórico. Sugestões de pedido devem ser
exemplos claramente identificados, pertinentes ao projeto e não enviados sozinhos.

### Canvas e sessões

O ambiente deve explicar o que significa abrir uma sessão e o que permanece
ativo quando uma aba fecha. A ação de fechar visualização precisa ser distinta
de encerrar um processo.

Em uma área já ocupada, usar vazio compacto no painel livre. A recepção completa
é mais adequada a um workspace inteiramente vazio. A ferramenta inicial deve
ser escolhida pela intenção de uso, sem exibir infraestrutura irrelevante.

O modo simples deve conter o necessário para os caminhos comuns. O avançado
pode expor divisões, diagnósticos e configurações adicionais, sem esconder ações
essenciais de recuperação ou autorização.

### Documentos e arquivos

Separar a navegação de conteúdo, edição e ações administrativas. Salvar deve ter
estado visível, e um conflito precisa indicar se o rascunho foi preservado e como
comparar as versões.

O rótulo atual “Consultar/repetir salvamento” une duas ações de semânticas
diferentes. A proposta é apresentar o próximo passo que o estado real permite,
com explicação da preservação do rascunho. Excluir, restaurar e encerrar colaboração
merecem separação das ações frequentes de edição.

Arquivo do projeto, documento do Space e artefato produzido pelo assistente
precisam ter origem reconhecível. Unificar a descoberta visual não deve apagar
as diferenças de escopo e persistência.

### Permissões e aprovações

Mostrar o assistente, o recurso afetado e o que a autorização permite. Perfis
devem ser comparáveis com linguagem curta e descrição fiel. “Aprovar por mim”
é menos explícito que um rótulo que anuncie as edições permitidas e seus limites.
“Acesso completo” deve continuar comunicando claramente sua amplitude.

Uma aprovação específica precisa distinguir autorizar aquela ação de alterar
um perfil persistente. A interface deve esclarecer alcance e duração conforme
a política real, sem prometer que um bloqueio interrompe efeitos já iniciados.

WorkItem, Grants e identificadores da máquina ficam nos detalhes. A revisão de
uma decisão relevante deve ajudar a pessoa a compreender o efeito, sem repetir
confirmações que não acrescentam informação.

### Atividade, Hub e notificações

Apresentar o que aconteceu em linguagem de produto, com vínculo para o trabalho
correspondente. Tipos internos de eventos e JSON ficam no registro técnico.

A lateral chama uma entrada de “Central do Oxta”, enquanto o diálogo usa “Hub
SENTRA” e uma aba se chama “Companions”. A recomendação é um vocabulário único.
Sobre, personalização e acompanhamento de trabalho podem coexistir, mas não
precisam competir pelo mesmo destaque.

Notificações devem ser proporcionais: decisões pendentes permanecem encontráveis;
sucessos rotineiros não interrompem; avisos repetidos podem ser agrupados sem
ocultar problemas diferentes. A ilha precisa deixar claro quando mostra outro
assistente, e não o trabalho que a pessoa está vendo.

### Rede, computadores e integrações

Priorizar objetivo e disponibilidade: qual computador está conectado, o que
está autorizado e qual ação está disponível. Conexão, pareamento e execução
remota são estados distintos.

Um título orientado a uma ação concreta comunica mais que “Trabalhe de qualquer
lugar”. Endereço e porta podem ficar na configuração manual quando necessário;
qualquer fluxo assistido depende de capacidades reais do produto.

Skills e pacotes MCP têm interfaces de importação e revisão com hashes,
identificadores e parâmetros avançados. A experiência comum pode começar por
origem, descrição, disponibilidade e permissões, mantendo revisão e diagnóstico
acessíveis. Não remover verificações para encurtar um formulário.

## Linguagem: exemplos a avaliar

| Texto atual | Proposta de linguagem | Condição a preservar |
| --- | --- | --- |
| Home | Início | Mesmo destino |
| Novo Dot | Novo assistente; explicar uma vez que assistentes são Dots | Decisão de nomenclatura da marca ainda necessária |
| Novo Space | Novo espaço | Escopo próprio continua identificável |
| Submeter intenção | Criar equipe, delegar trabalho ou outro verbo específico | O botão acompanha a ação escolhida |
| Consultar mesma intenção | Verificar andamento | Consulta a operação original; não reenvia |
| A consulta não chegou ao Canvas | Não foi possível atualizar as informações | Não afirmar que a tarefa falhou |
| O runtime ainda não anunciou modelos disponíveis | Nenhum modelo disponível. Verifique Modelos e integrações. | Não presumir causa específica sem diagnóstico |
| WorkItem e máquina desta conversa | Detalhes técnicos do trabalho | Informações completas continuam disponíveis |
| Viewer conectado | Visualização conectada | Não confundir com máquina autorizada a executar |
| Companions | Assistentes ou Personagens, conforme o conteúdo | Diferenciar trabalho de personalização |

Renomear uma entidade exige consistência em toda a jornada. Uma substituição
global de palavras sem examinar seus significados pode introduzir novas ambiguidades.

## Estados e recuperação

| Situação real | O cliente precisa entender | Ação de interface proposta |
| --- | --- | --- |
| Carregamento inicial | Os dados ainda estão chegando | Preservar estrutura e indicar carregamento local |
| Lista vazia confirmada | Não há itens naquele contexto | Explicar a primeira ação adequada |
| Consulta falhou | Os dados atuais não puderam ser consultados | Atualizar informações; manter contexto conhecido como anterior |
| Mensagem em envio | O pedido está sendo transmitido | Indicação local e prevenção de duplicação |
| Aguardando aprovação | Há decisão necessária do usuário | Acesso direto ao pedido e seu efeito |
| Trabalho em execução | O pedido foi admitido e está sendo processado | Mostrar contexto e atividade confirmada |
| Entrega incerta | O sistema ainda não sabe se a ação ocorreu | Consultar a operação original e preservar o texto |
| Resposta recebida | Chegou uma resposta do assistente | Permitir leitura sem declarar sucesso da tarefa |
| Tarefa verificada | A evidência exigida foi confirmada | Resultado e evidência proporcionais à confirmação |
| Falha confirmada | Há uma falha identificada | Explicar impacto e recuperação compatível |

Fechar um painel, parar observação e cancelar trabalho são ações diferentes.
Um botão de cancelamento só deve prometer o que o backend consegue confirmar.
Em operações pendentes, explicar por que uma ação está indisponível e oferecer
a consulta segura, evitando sensação de bloqueio sem saída.

## Qualidade visual e interação

- Tipografia de interface consistente, com corpo confortável e metadados
  importantes legíveis; evitar 10 px para informação operacional necessária.
- Cor de destaque concentrada na ação principal e seleção; cores de estado
  acompanhadas por texto ou ícone, sem depender só da tonalidade.
- Menos contêineres concorrentes; espaçamento separa assuntos e aproxima relações.
- Rolagem com responsabilidade clara por região; reduzir rolagens aninhadas
  desnecessárias, especialmente em diálogos e navegação estreita.
- Foco visível, retorno ao acionador, nomes acessíveis e ordem de teclado lógica.
- Contraste verificado com estilos efetivos nos dois temas; os dois problemas
  medidos na avaliação anterior continuam candidatos prioritários a correção.
- Layout estreito reorganiza a estrutura e mantém ações encontráveis; não apenas
  reduz fontes. Alvos de toque precisam de tamanho e separação adequados.
- Movimento breve para explicar mudança de estado; respeitar preferência reduzida.
- Conteúdo longo, nomes grandes, falta de informação e dependência indisponível
  fazem parte do desenho, não apenas os dados de demonstração.

## Prioridades do estudo

| Prioridade | Frente | Resultado esperado |
| --- | --- | --- |
| 1 | Clareza dos estados, autorização e recuperação | A pessoa entende o que ocorreu e o próximo passo seguro |
| 1 | Leitura, contraste, foco e caminhos acessíveis | Operações essenciais ficam utilizáveis por mais pessoas |
| 2 | Home, retomada e navegação | O trabalho atual fica encontrável com menos exploração |
| 2 | Conversa, criação de assistente e resultados | Começar e concluir uma tarefa exige menos interpretação |
| 3 | Canvas, documentos, atividade e configurações | Recursos avançados aparecem perto da necessidade |
| 4 | Ritmo visual, personagens e movimento | A identidade fica consistente com a experiência de trabalho |

Esta ordem é uma recomendação para um futuro plano. Não é uma fila de mudanças
já autorizada ou iniciada por este estudo.

## Como validar com clientes

Propor uma rodada exploratória com pessoas que não conhecem o SENTRA e usuários
habituais, registrando separadamente os resultados. Não misturar tempo de login,
instalação ou inferência com dificuldade de navegação.

Tarefas: iniciar um pedido, localizar a entrega, explicar um estado pendente,
aprovar uma ação específica, retomar um trabalho, preservar um rascunho após
falha e localizar um arquivo ou sessão do projeto.

Registrar sucesso sem ajuda, decisões incorretas, caminhos percorridos, dúvidas,
recuperação e tempo até encontrar a ação. Perguntar o que a pessoa acredita que
acontecerá antes de clicar ajuda a revelar rótulos enganosos.

Metas iniciais para discussão, não resultados medidos: pelo menos 80% de sucesso
sem ajuda nas tarefas comuns; contexto correto identificado no início; nenhuma
confusão observada entre consultar e reenviar ou entre fechar painel e encerrar
processo. Definir metas temporais após conhecer a linha de base.

Complementar com teclado, zoom, contraste, leitor de tela, conteúdo longo,
temas, viewport estreito e rede lenta. As verificações automatizadas apoiam a
avaliação; não substituem observar uma pessoa tentando concluir o trabalho.

## Fontes de código conferidas

| Área | Referências no snapshot examinado |
| --- | --- |
| Navegação e entrada da Home | shell-app.jsx:40, :841, :948 |
| Retomada e atenção | shell-home-resume.jsx:21 |
| Criação de Dot e modelo | shell-dialogs.jsx:38, :48, :51, :54, :59 |
| Coordenação e linguagem | shell-dialogs.jsx:94, :110 |
| Perfis de acesso | shell-access.jsx:7, :8, :53 |
| Recibos e eventos | shell-receipts.jsx:6, :21, :33 |
| Hub e nomenclatura | shell-hub.jsx:164; shell-hub-state.js:15 |
| Rede | shell-network.jsx:62, :83, :96 |
| Salvamento e ações de documento | document-panel.jsx:216–220 |
| Plugins e skills | plugin-bundles-dialog.jsx:55, :70; skill-library-dialog.jsx:52, :60 |
| Abertura contextual automática | shell-conversation-tools.jsx:20 |
| Recuperação e texto de falha | shell-failure.js:6, :15, :32 |

Os arquivos dessa tabela estão em sentra_canvas/desktop_ui/src. Capturas e
evidências visuais anteriores estão vinculadas no diagnóstico de interface.
