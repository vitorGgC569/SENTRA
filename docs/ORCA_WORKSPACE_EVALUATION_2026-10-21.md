# Janela integrada de avaliação — 21/10/2026

A janela `SENTRA Desktop` aberta inicialmente é a versão instalada anterior.
A versão do checkout foi aberta em outra janela, `SENTRA · Avaliação ORCA`, com
backend real, arquivos de avaliação próprios e workspace experimental habilitado.
O projeto `SENTRA_Avaliacao` contém Dots de avaliação e não é uma cópia dos Dots
ou das conversas da instalação. Não substitui os bundles ou os perfis instalados.

## Correção posterior: falha de carregamento no Electron

A primeira avaliação apresentada ao usuário falhou. HTTP 200 no verificador
externo não comprovou aplicação do CSS nem carregamento das imagens no renderer.
O diagnóstico do próprio Electron registrou `net::ERR_CONNECTION_RESET` durante
a transferência de recursos, inclusive `desktop.js`. A captura inicial mostrava
o shell sem estilos; a seguinte mostrava o erro do bootstrap.

Correção no transporte local: compressão gzip negociada para JS/CSS/SVG; escrita
em blocos de 64 KiB com prazo de 30 segundos, separado do prazo de cinco segundos
para leitura da requisição; conexão encerrada sem anexar outra resposta HTTP em
caso de falha após envio dos headers. O teste de backpressure retém a leitura por
6,2 segundos e recebe o bundle integral.

A janela isolada foi reaberta com o backend corrigido e o mesmo estado de
avaliação. O processo de terminal independente foi preservado. A instalação
anterior não foi substituída nem encerrada.

Evidência do renderer: `styled=true`, três mascotes com imagem carregada,
`loadError=false` e botão de QR presente. Arquivo local de diagnóstico:
`.tmp/orca-live-evaluation/display-readiness.json`. Isso comprova prontidão de
estilos/imagens; não homologa toda a fidelidade visual ou o uso em aparelhos.

Transferência conferida: JS de 2.185.695 bytes recebeu 729.460 bytes por gzip;
CSS de 160.013 recebeu 35.236. Os hashes do conteúdo descomprimido coincidem.
O gateway LAN continuou `ready`. Lote de regressão: 19 testes Python passaram,
incluindo entrega comprimida, cliente lento, isolamento da avaliação e escopo
dos serviços do computador.

## O que conferir

Nova avaliação: janela **SENTRA · Modo Simples**, com estado próprio e navegação
menos densa. O QR está no ícone **Dispositivos** no topo do Canvas. “Nova sessão”
abre as ferramentas; “Acesso do Dot” prepara permissões locais sem preencher
Grants/WorkItems. Detalhes: [Modo Simples](ORCA_SIMPLE_MODE_2026-10-21.md).
As instruções com o texto “Celular · QR Code” abaixo descrevem a avaliação anterior.

1. Na janela `SENTRA · Avaliação ORCA`, abrir o Canvas de `Oxta Avaliacao`.
2. Conferir abas, divisões, explorador e lista de subagentes dentro do Canvas.
3. Clicar **Celular · QR Code** no topo, depois **Exibir QR Code**.
4. O convite é temporário, dura dois minutos e exige aprovação do dispositivo.

O acesso ao celular também foi colocado na oferta do workspace quando o Canvas
anterior estiver selecionado. Não depende de ativar o workspace ORCA primeiro.

O QR pareia o **aplicativo SENTRA já instalado** no Android/iPhone. Não instala
esse aplicativo e não é um QR do Expo Go. Os pacotes nativos móveis e a
homologação física permanecem pendentes; exportação Hermes não é APK/IPA.

## Imagens dos Dots

Os quatro PNGs responderam HTTP 200 no broker instalado e na avaliação. O
componente mantinha a inicial `D` após uma falha de carregamento. Na versão do
checkout, agora há uma segunda tentativa com URL de recuperação antes do
fallback. Uma falha persistente continua explícita. A renderização final será
conferida pelo usuário na janela de avaliação; HTTP 200 não é prova visual.

## Instância e limites

Estado separado: `.tmp/orca-live-evaluation`. O launcher
`python -m sentra_canvas.evaluation --state <pasta-vazia>` recusa um estado
existente sem o marcador próprio de avaliação. `--electron <electron.exe>` abre
uma janela com perfil de exibição próprio; `--mobile` inicia o gateway LAN
explicitamente. Preparar antes com `npm run build:orca-validation` no desktop.

Nesta sessão, o gateway de avaliação está em
`ws://192.168.0.137:5198/sentra/mobile/v1`; o endereço pode mudar com a rede.
Não foi alterada a regra do firewall do Windows. A conexão entre aparelhos
precisa ser conferida na mesma LAN.

Verificações realizadas: gateway disponível/ready/LAN; convite real com duração
de 120 segundos; geração em memória de PNG QR válido; quatro assets de mascote
disponíveis; três testes de isolamento/recusa de estado e preparação passaram;
142 testes Node desktop passaram; dois builds desktop isolados concluíram.
Não houve nova inspeção automatizada da aparência ou teste em telefone físico.

Build atual: `sentra-orca-experimental-3352f532435f`.
O plano integral de execução, ACP, worktrees, mobile e distribuição continua no
[acompanhamento](ORCA_IMPLEMENTATION_TRACKER.md).
