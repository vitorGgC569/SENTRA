const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),esbuild=require('esbuild');
function load(file){const code=esbuild.transformSync(fs.readFileSync(path.join(__dirname,'../components',file),'utf8'),{loader:'ts',format:'cjs'}).code;const context={module:{exports:{}},exports:{},setTimeout,clearTimeout,console};vm.runInNewContext(code,context);return context.module.exports;}
const {PersistentDrafts}=load('persistent-drafts.ts'),{textChords,framebufferPoint}=load('mobile-input.ts');
function memory(){const values=new Map();return {values,read:async key=>values.get(key)??null,write:async(key,value)=>{assert.ok(Buffer.byteLength(value)<2048);values.set(key,value)},remove:async key=>{values.delete(key)}};}
test('protected draft adapter restores Unicode across process recreation and scopes',async()=>{
 const storage=memory(),store=new PersistentDrafts(storage),text='🔒'.repeat(900)+' terminal \n';await store.write('host-a.chat',text);await store.write('host-b.chat','other');
 assert.equal(await new PersistentDrafts(storage).read('host-a.chat'),text);assert.equal(await store.read('host-b.chat'),'other');
 await store.write('host-a.chat','');assert.equal(await store.read('host-a.chat'),'');assert.equal([...storage.values.keys()].filter(key=>key.startsWith('host-a.chat.')).length,0);
});
test('draft manifest remains readable if a chunk fails and pending writes are coalesced',async()=>{
 const storage=memory(),store=new PersistentDrafts(storage);await store.write('draft','saved');const original=storage.write;
 storage.write=async(key,value)=>{if(value==='fail')throw Error('keychain locked');await original(key,value)};
 await assert.rejects(store.write('draft','fail'),/locked/);assert.equal(await store.read('draft'),'saved');
 await Promise.all(Array.from({length:100},(_,i)=>store.write('draft','latest '+i)));assert.equal(await store.read('draft'),'latest 99');
 await assert.rejects(store.write('draft','a'.repeat(17281)),/excede/);
});
test('keyboard chords contain physical make keys and pointer coordinates stay in frame',()=>{
 assert.deepEqual(JSON.parse(JSON.stringify(textChords('aA!\n'))),[[[30]],[[42],[30]],[[42],[2]],[[28]]]);assert.throws(()=>textChords('🙂'),/mapeada/);assert.throws(()=>textChords('a'.repeat(129)),/128/);
 assert.deepEqual(Array.from(framebufferPoint(-10,600,100,100,1920,1080)),[1,1080]);
});
