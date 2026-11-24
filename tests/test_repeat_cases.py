"""G7: the owner repeats the cue. Said word for word, said with the ear's errors, said half and went on, said ahead of the cue: the next portion comes at once, once, with no false step.
A question the cloud did not take, the owner says it again aloud: a new question, and its answer. The real controller, the ear and the wire on the injected clock (``test_h3_tempo``), with the
candidate's flags on. Nothing here is a measurement of a call."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S
from test_h3_tempo import HEAD, PORTION, TICK, call       # noqa: F401 - call is the fixture

from echo_sync.settings import controller_settings, resolve      # ROOT-1: the one builder of a controller's settings


HOST_PASSES = controller_settings(resolve({}))      # what a profile that turned the flags on hands the controller
HOST_SYNCS_ENGINE = 'controller.engine.settings=controller.settings' in (Path(__file__).parents[1] / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')
CANDIDATE = dict(fast_text='on', ear_release='on', instant='on', material_pick='on', spare_helper='on', warm_start='on', open_overlap='on')
NEXT = 'Налоги устанавливают законом.'
ANSWER = HEAD + ' ' + PORTION + ' ' + NEXT


def rig_of(call, **extra):
    rig = call(**{**CANDIDATE, **extra})
    rig.c.settings = controller_settings(rig.settings)     # what controlled_host gives the controller of the profile (ROOT-1: the same builder)
    if HOST_SYNCS_ENGINE:
        rig.c.engine.settings = rig.c.settings
    return rig


def steps(rig):
    return [r for r in rig.said()]


def utter(rig, text, speech=1.2, lag=0.15, turn=None, final=None, final_after=0.6):
    """One utterance through the ear; the cloud's own final of it ``final_after`` s after the ear's text when ``final`` is given."""
    uid = rig.onset()
    if turn:
        rig.pump(min(0.3, speech))
        rig.w.feed(S.turn_created(turn, 'user', text.split()[0]))
        rig.pump(max(0.0, speech - 0.3))
    else:
        rig.pump(speech)
    rig.offset()
    rig.pump(lag)
    rig.worker.heard(uid, text)
    rig.pump(TICK)
    if final is not None:
        rig.pump(final_after)
        rig.w.feed(S.turn_done(turn, 'user', final))
        rig.pump(TICK)


@pytest.mark.parametrize('heard', ['статья семнадцать налогового кодекса', 'Статья 17 Налогового кодекса', 'статья семнадцатая налогового кодекса', 'статья статья семнадцать налогового кодекса',
                                   'ну статья семнадцать налогового кодекса'],
                         ids=['words', 'digits', 'case', 'stammer', 'filler'])
def test_the_repeat_of_the_head_gives_the_next_portion_once(call, heard):
    rig = rig_of(call)
    rig.first_portion()
    rig.pump(0.5)
    utter(rig, heard, turn='u2', final=heard)
    rig.pump(1.0)                  # inside the tempo's wait (2 s): a second portion here is a double, not the replay
    assert rig.said() == [HEAD, PORTION], rig.said()


@pytest.mark.parametrize('heard', ['общие условия установления налогов и сборов', 'общие условия установление налогов и сборов', 'общие условия установления налогов сборов',
                                   'общий условия установления налогов и сборов'],
                         ids=['words', 'case', 'swallowed_and', 'ending'])
def test_the_repeat_of_a_middle_portion_with_the_ears_errors_moves_on(call, heard):
    rig = rig_of(call)
    rig.second_portion()
    rig.pump(0.5)
    utter(rig, heard, speech=2.0, turn='u3', final=heard)
    rig.pump(1.0)                  # inside the tempo's wait (2 s): a second portion here is a double, not the replay
    assert rig.said()[:2] == [HEAD, PORTION] and PORTION not in rig.said()[2:], rig.said()


# -- the matcher: a stammer inside a repeat is the repeat ------------------------------------------------------------------------------
from echo_sync.ru_alignment import match_current, without_repeats      # noqa: E402


@pytest.mark.parametrize('heard', ['статья статья семнадцать налогового кодекса', 'статья семнадцать семнадцать налогового кодекса', 'статья семнадцать налогового налогового кодекса',
                                   'ст статья семнадцать налогового кодекса', 'статья семнадцать нало налогового кодекса'],
                         ids=['word_twice', 'number_twice', 'adjective_twice', 'begun_word', 'begun_adjective'])
def test_a_word_said_twice_or_begun_and_said_again_is_the_repeat(heard):
    assert match_current(heard, HEAD) == 'ack'


@pytest.mark.parametrize('heard,portion', [('статья статья восемнадцать налогового кодекса', HEAD), ('статья семнадцать семнадцать налогового', HEAD),
                                           ('не не облагается налогом', 'Облагается налогом.'), ('общие общие условия налогов и сборов', PORTION),
                                           ('два два процента', 'Двадцать два процента.'), ('статья статья семнадцать', 'Статья 17 статья 18.')],
                         ids=['other_number', 'word_left_out', 'added_ne', 'words_left_out', 'other_value', 'half_of_a_portion'])
def test_the_stammer_takes_nothing_else_away(heard, portion):
    """Another number, a word left out, an added «не», a number that is not the portion's: no repeat with or without the stammer."""
    assert match_current(heard, portion) != 'ack'


