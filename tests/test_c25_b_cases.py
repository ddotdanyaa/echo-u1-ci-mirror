"""c25-b: the cases of the wave (no answer to a bank question after an abandoned portion; …). Cloud stand only (``tools.replay.no_cloud.Scene`` in 'cloud' mode, the model hangs)."""
import logging

import pytest

CHATTER = 'Мы вчера ходили в кино, там было шумно'


def bank_after_abandon(model, at):
    logging.disable(logging.WARNING)
    from tools.replay import no_cloud as N
    s = N.Scene('cloud', seed=0, length=at + 25.0, model=model, profile={**N.PROFILE})
    s.ask(2.0, 'Что такое нематериальные активы?')
    s.say(10.0, 'chatter', CHATTER)
    s.say(14.0, 'chatter', CHATTER)          # the portion is abandoned; this chatter goes to a job that never answers
    s.ask(at, 'Что такое бухгалтерский учёт?')
    try:
        rec = s.play()
    finally:
        s.close()      # h31: the stand's patches come back
    return [c for c in rec.cues if c[0] >= at]


@pytest.mark.parametrize('model,at', [('hang', 17.0), ('hang', 17.3), ('fail', 17.0)])
def test_a_bank_question_after_an_abandoned_portion_and_a_job_of_chatter_is_answered_from_the_bank(model, at):
    """Case 2: the job of the chatter left its text (``fast_left``), and the ear's take glued it to the bank question as the head of one breath: «Мы вчера ходили в кино … что
    такое бухгалтерский учёт» is in no bank, it went to the model, which hung: «Нет ответа» 13 s later and no answer at all."""
    cues = bank_after_abandon(model, at)
    assert cues and cues[0][1].startswith('Формирование') and cues[0][0] < at + 3.0, cues


@pytest.mark.parametrize('question', ['Что говорит статья 58 Налогового кодекса?', 'Статья 58 НК?', 'Расскажи про статью 58 Налогового кодекса', 'О чём статья 58 НК РФ?', 'Статья 58 НК'])
@pytest.mark.parametrize('answer', ['Статья 58 Налогового кодекса — порядок уплаты налогов, сборов, страховых взносов.', 'Статья 58 НК РФ: порядок уплаты налогов.',
                                    'Статья 58 Налогового кодекса устанавливает порядок уплаты налогов.'])
def test_the_first_portion_does_not_restate_the_article_asked(question, answer):
    """Case 6: «Статья 58 Налогового кодекса —» said the question back; the content comes first."""
    from echo_sync.first_useful import compact_opening
    assert compact_opening(answer, question).startswith('порядок уплаты'), compact_opening(answer, question)


@pytest.mark.parametrize('question,answer', [('Что говорит статья 58 Налогового кодекса?', 'Статья 59 Налогового кодекса — безнадёжные долги.'),
                                             ('Что говорит статья 58 Налогового кодекса?', 'Статья 58 Трудового кодекса — срочный трудовой договор.'),
                                             ('Как зовут кота?', 'Статья 58 Налогового кодекса — порядок уплаты налогов.'),
                                             ('Что говорит статья 58 Налогового кодекса?', 'Статья 58 Налогового')])
def test_another_article_or_no_article_asked_keeps_the_answer_as_it_is(question, answer):
    from echo_sync.first_useful import compact_opening
    out = compact_opening(answer, question)
    assert out in (answer, ''), out
    assert out == answer or answer == 'Статья 58 Налогового', out


@pytest.mark.xfail(strict=True, reason='c25-b case 6 at the base: _publish_reference through compact_opening turned 6 pinned tests red (test_marathon 30 questions, test_half_hour short call, test_local_fallback and test_no_cloud_rules law questions: the stand wants «статья N» in the answer); owner decision + stand patch c25-b-stand.diff')
def test_the_base_s_answer_to_an_article_starts_with_its_content():
    """Case 6 at the base: «Статья 23 НК» is a hit of the reference base, «Статья 23 Налогового кодекса — обязанности …»; the first cue is «Обязанности …»."""
    logging.disable(logging.WARNING)
    from tools.replay import no_cloud as N
    s = N.Scene('cloud', seed=0, length=20.0, model='fail', profile={**N.PROFILE})
    s.ask(2.0, 'Что такое статья 23 НК?')
    try:
        rec = s.play()
    finally:
        s.close()      # h31: the stand's patches come back
    assert rec.cues and rec.cues[0][1].startswith('Обязанности') and rec.cues[0][0] < 5.0, rec.cues


@pytest.mark.parametrize('text', ['Принял, сейчас посмотрю.', 'Принял, посмотрю в базе.', 'Принято, посмотрю в базе.', 'Принял, смотрю в базе.', 'Посмотрю в интернете.', 'Принял, сейчас посмотрю в кодексе.',
                                  'Принял, поищу в источниках.', 'Хорошо, принял, сейчас гляну в базе.'])
def test_an_announcement_of_looking_is_never_a_cue(text):
    """Case 7: «Принял, сейчас посмотрю» and its kin are no hint: nothing of them is said; the answer after them is."""
    from echo_sync.textutil import strip_process_prefix
    assert strip_process_prefix(text, 'Какая ставка НДС?') == ''
    assert strip_process_prefix(text + ' Ставка НДС 20 процентов.', 'Какая ставка НДС?') == 'Ставка НДС 20 процентов.'


@pytest.mark.parametrize('text', ['Смотрю в базе данных ошибку — так называется отладка.', 'Посмотрим на пример.'])
def test_a_sentence_that_goes_on_past_the_place_stays(text):
    from echo_sync.textutil import strip_process_prefix
    assert strip_process_prefix(text, 'Что такое отладка?') == text


@pytest.fixture(scope='module')
def bank7():
    logging.disable(logging.WARNING)
    from echo_sync.instant import Instant, load_bank
    rows = load_bank('cloud_context/bank/instant_bank_7.json')
    return Instant(rows)


@pytest.mark.parametrize('q', ['Когда и где появился термин финансы?', 'когда и где появился термин финансы', 'Где впервые возник термин финансы?', 'Что и где возник термин финансы?'])
def test_a_loose_paraphrase_of_a_bank_question_is_answered_locally(bank7, q):
    """Case 5: «когда и где» asks two kinds, the entry's form «Когда появился термин финансы?» is one of them (it scored as another kind: 0.60 < 0.70 and went to the model, 5 s); «впервые» is the speaker's."""
    hit = bank7.lookup(q)
    assert hit is not None and hit.answer.startswith('Из торговых городов Италии'), hit


@pytest.mark.parametrize('q', ['Когда и где появился термин кредит?', 'Где впервые возник термин инвестиция?', 'Когда и где родился Пушкин?', 'Кто и где придумал термин финансы?'])
def test_the_two_kinds_open_no_other_entry(bank7, q):
    hit = bank7.lookup(q)
    assert hit is None or not hit.answer.startswith('Из торговых городов Италии'), hit
