"""c24-c item 2: the owner names a word of the portion while writing. «последнее записанное слово X» / «я записал X»: on AFTER it; «повтори со слова X» / «с X»: on FROM it. A word twice
in the portion: the place told by where they are (``at``), else the earlier place (a short tail more, nothing unwritten skipped). A word of the next portion only: no place. Pure."""
import pytest

from echo_sync.repeat_rule import landmark, landmark_command

P = 'Налоговый вычет уменьшает облагаемый доход гражданина.'
TWICE = 'Налог платят с дохода, и налог платят вовремя.'
NUM = 'Ставка налога составляет 13 процентов от дохода.'
NEG = 'Пособие не облагается налогом в этом случае.'


@pytest.mark.parametrize('said, want', [
    ('повтори со слова облагаемый', ('from', ['облагаемый'])),
    ('повтори с облагаемый', ('from', ['облагаемый'])),
    ('со слова облагаемый', ('from', ['облагаемый'])),
    ('начни с облагаемый доход', ('from', ['облагаемый', 'доход'])),
    ('последнее записанное слово облагаемый', ('after', ['облагаемый'])),
    ('последнее слово уменьшает', ('after', ['уменьшает'])),
    ('я записал уменьшает', ('after', ['уменьшает'])),
    ('записал до слова уменьшает', ('after', ['уменьшает'])),
    ('я остановился на слове уменьшает', ('after', ['уменьшает'])),
    ('после слова уменьшает', ('after', ['уменьшает'])),
    ('ну дальше после уменьшает', ('after', ['уменьшает'])),
])
def test_the_command_and_its_word(said, want):
    assert landmark_command(said) == want


@pytest.mark.parametrize('said', ['повтори', 'облагаемый доход гражданина', 'с начала', 'что такое облагаемый доход', 'повтори со слова', 'я записываю',
                                  'последнее слово', 'Он сказал повтори со слова облагаемый и ушёл из комнаты сразу', 'дальше', 'я буду записывать'])
def test_no_landmark(said):
    assert landmark_command(said) is None


def test_after_and_from_differ_by_the_word_itself():
    assert landmark('последнее записанное слово облагаемый', P) == ('rest', 'доход гражданина.')
    assert landmark('повтори со слова облагаемый', P) == ('rest', 'облагаемый доход гражданина.')


def test_the_last_word_written_is_the_portion_done():
    assert landmark('последнее записанное слово гражданина', P) == ('next', None)
    assert landmark('повтори со слова гражданина', P) == ('rest', 'гражданина.')


def test_a_word_twice_is_placed_by_where_they_are_else_the_earlier_place():
    assert landmark('я записал налог', TWICE) == ('rest', 'платят с дохода, и налог платят вовремя.')      # the earlier: nothing skipped
    assert landmark('я записал налог', TWICE, at=4) == ('rest', 'платят вовремя.')                       # helped from «и налог…»: the later
    assert landmark('я записал налог', TWICE, at=1) == ('rest', 'платят с дохода, и налог платят вовремя.')  # just past the first «Налог»: that one
    assert landmark('повтори с налог', TWICE, at=1) == ('rest', 'Налог платят с дохода, и налог платят вовремя.')
    assert landmark('я записал налог платят', TWICE) == ('rest', 'с дохода, и налог платят вовремя.')
    assert landmark('я записал и налог', TWICE) == ('rest', 'платят вовремя.')                           # two words name the later one


def test_a_number_and_a_negation_by_value():
    assert landmark('последнее записанное слово тринадцать', NUM) == ('rest', 'процентов от дохода.')
    assert landmark('я записал четырнадцать', NUM) is None                 # another number: no place, never a near one
    assert landmark('я записал не', NEG) == ('rest', 'облагается налогом в этом случае.')
    assert landmark('повтори с облагается', NEG) == ('rest', 'облагается налогом в этом случае.')


def test_a_word_not_in_the_portion_is_no_place():
    assert landmark('я записал покупке', P) is None          # a word of the next portion: never a jump over what is not written
    assert landmark('повтори со слова это', P) is None
    assert landmark('облагаемый', P) is None                  # no command: the rule's own reading


# c24-c item 2, without a command: dictating, the owner says the last words they wrote, a run of the portion short of its end. The rest after the run, when the run is sure.
from echo_sync.repeat_rule import written_to      # noqa: E402


@pytest.mark.parametrize('said, portion, rest', [
    ('не облагается', NEG, 'налогом в этом случае.'),
    ('облагается налогом в этом', NEG, 'случае.'),
    ('доход гражданина', P + ' Его получают при лечении.', 'Его получают при лечении.'),
    ('13 процентов', NUM, 'от дохода.'),
    ('тринадцать процентов', NUM, 'от дохода.'),
    ('ну уменьшает облагаемый', P, 'доход гражданина.'),
])
def test_the_run_written_and_the_rest(said, portion, rest):
    assert written_to(said, portion) == rest


@pytest.mark.parametrize('said, portion', [
    ('облагаемый', P),                          # one word: no sure place
    ('доход гражданина', P),                    # the end: the rule's NEXT, not a tail
    ('налог платят', TWICE),                    # twice in the portion: no sure place (a landmark with «и» tells it)
    ('14 процентов', NUM),                      # another number
    ('облагается налогом', 'Пособие облагается налогом, а не облагается налогом доход.'),
    ('уменьшает доход', P),                     # a word left out: not a run
    ('что уменьшает облагаемый', P),            # a question
])
def test_no_sure_run(said, portion):
    assert written_to(said, portion) is None
