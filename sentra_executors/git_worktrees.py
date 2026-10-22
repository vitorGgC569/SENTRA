"""Optional Git isolation behind the existing central Machine admission."""
from dataclasses import dataclass
from sentra_runtime.effect_boundary import current_effect_context
from ._base import GuardedExecutor,EffectRefusedBeforePublication
from workspace.worktrees import WorktreeManager
from workspace.git_workflow import CAPABILITIES,validate_args


@dataclass(frozen=True)
class GitWorktreeBinding:
    capability_id:str
    manager:WorktreeManager
    dot_id:str
    timeout_seconds:float=120
    control:object=None
    owner:str=''


class GitWorktreeExecutor(GuardedExecutor):
    kind='git-worktrees'

    def _validate(self,request,binding):
        args=dict(request.arguments)
        if request.capability_id=='git:worktree':
            if set(args)!={'dot_id','base_commit'} or args['dot_id']!=binding.dot_id:
                raise ValueError('worktree must belong to the configured Dot')
            if binding.control:
                from sentra_canvas.task_workspace import binding as workspace_binding
                work=binding.control.work_item_info(request.work_item_id,binding.owner)
                m=work.get('metadata',{})
                current=workspace_binding(binding.control,binding.owner,m.get('workspace_id'),m.get('conversation_id'),request.principal_id) if m.get('conversation_id') else None
                if current and (current['work_item_id']!=request.work_item_id or current['base_commit']!=args['base_commit']):
                    raise ValueError('conversation already has a worktree; reconcile before selecting another')
        elif request.capability_id=='git:worktree.inspect':
            if set(args)!={'worktree_id'}:raise ValueError('exact existing worktree required')
        elif request.capability_id in CAPABILITIES:
            validate_args(request.capability_id,args)
        else:raise ValueError('unsupported git capability')
        return args

    def _execute(self,binding,arguments):
        context=current_effect_context.get()
        if context is None:raise PermissionError('central physical effect fence required')
        context.checkpoint()
        if binding.capability_id=='git:worktree':
            result=binding.manager.create(context.request)
            if binding.control:
                from sentra_canvas.task_workspace import register
                return register(binding.control,binding.owner,context.request,binding.manager,result)
            return result
        result=binding.manager.inspect(arguments['worktree_id'])
        if (result['principal_id']!=context.request.principal_id or result['dot_id']!=binding.dot_id):
            raise PermissionError('worktree belongs to another task or Dot')
        if result['work_item_id']!=context.request.work_item_id:
            if not binding.control:raise PermissionError('worktree belongs to another task')
            from sentra_canvas.task_workspace import for_work_item
            selected=for_work_item(binding.control,binding.owner,context.request.work_item_id,context.request.principal_id)
            if not selected or selected['worktree_id']!=result['worktree_id']:raise PermissionError('Git step belongs to another conversation or Run')
        if binding.capability_id in CAPABILITIES:
            from workspace.git_workflow import execute
            before_cleanup=None
            if binding.capability_id=='git:cleanup' and binding.control:
                def before_cleanup():
                    workspace_id='xws-git-'+result['worktree_id']
                    from sentra_canvas.workspace_file_editor import workspace_draft_lock
                    work=binding.control.work_item_info(context.request.work_item_id,binding.owner)
                    with workspace_draft_lock(binding.control,work['metadata']['workspace_id'],workspace_id):
                        workspace=binding.control.execution_workspace_info(workspace_id,binding.owner)
                        if workspace['state']!='READY' or workspace.get('lease_run_id'):
                            raise EffectRefusedBeforePublication('release the execution workspace lease before cleanup')
                        from sentra_canvas.workspace_file_editor import has_protected_workspace_drafts
                        if has_protected_workspace_drafts(binding.control,binding.owner,workspace['metadata']['workspace_id'],workspace_id):
                            raise EffectRefusedBeforePublication('save or discard protected editor drafts before cleanup; no draft was removed')
                        from sentra_executors.conpty_sessions import PersistentConPTYLedger
                        sessions=PersistentConPTYLedger(binding.control).sessions(binding.owner,workspace['metadata']['workspace_id'])
                        if len(sessions)>=100 or any(s['principal_id']==result['principal_id'] and s['state']=='OPEN' for s in sessions):
                            raise EffectRefusedBeforePublication('close or reconcile existing Dot terminal sessions before cleanup')
                        # Fence future file/task resolution before physical removal.
                        # Partial cleanup stays unavailable and requires observation.
                        context.checkpoint()
                        binding.control.transition_execution_workspace(workspace_id,binding.owner,'DISCARDED',
                            metadata={'cleanup_operation_id':context.request.operation_id})
            return execute(binding.manager,context.request,before_cleanup=before_cleanup)
        return result


def declare_git_worktree_machine(*,machine_id,owner_principal_id,bindings,policy):
    from sentra_runtime.contracts import Machine,Capability
    from .discovery import MachineDeclaration
    executor=GitWorktreeExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,
        bindings={b.capability_id:b for b in bindings},policy=policy)
    capabilities=tuple(Capability(b.capability_id,'Task scoped Git step, requiring exact review and central admission','high') for b in bindings)
    return MachineDeclaration(Machine(machine_id,executor.kind,owner_principal_id,capabilities),executor)
