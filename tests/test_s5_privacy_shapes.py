"""S5: personal data by SHAPE (a city/international phone, an account, an IBAN, a full name (any case of the letters), an address, a secret word + its value) never reaches the PUBLIC search;
a public question with numbers («статья 422 НК», «ставка 20 %», «счёт 62», a sum, a classifier code, «Как зовут Путина», «Пароль 12 символов», «Родился Пушкин 06.06.1799») still does. The rig is the real ControlledMedia + NativeMediaSocket of test_a_e88_calls (the lookup route is open there).
The decision itself is asserted (the gate refuses / lets), and what ``World.lookup_calls`` was given is read. Not run on the laptop."""
import pytest

import helpers_s6_state as S
from echo_sync import privacy_gate
from echo_sync.controlled_media import ControlledMedia
from test_h1_fast_text import rig      # noqa: F401 - rig is the fixture

BASE = 'Проверь, пожалуйста, что такое гидравлический удар'
PERSONAL = ['495 123-45-67', '+49 30 1234567', '8 (4012) 12-34-56', '+1 (555) 123-4567', 'звони 123-45-67', 'счёт 40817810338000001234', 'р/с 40817 810 3 3800 0000123',
            'IBAN DE89 3704 0044 0532 0130 00', 'я родился 12.03.1990', 'Иванов Иван Иванович', 'иванов иван иванович', 'Иван Петрович Сидоров', 'меня зовут Данил',
            'живу на улице Ленина, дом 5', 'ул. Тверская, д. 7, кв. 12', 'пароль 1234', 'пароль: qwerty12', 'PIN 4321', 'cvv 123', 'код из смс 4455', 'смс-код 5566', 'логин admin']
PUBLIC = ['статья 422 НК', 'ставка 20 %', 'счёт 62', 'как заполнить платёжное поручение', 'ОКВЭД 62.01', 'какая ставка НДС в 2024 году', 'сколько стоит 1 500 000 рублей в долларах',
          'как придумать пароль', 'что такое PIN-код', 'закон 115-ФЗ о ККТ', 'код ошибки 404', 'код ТН ВЭД 8471', 'тарифы 2023 2024', 'ставка 7,5 % до 12.03.2024', 'когда родился Пушкин',
          'Федеральный закон 54-ФЗ от 22.05.2003', 'курс 92,45 на 15.11.2024', 'Как зовут Путина', 'Пароль 12 символов', 'смс-код 6 цифр', '+12 000 000 рублей', 'ТН ВЭД 8471 30 00 00', 'Родился Пушкин 06.06.1799', 'ОКПО 12345678', 'площадь 45 кв. м', 'сколько 100 000 000 000 в рублях', 'Конституция РФ статья 29 пункт 3']


def ask(rig, text):
    rig.w.feed(S.turn_created('u1', 'user', text.split()[0]))
    rig.w.feed(S.turn_done('u1', 'user', text))
    rig.pump()


@pytest.mark.parametrize('form', PERSONAL)
def test_the_gate_refuses_personal_data_by_shape(form):
    assert not ControlledMedia.public_lookup_allowed(f'{BASE}, {form}.', True)


@pytest.mark.parametrize('form', PERSONAL)
def test_personal_data_never_reaches_the_public_search(rig, form):
    ask(rig, f'{BASE}, {form}.')
    token = form.split()[-1].strip('.,')
    for query in rig.w.lookup_calls:
        assert ControlledMedia.public_lookup_allowed(query, True), f'S5: «{query}» went to the public search'
        assert token not in query, f'S5: «{query}» carries «{token}»'


@pytest.mark.parametrize('form', PUBLIC)
def test_a_public_question_with_numbers_stays_public_and_is_searched(rig, form):
    assert ControlledMedia.public_lookup_allowed(f'{form}, что такое гидравлический удар?', True), 'a false refusal'
    ask(rig, f'{BASE}, {form}.')
    assert rig.w.lookup_calls, 'a public question must reach the public search'
    assert all(ControlledMedia.public_lookup_allowed(query, True) for query in rig.w.lookup_calls)
