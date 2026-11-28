"""U19-S8: the language acceptance replay (tools.replay.lang_replay) on invented rows (no private journal in the repo)."""
from tools.replay import lang_replay as R

KNOWN = {'что', 'такое', 'ссылка', 'в', 'расскажи', 'про', 'вторую', 'порцию'}


def fx(cloud=(), ear=(), cues=()):
    return {'cloud': [[1.0 + i, 'user', 'u%d' % i, t] for i, t in enumerate(cloud)], 'ear': [[2.0 + i, 2.5 + i, 3.0 + i, t] for i, t in enumerate(ear)],
            'cues': [[float(t), text, 'completed'] for t, text in cues]}


def test_a_russian_call_has_no_switch_and_plain_cues():
    got = R.call(fx(['Что такое ссылка в Excel', 'расскажи про вторую порцию'], ['что такое ссылка'], [(5, 'Ссылка в Excel, это адрес ячейки.')]), KNOWN)
    assert got['switches_to_en'] == 0 and got['cues_with_ssml'] == 0 and got['ru_instruction'] == '' and got['ear_unknown_words'] == 0


def test_an_english_question_switches_and_is_counted():
    got = R.call(fx(['What is the main risk here and why does it matter']), KNOWN)
    assert got['switches_to_en'] == 1


def test_an_english_cue_gets_a_voice_span_and_a_latin_ear_word_is_unknown():
    got = R.call(fx(ear=['что такое rapidly'], cues=[(5, 'What is the main risk here?')]), KNOWN)
    assert got['cues_with_ssml'] == 1 and got['ear_unknown_words'] == 1 and got['ear_words'] == 3


def test_acceptance_flags_each_claim():
    ok = R.acceptance([R.call(fx(['Что такое ссылка'], ['что такое ссылка']), KNOWN)])
    assert ok['L1_no_switch'] and ok['L2_ear_unknown'] and ok['L3_ru_pcm_same'] and ok['calls'] == 1
    bad = R.acceptance([R.call(fx(['What is the main risk here and why does it matter'], ['rapidly rapidly']), KNOWN)])
    assert not bad['L1_no_switch'] and not bad['L2_ear_unknown']


def test_the_repeat_rule_verdict_of_the_ear_is_counted_not_judged():
    got = R.call(fx(ear=['ссылка в Excel это адрес ячейки'], cues=[(1, 'Ссылка в Excel, это адрес ячейки.')]), KNOWN)
    assert got['ear_next'] == 1 and 'cross_changed' not in got


def test_real_shaped_russian_calls_stay_russian():
    rows = [R.call(fx(['Что такое ссылка в Excel', 'расскажи про вторую порцию'], ['что такое ссылка'], [(5, 'Ссылка в Excel, это адрес ячейки.'), (9, 'Вторая порция.')])) for _ in range(2)]
    got = R.acceptance(rows)
    assert got['L1_no_switch'] and got['L3_ru_pcm_same'] and got['calls'] == 2, got


def test_a_russian_cue_makes_the_plain_request_and_an_english_one_a_language_request():
    for text in ('Ссылка в Excel, это адрес ячейки.', 'Тридцать рублей.', 'Статья 17 части 2, пункт B2.'):
        assert R.request(text) == R.RU_REQUEST
    assert R.request('What is the main risk here?') != R.RU_REQUEST
    got = R.acceptance([R.call(fx(cues=[(5, 'Тридцать рублей.')]), KNOWN)])
    assert got['cues_request_changed'] == 0 and got['L3_ru_pcm_same'] and got['L3_basis'].startswith('proxy') and got['L2_basis'].startswith('proxy')
