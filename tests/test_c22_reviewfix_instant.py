"""c22-reviewfix: review of master 4a91807 (instant.py _CHANGES). A live rate is never a bank answer, in every case of «курс» (the dative
«курсам» too), in the market sense of «курсовая стоимость / цена», and in the live wordings with no «курс» at all («Почём евро?»). The
coursework paper and the accounting term «курсовая разница» stay answerable from the bank. Expectations are written here."""
import pytest

from echo_sync import instant
from echo_sync.instant import Instant

LIVE = ['По каким курсам меняют доллар?', 'По курсам ЦБ сколько стоит евро?', 'К курсам валют привязан тариф?',
        'Какая курсовая стоимость акции Газпрома?', 'Курсовая цена евро?',
        'Сколько стоит доллар?', 'Почём евро?', 'Сколько рублей за доллар?', 'Сколько дают за доллар?', 'Какая цена доллара?',
        'Какая стоимость биткоина?', 'Сколько стоит одна акция Сбербанка?']


@pytest.mark.parametrize('question', LIVE)
def test_a_live_rate_is_never_a_bank_answer(question):
    assert instant._changes(question)
    row = {'q': question, 'answer': 'По девяносто рублей.'}
    assert instant.clean_entry(row, 'М') is None
    kept = {'q': 'Что такое курсовая работа?', 'answer': 'Самостоятельная работа студента.', 'alt': [question]}
    assert question not in instant.clean_entry(kept, 'М')['alt']


STAYS = ['Что такое курсовая разница?', 'Как учитывать курсовые разницы?', 'Сколько стоит написать курсовую?',
         'Какой объём курсовой работы?', 'Что такое валюта?', 'Сколько стоит патент для ИП?']


@pytest.mark.parametrize('question', STAYS)
def test_the_coursework_and_the_accounting_term_stay_answerable(question):
    assert not instant._changes(question)
    row = instant.clean_entry({'q': question, 'answer': 'Разница от пересчёта валюты по разным датам.'}, 'М')
    assert row is not None and Instant([row], adapters=()).lookup(question, bank_only=True) is not None
