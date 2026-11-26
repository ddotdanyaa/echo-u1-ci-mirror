"""V6 E75: «answers in more detail: a definition and an explanation are 2-3 phrases, the first phrase is already a good answer». The tests of test_h7 look at the text of FT.BRAIN. Here the real call asks the
job: the request the channel makes for the question of the call carries the rule, in every form of the instructions production sends (the long BRAIN_POLICY and, under the setting brain_short, SHORT_POLICY in its
place), and the job's two-phrase definition is said whole (its second phrase after the first). The LENGTH and the correctness the model gives (E48: «BRAIN is not measured») are not here: that needs a measurement on the model, not a test."""
import pytest

from echo_sync import fast_text as FT
from echo_sync import brain_short
from echo_sync.content_policy import CallContext, build_instructions
from route_kit import S, LIVE, TICK, answer_with_job, call, texts      # noqa: F401

DEFINITION = 'Инфляция — это устойчивый рост общего уровня цен. Из-за неё деньги со временем покупают меньше.'
RULE = {False: ('две-три короткие фразы', 'первая фраза сама по себе годится как ответ'),      # the long BRAIN_POLICY (test_h7 holds the same two needles)
        True: tuple(needle for name, needle in brain_short.KEEP if name in ('explain', 'first_alone'))}      # SHORT_POLICY says the same rule shorter; its own table of needles owns the wording


def production_instructions(short):
    """The instructions source of the job channel as controlled_host gives it (build_instructions over the owner's context with BRAIN_POLICY) and, under brain_short, as for_call wraps it."""
    given = lambda *a: build_instructions(CallContext(subject='экономика'), FT.BRAIN_POLICY)      # noqa: E731
    return FT._short_brain(given) if short else given


@pytest.mark.parametrize('short', [False, True], ids=['long_brain', 'short_brain'])
def test_the_job_of_a_definition_is_asked_with_the_rule_of_two_or_three_phrases_and_both_phrases_are_said(call, short):
    rig = call(**LIVE)
    rig.fast.instructions = production_instructions(short)      # the rig stubs the policy as 'POLICY' (test_h3_tempo): the job asks with what production sends
    n = answer_with_job(rig, 'Что такое инфляция', DEFINITION, 'u1')
    instructions = rig.fake.run(n).request['instructions']
    assert len(RULE[short]) == 2 and all(phrase in instructions for phrase in RULE[short]), instructions
    assert 'Предмет занятия: экономика' in instructions and ('Ты суфлёр: человек вслух' in instructions) == short, instructions      # the owner's lines stay and the variant is the one asked for
    for i in range(6):                  # the product goes on by portions: the next one is cued when the listener has said the last one (the cloud hears the listener repeat each cue)
        if 'покупают меньше' in ' '.join(texts(rig)):
            break
        rig.w.feed(S.turn_created(f'say{i}', 'user', ''))
        rig.pump(0.5)
        rig.w.feed(S.turn_done(f'say{i}', 'user', texts(rig)[-1]))
        rig.pump(TICK * 6)
    said = ' '.join(texts(rig))
    assert 'устойчивый рост' in said and 'покупают меньше' in said, said
