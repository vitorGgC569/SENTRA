# Wren — frentes 15 e 18

Data: 2026-10-12. Checkout: `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Sem commit, push, reset ou clean.

## Escopo

Frente 15: equipes, contas locais e sincronização de apresentação com escopo exato de projeto, espaço ou documento. A filiação não é Grant. Cada leitura e escrita reconsulta o Control Plane da instalação. Credenciais de provedor não entram no registro.

Frente 18: SENTRA Peer Gateway. Descoberta por endereço explícito, identidade criptográfica, pareamento só com o mesmo código confirmado dos dois lados, canal TLS no websocket `/sentra-peer`, mensagens, projeção de Canvas e delegação com recibo. Autorização só pelo Control Plane da instalação que recebe o pedido. Queda antes do recibo deixa o intent `UNCERTAIN` e não reenvia.

VPN, descoberta e pareamento não autorizam execução. O gateway não serve SQLite, não abre `0.0.0.0` e não cria um segundo Control Plane.

## Código neste checkout

- `sentra_collab/scope.py`: escopo normalizado de projeto, espaço ou documento.
- `sentra_collab/teams.py`: contas, equipes, filiação e projeção. Decide pelo `ControlPlaneService` recebido, com `local_owner=False`.
- `sentra_federation/`: identidade ECDSA P-256, política de bind, diário local em JSON, envelopes assinados, websocket e `PeerGateway`.
- `sentra_remote/peer_surface.py`: bind documentado e diagnóstico sem caminho, chave privada ou SQLite. Export lazy em `sentra_remote/__init__.py`.
- `tests/unit/frentes/wren/test_fronts_15_18.py`.

O diário e os registros de equipe ficam em JSON no diretório privado do processo. Não há namespace novo de SQLite. Run, WorkItem, Operation e Grant saem do Control Plane já existente.

Bind aceito: loopback, endereço privado, ou rede passada em `documented_networks` com prefixo de pelo menos /8. `0.0.0.0`, multicast, reservado e endereço público sem essa documentação são recusados. Um prefixo `/0` também é recusado.

O hello inicial não envia certificado de cliente, para o listener aceitar um peer ainda desconhecido. A identidade desse hello é a assinatura ligada à impressão do certificado TLS do servidor. Nas mensagens seguintes os dois lados apresentam certificado: o cliente exige o certificado pinado do servidor (`CERT_REQUIRED`) e o servidor só aceita certificado de cliente que já esteja no conjunto pinado. A aplicação ainda confere impressão, assinatura, pareamento e Grant.

A delegação não executa comando, não chama shell e não promove o WorkItem. O remoto fica com WorkItem `PENDING` e Operation `WAITING_EXTERNAL`. O recibo traz `executed: false` e `automatic_resend: false`.

## Teste unitário executado agora

Comando, na raiz do checkout:

```text
python -m pytest tests/unit/frentes/wren -q --tb=line
```

Resultado: **7 passed in 7.81s**.

O teste sobe dois `ControlPlaneService.from_store` em diretórios temporários do pytest e dois listeners em `127.0.0.1` com portas efêmeras. Isso não é o Control Plane do usuário, não é VPN, não é duas máquinas e não é prova física.

Cobriu:

- bind público e `0.0.0.0` recusados; `26.1.2.3` só entra com a rede `26.0.0.0/8` documentada; `/0` é recusado;
- descoberta e confirmação de um lado só deixam `execution_authorized: false`; `vpn_member=True` não cria Run;
- código de confirmação errado é recusado; chat antes do segundo confirm não cria Run remoto;
- depois do pareamento dos dois lados, chat e projeção de Canvas exigem Grant; a projeção com raiz `runs` é recusada; o número de Runs não cresce na projeção; `effect_started` permanece falso;
- revogação do pareamento impede a mensagem seguinte;
- delegação sem Grant remoto não admite trabalho; com Grant, o WorkItem remoto permanece `PENDING` e a Operation `WAITING_EXTERNAL`;
- revogar o Grant local impede outra delegação; certificado não pareado no servidor é recusado sem mudar o WorkItem já admitido;
- perda depois do envio marca `UNCERTAIN`, o segundo `delegate` do mesmo intent não cria outra Operation, e o reconcile depois de `restore_link` acha o recibo uma vez;
- perda antes do envio reconcilia como `absent`, a Operation local vai a `FAILED` com `executed: false`, e o mesmo intent não é reenviado;
- conta rejeita `token` e chave privada; filiação de documento não sincroniza o projeto nem outro documento; revogar o Grant de sync bloqueia a escrita embora a filiação continue no JSON;
- projeção federada para escopo de projeto é recusada quando a filiação remota é só de documento, e o remoto não cria Run;
- `GET /canvas.sqlite3` no listener responde `404` sem corpo de banco; o diagnóstico não contém caminho de identidade nem a palavra sqlite.

## Prova física contemporânea

Não houve. Nenhum par de máquinas, nenhuma VPN real, nenhuma confirmação humana fora do processo de teste, nenhum Canvas aberto na interface e nenhum comando executado no computador do outro. A queda de enlace foi a flag `drop_before_send` / `drop_before_receipt` no mesmo host, não uma falha de rede observada.

Não declarar as frentes 15 e 18 homologadas por este teste unitário.

## Delegação de Dot — 2026-10-13

O digest do payload não é a delegação. O remoto cria o WorkItem com a tarefa e o projeto, executa no Control Plane, grava um artefato JSON com tarefa, projeto e resultado, e deixa o WorkItem em `IN_REVIEW` com a Operation em `WAITING_EXTERNAL`. A origem confere os bytes do artefato. A revisão `approved` fecha em `COMPLETED` sem escrever outro artefato. Queda antes do recibo reconcilia o mesmo artefato e não executa de novo.

`home_network` lê a configuração e a desconexão no disco e não sobe listener. `network_enable`, `network_disable`, `network_invite`, `network_revoke`, `network_converse`, `network_delegate` e `network_review` reservam WorkItem do agente do Dot, Operation e lease, marcam `effect_possible` e só então escutam ou enviam. O renderer não leva identidade nem Grant. Registrar a rota em `service.py` não homologa. `service.py` não foi editado.

Dois processos no loopback validam a integração. Não homologam duas máquinas. A Radmin `26.168.99.36` segue só como prova preparada, sem contato. O caminho do artefato não depende dessa segunda máquina.

### Prova real preparada, não executada

1. Nas duas instalações, bind só em loopback ou endereço privado. A Radmin desta máquina, lida sem conectar, está em `26.168.99.36` no adaptador `Radmin VPN`. O cache de vizinhos tem `26.52.38.19` unreachable e `26.0.0.1` stale. Nenhuma segunda máquina foi contactada.
2. Cada lado confirma o mesmo código fora do canal.
3. O Control Plane de cada lado emite `federation.delegate` no projeto. VPN não entra na decisão.
4. Uma delegação da tarefa. O remoto grava o artefato e fica em `IN_REVIEW`. A origem confere os bytes. A revisão fecha sem segundo artefato.
5. Derrubar o enlace antes do recibo, restaurar, reconciliar. A Operation remota continua uma só.

Sem essa troca entre máquinas, a frente não está homologada.

## Lapidação de 2026-10-13

O teste de 7 passed continua sendo dois Control Planes temporários no loopback. O listener agora recusa endereço global mesmo quando a rede foi documentada; essa rede só serve para descoberta e discagem, e não autoriza. Delegar `installer/windows` é recusado antes de criar Run. O instalador da imagem permanece com o Latch. `installer/windows` não foi editado. `physical_proof` e `image_installer` ficam falsos no status. Sem prova física nova.

## O que permanece fora de homologação

1. Dois SENTRAs em computadores diferentes, com o endereço de VPN documentado e o código de pareamento conferido pelas duas pessoas.
2. Queda real de enlace, com os dois diários reconciliados depois que a VPN volta, sem segundo efeito.
3. A janela da rede no shell. O call site `PeerGatewaySurface.network` existe; a Lumen ainda precisa chamá-lo em `network-dialog.jsx`.
4. Certificado de cliente já no hello, e âncora que não seja o próprio certificado autoassinado do peer (`path_length` 0).
5. Qualquer efeito no Control Plane, nas conversas ou nas VMs já existentes do usuário. Esta rodada não os abriu.
