import hashlib
import pytest
from native_bridge.job_store import JobStore
from native_bridge.protocol import ChatJob


def test_lost_ack_and_restart_do_not_create_second_send(tmp_path):
    path=tmp_path/'relay.sqlite3'
    store=JobStore(path)
    job=ChatJob(task_id='turn-1234',prompt='hello',kind='CHAT_START',delivery_key='turn-1234')
    original=store.submit(job)
    claim=store.poll('TAB-1')
    store.progress(original,'TAB-1',claim['lease_token'],'sending')
    store.close()
    restarted=JobStore(path)
    assert restarted.submit(ChatJob(task_id='turn-1234',prompt='hello',kind='CHAT_START',delivery_key='turn-1234'))==original
    assert restarted.delivery_status(original)['state']=='pending'
    assert restarted.poll('TAB-2') is None
    with pytest.raises(ValueError,match='DELIVERY_KEY_CONFLICT'):
        restarted.submit(ChatJob(task_id='turn-1234',prompt='changed',kind='CHAT_START',delivery_key='turn-1234'))
    restarted.close()


def test_only_exact_user_message_receipt_confirms_delivery(tmp_path):
    store=JobStore(tmp_path/'relay.sqlite3')
    job=ChatJob(task_id='turn-1234',prompt='hello',kind='CHAT_START')
    ident=store.submit(job)
    claim=store.poll('TAB-1')
    store.progress(ident,'TAB-1',claim['lease_token'],'sending')
    evidence=dict(conversation_id='conversation-1234',message_id='message-1234',
                  prompt_sha256=hashlib.sha256(b'hello').hexdigest(),images_attached=0)
    with pytest.raises(ValueError,match='digest mismatch'):
        store.delivery_receipt(ident,'TAB-1',claim['lease_token'],{**evidence,'prompt_sha256':'0'*64})
    assert store.delivery_receipt(ident,'TAB-1',claim['lease_token'],evidence)['state']=='sent'
    assert store.delivery_receipt(ident,'TAB-1',claim['lease_token'],evidence)['state']=='sent'
    with pytest.raises(ValueError,match='conflicting'):
        store.delivery_receipt(ident,'TAB-1',claim['lease_token'],{**evidence,'message_id':'message-5678'})
    store.close()


def test_uncertain_first_message_blocks_second_for_same_conversation(tmp_path):
    store=JobStore(tmp_path/'relay.sqlite3')
    url='https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc'
    first=store.submit(ChatJob(task_id='first',prompt='hello',new_chat=False,conversation_url=url))
    claim=store.poll('TAB-1')
    store.progress(first,'TAB-1',claim['lease_token'],'sending')
    store.cancel(first)
    second=store.submit(ChatJob(task_id='second',prompt='later',new_chat=False,conversation_url=url))
    next_claim=store.poll('TAB-2')
    with pytest.raises(ValueError,match='BUSY'):
        store.progress(second,'TAB-2',next_claim['lease_token'],'sending')
    assert store.delivery_status(second)['state']=='not_sent'
    store.close()

def test_later_web_delivery_survives_expired_queued_job(tmp_path):
    """Previously BEGIN IMMEDIATE after _expire caused a nested transaction."""
    from native_bridge.protocol import ChatJob
    ticks=[1000.0]
    store=JobStore(tmp_path/"relay.sqlite3",clock=lambda: ticks[0])
    first=ChatJob(task_id="task-expired",kind="CHAT_SEND",new_chat=False,
                  conversation_url="https://chatgpt.com/c/aaaaaaaabbbbcccc",
                  prompt="first",delivery_key="send:expired")
    store.submit(first)
    ticks[0]+=4000
    second=ChatJob(task_id="task-new",kind="CHAT_SEND",new_chat=False,
                   conversation_url="https://chatgpt.com/c/ddddddddeeeeffff",
                   prompt="new",delivery_key="send:new")
    assert store.submit(second)==second.job_id
    assert store.delivery.status(first.job_id)["state"]=="not_sent"
    assert store.delivery.status(second.job_id)["state"]=="not_sent"
