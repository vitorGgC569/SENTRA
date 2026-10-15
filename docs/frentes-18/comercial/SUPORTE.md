# Suporte

O suporte descrito aqui é local e gratuito. Não há contrato de suporte pago, não há fila comercial e o produto não está homologado comercialmente.

## O que enviar

- versão do produto
- comando executado
- resultado do comando, sem segredos
- se houve estado UNCERTAIN, o identificador da operação e a confirmação de que ela não foi reenviada

No checkout, estes comandos imprimem só política e fatos redigidos:

```text
python -B -m sentra_quality local-use
python -B -m sentra_quality support-bundle
```

## O que não enviar

Não envie tokens, chaves, cookies, prompts completos nem o arquivo `auth.json`. Não envie conteúdo de `.sentra`, `.oma` ou perfis de navegador.

## Limites conhecidos

- O pacote de suporte não autoriza efeito e não cria Grant.
- Operação UNCERTAIN não é reenviada por este fluxo.
- Não há homologação comercial, nem auditoria de segurança independente, nem prova física de instalação limpa neste documento.
- Licenças de terceiros, SBOM e CVE não ficam resolvidos por este texto.
