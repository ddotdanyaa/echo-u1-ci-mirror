"""V1a E85: the start with no question: 60-90 s of ordinary talk, then a question. Expected: silence with no false «Не нашёл», then a normal first help; and the failure signs of the table (no final, a refused job,
a cold open) each end in a state the call lives in, said as nothing.

The scene has a guard already (tests/test_w8_silence.py::test_e85_ninety_seconds_of_talk_say_nothing_then_a_question_is_answered, commit of W8); these tests are the same scene plus the signs of the backlog's table that
that file does not take: a refused job on every line of talk, a turn that never gets its final, the very first utterance of the call a question. On the real ControlledMedia (rig ``call``), the job's stream scripted.
Not run on the laptop. The «literature review» of the row (W19) is a document, not a test: report.
"""
from kind_a_kit import LIVE_RULES, TICK, pending_jobs, said_to_the_room, spoken_failures
from test_h3_tempo import call      # noqa: F401 - the fixture
from test_w8_silence import AUSTRALIA, CHAT, first_help_is, question, talk
from echo_sync.timer_policy import CLOUD_DEAF_S
import helpers_s6_state as S

# CHAT's last line, «Слушай а ты куда в субботу», asks the prompter by the owner's ruling (classifier ruling 3: the singular «ты» addresses it), so a failed job on it is told: the lines of talk that a job fails on ask nothing.
TALK = CHAT[:4]


def test_ninety_seconds_of_talk_then_a_question_the_scene_of_the_row(call):
    rig = call(**LIVE_RULES)
    n = talk(rig, CHAT * 3)
    assert rig.said() == [] and not spoken_failures(rig)
    question(rig, 'u9', AUSTRALIA, n, 'Канберра.')
    first_help_is(rig, AUSTRALIA, 'Канберра.')


def test_the_job_refuses_every_line_of_the_talk_and_nothing_false_is_said(call):
    """Sign «отказ job»: each line of talk gets a job that fails (its one more too); the cloud says nothing of its own. 90 s: no cue, no «Не нашёл», and the next real question is still answered."""
    rig = call(**LIVE_RULES)
    for k, line in enumerate(TALK * 4):
        since = len(rig.fake.runs)
        said_to_the_room(rig, f'c{k}', line)
        for _ in range(3):
            for n in pending_jobs(rig, since):
                rig.fake.run(n).fail()
                rig.pump(TICK * 2)
        rig.pump(6.0)
    assert rig.said() == [] and not spoken_failures(rig), (rig.said(), [c.text for c in spoken_failures(rig)])
    n = len(rig.fake.runs)
    question(rig, 'u9', AUSTRALIA, n, 'Канберра.')
    first_help_is(rig, AUSTRALIA, 'Канберра.')


def test_a_turn_that_never_gets_its_final_says_nothing_and_the_call_is_alive(call):
    """Sign «нет final»: the cloud opened a user turn and never closed it, for as long as the call's rule allows (CLOUD_DEAF_S, W9-arch: a cloud that has opened a turn and sent nothing for that long is told once as the channel's phrase, and that is no failure of this sign). Nothing is said, no failure; the next question is answered."""
    rig = call(**LIVE_RULES)
    rig.w.feed(S.turn_created('u0', 'user', 'Ну в общем'))
    rig.pump(CLOUD_DEAF_S - 1.0)
    assert rig.said() == [] and not spoken_failures(rig)
    n = len(rig.fake.runs)
    question(rig, 'u1', AUSTRALIA, n, 'Канберра.')
    first_help_is(rig, AUSTRALIA, 'Канберра.')


def test_the_very_first_utterance_of_the_call_is_a_question_and_gets_its_help(call):
    """Sign «холодное открытие»: no talk before it, no warm-up."""
    rig = call(**LIVE_RULES)
    question(rig, 'u1', AUSTRALIA, 0, 'Канберра.')
    first_help_is(rig, AUSTRALIA, 'Канберра.')
