// Presentation preferences never carry execution authority or resource intents.
import {restoreLayout,initialLayout} from './layout.js';
export const MODE_KEY='sentra-workspace-presentation-v1';
export function readMode(storage){try{return storage?.getItem(MODE_KEY)==='advanced'?'advanced':'simple'}catch{return 'simple'}}
export function writeMode(storage,mode){if(!['simple','advanced'].includes(mode))throw Error('Modo inválido');try{storage?.setItem(MODE_KEY,mode)}catch{}}
export function layoutStorageKey(scope,mode){return mode==='simple'?scope+':simple-v1':scope}
export function simpleLayout(){return {version:1,tree:{type:'leaf',groupId:'main'},panes:{main:{tabs:[],active:null}},focused:'main'}}
export function restoreModeLayout(storage,scope,mode){return restoreLayout(storage,layoutStorageKey(scope,mode),mode==='simple'?simpleLayout:initialLayout)}
export function sessionTools(tools){return tools.filter(tool=>tool.mode!=='external-app'&&!['antigravity-app'].includes(tool.id)&&['sentra-cli','codex','opencode','grok'].includes(tool.id))}
export const ACCESS_CHOICES={
 read:{title:'Consultar arquivos',description:'Este acesso permite apenas ler arquivos do projeto, sem alterar, excluir ou executar comandos.'},
 ask:{title:'Trabalhar com sua aprovação',description:'Este acesso permite consultar arquivos e pedir sua aprovação para alterações ou comandos no projeto.'},
 none:{title:'Desativar este acesso',description:'Desativa o acesso local a arquivos e comandos desta conversa. Não encerra processos nem altera outras conversas.'},
};
