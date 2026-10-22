import type {Device} from './client';

export function directEndpoint(value:string):string{
 const text=value.trim();
 const url=new URL(text.includes('://')?text:'ws://'+text);
 if(!['ws:','wss:'].includes(url.protocol)||url.username||url.password||url.search||url.hash||
    !url.hostname||url.pathname!=='/'&&url.pathname!=='/sentra/mobile/v1')throw Error('Endereço LAN inválido. Use IP:porta.');
 url.pathname='/sentra/mobile/v1';return url.toString();
}

/** Host key and original scope identify the login; an IP address never does. */
export function upsertDevice(devices:Device[],incoming:Device):Device[]{
 return [...devices.filter(d=>!(d.public_key===incoming.public_key&&
  d.scope.project_id===incoming.scope.project_id&&d.scope.space_id===incoming.scope.space_id&&
  d.scope.dot_id===incoming.scope.dot_id)),incoming];
}

export function deviceAtAddress(device:Device,address:string):Device{
 return {...device,endpoint:directEndpoint(address)};
}
