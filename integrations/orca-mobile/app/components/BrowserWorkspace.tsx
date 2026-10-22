import React,{useEffect,useState} from 'react';
import {Image,Pressable,ScrollView,Text,TextInput,View} from 'react-native';

export function BrowserWorkspace({request,conversation,dotId,colors}:{request:(action:string,fields?:Record<string,unknown>,effect?:boolean)=>Promise<any>;conversation:any;dotId:string;colors:Record<string,string>}){
 const [inventory,setInventory]=useState<any>(null),[selected,setSelected]=useState(''),[session,setSession]=useState(''),[sessions,setSessions]=useState<any[]>([]),[url,setUrl]=useState(''),[observation,setObservation]=useState<any>(null),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
 const actor=inventory?.dots?.find((d:any)=>d.dot_id===dotId),machine=inventory?.machines?.find((m:any)=>m.kind==='browser'&&m.agent_id===actor?.agent_id);
 const jobs=inventory?.work_items?.filter((w:any)=>w.machine_id===machine?.machine_id&&w.capabilities.includes('browser:operate'))||[];
 const work=jobs.find((w:any)=>w.work_item_id===selected)||jobs[0];
 async function inventoryRead(){if(!conversation)return;try{setInventory(await request('dot_computer_get',{conversation_id:conversation.conversation_id}));setNotice('')}catch(e:any){setNotice(e.message)}}
 useEffect(()=>{void inventoryRead()},[conversation?.conversation_id]);
 async function run(action:string){if(busy||!work)return;setBusy(true);try{const args={action,...(!['open','session.list'].includes(action)?{session_id:session}:{}),...(action==='open'?{profile:machine.profiles[0].name}:{}),...(action==='navigate'?{url}:{}),...(action==='session.list'?{limit:50}:{}),...(action==='observe'?{include_image:true}:{})};const value=await request('dot_computer_action',{conversation_id:conversation.conversation_id,request:{action:'machine_execute',machine_id:machine.machine_id,work_item_id:work.work_item_id,capability_id:'browser:operate',arguments:args}},true);if(value.state!=='SUCCEEDED')throw Error('Operação não concluída: '+value.state);const result=value.evidence?.payload||value.evidence||{};if(result.sessions)setSessions(result.sessions);if(result.session_id)setSession(result.session_id);if(result.observation_id)setObservation(result);setNotice('Operação confirmada.');}catch(e:any){setNotice(e.message)}finally{setBusy(false)}}
 const text=(value:string,size=13)=><Text selectable style={{color:colors.text,fontSize:size,lineHeight:size*1.7}}>{value}</Text>;
 const button=(label:string,onPress:()=>void,disabled=false)=><Pressable accessibilityRole="button" disabled={busy||disabled} onPress={onPress} style={{padding:13,borderWidth:1,borderColor:colors.line,borderRadius:9,marginVertical:6,opacity:busy||disabled?.45:1}}>{text(label)}</Pressable>;
 return <ScrollView contentContainerStyle={{padding:22}}>{text('Navegador do Dot',28)}{text('A rede, o trabalho e as permissões são os mesmos do desktop. Esta tela não usa os cookies dos modelos Web.',12)}
  {!conversation?text('Abra uma conversa para selecionar seu escopo.'):button('Consultar serviços',()=>void inventoryRead())}
  {jobs.map((w:any)=><View key={w.work_item_id}>{button((w.work_item_id===work?.work_item_id?'✓ ':'')+w.objective,()=>{setSelected(w.work_item_id);setSession('');setSessions([]);setObservation(null)})}</View>)}
  {!work&&text('Nenhum WorkItem de navegador autorizado neste Dot. Configure no desktop.',12)}
  {button('Consultar sessões existentes',()=>void run('session.list'),!work)}
  {sessions.map(s=><View key={s.session_id||s.id}>{button((session===(s.session_id||s.id)?'✓ ':'')+(s.title||s.url||s.session_id||s.id),()=>{setSession(s.session_id||s.id);setObservation(null)})}</View>)}
  {button('Abrir nova sessão no perfil configurado',()=>void run('open'),!work||!machine?.profiles?.length)}
  {!!session&&<>{text('Sessão: '+session,10)}<TextInput accessibilityLabel="Endereço no navegador autorizado" autoCapitalize="none" autoCorrect={false} placeholder="https://…" placeholderTextColor={colors.muted} value={url} onChangeText={setUrl} style={{color:colors.text,borderColor:colors.line,borderWidth:1,padding:15,borderRadius:9,marginVertical:12}}/>{button('Navegar',()=>void run('navigate'),!url)}{button('Observar página',()=>void run('observe'))}</>}
  {!!notice&&<Text accessibilityLiveRegion="polite" style={{color:colors.accent,fontSize:12,marginVertical:15}}>{notice}</Text>}
  {observation?.viewport_image?.mime==='image/jpeg'&&observation.viewport_image.base64?.length<=1400000&&<Image accessibilityLabel="Página observada no navegador do Dot" source={{uri:'data:image/jpeg;base64,'+observation.viewport_image.base64}} style={{width:'100%',aspectRatio:1.6,marginVertical:18}} resizeMode="contain"/>}{observation&&<View style={{padding:18,borderWidth:1,borderColor:colors.line,borderRadius:10}}>{text(observation.title||'Página observada',18)}{text(observation.semantic_summary||'Nenhum elemento interativo observado.',12)}</View>}
 </ScrollView>;
}