# -- a longer answer: half and on, ahead of the cue --------------------------------------------------------------------------------------
ASK = 'Как проходит фотосинтез в листьях растений?'
P1, P2, P3 = 'Свет попадает на хлорофилл в листьях.', 'Вода распадается на кислород и водород.', 'Углекислый газ превращается в глюкозу.'


def photosynthesis(call):
    rig = rig_of(call)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    assert rig.said() == [P1]
    rig.pump(0.5)
    return rig


@pytest.mark.parametrize('heard', ['свет попадает на хлорофилл в листьях', 'свет попадает на хлорофилл в листьях да', 'свет падает на хлорофилл в листьях'],
                         ids=['words', 'tag', 'particle_word'])
def test_the_whole_repeat_moves_on_at_once_and_its_final_moves_nothing(call, heard):
    rig = photosynthesis(call)
    utter(rig, heard, speech=1.8, turn='u2', final=heard + '.')
    rig.pump(1.0)
    # integ-c17: «свет падает» (another real word) was no step (w8-repeat); the owner's rule of 06.11 (4babaaf, ``most_said``): most of the portion said goes on
    assert rig.said() == [P1, P2], rig.said()


@pytest.mark.parametrize('heard', ['свет попадает на хлорофил в листьях', 'свет попадает на хлорофилл в листях'], ids=['garbled_long', 'garbled_last'])
def test_a_word_the_ear_garbled_into_a_non_word_moves_on_always(call, heard):
    """The real ear (14_EAR_N2): «в», «на» are not lost (2 of 232, 0 of 139), a non-word for a long word is. The heal is always on (the key ``ack_garble`` is gone)."""
    assert HOST_SYNCS_ENGINE, 'the engine keeps the settings it was built with: the ear takes the repeat, the engine refuses it'
    rig = rig_of(call)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    rig.pump(0.5)
    utter(rig, heard, speech=1.8, turn='u2', final=heard + '.')
    rig.pump(1.0)
    assert rig.said() == [P1, P2], rig.said()


@pytest.mark.parametrize('first,second', [('свет попадает', 'на хлорофилл в листьях'), ('свет попадает на', 'хлорофилл в листьях'), ('свет', 'попадает на хлорофилл в листьях')])
def test_half_said_a_pause_and_the_rest_said_gives_the_next_portion_and_no_false_step(call, first, second):
    """The owner said half, stopped short of the tempo's wait, went on: the rest of the portion is not cued over them, the next portion comes once."""
    rig = photosynthesis(call)
    utter(rig, first, speech=0.6)
    rig.pump(0.3)
    utter(rig, second, speech=1.0, turn='u2', final=f'{first} {second}.')
    rig.pump(1.0)
    assert rig.said() == [P1, P2], rig.said()


@pytest.mark.parametrize('heard', ['свет попадает на хлорофилл в листьях вода распадается', 'свет попадает на хлорофилл в листьях вода'],
                         ids=['two_words_ahead', 'one_word_ahead'])
def test_said_ahead_of_the_cue_moves_on_once_and_does_not_go_back(call, heard):
    rig = photosynthesis(call)
    utter(rig, heard, speech=2.2, turn='u2', final=heard + '.')
    rig.pump(1.0)
    assert rig.said()[0] == P1 and P1 not in rig.said()[1:], rig.said()
    assert len(rig.said()) == 2 and rig.said()[1] in (P2, 'распадается на кислород и водород.', 'на кислород и водород.'), rig.said()
    assert rig.c.state()['chunk_index'] == 1


