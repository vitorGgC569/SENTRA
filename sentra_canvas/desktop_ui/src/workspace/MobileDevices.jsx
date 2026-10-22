import React,{useEffect,useState} from 'react';
import {Modal} from '../primitives';
import {api} from '../api';
import QRCode from 'qrcode';
const readActions=['workspace_inventory','workspace_presentation_get','workspace_request_status','dot_canvas_get','conversation_list','conversation_get','message_list','message_send','message_request_status','coordinator_approval_list','document_list','document_get','project_file_list','project_file_preview','project_file_diff','dot_computer_get','dot_computer_read','dot_vm_status','dot_vm_frame'];
export function MobileDevices({dot,onClose,advanced=true}){
 const [bind,setBind]=useState('auto');
 const [devices,setDevices]=useState([]),[offer,setOffer]=useState(null),[qr,setQr]=useState(''),[network,setNetwork]=useState(null),[error,setError]=useState(''),[operate,setOperate]=useState(false),[approveActions,setApproveActions]=useState(false),[busy,setBusy]=useState(false);
 const call=async body=>(await api('/api/mobile/control',body)).value;
 async function refresh(){try{const [list,status]=await Promise.all([call({action:'list'}),call({action:'status'})]);setDevices(list);setNetwork(status);setError('')}catch(e){setError(e.message)}}
 useEffect(()=>{let alive=true;const load=()=>{if(alive)void refresh()};load();const timer=setInterval(load,2500);return()=>{alive=false;clearInterval(timer)}},[]);
 async function invite(){setBusy(true);try{const value=await call({action:'invite'});setOffer({...value,expires:Date.now()+value.expires_in*1000});setQr(await QRCode.toDataURL(value.uri,{width:240,margin:2}));}catch(e){setError('O gateway LAN precisa estar iniciado. '+e.message)}finally{setBusy(false)}}
 async function approve(device){setBusy(true);try{await call({action:'approve',device_id:device.id,scope:{project_id:dot.project_id,space_id:dot.space_id,dot_id:dot.dot_id,actions:[...readActions,...(operate?['dot_computer_action','dot_vm_input','dot_vm_handoff']:[]),...(approveActions?['coordinator_approval_reply']:[])]}});await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}
 async function activate(){setBusy(true);try{await call({action:'start',bind:bind.trim()||'auto'});await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}
 async function deactivate(){setBusy(true);try{await call({action:'stop'});setOffer(null);setQr('');await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}
 return <Modal open onOpenChange={onClose} title="Conectar Android ou iPhone" description={'Parear o aplicativo SENTRA com '+dot.name+' pela rede local.'} className="sw-mobile-dialog">
  <section aria-label="Conexão LAN" className="sw-mobile-network"><strong>{network?.available?(network.status==='ready'?(advanced?'Gateway conectado':'Pronto para conectar'):(advanced?'Broker reiniciando…':'Preparando conexão…')):(advanced?'Gateway indisponível':'Conexão local indisponível')}</strong>{advanced?<p>{network?.reason||'Consultando rede…'}</p>:<p>Conecte o celular e este computador à mesma LAN ou VPN privada.</p>}{network?.endpoint&&<details open={advanced||undefined}><summary>Endereço deste computador</summary><code>{network.endpoint}</code><button onClick={async()=>{try{await navigator.clipboard.writeText(network.endpoint)}catch{setError('Não foi possível copiar o endereço.')}}}>Copiar endereço LAN</button><small>O celular pode atualizar este endereço preservando o pareamento com este computador.</small></details>}{!advanced&&network?.reason&&network.status!=='ready'&&<details><summary>Detalhes da conexão</summary><p>{network.reason}</p></details>}</section>
  {!network?.available&&<section className="sw-mobile-network"><p>Ative a conexão direta neste computador para conectar celulares pela LAN ou VPN privada.</p><details><summary>Escolher interface da VPN</summary><label>IPv4 privado deste computador<input aria-label="Interface LAN ou VPN" value={bind} onChange={e=>setBind(e.target.value)} placeholder="auto ou IP da interface"/></label></details><button disabled={busy} onClick={activate}>Ativar conexão LAN / VPN</button></section>}
  {network?.available&&<details className="sw-mobile-network"><summary>Alterar conexão LAN / VPN</summary><p>Desative a conexão para escolher outro endereço. Os pareamentos ficam salvos; os celulares precisarão reconectar. Os trabalhos dos Dots continuam no computador.</p><button disabled={busy} onClick={deactivate}>Desativar conexão com celulares</button></details>}
  <div className="sw-mobile-pair">
   {qr&&offer?.expires>Date.now()?<><img src={qr} width={240} height={240} alt="QR temporário de pareamento SENTRA"/><p>Escaneie no aplicativo SENTRA. Depois confira a identidade e aprove o dispositivo abaixo.</p></>:<p>Crie um convite temporário para conectar seu celular a este computador.</p>}
   <button disabled={busy||!network?.lan||network?.status!=='ready'} onClick={invite}><strong>Exibir QR Code</strong> · válido por 2 minutos</button>
   <small>Este QR conecta o aplicativo SENTRA instalado no celular. Ele não instala o app nem é um QR do Expo Go.</small>
   {offer?.expires>Date.now()&&<button onClick={async()=>{try{await navigator.clipboard.writeText(offer.uri)}catch{setError('Não foi possível copiar. Use o QR temporário.')}}}>Copiar convite</button>}
  </div>
  <label><input type="checkbox" checked={operate} onChange={e=>setOperate(e.target.checked)}/>{advanced?'Permitir pedidos de operação remota neste Dot. Grants e posse de entrada continuam obrigatórios.':'Permitir solicitar ações pelo celular. Os limites de acesso do Dot continuam valendo.'}</label>
  <label><input type="checkbox" checked={approveActions} onChange={e=>setApproveActions(e.target.checked)}/>Permitir que este dispositivo aprove ou recuse pedidos do coordenador neste Dot.</label>
  {devices.map(d=><article key={d.id}><strong>{d.name}</strong><small>{advanced?d.state+' · Dispositivo: '+d.id:d.state==='pending'?'Aguardando sua aprovação':['active','approved'].includes(d.state)?'Conectado a este Dot':'Acesso encerrado'}</small><small>Confira no celular: {d.fingerprint}</small>
   {d.state==='pending'&&<button disabled={busy} onClick={()=>approve(d)}>Aprovar para {dot.name}</button>}
   {['active','approved'].includes(d.state)&&<button onClick={async()=>{try{await call({action:'revoke',device_id:d.id});await refresh()}catch(e){setError(e.message)}}}>Revogar dispositivo</button>}
  </article>)}
  {error&&<p role="alert">{error}</p>}
 </Modal>;
}
