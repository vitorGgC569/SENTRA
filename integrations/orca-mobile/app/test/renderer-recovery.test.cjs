const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),esbuild=require('esbuild');
const code=esbuild.transformSync(fs.readFileSync(path.join(__dirname,'../components/renderer-recovery.ts'),'utf8'),{loader:'ts',format:'cjs'}).code;
const context={module:{exports:{}}};vm.runInNewContext(code,context);const {RendererRecovery}=context.module.exports;
test('lost render acknowledgements replace at most two views and reject stale callbacks',()=>{
 const recovery=new RendererRecovery();recovery.select('session','view1');assert.equal(recovery.restart('view1'),true);
 assert.equal(recovery.restart('view1'),false);recovery.select('session','view2');assert.equal(recovery.restart('view1'),false);
 assert.equal(recovery.restart('view2'),true);recovery.select('session','view3');assert.equal(recovery.restart('view3'),false);
 assert.equal(recovery.count,2);recovery.select('explicit-new-observation','view4');assert.equal(recovery.restart('view4'),true);
});
