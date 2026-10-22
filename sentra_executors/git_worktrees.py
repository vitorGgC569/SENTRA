"""Optional Git isolation behind the existing central Machine admission."""
from dataclasses import dataclass
from sentra_runtime.effect_boundary import current_effect_context
from ._base import GuardedExecutor
from workspace.worktrees import WorktreeManager


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
        if (result['principal_id']!=context.request.principal_id or
                result['work_item_id']!=context.request.work_item_id or result['dot_id']!=binding.dot_id):
            raise PermissionError('worktree belongs to another task or Dot')
        return result


def declare_git_worktree_machine(*,machine_id,owner_principal_id,bindings,policy):
    from sentra_runtime.contracts import Machine,Capability
    from .discovery import MachineDeclaration
    executor=GitWorktreeExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,
        bindings={b.capability_id:b for b in bindings},policy=policy)
    capabilities=tuple(Capability(b.capability_id,'Persistent, task scoped Git isolation; no publication','high') for b in bindings)
    return MachineDeclaration(Machine(machine_id,executor.kind,owner_principal_id,capabilities),executor)