def test_the_whole_next_portion_said_ahead_skips_it(call):
    rig = photosynthesis(call)
    heard = 'свет попадает на хлорофилл в листьях вода распадается на кислород и водород'
    utter(rig, heard, speech=3.5, turn='u2', final=heard + '.')
    rig.pump(1.0)
    assert rig.said() == [P1, P3], rig.said()


@pytest.mark.parametrize('ahead', ['вода распадается на кислород', 'вода не распадается на кислород и водород', 'вода распадается на азот и водород'],
                         ids=['not_whole', 'added_ne', 'other_word'])
def test_what_is_not_the_whole_next_portion_word_for_word_skips_nothing(call, ahead):
    rig = photosynthesis(call)
    heard = 'свет попадает на хлорофилл в листьях ' + ahead
    utter(rig, heard, speech=3.5, turn='u2', final=heard + '.')
    rig.pump(1.0)
    assert P3 not in rig.said() and rig.c.state()['chunk_index'] <= 1, rig.said()


# -- the friend's question was not taken; the owner says it again aloud --------------------------------------------------------------
VAT = 'Сколько процентов НДС в России?'


def answered(rig, n, answer):
    rig.job_says(n, answer)
    rig.job_ends(n)


@pytest.mark.parametrize('lost', ['nothing', 'garbled', 'piece'])
def test_the_owner_says_the_lost_question_again_and_it_is_answered(call, lost):
    rig = rig_of(call)
    if lost != 'nothing':                    # the friend far from the microphone: the cloud has a turn of noise or a piece of it, no question
        rig.w.feed(S.turn_created('u1', 'user', ''))
        rig.w.feed(S.turn_done('u1', 'user', {'garbled': 'сколько от в ро', 'piece': 'в России'}[lost]))
        rig.pump(2.0)
    assert rig.said() == []
    rig.w.feed(S.turn_created('u2', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('u2', 'user', VAT))
    rig.pump(TICK)
    last = len(rig.fake.runs) - 1
    assert last >= 0 and 'НДС' in rig.fake.run(last).question, 'the job is asked the question the owner said'
    answered(rig, last, 'НДС в России 20 процентов.')
    assert rig.said() == ['НДС в России 20 процентов.'], rig.said()


def test_the_lost_question_said_again_while_an_answer_waits_is_a_new_question(call):
    rig = photosynthesis(call)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'сколько от в ро'))
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u3', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('u3', 'user', VAT))
    rig.pump(0.3)
    assert P2 not in rig.said(), 'a question is no repeat of the portion'


def test_half_said_the_rest_cued_and_the_owner_said_it_with_the_cue_gives_the_next_portion_once(call):
    rig = photosynthesis(call)
    utter(rig, 'свет попадает', speech=0.6)
    cue = rig.next_cue(2.5)
    assert cue is not None and cue.text == 'на хлорофилл в листьях.', 'precondition: the rest was cued'
    rig.pump(0.2)
    utter(rig, 'на хлорофилл в листьях', speech=1.0, turn='u2', final='свет попадает на хлорофилл в листьях.')
    rig.pump(1.0)
    assert rig.said()[-1] == P2 and rig.said().count(P2) == 1 and rig.said().count('на хлорофилл в листьях.') == 1, rig.said()


@pytest.mark.parametrize('lead', [0.1, 0.4, 0.8])
def test_the_owner_who_knows_the_portion_says_it_before_its_cue_has_sounded_out(call, lead):
    """Ahead of the cue: the portion was cued and the owner says it at once, over its sound. It is the repeat, once, and the next one comes; no replay of it."""
    rig = photosynthesis(call)
    utter(rig, 'свет попадает на хлорофилл в листьях', speech=1.8, turn='u2', final='Свет попадает на хлорофилл в листьях.')
    assert rig.said() == [P1, P2]
    rig.pump(lead)
    utter(rig, 'вода распадается на кислород и водород', speech=1.8, turn='u3', final='Вода распадается на кислород и водород.')
    rig.pump(1.0)
    assert rig.said() == [P1, P2, P3], rig.said()


