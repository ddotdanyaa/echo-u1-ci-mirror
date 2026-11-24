"""V2 H31-06: scene ``n2_d06``: the history keeps the TAIL of the question, and the link of «приведите пример» with the question it is about is lost. Success of the backlog: scene d06 is green with no row in the table of known mismatches.

The scene's step 2 has the question in three parts with pauses (1.6 s and 1.3 s); here its words go in as the ear's three pieces and the cloud's whole final (the order of ``test_w3_replays.E36``), through the real ControlledMedia (rig ``call``).
The corpus file of the scene (``cloud_context``) is not in this tree: the words are copied from it. Not run on the laptop.
"""
import pytest

import helpers_s6_state as S
from question_kit import LIVE_RULES, TICK, answered, call, entry_of, heard, job_input, job_text, piece, plan, user_turn      # noqa: F401 - call is the fixture

PARTS = ('слушай смотри комната у нас четыре на пять метров', 'потолок два с половиной метра', 'ну и посчитай мне площадь стен только без окон и дверей просто')
WHOLE = 'Слушай, смотри, комната у нас четыре на пять метров. Потолок два с половиной метра. Ну и посчитай мне площадь стен, только без окон и дверей, просто'
ANSWER = '45 квадратных метров. Периметр четыре плюс пять, умножить на два, это восемнадцать метров. Умножить на два с половиной.'


def asked_in_parts(rig):
    rig.w.feed(S.turn_created('u1', 'user', ''))
    for text in PARTS:
        piece(rig, text, speech=2.0, gap=1.4)
    rig.pump(0.8)
    rig.w.feed(S.turn_done('u1', 'user', WHOLE))
    rig.pump(TICK * 3)


def test_the_question_in_three_parts_is_one_question_of_the_job_and_one_entry_of_the_history(call):
    rig = call(**LIVE_RULES)
    asked_in_parts(rig)
    text = job_text(rig, 0)
    assert 'четыре на пять' in text and 'площадь стен' in text, f'the job got a tail: {text!r}'
    answered(rig, 0, ANSWER)
    rig.pump(2.0)
    entry = entry_of(rig, 'площадь стен')
    assert entry is not None, [e.get('question') for e in rig.c.state().get('history', [])]
    assert 'четыре на пять' in entry['question'] and 'потолок' in entry['question'].lower(), f'the history holds the tail: {entry["question"]!r}'


@pytest.mark.parametrize('example', ['Приведите пример', 'А можно пример', 'Ну, приведите пример, чтобы я представил'])
def test_the_example_asked_after_the_answer_is_linked_to_the_original_question(call, example):
    rig = call(**LIVE_RULES)
    asked_in_parts(rig)
    answered(rig, 0, ANSWER)
    rig.pump(1.0)
    user_turn(rig, 'u2', example)
    assert rig.fake.runs[1:], 'the job heard the request for an example'
    whole = job_input(rig, 1).lower()
    assert 'площадь стен' in whole or 'четыре на пять' in whole, f'the link to the question is lost: {whole!r}'


def test_the_example_of_a_short_definition_is_linked_to_its_term(call):
    """c06 step 10 in spirit: «что такое темп» answered, «приведите пример» after it: the job sees the term."""
    rig = call(**LIVE_RULES)
    plan(rig, asked='Что такое темп', answer='Темп — скорость исполнения музыки. Он бывает быстрым и медленным.')
    rig.pump(1.0)
    user_turn(rig, 'u1', 'Приведите пример, чтобы я представил')
    assert rig.fake.runs[1:]
    assert 'темп' in job_input(rig, 1).lower()
