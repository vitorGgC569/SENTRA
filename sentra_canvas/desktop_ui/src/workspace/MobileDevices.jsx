import React,{useEffect,useRef,useState} from 'react';
import {Modal} from '../primitives';
import {api} from '../api';
import QRCode from 'qrcode';
const readActions=['workspace_inventory','workspace_presentation_get','workspace_request_status','dot_canvas_get','conversation_list','conversation_get','message_list','message_send','message_request_status','coordinator_approval_list','document_list','document_get','project_file_list','project_file_preview','project_file_diff','dot_computer_get','dot_computer_read','dot_vm_status','dot_vm_frame'];
export function MobileDevices({dot,onClose,advanced=true}){
 const [bind,setBind]=useState('auto');
 const [devices,setDevices]=useState([]),[offer,setOffer]=useState(null),[qr,setQr]=useState(''),[network,setNetwork]=useState(null),[actionError,setActionError]=useState(''),[statusError,setStatusError]=useState(''),[operate,setOperate]=useState(false),[approveActions,setApproveActions]=useState(false),[busy,setBusy]=useState(false);
 const mounted=useRef(false),readGeneration=useRef(0),periodicRead=useRef(false),actionInFlight=useRef(false),readControllers=useRef(new Set());
 const call=async (body,signal)=>(await api('/api/mobile/control',body,{readOnly:body.action==='list'||body.action==='status',signal})).value;
 async function refresh(periodic=false){
  if(periodic&&periodicRead.current)return;
  if(periodic)periodicRead.current=true;
  const generation=++readGeneration.current,controller=new AbortController();readControllers.current.add(controller);
  const timeout=setTimeout(()=>controller.abort(),8000);
  try{const [list,status]=await Promise.all([call({action:'list'},controller.signal),call({action:'status'},controller.signal)]);
   if(mounted.current&&generation===readGeneration.current){setDevices(list);setNetwork(status);setStatusError('')}
  }catch(e){if(mounted.current&&generation===readGeneration.current)setStatusError(e.name==='AbortError'?'A consulta demorou demais. Ela será tentada novamente.':e.message)}
  finally{clearTimeout(timeout);readControllers.current.delete(controller);controller.abort();if(periodic)periodicRead.current=false}
 }
 useEffect(()=>{mounted.current=true;void refresh(true);const timer=setInterval(()=>void refresh(true),2500);return()=>{mounted.current=false;readGeneration.current++;clearInterval(timer);for(const controller of readControllers.current)controller.abort()}},[]);
 async function runAction(action){
  if(actionInFlight.current)return;
  actionInFlight.current=true;readGeneration.current++;setBusy(true);setActionError('');
  try{await action()}catch(e){if(mounted.current)setActionError(e.message)}finally{actionInFlight.current=false;if(mounted.current)setBusy(false)}
 }
 async function invite(){await runAction(async()=>{const started=Date.now(),value=await call({action:'invite'});const image=await QRCode.toDataURL(value.uri,{width:240,margin:2});if(mounted.current){setOffer({...value,expires:started+value.expires_in*1000});setQr(image)}})}
 async function approve(device){await runAction(async()=>{await call({action:'approve',device_id:device.id,scope:{project_id:dot.project_id,space_id:dot.space_id,dot_id:dot.dot_id,actions:[...readActions,...(operate?['dot_computer_action','dot_vm_input','dot_vm_handoff']:[]),...(approveActions?['coordinator_approval_reply']:[])]}});await refresh()})}
 async function activate(){await runAction(async()=>{await call({action:'start',bind:bind.trim()||'auto'});await refresh()})}
 async function deactivate(){await runAction(async()=>{await call({action:'stop'});if(mounted.current){setOffer(null);setQr('')}await refresh()})}
 return <Modal open onOpenChange={onClose} title="Conectar Android ou iPhone" description={'Parear o aplicativo SENTRA com '+dot.name+' pela rede local.'} className="sw-mobile-dialog">
  <section aria-label="Conexão LAN" className="sw-mobile-network"><strong>{!network&&!statusError?'Consultando conexão…':statusError?'Não foi possível consultar a conexão':network?.available?(network.status==='ready'?(advanced?'Gateway conectado':'Pronto para conectar'):(advanced?'Broker reiniciando…':'Preparando conexão…')):(advanced?'Gateway indisponível':'Conexão local indisponível')}</strong>{advanced?<p>{network?.reason||'Consultando rede…'}</p>:<p>Conecte o celular e este computador à mesma LAN ou VPN privada.</p>}{network?.endpoint&&<details open={advanced||undefined}><summary>Endereço deste computador</summary><code>{network.endpoint}</code><button onClick={async()=>{try{await navigator.clipboard.writeText(network.endpoint)}catch{setActionError('Não foi possível copiar o endereço.')}}}>Copiar endereço LAN</button><small>O celular pode atualizar este endereço preservando o pareamento com este computador.</small></details>}{!advanced&&network?.reason&&network.status!=='ready'&&<details><summary>Detalhes da conexão</summary><p>{network.reason}</p></details>}</section>
  {!network?.available&&<section className="sw-mobile-network"><p>Ative a conexão direta neste computador para conectar celulares pela LAN ou VPN privada.</p><details><summary>Escolher interface da VPN</summary><label>IPv4 privado deste computador<input aria-label="Interface LAN ou VPN" value={bind} onChange={e=>setBind(e.target.value)} placeholder="auto ou IP da interface"/></label></details><button disabled={busy} onClick={activate}>Ativar conexão LAN / VPN</button></section>}
  {network?.available&&<details className="sw-mobile-network"><summary>Alterar conexão LAN / VPN</summary><p>Desative a conexão para escolher outro endereço. Os pareamentos ficam salvos; os celulares precisarão reconectar. Os trabalhos dos Dots continuam no computador.</p><button disabled={busy} onClick={deactivate}>Desativar conexão com celulares</button></details>}
  <div className="sw-mobile-pair">
   {qr&&offer?.expires>Date.now()?<><img src={qr} width={240} height={240} alt="QR temporário de pareamento SENTRA"/><p>Escaneie no aplicativo SENTRA. Depois confira a identidade e aprove o dispositivo abaixo.</p></>:<p>Crie um convite temporário para conectar seu celular a este computador.</p>}
   <button disabled={busy||!!statusError||!network?.lan||network?.status!=='ready'} onClick={invite}><strong>Exibir QR Code</strong> · válido por 2 minutos</button>
   <small>Este QR conecta o aplicativo SENTRA instalado no celular. Ele não instala o app nem é um QR do Expo Go.</small>
   {offer?.expires>Date.now()&&<button onClick={async()=>{try{await navigator.clipboard.writeText(offer.uri)}catch{setActionError('Não foi possível copiar. Use o QR temporário.')}}}>Copiar convite</button>}
  </div>
  <label><input type="checkbox" checked={operate} onChange={e=>setOperate(e.target.checked)}/>{advanced?'Permitir pedidos de operação remota neste Dot. Grants e posse de entrada continuam obrigatórios.':'Permitir solicitar ações pelo celular. Os limites de acesso do Dot continuam valendo.'}</label>
  <label><input type="checkbox" checked={approveActions} onChange={e=>setApproveActions(e.target.checked)}/>Permitir que este dispositivo aprove ou recuse pedidos do coordenador neste Dot.</label>
  {devices.map(d=><article key={d.id}><strong>{d.name}</strong><small>{advanced?d.state+' · Dispositivo: '+d.id:d.state==='pending'?'Aguardando sua aprovação':['active','approved'].includes(d.state)?'Conectado a este Dot':'Acesso encerrado'}</small><small>Confira no celular: {d.fingerprint}</small>
   {d.state==='pending'&&<button disabled={busy||!!statusError} onClick={()=>approve(d)}>Aprovar para {dot.name}</button>}
   {['active','approved'].includes(d.state)&&<button disabled={busy||!!statusError} onClick={()=>void runAction(async()=>{await call({action:'revoke',device_id:d.id});await refresh()})}>Revogar dispositivo</button>}
  </article>)}
  {statusError&&<p role="alert">Não foi possível consultar o estado da conexão. {statusError}</p>}
  {actionError&&<div><p role="alert">{actionError}</p><button type="button" onClick={()=>setActionError('')}>Dispensar aviso</button></div>}
 </Modal>;
}
