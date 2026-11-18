"""Only synthetic ticket/epoch races; no cloud, real network or private audio."""
import asyncio

import pytest

from lookup_transport_slice import LookupTransport


class Controller:
    def __init__(self):
        self.epoch = 8
        self.current_ticket = ("q1", 3)
        self.response_count = 0

    def ticket_stale(self, ticket):
        return ticket != self.current_ticket

    def lookup_result(self, epoch, rows=None, failure=None, ticket=None):
        self.response_count += 1
        if self.ticket_stale(ticket) or epoch != self.epoch:
            return [], None, None
        if failure is not None:
            return [], "lookup_unavailable", type(failure).__name__
        return [{"type": "deliver", "rows": rows}], None, None


class Early:
    def __init__(self, on_resolve=None):
        self.queries = []
        self.on_resolve = on_resolve

    async def resolve(self, turn, query):
        self.queries.append((turn, query))
        if self.on_resolve is not None:
            return await self.on_resolve()
        return [{"url": "https://example.invalid", "text": "synthetic"}]


class Wire(LookupTransport):
    def __init__(self, controller, early, on_observe=None):
        self.controller = controller
        self.early = early
        self.events = []
        self.delivered = []
        self.errors = []
        self.on_observe = on_observe

    async def _observe(self, event, **kwargs):
        self.events.append((event, kwargs))
        if self.on_observe:
            self.on_observe(event)

    async def actions(self, actions):
        self.delivered.extend(actions)

    async def _error(self, code, reason, epoch=None):
        self.errors.append((code, reason, epoch))


def action():
    return {
        "epoch": 8, "ticket": ("q1", 3), "input_turn_id": "u1",
        "question": "Что такое инерция?", "lookup_question": "Что такое инерция?"
    }


def test_stale_ticket_aborts_before_external_call():
    c = Controller()
    c.current_ticket = ("q2", 4)
    w = Wire(c, Early())
    asyncio.run(w._lookup(action()))
    assert w.early.queries == []
    assert w.delivered == []
    assert w.errors == []


def test_stale_epoch_aborts_before_external_call():
    c = Controller()
    c.epoch = 9
    w = Wire(c, Early())
    asyncio.run(w._lookup(action()))
    assert w.early.queries == []


@pytest.mark.parametrize("kind", ["ticket", "epoch"])
def test_queued_lookup_rechecks_after_await_before_external_call(kind):
    c = Controller()
    def during_observe(event):
        if event == "lookup_start":
            if kind == "ticket":
                c.current_ticket = ("q2", 4)
            else:
                c.epoch = 9
    w = Wire(c, Early(), on_observe=during_observe)
    asyncio.run(w._lookup(action()))
    assert w.early.queries == []
    assert w.delivered == []


def test_current_lookup_uses_original_ticket_once():
    c = Controller()
    w = Wire(c, Early())
    asyncio.run(w._lookup(action()))
    assert w.early.queries == [("u1", "Что такое инерция?")]
    assert len(w.delivered) == 1
    assert len(w.delivered[0]["rows"]) == 1
    assert c.response_count == 1


def test_stale_after_started_network_is_ignored_by_existing_result_gate():
    c = Controller()
    async def stale_during_fetch():
        c.current_ticket = ("q2", 4)
        await asyncio.sleep(0)
        return [{"url": "https://example.invalid", "text": "old"}]
    w = Wire(c, Early(on_resolve=stale_during_fetch))
    asyncio.run(w._lookup(action()))
    assert len(w.early.queries) == 1
    assert w.delivered == []
    assert w.errors == []


def test_network_failure_goes_through_existing_error_gate():
    c = Controller()
    async def fails():
        raise RuntimeError("synthetic offline error")
    w = Wire(c, Early(on_resolve=fails))
    asyncio.run(w._lookup(action()))
    assert w.errors == [("lookup_unavailable", "RuntimeError", 8)]
    assert w.delivered == []


def test_cancelled_pending_task_is_not_reported_as_failure():
    c = Controller()
    async def canceled():
        raise asyncio.CancelledError()
    w = Wire(c, Early(on_resolve=canceled))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(w._lookup(action()))
    assert w.errors == []
