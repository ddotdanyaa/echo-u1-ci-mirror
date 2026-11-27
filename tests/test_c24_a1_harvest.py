"""c24-a1 (test_harvest 1027, red since c22-merge): the checker's «stale». At 87.1 of 10:27 the owner said «наличие и движение денег организации», the final
retired the plan as a new question, the job declined it (no question) and the plan went on: «на счетах в банке.» is the same answer, not an old one. A question
the job did not decline (it failed, it timed out) and the old plan after it stays stale (P16 of c22-break)."""
from tools import harvest as H


def rows(reason):
    return [{'t': 0, 'ev': 'call_open', 'max_auto_repeats': 3},
            {'t': 1000, 'ev': 'user_final', 'text': 'Что такое счёт 51?'},
            {'t': 1100, 'ev': 'decision', 'kind': 'question', 'reason': 'admitted_answer', 'revision': 1, 'index': 0},
            {'t': 1100, 'ev': 'cue', 'text': 'Счёт 51 «Расчётные счета» учитывает деньги'},
            {'t': 5000, 'ev': 'cue', 'text': 'на счетах в банке.'},
            {'t': 8000, 'ev': 'user_final', 'text': 'наличие и движение денег организации'},
            {'t': 8050, 'ev': 'decision', 'kind': 'retire', 'reason': 'new_question', 'revision': 2, 'index': 0},
            {'t': 9400, 'ev': 'decision', 'kind': 'silent', 'reason': reason, 'revision': 2},
            {'t': 9400, 'ev': 'decision', 'kind': 'resume', 'reason': 'plan_goes_on_after_no_answer', 'revision': 3},
            {'t': 9400, 'ev': 'cue', 'text': 'на счетах в банке.'}]


def test_the_plan_that_goes_on_after_a_declined_job_is_no_old_answer():
    assert H.checks(rows('fast_text_declined'))['stale'] == 0


def test_the_old_plan_after_a_question_nobody_answered_is_stale():
    assert H.checks(rows('fast_text_failed'))['stale'] == 1
