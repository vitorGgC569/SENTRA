// Own Electron fixture/profile only. Does not load the installed app or its data.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const url=process.argv[2],output=path.resolve(process.argv[3]);
fs.mkdirSync(output,{recursive:false});app.setPath('userData',path.join(output,'profile'));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1150,height:780,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true}});
 const run=code=>win.webContents.executeJavaScript(code,true);
 const wait=async code=>{const deadline=Date.now()+15000;while(Date.now()<deadline){if(await run('Boolean('+code+')'))return;await pause(80)}throw Error('Timed out: '+code)};
 const click=label=>run(`(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===${JSON.stringify(label)}||b.getAttribute('aria-label')===${JSON.stringify(label)});if(!b||b.disabled)throw Error('Missing/enabled control: '+${JSON.stringify(label)});b.click()})()`);
 async function type(text){await run("document.querySelector('.cm-content').focus()");win.webContents.sendInputEvent({type:'keyDown',keyCode:'A',modifiers:['control']});win.webContents.sendInputEvent({type:'keyUp',keyCode:'A',modifiers:['control']});win.webContents.insertText(text);await pause(100)}
 async function screenshot(name){await pause(100);fs.writeFileSync(path.join(output,name),(await win.webContents.capturePage()).toPNG())}
 try{
  await win.loadURL(url);await wait("document.querySelector('.sw-code-lines')");await click('Editar');await wait("document.querySelector('.cm-content')");
  await type('draft after restart ação 🦊\n');await wait("window.fixture.hostDraft().draft?.content==='draft after restart ação 🦊\\n'");
  await screenshot('editor-dark.png');await win.reload();await wait("document.querySelector('.cm-content')?.textContent.includes('draft after restart')");
  assert.equal(await run('window.fixture.effects()'),0);
  await run("window.fixture.setFile('edited by another Dot\\n');window.dispatchEvent(new Event('focus'))");await wait("document.querySelector('.sw-file-conflict')");
  assert.equal(await run("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Salvar').disabled"),true);
  await screenshot('editor-conflict.png');
  await run("document.querySelector('.sw-file-conflict input').click()");await click('Manter meu texto sobre esta versão');
  await wait("!document.querySelector('.sw-file-conflict')");
  await click('Salvar');await wait("document.body.textContent.includes('fixture lost acknowledgement')");assert.equal(await run('window.fixture.effects()'),1);
  await win.reload();await wait("[...document.querySelectorAll('button')].some(b=>b.textContent==='Consultar sem reenviar')");
  await click('Consultar sem reenviar');await wait("document.body.textContent.includes('Arquivo salvo e conferido.')");
  assert.equal(await run('window.fixture.effects()'),1);assert.equal(await run('window.fixture.hostDraft().draft'),null);
  await click('Editar');await wait("document.querySelector('.cm-content')");await type('second change\n');
  await wait("window.fixture.hostDraft().draft?.content==='second change\\n'");
  await run("document.documentElement.dataset.sentraTheme='light'");await screenshot('editor-light.png');
  const colors=await run("({bg:getComputedStyle(document.querySelector('.cm-editor')).backgroundColor,text:getComputedStyle(document.querySelector('.cm-editor')).color})");
  assert.equal(colors.bg,'rgb(255, 255, 255)');assert.equal(colors.text,'rgb(10, 10, 10)');
  win.webContents.sendInputEvent({type:'keyDown',keyCode:'S',modifiers:['control']});win.webContents.sendInputEvent({type:'keyUp',keyCode:'S',modifiers:['control']});
  await wait("window.fixture.effects()===2 && window.fixture.hostDraft().draft===null");
  await win.setContentSize(600,700);await pause(100);
  const narrow=await run('({width:innerWidth,scroll:document.documentElement.scrollWidth})');assert.ok(narrow.scroll<=narrow.width);
  fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({passed:true,scope:'simulated host; real renderer',draft_restored:true,conflict_preserved:true,lost_ack_not_replayed:true,keyboard_save:true,physical_effects_simulated:2,colors,narrow},null,2));
  win.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(output,'error.txt'),String(error.stack||error));console.error(error);win.destroy();app.exit(1)}
});
