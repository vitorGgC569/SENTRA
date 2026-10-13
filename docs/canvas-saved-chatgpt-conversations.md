# Conversas salvas do Canvas no ChatGPT

A integração gerenciada do SENTRA habilita `useSavedChats` e mantém
`experimentalFreshConversationPerTurn` desabilitado. Novos chats do ChatGPT
ficam no histórico da conta conectada.

Para os turnos automáticos dos Dots, o identificador estável da conversa nativa,
o modelo, o esforço e a época de compactação identificam o chat remoto. Conversas
nativas diferentes usam chats diferentes. Continuações enviam apenas o trecho
posterior à última resposta do assistente.

O Browser Host registra a URL de uma conversa concluída no arquivo
`saved-conversations.bin`, ao lado do descritor do navegador. O arquivo usa
`safeStorage` do Electron (proteção do usuário do Windows), escrita atômica e
isolamento entre os perfis de produção e desenvolvimento. Fechar a aba,
expirar a retenção de 30 minutos ou reiniciar o navegador não apaga esse vínculo.
O journal protegido do SENTRA continua responsável pelas mensagens, operações
e envios cujo resultado é incerto.

Ao retomar, o navegador abre a URL exata, exige histórico de respostas e adquire
novamente o conector SENTRA. Índice ilegível, URL divergente ou chat indisponível
bloqueiam a retomada. A integração não cria outro chat silenciosamente nesses
casos. A compactação explícita aposenta o vínculo local do contexto anterior;
o chat anterior continua salvo no ChatGPT. Alterar modelo ou esforço também
produz outra identidade de contexto.

Conversas temporárias antigas não podem ser convertidas retroativamente em
histórico salvo. A primeira mensagem enviada após habilitar a opção cria um
chat salvo a partir do histórico nativo disponível.

Validação automatizada: nove testes em
`launcher/tests/saved-conversations.test.cjs`, incorporados ao patch upstream e
executados pelo build gerenciado. Cobrem armazenamento protegido, retomada,
isolamento de conversas, recusa de URLs inválidas, falha de armazenamento,
chat indisponível e aposentadoria do vínculo após compactação.

Validação real em 11/10/2026: a conversa nativa “Teste de conversa salva — Codex”
recebeu uma palavra de teste, o navegador e o upstream gerenciados foram
reiniciados e a mensagem seguinte recuperou essa palavra. O Browser Host
registrou `browser.saved_conversation_restored`; a resposta ficou registrada
com recibo na interface nativa. O build também valida os padrões de configuração
e a preservação da preferência após recarregar o arquivo de configuração.
