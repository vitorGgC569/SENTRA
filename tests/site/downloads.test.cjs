const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../site/downloads.js'),'utf8');
const base='https://github.com/vitorGgC569/SENTRA/releases/';
function android(){return {url:base+'download/mobile-preview-1/SENTRA.apk',release:base+'tag/mobile-preview-1',sha256:'a'.repeat(64),version:'mobile-preview-1',size:1048576};}
async function render(data,fail=false){
 const elements=new Map();
 const document={getElementById(id){if(!elements.has(id))elements.set(id,{hidden:true,textContent:''});return elements.get(id);}};
 const context=vm.createContext({document,URL,Date,fetch:async()=>{if(fail)throw Error('offline');return {ok:true,json:async()=>data};}});
 vm.runInContext(source,context);await new Promise(resolve=>setImmediate(resolve));return id=>document.getElementById(id);
}
test('verified Android release uses English labels and keeps iOS unavailable',async()=>{
 const get=await render({schema:1,generated_at:'2026-10-23T12:00:00Z',android:android(),ios:null});
 assert.equal(get('android-status').textContent,'Preview available');assert.equal(get('android-download').hidden,false);
 assert.equal(get('android-download').href,android().url);assert.equal(get('ios-download').hidden,true);
 assert.match(get('catalog-status').textContent,/^Availability updated on /);
});
test('unavailable Android has an English preparation state',async()=>{
 const get=await render({schema:1,generated_at:'2026-10-23',android:null,ios:null});
 assert.equal(get('android-status').textContent,'Build in preparation');assert.equal(get('android-download').hidden,true);
});
test('foreign download URL stays hidden',async()=>{
 const get=await render({schema:1,generated_at:'2026-10-23',android:{...android(),url:'https://example.com/SENTRA.apk'}});
 assert.equal(get('android-download').hidden,true);
});
test('official TestFlight channel uses English labels',async()=>{
 const get=await render({schema:1,generated_at:'2026-10-23',ios:{url:'https://testflight.apple.com/join/Abc123'}});
 assert.equal(get('ios-download').hidden,false);assert.equal(get('ios-status').textContent,'Available on TestFlight');
});
test('offline catalog provides an English fallback without a download',async()=>{
 const get=await render(null,true);assert.equal(get('android-status').textContent,'Browse releases');
 assert.match(get('catalog-status').textContent,/^Could not load the catalog/);assert.equal(get('android-download').hidden,true);
});

test('older Windows installer remains clearly marked as preview',async()=>{
 const windows={release:base+'tag/installer-preview-1',metadata:base+'download/installer-preview-1/windows-preview.json',sha256:'a'.repeat(64),size:3176796914,version:'installer-preview-1',parts:[{}, {}, {}],current_interface:false};
 const get=await render({schema:1,generated_at:'2026-10-24',windows});
 assert.equal(get('windows-status').textContent,'Older installer preview');
 assert.equal(get('windows-release').href,windows.release);assert.equal(get('windows-verification').hidden,false);
 assert.match(get('windows-description').textContent,/predates the current local interface/);
 assert.match(get('windows-version').textContent,/3 parts/);
});

test('foreign Windows metadata cannot replace the static release link',async()=>{
 const get=await render({schema:1,generated_at:'2026-10-24',windows:{release:base+'tag/x',metadata:'https://example.com/proof',sha256:'a'.repeat(64),size:10}});
 assert.equal(get('windows-verification').hidden,true);assert.equal(get('windows-release').href,undefined);
});
