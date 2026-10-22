import {useEffect,useRef,useState} from 'react';
import {AppState} from 'react-native';
import {pairedDiscoveryCandidates,type Device} from '@sentra/mobile-transport';
import type Zeroconf from 'react-native-zeroconf';

/** Discovery never pairs, authenticates or dispatches a host request. */
export function useLanDiscovery(devices:Device[]){
 const [candidates,setCandidates]=useState<Device[]>([]),[scanning,setScanning]=useState(false),[notice,setNotice]=useState('');
 const instance=useRef<Zeroconf|null>(null),epoch=useRef(0),timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
 function stop(){epoch.current++;clearTimeout(timer.current);const previous=instance.current;instance.current=null;
  try{previous?.stop()}catch{}try{previous?.removeDeviceListeners()}catch{}try{previous?.removeAllListeners()}catch{}setScanning(false);}
 async function start(){stop();if(AppState.currentState!=='active')return;const ticket=epoch.current;setCandidates([]);setNotice('Buscando hosts já pareados por até 8 segundos…');setScanning(true);
  try{
   const module=await import('react-native-zeroconf');if(ticket!==epoch.current||AppState.currentState!=='active')return;
   const scanner=new module.default();instance.current=scanner;let resolved=0;
   scanner.on('resolved',service=>{if(ticket!==epoch.current)return;if(++resolved>64){stop();setNotice('Limite de anúncios alcançado. Use QR ou endereço manual.');return;}
    const approved=pairedDiscoveryCandidates(devices,service);if(approved.length)setCandidates(previous=>[...new Map([...previous,...approved].map(device=>[device.device_id+':'+device.endpoint,device])).values()].slice(0,16));
   });
   scanner.on('error',()=>{if(ticket!==epoch.current)return;stop();setNotice('Descoberta indisponível nesta rede. Use o QR ou endereço manual.');});
   scanner.scan({type:'sentra',protocol:'tcp',domain:'local.',implType:'NSD',resolveTimeout:3});
   timer.current=setTimeout(()=>{if(ticket!==epoch.current)return;stop();setNotice('Busca concluída. Confira a identidade ao conectar. QR e endereço manual continuam disponíveis.');},8000);
  }catch{if(ticket===epoch.current){stop();setNotice('Este build ou aparelho não oferece descoberta local. Use o QR ou endereço manual.')}}
 }
 useEffect(()=>{const subscription=AppState.addEventListener('change',state=>{if(state!=='active')stop()});return()=>{stop();subscription.remove()}},[]);
 const approved=candidates.flatMap(candidate=>{const current=devices.find(device=>device.device_id===candidate.device_id&&device.public_key===candidate.public_key&&
  device.scope.project_id===candidate.scope.project_id&&device.scope.space_id===candidate.scope.space_id&&device.scope.dot_id===candidate.scope.dot_id);
  return current?[{...current,endpoint:candidate.endpoint}]:[];});
 return {candidates:approved,scanning,notice,start,stop};
}
