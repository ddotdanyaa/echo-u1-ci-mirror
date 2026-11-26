"""W5 stumble: ``echo_sync.pace``, the pure decision «wait N ms» / «prompt from word K» on the ear's words with their times. No clock, no I/O.
What is pinned: the rules of WAVE5 w5-stumble one by one; the 300-row table and the tempo simulation are in ``test_w5_pace_table.py``."""
import pytest

from echo_sync.pace import CAP_SECONDS, Pace, portion_tokens
from echo_sync.timer_policy import TEMPO_REPEAT_SECONDS

PORTION = 'Общие условия установления налогов, и сборов в 1999 году не менялись.'


def said(pace, words, t0=0.0, gap=0.15, dur=0.35, gaps=None):
    """Words one after another from ``t0``; ``gaps`` overrides the gap before word i. Returns the end of the last."""
    t = t0
    for i, w in enumerate(words):
        if i:
            t += (gaps or {}).get(i, gap)
        pace.word(w, t, t + dur)
        t += dur
    return t


def first_prompt(pace, after, limit=3.0, step=0.01):
    t = after
    while t < after + limit:
        d = pace.decide(t)
        if d.kind != 'wait':
            return d, t
        t += step
    return None, t


def test_tokens_keep_numbers_whole_and_see_the_commas():
    toks = portion_tokens('Это 300 000 рублей, а не 30.')
    assert [t.norm for t in toks] == ['это', '300000', 'рублей', 'а', 'не', '30']
    assert [t.number for t in toks] == [False, True, False, False, False, True]
    assert toks[2].boundary and not toks[1].boundary


def test_the_cap_is_never_later_than_the_wait_of_today():
    assert CAP_SECONDS == TEMPO_REPEAT_SECONDS == 2.0


def test_no_cue_no_decision():
    assert Pace().decide(1.0).kind == 'idle'


def test_the_whole_portion_said_is_done():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, 'общие условия установления налогов и сборов в тысяча девятьсот девяносто девятом году не менялись'.split(), t0=0.5)
    assert p.decide(end + 0.1).kind == 'done'


def test_a_stop_inside_a_group_is_helped_within_the_target_from_the_same_word():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия'], t0=0.5)
    d, t = first_prompt(p, end)
    assert d.kind == 'prompt' and d.index == 2 and p.text(d.index).startswith('установления')
    assert 0.55 <= t - end <= 1.05, 'help 0.7-1.2 s after the stumble, with ~0.13 s from decision to sound'


def test_the_wait_is_told_in_ms():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия'], t0=0.5)
    d = p.decide(end + 0.1)
    assert d.kind == 'wait' and isinstance(d.wait_ms, int) and 300 <= d.wait_ms <= 1000


def test_a_breath_at_the_comma_waits_longer_than_inside_a_group():
    a = Pace(); a.cue(PORTION, 0.0); ea = said(a, ['общие', 'условия'], t0=0.5)
    b = Pace(); b.cue(PORTION, 0.0); eb = said(b, ['общие', 'условия', 'установления', 'налогов'], t0=0.5)
    _, ta = first_prompt(a, ea); _, tb = first_prompt(b, eb)
    assert tb - eb > ta - ea + 0.2


def test_a_breath_pause_of_this_person_gives_no_false_prompt():
    """Slow speaker: on earlier portions their breath at a comma ran to 1.5 s. The same breath now is no stumble."""
    p = Pace()
    for _ in range(3):
        p.cue(PORTION, 0.0)
        said(p, 'общие условия установления налогов и сборов в тысяча девятьсот девяносто девятом году не менялись'.split(), t0=0.6, gap=0.3, dur=0.5, gaps={4: 1.5})
    p.cue(PORTION, 0.0)
    end = said(p, 'общие условия установления налогов'.split(), t0=0.6, gap=0.3, dur=0.5)
    for t in (end + 0.5, end + 1.0, end + 1.49):
        assert p.decide(t).kind == 'wait'


def test_a_fast_speaker_is_helped_sooner_than_a_slow_one():
    fast, slow = Pace(), Pace()
    for pace, gap, dur in ((fast, 0.06, 0.22), (slow, 0.35, 0.5)):
        for _ in range(3):
            pace.cue(PORTION, 0.0)
            said(pace, 'общие условия установления налогов и сборов в тысяча девятьсот девяносто девятом году не менялись'.split(), t0=0.4, gap=gap, dur=dur)
    fast.cue(PORTION, 0.0); slow.cue(PORTION, 0.0)
    ef = said(fast, ['общие', 'условия'], t0=0.4, gap=0.06, dur=0.22); es = said(slow, ['общие', 'условия'], t0=0.4, gap=0.35, dur=0.5)
    _, tf = first_prompt(fast, ef); _, ts = first_prompt(slow, es)
    assert tf - ef < ts - es and tf - ef <= 0.65 and ts - es <= 1.05


@pytest.mark.parametrize('filler', ['э', 'эээ', 'мм', 'ну', 'вот', 'как его', 'это самое', 'забыл'])
def test_a_filler_is_help_at_once(filler):
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия'] + filler.split(), t0=0.5)
    d, t = first_prompt(p, end)
    assert d.kind == 'prompt' and d.index == 2 and t - end <= 0.6 and d.reason in ('filler', 'blank')


def test_a_filler_the_person_talks_through_is_no_prompt():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия', 'э'], t0=0.5)
    p.word('установления', end + 0.2, end + 0.6)
    assert p.decide(end + 0.65).kind == 'wait'


