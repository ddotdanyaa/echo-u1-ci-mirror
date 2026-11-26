"""c25-c: the half hour of P1 (ear_job, cloud_form, ear_lookup) on seeds 0:20 - its own causes, one minimal test each.

Seeds 5, 11, 15 (half_hour, P1 = c24-profile on the stand): the first cue is «Статья 346.12» alone; the owner says it back word for word, the ear writes
«статья триста сорок шесть двенадцать», ``ru_numbers`` refuses the run (300 40 6 12 is no one number) and reads its words one by one; the veto of the
ear's number then sees 300, 40 and 6 the portion lacks and takes the cloud's right confirmation away: the portion again (extra) and the next late (stuck).
"""
import pytest

from echo_sync.controlled_media import ControlledMedia


def bare():
    c = ControlledMedia.__new__(ControlledMedia)
    c.settings = {}
    return c


@pytest.mark.parametrize('heard', ['статья триста сорок шесть двенадцать', 'триста сорок шесть двенадцать', 'статьы триста сорок шесть двенадцать'])
def test_a_dotted_article_said_back_word_for_word_is_no_other_number(heard):
    assert not bare()._ear_other_number(heard, 'Статья 346.12')


@pytest.mark.parametrize('heard,portion', [('статья триста пятьдесят шесть двенадцать', 'Статья 346.12'), ('статья 356 12', 'Статья 346.12'),
                                           ('статья триста сорок шесть тринадцать', 'Статья 346.12'), ('сто двадцать пять тридцать', 'Это 125 рублей.'),
                                           ('девятьсот восемьдесят девять', 'датируют 988 годом,')])
def test_another_number_said_back_is_still_vetoed(heard, portion):
    assert bare()._ear_other_number(heard, portion)


def test_the_parts_said_one_by_one_stay_as_before():
    assert not bare()._ear_other_number('статья одиннадцать три', 'Статья 11.3')


# Seeds 1, 2, 6, 14 (P1) and 15 (P0): a stutter «28. Это... 28. Это 7 раз по 4.» that the ear writes with a wrong first number («тридцать восемь эта двадцать
# восемь это семь раз по четыре»): the owner began the portion again, and what they said the second time stands; the veto read the false start's 38.
@pytest.mark.parametrize('heard,portion', [('тридцать восемь эта двадцать восемь это семь раз по четыре', '28. Это 7 раз по 4.'),
                                           ('двадцать четыре это двадцать пять это пять раз по пять', '25. Это 5 раз по 5.'),
                                           ('шестьдесят три это шестьдесят четыре это восемь раз по восем', '64. Это 8 раз по 8.'),
                                           ('статья двадцать два статья двадцать один налогового кодекса', 'Статья 21 Налогового кодекса о налогах и сборах.')])
def test_a_false_start_with_a_wrong_number_then_the_portion_again_is_no_veto(heard, portion):
    assert bare()._restart_says_no_other(heard, portion)


@pytest.mark.parametrize('heard,portion', [('двадцать восемь это двадцать девять это семь раз по четыре', '28. Это 7 раз по 4.'),
                                           ('двадцать девять это семь раз по четыре', '28. Это 7 раз по 4.'),
                                           ('тридцать восемь это семь раз по четыре', '28. Это 7 раз по 4.')])
def test_a_wrong_number_with_no_restart_or_in_the_restart_is_still_vetoed(heard, portion):
    assert not bare()._restart_says_no_other(heard, portion)


def test_s5_the_socket_drops_while_the_owner_speaks_the_stand_goes_on():
    """S5 of c24-e: a repeat said across the reconnect (9.0 s, the drop at 10.0 s) crashed the stand: the ear's text of the line reached the worker of
    the new call, which had no sink yet (``Recognizer.heard``). The audio of that line went to the old call: the new call's ear never heard it."""
    import logging
    from tools.replay import no_cloud as N
    level = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        def scene(sc):
            sc.ask(4.0, 'Что такое бухгалтерский учёт?')
            sc.repeat(9.0)
            sc.later(10.0, sc.reconnect, call=None)
        rec = N.run('cloud', scene, length=40.0)
    finally:
        logging.disable(level)
    assert rec is not None