# -- an abbreviation is said as the voice says it: by its letters («РФ» is «эр эф»), or in full -----------------------------------------
@pytest.mark.parametrize('heard,portion', [('налоговый кодекс эр эф', 'Налоговый кодекс РФ.'), ('эн дэ эс в россии двадцать процентов', 'НДС в России 20 процентов.'),
                                           ('эн дэ эф эл тринадцать процентов', 'НДФЛ 13 процентов.'), ('статья семнадцать эн ка эр эф', 'Статья 17 НК РФ.'),
                                           ('эф эн эс проверяет', 'ФНС проверяет.'), ('налоговый кодекс российской федерации', 'Налоговый кодекс РФ.'),
                                           ('статья семнадцать налогового кодекса российской федерации', 'Статья 17 НК РФ.'), ('статья семнадцать нк рф', 'Статья 17 НК РФ.')],
                         ids=['rf', 'nds', 'ndfl', 'nk_rf', 'fns', 'rf_in_full', 'nk_rf_in_full', 'as_written'])
def test_an_abbreviation_said_by_its_letters_or_in_full_is_the_repeat(heard, portion):
    assert match_current(heard, portion) == 'ack'


@pytest.mark.parametrize('heard,portion', [('эн дэ эс в россии десять процентов', 'НДС в России 20 процентов.'), ('статья семнадцать гэ ка эр эф', 'Статья 17 НК РФ.'),
                                           ('статья семнадцать трудового кодекса российской федерации', 'Статья 17 НК РФ.'), ('эн дэ эс в россии двадцать процентов', 'НДФЛ в России 20 процентов.'),
                                           ('у ка', 'УК РФ.'), ('эр эф', 'Это РФ.')],
                         ids=['other_number', 'other_code', 'other_code_in_full', 'other_tax', 'half_of_two', 'word_left_out'])
def test_letters_of_another_abbreviation_are_no_repeat(heard, portion):
    assert match_current(heard, portion) != 'ack'


@pytest.mark.parametrize('heard,portion', [('пункт два статьи пятнадцать', 'П. 2 ст. 15.'), ('часть первая статьи двести двадцать семь', 'Ч. 1 ст. 227.'), ('глава двадцать один', 'Гл. 21.'),
                                           ('статья пятнадцать пункт два', 'Ст. 15 п. 2.')], ids=['p_st', 'ch_st', 'gl', 'st_p'])
def test_a_short_form_before_a_number_said_in_full_is_the_repeat(heard, portion):
    assert match_current(heard, portion) == 'ack'


@pytest.mark.parametrize('heard,portion', [('пункт три статьи пятнадцать', 'П. 2 ст. 15.'), ('статья два статьи пятнадцать', 'П. 2 ст. 15.'), ('пункт два статьи пятнадцать', 'П. 2 гл. 15.')],
                         ids=['other_number', 'other_word', 'other_unit'])
def test_a_short_form_said_as_another_word_is_no_repeat(heard, portion):
    assert match_current(heard, portion) != 'ack'


# -- Р031 seed 1 (the board of 6 Nov): the portion and the start of the next one in one breath; the cloud took the repeat, the ear came
#    later with «… первое налог начисляют»: «первое» was read as another number and the step was taken back, the portion said again ---------
R1, R2, R3 = 'Льготные ставки 10 и 0 процентов.', 'Первое: налог начисляют по итогам периода.', 'Второе: базу считают нарастающим итогом.'


def late_ear(rig, ear, final, speech=3.5, ear_lag=0.7, partial='Льготные ставки 10 и 0 процентов'):
    """The cloud's stable partial takes the repeat while the owner still speaks (the stand: 16.16, the speech ended at 17.53), the ear's text comes after the end."""
    uid = rig.onset()
    rig.pump(0.3)
    rig.w.feed(S.turn_created('u2', 'user', final.split()[0]))
    rig.pump(1.0)
    for n, word in enumerate(partial.split()):
        rig.w.feed(S.turn_delta('u2', word if not n else ' ' + word, n))
        rig.pump(0.15)
    rig.pump(max(0.0, speech - 1.3 - 0.15 * len(partial.split())))
    rig.offset()
    rig.w.feed(S.turn_done('u2', 'user', final))
    rig.pump(ear_lag)
    rig.worker.heard(uid, ear)
    rig.pump(TICK)


@pytest.mark.parametrize('ear,final', [('льготные ставки десять и ноль процентов первое налог начисляют', 'Льготные ставки 10 и 0 процентов. Первое: налог начисляют'),
                                       ('льготные ставки десять и ноль процентов первое', 'Льготные ставки 10 и 0 процентов. Первое.')],
                         ids=['start_of_next', 'first_word_of_next'])
