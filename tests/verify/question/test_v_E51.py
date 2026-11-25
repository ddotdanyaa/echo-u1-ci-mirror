"""V3 E51: a compound question must not leave a part forgotten. The backlog (E51): «составной вопрос и забытый подпункт»: the answer ended, a part of the question is still open
(``followup.QuestionMap.open_parts`` has it in the conversation map) and NOTHING reads it: the call goes silent about that part.

Real ControlledMedia (rig ``call``). The question has two asks («сколько стоит доставка и когда привезут»); the answer settles the first only («пятьсот рублей») and is spoken to its end.
The contract: the open ask is not dropped: either a new job is asked for exactly that part, or the listener hears the part named (not the whole old question again).
Red until a reader of the open part lives in cm_answer/cm_route (the action of speech in ACTS). Not run on the laptop."""
from question_kit import LIVE_RULES, TICK, call, plan      # noqa: F401 - call is the fixture

ASKED = 'Сколько стоит доставка и когда привезут'
ANSWER = 'Доставка стоит пятьсот рублей.'
OPEN_PART = 'когда привезут'


def _mentions_open_part(text):
    folded = str(text).casefold().replace('ё', 'е')
    return 'привез' in folded or 'срок' in folded or 'доставят' in folded


def test_an_open_part_of_a_compound_question_is_taken_up_after_the_answer_ended(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ASKED, answer=ANSWER)
    jobs_before = len(rig.fake.runs)
    said_before = list(rig.said())
    rig.pump(TICK * 4)
    rig.pump(12.0)
    new_jobs = [run for run in rig.fake.runs[jobs_before:] if _mentions_open_part(getattr(run, 'question', '') or str(getattr(run, 'request', '')))]
    new_cues = [text for text in rig.said()[len(said_before):] if _mentions_open_part(text)]
    assert new_jobs or new_cues, f'the part «{OPEN_PART}» is open and nothing took it up: jobs {len(rig.fake.runs) - jobs_before}, new cues {rig.said()[len(said_before):]}'
