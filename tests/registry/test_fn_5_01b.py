"""Registry 5.01b «Римские цифры, века, числа словами» (state per registry: РАБОТАЕТ НА СЕРВЕРЕ, phone not checked).

Proved through the real controlled_host.serve() (helpers_s6_fault.HostRig, virtual time, fake phone / cloud / SAPI worker): the cloud's answer is
published to the phone as written, and the text that goes to the synthesizer (the fake SAPI worker's call log) has a Roman century range read as
words («XIII-XV веках» and «с XIII по XV век» -> «с тринадцатого по пятнадцатый век») and a grouped number in words («40 000» -> «сорок тысяч»; the old reading was «сорок ноль ноль ноль», E89). Live profile values are set explicitly: number_ranges=off
(code defaults equal the live ones). What the voice then sounds like is NOT proved here (see the proof record: phone recipe).
Mutation check (private copy): _whole_numbers() in echo_sync/speech_text.py replaced by an identity function -> the tests go red; restored -> green.
"""
import json
from pathlib import Path

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

LIVE = {'number_ranges': 'off'}


def settings_file(home, **values):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


def one_portion(tmp_path, monkeypatch, answer, **settings):
    """A question and a one-portion answer; returns (what the phone was shown, what went to the synthesizer for it)."""
    async def body(host):
        settings_file(host.home, **settings)
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(answer)
        await host.advance(2)
        shown = host.spoken()
        return shown, [text for _, text in host.synth_plan.calls if shown and text.startswith(shown[0][:12])]
    return run_host(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('answer,voiced', [
    ('Торговые города Италии процветали в XIII-XV веках,', 'Торговые города Италии процветали с тринадцатого по пятнадцатый век,'),
    ('Соседи тоже расцвели с XIII по XV век.', 'Соседи тоже расцвели с тринадцатого по пятнадцатый век.'),
    ('Тогда там жило около 40 000 жителей,', 'Тогда там жило около сорока тысяч жителей,'),
    ('А потом их стало 1 250 000.', 'А потом их стало один миллион двести пятьдесят тысяч.'),
], ids=['century_range_dash', 'century_range_s_po', 'grouped_number', 'grouped_million'])
def test_voice_text_is_words_and_phone_text_is_as_written(tmp_path, monkeypatch, answer, voiced):
    shown, sent = one_portion(tmp_path, monkeypatch, answer, **LIVE)
    assert shown == [answer], shown            # the published portion keeps the cloud's own text
    assert sent == [voiced], sent              # the synthesizer got it spoken: words for the Roman numerals, one whole number


def test_single_century_is_a_word(tmp_path, monkeypatch):
    shown, sent = one_portion(tmp_path, monkeypatch, 'Город основали в XIV веке, давно.', **LIVE)
    assert shown == ['Город основали в XIV веке, давно.'] and sent == ['Город основали в четырнадцатом веке, давно.'], sent
