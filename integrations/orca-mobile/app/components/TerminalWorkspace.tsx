import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Alert,AppState,Pressable,ScrollView,Text,TextInput,View} from 'react-native';
import {WebView} from 'react-native-webview';
import * as Crypto from 'expo-crypto';
import {Buffer} from 'buffer';
import {MobileClient,TerminalFeed,type TerminalOutputFrame,type TerminalDelivery} from '@sentra/mobile-transport';
import {useProtectedDraft} from './use-protected-draft';
import {TERMINAL_DOCUMENT} from '../terminal/document';

type Props={draftScope:string;client:MobileClient|null;conversation:any;connected:boolean;colors:Record<string,string>;
 request:(action:string,fields?:Record<string,any>,effect?:boolean)=>Promise<any>};
const unwrap=(value:any)=>value?.ok===true?value.value:value;

export function TerminalWorkspace({draftScope,client,conversation,connected,colors,request}:Props){
 const [inventory,setInventory]=useState<any>(null),[selected,setSelected]=useState(''),[ready,setReady]=useState(false);
 const [notice,setNotice]=useState(''),[writing,setWriting]=useState(false),[reload,setReload]=useState(0),[processLive,setProcessLive]=useState(false);
 const [foreground,setForeground]=useState(AppState.currentState==='active'),[viewStatus,setViewStatus]=useState('Aguardando sessão.');
 const web=useRef<WebView<{}>>(null),sequence=useRef(0),writingNow=useRef(false),current=useRef({client,connected});
 const pending=useRef(new Map<number,{resolve:(value:any)=>void;reject:(error:Error)=>void;timer:ReturnType<typeof setTimeout>}>());
 current.current={client,connected};
 const terminals=inventory?.terminals||[],terminal=terminals.find((row:any)=>row.id===selected);
 const work=inventory?.work_items?.find((row:any)=>row.work_item_id===terminal?.work_item_id&&row.machine_id===terminal?.machine_id&&row.capabilities.includes('terminal:read'));
 const view=useMemo(()=>Crypto.randomUUID(),[selected,reload,client,connected,foreground,conversation?.conversation_id]);
 const draft=useProtectedDraft(JSON.stringify(['terminal',draftScope,conversation?.conversation_id,selected]));
 const command=draft.value,setCommand=draft.change;
 const activeView=useRef(view);activeView.current=view;
 const html=useMemo(()=>TERMINAL_DOCUMENT.replace('__SENTRA_VIEW_ID__',view),[view]);

 function cancelPending(){for(const item of pending.current.values()){clearTimeout(item.timer);item.reject(Error('Visualização desconectada.'))}pending.current.clear()}
 useEffect(()=>{setReady(false);setProcessLive(false);cancelPending();return cancelPending},[view]);
 useEffect(()=>{const sub=AppState.addEventListener('change',state=>setForeground(state==='active'));return()=>sub.remove()},[]);
 useEffect(()=>{
  let alive=true;setInventory(null);setSelected('');
  if(client&&connected&&conversation)void client.request({action:'dot_computer_get',conversation_id:conversation.conversation_id})
   .then(value=>{if(alive){const inv=unwrap(value);setInventory(inv);const candidate=inv.terminals?.find((terminal:any)=>inv.work_items?.some((job:any)=>job.work_item_id===terminal.work_item_id&&job.capabilities?.includes('terminal:read')));setSelected(candidate?.id||inv.terminals?.[0]?.id||'');if(inv.terminal_observation?.protocol_version!==1)setNotice('Esta versão do host não oferece o contrato incremental de terminal. Atualize a instância experimental.')}})
   .catch(error=>{if(alive)setNotice(error.message)});
  return()=>{alive=false};
 },[client,connected,conversation?.conversation_id,reload]);

 async function widget(kind:string,fields:Record<string,unknown>,identity=view){
  if(activeView.current!==identity||!web.current)throw Error('Visualização mudou.');
  const id=++sequence.current;
  const packet=JSON.stringify({id,view:identity,kind,terminal_id:selected,...fields}).replace(/</g,'\\u003c');
  return new Promise<any>((resolve,reject)=>{
   const timer=setTimeout(()=>{pending.current.delete(id);reject(Error('Renderização não confirmada. Retome a observação.'))},10000);
   pending.current.set(id,{resolve,reject,timer});
   try{web.current!.injectJavaScript('window.sentraTerminalFrame('+packet+');true;');}
   catch(error){clearTimeout(timer);pending.current.delete(id);reject(error)}
  });
 }

 useEffect(()=>{
  let alive=true,feed:TerminalFeed|undefined;
  if(!client||!connected||!conversation||!terminal||!work||!ready||!foreground||inventory?.terminal_observation?.protocol_version!==1)return;
  const identity=view,scope={machine_id:work.machine_id,work_item_id:work.work_item_id,capability_id:'terminal:read',terminal_id:terminal.id};
  let geometry:number|undefined;
  const read=(action:string,fields:Record<string,unknown>={})=>client.request({action:'dot_computer_read',conversation_id:conversation.conversation_id,
   request:{action,...scope,...fields}}).then(unwrap);
  const checkpoint=async(minimum=0)=>{
   const value=await read('terminal_checkpoint');if(!alive)throw Error('Observação substituída.');
   if(value.available&&value.checkpoint?.cursor>=minimum){await widget('checkpoint',{value},identity);geometry=value.geometry_sequence;return value.checkpoint.cursor as number;}
   return null;
  };
  async function deliver(frame:TerminalDelivery){
   if(!alive)throw Error('Observação substituída.');
   if(frame.reset||(geometry!==undefined&&frame.geometry_sequence!==geometry)){
    const after=await checkpoint(frame.start);if(after!==null){setViewStatus('Checkpoint restaurado.');return {cursor:after}}
    if(geometry!==undefined&&frame.geometry_sequence!==geometry)throw Error('A nova geometria aguarda checkpoint. Retome a observação.');
    setNotice('Histórico parcial: há saída anterior indisponível.');
   }
   geometry=frame.geometry_sequence;
   await widget('output',{frame},identity);
   if(alive){setProcessLive(frame.process_live===true||frame.recoverable===true);setViewStatus(frame.status==='history_restored'?'Histórico restaurado · somente leitura':frame.process_live||frame.recoverable?'Processo em execução':'Processo encerrado · somente leitura');}
  }
  void(async()=>{
   let after=0;
   try{
    try{const restored=await checkpoint();if(restored!==null)after=restored;else setNotice('Checkpoint indisponível: exibindo o histórico incremental.');}
    catch(error:any){if(!alive)return;await widget('reset',{},identity);setNotice('Checkpoint não restaurado: '+error.message+' Histórico parcial.');}
    if(!alive)return;
    feed=new TerminalFeed(terminal.id,cursor=>read('terminal_output',{cursor}) as Promise<TerminalOutputFrame>,deliver,
     error=>{if(alive){setNotice(error.message);setViewStatus('Observação interrompida. Nenhuma entrada foi repetida.')}},after);
    feed.start();
   }catch(error:any){if(alive)setNotice(error.message)}
  })();
  return()=>{alive=false;feed?.stop();cancelPending()};
 },[client,connected,conversation?.conversation_id,terminal?.id,work?.work_item_id,ready,foreground,view,inventory?.terminal_observation?.protocol_version]);

 function confirm(data:string,clearDraft=false){
  const identity=view,session=terminal,job=work,transport=client,submitted=command;
  if(!job?.capabilities?.includes('terminal:write')){setNotice('O WorkItem desta sessão não tem Grant de escrita. Configure no desktop.');return;}
  Alert.alert('Enviar entrada ao terminal?','A entrada será entregue à sessão '+session.name+'.',[
   {text:'Cancelar'},{text:'Enviar',onPress:()=>{void(async()=>{
    if(writingNow.current||activeView.current!==identity||current.current.client!==transport||!current.current.connected||AppState.currentState!=='active')return;
    writingNow.current=true;setWriting(true);
    try{
     if(!data||Buffer.byteLength(data,'utf8')>4096)throw Error('A entrada deve ter no máximo 4096 bytes.');
     const value=await request('dot_computer_action',{conversation_id:conversation.conversation_id,request:{action:'machine_execute',
      machine_id:job.machine_id,work_item_id:job.work_item_id,capability_id:'terminal:write',arguments:{terminal_id:session.id,data}}},true);
     if(value.state!=='SUCCEEDED')throw Error('Entrega não confirmada. Consulte o recibo no desktop.');
     if(activeView.current===identity){if(clearDraft)draft.clear(submitted);setNotice('Entrada entregue. A conclusão do processo ainda não foi comprovada.');}
    }catch(error:any){if(activeView.current===identity)setNotice(error.message)}
    finally{writingNow.current=false;setWriting(false)}
   })()}}]);
 }
 const text=(value:string,size=13)=><Text selectable style={{color:colors.text,fontSize:size,lineHeight:size*1.6}}>{value}</Text>;
 const button=(label:string,press:()=>void,disabled=false)=><Pressable accessibilityRole="button" disabled={disabled} onPress={press}
  style={{padding:12,borderColor:colors.line,borderWidth:1,borderRadius:8,margin:4,opacity:disabled?.45:1}}>{text(label,12)}</Pressable>;
 const writable=!!work?.capabilities?.includes('terminal:write')&&processLive&&connected&&foreground&&!writing;
 return <ScrollView contentContainerStyle={{padding:16,paddingBottom:35}}>{text('Terminal do Dot',26)}
  {text('Saída atualizada continuamente. Entrada passa pelo WorkItem e Grants da sessão.',12)}
  {!conversation&&text('Abra uma conversa para selecionar o escopo autorizado.')}
  {button('Atualizar sessões / retomar observação',()=>setReload(value=>value+1),!connected)}
  <ScrollView horizontal>{terminals.map((row:any)=><View key={row.id}>{button((row.id===selected?'✓ ':'')+row.name,()=>{setSelected(row.id);setNotice('')})}</View>)}</ScrollView>
  {inventory?.terminal_catalog_may_have_more&&text('O catálogo está limitado às 100 sessões mais recentes. Consulte as anteriores no desktop.',11)}
  {terminal&&<><Text style={{color:colors.muted,fontSize:10,marginVertical:8}}>{terminal.id} · {terminal.dot_id||'Dot'}</Text>
   <View style={{height:360,borderColor:colors.line,borderWidth:1,backgroundColor:'#111714'}}>
    <WebView<{}> key={view} ref={web} source={{html}} originWhitelist={['*']} onShouldStartLoadWithRequest={event=>event.url==='about:blank'}
     javaScriptEnabled domStorageEnabled={false} allowFileAccess={false} javaScriptCanOpenWindowsAutomatically={false}
     setSupportMultipleWindows={false} sharedCookiesEnabled={false} thirdPartyCookiesEnabled={false} incognito cacheEnabled={false}
     mixedContentMode="never" onMessage={event=>{try{const value=JSON.parse(event.nativeEvent.data);if(value.view!==activeView.current)return;
      if(value.type==='ready')setReady(true);else if(value.type==='ack'){const item=pending.current.get(value.id);if(item){pending.current.delete(value.id);clearTimeout(item.timer);value.error?item.reject(Error(value.error)):item.resolve(value)}}}catch{setNotice('Mensagem inválida da visualização.')}}}
     onError={()=>{setReady(false);setNotice('O terminal não carregou neste aparelho. Retome a observação.')}}/>
   </View>{text(viewStatus,11)}{!work&&text('Não há WorkItem de leitura autorizado para esta sessão.',12)}
   <TextInput accessibilityLabel="Entrada para a sessão autorizada" value={command} editable={draft.ready} onChangeText={setCommand} autoCapitalize="none" autoCorrect={false}
    multiline placeholder="Comando ou resposta para o processo…" placeholderTextColor={colors.muted}
    style={{color:colors.text,borderColor:colors.line,borderWidth:1,borderRadius:9,padding:13,marginVertical:10}}/>
   {text(draft.status,10)}{button('Enviar texto + Enter',()=>confirm(command+'\r',true),!writable||!draft.ready||!command)}
   <ScrollView horizontal>{[['Ctrl+C','\x03'],['Tab','\t'],['Esc','\x1b'],['↑','\x1b[A'],['↓','\x1b[B'],['Enter','\r']].map(([label,data])=><View key={label}>{button(label,()=>confirm(data),!writable)}</View>)}</ScrollView>
  </>}{!!notice&&<Text accessibilityLiveRegion="polite" style={{color:colors.accent,marginTop:12,fontSize:12,lineHeight:20}}>{notice}</Text>}
 </ScrollView>;
}
