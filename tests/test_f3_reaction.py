"""WAVE15 f3-reaction: ``prompt_pace`` = "on" reconciled with H3 rule 3. The owner's window (WAVE10 item 16): a stumble is helped 0.7-1.2 s after the listener's
last word, never earlier (a breath, a filler that may still bring the word) nor later. The ear's offset comes PACE_QUIET (0.3 s) after the last word. The scenes are H3's
(test_h3_tempo.Rig), the flag on; what is said is H3's, when is the window's."""
import pytest

from echo_sync.controlled_media import PACE_HELP_SECONDS, PACE_QUIET_SECONDS
from test_h3_tempo import GRID, HEAD, PORTION, REST, call  # noqa: F401 - the fixture

LO, HI = PACE_HELP_SECONDS[0] - PACE_QUIET_SECONDS, PACE_HELP_SECONDS[1] - PACE_QUIET_SECONDS      # from the offset


def in_window(cue, ended):
    return cue is not None and LO - 0.01 <= cue.t - ended <= HI + GRID


@pytest.mark.parametrize('said,rest', [
    ('общие', REST), ('ну общие', REST), ('общие ну', REST), ('общие э-э', REST), ('общие условия', 'установления налогов и сборов.'),
    ('общие условия установления налогов', 'и сборов.'), ('общие как там', REST), ('общие условия блин', 'установления налогов и сборов.'),
    ('общие общие', REST), ('общие общие общие', REST), ('общие условия условия', 'установления налогов и сборов.'), ('общие общие условия', 'установления налогов и сборов.'),
], ids=lambda value: str(value).replace(' ', '_'))
def test_a_start_with_its_neighbours_is_helped_inside_the_owners_window(call, said, rest):
    rig = call(prompt_pace='on')
    assert rig.settings['prompt_pace'] == 'on'
    rig.second_portion()
    rig.pump(1.0)
    ended = rig.says(said)
    cue = rig.next_cue(2)
    assert in_window(cue, ended) and cue.text == rest, (cue and (cue.text, round(cue.t - ended, 2)))


def test_a_filler_is_no_help_before_a_breath(call):
    """«общие ну»: the pace says the word will not come; the help is the first moment of the window, not the instant the ear's text lands (0.15 s after the offset)."""
    rig = call(prompt_pace='on')
    rig.second_portion()
    rig.pump(1.0)
    before = len(rig.cues())
    ended = rig.says('общие ну', lag=0.05)
    assert len(rig.cues()) == before, 'no help with the text of the ear: the listener stopped 0.35 s ago'
    cue = rig.next_cue(2)
    assert in_window(cue, ended) and cue.t - ended <= LO + GRID


def test_speech_that_begins_in_the_wait_is_not_cut_into(call):
    rig = call(prompt_pace='on')
    rig.second_portion()
    rig.pump(1.0)
    rig.says('общие', speech=0.3, lag=0.1)
    rig.pump(0.1)
    rig.onset()
    rig.pump(2.0)
    assert rig.said() == [HEAD, PORTION], 'speech began inside the window: no help into it'


def test_the_stammer_of_the_call_with_the_wait_of_h3(call):
    rig = call(prompt_pace='on', repeat_seconds=3.5)
    rig.second_portion()
    rig.pump(2.1)
    ended = rig.says('общие', speech=1.2, lag=0.13)
    cue = rig.next_cue(2)
    assert in_window(cue, ended) and cue.text == REST


# =====================================================================================================================================
# flow_ahead: the next portion at once. Its controller input (``ear_progress``) had no producer: the flag did nothing on the server.
# =====================================================================================================================================

def test_the_ear_takes_its_text_so_far_when_it_acts(call):
    assert call().ear.partial_ms and not call(ear='shadow').ear.partial_ms, 'U54: an acting ear always gives its text so far (the tail of the portion); a shadow ear, as it was'


def test_the_ears_partial_text_feeds_flow_ahead(tmp_path):
    """test_w5_flow's real controller scene, the text so far given as the transport gives it (``ear_partial``, native_media_socket), not by the test's own door."""
    from test_stable_partial_ack import ANSWER, Speaker, dictation, speaks
    from test_w5_flow import SPS, syllables
    d = dictation(tmp_path, ANSWER, 2, settings={'preset': 'meaning', 'local_ear': 'act'})
    portion = d.current
    d.controller.flow.tempo.per_syllable = [SPS] * 8
    words = portion.rstrip('.').split()
    d.controller.ear_onset(1)
    cloud = Speaker(d).start()
    spoken = []
    for k in range(1, len(words)):
        d.clock.advance(max(1, syllables(words[k - 1])) * SPS)
        spoken += speaks(d.controller.ear_partial({'uid': 1, 'text': ' '.join(words[:k]).lower(), 'decode_ms': 40}))
        spoken += speaks(d.controller.tick(now=d.clock()))
    for _ in range(5):
        d.clock.advance(0.1)
        spoken += speaks(d.controller.tick(now=d.clock()))
    assert spoken == [d.chunks[3]] and d.index == 3, 'the next portion goes before the ear heard the end of the utterance'
    assert cloud.final(portion) == [] and d.index == 3


# =====================================================================================================================================
# lead_cue: the lead does not stand before the substance. It used to wait for a repeat of the lead, and with none it was cued again after repeat_seconds.
# =====================================================================================================================================

def test_the_substance_follows_the_lead_at_once_when_the_listener_has_not_begun(call):
    from test_w5_lead_wiring import EAR, FINAL, LEAD, final, question, wired
    rig = wired(call(fast_text='on', lead_cue='on'))
    question(rig, EAR)
    final(rig, 'u1', FINAL)
    assert rig.said() == [LEAD]
    rig.job_says(0, 'Первая мировая война началась 28 июля 1914 года.')
    rig.job_ends(0)
    rig.pump(0.5)
    assert rig.said() == [LEAD, '28 июля 1914 года.'], 'the substance at once, the lead not again'


def test_a_listener_already_repeating_the_lead_is_not_spoken_over(call):
    from test_w5_lead_wiring import EAR, FINAL, LEAD, final, question, wired
    rig = wired(call(fast_text='on', lead_cue='on'))
    question(rig, EAR)
    final(rig, 'u1', FINAL)
    rig.onset()
    rig.job_says(0, 'Первая мировая война началась 28 июля 1914 года.')
    rig.job_ends(0)
    rig.pump(0.5)
    assert rig.said() == [LEAD] and rig.c.state()['chunk_index'] == 0, 'the repeat of the lead goes the usual way'
