// Real React renderer, synthetic read-only receipt backend, disposable profile.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {parseWorkspaceFixtureArgs}=require('./workspace-fixture-args.cjs');
const fixture=parseWorkspaceFixtureArgs(process.argv.slice(2)),output=path.resolve(fixture.output);
fs.mkdirSync(output,{recursive:true});app.setPath('userData',path.join(output,'profile-'+process.pid));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const channels=value=>value.match(/[\d.]+/g).map(Number);
function contrast(text,button,notice){
 const foreground=channels(text),overlay=channels(button),base=channels(notice),alpha=overlay[3]??1;
 const background=overlay.slice(0,3).map((channel,i)=>channel*alpha+base[i]*(1-alpha));
 const luminance=rgb=>rgb.slice(0,3).map(c=>{const s=c/255;return s<=.04045?s/12.92:((s+.055)/1.055)**2.4}).reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0);
 const a=luminance(foreground),b=luminance(background);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
}
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:780,height:600,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true}});
 const errors=[];win.webContents.on('console-message',event=>{if(event.level==='error')errors.push(event.message)});
 const run=code=>win.webContents.executeJavaScript(code,true);
 const wait=async code=>{const end=Date.now()+10000;while(Date.now()<end){if(await run(code))return;await pause(40)}throw Error('Renderer timeout: '+code)};
 const click=async label=>{
  await wait(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()===${JSON.stringify(label)}&&!b.disabled)`);
  return run(`(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===${JSON.stringify(label)});if(!b||b.disabled)throw Error('Unavailable '+${JSON.stringify(label)});b.click()})()`);
 };
 const capture=async name=>{await pause(100);fs.writeFileSync(path.join(output,name),(await win.webContents.capturePage()).toPNG())};
 try{
  await win.loadFile(path.resolve(fixture.target));await wait("!!document.querySelector('.terminal-input-notice')");
  assert.equal(await run("document.querySelector('details').open"),false);
  await run("document.querySelector('summary').click()");
  assert.equal(await run("document.querySelectorAll('li').length"),3);
  assert.match(await run("document.querySelector('li').textContent"),/outra conexão/);
  assert.equal(await run("document.body.textContent.includes('fixture-pending')"),false);
  const dark=await run("getComputedStyle(document.querySelector('.terminal-input-notice')).backgroundColor");
  const control=()=>run("(()=>{const button=document.querySelector('.terminal-input-notice button'),s=getComputedStyle(button);return {color:s.color,background:s.backgroundColor,disabled:button.disabled}})()");
  const darkControl=await control();assert.equal(darkControl.disabled,false);const darkContrast=contrast(darkControl.color,darkControl.background,dark);assert.ok(darkContrast>=4.5);
  await capture('multiple-dark.png');await win.setContentSize(360,640);
  assert.ok(await run('document.documentElement.scrollWidth<=innerWidth'));
  await run("document.documentElement.dataset.sentraTheme='light'");await pause(100);
  const light=await run("getComputedStyle(document.querySelector('.terminal-input-notice')).backgroundColor");
  assert.notEqual(light,dark,'Fixture did not adopt the real light theme');
  const lightControl=await control();assert.equal(lightControl.disabled,false);const lightContrast=contrast(lightControl.color,lightControl.background,light);assert.ok(lightContrast>=4.5);
  await capture('multiple-light-narrow.png');
  win.webContents.debugger.attach('1.3');
  await win.webContents.debugger.sendCommand('Emulation.setFocusEmulationEnabled',{enabled:true});
  await run("document.querySelector('.terminal-input-notice button').focus()");
  assert.equal(await run("document.activeElement.textContent.trim()"),'Conferir 3 entradas');
  assert.equal(await run('document.hasFocus()'),true);
  await win.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r',unmodifiedText:'\r'});
  await win.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
  win.webContents.debugger.detach();await wait('window.fixture.queries.length===3');
  await wait("document.querySelectorAll('button').length===1");
  assert.match(await run("document.querySelector('[role=status]').textContent"),/1 entrega/);
  assert.equal(await run("document.body.textContent.includes('Continuar digitando')"),false);
  await run('window.fixture.confirmLast()');await click('Consultar confirmação');
  await wait("document.body.textContent.includes('Continuar digitando')");await click('Continuar digitando');
  await wait("!document.querySelector('.terminal-input-notice')");
  assert.equal(await run('window.fixture.physicalWrites'),0);assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({passed:true,scope:'React controls with synthetic read-only receipts; not physical execution',bulk_queries:3,keyboard_bulk_activation:true,uncertain_entry_preserved:true,old_connection_label:true,narrow_no_overflow:true,button_contrast:{dark:darkContrast,light:lightContrast},physical_writes:0},null,2));
  win.destroy();app.exit(0);
 }catch(error){
  try{console.error(await run("JSON.stringify({queries:window.fixture?.queries,active:document.activeElement?.outerHTML,focus:document.hasFocus()})"))}catch{}
  fs.writeFileSync(path.join(output,'error.txt'),String(error.stack||error));win.destroy();app.exit(1)
 }
});
