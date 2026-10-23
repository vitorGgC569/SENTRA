import {Terminal} from '@xterm/xterm';
import {Unicode11Addon} from '@xterm/addon-unicode11';
import {activateOrcaTerminalUnicodeProvider} from '../../../../integrations/orca-terminal/vendor/orca/src/shared/terminal-unicode-provider';
import {restoreCheckpoint,writeTerminalFrame} from '../../../../sentra_canvas/desktop_ui/src/terminal-checkpoint';
import {EmulatorBudget} from '../../../orca-terminal/src/emulator-budget.mjs';

const view=document.documentElement.dataset.sentraView;
const post=value=>window.ReactNativeWebView?.postMessage(JSON.stringify({view,...value}));
const budget=new EmulatorBudget({maxBytes:16*1024*1024,maxRenderers:1});
if(!budget.reserve(view,100,28,500))throw Error('Limite de visualização indisponível');
const term=new Terminal({cols:100,rows:28,scrollback:500,allowProposedApi:true,disableStdin:true,
 fontFamily:'monospace',fontSize:12,convertEol:false,vtExtensions:{kittyKeyboard:true},
 theme:{background:'#111714',foreground:'#e1eee5',cursor:'#b9e5c5'}});
term.loadAddon(new Unicode11Addon());activateOrcaTerminalUnicodeProvider(term);
term.open(document.getElementById('terminal'));
if(term.textarea){term.textarea.readOnly=true;term.textarea.setAttribute('inputmode','none');term.textarea.tabIndex=-1;}
const entry={term,alive:true,inputEpoch:0,cursor:0};let terminalId=null,busy=false;
entry.resizeRenderer=(cols,rows)=>{if(!budget.reserve(view,cols,rows,500))throw Error('Limite de memória da visualização');term.resize(cols,rows)};
entry.onRendererStall=()=>{entry.alive=false;term.dispose();budget.release(view);post({type:'renderer-stalled'})};
// Output may contain terminal queries. This viewer never forwards onData/onBinary.
term.options.disableStdin=true;
window.sentraTerminalFrame=async packet=>{
 if(packet.view!==view)return;
 if(busy){post({type:'ack',id:packet.id,error:'Renderer ocupado'});return;}
 busy=true;
 try{
  if(terminalId&&terminalId!==packet.terminal_id)throw Error('Identidade da sessão mudou');
  terminalId=packet.terminal_id;
  if(packet.kind==='reset'){term.reset();entry.cursor=0;}
  else if(packet.kind==='checkpoint'){
   if(typeof DecompressionStream==='undefined')throw Error('Este WebView não suporta o codec do checkpoint.');
   await restoreCheckpoint(entry,packet.value);
  }else if(packet.kind==='output'){
   const frame=packet.frame;
   if(frame.terminal_id!==terminalId||typeof frame.text!=='string'||frame.text.length>32000||new TextEncoder().encode(frame.text).length>64000||
    !Number.isSafeInteger(frame.start)||frame.start<0||!Number.isSafeInteger(frame.cursor)||frame.cursor>1e12||Array.from(frame.text).length!==frame.cursor-frame.start)throw Error('Frame inconsistente');
   if(frame.reset){term.reset();entry.cursor=frame.start;}
   if(entry.cursor!==frame.start)throw Error('Sequência visual interrompida');
   if(Number.isInteger(frame.cols)&&Number.isInteger(frame.rows)&&frame.cols>=20&&frame.cols<=500&&frame.rows>=5&&frame.rows<=200)
    entry.resizeRenderer(frame.cols,frame.rows);
   await writeTerminalFrame(entry,frame.text);entry.cursor=frame.cursor;
  }else throw Error('Mensagem de terminal incompatível');
  term.options.disableStdin=true;post({type:'ack',id:packet.id,cursor:entry.cursor});
 }catch(error){post({type:'ack',id:packet.id,error:String(error.message||error).slice(0,160)});}
 finally{busy=false;}
};
post({type:'ready'});
