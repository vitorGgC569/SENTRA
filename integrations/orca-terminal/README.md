# Checkpoints experimentais de terminal

Espelho de leitura baseado nos módulos ORCA identificados em `provenance.json`.
O processo Node recebe somente eventos de saída/geometria por stdin e devolve
checkpoints por stdout. Não recebe credenciais do broker, entrada de PTY ou
autoridade para executar ações. Não inicia o aplicativo ORCA.

## Preparação no checkout

Requer Node 22 ou superior. Dentro desta pasta:

```powershell
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm test
```

O build aplica o patch fixado do serializer somente às dependências deste
pacote e registra hashes das fontes/saída em `dist/manifest.json`. O backend
recusa artefato ausente, divergente ou obsoleto. Node é localizado por PATH ou
`SENTRA_TERMINAL_NODE`. Sem esse runtime, a capacidade é indisponível; o
histórico ANSI anterior permanece como recuperação parcial explícita.

Use os comandos `build:orca-validation`/`build:orca-preview` do desktop para
avaliar a integração sem substituir os bundles instalados. A distribuição do
runtime e do pacote no instalador ainda precisa ser implementada e homologada.

## Limites

- Até 32 espelhos, sujeitos também ao orçamento agregado de 2 milhões de células
  lógicas. Isso não representa um limite medido de RSS.
- Geometria entre 20–500 colunas e 5–200 linhas; até 500 linhas de scrollback
  por checkpoint. O serializer reduz esse histórico se necessário para caber
  no limite de 512 KiB do frame. A interface indica o histórico limitado.
- A fila persistente e a quota de armazenamento pertencem ao daemon SENTRA:
  4 MiB agregados/512 KiB por sessão e 16 MiB de payload cifrado, compartilhados
  entre chunks e checkpoints, com metadados adicionais.
- Buffer normal/alternativo, cursor, atributos salvos em ambos os buffers,
  Unicode, modos, OSC e cauda de escape incompleta têm cobertura automatizada.
  Isso não homologa todos os programas TUI ou a renderização visual do Windows.
- Restaurar não recria processos. Depois da morte do daemon, o frame é
  somente leitura. Lacuna na sequência/geometria impede alegar restauração fiel.

Os testes de renderer instanciam xterm em Node sem abrir DOM/janela/navegador.
São testes de células e estado, não de aparência visual.
