"""Реестр 4.04b «Задание модели на тексте уха до финала»: вопрос без формы вопроса (ухо пишет «нужно солить воду …» без «?») получает ответ до облачного финала,
если задание модели стартует на тексте уха и на открытом ходе облака. Реестр: ВЫКЛЮЧЕНО (ear_job, cloud_form, ear_lookup в файле on, но действуют off, пока prepare_wide=off).
Граница: локальное ухо (в облаке его нет): заготовленный текст на конец речи; громкий звук в микрофоне телефона даёт речь по энергии; сценарная модель.
Включение: ECHO_REGISTRY_SET="prepare_wide=on" (три ключа уже on в файле). Пустышка: ECHO_REGISTRY_SET="ear_job=off" краснит тест при включённом ключе."""
import pytest
import _h4 as H

FORMLESS = 'Нужно солить воду, когда варишь макароны?'                    # облако пишет «?», ухо слышит только слова
FORMLESS_EAR = 'нужно солить воду когда варишь макароны'
FORMED = 'Какая самая длинная река в Южной Америке?'
FORMED_EAR = 'какая самая длинная река в южной америке'
PASTA = 'Воду солят в начале варки. Обычно берут около десяти граммов соли на литр.'
RIVER = 'Самая длинная река Южной Америки — Амазонка. Она течёт через Бразилию.'
KEYS = dict(prepare_wide='on')       # ear_job, cloud_form, ear_lookup уже on в файле сервера; движок включает их только при prepare_wide=on


def scene(tmp_path, monkeypatch, said, ear_text, answers, **own):
    """Человек говорит вопрос (облако пишет его по слову, ухо слышит речь), затем 3.3 с тишины до облачного финала.
    Возвращает: что звучало ДО финала, что ушло модели до финала, что звучало после, журнал."""
    model = H.Model(answers)

    async def body(host):
        await host.advance(0.5)
        host.voice('loud')
        words = said.split(' ')
        tid = await H.hears(host, words[0])
        for word in words[1:]:
            await host.advance(0.25)
            await H.hears_more(host, tid, word)
        host.voice('quiet')
        await host.advance(3.3)                                  # речь кончилась, облачный финал ещё не пришёл
        before, asked = list(host.spoken()), model.questions()
        await H.final(host, tid, said)
        await host.advance(1)
        return before, asked, list(host.spoken()), H.journal(host)
    return H.play(tmp_path, monkeypatch, body, model=model, ear=[ear_text], **own)


def check_cue_before_final(result):
    before, asked, _, rows = result
    assert asked and 'макарон' in asked[0], 'the job on the ear text started before the cloud final: %s' % asked
    assert before[:1] == [PASTA.split('. ')[0] + '.'], 'the first portion is already said before the final: %s' % before
    assert ('answer', 'fast_text_owns') in H.decisions(rows)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 4.04b: ВЫКЛЮЧЕНО, ear_job/cloud_form/ear_lookup в файле on, но действуют off без prepare_wide')
def test_a_question_without_a_form_is_answered_before_the_cloud_final(tmp_path, monkeypatch):
    check_cue_before_final(scene(tmp_path, monkeypatch, FORMLESS, FORMLESS_EAR, {'макарон': PASTA}))


def test_with_the_keys_on_the_same_question_is_answered_before_the_cloud_final(tmp_path, monkeypatch):
    check_cue_before_final(scene(tmp_path, monkeypatch, FORMLESS, FORMLESS_EAR, {'макарон': PASTA}, **KEYS))


def test_control_under_the_live_profile_the_same_question_is_answered_only_after_the_final(tmp_path, monkeypatch):
    before, asked, after, rows = scene(tmp_path, monkeypatch, FORMLESS, FORMLESS_EAR, {'макарон': PASTA})
    assert before == [] and asked == [], 'nothing is said and the model is not asked until the cloud final: %s %s' % (before, asked)
    assert after[:1] == [PASTA.split('. ')[0] + '.'], 'the answer comes with the final: %s' % after
    assert ('answer', 'fast_text_owns') in H.decisions(rows)


def test_control_a_question_with_a_form_is_answered_before_the_final_without_the_keys(tmp_path, monkeypatch):
    before, asked, _, rows = scene(tmp_path, monkeypatch, FORMED, FORMED_EAR, {'река': RIVER})
    assert asked and 'река' in asked[0] and before[:1] == ['Самая длинная река Южной Америки — Амазонка.'], (asked, before)
    assert ('answer', 'fast_text_owns') in H.decisions(rows)
