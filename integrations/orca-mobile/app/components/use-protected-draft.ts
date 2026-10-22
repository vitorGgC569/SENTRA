import {useEffect,useRef,useState} from 'react';
import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import {PersistentDrafts} from './persistent-drafts';
const options={keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY};
export const protectedDrafts=new PersistentDrafts({read:key=>SecureStore.getItemAsync(key,options),write:(key,value)=>SecureStore.setItemAsync(key,value,options),remove:key=>SecureStore.deleteItemAsync(key,options)});
const drafts=protectedDrafts;

export function useProtectedDraft(identity:string){
 const [value,setValue]=useState(''),[status,setStatus]=useState('Carregando rascunho protegido…');
 const current=useRef(identity),storageKey=useRef(''),edit=useRef(0),latest=useRef('');current.current=identity;
 useEffect(()=>{let alive=true;storageKey.current='';edit.current=0;setValue('');setStatus('Carregando rascunho protegido…');
  void(async()=>{try{const key='sentra-draft-'+await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,identity);const stored=await drafts.read(key);if(alive&&current.current===identity){storageKey.current=key;latest.current=stored;setValue(stored);setStatus('Rascunho protegido salvo.')}}catch{if(alive)setStatus('Não foi possível abrir o rascunho protegido.')}})();
  return()=>{alive=false};
 },[identity]);
 function change(next:string){const key=storageKey.current;if(!key||current.current!==identity)return;const ticket=++edit.current;latest.current=next;setValue(next);setStatus('Salvando rascunho protegido…');
  void drafts.write(key,next).then(()=>{if(current.current===identity&&ticket===edit.current)setStatus('Rascunho protegido salvo.')},()=>{if(current.current===identity&&ticket===edit.current)setStatus('Falha ao salvar rascunho. Mantenha o app aberto.');});
 }
 function clear(expected:string){if(current.current===identity&&latest.current===expected)change('');}
 return {value,change,clear,status,ready:storageKey.current!==''};
}
