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
 state.textContent='Availability updated on '+new Date(data.generated_at).toLocaleDateString('en-US')+'.';
 }catch{document.getElementById('android-status').textContent='Browse releases';state.textContent='Could not load the catalog. Published downloads are available on GitHub Releases.';}}
load();
