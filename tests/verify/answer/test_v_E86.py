"""V3 E86 (``two_witnesses``): sound without waiting for the final when the ear and the STABLE piece of the cloud agree; a piece that disagrees (the ear misheard the number) never lets the ear's answer sound.

Real ControlledMedia and wire (rig of test_repeat_cases ``rig_of``: the candidate profile with ``two_witnesses`` on; the reference base answers «Семнадцатая статья Налогового кодекса» with «Статья 17 Налогового кодекса»).
The backlog says «дизайн, кода нет», the code has ``cm_kind._two_witnesses``: this is the first check of it on the wire. The expectations are the backlog's, not a measurement: a red row is a card for K/P. Not run on the laptop."""
import helpers_s6_state as S
from answer_kit import TICK, call, texts      # noqa: F401
from test_h3_tempo import ASKED, HEAD
from test_repeat_cases import rig_of

EAR_17 = 'семнадцатая статья налогового кодекса'
OTHER = 'Восемнадцатая статья Налогового кодекса'


def stable_piece(rig, text):
    """The cloud's open turn: two deltas that agree (a stable piece), no final."""
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_delta('u1', text, 1))
    rig.pump(0.3)
    rig.w.feed(S.turn_delta('u1', '', 2))
    rig.pump(0.3)


def test_the_ear_and_the_stable_piece_agree_the_hint_sounds_before_the_final(call):
    rig = rig_of(call)
    rig.says(EAR_17, speech=1.4)
    stable_piece(rig, ASKED)
    rig.pump(1.0)
    assert texts(rig)[:1] == [HEAD], f'no final yet: {texts(rig)}'


def test_the_stable_piece_that_names_another_article_never_lets_the_ears_answer_sound(call):
    rig = rig_of(call)
    rig.says(EAR_17, speech=1.4)
    stable_piece(rig, OTHER)
    rig.pump(1.5)
    assert HEAD not in texts(rig), f'the ear\'s 17 sounded over the cloud\'s 18: {texts(rig)}'
