import type {Device} from './client';

/** A completed async step may only activate the exact still-paired session. */
export function canActivateSession(
 transport:{isPairedTo:(device:Device)=>boolean},current:unknown,device:Device,
 foreground:boolean,startedEpoch:number,currentEpoch:number,
):boolean{
 return foreground&&startedEpoch===currentEpoch&&transport===current&&transport.isPairedTo(device);
}
