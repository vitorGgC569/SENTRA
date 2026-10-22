'use strict';
// Disposable application renderer test, no installed profile or external page.
const {app,BrowserWindow,ipcMain}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const argument=process.argv.find(value=>value.startsWith('--terminal-test='));
const directory=argument&&argument.slice('--terminal-test='.length);
if(!directory||!path.isAbsolute(directory))throw Error('Explicit isolated fixture directory required');
app.setPath('userData',path.join(directory,'profile'));
const fixture=JSON.parse(fs.readFileSync(path.join(directory,'fixture.json'),'utf8'));
const waiters=new Map(),messages=[];let win,server,hits=0;
const timer=setTimeout(()=>{console.error('Offline terminal renderer timed out');app.exit(5)},25000);
ipcMain.on('terminal-message',(event,raw)=>{
 if(event.sender!==win?.webContents)return;
 const message=JSON.parse(raw);messages.push(message);
 const key=message.type==='ready'?'ready':message.id;
 const waiter=waiters.get(key);if(waiter){waiters.delete(key);waiter(message)};
});
const message=id=>new Promise(resolve=>waiters.set(id,resolve));
app.whenReady().then(async()=>{
 try{
  server=http.createServer((_request,response)=>{hits++;response.end('not expected')});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,width:800,height:420,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true,
   partition:'mobile-terminal-qa-'+process.pid,preload:path.join(__dirname,'terminal-preload.cjs')}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  const ready=message('ready');await win.loadFile(path.join(directory,'terminal.html'));await ready;
  assert.equal(await win.webContents.executeJavaScript("typeof require==='undefined'&&typeof process==='undefined'"),true);
  const send=async(id,kind,fields)=>{const ack=message(id);await win.webContents.executeJavaScript('window.sentraTerminalFrame('+JSON.stringify({id,view:'qa-terminal',terminal_id:'t',kind,...fields})+')');return await ack;};
  assert.equal((await send(1,'output',{frame:fixture.raw})).error,undefined);
  await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  assert.match(await win.webContents.executeJavaScript("document.querySelector('.xterm-rows').textContent"),/UTF8 🐋/);
  const initialColor=await win.webContents.executeJavaScript("getComputedStyle([...document.querySelectorAll('.xterm-rows span')].find(s=>s.textContent.includes('UTF8'))).color");
  assert.notEqual(initialColor,'rgb(225, 238, 229)');
  assert.equal((await send(2,'checkpoint',{value:fixture.checkpoint})).error,undefined);
  assert.equal((await send(3,'output',{frame:fixture.next})).error,undefined);
  await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  const visible=await win.webContents.executeJavaScript("document.querySelector('.xterm-rows').textContent");
  assert.match(visible,/NORMALZ/);assert.doesNotMatch(visible,/TUI/);
  const savedColor=await win.webContents.executeJavaScript("[...document.querySelectorAll('.xterm-rows span')].filter(s=>s.textContent==='Z').map(s=>getComputedStyle(s).color)");
  assert.ok(savedColor.includes(initialColor),JSON.stringify(savedColor));
  const networkBlocked=await win.webContents.executeJavaScript(`fetch('http://127.0.0.1:${server.address().port}/probe').then(()=>false,()=>true)`);
  assert.equal(networkBlocked,true);assert.equal(hits,0);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('textarea').readOnly"),true);
  assert.ok(messages.every(m=>['ready','ack'].includes(m.type)));
  fs.writeFileSync(path.join(directory,'terminal.png'),(await win.webContents.capturePage()).toPNG());
  fs.writeFileSync(path.join(directory,'result.json'),JSON.stringify({passed:true,normal_buffer_restored:true,saved_color_restored:true,
   unicode_rendered:true,query_input_forwarded:false,network_blocked:true,render_acknowledgements:3}));
  clearTimeout(timer);server.close();app.quit();
 }catch(error){console.error(error.stack);clearTimeout(timer);server?.close();app.exit(6)}
});
