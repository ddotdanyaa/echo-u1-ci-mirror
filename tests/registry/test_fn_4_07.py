"""Реестр 4.07 «Местный режим без облака» (local_fallback=on под живым профилем): облако недоступно (при открытии или посреди звонка) -- звонок не закрывается, человек слышит одну
короткую фразу о причине и получает ответы из местных баз (здесь счёт) без облака и без текстовой модели. Границы стенда: канал облака (запуск помощника-канала падает), локальное ухо
и громкая речь даёт помощник главы (ear=[вопрос], host.voice). Судим по подсказкам, журналу и кадрам телефона."""
import _h4 as H
from echo_sync import reserve_text as RT

QUESTION = 'Сколько будет тридцать шесть плюс девять?'
LINE = 'Облако недоступно. Отвечаю из местных баз.'


def call(tmp_path, monkeypatch, *, cloud_down, fall=False, ask=True, text_out=True, **own):
    """Один звонок. cloud_down: облако не открывается с самого начала; fall: канал облака обрывается через секунду звонка. Если ask, человек говорит вопрос (его слышит ухо) и молчит 4 с.
    text_out: ни одна дорога текста не ответит (первая отдыхает, запасных нет): единая дорога живая сама говорит за звонок, и тогда фразы «облако недоступно» нет (always-answer, ``_roads_alive``); фраза нужна, когда отвечать нечем кроме местных баз."""
    if text_out: monkeypatch.setitem(RT._PRIMARY, 'until', float('inf'))
    async def down(self): raise ConnectionError('cloud unreachable')
    if cloud_down: monkeypatch.setattr(H.F.FakeBridge, 'start', down)
    model = H.Model()

    async def body(host):
        await host.advance(1)
        if fall: host.bridge.inbox.put_nowait(None)                    # канал облака закрылся (конец потока)
        await host.advance(2)
        if ask:
            host.voice('loud')
            await host.advance(1)
            host.voice('quiet')
            await host.advance(4)
        return host.finished, host.errors(), list(host.spoken()), H.journal(host)
    return model, H.play(tmp_path, monkeypatch, body, model=model, ear=[QUESTION], **{'local_onset_engine': 'energy', **own})      # the stand's loud sound is a tone: the energy rule hears it as speech on every machine, the neural detector (when its model file is there) does not


def test_a_call_opens_and_says_why_when_the_cloud_is_down(tmp_path, monkeypatch):
    model, (finished, errors, spoken, rows) = call(tmp_path, monkeypatch, cloud_down=True, ask=False)
    assert ('error', 'controlled_upstream_unavailable') in [(r['ev'], r.get('code')) for r in rows], 'the cloud really was unreachable'
    assert not finished and errors == [], 'the call stayed open and the phone got no error frame: %s %s' % (finished, errors)
    assert H.cues(rows) == [LINE], H.cues(rows)


def test_a_question_is_answered_from_local_bases_without_the_cloud_and_the_model(tmp_path, monkeypatch):
    model, (finished, errors, spoken, rows) = call(tmp_path, monkeypatch, cloud_down=True)
    assert not finished and errors == []
    assert H.cues(rows)[:2] == [LINE, 'Сорок пять.'], H.cues(rows)
    assert ('question', 'local_reference') in H.decisions(rows), H.decisions(rows)
    assert [r['text'] for r in rows if r['ev'] == 'ear_final'] == [QUESTION]
    assert model.requests == [], model.questions()


def test_a_channel_that_dies_mid_call_does_not_close_it_and_the_next_question_is_answered(tmp_path, monkeypatch):
    model, (finished, errors, spoken, rows) = call(tmp_path, monkeypatch, cloud_down=False, fall=True)
    assert ('error', 'controlled_upstream_closed') in [(r['ev'], r.get('code')) for r in rows], 'the channel really fell'
    assert not finished and errors == [], (finished, errors)
    assert spoken[:2] == [LINE, 'Сорок пять.'], spoken
    assert ('question', 'local_reference') in H.decisions(rows) and model.requests == []


def test_control_with_the_cloud_up_there_is_no_local_line_and_no_local_answer(tmp_path, monkeypatch):
    model, (finished, errors, spoken, rows) = call(tmp_path, monkeypatch, cloud_down=False, ask=False)
    assert not finished and spoken == [] and H.cues(rows) == [], (spoken, H.cues(rows))
    assert not any(r['ev'] == 'error' for r in rows), rows


def test_with_a_live_road_of_text_the_cloud_gone_says_no_line_and_the_question_is_still_answered(tmp_path, monkeypatch):
    """The one road: while a road of text lives the call is answered as ever and nothing says the cloud is gone (the line is for the call that has only the local bases)."""
    model, (finished, errors, spoken, rows) = call(tmp_path, monkeypatch, cloud_down=True, text_out=False)
    assert not finished and errors == [] and LINE not in H.cues(rows) and H.cues(rows)[:1] == ['Сорок пять.'], H.cues(rows)
