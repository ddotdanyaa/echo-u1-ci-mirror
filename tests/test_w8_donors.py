"""w8-donors: LocalAgreement over the ear's peeks (stable_text.py, N73) and the stop heard on a peek (ear_command.py, N74). Pure, no model."""
import pytest

from echo_sync.stable_text import LocalAgreement
from echo_sync.ear_command import early_command


def feed(texts, n=2):
    agree = LocalAgreement(n)
    return [agree.push(text) for text in texts], agree


def test_one_peek_commits_nothing():
    out, agree = feed(['сколько стоит билет'])
    assert out == [''] and agree.committed == ''


def test_two_peeks_commit_their_common_prefix_but_not_the_last_word_they_share():
    out, agree = feed(['сколько стоит билет', 'сколько стоит билет до'])
    assert out == ['', 'сколько стоит'] and agree.committed == 'сколько стоит'   # «билет» may still grow into «билета»


def test_commit_is_monotone_a_later_disagreement_never_takes_words_back():
    _, agree = feed(['какая столица франции', 'какая столица франции и', 'какая столиц германии'])
    assert agree.committed == 'какая столица'


def test_a_number_is_held_while_it_can_still_grow():
    _, agree = feed(['ставка двадцать пять процентов', 'ставка двадцать пять'])
    assert agree.committed == 'ставка'                                 # «двадцать пять» may become «двадцать пятый» / «двести двадцать пять»
    agree.push('ставка двадцать пять процентов годовых'); agree.push('ставка двадцать пять процентов годовых в')
    assert agree.committed == 'ставка двадцать пять процентов'          # «годовых» is the last word one of the two has


def test_ne_waits_for_the_word_it_negates():
    _, agree = feed(['это не', 'это не'])
    assert agree.committed == 'это'


def test_casefold_and_yo_do_not_break_agreement_and_reset_starts_over():
    _, agree = feed(['Ещё раз объясни', 'еще раз объясни мне'])
    assert agree.committed == 'еще раз'
    agree.reset()
    assert agree.committed == '' and agree.push('новое') == ''


def test_n3_needs_three_peeks():
    out, _ = feed(['а б в', 'а б в', 'а б в г'], n=3)
    assert out == ['', '', 'а б']


@pytest.mark.parametrize('text,kind', [
    ('стоп', 'stop'), ('Стоп-стоп!', 'stop'), ('хватит', 'stop'), ('подожди секунду', 'stop'), ('так, погоди', 'stop'),
    ('нет, стоп', 'stop'), ('эээ стоп', 'stop')])
def test_a_whole_peek_that_is_a_stop_acts_early(text, kind):
    assert early_command(text) == kind


@pytest.mark.parametrize('text', [
    'стоп а сколько', 'не стоп', 'стоит подождать', 'хватит ли денег', 'дальше', 'повтори', 'стоп стоп стоп стоп', '', None,
    'подожди я хотел спросить'])
def test_anything_else_waits_for_the_final(text):
    assert early_command(text) is None                                    # «дальше» / «повтори» go the full way: a peek may be «дальше что было»


def test_own_voice_saying_the_stop_word_is_not_a_stop():
    assert early_command('хватит', portion='Хватит одной ложки соли.') is None
    assert early_command('стоп', portion='Амортизация — это перенос стоимости.') == 'stop'
