# SENTRA Studio — protótipo independente

Prévia navegável de um redesign do SENTRA Canvas. Não altera a interface instalada, serviços, sessões, cookies ou contas do SENTRA.

## Abrir

No PowerShell, dentro desta pasta:

```powershell
npm.cmd install
npm.cmd run dev
```

Acesse **http://127.0.0.1:5198**. O servidor usa uma porta exclusiva e falha se ela já estiver ocupada. Para encerrá-lo, use Ctrl+C no terminal que o iniciou.

```powershell
npm.cmd run build
npm.cmd run preview
```

O build fica em `dist/` desta pasta. A prévia do build usa **http://127.0.0.1:5199**.

## Roteiro de avaliação

1. Abra o documento **Direção do Studio** pela resposta do Atlas. Edite o texto, alterne para Leitura e redimensione o painel pela borda (mouse ou setas do teclado).
2. Escreva um rascunho e alterne entre Dots, telas e ferramentas. A conversa mantém seu rascunho e posição de leitura nesta sessão.
3. Envie uma mensagem de demonstração. Use **Cenários de demonstração** no cabeçalho para experimentar conclusão, aprovação, falha, desconexão, pausa ou resultado não confirmado.
4. Explore Início, Conversas, Dots, Spaces, Documentos, Canvas e Rede. Selecione um nó do Canvas para abrir seus detalhes.
5. Em Configurações, alterne Claro, Escuro e Sistema. Abra Contas e modelos para simular a conexão com ChatGPT.
6. Abra **Catálogo de componentes** no cabeçalho para revisar tokens, tipografia, ações, estados e identidade.
7. Em Ajuda, use **Rever primeiro acesso** para explorar o onboarding.

## Limites intencionais

- Todas as respostas e atividades são simuladas. Não há chamadas aos serviços SENTRA, OpenAI ou outros provedores.
- A autenticação é uma demonstração sem campos de senha. O botão de conexão não autentica nem desconecta uma conta real.
- Anexos guardam somente nomes de arquivos em memória; conteúdo não é lido nem enviado.
- Voz insere uma transcrição fictícia. Não solicita acesso ao microfone.
- Computador, navegador, terminal e diagnósticos são apresentações locais fictícias.
- Criar Dot/nova conversa permite escolher entre três exemplos já preparados. Canvas demonstra seleção, zoom e inspeção de um grafo fixo.
- Documentos, mensagens, nomes e configurações de demonstração duram até recarregar. Apenas o tema é salvo no armazenamento local da origem do protótipo, na chave `sentra-studio-prototype-theme`.
- As bibliotecas do protótipo possuem manifesto e lockfile próprios. Não é necessário modificar ou construir o frontend principal.

## Assets

Mascotes copiados dos assets OpenDots já presentes no repositório. Licença MIT e atribuição preservadas em `public/assets/LICENSE` (Copyright Atai Barkai). Nenhuma imagem depende de serviço externo.
