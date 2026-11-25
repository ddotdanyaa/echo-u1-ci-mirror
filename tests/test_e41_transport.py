"""E41 integration tests: the public sink is tested independently from classifiers.

Only fakes for network and acoustic input; no external service or real audio.
"""
import asyncio
from types import SimpleNamespace

import pytest

from echo_sync.controlled_host import lookup_publicly_permitted
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket


@pytest.mark.parametrize('original,query', [
    ('Лена, когда была Полтавская битва?', 'Когда была Полтавская битва?'),
    ('Лена, проверь запись. В каком году основали Петербург?', 'В каком году основали Петербург?'),
    ('Лена сколько будет два плюс два', 'сколько будет два плюс два'),
])
def test_last_mile_checks_original_utterance_not_just_extracted_query(original, query):
    heard = {'text': original, 'valid': True}
    c = SimpleNamespace(
        public_lookup_allowed=ControlledMedia.public_lookup_allowed,
        question_text='',
        ledger=SimpleNamespace(latest_user=lambda: heard),
    )
    assert ControlledMedia.public_lookup_allowed(query, True)  # public-looking suffix
    assert not lookup_publicly_permitted(c, query)
    heard['text'] = query
    assert lookup_publicly_permitted(c, query)
    c.question_text = original
    assert not lookup_publicly_permitted(c, query)


def test_last_mile_fails_closed_if_live_context_cannot_be_read():
    c = SimpleNamespace(
        public_lookup_allowed=ControlledMedia.public_lookup_allowed,
        question_text='',
        ledger=SimpleNamespace(latest_user=lambda: 1 / 0),
    )
    assert not lookup_publicly_permitted(c, 'Что такое инерция?')


@pytest.mark.parametrize('utterance', [
    'Лена, когда была Полтавская битва?',
    'Лена сколько будет два плюс два',
    'Миша, открой запись. Сколько будет два плюс два?',
])
def test_early_partial_and_final_do_not_start_public_network(utterance, tmp_path):
    async def scenario():
        requested = []
        async def fetch(question):
            requested.append(question)
            return []
        async def emit(_event):
            pass
        clock = [0.0]
        c = ControlledMedia(tmp_path / 'state.db', session_id='e41', source_delivery='delegation')
        w = NativeMediaSocket(c, emit, None, fetch, None, prefetch=True, clock=lambda: clock[0])
        w.ready = True
        try:
            await w.provider({'type': 'turn.created', 'turn': {'id': 'u1', 'role': 'user', 'transcript': utterance}})
            clock[0] = 1.0
            await w.tick()
            await asyncio.sleep(0)
            await w.provider({'type': 'turn.done', 'turn': {'id': 'u1', 'role': 'user', 'transcript': utterance}})
            clock[0] = 2.0
            await w.tick()
            await asyncio.sleep(0.01)
            assert requested == [], requested
        finally:
            await w.close()
    asyncio.run(scenario())


def test_ordinary_knowledge_question_remains_searchable(tmp_path):
    async def scenario():
        requested = []
        async def fetch(question):
            requested.append(question)
            return []
        async def emit(_event):
            pass
        clock = [0.0]
        c = ControlledMedia(tmp_path / 'state.db', session_id='e41-normal', source_delivery='delegation')
        w = NativeMediaSocket(c, emit, None, fetch, None, prefetch=True, clock=lambda: clock[0])
        w.ready = True
        try:
            await w.provider({'type': 'turn.created', 'turn': {'id': 'u1', 'role': 'user', 'transcript': 'Что такое инерция'}})
            clock[0] = 1.0
            await w.tick()
            await asyncio.sleep(0)
            assert requested == ['Что такое инерция'], requested
        finally:
            await w.close()
    asyncio.run(scenario())


def test_stale_queued_lookup_does_not_leave_controller(tmp_path):
    async def scenario():
        requested = []
        async def fetch(question):
            requested.append(question)
            return []
        async def emit(_event):
            pass
        c = ControlledMedia(tmp_path / 'stale.db', session_id='e41-stale', source_delivery='delegation')
        first = 'Что такое инерция?'
        second = 'Что такое энтропия?'
        c.provider({'type': 'turn.created', 'turn': {'id': 'u1', 'role': 'user', 'transcript': first}})
        old_actions = c.provider({'type': 'turn.done', 'turn': {'id': 'u1', 'role': 'user', 'transcript': first}})
        old_lookup = next(a for a in old_actions if a['type'] == 'lookup')
        c.provider({'type': 'turn.created', 'turn': {'id': 'u2', 'role': 'user', 'transcript': second}})
        c.provider({'type': 'turn.done', 'turn': {'id': 'u2', 'role': 'user', 'transcript': second}})
        assert c.ticket_stale(old_lookup['ticket']), 'premise: the first ticket must be superseded'
        w = NativeMediaSocket(c, emit, None, fetch, None, prefetch=True)
        w.ready = True
        try:
            await w._lookup(old_lookup)
            assert requested == [], 'a stale question reached a public network sink'
        finally:
            await w.close()
    asyncio.run(scenario())


def test_last_mile_rejects_missing_or_invalid_origin():
    current={'text': 'Что такое инерция?', 'valid': True}
    c=SimpleNamespace(
        public_lookup_allowed=ControlledMedia.public_lookup_allowed,
        question_text='',
        question_id=None,
        ledger=SimpleNamespace(latest_user=lambda: current),
    )
    assert lookup_publicly_permitted(c, 'Что такое инерция?')
    current['valid']=False
    assert not lookup_publicly_permitted(c, 'Что такое инерция?')
    current['valid']=True
    current['text']=''
    assert not lookup_publicly_permitted(c, 'Что такое инерция?')
    c.ledger.latest_user=lambda: None
    assert not lookup_publicly_permitted(c, 'Что такое инерция?')
