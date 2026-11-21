"""V6 E75: «answers in more detail: a definition and an explanation are 2-3 phrases, the first phrase is already a good answer». The tests of test_h7 look at the text of FT.BRAIN. Here the real call asks the
job: the request that the channel makes for the question of the call carries the rule, and the job's two-phrase definition is said whole (its second phrase after the first). The LENGTH and the
correctness the model gives (E48: «BRAIN is not measured») are not here: that needs a measurement on the model, not a test."""
from route_kit import LIVE, TICK, answer_with_job, call, texts      # noqa: F401

DEFINITION = 'Инфляция — это устойчивый рост общего уровня цен. Из-за неё деньги со временем покупают меньше.'


def test_the_job_of_a_definition_is_asked_with_the_rule_of_two_or_three_phrases_and_both_phrases_are_said(call):
    rig = call(**LIVE)
    n = answer_with_job(rig, 'Что такое инфляция', DEFINITION, 'u1')
    instructions = rig.fake.run(n).request['instructions']
    assert 'две-три короткие фразы' in instructions and 'первая фраза сама по себе годится как ответ' in instructions
    rig.pump(TICK * 40)
    said = ' '.join(texts(rig))
    assert 'устойчивый рост' in said and 'покупают меньше' in said, said
