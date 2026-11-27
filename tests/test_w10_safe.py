"""w10-integ item 1 (WAVE10.md): the rest of W9S-F1 on top of E88. The PUBLIC search (``public_lookup_allowed(search=True)``, the gate of ``_lookup``, of the ear's
prefetch and of ``impersonal``) never sees a phone, an e-mail, a card, a passport, «кто/почему/сколько я», nor the name of an introduction; the
route's own gate (``public_lookup_allowed``) is not touched (the bare «я» is the speaker's frame: w9-safe, 16 tests). A general question after an
introduction is still looked up - its question part, without the name."""
import pytest

from echo_sync.controlled_media import ControlledMedia

impersonal = ControlledMedia._impersonal
from echo_sync.generator import needs_verification
from test_w9_safe import LEAKS, PUBLIC
from test_w3_integ import PUBLIC as E88_PUBLIC

INTRO = 'Добрый день, меня зовут Игорь Петров, я звоню уже в третий раз. До какого числа сдавать декларацию по НДС?'


@pytest.mark.parametrize('question', LEAKS + ['почему я опоздал на поезд', 'куда я положил ключи', 'мой номер 8 916 123 45 67 запиши', 'СНИЛС 123-456-789 01 чей'])
def test_w10_personal_or_contact_data_never_reaches_the_public_search(question):
    assert not ControlledMedia.public_lookup_allowed(question, True)


@pytest.mark.parametrize('question', PUBLIC + E88_PUBLIC + ['скажи мне, какая ставка НДС в 2026 году', 'сколько стоит 1 доллар в рублях'])
def test_w10_a_public_question_keeps_its_search(question):
    assert ControlledMedia.public_lookup_allowed(question, True)


@pytest.mark.parametrize('question', ['кто я такой', 'позвони на 89161234567 и узнай курс', 'что пришло на ivan.petrov@mail.ru'])
def test_w10_impersonal_never_hands_contact_data_to_the_search(question):
    assert impersonal(question) == '' or ControlledMedia.public_lookup_allowed(impersonal(question), True)
    assert '8916' not in impersonal(question) and '@' not in impersonal(question)


def test_w10_the_question_after_an_introduction_is_looked_up_without_the_name(tmp_path, monkeypatch):
    from helpers_spoken_diagnostics import run_wire
    from test_f3_delegation import Model
    assert needs_verification(INTRO, ()) and not ControlledMedia.public_lookup_allowed(INTRO, True), 'precondition'

    async def body(rig):
        model = Model(rig)
        await model.question(INTRO, 'Декларацию по НДС подают до двадцать пятого числа.')
        assert len(rig.lookup_plan.calls) == 1, rig.lookup_plan.calls
        query = rig.lookup_plan.calls[0][1]
        assert 'игорь' not in query.casefold() and 'петров' not in query.casefold() and 'меня' not in query.casefold(), query
        assert 'деклараци' in query.casefold() and ControlledMedia.public_lookup_allowed(query, True), query
    run_wire(tmp_path, monkeypatch, body)
