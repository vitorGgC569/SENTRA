import {test} from 'node:test';
import assert from 'node:assert/strict';
import {emptyProfile,validProfile,rememberPanel,resumablePanel,sessionTitle,taskState,PresentationWriter} from '../src/workspace/continuity.js';
import {stageConversationDraft} from '../src/shell-draft-staging.js';
test('resume selects existing references without creating or rebinding a resource',()=>{
 const p=rememberPanel(emptyProfile(),{id:'terminals:gone',kind:'terminals',resourceId:'gone'});
 const good=rememberPanel(p,{id:'files:a',kind:'files',resourceId:'a.txt'});
 assert.ok(validProfile(good));assert.equal(resumablePanel(p,{resources:{terminals:[]}}),null);
 assert.equal(resumablePanel(good,{resources:{terminals:[]}}).resourceId,'a.txt');
 assert.equal(sessionTitle({id:'t',name:'Dot_agent_sentra'}, {t:'Revisando login'}),'Revisando login');
 assert.equal(sessionTitle({id:'t',name:'SENTRA CLI'}, {},'Oxta'),'Trabalho de Oxta');
});
test('delivery, uncertainty, execution and task completion have one truthful primary state',()=>{
 assert.equal(taskState({status:'completed'}).label,'Aguardando confirmação');
 assert.equal(taskState({work_item_state:'RUNNING',operation_state:'SUCCEEDED'}).label,'Em execução');
 assert.equal(taskState({work_item_state:'SUCCEEDED',operation_state:'UNCERTAIN'}).label,'Aguardando confirmação');
 assert.equal(taskState({handoff_id:'h',operation_state:'SUCCEEDED'}).label,'Aguardando confirmação');
 assert.equal(taskState({status:'failed'}).label,'Falhou');
 assert.equal(taskState({status:'expired'}).label,'Expirado');
 assert.equal(taskState({status:'cancelled'}).label,'Cancelado');
 assert.equal(taskState({status:'SUCCEEDED',lifecycle:{stage:'verified',evidence_verified:true}}).label,'Concluído e verificado');
 assert.equal(taskState({status:'FAILED',lifecycle:{stage:'verified',evidence_verified:true}}).label,'Falhou');
});
test('presentation writer serializes newest state and freezes a cross-window conflict',async()=>{
 const calls=[],errors=[];let release;const writer=new PresentationWriter((p,r)=>{calls.push({p,r});return new Promise(resolve=>release=resolve)},0,e=>errors.push(e));
 writer.schedule(emptyProfile());const pending=writer.flush();writer.schedule({...emptyProfile(),started:true});
 assert.equal(calls.length,1);release({saved:true,revision:1});await pending;await new Promise(r=>setTimeout(r,0));
 assert.equal(calls.length,2);assert.equal(calls[1].r,1);assert.equal(calls[1].p.started,true);
 release({saved:false,conflict:true,revision:2});await new Promise(r=>setTimeout(r,0));
 writer.schedule(emptyProfile());await writer.flush();assert.equal(calls.length,2);assert.equal(errors.length,1);writer.close();
});
test('first-use suggestion only stages a draft and never replaces pending or typed work',()=>{
 const rows=new Map(),s={getItem:k=>rows.get(k),setItem:(k,v)=>rows.set(k,v)},c={project_id:'p',conversation_id:'a'};
 assert.equal(stageConversationDraft(s,c,'Conhecer o projeto'),true);
 assert.equal(stageConversationDraft(s,c,'Outra tarefa'),false);
 assert.equal(JSON.parse(rows.get('sentra_shell_draft:p:a')).content,'Conhecer o projeto');
 s.setItem('sentra_shell_draft:p:b',JSON.stringify({content:'',pending:{request_key:'uncertain'}}));
 assert.equal(stageConversationDraft(s,{...c,conversation_id:'b'},'new'),false);
});


test('clean layout adopts a newer host revision without creating resources',()=>{
 const w=new PresentationWriter(async()=>{throw Error('Must not write while observing')},2);
 const profile=emptyProfile();assert.equal(w.observe({revision:3,profile}),profile);
 assert.equal(w.revision,3);assert.equal(w.observe({revision:2,profile}),null);w.close();
});
test('remote layout cannot overwrite unsaved local changes or cross an in-flight save',()=>{
 const errors=[],w=new PresentationWriter(async()=>{},1,e=>errors.push(e.message));
 w.schedule(rememberPanel(emptyProfile(),{id:'activity',kind:'activity'}));
 assert.equal(w.observe({revision:2,profile:emptyProfile()}),null);
 assert.equal(w.conflict,true);assert.ok(w.pending);assert.equal(errors.length,1);w.close();
 const other=new PresentationWriter(async()=>{},1);other.busy=true;
 assert.equal(other.observe({revision:2,profile:emptyProfile()}),null);assert.equal(other.conflict,true);other.close();
});
