// Adapted from ORCA MobileNativeChatCardHeaderAction.tsx at 70b2197c.
// Copyright (c) 2026 Lovecast Inc. MIT; see ../THIRD_PARTY_LICENSES/ORCA.txt.
import {Keyboard,Pressable,StyleSheet} from 'react-native';
import {ChevronDown,X} from 'lucide-react-native';

export function CardHeaderAction({onCancel,onCollapse,disabled,color,label}:{
 onCancel?:()=>Promise<unknown>;onCollapse?:()=>void;disabled?:boolean;color:string;label?:string;
}){
 if(!onCancel&&!onCollapse)return null;
 const Icon=onCancel?X:ChevronDown;
 return <Pressable accessibilityLabel={label||(onCancel?'Cancelar operação':'Recolher')}
  accessibilityState={onCancel?undefined:{expanded:true}} hitSlop={8} style={styles.action}
  disabled={disabled} onPress={()=>{if(onCancel){void onCancel();return;}Keyboard.dismiss();onCollapse?.()}}>
  <Icon size={16} color={color}/>
 </Pressable>;
}
const styles=StyleSheet.create({action:{width:28,height:28,alignItems:'center',justifyContent:'center'}});
