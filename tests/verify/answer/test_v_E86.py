"""V3 E86 (``two_witnesses``): sound without waiting for the final when the ear and the STABLE piece of the cloud agree; a piece that disagrees (the ear misheard the number) never lets the ear's answer sound.

Real ControlledMedia and wire (rig of test_repeat_cases ``rig_of``: the candidate profile with ``two_witnesses`` on; the reference base answers «Семнадцатая статья Налогового кодекса» with «Статья 17 Налогового кодекса»).
The backlog says «дизайн, кода нет», the code has ``cm_kind._two_witnesses``: this is the first check of it on the wire. The expectations are the backlog's, not a measurement: a red row is a card for K/P. Not run on the laptop.
Order of events: a second witness is judged when the cloud's stable piece is THERE when the ear's text arrives (the cloud's turn opens with the speech, as on the phone). With no turn of the cloud open at all the base's own answer to a question stands on the ear alone, a number too (h28/h29: tests/test_h29_call.py ``test_a_bank_question_with_a_number_needs_no_cloud``, the owner's call of 07.11 910 s: «the article of the base came on the seventh second»): the cue names it and the final corrects it (``_ear_first_overruled``); there the ear's text before any piece of the cloud is no disagreement to wait for."""
import helpers_s6_state as S
from answer_kit import TICK, call, texts      # noqa: F401
from test_h3_tempo import ASKED, HEAD
from test_repeat_cases import rig_of

EAR_17 = 'семнадцатая статья налогового кодекса'
OTHER = 'Восемнадцатая статья Налогового кодекса'


def says_over(rig, ear, cloud, speech=1.4, lag=0.15):
    """One utterance of 1.4 s: the cloud's open turn is up during the speech (a stable piece: two deltas that agree, no final), the ear's text comes after the end of speech."""
    uid = rig.onset()
    rig.pump(0.3)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_delta('u1', cloud, 1))
    rig.pump(0.3)
    rig.w.feed(S.turn_delta('u1', '', 2))
    rig.pump(speech - 0.6)
    rig.offset()
    rig.pump(lag)
    rig.worker.heard(uid, ear)
    rig.pump(TICK)


def test_the_ear_and_the_stable_piece_agree_the_hint_sounds_before_the_final(call):
    rig = rig_of(call)
    says_over(rig, EAR_17, ASKED)
    rig.pump(1.0)
    assert texts(rig)[:1] == [HEAD], f'no final yet: {texts(rig)}'


def test_the_stable_piece_that_names_another_article_never_lets_the_ears_answer_sound(call):
    rig = rig_of(call)
    says_over(rig, EAR_17, OTHER)
    rig.pump(1.5)
    assert HEAD not in texts(rig), f'the ear\'s 17 sounded over the cloud\'s 18: {texts(rig)}'
