"""W1F-B, class C4 (W1 groups G4 TR-AUTOREPEAT, G5, G6, G7 sc01): the silence auto-repeat is re-armed only by silence.

Deployed (66b29f1) every final that spoke nothing re-armed the 6-s timer (controlled_media.py, «a barge-in can cancel synthesis before its
first byte»): a connection check («Слушай, ты меня хорошо слышишь»), thanks, a bystander, a command the classifier did not know («Стой,
подожди секунду») - each was followed 6 s later by the stale portion spoken over the listener (w1_12 step 3 at +6.1 s, w1_10 steps 2 and 7,
w1_09 step 2, w1_14 step 1, sc01 step 3), and the cap it spent left dead air after a real request.

The rule now: the timer runs again after silence (the end of a cue's playout, a start of speech that never became a transcript, a final
that carries nothing but fillers) or after a real try at the portion (an attempt_* verdict); never after an utterance the classifier could
not place. Under on_mismatch='silent' the classifier folds all of those into one reason, 'mismatch_policy_silent'; the controller logs
the sub-reason it stands for (``attempt_shared_stem``, ``unrelated_speech``, ``weak_question_ignored`` …) so the sink is measurable.
"""
import logging

import pytest

from helpers_w1f import Wire

LAKE_Q = 'Расскажи про самые глубокие озера в мире'
LAKE_A = ' Самое глубокое — это Байкал в России, примерно 1642 метра глубины.'


def lake(tmp_path, said, reply=' Да, слышу тебя отлично.'):
    """The first portion is played and heard to its end; before the timer runs out the listener says ``said`` and the cloud replies."""
    w = Wire(tmp_path)
    w.user('u1', LAKE_Q, 0.0, 2.0)
    w.assistant('a1', LAKE_A, 2.01, 3.5)
    w.user('u2', said, 4.5, 6.5)
    if reply:
        w.assistant('a2', reply, 6.55, 8.0)
    return w.until(17.0)


@pytest.mark.parametrize('said', [' Слушай, ты меня хорошо слышишь', ' Ты меня вообще слышишь', ' Спасибо, ты молодец',
                                  ' Мы вчера ходили в кино, там было шумно', ' Стой, подожди секунду'],
                         ids=['connection_check', 'connection_check_2', 'thanks', 'bystander', 'stop_like'])
def test_speech_the_classifier_cannot_place_never_brings_the_stale_portion_back(tmp_path, said):
    w = lake(tmp_path, said)
    first = w.played[0][1] if w.played else None
    assert first and first.startswith('Самое глубокое'), w.played    # the first portion (its exact cut is the portioner's)
    assert w.played_after(6.5) == [], w.played            # deployed: the same portion again 6 s after the final
    assert w.state().get('chunk_index') == 0


def test_a_slow_final_of_other_speech_takes_back_the_timer_its_silence_armed(tmp_path):
    """sc01: the provider took 4.2 s to finalise a turn whose words had arrived at once, so the listener's flag expired first (2.5 s) and
    armed the timer. The final then says it was speech the classifier cannot place: the timer is taken back (a turn that never ends
    keeps it: tests/test_s6_state_machine.py, the call is never left listening for good)."""
    said = ' Мы вчера ходили в кино, там было шумно'
    w = Wire(tmp_path)
    w.user('u1', LAKE_Q, 0.0, 2.0)
    w.assistant('a1', LAKE_A, 2.01, 3.5)
    w.user('u2', said, 4.5, 8.7, grow=[len(said)], times=[4.5])
    w.until(20.0)
    assert w.played_after(4.5) == [], w.played                # deployed: the portion again 6 s after the expiry (13.0 s)


@pytest.mark.parametrize('said', [' Самое глубокое', ' Э', ' Ну'], ids=['a_try_at_the_portion', 'noise', 'filler'])
def test_a_real_try_or_mere_noise_still_brings_the_portion_back_after_the_silence(tmp_path, said):
    w = lake(tmp_path, said, reply=None)
    again = w.played_after(6.5)
    # G3, rule 3 (changed on purpose): after a try at its start only what is missing of the portion is said
    assert len(again) == 1 and w.played[0][1].endswith(again[0]) and again[0].startswith('Самое глубокое') is ('глубокое' not in said), w.played
    assert 6.5 + 5.9 <= next(at for at, _ in w.played if at >= 6.5) <= 6.5 + 6.3


@pytest.mark.parametrize('said,detail', [(' Мы вчера ходили в кино, там было шумно', 'unrelated_speech'),
                                         (' Самое глубокое озеро', 'attempt_shared_stem')])
def test_the_mismatch_sub_reason_is_logged(tmp_path, said, detail, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    lake(tmp_path, said, reply=None)
    lines = [record.getMessage() for record in caplog.records if 'mismatch' in record.getMessage()]
    assert any(f'reason={detail}' in line for line in lines), lines


@pytest.mark.parametrize('partial,arms', [(' Мы вчера ходили в кино', False), (' Самое глубокое', True)],
                         ids=['other_speech', 'a_try'])
def test_the_quiet_observation_of_a_stalled_partial_arms_the_timer_only_for_a_try(tmp_path, partial, arms):
    """The transport's 3-s quiet observation (``partial_quiet``) of a partial nobody finishes is still reported to the phone; it arms
    the timer for a try at the portion, never for other speech."""
    w = Wire(tmp_path)
    w.user('u1', LAKE_Q, 0.0, 2.0)
    w.assistant('a1', LAKE_A, 2.01, 3.5)
    w.until(9.0)
    w.c.repeat_at = None                                  # whatever the playout armed is not what this observation does
    w.c.provider({'type': 'turn.created', 'turn': {'id': 'u2', 'role': 'user', 'transcript': partial}})
    assert w.c.partial_quiet(now=12.0)
    assert (w.c.repeat_at == 12.0 + w.c.repeat_seconds) if arms else w.c.repeat_at is None, w.c.repeat_at
