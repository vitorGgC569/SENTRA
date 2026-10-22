# Terminal móvel, LAN e continuidade — 21/10/2026

Build de fontes e artefatos: `sentra-orca-experimental-0840b51b0deb`.
A migração integral continua aberta. A janela já aberta usa o backend anterior
desta mesma data; este build não foi aplicado à instalação ou aos aparelhos.

## Implementado

- Leitura incremental e checkpoint exigem WorkItem em execução, Grant
  `terminal:read`, identidade da máquina e vínculo central da sessão. Trocar
  Dot, terminal ou WorkItem não transfere autorização.
- Frames limitados a 16.000 pontos de código Unicode, cursor e lacuna explícitos.
  O catálogo informa o limite de 100 sessões recentes.
- Uma leitura em andamento, aguardando confirmação do renderer antes de avançar.
  Consultas a cada 700 ms quando alcançam a saída atual. Assinatura de eventos
  continua pendente; este transporte usa leitura periódica limitada.
- xterm offline com o provedor Unicode ORCA inventariado e o restaurador do
  desktop: buffers normal/alternativo, geometria, atributos salvos e sequências
  incompletas. O WebView não recebe credenciais nem encaminha respostas de
  protocolo ao processo; sua CSP bloqueia rede.
- Entrada nativa de texto, Enter, Ctrl+C, Tab, Esc e setas, com confirmação e
  operação central existente. O diário persiste a intenção antes de transmitir.
  Mudança de cliente/escopo invalida entradas pendentes. Suspensão interrompe a
  leitura; reconexão não repete entradas.

Leituras são observações autorizadas, sem recibo inventado de conclusão física.
Entrada entregue também não comprova que o comando terminou.

## Evidências

O ensaio Windows usa gateway WebSocket E2EE, Canvas HTTP, DPAPI e ConPTY reais,
com estado próprio. Uma entrada acrescenta uma linha a um arquivo temporário.
A confirmação é descartada e a conexão cai. Após autenticar novamente, o
cliente consulta o pedido original e recupera o recibo sem reenviar. O arquivo
contém exatamente uma linha. Revogar o Grant bloqueia a próxima observação.
O ensaio usa loopback; não comprova Wi-Fi de Android/iPhone.

O renderer foi ensaiado em Electron descartável, sem perfil do usuário:
Unicode, buffers, atributos e sequência incompleta restaurados; tentativa de
rede bloqueada pela CSP, com zero acessos ao servidor. Isso não homologa o
WebView nativo dos telefones.

- 19 testes Python passaram: terminal real, confirmação perdida, revogação,
  renderer, reinício do broker, escopo, ambiente PowerShell e assets.
- 15 testes Node do transporte e um teste dos mods nativos Expo passaram.
- TypeScript do aplicativo e transporte passou.
- Exportações Hermes Android/iOS concluíram. Não são APK/IPA.
- Inventário conferiu oito módulos E2EE, 28 arquivos de terminal, onze origens
  de adaptação e 979 registros de dependências.

## Ambiente PowerShell

O ensaio revelou um `PSModulePath` temporário herdado do host de desenvolvimento
que podia carregar PSReadLine de outro runtime e abrir um prompt de confiança.
A criação de terminais PowerShell pelo Canvas agora compõe esse caminho pelos
valores persistidos do Windows; se ausentes, o PowerShell inicializa padrões.
PATH e demais variáveis permanecem. Nenhuma política de execução, confiança ou
registro foi alterado. Outros pontos de criação de subprocessos ainda precisam
de auditoria.

## Configuração nativa LAN

O campo Android anterior não era processado pelos plugins instalados. Agora
`expo-build-properties` 55.0.18, compatível com o Expo 55 instalado, configura
`android.usesCleartextTraffic=true`. A introspecção confirma o atributo no
manifesto Android. A conexão LAN mantém E2EE e chave do host fixada.
[Configuração oficial](https://docs.expo.dev/versions/latest/sdk/build-properties/).

No iOS, os mods preservam a descrição de acesso à rede local e
`NSAllowsLocalNetworking=true`, sem habilitar `NSAllowsArbitraryLoads`.
[Referência Apple](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking).

## Ainda falta

Build nativo e assinatura Android/iOS; aparelhos físicos; WebView/IME/touch e
suspensão reais; descoberta LAN/mDNS; hierarquia e rascunhos persistentes;
criação de WorkItems/Grants no desktop; assinatura retomável de eventos e
controles remotos completos. WorkItem encerrado não recebe autorização nova
para histórico: esse caso exige contrato próprio.

O QR atual pareia um aplicativo SENTRA já instalado. Não instala o aplicativo
nem substitui os builds nativos pendentes. Outras frentes permanecem no
[acompanhamento integral](ORCA_IMPLEMENTATION_TRACKER.md).
