"""M7/S1: ``cm_probes.probe(name, text, ctx)`` is the one door of the controller to the pure language functions (classifier, user_intents, question_part, lang_hint).
It returns a ``Feature(value, confidence, origin)``; it decides nothing."""
import pytest

from cm_patch import patch_controller
from echo_sync import classifier, cm_probes, lang_hint, question_part, user_intents
from echo_sync.cm_probes import PROBES, UNKNOWN, Feature, probe

STATE = {'chunks': ['первая часть ответа'], 'chunk_index': 0}
SAMPLE = {   # one honest call of each row: (text, ctx)
    'analyze': ('что такое налог', {'state': {}, 'settings': {}}),
    'portion_share': ('первая часть', {'state': STATE}),
    'waiting_portion': ('', {'state': STATE}),
    'known_word': ('налог', {}), 'readings': ('налог', {}),
    'ear_foreign': ('hello there', {'known': set()}), 'ear_unknown': ('hello there', {'known': set()}),
    'cross_equal': ('мак', {'other': 'mac'}),
}


def test_every_row_returns_a_feature():
    for name in PROBES:
        text, ctx = SAMPLE.get(name, ('так, что такое налог?', {}))
        found = probe(name, text, ctx)
        assert isinstance(found, Feature) and found.origin.startswith('cm_probes.'), name
        assert 0.0 <= found.confidence <= 1.0, name


def test_the_rows_cover_every_classifier_function_the_controller_calls():
    needed = {'analyze', 'strip_fillers', 'question_part', 'open_tail', 'turn_end', 'waiting_portion', 'self_corrected', 'portion_share', 'known_word', 'readings',
              'fold_asr', 'hearing_repair', 'is_confirmation_tag', 'is_repeat_request', 'pause_split', 'question_extract', 'ear_foreign', 'lang_counts', 'turn_lang'}
    assert needed <= set(PROBES)


def test_probe_is_a_call_through_of_each_classifier_function():
    settings, state = {}, {}
    assert probe('analyze', 'что такое налог', state=state, settings=settings).value == classifier.analyze('что такое налог', state, [], settings)
    assert probe('strip_fillers', 'ну что такое налог', settings=settings).value == classifier.strip_fillers('ну что такое налог', settings)
    assert probe('question_part', 'так, что такое налог?').value == classifier.question_part('так, что такое налог?')
    assert probe('open_tail', 'а потом').value == classifier.open_tail('а потом')
    assert probe('turn_end', 'а потом').value == classifier.turn_end('а потом')
    assert probe('question_extract', 'так, что такое налог?').value == question_part.extract('так, что такое налог?')
    assert probe('word_lang', 'налог').value == lang_hint.word_lang('налог') == 'ru'
    assert probe('is_stop', 'стоп', fillers=frozenset()).value == user_intents.is_stop(['стоп'], frozenset())


def test_no_evidence_is_unknown_not_a_verdict():
    assert probe('word_lang', 'B2').value == UNKNOWN and probe('word_lang', 'B2').confidence == 0.0
    assert probe('portion_share', 'что-то', state={}).value == UNKNOWN
    assert probe('pause_split', 'что такое налог').value == UNKNOWN


def test_a_toy_row_needs_only_this_module(monkeypatch):
    monkeypatch.setitem(PROBES, 'toy_length', lambda text, **_: len(text))
    assert probe('toy_length', 'abcd') == Feature(4, 1.0, 'cm_probes.lambda'.replace('lambda', '<lambda>'))
    monkeypatch.setitem(PROBES, 'toy_known', lambda text, **_: Feature('yes', 0.5, 'toy'))
    assert probe('toy_known', 'x') == Feature('yes', 0.5, 'toy')


def test_an_unknown_probe_is_an_error_not_a_silent_none():
    with pytest.raises(KeyError):
        probe('no_such_probe', 'x')


@pytest.mark.parametrize('name', ['analyze', 'strip_fillers', 'question_part', 'open_tail', 'turn_end', 'portion_share', 'self_corrected'])
def test_patch_controller_reaches_the_probe(monkeypatch, name):
    hit = patch_controller(monkeypatch, name, lambda *a, **k: 'patched')
    assert cm_probes in hit
    text, ctx = SAMPLE.get(name, ('x', {'state': {}, 'settings': {}}))
    assert probe(name, text, ctx).value == 'patched'
