# Setup local: sessão existente pelo DOM

O MCP continua local e usa o túnel da OpenAI Platform. A extensão não publica o
MCP nem exige um serviço SENTRA externo. Ela permite que o Setup execute a
configuração autorizada no DOM do perfil já aberto, incluindo Firefox.

O Setup incorpora os pacotes de revisão Chromium e Firefox e o XPI Firefox
aprovado pela Mozilla em 18/10/2026 no canal não listado. Registra o host
Native Messaging por usuário e protege a conexão temporária com DPAPI. A ponte
permite somente as páginas oficiais de túneis e chaves da Platform e controla
somente as abas criadas pela própria configuração. Não importa cookies,
credenciais do perfil, senhas ou históricos. A nova chave criada com autorização
é enviada ao processo local para armazenamento protegido pelo Windows.

O navegador continua responsável pela sessão de autenticação. Quando houver
mais de um perfil elegível, a configuração não escolhe uma conta arbitrariamente.
Janelas privadas não são selecionadas automaticamente. Quando existe uma única
aba Platform elegível, ela é duplicada pela API do próprio navegador, preservando
o contexto de sessão e o container Firefox sem ler cookies. Se houver várias
abas Platform, a configuração pede uma escolha em vez de inferir a identidade.
Login vencido, MFA e escolhas de workspace permanecem etapas
do usuário; a automação prossegue quando o provedor libera a página necessária.

## Distribuição privada

Os ZIPs de fontes são pacotes para revisão e assinatura; não são extensões de
produção assinadas. O Firefox Release exige assinatura Mozilla inclusive para
autodistribuição privada, chamada *unlisted*. Isso não cria uma listagem pública.
O Chrome para Windows também exige um canal de instalação permitido pelo
navegador e a confirmação da extensão. Pacotes temporários e modo de
desenvolvedor servem apenas para testes, não comprovam instalação permanente.

O XPI Firefox privado é incorporado sem alterar os bytes assinados, com SHA-256
fixado e comparação dos scripts com os fontes revisados. A Mozilla apenas
resserializou o manifesto JSON, mantendo os mesmos valores. O teste do Firefox
158.0 na VM passou com a extensão temporária, host nativo compilado, DPAPI real,
sessão sintética preservada, DOM, formulário e preservação da aba original.
A aceitação do XPI assinado em instalação permanente e a conta real ainda
precisam ser comprovadas no navegador.
O validador Mozilla aprovou o pacote sem erros. Registrou dois alertas sobre
a declaração de coleta de dados em versões antigas (Firefox abaixo de 140 e
Android abaixo de 142). O teste desta revisão usa Firefox 158 no Windows;
não comprova versões antigas nem instalação Android.

Quando a ponte estiver ausente, o Setup oferece “Habilitar ponte no Firefox”.
O botão abre Extensões no Firefox instalado e seleciona o XPI na pasta local.
O usuário confirma a instalação pelo próprio navegador. Ao fechar o aviso,
o Setup retoma automaticamente a configuração na sessão Platform desejada.
Não abre um perfil separado nem altera a segurança do navegador.

Ainda não há ID de loja confirmado para Chromium. `distribution.json` mantém
essa pendência e não declara distribuição de todos os navegadores pronta. O Setup
reporta `browser_extension_required` quando a ponte não está habilitada. Nenhuma
preferência de segurança ou política administrativa é alterada para contornar
essa exigência. Os identificadores e a chave pública Chromium atuais são da
revisão de desenvolvimento; o pacote final precisa manter os identificadores
aprovados pelo respectivo canal antes de uma nova compilação integral.

## Evidência necessária

Testes de protocolo, enquadramento, autenticação local, preservação de abas e
semântica DOM com dados sintéticos não comprovam uma conta real. A instalação
anterior na VM validou o núcleo local, o MCP, a interface e 13 executáveis; ela
precede esta ponte. É necessário repetir a validação com o candidato atualizado,
as extensões privadas autorizadas e a sessão real de cada navegador pretendido.

Referências oficiais:

- https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging
- https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/
- https://developer.chrome.com/docs/extensions/how-to/distribute/install-extensions
