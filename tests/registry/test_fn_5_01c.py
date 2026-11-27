"""Registry 5.01c «Текст перед голосом: цифры, символы, сокращения словами» (state per registry: ВЫКЛЮЧЕНО, key speech_text, code default off).

Goal described here (xfail strict until the key is on by default / switched on at deployment): through the real controlled_host.serve()
(helpers_s6_fault.HostRig, virtual time, fake phone / cloud / SAPI worker) the cloud's answer is published to the phone as written, while the text
that reaches the synthesizer (the fake SAPI worker's call log) has a date, «ст. 15», «22 %» and money brought to words, no digit and no symbol left.
The profile file does NOT set speech_text: the engine default, read at run time, acts (as of now off -> the voice gets «22 %» and «40000» as is).
The fifth test pins a known defect of the code behind the key: a date written with «года» ("01.01.2026 года") is voiced «...шестого года года».
Mutation check (private copy): the default of speech_text in echo_sync/settings.py switched off -> on: the four first tests pass under --runxfail, the fifth
still fails on the doubled word (a one-line fix of the date branch in the copy makes it pass too); key off: all fail.
"""
import json
import re
from pathlib import Path

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

NO_SYMBOLS = re.compile(r'[\d%₽]')


def settings_file(home, **values):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


def one_portion(tmp_path, monkeypatch, answer):
    """A question and a one-portion answer; returns (what the phone was shown, what went to the synthesizer for it)."""
    async def body(host):
        settings_file(host.home)                # no speech_text key: the engine default acts
        before = len(host.synth_plan.calls)
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(answer)
        await host.advance(2)
        shown = host.spoken()
        return shown, [text for _, text in host.synth_plan.calls[before:]][:1]      # the first synthesized cue after the question
    return run_host(tmp_path, monkeypatch, body)


@pytest.mark.parametrize('answer,words,written', [
    ('С 01.01.2026 налог растёт для всех плательщиков,', ('первого января', 'две тысячи двадцать шестого года'), '01.01.2026'),
    ('Об этом прямо сказано в ст. 15 кодекса для всех,', ('стат', 'пятнадцат'), 'ст. 15'),
    ('Ставка налога составляет 22 % от суммы для всех,', ('двадцать два процента',), '22 %'),
    ('Штраф составит не менее 40 000 рублей для всех.', ('сорока тысяч рублей',), '40 000'),
], ids=['date', 'article', 'percent', 'money'])
def test_voice_gets_words_and_phone_gets_the_written_text(tmp_path, monkeypatch, answer, words, written):
    shown, sent = one_portion(tmp_path, monkeypatch, answer)
    assert len(shown) == 1 and answer.startswith(shown[0]) and written in shown[0], shown      # the phone text keeps the cloud's own digits and symbols
    assert len(sent) == 1 and not NO_SYMBOLS.search(sent[0]), sent          # nothing but words went to the voice
    assert all(word in sent[0] for word in words), sent


@pytest.mark.xfail(strict=True, reason='реестр 5.01c: и при включённом тексте перед голосом слово «года» задваивается («...двадцать шестого года года»)')
def test_date_with_the_word_year_is_not_doubled(tmp_path, monkeypatch):
    answer = 'С 01.01.2026 года налог растёт для всех плательщиков,'
    shown, sent = one_portion(tmp_path, monkeypatch, answer)
    assert len(shown) == 1 and answer.startswith(shown[0]) and '01.01.2026 года' in shown[0], shown
    assert len(sent) == 1 and not NO_SYMBOLS.search(sent[0]), sent
    assert 'двадцать шестого года' in sent[0] and 'года года' not in sent[0], sent          # the year word must be spoken once
