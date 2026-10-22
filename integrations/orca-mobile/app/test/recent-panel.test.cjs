const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),esbuild=require('esbuild');
const code=esbuild.transformSync(fs.readFileSync(require('node:path').join(__dirname,'../components/recent-panel.ts'),'utf8'),{loader:'ts',format:'cjs'}).code;
const sandbox={exports:{},module:{exports:{}}};vm.runInNewContext(code,sandbox);const {recentMobilePanel}=sandbox.module.exports;
test('a desktop panel is a scoped navigation hint and cannot resurrect an orphan',()=>{
 const profile={recent:[{kind:'terminals',resourceId:'gone'},{kind:'computer',dotId:'other'},{kind:'files'}]};
 assert.equal(recentMobilePanel(profile,{resources:{terminals:[]}},'owner').screen,'files');
 assert.equal(recentMobilePanel({recent:[{kind:'terminals',resourceId:'gone'}]},null,'owner'),null);
 assert.equal(recentMobilePanel({recent:[{kind:'terminals',resourceId:'t'}]},{resources:{terminals:[{id:'t',dot_id:'other'}]}},'owner'),null);
});
test('a known panel retains its conversation identity without sending an action',()=>{
 const value=recentMobilePanel({recent:[{kind:'browser',dotId:'owner',conversationId:'conversation'}]},null,'owner');
 assert.equal(value.screen,'browser');assert.equal(value.conversationId,'conversation');
});
