"""W1F-B, W1 group G6 latent (w1_10, found offline): «стоп» pauses the CURRENT answer and keeps all of it.

Coordinator ruling (3 Nov 2026, binding): «under CL2 ruling 1 «стоп» is a PAUSE that keeps the plan. Consistently, text of the CURRENT
answer that has already arrived when the user pauses — published or not yet published — and text of the same answer that keeps arriving
after the pause are kept in the plan (never spoken while paused; spoken from the paused portion on «продолжай / ещё раз / повтори» or by a
resume). Only a NEW question (internal retire) discards the old answer's tail. … Bound it: a paused answer still has the post-publication
30 s cap for an unfinished stream, and nothing is spoken until the listener resumes.»

w1_10 (W1 run 20261103-031522): the answer « Обычно берут воду примерно 80 градусов —то есть не кипяток — и настаивают» was cut when the
listener spoke; only «Обычно берут | воду примерно» was published (the cut segment was held for a continuation). Deployed (66b29f1), a
recognised «стоп» closed the plan at the PUBLISHED frontier and «80 градусов — то есть не кипяток — и настаивают» was lost: after «Продолжай»
and the repeats the answer ended at «воду примерно». W1F-C makes the natural stop forms («Стой, подожди секунду») recognised.
"""
from helpers_w1f import Wire

TEA_Q = 'Как правильно заварить зеленый чай'
TEA_A1 = ' Обычно берут воду примерно 80 градусов —то есть не кипяток — и настаивают'


def dictated_after(w, seconds):
    out = []
    for at, text in w.played:
        if at >= seconds and (not out or out[-1] != text):
            out.append(text)
    return ' '.join(out)


def test_w1_10_a_stop_keeps_the_text_that_had_already_arrived(tmp_path):
    w = Wire(tmp_path, ack=((41.0, 120.0),))
    w.user('u1', TEA_Q, 5.4, 8.5)
    w.assistant('a1', TEA_A1, 8.5, 12.6, grow=[27, 40, 60, len(TEA_A1)], times=[8.5, 9.5, 10.6, 11.8])
    w.user('u2', ' Стоп', 12.6, 13.2)
    w.assistant('a2', ' Конечно, слушаю.', 13.3, 14.4)                          # the cloud's reply to the stop: not the answer
    w.user('u5', ' Продолжай', 40.0, 40.6)
    w.until(120.0)
    assert w.played_after(13.2) and w.played_after(13.2)[0] == w.played_after(40.0)[0], w.played   # silent until «Продолжай»
    plan = w.plan()
    assert '80 градусов' in plan and plan.endswith('настаивают'), plan               # deployed: «… воду примерно»
    assert 'слушаю' not in plan, plan
    heard = dictated_after(w, 40.0)
    assert '80 градусов' in heard and heard.endswith('настаивают'), w.played


def test_text_of_the_same_answer_that_arrives_after_the_stop_is_kept_and_not_spoken(tmp_path):
    """The cloud's segment is still streaming when the listener says «стоп»: its later words join the paused plan, silently."""
    answer = ' Инерция — это свойство тела сохранять своё состояние движения или покоя, пока внешняя сила не заставит его изменить.'
    w = Wire(tmp_path, ack=((30.0, 120.0),))
    w.user('u1', 'Что такое инерция', 0.0, 2.0)
    w.assistant('a1', answer, 2.01, 9.0)                                          # word by word until 9 s
    # F1 (wave F): the first cue is the first clause, out when its comma arrives (~6.3 s; the 2-word cue was out before 5.5 s)
    w.user('u2', ' Стоп', 7.0, 7.5)                                               # the first cue is out, the segment goes on
    w.user('u3', ' Продолжай', 30.0, 30.5)
    w.until(90.0)
    assert w.played and w.played[0][0] < 7.0, w.played
    assert w.played_after(7.5)[:1] == w.played_after(30.0)[:1], w.played           # nothing between the stop and «Продолжай»
    assert w.plan().endswith('пока внешняя сила не заставит его изменить.'), w.plan()
    assert dictated_after(w, 30.0).endswith('изменить.'), w.played


def test_an_open_paused_stream_is_still_closed_by_the_cap(tmp_path):
    """Bounded: a paused answer whose producer never closes its turn is closed as it stands after the post-publication cap (30 s);
    nothing is spoken meanwhile, and the paused plan keeps what did arrive."""
    w = Wire(tmp_path)
    w.user('u1', 'Что такое инерция', 0.0, 2.0)
    w.assistant('a1', ' Инерция — это свойство тела сохранять своё состояние движения или покоя', 2.01, 5.0, final=False)
    # F1 (wave F): this open sentence has no clause mark and does not run past the first-cue window, so its first cue is chosen
    # from what arrived when the producer has been silent for the answer wait (~13 s; the 2-word cue was out before 3.6 s): the stop
    # comes after it, as the scenario needs, and the cap counts from the pause
    w.user('u2', ' Стоп', 14.0, 14.4)
    w.until(40.0)
    assert w.state().get('streaming') and w.state().get('paused'), w.state()        # inside the cap: still open, paused
    w.until(50.0)
    state = w.state()
    assert not state.get('streaming') and state.get('paused'), state                 # the cap closed it; the pause stands
    assert w.plan().endswith('или покоя'), w.plan()
    assert w.played_after(14.4) == [], w.played                                       # nothing after the stop (F1: was 4.0)


def test_a_new_question_after_a_stop_discards_the_old_tail(tmp_path):
    w = Wire(tmp_path)
    w.user('u1', TEA_Q, 5.4, 8.5)
    w.assistant('a1', TEA_A1, 8.5, 12.6, grow=[27, 40, 60, len(TEA_A1)], times=[8.5, 9.5, 10.6, 11.8])
    w.user('u2', ' Стоп', 12.6, 13.2)
    w.user('u3', 'Что такое масса', 20.0, 21.0)
    w.assistant('a3', ' Масса — это мера инертности тела.', 21.05, 22.0)
    w.assistant('a4', ' и настаивают три минуты.', 22.5, 23.0)                     # a late tail of the old answer
    w.until(30.0)
    assert 'настаивают' not in w.plan() and 'инертности' in w.plan(), w.plan()
    assert w.state()['history'][-2]['status'] == 'interrupted', w.state()['history'][-2]