def test_an_introductory_word_at_the_start_is_no_filler():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['ну'], t0=0.5)
    assert p.decide(end + 0.6).kind == 'wait'


def test_a_stretched_word_is_help_at_once():
    p = Pace(); p.cue(PORTION, 0.0)
    said(p, ['общие'], t0=0.5)
    p.word('условия', 0.95, 2.1)            # 1.15 s for four syllables
    d, t = first_prompt(p, 2.1)
    assert d.kind == 'prompt' and d.index == 2 and t - 2.1 <= 0.6 and d.reason == 'stretch'


def test_back_to_the_beginning_is_help_at_once_from_where_they_are():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия', 'общие'], t0=0.5)
    d, t = first_prompt(p, end)
    assert d.kind == 'prompt' and d.index == 1 and t - end <= 0.6 and d.reason == 'restart'


def test_a_word_said_twice_is_help_at_once():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия', 'условия'], t0=0.5)
    d, t = first_prompt(p, end)
    assert d.kind == 'prompt' and d.index == 2 and t - end <= 0.6


def test_a_broken_word_is_help_at_once_from_that_word():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия', 'устан'], t0=0.5)
    d, t = first_prompt(p, end)
    assert d.kind == 'prompt' and d.index == 2 and t - end <= 0.6 and d.reason == 'cut'


def test_a_number_is_never_cut_the_help_starts_at_its_preposition():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, 'общие условия установления налогов и сборов в тысяча девятьсот'.split(), t0=0.5)
    d, _ = first_prompt(p, end)
    assert d.kind == 'prompt' and p.text(d.index).startswith('в 1999 году')


def test_the_negation_is_never_lost():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, 'общие условия установления налогов и сборов в тысяча девятьсот девяносто девятом году не'.split(), t0=0.5)
    d, _ = first_prompt(p, end)
    assert d.kind == 'prompt' and p.text(d.index) == 'не менялись.'
    p2 = Pace(); p2.cue(PORTION, 0.0)
    end = said(p2, 'общие условия установления налогов и сборов в тысяча девятьсот девяносто девятом году'.split(), t0=0.5)
    d, _ = first_prompt(p2, end)
    assert p2.text(d.index) == 'не менялись.'


def test_a_misheard_word_the_person_goes_on_from_is_no_stumble():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'уловия', 'установления'], t0=0.5)
    d = p.decide(end + 0.3)
    assert d.kind == 'wait'


def test_other_speech_is_not_its_business():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['а', 'сколько', 'стоит', 'билет'], t0=0.5)
    assert p.decide(end + 2.5).kind == 'hold'


def test_while_the_ear_hears_speech_nothing_is_cut():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия'], t0=0.5)
    p.voice(end + 0.4, True)
    assert p.decide(end + 1.9).kind == 'wait'


def test_speech_whose_text_has_not_come_is_waited_for_then_bounded():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие'], t0=0.5)
    p.voice(end + 0.2, True); p.voice(end + 0.9, False)
    assert p.decide(end + 1.6).kind == 'wait', 'the text of that speech may be the next words'
    d, t = first_prompt(p, end + 1.6)
    assert d.kind == 'prompt' and t - (end + 0.9) <= CAP_SECONDS + 0.01


def test_no_start_after_the_microphone_opens():
    p = Pace(); p.cue(PORTION, 1.0)
    assert p.decide(1.5).kind == 'wait'
    d, t = first_prompt(p, 1.0)
    assert d.kind == 'prompt' and d.index == 0 and 0.9 <= t - 1.0 <= CAP_SECONDS


def test_never_later_than_the_cap():
    p = Pace()
    for _ in range(3):        # a person whose every pause is long
        p.cue(PORTION, 0.0)
        said(p, 'общие условия установления налогов и сборов в тысяча девятьсот девяносто девятом году не менялись'.split(), t0=0.6, gap=1.6, dur=0.6)
    p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия'], t0=0.6, gap=1.6, dur=0.6)
    _, t = first_prompt(p, end)
    assert t - end <= CAP_SECONDS + 0.01


def test_after_a_prompt_the_tail_is_the_portion():
    p = Pace(); p.cue(PORTION, 0.0)
    end = said(p, ['общие', 'условия'], t0=0.5)
    d, t = first_prompt(p, end)
    p.prompted(d.index, t + 2.0)
    end = said(p, 'установления налогов и сборов в тысяча девятьсот девяносто девятом году не менялись'.split(), t0=t + 2.4)
    assert p.decide(end + 0.1).kind == 'done'


def test_an_utterance_with_no_word_times_is_spread_and_its_inner_gaps_are_not_learnt():
    p = Pace(); p.cue(PORTION, 0.0)
    p.utterance('общие условия', 0.5, 1.3)
    assert [round(w.start, 2) for w in p.words] == [0.5, 0.85] and p.words[1].joined and not p.words[0].timed
    assert p.inner == [] and p.syllable == []
    d, t = first_prompt(p, 1.3)
    assert d.kind == 'prompt' and d.index == 2 and 0.55 <= t - 1.3 <= 1.05


def test_a_one_word_utterance_keeps_its_length_a_stretch_is_seen():
    p = Pace(); p.cue(PORTION, 0.0)
    p.utterance('общие', 0.5, 0.9)
    p.utterance('условия', 1.2, 2.4)
    d, t = first_prompt(p, 2.4)
    assert d.reason == 'stretch' and d.index == 2 and t - 2.4 <= 0.6
