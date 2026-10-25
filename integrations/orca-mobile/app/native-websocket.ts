import {NATIVE_MOBILE_ORIGIN} from '@sentra/mobile-transport';

type NativeSocketConstructor = new (
 url:string, protocols:undefined, options:{headers:Record<string,string>}
) => WebSocket;

export function createNativeWebSocket(url:string){
 // Expo's DOM declarations omit React Native's supported third argument.
 const NativeSocket=WebSocket as unknown as NativeSocketConstructor;
 return new NativeSocket(url,undefined,{headers:{Origin:NATIVE_MOBILE_ORIGIN}});
}
