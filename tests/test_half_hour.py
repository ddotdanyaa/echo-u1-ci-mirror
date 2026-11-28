"""G18: half an hour of conversation on the stand (``tools.replay.half_hour``): the units of what it found, and a short call through the real chain."""
import pytest


def test_the_stand_owes_the_next_portion_only_when_the_ear_kept_the_numbers_and_the_not():
    from tools.replay.half_hour import ear_keeps
    assert ear_keeps('двадцать четыре это восемь раз по три', '24. Это 8 раз по 3.')
    assert not ear_keeps('тридцать четыре это восемь раз по три', '24. Это 8 раз по 3.')        # the ear changed a number: said again by design
    assert not ear_keeps('ватает сорок рублей', 'Не хватает 40 рублей.')
    assert ear_keeps('статья 346 12', 'Статья 346.12')


@pytest.mark.xfail(strict=True, reason='g18 finding, fast_text.ends_like (A2): the patch is in cloud_context/reports/g18-half-hour.md')
def test_the_last_words_of_a_portion_that_ends_in_function_words_close_the_try():
    """half_hour seeds 2, 5, 7, 9, 10: «Ну вот, только у тех» for «доступ к информации только у тех,»: the owner said the portion's last words (the rule of 06.11), the
    key of ``ends_like`` is its last two content words («доступ информация»), the same portion was said again and the next one waited for a second try."""
    from echo_sync.fast_text import ends_like
    assert ends_like('ну вот только у тех', 'доступ к информации только у тех,')
    assert not ends_like('ну вот только не у тех', 'доступ к информации только у тех,')


def test_a_short_call_on_the_stand_answers_every_question_in_place():
    """Twelve questions of different subjects, the owner saying each portion back: every question answered, no step of two portions."""
    from tools.replay import half_hour as H
    for seed in (2, 4):
        r = H.one(seed, questions=12, minutes=5.0)
        assert r['asked'] == 12 and not r['crash']
        kinds = [e[0] for e in r['events']]
        assert 'unanswered' not in kinds and 'skipped' not in kinds, r['events']
        assert r['tries'] >= 12


def test_the_table_counts_by_minute():
    from tools.replay.half_hour import table
    rows = [{'minutes': {'unanswered': {3: 1}, 'extra': {}, 'stuck': {0: 2}, 'skipped': {}}, 'asked_by_minute': {0: 2, 3: 1}}]
    out = table(rows, 3).splitlines()
    assert out[1].split() == ['0', '2', '0', '0', '2', '0'] and out[4].split() == ['3', '1', '1', '0', '0', '0']


def test_the_half_hour_gives_the_logging_back():
    """integ-c19: ``half_hour.one`` disabled logging and never gave it back: 49 tests of test_t1_transport (and the logging tests of t_new_classes, spoken_diagnostics …) failed after it on the same worker."""
    import logging
    from tools.replay import half_hour as H
    before = logging.root.manager.disable
    H.one(1, questions=2, minutes=1.0)
    assert logging.root.manager.disable == before


def test_the_half_hour_gives_the_threads_and_the_host_back():
    """integ-c19: ``HalfHour.close`` (an episode's end) hid ``Stand.close``: fast_text's threading and the host's kwargs stayed the stand's after ``one``."""
    import echo_sync.fast_text as FT
    from tools.replay import half_hour as H
    from tools.replay import stand as A
    threading, kwargs = FT.threading, A.S.host_kwargs
    H.one(1, questions=2, minutes=1.0)
    assert FT.threading is threading and A.S.host_kwargs is kwargs
