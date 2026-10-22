"""Owner-reviewed, fixed access recipes over the existing conversation service.

Models may describe the requested access. Only the authenticated owner shell
entry point can apply a recipe; actor and mobile allowlists do not expose it.
No new grant authority, policy dialect or execution path is introduced.
"""
from .store import Denied


def configure_access(canvas,project_id,params,key,graph):
    if set(params)!={'dot_id','space_id','member_dot_id','conversation_id','profile','approved'}:
        raise ValueError('exact reviewed access recipe required')
    if params['approved'] is not True:raise Denied('owner confirmation required')
    if params['profile'] not in {'read','ask','none'}:raise ValueError('unknown access recipe')
    member=next((d for d in graph['dots'] if d['dot_id']==params['member_dot_id']),None)
    if member is None:raise Denied('access belongs to another Dot canvas')
    from contextlib import closing
    control=canvas._shell_service();owner=canvas._runtime().owner
    with closing(control.store.connect('shell')) as db:
        conversation=control.shell._entity(db,owner,project_id,'conversation',params['conversation_id'],space_id=params['space_id'])
    if conversation['dot_id']!=member['dot_id']:raise Denied('access belongs to another conversation')
    from .shell_access import dispatch_access
    from .shell_requests import ShellHostRequests
    requests=ShellHostRequests(control,owner)
    def apply():
        # Changes may span central stores. A crash after this point is uncertain;
        # inspecting the outer journal never repeats the configuration.
        requests.note_effect_possible(project_id,key)
        fields={'space_id':params['space_id'],'conversation_id':params['conversation_id']}
        if params['profile']=='ask':fields['mode']='ask'
        else:fields.update(mode='custom',scope='workspace',approval='ask',
            capabilities=['computer:file.read'] if params['profile']=='read' else [])
        inner_key=requests.operation_id(project_id,key,'access-recipe')
        value=dispatch_access(canvas,project_id,'access_set',fields,inner_key)
        if value.get('status')=='uncertain' or not value.get('work_item_id'):
            return {'status':'uncertain','automatic_retry':False,'control_mutation_only':True}
        return {'status':'configured','profile':params['profile'],'dot_id':member['dot_id'],
            'conversation_id':conversation['conversation_id'],'access':value,
            'automatic_retry':False,'control_mutation_only':True,'external_completion_claimed':False}
    return requests.invoke(project_id,'dot_canvas_access',params,key,apply)
