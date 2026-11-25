"""W1F-B, class C2 (W1 groups G2, G5 w1_14): one utterance, one decision.

The provider splits one breath into several user turns at its short pauses («Сколько …, если комната четыре на пять метров» | « Нет» |
«, подождите. Комната пять на шесть метров»). Deployed (66b29f1) the controller decided per fragment: the lone «Нет» was accepted alone,
which released the hearing latch, and the cloud's next segment («.») closed the unpublished answer to the UNCORRECTED first half, so its
first cue played while the listener was still talking; the correction was then judged against that stale portion (a failed repeat,
mismatch_policy_silent), the cloud's corrected reply was muted as a reply to a turn that was not the question, and the silence timer spoke
the stale portion again. The same class answered a question split at a mid-question pause («Как называется наука, которая изучает» |
« грибы») as its fragment.

The rule now: the question is still being spoken or corrected while a user turn that began within ``coalesce_seconds`` of the previous
final of the same utterance is open; before the first cue the answer is held then (bounded by MERGE_PATIENCE_SECONDS and the answer cap); a
fragment that continues the question is judged with the joined utterance, never against the stale portion; after the first cue it still
joins while the listener has confirmed nothing, and then the stale answer is retired, never restored.

The frames are the probe-clock frames of the W1 run 20261103-031522 (w1_05 step 1, call 06a85fb91dd0; w1_14 step 1) and of the v1 run
20261103-030307 (sc03 step 1, call 01373c8b45e4), as the analysts' offline replays reproduced them through the same controller.
"""
import logging

import pytest

from helpers_w1f import Wire

ROOM_Q = 'Сколько это квадратных метров, если комната четыре на пять метров'
ROOM_Q_GROW = ([7, 11, 22, 29, 35, 43, 50, 53, 58, 65], [5.123, 5.213, 6.018, 6.622, 7.433, 8.093, 8.233, 8.689, 8.830, 9.793])
ROOM_FIX = ', подождите. Комната пять на шесть метров'
ROOM_FIX_GROW = ([8, 11, 20, 25, 28, 34, 41], [12.222, 12.362, 13.031, 13.382, 13.658, 14.112, 14.650])
ROOM_A3 = ' Ага. Тогда пять на шесть — это тридцать квадратных метров.'
ROOM_A3_GROW = ([16, 25, 31, 40, 51, 59], [15.551, 15.714, 16.159, 16.420, 16.964, 17.820])


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def room(tmp_path, *, dot=True, fix=ROOM_FIX, joined=False, reply=ROOM_A3):
    """w1_05 step 1 as it was played (``dot``: the cloud's 1-character segment «.» after the lone «Нет»; ``joined``: the provider kept
    «Нет, подождите…» in one turn)."""
    w = Wire(tmp_path)
    w.user('u1', ROOM_Q, 5.123, 10.663, grow=ROOM_Q_GROW[0], times=ROOM_Q_GROW[1])
    w.assistant('a1', ' Четыре на пять — это двадцать', 10.6635, 11.072, grow=[17, 30], times=[10.6635, 10.843])
    if joined:
        whole = ' Нет' + fix
        grow = ([4] + [n + 4 for n in ROOM_FIX_GROW[0]], [11.089] + ROOM_FIX_GROW[1]) if fix == ROOM_FIX else (None, None)
        w.user('u3', whole, 11.089, 15.534, grow=grow[0], times=grow[1])
    else:
        w.user('u2', ' Нет', 11.089, 11.782, grow=[4], times=[11.089])
        if dot:
            w.assistant('a2', '.', 11.784, 12.208, grow=[1], times=[11.784])
        grow = ROOM_FIX_GROW if fix == ROOM_FIX else (None, None)
        w.user('u3', fix, 12.222, 15.534, grow=grow[0], times=grow[1])
    w.assistant('a3', reply, 15.551, 19.628, **(dict(grow=ROOM_A3_GROW[0], times=ROOM_A3_GROW[1]) if reply == ROOM_A3 else {}))
    return w.until(23.5)


