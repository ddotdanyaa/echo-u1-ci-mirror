"""F3 (sc03 step 3, run 20261102-123343): «Сколько ног у паука? Нет, подождите, я хотел спросить про насекомое.»

The cloud heard ONE breath as three turns: « Сколько ног у паука» | « Нет, подождите, я хотел спросить про» | « насекомое». The first was
answered at once («Восемь.», its cue cut by the barge-in before any audio); the self-correction was classified
``silent/mismatch_policy_silent`` against the waiting «Восемь.», the model's corrected answer («У насекомых шесть» + « ног.») was
dropped as the reply to a non-question turn, and the silence timer re-spoke the stale «Восемь.» 3 s after the last final.
"""
import pytest

import helpers_s6_ack as H
from helpers_s6_seg import HOST_KWARGS
from echo_sync.classifier import CLARIFY_REPAIR, CORRECTION, QUESTION, QUIET, REPLAY, analyze
from echo_sync.controlled_media import ControlledMedia

PROD = H.PROD_SETTINGS
WAITING = H.waiting('Восемь.')


@pytest.mark.parametrize('text', [
    ' Нет, подождите, я хотел спросить про',                          # sc03 step 3, provider turn 2 (its object is turn 3)
    'Нет, подождите, я хотел спросить про насекомое',
    ' Нет, подождите, я хотел спросить про Вторую мировую войну',     # sc03 step 1, provider turn 2
    'Ой, нет, я хотела спросить про кита',
    'Подождите, я имел в виду насекомое',
])
def test_a_self_correction_of_the_question_is_a_new_turn_while_an_answer_waits(text):
    d = analyze(text, WAITING, [], PROD)
    assert d.kind in (CORRECTION, QUESTION) and d.question.strip() == text.strip(), d


@pytest.mark.parametrize('text,portion', [
    ('Он сказал нет я хотел спросить про погоду', 'Восемь.'),        # reported speech, not one's own repair: anchored at the start
    ('Мы вчера хотели спросить про погоду', 'Восемь.'),
    ('Я хотел спросить', 'Восемь.'),                                 # nothing to ask about: no new turn
    ('я хотел спросить про', 'Я хотел спросить про погоду'),        # a quotation of the waiting portion stays an attempt
])
def test_the_repair_vocabulary_does_not_swallow_background_talk_or_quotations(text, portion):
    assert analyze(text, H.waiting(portion), [], PROD).kind in (QUIET, REPLAY, CLARIFY_REPAIR)


def _ev(typ, tid, role, text):
    return {'type': typ, 'turn': {'id': tid, 'role': role, 'transcript': text}}


def test_sc03_step3_a_correction_split_over_provider_turns_never_dictates_the_stale_answer(tmp_path):
    """The live frames of sc03 step 3 on the probe clock (seconds), through the controller built like controlled_host."""
    now = [0.0]
    c = ControlledMedia(tmp_path / 's.sqlite3', session_id='native-probe-' + '0' * 32, clock=lambda: now[0], **HOST_KWARGS)
    spoken = []

    def at(t, actions=()):
        now[0] = t
        spoken.extend((t, a['text']) for a in actions if a['type'] == 'speak')

    # the call already had a question and its answer (sc03 steps 1-2)
    at(10.0); c.speech_started(); c.provider(_ev('turn.created', 'p1', 'user', 'В каком'))
    at(10.9, c.provider(_ev('turn.done', 'p1', 'user', 'В каком году началась Вторая мировая война?')))
    c.provider(_ev('turn.created', 'pa', 'assistant', 'Она началась в 1939 году.'))
    at(11.3, c.provider(_ev('turn.done', 'pa', 'assistant', 'Она началась в 1939 году.')))
    # step 3
    at(29.9); c.speech_started(); c.provider(_ev('turn.created', 'u1', 'user', ' Сколько'))
    at(32.822, c.provider(_ev('turn.done', 'u1', 'user', ' Сколько ног у паука')))
    at(32.823, c.provider(_ev('turn.created', 'a1', 'assistant', 'Восемь.')))
    at(33.244, c.provider(_ev('turn.done', 'a1', 'assistant', 'Восемь.')))
    # 23 ms later the listener goes on speaking: the transport cuts the «Восемь.» cue before its first PCM frame (live: clear at 33268)
    at(33.267); c.speech_started(); c.provider(_ev('turn.created', 'u2', 'user', ' Нет,'))
    spoken.clear()
    for t, piece in ((34.518, ' подождите,'), (35.089, ' я'), (35.482, ' хотел'), (36.202, ' спросить про')):
        at(t, c.tick(now=t)); c.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': piece})
    at(37.233, c.provider(_ev('turn.done', 'u2', 'user', ' Нет, подождите, я хотел спросить про')))
    at(37.233, c.provider(_ev('turn.created', 'a2', 'assistant', 'У насекомых')))
    at(37.48, c.provider(_ev('turn.done', 'a2', 'assistant', 'У насекомых шесть')))
    at(37.497); c.speech_started(); c.provider(_ev('turn.created', 'u3', 'user', ' насекомое'))
    at(38.156, c.provider(_ev('turn.done', 'u3', 'user', ' насекомое')))
    at(38.157, c.provider(_ev('turn.created', 'a3', 'assistant', ' ног.')))
    at(39.946, c.provider(_ev('turn.done', 'a3', 'assistant', ' ног.')))
    for k in range(1, 141):                                   # 7 s of ticks after the last event (live: «Восемь.» at 41.301)
        t = round(39.946 + k * 0.05, 3)
        at(t, c.tick(now=t))
    assert not any('Восемь' in text for _, text in spoken), spoken
    assert any('шесть' in text for _, text in spoken), spoken
