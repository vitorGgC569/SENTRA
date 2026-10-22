import React,{useEffect,useRef,useState} from 'react';
import {AppState,Image,Pressable,Text,TextInput,View} from 'react-native';
import {framebufferPoint,textChords} from './mobile-input';

export function ComputerControls({frame,owned,input,refresh,colors}:{frame:any;owned:boolean;input:(arguments_:any)=>Promise<any>;refresh:()=>Promise<void>;colors:Record<string,string>}){
 const [text,setText]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
 const current=useRef({owned,busy:false,active:true,epoch:0}),geometry=useRef({width:1,height:1}),gesture=useRef<{points:number[][];epoch:number}|null>(null);
 current.current.owned=owned;
 useEffect(()=>{current.current.active=AppState.currentState==='active';const sub=AppState.addEventListener('change',state=>{current.current.epoch++;current.current.active=state==='active';gesture.current=null});return()=>{current.current.active=false;current.current.epoch++;sub.remove()}},[]);
 function valid(epoch:number){return current.current.active&&current.current.owned&&epoch===current.current.epoch;}
 async function run(actions:any[],submitted?:string){const epoch=current.current.epoch;if(!valid(epoch)||current.current.busy)return;current.current.busy=true;setBusy(true);
  try{for(const action of actions){if(!valid(epoch))throw Error('Entrada interrompida porque o contexto mudou.');await input(action)}if(valid(epoch)){if(submitted!==undefined)setText(value=>value===submitted?'':value);setNotice('Entrada entregue.');await refresh()}}
  catch(error:any){if(valid(epoch))setNotice(error.message+' Nenhuma entrada será repetida automaticamente.')}
  finally{current.current.busy=false;if(current.current.active)setBusy(false)}
 }
 function point(event:any){return framebufferPoint(event.nativeEvent.locationX,event.nativeEvent.locationY,geometry.current.width,geometry.current.height,frame.source_width,frame.source_height);}
 const button=(label:string,action:()=>void)=><Pressable accessibilityRole="button" disabled={!owned||busy} onPress={action} style={{padding:12,borderColor:colors.line,borderWidth:1,borderRadius:8,margin:4,opacity:owned&&!busy?1:.45}}><Text style={{color:colors.text,fontSize:12}}>{label}</Text></Pressable>;
 return <View>{frame?.image_base64&&<View onLayout={event=>geometry.current=event.nativeEvent.layout}
  onStartShouldSetResponder={()=>owned&&!current.current.busy} onMoveShouldSetResponder={()=>owned&&!current.current.busy}
  onResponderGrant={event=>{gesture.current={points:[point(event)],epoch:current.current.epoch}}}
  onResponderMove={event=>{const value=gesture.current;if(!value||!valid(value.epoch))return;const next=point(event);if(value.points.length<31)value.points.push(next);else value.points[30]=next}}
  onResponderRelease={event=>{const value=gesture.current;gesture.current=null;if(!value||!valid(value.epoch))return;const last=point(event),first=value.points[0];value.points.push(last);void run([Math.hypot(last[0]-first[0],last[1]-first[1])>5?{action:'input.drag',points:value.points}:{action:'input.tap',x:last[0],y:last[1]}])}}
  onResponderTerminationRequest={()=>true} onResponderTerminate={()=>{gesture.current=null}}>
  <Image accessibilityLabel="Tela do Dot · toque para clicar ou arraste para mover" source={{uri:'data:image/png;base64,'+frame.image_base64}} resizeMode="contain" style={{width:'100%',aspectRatio:frame.source_width/frame.source_height,backgroundColor:'#101612'}}/>
 </View>}
 <Text style={{color:colors.muted,fontSize:11,lineHeight:18,marginVertical:10}}>Toque e arraste usam gestos atômicos; o host libera o botão mesmo se a resposta se perder. Teclado usa posições físicas US do convidado.</Text>
 <TextInput accessibilityLabel="Texto para o teclado remoto" value={text} onChangeText={setText} editable={owned&&!busy} autoCapitalize="none" autoCorrect={false} maxLength={128} placeholder="Texto para a máquina autorizada" placeholderTextColor={colors.muted} style={{color:colors.text,borderColor:colors.line,borderWidth:1,padding:12,borderRadius:8}}/>
 {button('Enviar texto ao teclado',()=>{try{void run(textChords(text).map(keys=>({action:'input.chord',keys})),text)}catch(error:any){setNotice(error.message)}})}
 <View style={{flexDirection:'row',flexWrap:'wrap'}}>{([['Enter',[[28]]],['Tab',[[15]]],['Esc',[[1]]],['⌫',[[14]]],['↑',[[224,72]]],['↓',[[224,80]]],['←',[[224,75]]],['→',[[224,77]]],['Ctrl+C',[[29],[46]]]] as const).map(([label,keys])=><View key={label}>{button(label,()=>void run([{action:'input.chord',keys}]))}</View>)}</View>
 {!!notice&&<Text accessibilityLiveRegion="polite" style={{color:colors.accent,fontSize:12,marginTop:10}}>{notice}</Text>}
 </View>;
}
