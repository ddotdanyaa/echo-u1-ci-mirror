"""U14-S5: the recall parser and resolver."""
import json
from pathlib import Path

import pytest

from echo_sync.conversation_ledger import ConversationLedger
from echo_sync.recall import Recall, parse, resolve

SCENES = Path(__file__).parent / 'fixtures' / 'harvest_scenes' / 'scenes.json'


def test_owner_phrase_user_20():
    assert parse('Слушай, повтори там мои последние 20 слов') == Recall('user', 20)


def test_no_owner_means_assistant_words_heard():
    assert parse('повтори последние пять слов') == Recall('assistant', 5)
    assert parse('повтори твои последние три слова') == Recall('assistant', 3)


@pytest.mark.parametrize('text,expected', [
    ('could you please repeat my last 12 words', Recall('user', 12)),
    ('Ну пожалуйста, скажи мои последние двадцать пять слов', Recall('user', 25)),
    ('повтори 20 последних слов', Recall('assistant', 20)),
])
def test_other_forms(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize('text', [
    'повтори', 'повтори со слова налог', 'повтори последнюю фразу', 'повтори пять', 'он сказал повтори пять слов',
    'повтори вторые слова', 'скажи пять слов о себе', 'прочитай первые 10 слов договора', 'скажи по-английски два слова', '', None, 'какой сегодня курс доллара'])
def test_misses(text):
    assert parse(text) is None


@pytest.mark.skipif(not SCENES.exists(), reason='data outside the repository: tests/fixtures/harvest_scenes/scenes.json (real call scenes of the owner are kept out of git)')
def test_real_scenes_are_not_recall():
    scenes = {s['id']: s for s in json.loads(SCENES.read_text(encoding='utf-8'))['scenes']}
    for sid in ('S11', 'S13', 'S38'):
        assert parse(scenes[sid]['text']) is None


def test_resolve_user_and_assistant():
    led = ConversationLedger()
    led.user_final('t1', 'раз два три четыре пять', final_rev=1)
    led.play_began('c1', 'шесть семь восемь девять', 0.0, voiced_s=2.0)
    led.play_done('c1', 2.0)
    assert resolve(led, Recall('user', 3)) == ['три', 'четыре', 'пять']
    assert resolve(led, Recall('assistant', 2)) == ['восемь', 'девять']
    assert resolve(led, None) == []
