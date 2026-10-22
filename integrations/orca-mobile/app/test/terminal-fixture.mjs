import {createRequire} from 'node:module';
import {deflateSync} from 'node:zlib';
import {writeFileSync} from 'node:fs';
const {SnapshotEngine}=createRequire(import.meta.url)('../../../orca-terminal/dist/engine.cjs');
const engine=new SnapshotEngine();
try{
 await engine.create('t',40,8);
 const text='NORMAL\x1b[32m\x1b[?1049h\x1b[2J\x1b[3;4HTUI\x1b7\x1b[31';
 await engine.apply('t',{kind:'output',sequence:1,start:0,text});const frame=engine.capture('t');
 const checkpoint={available:true,geometry_sequence:0,checkpoint:{version:1,encoding:'deflate-json-base64',
  data:deflateSync(Buffer.from(JSON.stringify(frame))).toString('base64'),cursor:frame.cursor,sequence:frame.sequence}};
 const raw='\x1b[32mUTF8 🐋\x1b[0m\x1b[6n',next='m\x1b8X\x1b[?1049lZ';
 writeFileSync(process.argv[2],JSON.stringify({raw:{start:0,cursor:Array.from(raw).length,text:raw,terminal_id:'t',reset:false,cols:40,rows:8},
  checkpoint,next:{start:frame.cursor,cursor:frame.cursor+next.length,text:next,terminal_id:'t',reset:false,cols:40,rows:8}}));
}finally{engine.close()}
