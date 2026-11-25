"""Реестр 3.06: повтор по таймеру при молчании человека; потолок повторов не бесконечен (max_auto_repeats=3 под живым профилем)."""
import _h3 as H

QUESTION = 'Какая река самая длинная в Африке?'
FIRST = 'Самая длинная река Африки — Нил.'
SECOND = 'Он течёт на север и впадает в Средиземное море.'
MODEL = {'длинная': FIRST + ' ' + SECOND}                    # ответ из двух порций


def _cues_of(rows, part):
    return [text for text in H.cues(rows) if part in text]


def test_silence_repeats_the_portion_then_stops_at_the_cap(tmp_path, monkeypatch):
    async def body(host):
        await H.say(host, QUESTION)
        await host.advance(60)                              # человек молчит целую минуту
        return H.journal(host), host.spoken()

    rows, spoken = H.play(tmp_path, monkeypatch, body, model=MODEL)
    first = _cues_of(rows, 'Нил')
    assert len(first) == 4, ('one cue and exactly max_auto_repeats=3 repeats of it', H.cues(rows))
    assert set(first) == {first[0]} and not _cues_of(rows, 'Средиземное'), 'same portion again; the next one waits for the person'
    assert ('silent', 'auto_repeat_cap') in H.decisions(rows), H.decisions(rows)
    assert H.cues(rows) == first and len(spoken) >= 4, (spoken, H.cues(rows))
    times = [row['t'] for row in rows if row['ev'] == 'cue']      # метки журнала, мс
    assert all(b - a <= 3000 for a, b in zip(times, times[1:])), ('repeats come within seconds, not the 6 s default', times)


def test_repeating_aloud_gives_the_next_portion_and_the_timer_works_again(tmp_path, monkeypatch):
    async def body(host):
        await H.say(host, QUESTION)
        await host.advance(60)                              # потолок достигнут, тишина
        await H.say(host, FIRST)                            # человек повторил порцию вслух
        await host.advance(60)
        return H.journal(host)

    rows = H.play(tmp_path, monkeypatch, body, model=MODEL)
    second = _cues_of(rows, 'Средиземное')
    assert len(second) == 4, ('next portion sounds once and is repeated by silence 3 times, not forever', H.cues(rows))
    assert len(_cues_of(rows, 'Нил')) == 4, H.cues(rows)

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
