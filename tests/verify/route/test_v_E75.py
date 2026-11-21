"""V6 E75: «answers in more detail: a definition and an explanation are 2-3 phrases, the first phrase is already a good answer». The tests of test_h7 look at the text of FT.BRAIN. Here the real call asks the
job: the request that the channel makes for the question of the call carries the rule, and the job's two-phrase definition is said whole (its second phrase after the first). The LENGTH and the
correctness the model gives (E48: «BRAIN is not measured») are not here: that needs a measurement on the model, not a test."""
from echo_sync import fast_text as FT
from route_kit import S, LIVE, TICK, answer_with_job, call, texts      # noqa: F401

DEFINITION = 'Инфляция — это устойчивый рост общего уровня цен. Из-за неё деньги со временем покупают меньше.'


def test_the_job_of_a_definition_is_asked_with_the_rule_of_two_or_three_phrases_and_both_phrases_are_said(call):
    rig = call(**LIVE)
    n = answer_with_job(rig, 'Что такое инфляция', DEFINITION, 'u1')
    instructions = rig.fake.run(n).request['instructions']
    # the rig's job request carries the rig's stub policy (test_h3_tempo passes instructions=lambda: 'POLICY'), so the rule is checked on the policy production sends (controlled_host: BRAIN_POLICY) and the request is checked to be built from the policy given to the job channel
    assert instructions.startswith('POLICY')
    assert 'две-три короткие фразы' in FT.BRAIN_POLICY and 'первая фраза сама по себе годится как ответ' in FT.BRAIN_POLICY
    for i in range(6):                  # the product goes on by portions: the next one is cued when the listener has said the last one (the cloud hears the listener repeat each cue)
        if 'покупают меньше' in ' '.join(texts(rig)):
            break
        rig.w.feed(S.turn_created(f'say{i}', 'user', ''))
        rig.pump(0.5)
        rig.w.feed(S.turn_done(f'say{i}', 'user', texts(rig)[-1]))
        rig.pump(TICK * 6)
    said = ' '.join(texts(rig))
    assert 'устойчивый рост' in said and 'покупают меньше' in said, said
