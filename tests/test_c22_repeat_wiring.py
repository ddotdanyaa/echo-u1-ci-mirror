"""c22-repeat: the owner's rule of repeats (``repeat_rule``), dictation (``dictation``, also said: «диктуй медленно») and the readers of a stumble (``ru_alignment.resume_word``, ``stumble_place``: no switch) in a call:
the real controller, the ear and the wire on the injected clock (``test_h3_tempo``), with the candidate's flags on, the profile given to the controller as controlled_host gives it. Nothing here
is a measurement of a call."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync.repeat_rule import DICTATION_START_SECONDS, DictationPace      # noqa: E402
from echo_sync.settings import resolve      # noqa: E402
from test_h3_tempo import GRID, TICK, call       # noqa: E402,F401 - call is the fixture
from test_repeat_cases import ASK, HOST_PASSES, P1, P2, P3, rig_of, utter      # noqa: E402

RULE = {}


def walk(call, **flags):
    rig = rig_of(call, **flags)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    assert rig.said() == [P1]
    rig.pump(0.5)
    return rig


def after(rig, heard, wait=1.2):
    utter(rig, heard, speech=max(0.4, 0.35 * len(heard.split())), turn=f'u{len(rig.said()) + 10}', final=heard + '.')
    rig.pump(wait)
    return rig.said()[1:]


def test_the_stumble_readers_and_the_rule_have_no_switch():
    d = resolve({})
    assert not {'stumble_place', 'resume_word', 'dictation'} & set(d), 'the stumble readers have no switch; dictation is said, no profile key'
    assert not {'stumble_place', 'resume_word', 'dictation'} & set(HOST_PASSES)


# -- the rule -----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('heard', ['листьях', 'в листьях', 'хлорофилл в листьях', 'свет попадает на хлорофилл', 'свет попадает на хлорофилл в листьях'],
                         ids=['last_word', 'last_two', 'last_three', 'most', 'whole'])
def test_the_last_word_or_most_of_the_portion_gives_the_next_one_at_once_and_once(call, heard):
    rig = walk(call, **RULE)
    assert after(rig, heard) == [P2]


@pytest.mark.parametrize('heard,rest', [('свет', 'попадает на хлорофилл в листьях.'), ('свет попадает', 'на хлорофилл в листьях.'), ('свет попадает э-э', 'на хлорофилл в листьях.')],
                         ids=['one_word', 'half', 'filler'])
def test_a_stumble_goes_on_from_the_word_it_stopped_at(call, heard, rest):
    rig = walk(call, **RULE)
    assert after(rig, heard, wait=1.8) == [rest]
    assert after(rig, rest.rstrip('.').lower()) == [rest, P2], 'the rest said: the next portion'


def test_silence_says_the_portion_again_from_its_start_and_is_bounded(call):
    rig = walk(call, **RULE)
    rig.pump(rig.c.repeat_seconds + 0.5)
    assert rig.said() == [P1, P1]
    rig.pump(60)
    assert rig.said().count(P1) == 1 + rig.c.max_auto_repeats, 'silence is no loop'


def test_off_the_last_word_alone_is_the_portion_again_as_before(call):
    rig = walk(call)
    assert after(rig, 'листьях') == [P1]


def test_the_cloud_final_of_a_try_the_ear_went_on_from_moves_nothing_more(call):
    rig = walk(call, **RULE)
    after(rig, 'в листьях', wait=0.2)
    rig.pump(3.0)
    assert rig.said()[1:2] == [P2] and P3 not in rig.said(), rig.said()


# -- dictation ----------------------------------------------------------------------------------------------------------------------------
def test_dictation_waits_for_the_hand_and_never_cuts_in(call):
    rig = walk(call, dictation='on', **RULE)
    rig.pump(6.0)                                              # writing: a silence longer than the silence timer of speech
    assert rig.said() == [P1], 'no cue while the owner writes'
    assert after(rig, 'в листьях') == [P2]
    rig.pump(DictationPace().wait(P2) + 1.0)
    assert rig.said()[-1] == P2 and rig.said().count(P2) == 2, 'nothing said for the whole wait: the portion again from its start'


def test_a_stop_inside_the_portion_while_dictating_is_helped_later_from_its_word(call):
    rig = walk(call, dictation='on', **RULE)
    utter(rig, 'свет попадает', speech=0.8, turn='u5', final='свет попадает.')
    rig.pump(2.0)
    assert rig.said() == [P1], 'the pen, not a stumble: not yet'
    rig.pump(DICTATION_START_SECONDS)
    assert rig.said() == [P1, 'на хлорофилл в листьях.']


@pytest.mark.parametrize('said', ['Диктуй медленно', 'режим диктовки'])
def test_dictation_is_turned_on_by_voice_and_off_again(call, said):
    rig = walk(call, **RULE)
    utter(rig, said, speech=0.9, turn='u7', final=said + '.')
    rig.pump(6.0)
    assert rig.said() == [P1], f'«{said}» turns dictation on: nothing said, no cue into the writing'
    assert rig.c.dictation
    utter(rig, 'хватит диктовать', speech=0.9, turn='u8', final='Хватит диктовать.')
    assert not rig.c.dictation


def test_dictation_off_by_default_the_silence_timer_of_speech(call):
    rig = walk(call, **RULE)
    rig.pump(rig.c.repeat_seconds + 0.5)
    assert rig.said() == [P1, P1]


# -- the readers of a stumble --------------------------------------------------------------------------------------------------------------
def test_the_stumble_reader_has_no_switch_a_jumped_word_is_always_read_as_a_place(call):
    on = walk(call)
    got_on = after(on, 'свет хлорофилл', wait=2.5)      # a word jumped over: stumble_place reads a place in it, from the call's own settings, no key
    assert got_on, got_on


def test_silence_after_the_help_of_a_stumble_helps_from_the_same_word_again_and_is_bounded(call):
    """The help of a stumble answers speech: it is no automatic repeat. Silence after it is helped from the same word (the owner: «тишина и запинка — помощь с того же слова»), bounded by
    ``max_auto_repeats``: before, the help took the one repeat there is, and a silent owner heard nothing more."""
    rig = walk(call, **RULE)
    rest = 'на хлорофилл в листьях.'
    after(rig, 'свет попадает', wait=1.8)
    assert rig.said() == [P1, rest]
    rig.pump(rig.c.repeat_seconds + 1.0)
    assert rig.said() == [P1, rest, rest]
    rig.pump(60)
    assert rig.said() == [P1, rest, rest], 'bounded: no loop'


def test_off_the_help_of_a_stumble_still_counts_as_the_repeat(call):
    rig = walk(call)
    after(rig, 'свет попадает', wait=2.5)
    rig.pump(30)
    assert rig.said() == [P1, 'на хлорофилл в листьях.']
