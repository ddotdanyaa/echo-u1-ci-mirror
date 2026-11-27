"""P04 (harvest g5-when-cue, integ-c17): the quiet side and the cue side of the reading of one utterance, by class.

Quiet: «что» after a verb of saying / knowing / thinking (or a thanks) is the conjunction, not a question word: «Она сказала, что приедет вечером, когда закончит работу»
(the long_quiet corpus line) is a report, no question. Cue: the ear's phonetic spellings («што такое налог», «пачему растёт инфляция») are the question words they sound like,
and «помоги понять / вспомнить / разобраться …» asks like «объясни …». Every case goes through the real ``ControlledMedia`` (Wire): the judge's line says what the call decided."""
import itertools
import logging

import pytest

from echo_sync.classifier import QUESTION, analyze, heard_spelling
from echo_sync.cm_probes import UNKNOWN, probe
from echo_sync.settings import CALL_SETTINGS
from helpers_w1f import Wire

SUBJECTS_GOVERNORS = ['я знаю', 'я думаю', 'она сказала', 'он говорил', 'мы надеемся', 'я понимаю', 'я помню', 'они слышали', 'он ответил', 'я видел', 'спасибо', 'жаль', 'она написала']
TAILS = ['налог растёт', 'это так', 'они приедут вечером', 'вы пришли', 'завтра будет дождь', 'приедет вечером, когда закончит работу']


def judged(tmp_path, caplog, text, end=2.0):
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = Wire(tmp_path)
    w.user('u1', text, 0.0, end)
    w.until(end + 4.0)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith('echo-sync judge tid=u1')]
    assert lines, text
    return lines[-1].split()[3].split('=')[1], w


@pytest.mark.parametrize('governor,tail', list(itertools.product(SUBJECTS_GOVERNORS, TAILS)))
def test_a_report_with_the_conjunction_what_is_no_question(governor, tail):
    said = f'{governor} что {tail}'
    assert analyze(said, {}, [], CALL_SETTINGS).kind != QUESTION, said


@pytest.mark.parametrize('said', [
    'Она сказала, что приедет вечером, когда закончит работу.', 'Спасибо, что пришли', 'Я знаю что налог растёт', 'Он говорил, что сколько нужно, столько и дадут'])
def test_the_call_stays_quiet_on_a_report(tmp_path, caplog, said):
    assert judged(tmp_path, caplog, said)[0] != 'question'


def test_the_transliterated_long_quiet_line_stays_quiet_too(tmp_path, caplog):
    kind, w = judged(tmp_path, caplog, 'Ona skazala, chto priedet vecherom, kogda zakonchit rabotu.')
    assert kind != 'question' and not w.issued


@pytest.mark.parametrize('said', ['Скажи что такое налог', 'Знаешь что такое налог?', 'Что такое налог', 'Подскажи, что такое НДС', 'Расскажи что нового в налоговом кодексе',
                                  'Я знаю что такое налог, а что такое НДС', 'Почему она сказала что приедет вечером?', 'Что сказала она'])
def test_a_real_question_with_the_word_what_is_still_a_question(said):
    assert analyze(said, {}, [], CALL_SETTINGS).kind == QUESTION, said


def test_the_probe_reports_the_conjunction_and_decides_nothing():
    assert probe('conjunction_that', 'она сказала что приедет').value == 1
    assert probe('conjunction_that', 'скажи что такое налог').value == UNKNOWN


@pytest.mark.parametrize('heard,said', [('што такое налог', 'что такое налог'), ('шта такое налог', 'что такое налог'), ('чё такое налог', 'что такое налог'),
                                        ('пачему растёт инфляция', 'почему растёт инфляция'), ('почиму растёт инфляция', 'почему растёт инфляция'),
                                        ('сколька стоит патент', 'сколько стоит патент'), ('када принят кодекс', 'когда принят кодекс'), ('кагда принят кодекс', 'когда принят кодекс'),
                                        ('зачим нужен налог', 'зачем нужен налог'), ('пажалуйста объясни налог', 'пожалуйста объясни налог')])
def test_the_ears_phonetic_spelling_is_the_word_it_sounds_like(heard, said):
    assert heard_spelling(heard) == said
    assert analyze(heard, {}, [], CALL_SETTINGS).kind == QUESTION, heard


@pytest.mark.parametrize('text', ['налог растёт', 'он знает кто пришёл', 'мама мыла раму', 'Саша пришла домой', 'ладно', 'что такое налог', 'пока'])
def test_a_known_word_or_a_remark_is_never_respelled(text):
    assert heard_spelling(text) == text


def test_the_call_cues_on_a_phonetic_question(tmp_path, caplog):
    assert judged(tmp_path, caplog, 'Што такое амортизация')[0] == 'question'


@pytest.mark.parametrize('verb', ['понять', 'вспомнить', 'разобраться'])
@pytest.mark.parametrize('lead', ['помоги', 'помогите', 'помоги мне', 'пожалуйста помоги'])
def test_help_me_understand_asks_like_explain(lead, verb):
    said = f'{lead} {verb} как считается амортизация' if verb == 'понять' else f'{lead} {verb} как считается амортизация'
    assert analyze(said, {}, [], CALL_SETTINGS).kind == QUESTION, said
    bare = f'{lead} {verb} с налогом'
    assert analyze(bare, {}, [], CALL_SETTINGS).kind == QUESTION, bare
    assert analyze(f'я помог {verb} налог', {}, [], CALL_SETTINGS).kind != QUESTION


@pytest.mark.parametrize('form', ['NFC', 'NFD'])
@pytest.mark.parametrize('said', ['это какой либо важно', 'какой налог сейчас', 'почему растёт инфляция', 'какое сегодня число', 'зачем ей это нужно', 'чей это договор'])
def test_a_decomposed_letter_is_not_a_misspelling(form, said):
    """The ear's text may come decomposed («й» = «и» + a mark): a word of the question vocabulary in any form is left as it was."""
    import unicodedata
    text = unicodedata.normalize(form, said)
    assert heard_spelling(text) == text
