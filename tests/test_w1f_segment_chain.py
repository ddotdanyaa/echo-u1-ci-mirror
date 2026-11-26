"""W1F-B, class C5 in the segment chain (W1 group G6, latent in w1_11): no foreign tail spliced onto an older cut segment.

w1_11 (W1 run 20261103-031522), reproduced offline with the transcript growing character by character as it does live:
- the answer was cut at «… Нельзя останавливаться»; the listener confirmed «У знака «Стоп»»;
- the cloud restarted: « Стоп. Окей, у знака «Стоп» нужно полностью остановиться перед стоп-линией». Deployed, the restart was dropped on
  the prefix « Стоп. Окей, у знака » (restart_unaligned: two of its first three content words were the confirmed portion's) - one
  character later the heard anchor знак→стоп would have aligned it (with word-sized deltas it does: restart_aligned);
- «Дальше» cut the restart, and its tail « или краем пересечения, не на зебре, не заехав на неё.» was taken for the rest of the OLD cut
  segment (its predecessor was the last ACCEPTED segment, not the last on the wire): «Нельзя останавливаться или краем пересечения» - the
  opposite of the traffic rule.

The rules now: a verdict that drops a restart is not taken while the heard anchor may still be completing at the end of its prefix (the
verdict must not depend on how the transport splits deltas); and a segment that goes on with a segment the controller dropped (its
predecessor on the wire) is dropped with it, never glued to an older one.
"""
import pytest

from helpers_w1f import Wire

SIGN_Q = 'Расскажи подробно, что нельзя делать у дорожного знака стоп и как его правильно проезжать'
SIGN_A1 = ' У знака «Стоп» нельзя просто притормозить на ходу и проскочить, даже если дорога кажется пустой. Нельзя останавливаться'
SIGN_A2 = ' Стоп. Окей, у знака «Стоп» нужно полностью остановиться перед стоп-линией'
SIGN_A3 = ' или краем пересечения, не на зебре, не заехав на неё.'


def sign(tmp_path, how):
    w = Wire(tmp_path)
    w.user('u1', SIGN_Q, 5.2, 12.4)
    w.assistant('a1', SIGN_A1, 12.4, 18.0)
    w.user('u2', ' У знака стоп', 18.05, 19.6)
    if how == 'chars':
        cuts = list(range(6, len(SIGN_A2) + 1))
        w.assistant('a2', SIGN_A2, 20.2, 23.8, grow=cuts, times=[20.2 + n * 0.05 for n in range(len(cuts))])
    else:
        w.assistant('a2', SIGN_A2, 20.2, 23.8)
    w.user('u3', ' Дальше', 23.83, 24.6)
    w.assistant('a3', SIGN_A3, 24.63, 28.9)
    return w.until(40.0)


@pytest.mark.parametrize('how', ['chars', 'words'])
def test_the_tail_of_a_restart_is_never_glued_to_the_old_cut_segment(tmp_path, how):
    w = sign(tmp_path, how)
    assert 'останавливаться или краем' not in w.plan(), w.plan()       # deployed (chars): the meaning of the rule inverted


def test_the_verdict_on_a_restart_does_not_depend_on_how_its_deltas_were_cut(tmp_path):
    plans = [sign(tmp_path / how, how).plan() for how in ('chars', 'words')]
    assert plans[0] == plans[1], plans