def test_the_start_of_the_next_portion_said_with_the_repeat_is_no_other_number(call, ear, final):
    rig = rig_of(call)
    rig.asks('u1', 'Какие льготные ставки НДС?', 0, f'{R1} {R2} {R3}')
    rig.pump(0.5)
    late_ear(rig, ear, final)
    rig.pump(2.5)                  # past the tempo's wait: a step taken back would have said R1 again
    assert rig.c.state()['chunk_index'] == 1 and rig.said().count(R1) == 1, (rig.said(), rig.c.state()['chunk_index'])


@pytest.mark.parametrize('ear', ['льготные ставки двадцать и ноль процентов первое налог начисляют', 'льготные ставки двадцать и ноль процентов'],
                         ids=['other_number_and_next', 'other_number_alone'])
def test_another_number_in_the_repeat_still_takes_the_step_back(call, ear):
    rig = rig_of(call)
    rig.asks('u1', 'Какие льготные ставки НДС?', 0, f'{R1} {R2} {R3}')
    rig.pump(0.5)
    late_ear(rig, ear, 'Льготные ставки 10 и 0 процентов. Первое: налог начисляют')
    rig.pump(1.0)
    assert rig.c.state()['chunk_index'] == 0, (rig.said(), rig.c.state()['chunk_index'])


# -- Р022 seeds 6, 18: the number said twice in the stammer («168… 168») is one number, for the matcher and for the ear's veto -------------
WEEK = 'В неделе 168 часов.'


@pytest.mark.parametrize('heard', ['в неделе сто шестьдесят восемь сто шестьдесят восемь часов', 'в неделе 168 168 часов', 'в неделе э-э сто шестьдесят восемь сто шестьдесят восемь часов',
                                   'в неделе сто шестьдесят сто шестьдесят восемь часов', 'в неделе в неделе сто шестьдесят восемь часов'],
                         ids=['words_twice', 'digits_twice', 'with_hesitation', 'begun_number', 'two_words_twice'])
def test_a_number_said_twice_is_the_repeat(heard):
    assert match_current(heard, WEEK) == 'ack'


@pytest.mark.parametrize('heard', ['в неделе сто шестьдесят семь сто шестьдесят восемь часов', 'в неделе 168 167 часов', 'в неделе сто шестьдесят восемь сто шестьдесят семь часов'],
                         ids=['other_then_right', 'right_then_other', 'right_then_other_words'])
def test_two_different_numbers_are_no_repeat(heard):
    assert match_current(heard, WEEK) != 'ack'


@pytest.mark.parametrize('ear,veto', [('в неделе э-э 168 168 часов', False), ('в неделе э-э сто шестьдесят восемь сто шестьдесят восемь часов', False),
                                      ('в неделе э-э сто шестьдесят семь сто шестьдесят семь часов', True), ('в неделе 168 167 часов', True)],
                         ids=['digits_twice', 'words_twice', 'other_twice', 'other_after'])
def test_the_ears_veto_reads_a_number_said_twice_as_one(call, ear, veto):
    rig = rig_of(call)
    state = {'chunks': [WEEK, 'Это семь дней по 24 часа.'], 'chunk_index': 0, 'revision': 1}
    heard = rig.c._before_the_next(without_repeats(ear, WEEK) or ear, state)
    assert rig.c._ear_other_number(heard, WEEK) is veto


# -- the stand's judge (tools/rehearsal/score.py): a portion said ahead of its cue, in the utterance that took the one before, is no false step ---------
def test_the_judge_counts_a_portion_said_ahead_as_said():
    from test_w9_rehearsal import _out, _said
    from tools.rehearsal import score
    chunks = ('Налог на прибыль платят российские организации и иностранные', 'с постоянным представительством.', 'Первое: налог начисляют по итогам периода.')
    cue = lambda t, index: (t, chunks[index], 1, index, chunks, False, False, 'u1')
    states = [(14.8, 1, 0, False, False, False, 1), (22.2, 1, 1, False, False, False, 1), (25.0, 1, 2, False, False, False, 1)]
    ahead = _said(2, 'stutter', chunks[0] + ' ' + chunks[1], 18.8, 23.4)
    m, _ = score.board(_out([ahead], [cue(14.8, 0), cue(23.6, 1), cue(25.0, 2)], states))
    assert m['false_step'] == 0
    alone = _said(2, 'stutter', chunks[0], 18.8, 21.0)
    m, _ = score.board(_out([alone], [cue(14.8, 0), cue(23.6, 1), cue(25.0, 2)], states))
    assert m['false_step'] == 1, 'the step past a portion nobody said is still false'
