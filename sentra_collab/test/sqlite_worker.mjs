// Child process boundary for real SQLite cross-process and kill/recovery tests.
// Receives only test-fixture values by IPC, never via URLs or process argv.
import {SQLiteHost} from "../sqlite_host.mjs";
const file=process.argv[2];
if(!file||!process.send)process.exit(2);
const db=new SQLiteHost({filename:file,
  fault:stage=>{if(stage==="after-write-before-commit"&&process.argv[3]==="crash")process.exit(77);}
});
process.on("message",async message=>{
  const {id,op,args={}}=message;
  try {
    let value;
    if(op==="consume")value=await db.callbacks.consumeNonce(args);
    else if(op==="commit")value=await db.callbacks.commitSnapshot({
      ...args,snapshot:new Uint8Array(Buffer.from(args.snapshotBase64,"base64"))
    });
    else if(op==="reconcile")value=await db.reconcileCommit({
      ...args,candidateSnapshot:new Uint8Array(Buffer.from(args.snapshotBase64,"base64"))
    });
    else if(op==="snapshot"){
      const s=await db.callbacks.loadSnapshot(args);
      value={revision:s.revision,snapshotBase64:s.snapshot?Buffer.from(s.snapshot).toString("base64"):null};
    }
    else if(op==="grant")value=await db.callbacks.resolveGrant(args);
    else if(op==="check")value=await db.callbacks.checkGrant(args);
    else if(op==="revoke")value=db.revoke(args.workspaceId,args.principalId);
    else throw Error("collaboration-denied");
    process.send({id,ok:true,value});
  }catch{process.send({id,ok:false,error:"collaboration-denied"});}
});
process.on("disconnect",()=>{db.close();process.exit(0);});
