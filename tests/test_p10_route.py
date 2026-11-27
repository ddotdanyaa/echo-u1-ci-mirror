"""P10 (family R, ``reserve_text.Roads``): the kept job (F2). Through the real ``FastText`` over ``Roads``."""
from helpers_fast_fake import channel, open_question, until

from echo_sync import fast_text as FT
from echo_sync import reserve_text as RT


def kinds(events):
    return [e['kind'] for e in events]


# ---- F2: the kept job stands as long as the roads let a job stand ----------------------------------------------------------------------------
def test_a_kept_job_is_not_killed_at_first_text_s_and_is_let_go_at_the_give_up_of_the_roads():
    fast, fake, clock = channel()
    fast.wide = True
    assert fast.prepare('Что такое инерция?') is True
    assert fast.prepare('Сколько будет пять на пять?') is True
    assert until(lambda: len(fake.runs) == 2)
    clock.t += FT.FIRST_TEXT_S + 0.1
    fast.poll()
    assert fast.spare is not None and fast.spare.outcome is None
    assert fast.release(qid='q1', turn='t1', epoch=1, question='Что такое инерция?') == 'adopted'
    clock.t += RT.GIVE_UP_S
    fast.poll()
    assert fast.spare is None or fast.spare.outcome is not None


