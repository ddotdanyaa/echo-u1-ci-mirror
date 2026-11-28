"""g21-brain: what the model is asked (no «сейчас отвечу», the gist first, no «да, верно» to a repeat) and what is cut at the output when it says them anyway. Production code, no network."""
import pytest

from echo_sync import fast_text as FT

PREFACES = ('Да, сравню и отвечу кратко.', 'Секунду, проверю и скажу точно.', 'Сейчас отвечу.', 'Минутку, уточню.', 'Хорошо, отвечаю.', 'Подожди, посмотрю.', 'Давай проверю.')


def spoken(deltas):
    job = FT.Job(1, 'q', {}, 0.0, '')
    out = []
    for d in deltas:
        job.push(d, 0.0)
        out.append(job.take())
    job.finish('ok')
    out.append(job.take())
    return ''.join(out)


def chunks(text, n):
    return [text[i:i + n] for i in range(0, len(text), n)]


def test_the_brain_forbids_run_up_and_confirming_a_repeat():
    for needle in ('сейчас отвечу', 'секунду', 'не подтверждай', 'да, верно', 'одной законченной фразой'):
        assert needle in FT.BRAIN_POLICY.lower(), needle


def test_the_short_brain_keeps_the_new_rules():
    from echo_sync import brain_short as B
    for needle in ('не подтверждай', 'сейчас отвечу', 'одной законченной фразой'):
        assert needle in B.SHORT_POLICY.lower()


@pytest.mark.parametrize('pre', PREFACES)
@pytest.mark.parametrize('n', (1, 3, 7, 1000))
def test_a_run_up_is_cut_whatever_the_deltas(pre, n):
    assert spoken(chunks(pre + ' Ставка НДС 20 процентов.', n)) == 'Ставка НДС 20 процентов.'


@pytest.mark.parametrize('n', (1, 4, 1000))
def test_a_confirmation_of_a_repeat_is_cut(n):
    assert spoken(chunks('Да, верно. Срок пять дней.', n)) == 'Срок пять дней.'
    assert spoken(chunks('Верно. Срок пять дней.', n)) == 'Срок пять дней.'


@pytest.mark.parametrize('text', ('Да. Срок пять дней.', 'Нет, не облагается.', 'Да, облагается по ставке 20 процентов.', 'Сейчас действует ставка 20 процентов.', 'Секундомер измеряет время.',
                                  'Проверка проводится раз в год.', 'Отвечает за это директор.', 'Сравнение идёт по цене.', 'Так называют налог на добавленную стоимость.', '20 процентов.'))
@pytest.mark.parametrize('n', (1, 5, 1000))
def test_a_real_answer_is_kept_whole(text, n):
    assert spoken(chunks(text, n)) == text


def test_the_start_is_held_only_while_it_may_still_be_a_run_up():
    job = FT.Job(1, 'q', {}, 0.0, '')
    job.push('Ставка 20', 0.0)
    assert job.take() == 'Ставка 20'
    job = FT.Job(2, 'q', {}, 0.0, '')
    job.push('Сейчас от', 0.0)
    assert job.take() == ''


def test_a_text_that_is_only_a_run_up_is_given_at_the_end_not_swallowed_silently():
    assert spoken(['Сейчас отвечу.']) == ''
    assert spoken(['Да, верно.']) == 'Да, верно.'          # nothing after it: it is the whole answer


def test_the_prepared_look_does_not_show_a_run_up():
    job = FT.Job(1, 'q', {}, 0.0, '')
    job.push('Секунду, проверю. Срок 5 дней.', 0.0)
    assert 'Секунду' not in job.spoken
