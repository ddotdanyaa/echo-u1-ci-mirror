"""The text before the voice (always on, no switch) is wired to ``render_cue_pcm``: every digit, symbol and abbreviation is brought to words
(``speech_text.speak``) and the numbers and the meaning stay (read back from the spoken text); the PCM cache key carries its mark (``voice_key``). Level2-c of 06.11: the bank sound of «с 01.01.2026»
was the voice's own reading of the digits."""
import json
import os
import wave
from decimal import Decimal
from pathlib import Path

import pytest

from echo_sync import pcm_cache
from echo_sync import speech_text as S
from echo_sync.controlled_host import render_cue_pcm, voice_key
from echo_sync.speech_text import speak
from echo_sync.settings import DEFAULTS, resolve

BANK = Path(os.environ.get('ECHO_BANK_5') or r'C:\УСТРОЙСТВО 1\U1\МАТЕРИАЛЫ\БАНК\instant_bank_5.json')
OWNER_CASES = [
    'Основная ставка НДС — 22 процента с 1 января 2026 года.',
    'С 01.01.2026 ставка НДС 22 %.',
    'Это статья 15 НК РФ, ст. 15 устанавливает местные налоги и сборы.',
    'Форма КО-2 — расходный кассовый ордер, КО-1 — приходный.',
    'Штраф 20 % от неуплаченной суммы, не менее 40 000 рублей, 1,5 млн ₽.',
    'Приказ Минфина от 17 сентября 2020 года N 204н, счёт 90.1, ФСБУ 6/2020.',
    'Задания на 6 ноября нет: в дневнике по МДК.03.01 на эту дату ничего не записано.',
]


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


class FakeVoice:
    """A synthesizer that keeps what it was asked to say and writes a short valid WAV."""

    voice = 'fake'

    def __init__(self):
        self.said = []

    def synthesize(self, text, output_path, **kwargs):
        self.said.append(text)
        with wave.open(str(output_path), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(24000)
            out.writeframes(b'\x10\x00' * 2400)


def test_the_switch_is_gone():
    assert 'speech_text' not in DEFAULTS and 'speech_text' not in resolve({'speech_text': 'off'})


def test_the_voice_gets_words_never_digits(tmp_path):
    text = 'Штраф 20 % и 40 000 рублей, КО-2.'
    voice = FakeVoice()
    assert render_cue_pcm(voice, text, tmp_path)
    assert voice.said == [speak(text)] and not any(ch.isdigit() for ch in voice.said[0]) and 'ка о два' in voice.said[0], voice.said
    assert 'сорок тысяч' in voice.said[0] and 'двадцать процентов' in voice.said[0]


def test_the_cache_key_carries_the_mark_so_a_sound_made_from_digits_is_not_reused():
    assert voice_key('sapi-irina') == 'sapi-irina:speech' and voice_key(None) == 'sapi:speech' and voice_key('v', 'fall') == 'v:fall:speech'
    text = 'С 1 января 2026 года ставка 22 %.'
    assert pcm_cache.key(text, voice_key('v'), 24000) != pcm_cache.key(text, 'v', 24000)


def test_a_cue_is_spoken_once_and_then_read_from_the_cache(tmp_path):
    cache = pcm_cache.PcmCache(tmp_path / 'pcm')
    voice = FakeVoice()
    text = 'Ставка 22 %.'
    for _ in range(2):
        pcm_cache.cached(cache, lambda said: render_cue_pcm(voice, said, tmp_path), text, voice_key('v'), 24000)
    assert voice.said == [S.speak(text)]


@pytest.mark.parametrize('text', OWNER_CASES)
def test_the_numbers_of_a_cue_are_the_numbers_of_its_speech(text):
    spoken = S.speak(text)
    assert not any(ch.isdigit() for ch in spoken), spoken
    assert S.numbers_of(text) == S.read_back(spoken), (text, spoken)


def test_a_course_code_is_said_digit_by_digit_not_as_a_date():
    """bank 5, b01118: «МДК.03.01» was said «третьего января»."""
    for text in ('МДК.03.01', 'МДК 03.01', 'по МДК.03.01 на эту дату'):
        spoken = S.speak(text)
        assert 'января' not in spoken and 'ноль три точка ноль один' in spoken, (text, spoken)
    assert S.speak('с 15.03 до 20.03') == 'с пятнадцатого марта до двадцатого марта'


@pytest.mark.skipif(not BANK.exists(), reason='the bank lives outside the repository')
def test_every_number_of_every_answer_of_bank_5_is_the_same_number_in_its_speech():
    rows = json.loads(BANK.read_text(encoding='utf-8'))
    assert len(rows) > 1000
    bad, texts = [], 0
    for row in rows:
        for key in ('core', 'answer'):
            text = row.get(key)
            if not isinstance(text, str) or not text.strip():
                continue
            texts += 1
            spoken = S.speak(text)
            if any(ch.isdigit() for ch in spoken) or S.numbers_of(text) != S.read_back(spoken):
                bad.append((row.get('id'), key, text[:80], [str(x) for x in S.numbers_of(text)[:6]], [str(x) for x in S.read_back(spoken)[:6]]))
    assert texts > 2000 and not bad, (len(bad), bad[:5])
