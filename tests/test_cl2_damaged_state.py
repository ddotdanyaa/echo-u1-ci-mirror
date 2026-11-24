"""CL2 amendment B (DEF-T-07): a damaged session row must never break every later call.

The phone's session id is the same constant for every call, so one bad row in ``controlled-state.sqlite3`` used to fail EVERY later
call: ``ControlledMedia()`` raised (JSONDecodeError, AttributeError) or the next question did (KeyError, TypeError). Now the row is
set aside with ONE warning (no words of the conversation in it) and the call starts clean: the next question is answered.

Each damage kind is written into the real database, then a call is opened the way the host opens it and a question is asked.
"""
import json
import logging
import sqlite3

import pytest

import helpers_s6_ack as H
from echo_sync.controlled_media import ControlledMedia
from echo_sync.engine import EchoEngine
from engine_say import engine_reply

GOOD = {'schema': 2, 'revision': 3, 'question': 'Секретный вопрос про налоги', 'answer': 'Секретный ответ про налоги.',
        'chunks': ['Секретный ответ', 'про налоги.'], 'chunk_index': 1, 'completed': False, 'pending_turn': None,
        'history': [{'question': 'Секретный вопрос про налоги', 'answer': 'Секретный ответ про налоги.'}]}


def without(key):
    state = dict(GOOD)
    del state[key]
    return json.dumps(state, ensure_ascii=False)


def with_value(key, value):
    return json.dumps({**GOOD, key: value}, ensure_ascii=False)


DAMAGE = {
    'cut_json': json.dumps(GOOD, ensure_ascii=False)[:57],
    'empty': '',
    'binary': b'\x00\xff\xfe\x81 not json \x00',
    'a_list': '[1, 2, 3]',
    'json_null': 'null',
    'a_number': '17',
    'no_revision': without('revision'),
    'no_chunk_index': without('chunk_index'),
    'no_chunks': without('chunks'),
    'no_history': without('history'),
    'revision_as_text': with_value('revision', '3'),
    'chunk_index_as_text': with_value('chunk_index', '1'),
    'chunk_index_out_of_range': with_value('chunk_index', 7),
    'chunks_not_a_list': with_value('chunks', 'Секретный ответ про налоги.'),
    'history_null': with_value('history', None),
    'history_a_dict': with_value('history', {'question': 'q'}),
    'history_of_strings': with_value('history', ['Секретный вопрос']),
    'completed_as_text': with_value('completed', 'no'),
}


def write_row(path, value):
    EchoEngine(path, lambda *args: None)                        # the tables exist, as on any phone that ever called
    with sqlite3.connect(str(path)) as db:
        db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)', (H.SESSION, value))


@pytest.mark.parametrize('kind', list(DAMAGE))
def test_a_damaged_row_is_set_aside_once_and_the_next_question_is_answered(tmp_path, caplog, kind):
    path = tmp_path / 'controlled-state.sqlite3'
    write_row(path, DAMAGE[kind])
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        c = ControlledMedia(path, session_id=H.SESSION, clock=H.FakeClock(), **H.HOST_KWARGS)   # the call opens
        c.speech_started()
        asked = c.provider(H.done('q1', 'user', 'Что такое инерция'))
        spoken = c.provider(H.done('a1', 'assistant', 'Инерция — это свойство тела сохранять скорость.'))
    assert [a['type'] for a in asked] == ['cancel', 'route'], asked
    assert [a['type'] for a in spoken] == ['speak'], f'{kind}: the next question was not answered: {spoken}'
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, f'{kind}: expected exactly one warning, got {[r.getMessage() for r in warnings]}'
    assert 'налог' not in warnings[0].getMessage().lower() and 'секрет' not in warnings[0].getMessage().lower()
    assert c.state()['revision'] >= 1 and c.state()['chunks'], 'the new answer is the stored plan now'


@pytest.mark.parametrize('kind', ['cut_json', 'a_list', 'no_chunks'])
def test_the_engine_alone_starts_clean_too(tmp_path, kind):
    """The text route (EchoEngine without the controller): ``state()`` reads nothing, and the next question is answered."""
    path = tmp_path / 'state.sqlite3'
    write_row(path, DAMAGE[kind])
    engine = EchoEngine(path, lambda *args: 'Первый второй третий. Четвёртый пятый.')
    assert engine.state(H.SESSION) is None
    assert engine_reply(engine, session_id=H.SESSION, turn_id='t1', text='Что это?', request={}, model='m') == 'Первый второй третий.'


def test_a_damaged_row_met_inside_a_turn_does_not_raise_either(tmp_path):
    """The first read of the bad row may be the turn itself (no ``state()`` call before it)."""
    path = tmp_path / 'state.sqlite3'
    write_row(path, DAMAGE['revision_as_text'])                 # «'3' + 1» used to raise TypeError inside the turn
    engine = EchoEngine(path, lambda *args: 'Первый второй третий. Четвёртый пятый.')
    assert engine_reply(engine, session_id=H.SESSION, turn_id='t1', text='Что это?', request={}, model='m') == 'Первый второй третий.'


def test_a_healthy_row_is_kept_as_it_is(tmp_path, caplog):
    path = tmp_path / 'controlled-state.sqlite3'
    write_row(path, json.dumps(GOOD, ensure_ascii=False))
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        c = ControlledMedia(path, session_id=H.SESSION, clock=H.FakeClock(), **H.HOST_KWARGS)
    assert c.state()['chunk_index'] == 1 and c.state()['revision'] == 3
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
