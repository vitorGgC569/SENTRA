import type {TerminalOutputFrame} from './contracts';
export type TerminalDelivery=TerminalOutputFrame&{reset:boolean};
/** One in-flight read, bounded frames and a generation fence. Never sends input. */
export class TerminalFeed {
 private cursor=0;private generation=0;private running=false;
 private timer:ReturnType<typeof setTimeout>|null=null;
 constructor(private terminalId:string,private read:(cursor:number)=>Promise<TerminalOutputFrame>,
  private deliver:(frame:TerminalDelivery)=>void|{cursor:number}|Promise<void|{cursor:number}>,private failed:(error:Error)=>void,after=0){
  if(!Number.isSafeInteger(after)||after<0||after>1e12)throw Error('Cursor inicial inválido');this.cursor=after;
 }
 get after(){return this.cursor;}
 start(){if(this.running)return;this.running=true;void this.poll(++this.generation);}
 stop(){this.running=false;this.generation++;if(this.timer!==null)clearTimeout(this.timer);this.timer=null;}
 private async poll(generation:number){
  try{
   const frame=await this.read(this.cursor);
   if(!this.running||generation!==this.generation)return;
   if(frame?.protocol_version!==1||frame.terminal_id!==this.terminalId||frame.read_only!==true||frame.automatic_input_replay!==false||
      typeof frame.text!=='string'||typeof frame.status!=='string'||typeof frame.truncated!=='boolean'||typeof frame.has_more!=='boolean'||
      !Number.isSafeInteger(frame.start)||frame.start<0||!Number.isSafeInteger(frame.cursor)||frame.cursor<frame.start||
      frame.cursor>1e12||Array.from(frame.text).length>16000||Array.from(frame.text).length!==frame.cursor-frame.start||
      frame.has_more&&frame.cursor===frame.start)
    throw Error('Frame de terminal inválido. Observação interrompida.');
   if(frame.start!==this.cursor&&!frame.truncated)throw Error('Lacuna de terminal não declarada. Consulte novamente.');
   const rendered=await this.deliver({...frame,reset:frame.truncated||frame.start!==this.cursor});
   if(!this.running||generation!==this.generation)return;
   const cursor=rendered?.cursor??frame.cursor;
   if(!Number.isSafeInteger(cursor)||cursor<0||cursor>1e12)throw Error('Cursor de renderização inválido');
   this.cursor=cursor;
   if(!frame.has_more&&frame.process_live!==true&&frame.recoverable!==true&&frame.status!=='running'){this.stop();return;}
   this.timer=setTimeout(()=>{this.timer=null;void this.poll(generation)},frame.has_more?0:700);
  }catch(error){if(!this.running||generation!==this.generation)return;this.stop();this.failed(error instanceof Error?error:Error('Observação indisponível.'));}
 }
}
