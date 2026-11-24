"""Реестр 4.04a «Ответ с уха до финала облака» (ear_release=on под живым профилем): вопрос в сильной форме открывается на тексте уха, не дожидаясь финала облака;
паузу повтора ведёт ухо (2 с вместо 6: цикл письма берётся из речи владельца (U141), пока он молчит, паузу ведёт ухо; ~1,1 с). Граница стенда: локальное ухо с заготовленным текстом (play(ear=...)), громкий звук микрофона (host.voice).
Облако: открытый ход с частью слов (H.hears), финал приходит позже (H.final). Судим по подсказкам и журналу звонка."""
import _h4 as H

QUESTION = 'Какая столица у Австралии?'
FIRST = 'Столица Австралии — город Канберра.'
ANSWERS = {'австрал': FIRST + ' Она стоит между Сиднеем и Мельбурном.', 'австри': 'Столица Австрии — Вена. Она стоит на Дунае.'}


def call(tmp_path, monkeypatch, ear_text, final, wait=8.0, partial='Какая столица', **own):
    """Человек говорит 1 с, ухо слышит ear_text, облако держит открытый ход «Какая столица» и присылает финал final через wait секунд после конца речи."""
    model = H.Model(ANSWERS)

    async def body(host):
        host.voice('loud')
        await host.advance(0.3)
        tid = await H.hears(host, partial)
        await host.advance(1.0)
        host.voice('quiet')
        await host.advance(2.0)
        before = list(host.spoken())                     # финала облака ещё нет
        await host.advance(wait - 2.0)
        await H.final(host, tid, final)
        await host.advance(3)
        return before, list(host.spoken()), H.journal(host)
    return model, H.play(tmp_path, monkeypatch, body, model=model, ear=[ear_text], **own)


def first_cue_after_ear(rows):
    ear = next(r['t'] for r in rows if r['ev'] == 'ear_final')
    return (next(r['t'] for r in rows if r['ev'] == 'cue') - ear) / 1000.0


def test_a_strong_question_opens_on_the_ear_text_before_the_cloud_final(tmp_path, monkeypatch):
    model, (before, spoken, rows) = call(tmp_path, monkeypatch, 'Какая столица у Австралии', QUESTION)
    assert before == [FIRST], 'the cue sounded while the cloud final had not come: %s' % before
    assert ('question', 'ear_first') in H.decisions(rows), H.decisions(rows)
    assert first_cue_after_ear(rows) < 2.0, first_cue_after_ear(rows)
    cue_at = next(r['t'] for r in rows if r['ev'] == 'cue')
    assert cue_at < next(r['t'] for r in rows if r['ev'] == 'user_final'), 'the cue is before the final'
    assert model.questions()[0].startswith('Какая столица у Австралии') and len(set(model.questions())) == 1


def test_the_cloud_final_that_agrees_only_confirms_what_the_ear_opened(tmp_path, monkeypatch):
    model, (before, spoken, rows) = call(tmp_path, monkeypatch, 'Какая столица у Австралии', QUESTION)
    assert before == [FIRST] and spoken[0] == FIRST and set(spoken) == {FIRST}, 'nothing else was said after the final: %s' % spoken
    assert H.cues(rows)[0] == FIRST and set(H.cues(rows)) == {FIRST}, H.cues(rows)
    assert [r['text'] for r in rows if r['ev'] == 'user_final'] == [QUESTION]
    assert next(r['t'] for r in rows if r['ev'] == 'cue') < next(r['t'] for r in rows if r['ev'] == 'user_final'), 'the one cue was before the final'


def repeat_gap(rows):
    """Секунды между первым звучанием подсказки и её первым повтором по молчанию (по меткам cue в журнале)."""
    cues = [r['t'] for r in rows if r['ev'] == 'cue']
    assert len(cues) >= 2, 'the cue was not repeated at all: %s' % cues
    return (cues[1] - cues[0]) / 1000.0


def test_under_the_live_profile_the_repeat_comes_after_about_two_seconds(tmp_path, monkeypatch):
    """Живой профиль как есть: пока владелец молчит и не шёл по порциям, цикла письма нет (U141: он берётся из речи, не из ключа), паузу повтора ведёт ухо: ~2 с, не 6 и не 1,1."""
    model, (before, spoken, rows) = call(tmp_path, monkeypatch, 'Какая столица у Австралии', QUESTION, wait=12.0)
    assert 1.5 <= repeat_gap(rows) <= 2.5, repeat_gap(rows)


def test_control_without_the_ear_tempo_the_repeat_pause_is_six_seconds(tmp_path, monkeypatch):
    """Контроль той же проверки (не живой профиль): the ear tempo off переданы в H.play; прежняя пауза около 6 с."""
    model, (before, spoken, rows) = call(tmp_path, monkeypatch, 'Какая столица у Австралии', QUESTION, wait=12.0)
    assert 5.0 <= repeat_gap(rows) <= 7.5, repeat_gap(rows)


def test_control_a_wrong_ear_text_is_judged_again_by_the_cloud_final(tmp_path, monkeypatch):
    model, (before, spoken, rows) = call(tmp_path, monkeypatch, 'Какая столица у Австралии', 'Какая столица у Австрии?')
    assert before == [FIRST], before                      # ухо открыло на своём тексте
    assert any('Австрии' in q for q in model.questions()), model.questions()
    assert 'Вена' in spoken[-1], spoken                  # финал облака не подтвердил: ответ на то, что сказано на деле


def test_control_a_text_that_is_no_strong_question_waits_for_the_cloud_final(tmp_path, monkeypatch):
    model, (before, spoken, rows) = call(tmp_path, monkeypatch, 'столица Австралии', 'Столица Австралии?', partial='столица')
    assert before == [], before
    assert ('question', 'ear_first') not in H.decisions(rows)
    assert first_cue_after_ear(rows) > 3.0, first_cue_after_ear(rows)
    assert spoken[:1] == [FIRST], spoken                  # после финала облака ответ всё равно звучит
