/** Owned loopback collaboration process. Credentials arrive only over stdin. */
import {createInterface} from 'node:readline';
import {CentralCollabBridge,createCentralCollabServer} from './central_bridge.mjs';
const input=createInterface({input:process.stdin,crlfDelay:Infinity});
let app=null,closing=false;
const startup=setTimeout(()=>process.exit(1),8000);
async function close(){
  if(closing)return;closing=true;clearTimeout(startup);
  try{if(app)await app.destroy();}finally{process.exit(0);}
}
input.once('line',async line=>{
  try{
    if(line.length>8192)throw Error('invalid-config');
    const config=JSON.parse(line);
    if(!Array.isArray(config.allowedOrigins)||config.allowedOrigins.length!==2||
       config.allowedOrigins.some(origin=>!/^http:\/\/(127\.0\.0\.1|localhost):[0-9]+$/.test(origin)))
      throw Error('invalid-origin');
    const bridge=new CentralCollabBridge({url:config.url,token:config.token});
    app=createCentralCollabServer({bridge,allowedOrigins:config.allowedOrigins,port:0});
    await app.listen();clearTimeout(startup);
    const address=app.server.httpServer.address();
    process.stdout.write(JSON.stringify({ready:true,url:'ws://127.0.0.1:'+address.port})+'\n');
  }catch{process.stderr.write('collaboration-startup-failed\n');process.exit(1);}
});
input.on('close',close);
process.on('SIGTERM',close);process.on('SIGINT',close);
