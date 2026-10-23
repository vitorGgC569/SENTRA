/** Bounds view-only restart loops. A restart never resends a process action. */
export class RendererRecovery {
 private scope='';private identity='';private attempts=0;
 constructor(private readonly limit=2){}
 select(scope:string,identity:string){if(scope!==this.scope){this.scope=scope;this.attempts=0}this.identity=identity}
 restart(identity:string){
  if(identity!==this.identity||this.attempts>=this.limit)return false;
  this.identity='';this.attempts++;return true;
 }
 get count(){return this.attempts}
}
