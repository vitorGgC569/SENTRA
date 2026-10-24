'use strict';
function releaseLink(value){try{const u=new URL(value);return u.protocol==='https:'&&u.hostname==='github.com'&&u.pathname.startsWith('/vitorGgC569/SENTRA/releases/')}catch{return false}}
async function load(){const state=document.getElementById('catalog-status');try{
 const r=await fetch('./downloads.json',{cache:'no-store'});if(!r.ok)throw Error('catalog');const data=await r.json();if(data.schema!==1)throw Error('schema');
 const a=data.android;if(a&&releaseLink(a.url)&&releaseLink(a.release)&&a.url.endsWith('.apk')&&/^[a-f0-9]{64}$/.test(a.sha256)){
  const button=document.getElementById('android-download');button.href=a.url;button.hidden=false;
  const notes=document.getElementById('android-release');notes.href=a.release;notes.hidden=false;
  document.getElementById('android-status').textContent='Preview available';document.getElementById('android-description').textContent='Standalone APK for evaluation on your local network. Read the release notes before installing.';
  document.getElementById('android-version').textContent=a.version+' · '+(a.size/1024/1024).toFixed(1)+' MB';
 }else document.getElementById('android-status').textContent='Build in preparation';
 const ios=data.ios;try{const u=new URL(ios?.url);if(u.protocol==='https:'&&u.hostname==='testflight.apple.com'&&/^\/join\/[a-zA-Z0-9]+$/.test(u.pathname)){
  const b=document.getElementById('ios-download');b.href=u.href;b.hidden=false;document.getElementById('ios-status').textContent='Available on TestFlight';document.getElementById('ios-description').textContent='Install the preview through the official TestFlight channel.';
 }}catch{}
 const w=data.windows;
 if(w&&releaseLink(w.release)&&releaseLink(w.metadata)&&/^[a-f0-9]{64}$/.test(w.sha256)&&Number.isSafeInteger(w.size)&&w.size>0){
  const notes=document.getElementById('windows-release');notes.href=w.release;
  const proof=document.getElementById('windows-verification');proof.href=w.metadata;proof.hidden=false;
  document.getElementById('windows-status').textContent=w.current_interface===true?'Current-interface preview':'Older installer preview';
  document.getElementById('windows-description').textContent=w.current_interface===true?'Preview installer containing the reviewed interface. Stable-release qualification remains pending.':'This published installer predates the current local interface. Read its release notes before testing.';
  document.getElementById('windows-version').textContent=w.version+' · '+(w.size/1024/1024/1024).toFixed(2)+' GB · '+(Array.isArray(w.parts)?w.parts.length:0)+' parts';
 }
 state.textContent='Availability updated on '+new Date(data.generated_at).toLocaleDateString('en-US')+'.';
 }catch{document.getElementById('android-status').textContent='Browse releases';state.textContent='Could not load the catalog. Published downloads are available on GitHub Releases.';}}
load();
