"""c24-e: the classes of the ten circles that have a minimal example, as tests that FAIL today (xfail strict: the fixing package turns them green and removes the mark).
Cloud stand only. The reports: cloud_context/reports/c24-e-classes.md."""
import logging

import pytest

from echo_sync.generator import needs_verification

FILLER = 'Сейчас, подожди, я подумаю. '


def test_a_filler_before_a_word_problem_does_not_make_it_a_live_data_question():
    assert not needs_verification(FILLER + 'Если у меня было 40 рублей и я потратил 30 рублей, сколько денег осталось?', ())
    assert not needs_verification(FILLER + 'Сколько будет 3 умножить на 4?', ())


def test_c25_b_other_pause_prefaces_do_not_make_live_data():      # c25-b G10: any leading sentence of pause words alone
    for pre in ('Сейчас, секунду. ', 'Так, сейчас подумаю. ', 'Ну сейчас, погоди. ', 'Сейчас-сейчас. '):
        assert not needs_verification(pre + 'Если у меня было 40 рублей и я потратил 30 рублей, сколько денег осталось?', ()), pre
    assert needs_verification('Сейчас, подожди. Какой сейчас курс доллара?', ())
    assert needs_verification('Подожди. Какая ставка НДС сейчас?', ())


def test_the_real_current_data_questions_stay_live_data_questions():
    for q in ('Какой сейчас курс доллара?', 'Подожди, какая сейчас ставка рефинансирования?', 'Сколько сейчас стоит нефть?'):
        assert needs_verification(q, ()), q


def test_the_plain_word_problem_is_not_live_data():
    assert not needs_verification('Если у меня было 40 рублей и я потратил 30 рублей, сколько денег осталось?', ())


@pytest.mark.xfail(strict=True, reason='c24-e S1: the cloud comes back while the owner repeats a portion: the next portion is 6-8 s late (18.4 s instead of ~12.7 s) and the stumble that follows is read against the status line')
def test_the_cloud_returning_during_a_repeat_does_not_hold_the_next_portion():
    logging.disable(logging.WARNING)
    from tools.replay import no_cloud as N

    def script(s):
        s.ask(4.0, 'Что такое бухгалтерский учёт?')
        s.repeat(9.0)
        s.cloud_back(5.0)           # the product's first retry is 10 s after the fall: in the middle of the repeat
    rec = N.run('refused', script, length=40.0)
    assert not [v for v in rec.violations if v[0] == 'NC5'], rec.violations


def test_the_same_scene_without_the_return_is_clean():
    logging.disable(logging.WARNING)
    from tools.replay import no_cloud as N

    def script(s):
        s.ask(4.0, 'Что такое бухгалтерский учёт?')
        s.repeat(9.0)
    assert N.run('refused', script, length=40.0).violations == []
