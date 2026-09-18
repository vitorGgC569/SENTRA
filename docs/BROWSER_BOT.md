# Navegador do bot (perfil dedicado)

O bot usa o **próprio navegador**, separado das suas abas pessoais.
É uma janela do Edge só dele, com login próprio guardado numa pasta
chamada **perfil dedicado**.

- Suas abas pessoais **não** são usadas nem fechadas.
- O login do bot fica guardado nesse perfil. Você só faz login **uma vez**.
- Se a sessão expirar, é só repetir o passo de login abaixo.

## Onde fica e como configurar

No arquivo `config.yaml`, seção `browser` (todas opcionais):

| Chave | O que é | Padrão |
|---|---|---|
| `browser.bot_profile_dir` | Pasta do perfil só do bot | `browser_profiles/edge-bot` |
| `browser.launch_flags` | Opções extras de abertura do Edge (lista) | 3 proteções anti-travamento |
| `browser.bot_headless` | Abrir sem janela (`true`) ou com janela (`false`) | `false` (com janela) |

> **Atenção — OneDrive:** a pasta do perfil **não pode** ficar dentro do
> OneDrive (o OneDrive corrompe o perfil do Edge e o programa recusa).
> Se o projeto está dentro do OneDrive, configure um caminho fora dele:
>
> ```yaml
> browser:
>   bot_profile_dir: "C:/Users/SEU_USUARIO/AppData/Local/SENTRA/edge-bot"
> ```
>
> Troque `SEU_USUARIO` pelo seu nome de usuário do Windows.

## Login único (fazer 1 vez)

1. Feche o Edge do bot se ele estiver aberto (o seu Edge pessoal pode
   continuar aberto, não tem problema).
2. Rode para criar/conferir a pasta do perfil:
   ```
   python scripts/prepare_browser_bot.py --init
   ```
   Tem que terminar com código `0` e mostrar o caminho da pasta.
   Se der código `2` falando de OneDrive/link, ajuste o
   `bot_profile_dir` como acima e repita.
3. Rode a verificação (abre a janela do bot):
   ```
   python scripts/prepare_browser_bot.py --check-login
   ```
4. Na janela que abrir, acesse o chat, clique em **Entrar** e faça o
   login normalmente (usuário + senha + confirmação, se pedir).
5. Quando a caixa de digitar mensagem aparecer (campo de texto vazio
   no rodapé da página), o login está pronto.
6. **Feche a janela do bot** (pode fechar sem medo: o login fica salvo
   na pasta do perfil).
7. Rode de novo para confirmar:
   ```
   python scripts/prepare_browser_bot.py --check-login
   ```
   Resultado esperado: mensagem de **logado** e código de saída `0`.

## Como verificar a saúde

```
python scripts/prepare_browser_bot.py --check-login
```

O que cada código de saída significa:

| Código | Significado | O que fazer |
|---|---|---|
| `0` | Logado, tudo certo | Nada. Pode usar o bot. |
| `1` | Não logado / sessão expirada | Siga o passo "sessão expirou" abaixo. |
| `2` | Erro operacional (pasta inválida, Edge não abriu, config errada) | Leia a mensagem de erro, corrija e repita. |

Dica: rode o `--check-login` antes de uma sessão longa. Ele **não envia
nenhuma mensagem**, só olha se a caixa de digitar está visível.

## Se a sessão expirar (passo a passo)

Sinais: `--check-login` devolve código `1`, ou o bot reclama de
"login exigido" / "sessão expirada".

1. Rode:
   ```
   python scripts/prepare_browser_bot.py --check-login
   ```
   Vai abrir a janela do bot na tela de entrar.
2. Faça o login de novo na janela (igual ao primeiro login).
3. Espere a caixa de digitar aparecer.
4. Feche a janela do bot.
5. Rode de novo:
   ```
   python scripts/prepare_browser_bot.py --check-login
   ```
   Tem que dar código `0`.
6. Se continuar dando `1`:
   - Confira se digitou usuário/senha certos e concluiu a confirmação.
   - Apague **só** se orientado: com o Edge do bot fechado, apague a
     pasta do perfil e repita do "Login único". Isso desloga tudo e
     começa do zero.
7. Se der código `2` (não abre, pasta inválida):
   - Veja se o caminho `bot_profile_dir` existe e está fora do OneDrive.
   - Veja se outro Edge do bot já está aberto usando o mesmo perfil
     (feche e repita).
   - Confira `browser.bot_headless: false` para ver a janela durante o login.

## O que NUNCA fazer

- Não apague a pasta do perfil com o Edge do bot aberto.
- Não aponte o perfil para dentro do OneDrive ou para atalhos/links.
- Não use o perfil do bot para navegar nas suas coisas pessoais
  (ele é só do bot, para o login não misturar).
