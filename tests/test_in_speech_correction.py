"""F2-glued: sc03 step 1, call f400e85c9adc (2026-11-02 12:39), replayed offline on the production controller wiring.

The provider split ONE utterance into two user turns. The model began to answer the first half and was cut when the listener
went on ("Она началась": no terminal punctuation, nothing published - the first-useful gate held it as an echo). The second
turn " Нет, подождите, я хотел спросить про Вторую мировую войну" was classified silent/not_a_question, so the question stayed
the first half, and the model's NEW reply to the correction ("А, понятно — Вторая мировая началась в 1939 году.") was taken for
the continuation of the cut segment (_continues_cut_answer) and glued to it as raw wire text (_source): «Она началасьА,».
"""
import ast
from pathlib import Path

import echo_sync
from echo_sync.classifier import CORRECTION, QUESTION, analyze
from echo_sync.controlled_media import ControlledMedia


def _host_kwargs():
    """What controlled_host.serve passes to ControlledMedia (the same ast read as tests/helpers_s6_ack.py)."""
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    call = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'ControlledMedia')
    return {k.arg: ast.literal_eval(k.value) for k in call.keywords if isinstance(k.value, ast.Constant)}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def created(tid, role, text=''):
    return {'type': 'turn.created', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def done(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


QUESTION_1 = 'В каком году началась Первая мировая война?'
CORRECTION_2 = ' Нет, подождите, я хотел спросить про Вторую мировую войну'   # exactly as the provider finalised it


def test_a_spoken_reformulation_of_the_question_is_a_new_question_even_before_any_answer_exists():
    decision = analyze(CORRECTION_2, None, [], None)
    assert decision.kind in (QUESTION, CORRECTION), decision          # deployed: silent/not_a_question


def test_the_reply_to_an_in_speech_correction_is_never_glued_to_the_cut_reply_to_the_first_half(tmp_path):
    clock = Clock()
    c = ControlledMedia(tmp_path / 'sc03.sqlite3', session_id='native-probe-' + '0' * 32, clock=clock, **_host_kwargs())
    c.speech_started()
    c.provider(created('u1', 'user', 'В'))
    clock.now += 3.894
    c.provider(done('u1', 'user', QUESTION_1))                          # 10.884 s of the probe
    clock.now += 0.006
    c.provider(created('a1', 'assistant', 'Она началась'))              # 10.890 s: the model answers the first half
    clock.now += 0.285
    c.provider(done('a1', 'assistant', 'Она началась'))                 # 11.175 s: cut, the listener goes on
    clock.now += 0.036
    c.speech_started()
    c.provider(created('u2', 'user', ' Нет'))                           # 11.211 s
    clock.now += 5.470
    c.provider(done('u2', 'user', CORRECTION_2))                        # 16.681 s
    clock.now += 0.003
    actions = c.provider(created('a2', 'assistant', 'А, понятно — Вторая'))   # 16.684 s: the model's NEW reply
    spoken = [a['text'] for a in actions if a['type'] == 'speak']
    # deployed: spoken == ['Она началасьА,'], owners == {'a1': 'u1', 'a2': 'u1'}, question_id == 'u1'
    assert not any('началасьА' in text or text.startswith('Она началась') for text in spoken), spoken
    assert c.question_id == 'u2', 'the listener corrected the question in the same breath: the correction is the question now'
    assert c.owners.get('a2') == 'u2', 'the reply that began after the correction answers the correction'
    assert 'началасьА' not in ((c.state() or {}).get('answer') or '')
