"""BREAK kind_question 3: «а почему?». A short clarification has no subject of its own: the job must get the exchange above it, once and twice. Real ControlledMedia, not run on the laptop.
Class of problem: К3 (what is a question is decided by form, not by what can be answered), К13 (memory of what was said)."""
from break_kit import ACCOUNT, LIVE_RULES, MATERIALS, answered, call, heard, index_of, job_input, plan, user_turn    # noqa: F401 - call is the fixture


def test_b06_a_bare_why_goes_to_the_job_with_the_exchange_it_is_about_and_the_cursor_stands(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    user_turn(rig, 'u1', 'А почему?')
    assert rig.fake.runs[1:], 'a bare «а почему?» was dropped as a scrap'
    assert 'материал' in job_input(rig, 1).lower(), job_input(rig, 1)
    assert index_of(rig) == 0
    answered(rig, 1, 'Потому что материалы — это актив предприятия.')
    rig.pump(1.0)
    assert heard(rig, 'актив предприятия')


def test_b07_a_second_why_carries_the_first_clarification_too(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    user_turn(rig, 'u1', 'А почему?')
    answered(rig, 1, 'Потому что материалы — это актив предприятия.')
    rig.pump(1.0)
    user_turn(rig, 'u2', 'А почему так?')
    assert rig.fake.runs[2:], 'the second «а почему» never reached a job'
    assert 'актив предприятия' in job_input(rig, 2), job_input(rig, 2)
