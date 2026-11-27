"""W1F-B, class C5 (W1 groups G5 w1_09 / w1_16, G4 TR-GLUE w1_08, G6 latent): a cloud reply to a turn that is NOT the question is never
spliced into the current answer.

GPT-Live hears and answers every turn: a bystander, small talk, an utterance the classifier could not place. Deployed (66b29f1) the turn
after such an utterance was given to the current question whenever its last segment had been cut mid-sentence
(``_continues_cut_answer``), and ``_restart_verdict`` read a new sentence as «the answer going on» unless it was pure chatter: the
vaccine answer took «Угу, понятно. Сильный контраст, шум отвлекает. Фильм-то всё равно удалось нормально посмотреть?» (w1_16 step 4),
the compass answer «свободно Ага.» | «У осьминога…» (w1_09 step 2), the tsunami answer «столб воды Хорошо.» (w1_08 step 3).

The rule now (R2a: the first letters are a signal, both errors tested): after such a turn the cloud's next segment is «not this answer»
unless it carries the strong held-continuation evidence - the rest of the cut word, or a lower-case word, digit or mark that goes on with
the cut sentence; then only that sentence is the answer's (up to its end: a terminator, or a capital on a common word, «воды Хорошо.»).
An attempt at the portion, a repeat request, a filler or a backchannel keep the old path (``_weigh_segment``).
"""
import pytest

from helpers_w1f import Wire

VACCINE_Q = 'Расскажи, как работает прививка'
VACCINE_CUT = ' Прививка тренирует иммунитет: в тело вводят безопасный фрагмент вируса, и организм учится распознавать'


def vaccine(tmp_path, said, reply, *, reply_start=9.05):
    """The answer arrives in one segment that is cut mid-sentence (the listener's turn opened); the listener repeats every cue except
    while ``said`` (a turn that is not the question) and the cloud's ``reply`` to it go on, then picks the dictation up again."""
    w = Wire(tmp_path, ack=((0.0, 5.0), (12.0, 90.0)))
    w.user('u1', VACCINE_Q, 0.0, 2.0)
    w.assistant('a1', VACCINE_CUT, 2.01, 6.0)
    w.user('u3', said, 7.0, 9.0)
    w.assistant('a2', reply, reply_start, 11.0)
    w.confirm(12.0)
    return w.until(60.0)


def dictated(w):
    """What the listener was dictated: every cue once, in order (a re-spoken portion counted once)."""
    out = []
    for _, text in w.played:
        if not out or out[-1] != text:
            out.append(text)
    return ' '.join(out)


@pytest.mark.parametrize('said,reply', [
    (' Мы вчера ходили в кино, там было очень шумно',
     ' Угу, понятно. Сильный контраст, шум отвлекает. Фильм-то всё равно удалось нормально посмотреть?'),   # w1_16 step 4
    (' Слушай, ты меня хорошо слышишь', ' Да, слышу тебя отлично. Если что-то поменяется со звуком, скажи.'),
], ids=['bystander', 'connection_check'])
def test_a_reply_to_a_turn_that_is_not_the_question_never_joins_the_answer(tmp_path, said, reply):
    w = vaccine(tmp_path, said, reply)
    plan = w.plan()
    assert 'Фильм' not in plan and 'Угу' not in plan and 'слышу' not in plan, plan    # deployed: published 222 -> 379
    assert plan.rstrip().endswith('распознавать') and w.state().get('completed'), plan  # the cut answer ends where the cloud stopped
    assert dictated(w).endswith('распознавать'), w.played


def test_after_a_bystander_the_rest_of_the_cut_sentence_is_still_the_answer(tmp_path):
    """The other error (R2a): the cloud ignores the bystander and goes on with its cut sentence - that is the answer."""
    w = vaccine(tmp_path, ' Мы вчера ходили в кино, там было очень шумно', ' вирус при встрече и быстро его уничтожать.')
    assert w.plan().endswith('распознавать вирус при встрече и быстро его уничтожать.'), w.plan()
    assert dictated(w).endswith('уничтожать.'), w.played


def test_the_rest_of_the_cut_sentence_is_taken_but_not_the_reply_glued_after_it(tmp_path):
    """w1_08 step 3: «Так, это понятно» and the cloud's « воды Хорошо.» - the rest of the cut sentence, then a reply with no full stop
    before it."""
    w = Wire(tmp_path, ack=((0.0, 5.0), (12.0, 90.0)))
    w.user('u1', 'Расскажи, как возникает цунами', 0.0, 2.0)
    w.assistant('a1', ' Цунами чаще всего начинается с внезапного смещения морского дна. Это толкает вверх огромный столб', 2.01, 6.0)
    w.user('u3', ' Так, это понятно', 7.0, 9.0)
    w.assistant('a2', ' воды Хорошо.', 9.02, 9.4)
    w.confirm(12.0)
    w.until(60.0)
    assert w.plan().endswith('столб воды') and w.state().get('completed'), w.plan()  # deployed: «…столб воды Хорошо.»
    assert dictated(w).endswith('столб воды'), w.played


def test_a_new_request_the_classifier_misses_is_never_spliced_into_the_old_answer(tmp_path):
    """w1_09 step 2: the compass answer was cut at «…которая свободно»; the request (no «?», its question word fifth) is placed or not by
    the classifier, but the cloud's octopus reply is never the rest of the compass answer."""
    w = Wire(tmp_path)
    w.user('u1', 'Объясни, как работает компас', 4.728, 7.975)
    w.assistant('a1', ' Внутри компаса есть намагниченная стрелка, которая свободно', 7.976, 12.133)
    w.user('u2', ' Подожди, лучше скажи другое, сколько рук у осьмин ога', 12.138, 16.931)
    w.assistant('a2', ' Ага. У осьминога обычно восемь рук — это и есть его щупальца.', 16.932, 21.122)
    w.until(30.0)
    plan = w.plan()
    assert 'свободно Ага' not in plan, plan                                          # deployed: the chunk «свободно Ага.»
    assert not ('компас' in w.c.question_text and 'осьминог' in plan), (w.c.question_text, plan)


def test_after_the_listener_repeats_the_portion_the_answer_still_goes_on_in_a_new_segment(tmp_path):
    """Control: an attempt or a confirmation keeps the old path - the model goes on after the listener's turn, in a new segment."""
    w = Wire(tmp_path, ack=((0.0, 90.0),))
    w.user('u1', VACCINE_Q, 0.0, 2.0)
    w.assistant('a1', VACCINE_CUT, 2.01, 6.0)
    w.assistant('a2', ' вирус. Потом организм справляется с болезнью быстрее.', 7.05, 8.5)
    w.until(60.0)
    assert w.plan().endswith('распознавать вирус. Потом организм справляется с болезнью быстрее.'), w.plan()
    assert dictated(w).endswith('быстрее.'), w.played
