"""w9-safe: what looks outward - the public lookup, the logs, the call trace.

Findings on the real code (the owner of controlled_media.py is the coordinator: the tests that need its patch are xfail(strict=True) with the
finding's number; the patch is in cloud_context/reports/w9-safe.md).
W9S-F1: ``ControlledMedia.public_lookup_allowed`` lets the first person («мне», «меня», «мою», «моим», «кто я») and contact data reach the public search.
"""
import pytest

from echo_sync.controlled_media import ControlledMedia

# Said to the phone, each of these would be sent to the third-party search as it stands; none of them names anything public by itself.
LEAKS = [
    'сколько мне платят на работе сейчас',
    'как меня зовут',
    'найди мою справку о доходах',
    'что с моим заказом сейчас',
    'кто я такой',
    'сколько я должен банку сейчас',
    'почему я заболел',
    'позвони на 89161234567 и узнай курс',
    'позвони на +7 (916) 123-45-67',
    'что пришло на ivan.petrov@mail.ru',
    'проверь карту 4276 1234 5678 9012',
    'действителен ли паспорт 4510 123456',
    # without the text channel the lookup is the whole utterance (controlled_media.py: question_part only when fast_call): the preface goes to the search too
    'Добрый день, меня зовут Игорь Петров, я звоню уже в третий раз. До какого числа сдавать декларацию по НДС',
]
PUBLIC = ['какая погода в Москве', 'какая ставка НДС в 2026 году', 'кто написал роман Хижина дяди Тома',
          'какой штраф по статье 12.9 КоАП', 'план счетов 89 счет какой', 'сколько будет 1234 умножить на 5678', 'курс доллара 95,5 рубля это много']


@pytest.mark.xfail(strict=True, reason='W9S-F1: the privacy gate of the public lookup misses мне/меня/мою/моим, «кто я», phones, e-mails, cards')
@pytest.mark.parametrize('question', LEAKS)
def test_w9s_f1_personal_question_never_reaches_public_lookup(question):
    assert not ControlledMedia.public_lookup_allowed(question)


@pytest.mark.parametrize('question', PUBLIC)
def test_public_question_still_reaches_public_lookup(question):
    assert ControlledMedia.public_lookup_allowed(question)


# The strict gate (echo_sync/privacy_gate.py): what the patch of W9S-F1 makes of the controller's gate.
from echo_sync import privacy_gate


@pytest.mark.parametrize('question', LEAKS)
def test_strict_gate_refuses_every_leak(question):
    assert privacy_gate.personal_reason(question)


@pytest.mark.parametrize('question', PUBLIC)
def test_strict_gate_lets_public_questions_go(question):
    assert privacy_gate.personal_reason(question) is None


def test_reasons_name_the_kind_of_data_and_never_echo_it():
    assert [privacy_gate.personal_reason(q) for q in ('как меня зовут', 'что пришло на a.b@c.ru', 'позвони 8 916 123 45 67',
                                                      'карта 4276123456789012', 'паспорт 4510 123456')] == ['first_person', 'email', 'phone', 'card', 'document']


def test_strict_gate_refuses_nothing_public_in_the_corpora():
    """The real questions of the corpora (RuBQ, the question set, the cloud rows of brain_eval_n2 that are questions): the strict gate refuses
    none the base gate lets go, unless it is in the first person or carries contact data (each such row is listed in the report)."""
    import json
    from pathlib import Path
    corpus = Path(__file__).resolve().parents[1] / 'cloud_context' / 'scripts' / 'corpus'
    texts = [q['text'] for q in json.loads((corpus / 'real_questions_ru.json').read_text(encoding='utf-8'))['questions']]
    texts += [q['text'] for q in json.loads((corpus / 'questions_v1.json').read_text(encoding='utf-8'))]
    texts += [r['text'] for r in json.loads((corpus / 'brain_eval_n2.json').read_text(encoding='utf-8'))['rows']]
    newly = [t for t in texts if ControlledMedia.public_lookup_allowed(t) and privacy_gate.personal_reason(t)]
    assert len(texts) > 800
    assert all(privacy_gate.personal_reason(t) in ('first_person', 'email', 'phone', 'card', 'document') for t in newly)
    assert not [t for t in newly if privacy_gate.personal_reason(t) != 'first_person'], 'contact data found in a public corpus row'


# N172/N173: the logs of a call. The controller's every line on a run of personal talk, a name, a phone, an e-mail, commands and answers
# carries none of their words (the call trace, a separate LOCAL file, keeps them by design: decision D-4).
def test_controller_logs_carry_no_word_of_what_was_said_or_answered(tmp_path, caplog):
    import logging
    from test_first_cue_never_silent import Clock, created, done, host_controller
    marker = 'Зюзюкина'
    said = [f'Меня зовут Анна {marker}, какой налог на квартиру сейчас', f'а сколько стоит {marker} 89161234567', 'Дальше',
            f'{marker} это вообще кто такая, напиши на anna.z@mail.ru', 'Повтори', f'Нет, неправильно, {marker} это фамилия', 'стоп',
            f'привет {marker} как дела', f'что такое {marker}']
    clock = Clock(100.0)
    c = host_controller(tmp_path, clock=clock)
    with caplog.at_level(logging.DEBUG):
        for i, text in enumerate(said):
            c.provider(created(f'u{i}', 'user', text.split()[0])); clock.now += 1
            c.provider(done(f'u{i}', 'user', text)); clock.now += 1
            c.provider(created(f'a{i}', 'assistant', ''))
            c.provider(done(f'a{i}', 'assistant', f'{marker} — это ответ номер {i}. Вторая часть ответа {marker}.'))
            for _ in range(30):
                clock.now += .5; c.tick(now=clock.now)
    logged = '\n'.join(r.getMessage() for r in caplog.records)
    assert caplog.records
    for secret in (marker, 'Анна', '9161234567', 'anna.z', 'налог', 'квартир', 'ответ номер'):
        assert secret not in logged, secret
