import React,{useState} from 'react';
import {Pressable,Text,View} from 'react-native';
import type {Device} from '@sentra/mobile-transport';
export function ScopeNavigator({devices,current,select,colors,disabled}:{devices:Device[];current:Device|null;select:(device:Device)=>void;colors:Record<string,string>;disabled:boolean}){
 const [host,setHost]=useState(''),[project,setProject]=useState(''),[space,setSpace]=useState('');
 const hostKey=host||current?.public_key||devices[0]?.public_key;
 const onHost=devices.filter(d=>d.public_key===hostKey),projectId=onHost.some(d=>d.scope.project_id===project)?project:onHost.find(d=>d.device_id===current?.device_id)?.scope.project_id||onHost[0]?.scope.project_id;
 const inProject=onHost.filter(d=>d.scope.project_id===projectId),spaceId=inProject.some(d=>d.scope.space_id===space)?space:inProject.find(d=>d.device_id===current?.device_id)?.scope.space_id||inProject[0]?.scope.space_id;
 const button=(label:string,active:boolean,action:()=>void)=><Pressable accessibilityRole="button" accessibilityState={{selected:active}} disabled={disabled} onPress={action} style={{padding:11,borderWidth:1,borderColor:active?colors.accent:colors.line,borderRadius:8,marginVertical:3}}><Text style={{color:colors.text,fontSize:12}}>{label}</Text></Pressable>;
 return <View style={{marginVertical:12}}><Text style={{color:colors.muted,fontSize:12}}>Máquina → Projeto → Space → Dot · escopos aprovados neste aparelho</Text>
  {[...new Set(devices.map(d=>d.public_key))].map(key=>{const row=devices.find(d=>d.public_key===key)!;return <View key={key}>{button('Máquina · '+new URL(row.endpoint).hostname,hostKey===key,()=>{setHost(key);setProject('');setSpace('')})}</View>})}
  {[...new Set(onHost.map(d=>d.scope.project_id))].map(id=><View key={id}>{button('Projeto · '+id,projectId===id,()=>{setProject(id);setSpace('')})}</View>)}
  {[...new Set(inProject.map(d=>d.scope.space_id))].map(id=><View key={id}>{button('Space · '+id,spaceId===id,()=>setSpace(id))}</View>)}
  {inProject.filter(d=>d.scope.space_id===spaceId).map(d=><View key={d.device_id}>{button('Abrir Dot · '+d.scope.dot_id,current?.device_id===d.device_id,()=>select(d))}</View>)}
 </View>;
}
