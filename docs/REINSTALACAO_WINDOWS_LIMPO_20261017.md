# Recuperação do SENTRA e teste em Windows limpo

Preparado em 17/10/2026 antes da formatação do computador. Este checkpoint
preserva o estado atual do projeto, inclusive documentação, vídeo de apresentação,
evidências visuais e manifesto Vite que ainda não estavam versionados.

## Recuperar o código

Depois de instalar o Git e autenticar a conta proprietária:

```powershell
git clone https://github.com/vitorGgC569/SENTRA.git
cd SENTRA
git pull --ff-only origin main
git status --short --branch
```

Para desenvolver, use Python 3.12 e as dependências do repositório. Para executar
o instalador empacotado, não é necessário instalar Python ou Node.

Git não preserva `auth.json`, `.sentra`, `.oma`, `runs`, perfis de navegador,
ISOs/VDIs, dependências, toolchains, `.tmp`, `dist`, `release` ou builds em
`%LOCALAPPDATA%\SENTRA\Build`. Faça backup separado desses dados se precisar
mantê-los. Credenciais protegidas pelo Windows podem exigir novo login após
a formatação. Um commit enviado não comprova backup desses diretórios.

## Candidato completo para o teste

- Release existente: `installer-preview-20261015-42870dc`, como rascunho de
  pré-release, acessível pela conta proprietária na [lista de releases](https://github.com/vitorGgC569/SENTRA/releases).
- Fonte dos executáveis: `42870dcd50a2476b2f3b52b3c36bd27d86f9496c`.
- Setup: `SENTRA-Setup-preview-20261015-42870dc.exe`, 2.834.212.662 bytes.
- SHA-256: `ac568db91d7614a91d9521d6560bfc94a34085853e102672eeae4f2914487c9e`.
- A entrega usa duas partes, pois o executável excede o limite por asset do GitHub.
- O kit local está em `release/preformat-20261017`, ignorado pelo Git.

O rascunho estava sem assets durante a inspeção inicial. O upload dos binários
foi bloqueado pela revisão automática por exigir autorização explícita para
exportar esses arquivos. A presença deste documento no Git não significa que
o upload foi concluído. Antes de formatar, confirme que ambas as partes e o kit
estão disponíveis no remoto ou guardados em outro dispositivo.

Em 17/10, os 14 executáveis e o Setup corresponderam aos hashes de proveniência.
A comparação dos inputs do build com o checkout encontrou somente três capturas
substituídas de PNG para JPEG em `docs/media/2026-10-13`; nenhum fonte de produto
diferia naquele momento. As atualizações deste guia, do README e do relatório
histórico vieram depois dessa comparação. O candidato foi reaproveitado com
seus recibos originais; não foi recompilado nem reetiquetado como build de 17/10.

## Recompor no computador novo

Na mesma pasta, coloque:

1. `SENTRA-Setup-preview-20261015-42870dc.exe.part01`;
2. `SENTRA-Setup-preview-20261015-42870dc.exe.part02`;
3. `SETUP-SHA256.json`, `RECOMPOR-SETUP.ps1` e `RECOMPOR-SETUP.cmd`, incluídos
   no kit de recuperação e também versionados em `installer/windows/recovery/20261015`.

Execute `RECOMPOR-SETUP.cmd`. Ele usa o PowerShell fornecido pelo Windows,
confere tamanho e SHA-256 de cada parte e do executável recomposto. Não instala
o aplicativo automaticamente e não sobrescreve um Setup existente.

Abra o executável recomposto para testar a primeira instalação. Conclua os
logins e as autorizações de conta solicitados pelo Setup. Verifique abertura
do Desktop/Canvas, criação de Dot, conversa, streaming, reinício e desinstalação.
Registre erros, etapa, caminho escolhido e logs sanitizados. Atualização e
rollback devem ser validados separadamente depois da primeira instalação.

## Verificação desta rodada e limites

O executável empacotado foi executado apenas com `--check`, sem instalar nem
iniciar serviços, e retornou **0**. Os checksums dos executáveis e das duas
partes foram conferidos. Isso comprova integridade do pacote, não uma instalação
concluída em Windows limpo.

A regressão dirigida de instalação/empacotamento teve **78 aprovados e uma
falha**: `test_failed_update_restores_deep_files_and_installation_identity`.
O journal do rollback em caminho longo foi gravado, mas a leitura sem prefixo
Win32 estendido o recusou como inseguro/ausente. O teste usou a base
`.tmp/preformat-20261017-pytest` neste checkout. A falha não foi corrigida nem
ocultada, e o pacote não é declarado homologado para rollback.

Comando da regressão:

```powershell
python -B -m pytest -q -p no:cacheprovider tests/unit/test_installer_automatic.py tests/unit/test_installer_resume_failures.py tests/unit/test_installer_long_paths.py tests/unit/test_sentra_canvas_installer_bundle.py tests/unit/test_build_payload_provenance.py tests/unit/test_release_runtime_components.py tests/unit/test_release_assistant.py --basetemp=.tmp/preformat-20261017-pytest
```

Sem assinatura Authenticode e sem homologação de instalação limpa, atualização,
rollback ou sessão remota RustDesk nesta rodada. As pendências de distribuição
RustDesk registradas no candidato continuam abertas; a release permanece como
rascunho para teste do proprietário.
