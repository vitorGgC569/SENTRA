import pytest
from orchestrator.events import EventBus, EventEnvelope, EventType


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    bus = EventBus()
    received = []

    async def on_task_created(event: EventEnvelope):
        received.append(event)

    bus.subscribe(EventType.TASK_CREATED, on_task_created)

    evt = EventEnvelope(
        event_type=EventType.TASK_CREATED,
        correlation_id="run-1",
        task_id="T-01",
        payload={"foo": "bar"},
    )
    await bus.publish(evt)

    assert len(received) == 1
    assert received[0].task_id == "T-01"
    assert received[0].correlation_id == "run-1"


@pytest.mark.asyncio
async def test_event_bus_wildcard_listener():
    bus = EventBus()
    all_events = []

    async def on_any(event: EventEnvelope):
        all_events.append(event)

    bus.subscribe_all(on_any)

    await bus.publish(EventEnvelope(event_type=EventType.RUN_STARTED, correlation_id="run-1"))
    await bus.publish(EventEnvelope(event_type=EventType.TASK_COMPLETED, correlation_id="run-1"))

    assert len(all_events) == 2
    assert len(bus.get_history("run-1")) == 2
