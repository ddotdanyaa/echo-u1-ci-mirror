"""W1F-B, class C2 while an older answer waits (W1 group G7 sc01, G5 w1_14 step 3): pieces of one question, each nothing alone.

sc01 step 3 (v1 run 20261103-030307): «Объясни одним предложением, что такое конденсация.» while «Это конденсация.» waited. The cloud's
VAD closed the turn at a 360-ms comma pause (« Объясни», final 107.120 s), it began its answer there (« Конденсация — это когда газ
охлаждается и его молекулы», cut) and transcribed the rest as « Кандса» (created 109.667, final 113.922), after which it went on with its
cut sentence (« теряют энергию, …»). Deployed: both finals were failed repeats (mismatch_policy_silent), both replies were dropped, and the
silence timer said «Это конденсация.» again. w1_14 step 3 is the same shape («А откуда взялось» | «Такое название у этой науки»).

The rule now: a QUIET final that began within ``coalesce_seconds`` of the previous QUIET final is joined with it (at most three pieces) and
judged again; a question the joined text makes is accepted as one. The cloud's reply to the first piece, cut mid-sentence and asking
nothing back, is where the answer begins: its next segment is weighed against it as usual (joined, or taking its place).
"""
from helpers_w1f import Wire

TERM_Q = 'Как называется переход вещества из газообразного состояния в жидкое'


def term_answer_waits(tmp_path):
    w = Wire(tmp_path)
    w.user('u1', TERM_Q, 95.784, 101.873)
    w.assistant('a1', ' Это конденсация.', 101.880, 103.765)
    return w


def test_sc01_a_question_cut_into_two_short_finals_is_answered_as_one(tmp_path):
    w = term_answer_waits(tmp_path)
    w.user('u2', ' Объясни', 106.269, 107.120)
    w.assistant('a2', ' Конденсация — это когда газ охлаждается и его молекулы', 107.121, 109.662)
    w.user('u3', ' Кандса', 109.667, 113.922)
    w.assistant('a3', ' теряют энергию, начинают сближаться и превращаются в жидкость.', 113.923, 115.181)
    w.until(125.0)
    later = w.played_after(106.269)
    assert later and 'Это конденсация.' not in later, w.played                # deployed: only the auto-repeat at 120.1 s
    assert 'Конденсац' in later[0] or 'газ' in later[0], later           # the answer the cloud began after the first piece
    assert w.plan().endswith('превращаются в жидкость.'), w.plan()
    assert w.c.question_id == 'u3' and 'Объясни' in w.c.question_text


def test_w1_14_a_follow_up_cut_into_two_finals_is_one_question(tmp_path):
    w = Wire(tmp_path)
    w.user('u1', 'Как называется наука, которая изучает грибы', 20.0, 26.725)
    w.assistant('a1', ' Микология.', 26.739, 28.129)
    w.user('u2', ' А откуда взялось', 30.531, 32.197)
    w.assistant('a2', ' Слово «микология» от греческих «mykes»', 32.198, 34.820)
    w.user('u3', ' Такое название у этой науки', 34.833, 37.367)
    w.assistant('a3', ' Да. Оно произошло от греческого «mykes» — гриб, и «logos» — учение.', 37.368, 42.116)
    w.until(50.0)
    later = w.played_after(30.531)
    assert later and 'Микология.' not in later, w.played                      # deployed: the auto-repeat «Микология.» at 43.5 s
    assert 'греческ' in w.plan(), w.plan()
    assert w.c.question_id == 'u3'


def test_two_unrelated_remarks_in_a_row_stay_quiet(tmp_path):
    """Negative control: pieces that make no question when joined stay what they were (quiet), whatever the cloud replies."""
    w = term_answer_waits(tmp_path)
    w.user('u2', ' Мы вчера ходили', 106.269, 107.120)
    w.assistant('a2', ' Угу, и как?', 107.121, 108.0)
    w.user('u3', ' в кино с друзьями', 108.5, 109.9)
    w.assistant('a3', ' Здорово, надеюсь, понравилось.', 109.95, 111.0)
    w.until(125.0)
    assert w.c.question_id == 'u1' and w.played_after(106.269) == [], w.played
