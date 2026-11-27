"""c24-a1: a run of speech the ear heard begin after the speech the question's final says had ended (a silence of EAR_RELEASE_SILENCE_SECONDS between them) is no breath
of that question, though it began before the final came: it does not join the question (``utterance_continued``). Ladder L4 seed 21: «Что такое активы?» ended at
77.94, the cloud's final came at 82.06, «Президент подписал закон о бюджете …» of somebody else began at 81.36 and was joined to it; the answer was retired. (The scene still misses that answer: the job on the other's final hits the model's timeout of L4 and holds the first cue, ``_first_held``.)"""
from tools.ladder import scenes as L

CS = 'two_witnesses=on,prepare_wide=on,ear_release=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = dict(kv.split('=') for kv in (CS + ',stop_in_flight=on,repeat_rule=on,stumble_place=on,local_fallback=on').split(','))


def test_speech_begun_after_the_question_ended_is_no_rest_of_it():
    out = L._play(L.Scene('L4', 21, flags=PROFILE))
    assert not [line for t, line in out.ctl if 86.0 < t < 87.0 and 'reason=utterance_continued' in line]
