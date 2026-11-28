"""3.10 Пауза без стирания: «стоп» останавливает звук, но порция и место в ответе остаются; молчание таймера паузу не трогает, «ещё раз» возвращает ту же порцию, дальше ответ идёт с места.
Живой профиль. Пауза идёт через шлюз действий (он всегда включён); последний тест смотрит запись шлюза."""
import _h3 as H

QUESTION = 'Как устроена солнечная система?'
FIRST, SECOND, THIRD = 'Солнце держит планеты на орбитах.', 'Меркурий ближе всех к звезде.', 'Юпитер самая большая планета.'
ANSWER = ' '.join((FIRST, SECOND, THIRD))


def scene(tmp_path, monkeypatch, stop=True, **own):
    """Вопрос; человек повторил первую порцию; звучит вторая; он говорит «Стоп» (или молчит), ждёт 10 с, просит «Ещё раз», повторяет порцию вслух."""
    model = H.Model({'солнечная': ANSWER})

    async def body(host):
        await H.say(host, QUESTION)
        await H.say(host, host.spoken()[0])
        await host.advance(0.5)
        assert host.spoken()[-1] == SECOND, host.spoken()
        before = len(host.spoken())
        if stop:
            await H.say(host, 'Стоп, пожалуйста.')
        await host.advance(10)
        silence = host.spoken()[before:]                 # что прозвучало за 10 с после «стоп» (или после тишины)
        await H.say(host, 'Ещё раз.')
        await host.advance(0.5)
        again = host.spoken()[before + len(silence):]
        await H.say(host, SECOND)                        # человек повторил порцию: место в ответе не потеряно
        await host.advance(0.5)
        return {'silence': silence, 'again': again, 'next': host.spoken()[before + len(silence) + len(again):], 'rows': H.journal(host)}
    out = H.play(tmp_path, monkeypatch, body, model=model, **own)
    out['asked'] = model.questions()
    return out


def test_stop_pauses_without_erasing_the_portion(tmp_path, monkeypatch):
    out = scene(tmp_path, monkeypatch)
    assert out['silence'] == [], 'a paused answer is not repeated by the silence timer: %s' % out['silence']
    assert out['again'][:1] == [SECOND], 'the paused portion comes back on «ещё раз»: %s' % out['again']
    assert out['next'][-1:] == [THIRD], 'after the portion is said the answer goes on from the same place: %s' % out['next']
    assert out['asked'] == [QUESTION], 'the answer was kept, not asked from the model again'
    assert ('stop', 'stop_pauses_the_answer') in H.decisions(out['rows'])


def test_control_without_stop_the_timer_repeats_the_same_portion(tmp_path, monkeypatch):
    out = scene(tmp_path, monkeypatch, stop=False)
    assert out['silence'] and set(out['silence']) == {SECOND}, 'with no «стоп» the silence is filled by repeats: %s' % out['silence']
    assert not any(kind == 'stop' for kind, _ in H.decisions(out['rows']))


def test_the_pause_goes_through_the_gate_and_the_journal_says_so(tmp_path, monkeypatch):
    out = scene(tmp_path, monkeypatch)
    assert out['silence'] == [] and out['again'][:1] == [SECOND] and out['next'][-1:] == [THIRD] and out['asked'] == [QUESTION]
    acts = [(row['act'], row['reason'], row['verdict'], row['did']) for row in out['rows'] if row['ev'] == 'why' and row.get('kind') == 'act']
    assert ('pause', 'stop', 'do', 1) in acts, acts

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
