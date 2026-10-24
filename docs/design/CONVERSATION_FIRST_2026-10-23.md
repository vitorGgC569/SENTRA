# Início centrado na conversa

Substitui a composição inicial descrita na primeira lapidação visual. O usuário
considerou o painel ainda poluído e forneceu uma referência de aplicativo de IA.

O centro agora contém apenas “O que vamos criar?” e o campo de mensagem, com
seletor de Dot, indicação do modelo atual e envio. Não há grades de assistentes,
espaços, retomada ou conversas no conteúdo principal. As conversas recentes
ficam na lateral; as configurações estão recolhidas. As áreas completas continuam
disponíveis pela navegação.

Enviar pelo início cria uma conversa com o Dot escolhido. O título usa as
primeiras oito palavras, com limite de 72 caracteres. Após a confirmação da
criação e a leitura do histórico vazio, a primeira mensagem segue pelo envio
existente, com seu journal e chave próprios. Um pedido pendente ou mensagens
já existentes impedem repetição automática. Se a criação ficar incerta, a tela
preserva o texto e oferece a consulta existente, sem criar outro pedido.

O rascunho inicial e a seleção do Dot ficam associados ao projeto e ao espaço.
Enter envia; Shift+Enter quebra a linha. Nenhuma configuração de acesso é
concedida pelo novo campo. As autorizações continuam no fluxo existente.

Validação: 263 testes da interface passaram. Inspeção renderizada em 1440×900,
1280×720 e 390×844, nos temas claro e escuro; sem overflow horizontal nas
superfícies observadas. Na simulação, foi confirmado o Dot “Teste”, o título
“Quero revisar o login do projeto com cuidado”, uma única mensagem do usuário
e a resposta explicitamente identificada como prévia. Também foram conferidos
o retorno ao início, a quebra de linha e o rascunho após recarregar.

Capturas: `evidence/2026-10-23/conversation-first/`. A fixture local agora simula
criação e mensagens em memória, sem executar agentes nem acessar serviços.
Essas capturas não comprovam envio real ao modelo. O backend permanece intacto.
