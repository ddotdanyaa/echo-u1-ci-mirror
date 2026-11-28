"""U19-S1: TurnLang, spans, translit, rules of ``echo_sync.lang_hint``. Pure code, no model, no clock; the Russian utterances are copies of real call phrases (S01, S03)."""
import pytest

from echo_sync import lang_hint as LH

S01 = 'Что такое абсолютная ссылка в Excel'
S03 = 'Допустим, XYZ Средние века'
ROMAN = 'XIII–XV'


def test_counts_and_word_lang():
    assert LH.word_lang('Excel') == 'en' and LH.word_lang('ссылка') == 'ru'
    assert LH.word_lang('XYZ') is None and LH.word_lang('GDP') is None and LH.word_lang('XIII') is None     # acronyms and romans vote for nobody
    assert LH.word_lang('123') is None
    c = LH.counts(S01)
    assert c['ru'] == 5 and c['en'] == 1
    assert LH.counts('see http://x.org/a or a@b.com now')['en'] == 3                                          # URL and e-mail are stripped before the vote


def test_russian_scenes_stay_ru():
    t = LH.TurnLang()
    for text in (S01, S03, ROMAN, ''):
        assert t.observe(text) == 'ru'


def test_english_question_switches_and_short_noise_keeps_previous():
    t = LH.TurnLang()
    assert t.observe('What is the capital of Canada?') == 'en'
    assert t.observe('ok') == 'en'                      # no evidence: keep
    assert t.observe('GDP') == 'en'
    assert t.observe('Что такое абсолютная ссылка') == 'ru'
    assert t.observe('Excel') == 'ru'


def test_one_foreign_word_never_switches():
    t = LH.TurnLang()
    for text in ('Как будет hello по-русски', 'Что такое Excel и Word', 'Please скажи'):
        assert t.observe(text) == 'ru'


def test_sticky_prior_in_en_needs_clear_russian():
    t = LH.TurnLang(initial='en')
    assert t.observe('Столица') == 'en'
    assert t.observe('Какая столица Канады') == 'ru'


def test_lang_spans_merge_singles():
    spans = LH.lang_spans(S01)
    assert [s[0] for s in spans] == ['ru'] and spans[0][3] == 6
    text = 'Скажи мне пожалуйста what is the capital of Canada'
    spans = LH.lang_spans(text)
    assert [s[0] for s in spans] == ['ru', 'en']
    assert text[spans[1][1]:spans[1][2]] == 'what is the capital of Canada' and spans[1][3] == 6
    assert LH.lang_spans('') == [] and LH.lang_spans('GDP') == []


def test_translit_and_cross_equal():
    assert LH.translit('Финансия').isascii() and LH.translit('Финансия')
    assert LH.cross_equal('финансия', 'financia') is True
    assert LH.cross_equal('прапедлей', 'rapidly') is False
    assert LH.cross_equal('кошка', 'кошка') is True and LH.cross_equal('кошка', 'собака') is False
    assert LH.cross_equal('да', 'da') is False          # too short to be evidence


def test_rules_and_instructions():
    assert set(LH.LANG_RULES) == {'ru', 'en'}
    assert LH.answer_instructions('ru') == ''           # the Russian prompt stays byte-identical
    en = LH.answer_instructions('en')
    assert 'English' in en and en == LH.LANG_RULES['en']['instruction']
    assert LH.answer_instructions('de') == '' and LH.LANG_FALLBACKS['de'] == 1
    assert LH.LANG_RULES['en']['negations'] is LH.EN_NOT and LH.LANG_RULES['en']['voice'] != LH.LANG_RULES['ru']['voice']


def test_ear_unknown_share():
    known = {'что', 'такое', 'ссылка'}
    assert LH.ear_unknown('что такое ссылка', known) == (0, 3, 0.0)
    assert LH.ear_unknown('что наводит финансия', known) == (2, 3, pytest.approx(2 / 3))
    assert LH.ear_unknown('', known) == (0, 0, 0.0)
    assert LH.ear_foreign('что наводит финансия', known) and not LH.ear_foreign('что такое ссылка', known)
    assert not LH.ear_foreign('x', known)               # one word is no evidence


@pytest.mark.parametrize('token', ['B2', 'C2', 'mp3', 'H2O', 'a4', 'X5', 'gpt4', 'ab12cd'])
def test_a_token_with_digits_is_no_english_word(token):
    """Class: a cell reference, a file or a model name (a Latin token with a digit in it) votes for nobody: it is not cut into a Latin «word» of its own."""
    assert LH.word_lang(token) is None
    assert LH.counts(f'Формула {token} умножить')['en'] == 0
    assert all(lang == 'ru' for lang, *_ in LH.lang_spans(f'Формула {token} умножить на C2'))


def test_a_sentence_with_cell_references_never_turns_the_turn_english():
    turn = LH.TurnLang()
    assert turn.observe('Формула B2 умножить на C2 и сложить с mp3') == 'ru'
    assert turn.observe('Open the file mp3 and the table B2 please') == 'en'      # real English words still switch


def test_the_probe_reports_it_as_unknown_not_as_a_language():
    from echo_sync.cm_probes import UNKNOWN, probe
    assert probe('word_lang', 'B2').value == UNKNOWN and probe('word_lang', 'mp3').value == UNKNOWN
    assert probe('word_lang', 'Excel').value == 'en'
