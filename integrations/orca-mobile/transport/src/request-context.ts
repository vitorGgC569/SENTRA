type Scope={project_id:string;space_id:string;dot_id:string};
type DeviceIdentity={device_id:string;scope:Scope};
export function bindRequestContext(transport:unknown,device:DeviceIdentity|null){
 if(!transport||!device)throw Error('Dispositivo não conectado.');
 return {transport,device_id:device.device_id,...device.scope};
}
export function requireRequestContext(bound:ReturnType<typeof bindRequestContext>,transport:unknown,device:DeviceIdentity|null){
 if(!device||bound.transport!==transport||bound.device_id!==device.device_id||
    ['project_id','space_id','dot_id'].some(key=>bound[key as keyof Scope]!==device.scope[key as keyof Scope]))
  throw Error('O contexto da conexão mudou. A ação antiga não será transmitida neste contexto.');
}
