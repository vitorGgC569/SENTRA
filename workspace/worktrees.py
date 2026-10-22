"""Persistent Git workspaces, fenced by the existing central effect context."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from sentra_runtime.effect_boundary import CentralEffectContext, current_effect_context
from sentra_canvas.instance_lock import InstanceLock


class WorktreeManager:
    def __init__(self, repository, state_dir):
        self.repository=Path(repository).resolve(strict=True)
        self.state=Path(state_dir).resolve();self.state.mkdir(parents=True,exist_ok=True)
        self.hooks=self.state/'empty-hooks';self.hooks.mkdir(exist_ok=True)
        common=self.git('rev-parse','--git-common-dir').strip()
        self.common=(self.repository/common).resolve()
        self.root=self.state/'worktrees';self.root.mkdir(exist_ok=True)

    def git(self,*args,cwd=None):
        environment={k:v for k,v in os.environ.items() if not k.upper().startswith('GIT_')}
        environment.update(GIT_TERMINAL_PROMPT='0',LC_ALL='C')
        return subprocess.run(['git','-c','core.hooksPath='+str(self.hooks),'-c','core.fsmonitor=false',
            '-C',str(cwd or self.repository),*args],check=True,env=environment,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),capture_output=True,text=True,timeout=45).stdout

    def _admit(self,request):
        context=current_effect_context.get()
        if not isinstance(context,CentralEffectContext) or context.request!=request or request.capability_id!='git:worktree':
            raise PermissionError('exact centrally admitted git:worktree effect required')
        context.checkpoint()
        return context

    def _registered(self,target,branch):
        wanted=os.path.normcase(str(target.resolve()))
        for block in self.git('worktree','list','--porcelain').split('\n\n'):
            fields=dict(line.split(' ',1) for line in block.splitlines() if ' ' in line)
            path=fields.get('worktree')
            if path and os.path.normcase(str(Path(path).resolve()))==wanted:
                return fields.get('branch')=='refs/heads/'+branch and not target.is_symlink()
        return False

    def create(self,request):
        context=self._admit(request)
        args=dict(request.arguments)
        if set(args)!={'dot_id','base_commit'} or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',args['dot_id']) or not re.fullmatch(r'[a-f0-9]{40,64}',args['base_commit']):
            raise ValueError('Dot and exact base commit required; prompt overrides are not accepted')
        identity=hashlib.sha256(json.dumps([request.principal_id,request.machine_id,request.work_item_id,args],sort_keys=True).encode()).hexdigest()[:24]
        target=self.root/identity;branch='codex/dot-'+identity
        manifest=self.state/(identity+'.json')
        # All worktree managers for this repository use the same common-dir lock.
        deadline=time.monotonic()+45
        while True:
            try:
                lock=InstanceLock(self.common/'sentra-worktrees.lock');break
            except RuntimeError:
                context.checkpoint()
                if time.monotonic()>=deadline:raise TimeoutError('repository admission busy')
                time.sleep(.05)
        try:
            context.checkpoint()
            if manifest.exists():
                prior=json.loads(manifest.read_text())
                if prior.get('state')!='ready' or not target.exists() or not self._registered(target,branch):
                    raise RuntimeError('worktree drift: reconcile; do not recreate')
                return {**prior,'reused':True}
            if target.exists():raise RuntimeError('unreconciled worktree path exists')
            base=self.git('rev-parse','--verify',args['base_commit']+'^{commit}').strip()
            head=self.git('rev-parse','HEAD').strip()
            if base!=head:
                raise ValueError('base drift requires a new centrally approved request at the current commit')
            result={'worktree_id':identity,'path':str(target),'branch':branch,'base_commit':base,
                    'dot_id':args['dot_id'],'work_item_id':request.work_item_id,'principal_id':request.principal_id}
            # Reserve metadata before Git. A crash becomes drift, never a second add.
            manifest.write_text(json.dumps({**result,'state':'creating'}))
            self.git('worktree','add','-b',branch,str(target),base)
            context.checkpoint()
            manifest.write_text(json.dumps({**result,'state':'ready'}))
            return {**result,'state':'ready','reused':False}
        finally:lock.close()

    def inspect(self,identity):
        if not re.fullmatch(r'[a-f0-9]{24}',identity):raise ValueError('invalid worktree identity')
        value=json.loads((self.state/(identity+'.json')).read_text())
        if value.get('state')!='ready' or value.get('worktree_id')!=identity:
            raise RuntimeError('worktree creation is not confirmed; reconcile before use')
        target=Path(value['path']).resolve(strict=True)
        if not target.is_relative_to(self.root):raise PermissionError('worktree escaped root')
        if not self._registered(target,value['branch']):raise RuntimeError('worktree identity drift')
        diff=self.git('diff','--no-ext-diff','--no-textconv','--stat',cwd=target)
        return {**value,'diff_stat':diff,'read_only':True}
