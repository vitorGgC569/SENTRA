"""Read-only terminal frames under a live central WorkItem and Grant."""
from .store import Denied

MAX_FRAME_CHARS=16000


def check_dot_terminal(canvas,project_id,dot_id,space_id,machine,terminal_id,work_item_id):
    if not isinstance(terminal_id,str) or not terminal_id or len(terminal_id)>128:
        raise ValueError('existing terminal identity required')
    from .workspace_contract import inventory
    view=inventory(canvas,project_id,{'dot_id':dot_id,'space_id':space_id})
    actor={dot['dot_id']:dot['agent_id'] for dot in view['graph']['dots']}
    terminal=next((t for t in view['resources']['terminals'] if t['id']==terminal_id),None)
    if terminal and actor.get(terminal.get('dot_id'))==machine['agent_id'] and (not terminal.get('work_item_id') or terminal['work_item_id']==work_item_id):return
    # A terminal created by the central lifecycle has its own durable binding,
    # even before an agent/tool presentation row has attached to it.
    from sentra_executors.conpty_sessions import PersistentConPTYLedger
    control=canvas._shell_service();owner=canvas._runtime().owner
    try:binding=PersistentConPTYLedger(control).get(owner,project_id,terminal_id)
    except (PermissionError,FileNotFoundError):raise Denied('terminal is outside this Dot machine') from None
    if (binding['principal_id']!=machine['agent_id'] or binding['principal_id'] not in actor.values()
            or binding['work_item_id']!=work_item_id):
        raise Denied('terminal is outside this Dot WorkItem')


def observe_terminal(services,project_id,action,params):
    machine,item,capability=services._scope(project_id,params,grant=True)
    if machine['kind']!='terminal' or capability!='terminal:read':
        raise Denied('terminal observation requires its terminal:read Grant')
    terminal_id=params.get('terminal_id')
    if not isinstance(terminal_id,str) or not terminal_id or len(terminal_id)>128:
        raise ValueError('existing terminal identity required')
    from sentra_executors.conpty_sessions import PersistentConPTYLedger
    try:binding=PersistentConPTYLedger(services.host.control).get(services.host.owner,project_id,terminal_id)
    except FileNotFoundError:raise Denied('terminal lacks its central lifecycle binding') from None
    if (binding['run_id'],binding['work_item_id'],binding['principal_id'])!=(item['run_id'],item['work_item_id'],machine['agent_id']):
        raise Denied('terminal lifecycle binding differs from the live WorkItem')
    if action=='terminal_checkpoint':return services.canvas.terminal_checkpoint(project_id,terminal_id)
    cursor=params.get('cursor',0)
    if type(cursor) is not int or not 0<=cursor<=10**12:raise ValueError('bounded terminal cursor required')
    value=services.canvas.terminal_output(project_id,terminal_id,cursor)
    text=value.get('text');end=value.get('cursor')
    if not isinstance(text,str) or type(end) is not int or end<len(text) or end>10**12:
        raise RuntimeError('invalid terminal observation')
    start=end-len(text);text=text[:MAX_FRAME_CHARS]
    fields=('status','exit_code','process_live','process_state','recoverable','persisted','runtime_id',
            'origin_runtime_id','geometry_sequence','cols','rows','checkpoint_supported','tail_uncertain')
    return {**{key:value[key] for key in fields if key in value},'protocol_version':1,
        'terminal_id':terminal_id,'start':start,'cursor':start+len(text),'text':text,
        'head':value.get('head',end),'has_more':bool(value.get('has_more')) or start+len(text)<end,
        'truncated':bool(value.get('truncated')) or start!=cursor,'read_only':True,
        'automatic_input_replay':False}
