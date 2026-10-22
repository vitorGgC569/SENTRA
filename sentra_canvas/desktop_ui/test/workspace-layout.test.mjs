import {test} from 'node:test';
import assert from 'node:assert/strict';
import {initialLayout,validateLayout,restoreLayout,saveLayout,moveTab,leaf,removeGroup,dropTabAtEdge,dropEdge} from '../src/workspace/layout.js';
test('layout storage is scoped and rejects malformed trees',()=>{const data=new Map(),store={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};const a=initialLayout();a.panes.main.active='files';saveLayout(store,'alice/dot',a);assert.equal(restoreLayout(store,'alice/dot').panes.main.active,'files');assert.equal(restoreLayout(store,'bob/dot').panes.main.active,'terminals');assert.equal(validateLayout({...a,tree:{type:'split',ratio:NaN}}),false);assert.equal(validateLayout({...a,tree:{type:'split',direction:'horizontal',ratio:.5,first:leaf('main'),second:leaf('main')}}),false);});
test('moving a tab changes only presentation and collapses groups safely',()=>{let state=initialLayout();state.tree={type:'split',direction:'horizontal',ratio:.5,first:state.tree,second:leaf('two')};state.panes.two={tabs:[],active:null};const moved=moveTab(state,'main','two','terminals');assert.equal(validateLayout(moved),true);assert.equal(moved.panes.two.active,'terminals');assert.equal(moved.panes.main.tabs.some(t=>t.id==='terminals'),false);assert.deepEqual(removeGroup(moved.tree,'two'),leaf('main'));assert.equal(state.panes.two.tabs.length,0);});
test('file tabs retain exact conversation and execution workspace identities',()=>{const state=initialLayout(),tab={id:'file-task',kind:'files',resourceId:'sample.txt',dotId:'dot',conversationId:'conversation',executionWorkspaceId:'xws-git-tree'};state.panes.main={tabs:[tab],active:tab.id};assert.equal(validateLayout(state),true);const data=new Map(),store={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};saveLayout(store,'scope',state);assert.deepEqual(restoreLayout(store,'scope').panes.main.tabs[0],tab);tab.conversationId={};assert.equal(validateLayout(state),false);});

test('edge drop moves the exact existing tab in one valid layout transaction',()=>{
 for(const edge of ['left','right','top','bottom']){
  const state=initialLayout(),tab=state.panes.main.tabs[0],next=dropTabAtEdge(state,'main','main',tab.id,edge,'split');
  assert.equal(validateLayout(next),true);assert.equal(next.panes.split.tabs[0],tab);assert.equal(next.focused,'split');
  assert.equal(next.tree.direction,['left','right'].includes(edge)?'horizontal':'vertical');assert.equal(state.panes.main.tabs.length,7);
 }
 const state=initialLayout();assert.equal(dropTabAtEdge(state,'foreign','main','map','left','split'),state);
 const rect={left:0,top:0,right:500,bottom:300,width:500,height:300};
 assert.equal(dropEdge(rect,1,100),'left');assert.equal(dropEdge(rect,490,100),'right');assert.equal(dropEdge(rect,250,1),'top');assert.equal(dropEdge(rect,250,290),'bottom');assert.equal(dropEdge(rect,250,150),null);
});
