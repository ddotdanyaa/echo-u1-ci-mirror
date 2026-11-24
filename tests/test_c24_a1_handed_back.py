"""c24-a1 (fuzz seed 143, A2 with a dangerous number): «Если у меня было 70 рублей и я потратил 30 рублей, сколько денег осталось?» after the same with 30 and 70; the
cloud lost its final, the ear stood in, the job failed and the question went back to the cloud (``fast_text_candidate_handed_back``). The older answer «Не хватает 40
рублей.» is held while such a question waits (A1-F2, ``_candidate_form_asks``) - but only a question by its form, and the ear's text has no «?»: the classifier read
it as no question and «Не хватает 40 рублей.» was cued for «Осталось 40 рублей.». The form of a question is read without the mark too (``question_part.extract``)."""
import pytest

CS = 'prepare_wide=on,ear_release=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,stumble_place=on,local_fallback=on'


def test_a_question_handed_back_holds_the_older_answer(monkeypatch):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    assert [v for v in stand.run(143).violations if v[0] in ('A2', 'A2e', 'A7')] == []


@pytest.mark.parametrize('text,asks', [('если у меня было семьдесят рублей и я потратил тридцать рублей сколько денег осталось', True),
                                       ('нужно не охлаждать а нагревать эту жидкость при таком давлении', True),
                                       ('маша закрой дверь пожалуйста', False), ('да я готовился на самом деле', False)])
def test_the_form_of_a_question_without_its_mark(text, asks):
    from echo_sync.classifier import question_by_form
    assert question_by_form(text) is asks
