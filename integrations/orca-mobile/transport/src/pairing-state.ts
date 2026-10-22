import type {Device,PairingOffer} from './client';

export function directEndpoint(value:string):string{
 const text=value.trim();
 const url=new URL(text.includes('://')?text:'ws://'+text);
 if(!['ws:','wss:'].includes(url.protocol)||url.username||url.password||url.search||url.hash||
    !url.hostname||url.pathname!=='/'&&url.pathname!=='/sentra/mobile/v1')throw Error('Endereço LAN inválido. Use IP:porta.');
 const octets=url.hostname.split('.').map(Number);
 if(octets.length!==4||octets.some((value,i)=>!Number.isInteger(value)||value<0||value>255||String(value)!==url.hostname.split('.')[i])||
  !(octets[0]===10||octets[0]===127||octets[0]===192&&octets[1]===168||octets[0]===172&&octets[1]>=16&&octets[1]<=31||octets[0]===100&&octets[1]>=64&&octets[1]<=127))throw Error('Use um endereço IPv4 de LAN ou VPN privada.');
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
/** A fresh desktop QR can recover an address without consuming its invite. */
export function deviceAtOffer(device:Device,offer:PairingOffer):Device{
 if(offer.public_key!==device.public_key)throw Error('Este QR pertence a outra máquina. A identidade pareada foi preservada.');
 return deviceAtAddress(device,offer.endpoint);
}
