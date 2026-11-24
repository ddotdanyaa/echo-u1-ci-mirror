"""U53 (one-input): the LAST word of a portion the ear got wrong or cut does not keep the portion from counting («написывал» for «описывал», «воинский у» for «воинский устав»). Numbers and «не» are strict; another word of the same length is no such word. Replay 08:41 (20261111-084102) is laptop-only."""
import pytest
from echo_sync.ru_alignment import match_current

P = 'Он подробно описывал воинский устав.'


@pytest.mark.parametrize('portion,heard', [
    ('Автор подробно описывал воинский устав.', 'автор подробно описывал воинский у'),             # cut by the ear: a head of the word, the word before it said
    ('Мы разобрали раздел о правах и глав', 'мы разобрали раздел о правах и гла'),
    ('Автор очень подробно описывал.', 'автор очень подробно написывал'),            # one letter wrong: >= 0.8, length >= 5
    ('Башню очень долго и тщательно измеряли.', 'башню очень долго и тщательно измерали'),
])
def test_the_last_word_cut_or_garbled_still_counts(portion, heard):
    assert match_current(heard, portion) == 'ack'


@pytest.mark.parametrize('portion,heard', [
    ('Башню очень долго и тщательно измеряли.', 'башню очень долго и тщательно мерили'),          # another word, not near
    ('Налог платит покупатель.', 'налог платит продавец'),                                         # another word of about the same length
    ('Это дебет счёта.', 'это кредит счёта'),
    ('Срок оплаты тридцать дней.', 'срок оплаты тридцать два'),                                   # a number is strict
    ('Срок оплаты тридцать дней.', 'срок оплаты сорок дней'),
    ('Платеж не облагается.', 'платеж облагается'),                                                 # «не» is strict
    ('Автор подробно описывал воинский устав.', 'автор подробно описывал другой у'),              # the word before the cut one differs
    ('Налог платит покупатель.', 'налог берет по'),                                                 # a head of a word, but the word before differs
    ('Автор подробно описывал воинский устав.', 'автор подробно описывал воинский стат'),          # not a head, not near enough
])
def test_another_word_in_the_place_does_not_count(portion, heard):
    assert match_current(heard, portion) != 'ack'