def assert_bound_to_the_correction(w, wrong=('Четыре на пять', 'двадцать'), right='тридцать'):
    played = [text for _, text in w.played]
    assert not any(stale in text for text in played for stale in wrong), played      # deployed: «Четыре на пять —» at 11.784 and 21.550
    assert right in ' '.join(played) or right in w.plan(), (played, w.plan())
    assert w.c.question_id not in ('u1', None), w.c.question_id                     # deployed: u1, the uncorrected half
    assert w.c.owners.get('a3') == w.c.question_id, w.c.owners                      # the corrected reply answers the question


def test_w1_05_a_condition_fixed_in_speech_never_dictates_the_stale_answer(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = room(tmp_path)
    assert_bound_to_the_correction(w)
    assert 'пять на шесть' in w.c.question_text and 'четыре на пять' in w.c.question_text   # the whole utterance is the question
    lines = [record.getMessage() for record in caplog.records]
    assert any('reason=utterance_goes_on' in line for line in lines), lines                 # the lone «Нет» waited for the rest


def test_a_retransmitted_final_is_never_taken_for_the_rest_of_the_question(tmp_path):
    """S4 (helpers_s6_state.replay_last_ack): a final delivered again on a new call, with no announcement before it, has no known start:
    it never goes on with the question asked just before it."""
    w = Wire(tmp_path)
    w.user('u1', 'Что такое инерция', 1.0, 3.0)
    w.at(3.05, {'type': 'turn.done', 'turn': {'id': 'old-ack', 'role': 'user', 'transcript': 'Нет, кит не рыба,'}})
    w.until(4.0)
    assert w.c.question_id == 'u1' and w.c.question_text == 'Что такое инерция', (w.c.question_id, w.c.question_text)


@pytest.mark.parametrize('shape', ['without_the_dot_segment', 'one_provider_turn'])
def test_w1_05_the_same_correction_in_the_other_split_shapes(tmp_path, shape):
    w = room(tmp_path, dot=shape != 'without_the_dot_segment', joined=shape == 'one_provider_turn')
    assert_bound_to_the_correction(w)


@pytest.mark.parametrize('fix', [', вернее, пять на шесть метров', ', точнее, пять на шесть', ', ой, не так, пять на шесть метров'],
                         ids=['vernee', 'tochnee', 'oi_ne_tak'])
def test_w1_05_other_wordings_of_the_correction(tmp_path, fix):
    w = room(tmp_path, fix=fix, reply=' Тогда пять на шесть — это тридцать квадратных метров.')
    assert_bound_to_the_correction(w)


@pytest.mark.parametrize('cut', [' Три билета по двести', ' Три билета по двести — это шестьсот'], ids=['cut_early', 'cut_late'])
def test_a_price_fixed_in_speech_the_same_way(tmp_path, cut):
    """One more template: a price, the provider's split, the stale reply cut and closed by a lone «.». A first cue of it that went out
    BEFORE the listener said a word (``cut_late``: the cloud was fast) is legitimate; nothing of it may follow once they began to correct."""
    w = Wire(tmp_path)
    w.user('u1', 'Сколько стоят три билета по двести рублей', 1.0, 4.0)
    w.assistant('a1', cut, 4.001, 4.3 if cut == ' Три билета по двести' else 4.6)
    w.user('u2', ' Нет', 4.62, 5.2)
    w.assistant('a2', '.', 5.202, 5.6)
    w.user('u3', ', подождите, четыре билета по двести рублей', 5.65, 8.4)
    w.assistant('a3', ' Четыре билета по двести рублей — это восемьсот рублей.', 8.42, 10.5)
    w.until(18.0)
    stale = [text for text in w.played_after(4.62) if 'Три билета' in text or 'шестьсот' in text]
    assert not stale, w.played
    assert 'восемьсот' in w.plan() or any('восемьсот' in text for _, text in w.played), (w.played, w.plan())
    assert w.c.question_id == 'u3' and w.c.owners.get('a3') == 'u3', (w.c.question_id, w.c.owners)
    assert 'Три билета' not in w.plan() and 'шестьсот' not in w.plan(), w.plan()


SC03_Q = 'В каком году началась Первая мировая война'


def test_sc03_the_stale_year_is_never_played_while_the_listener_corrects_the_question(tmp_path):
    w = Wire(tmp_path)
    w.user('u1', SC03_Q, 5.494, 9.388)
    w.assistant('a1', ' В 1914 году', 9.389, 9.854, grow=[7, 12], times=[9.389, 9.6])
    w.user('u2', ' Нет', 9.861, 10.300, grow=[4], times=[9.861])
    w.assistant('a2', '.', 10.303, 10.798, grow=[1], times=[10.303])
    w.user('u3', ', подождите, я хотел спросить про Вторую мировую войну', 10.813, 15.066)
    w.assistant('a3', ' А, понял — Вторая началась в 1939.', 15.081, 17.499)
    w.until(22.0)
    played = [text for _, text in w.played]
    assert not any('1914' in text for text in played), played                     # deployed: «В 1914 году.» at 10.303
    assert '1939' in w.plan() or any('1939' in text for text in played), (played, w.plan())
    assert w.c.owners.get('a3') == w.c.question_id


MYCO_Q = ' Как называется наука, которая изучает'


def mycology(tmp_path, *, tail=' грибы', reply=', язык...? Грибы изучает микология.', tail_start=12.366, tail_end=13.142):
    w = Wire(tmp_path)
    w.user('u1', MYCO_Q, 6.333, 10.485)
    w.assistant('a1', ' Что именно? Живые организмы, звёзды', 10.486, 12.358, grow=[11, 17, 26, 36], times=[10.486, 11.2, 11.9, 12.1])
    w.user('u2', tail, tail_start, tail_end)
    w.assistant('a2', reply, tail_end + 0.001, 17.528)
    return w.until(26.0)


def test_w1_14_a_question_split_at_a_pause_is_one_question_even_after_the_first_cue(tmp_path):
    w = mycology(tmp_path)
    first = w.played[0][1] if w.played else ''
    assert first and not first.startswith('Что именно?'), w.played     # live: the counter-question went out before « грибы»; since C10 it is never cued
    later = w.played_after(13.142)
    assert first not in later, w.played                                     # deployed: the silence timer said it again at 19.3 s
    assert any('миколог' in text for text in later) or 'миколог' in w.plan(), (w.played, w.plan())
    assert w.c.question_text.rstrip().endswith('изучает грибы'), w.c.question_text
    assert 'язык' not in w.plan() and 'организмы' not in w.plan(), w.plan()   # nothing of the counter-question's cut sentence
    # One utterance: the answer to its unfinished first half is not noted to the model as «left unsaid» (ruling 5a).
    assert w.c.note_due is None and w.c.noted_text is None, (w.c.note_due, w.c.noted_text)


def test_an_independent_question_right_after_is_never_glued_to_the_first(tmp_path):
    """Negative control: a question that opens with its own question word is its own question, however soon it comes."""
    w = mycology(tmp_path, tail=' Какой город является столицей Японии', reply=' Токио.')
    assert w.c.question_text.strip() == 'Какой город является столицей Японии', w.c.question_text
    assert 'Токио.' in [text for _, text in w.played]


def test_a_wrong_number_repeat_of_the_first_cue_stays_a_try_at_it(tmp_path):
    """Negative control (w1_03, sc04): «Пять на пять» for the heard «Четыре на пять —» overlaps only the portion and opens with no
    correction: a slip in the repeat, never a new question, however soon after the question it comes."""
    w = Wire(tmp_path)
    w.user('u1', 'Сколько будет четыре на пять', 1.0, 3.0)
    w.assistant('a1', ' Четыре на пять — это двадцать.', 3.001, 3.4)
    w.user('u2', ' Пять на пять', 4.6, 5.6)
    w.until(9.0)
    assert w.played and w.played[0][1].startswith('Четыре на пять'), w.played
    assert w.c.question_id == 'u1' and w.state().get('chunk_index') == 0


def test_a_lone_no_that_nothing_follows_does_not_lose_the_answer(tmp_path):
    """Bounded: «Нет» after the question holds the first cue for the window only; when the listener says nothing more, the answer that
    did arrive is dictated."""
    w = Wire(tmp_path)
    w.user('u1', 'Сколько будет семь умножить на восемь', 1.0, 3.0)
    w.assistant('a1', ' Пятьдесят шесть', 3.001, 3.5)
    w.user('u2', ' Нет', 3.52, 4.1)
    w.assistant('a2', '.', 4.102, 4.3)
    w.until(20.0)
    assert any('Пятьдесят шесть' in text for _, text in w.played), w.played
