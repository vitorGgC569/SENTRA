"""Read existing conversation turns into the Dot's current task inventory."""
from contextlib import closing
from sentra_core.conversations import _decode
from sentra_runtime.task_lifecycle import project_task


def conversation_tasks(control, owner, project_id, space_id, dots, conversation_id=None):
    members={d['dot_id']:d for d in dots}
    with closing(control.store.connect('shell')) as db:
        conversations={}
        for row in db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND space_id=? AND kind='conversation'",
                (owner,project_id,space_id)):
            value=_decode(row['body'])
            if value['dot_id'] in members:conversations[value['conversation_id']]=value
        rows=db.execute("SELECT * FROM shell_messages WHERE owner=? AND project_id=? AND space_id=? AND role='user' "
            +("AND conversation_id=? " if conversation_id else '')+"ORDER BY created_at DESC LIMIT 100",
            (owner,project_id,space_id,*([conversation_id] if conversation_id else []))).fetchall()
    result=[]
    for row in rows:
        conversation=conversations.get(row['conversation_id'])
        if conversation is None:continue
        dot=members[conversation['dot_id']]
        work=control.work_item_info(row['work_item_id'],owner)
        operation=control.durable.operation_status(row['operation_id'],owner)
        if work['assignee_agent_id']!=dot['agent_id']:continue
        content=_decode(row['protected_content'])
        value={'id':row['message_id'],'work_item_id':row['work_item_id'],'operation_id':row['operation_id'],
            'conversation_id':row['conversation_id'],'member_dot_id':dot['dot_id'],'agent_id':dot['agent_id'],
            'objective':content[:140] if isinstance(content,str) else 'Trabalho da conversa',
            'work_item_state':work['state'],'operation_state':operation['state'],
            'kind':'conversation_task'}
        from .task_verification import recorded
        proof=recorded(control,owner,row['work_item_id'])
        if proof:value['verification']=proof
        value['lifecycle']=project_task(value,verified_evidence=bool(proof and proof.get('verified') is True and proof.get('finalized') is True
            and proof['operation_id']==operation['operation_id'] and operation['state']=='SUCCEEDED'))
        result.append(value)
    return result


def decorate_messages(control,owner,project_id,space_id,conversation_id,messages):
    with closing(control.store.connect('shell')) as db:
        conversation=control.shell._entity(db,owner,project_id,'conversation',conversation_id,space_id=space_id)
        dot=control.shell._entity(db,owner,project_id,'dot',conversation['dot_id'],space_id=space_id)
    tasks={r['operation_id']:r for r in conversation_tasks(control,owner,project_id,space_id,[dot],conversation_id)}
    return [{**m,**({'task_lifecycle':tasks[m['operation_id']]['lifecycle'],
        'task_verification':tasks[m['operation_id']].get('verification')} if m.get('role')=='user'
        and m.get('operation_id') in tasks else {})} for m in messages]
