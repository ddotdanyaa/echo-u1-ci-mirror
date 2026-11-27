"""U14-S4: the ledger is wired to the controller: the FramelessTurns sink and the X-CUE subscription. Off: nothing is constructed."""
import asyncio
import json
import pathlib
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket

FIXTURE = pathlib.Path(__file__).parent / 'fixtures' / 'harvest' / '20261107-202918-5fa76eaa002d.json'


class Source:
    async def send(self, kind, payload=b''): pass
    async def close(self): pass


def _turn(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def _cue(c):
    c.provider(_turn('u', 'user', 'Почему меняются времена года?'))
    c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'source'}])
    return c.provider(_turn('a', 'assistant', getattr(c, 'answer_marker', '') + 'Наклон земной оси меняет освещение.'))[0]


def test_the_ledger_is_always_there_beside_the_state_file(tmp_path):
    """M9: memory is not a switch (the old test of ``conversation_ledger=off`` constructing nothing is gone with the key): the ledger stands, on disk in a folder of its own for this state file and session."""
    c = ControlledMedia(tmp_path / 's.db', session_id='s')
    assert c.convo is not None
    c.begin_call()
    _cue(c)
    assert [p.name for p in (tmp_path / 'conversation').iterdir()] == ['s.db-s']


def test_fake_socket_a_done_b_cut_at_half(tmp_path):
    async def run():
        async def emit(x): pass
        async def synth(text): return b'\x01\0' * 4800
        c = ControlledMedia(tmp_path / 's.db', session_id='s', settings={'words_per_portion': 3, 'conversation_ledger': 'memory'})
        async def connect(): return Source()
        wire = NativeMediaSocket(c, emit, connect, lambda _: None, synth); wire.ready = True
        cue = _cue(c)
        c.begin_call()
        cue_a, cue_b = dict(cue, text='раз два три четыре'), dict(cue, text='пять шесть семь восемь')
        c._cue_event('began', cue_a, 10.0, voiced=2.0)
        c._cue_event('done', cue_a, 12.0)
        c._cue_event('began', cue_b, 20.0, voiced=2.0)
        c._cue_event('cut', cue_b, 20.35 + 1.0)
        return c
    c = asyncio.run(run())
    plays = [r for r in c.convo._recs if r.kind == 'play']
    assert len(plays) == 2
    assert c.convo.heard(plays[0].ref) == ['раз', 'два', 'три', 'четыре']
    assert c.convo.heard(plays[1].ref) == ['пять', 'шесть']          # half of the voiced two seconds


def test_replay_202918_user_count_equals_finals_and_play_count_equals_cue_rows(tmp_path):
    fx = json.loads(FIXTURE.read_text(encoding='utf-8'))
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings={'conversation_ledger': 'memory'})
    c.begin_call()
    tids = []
    for at, kind, tid, text in fx['cloud']:
        if kind == 'user':
            c.provider(_turn(tid, 'user', text)); tids.append(tid)
    for i, (at, text, how) in enumerate(fx['cues']):
        cue = {'revision': 1, 'index': i, 'text': text}
        c._cue_event('began', cue, at)
        c._cue_event('done' if how == 'completed' else 'cut', cue, at + (3.0 if how == 'completed' else 0.5))
    users = [r for r in c.convo._recs if r.kind == 'user' and not r.superseded]
    assert len(users) == len(set(tids)) == fx['checks']['finals']
    assert len([r for r in c.convo._recs if r.kind == 'play']) == len(fx['cues']) == fx['checks']['cues']
    cut = [p for p in c.convo._plays.values() if p['end'] == 'cut']
    assert len(cut) == 6 and all(p['heard_n'] < len(p['words']) for p in cut if len(p['words']) > 1)


def test_revise_gives_two_answer_rows_with_supersedes_and_unplayed_is_not_heard(tmp_path):
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings={'conversation_ledger': 'memory'})
    c.begin_call()
    one, two, three = ({'revision': r, 'index': 0, 'text': t} for r, t in ((1, 'раз два три'), (2, 'четыре пять'), (3, 'шесть семь')))
    c._cue_event('began', one, 10.0, voiced=2.0); c._cue_event('done', one, 12.0)
    c._cue_event('began', two, 20.0, voiced=2.0); c._cue_event('done', two, 22.0)
    answers = [r for r in c.convo._recs if r.kind == 'answer']
    assert [a.ref for a in answers] == ['r1', 'r2'] and answers[0].superseded and not answers[1].superseded
    assert c.convo._recs[0].kind == 'answer' and c.convo._recs[1].kind == 'play'      # the row stands before the first play
    # revision 3 never began: no row, and none of its words are heard
    assert len([r for r in c.convo._recs if r.kind == 'answer']) == 2
    assert 'шесть' not in c.convo.played_words(20)
    c._cue_event('began', dict(two, index=1), 30.0, voiced=1.0)      # a second cue of the same revision: no new row
    assert len([r for r in c.convo._recs if r.kind == 'answer']) == 2
