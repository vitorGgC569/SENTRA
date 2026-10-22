import {Terminal} from '@xterm/xterm';
import {Unicode11Addon} from '@xterm/addon-unicode11';
import {activateOrcaTerminalUnicodeProvider} from '../../../../integrations/orca-terminal/vendor/orca/src/shared/terminal-unicode-provider';
import {restoreCheckpoint} from '../../../../sentra_canvas/desktop_ui/src/terminal-checkpoint';

const view=document.documentElement.dataset.sentraView;
const post=value=>window.ReactNativeWebView?.postMessage(JSON.stringify({view,...value}));
const term=new Terminal({cols:100,rows:28,scrollback:500,allowProposedApi:true,disableStdin:true,
 fontFamily:'monospace',fontSize:12,convertEol:false,vtExtensions:{kittyKeyboard:true},
 theme:{background:'#111714',foreground:'#e1eee5',cursor:'#b9e5c5'}});
term.loadAddon(new Unicode11Addon());activateOrcaTerminalUnicodeProvider(term);
term.open(document.getElementById('terminal'));
if(term.textarea){term.textarea.readOnly=true;term.textarea.setAttribute('inputmode','none');term.textarea.tabIndex=-1;}
const entry={term,alive:true,inputEpoch:0,cursor:0};let terminalId=null,busy=false;
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
   if(frame.terminal_id!==terminalId||Array.from(frame.text).length!==frame.cursor-frame.start)throw Error('Frame inconsistente');
   if(frame.reset){term.reset();entry.cursor=frame.start;}
   if(entry.cursor!==frame.start)throw Error('Sequência visual interrompida');
   if(Number.isInteger(frame.cols)&&Number.isInteger(frame.rows)&&frame.cols>=20&&frame.cols<=500&&frame.rows>=5&&frame.rows<=200)
    term.resize(frame.cols,frame.rows);
   await new Promise(resolve=>term.write(frame.text,resolve));entry.cursor=frame.cursor;
  }else throw Error('Mensagem de terminal incompatível');
  term.options.disableStdin=true;post({type:'ack',id:packet.id,cursor:entry.cursor});
 }catch(error){post({type:'ack',id:packet.id,error:String(error.message||error).slice(0,160)});}
 finally{busy=false;}
};
post({type:'ready'});
