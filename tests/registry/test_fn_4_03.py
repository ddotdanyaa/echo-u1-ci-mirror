"""Реестр 4.03 «Ответ моделью: быстрый текст Codex»: вопрос вне банка уходит текстовой модели, первая порция её ответа становится подсказкой
раньше облачного голоса; промолчавшая или упавшая модель подсказки не даёт. Живой профиль сервера (fast_text=on). Граница: сценарная модель."""
import _h4 as H

QUESTION = 'Какая самая высокая гора в Андах?'
FIRST = 'Самая высокая гора в Андах — Аконкагуа.'
SECOND = 'Она стоит в Аргентине.'
VOICE = 'Это Аконкагуа, шесть тысяч девятьсот шестьдесят метров.'


def test_a_question_outside_the_bank_gets_the_model_first_portion_before_the_cloud_voice(tmp_path, monkeypatch):
    model = H.Model({'гора': FIRST + ' ' + SECOND})

    async def body(host):
        await H.say(host, QUESTION)
        await host.advance(1)
        before = list(host.spoken())                      # облако ещё молчит
        await H.cloud_answer(host, VOICE)                 # облачный голос приходит позже
        await host.advance(2)
        return H.journal(host), before, list(host.spoken())

    rows, before, spoken = H.play(tmp_path, monkeypatch, body, model=model)
    assert model.questions() == [QUESTION], 'the question went to the model, once'
    assert before[:1] == [FIRST], before                  # первая порция опубликована без облачного голоса
    assert ('answer', 'fast_text_owns') in H.decisions(rows)
    cue_at = min(row['t'] for row in rows if row['ev'] == 'cue')
    voice_at = min(row['t'] for row in rows if row['ev'] == 'assistant_final')
    assert cue_at < voice_at, (cue_at, voice_at)          # подсказка раньше облачного голоса
    assert set(spoken) == {FIRST}, 'the cloud voice did not replace the model cue: %s' % spoken


def test_a_second_portion_comes_only_after_the_first_is_repeated_aloud(tmp_path, monkeypatch):
    model = H.Model({'гора': FIRST + ' ' + SECOND})

    async def body(host):
        await H.say(host, QUESTION)
        await host.advance(1)
        await H.say(host, FIRST)                          # человек повторил первую порцию вслух
        await host.advance(1)
        return list(host.spoken())

    spoken = H.play(tmp_path, monkeypatch, body, model=model)
    assert spoken[:1] == [FIRST] and SECOND in ' '.join(spoken[1:]), spoken


def test_a_silent_model_gives_no_cue_of_its_own(tmp_path, monkeypatch):
    model = H.Model({})                                   # на любой вопрос модель отвечает «—»

    async def body(host):
        await H.say(host, QUESTION)
        await host.advance(2)
        return H.journal(host), list(host.spoken())

    rows, spoken = H.play(tmp_path, monkeypatch, body, model=model)
    assert model.questions() == [QUESTION], 'the model was asked'
    assert ('silent', 'fast_text_declined') in H.decisions(rows)
    assert spoken == [] and H.cues(rows) == [], spoken


import pytest      # noqa: E402

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
