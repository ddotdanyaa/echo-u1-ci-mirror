"""3.07 Режим записи: потолок повторов по молчанию вне записи 3, пока человек пишет (повторил вслух подряд две порции ответа) растёт до 15. Судим по подсказкам и журналу звонка."""
import _h3 as H

PORTIONS = ['Сатурн — шестая планета от Солнца.', 'Его кольца состоят из льда и камней.', 'У Сатурна больше восьмидесяти спутников.',
            'Самый крупный спутник называется Титан.', 'Год на Сатурне длится почти тридцать земных лет.']
ANSWER = ' '.join(PORTIONS)


def call(tmp_path, monkeypatch, said_aloud):
    """Человек спрашивает, повторяет вслух первые ``said_aloud`` порций ответа и дальше молчит две минуты; возвращает (подсказки, журнал)."""
    async def body(host):
        await H.say(host, 'Расскажи про планету Сатурн.')
        await host.advance(3)
        for portion in PORTIONS[:said_aloud]:
            await H.say(host, portion)
            await host.advance(1)
        await host.advance(120)
        return host.spoken(), H.journal(host)
    return H.play(tmp_path, monkeypatch, body, model={'сатурн': ANSWER})


def test_a_silent_owner_who_has_not_written_gets_the_portion_three_more_times(tmp_path, monkeypatch):
    spoken, rows = call(tmp_path, monkeypatch, said_aloud=0)
    assert set(spoken) == {PORTIONS[0]}, 'nobody went on, the first portion only'
    assert len(spoken) == 1 + 3, spoken                    # раз сказана и три повтора по молчанию
    assert ('silent', 'auto_repeat_cap') in H.decisions(rows)


def test_one_portion_said_aloud_is_not_yet_writing(tmp_path, monkeypatch):
    spoken, rows = call(tmp_path, monkeypatch, said_aloud=1)
    assert spoken.count(PORTIONS[1]) == 1 + 3, spoken      # человек продвинулся на одну порцию: ещё не запись
    assert PORTIONS[2] not in spoken


def test_two_portions_said_aloud_is_writing_and_the_cap_rises(tmp_path, monkeypatch):
    spoken, rows = call(tmp_path, monkeypatch, said_aloud=2)
    assert spoken.count(PORTIONS[2]) == 1 + 15, spoken     # пока человек пишет, подсказка повторяется до 15 раз
    assert spoken[-16:] == [PORTIONS[2]] * 16
    assert ('silent', 'auto_repeat_cap') in H.decisions(rows)
