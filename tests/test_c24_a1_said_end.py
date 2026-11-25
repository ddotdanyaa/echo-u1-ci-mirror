"""c24-a1: one final says one utterance. A final that came while the NEXT utterance was being said (it began after the speech that final says had ended)
does not say that next utterance, however many words they share («не нагревать, а охлаждать» | «не охлаждать, а нагревать»; «70 … 90» | «90 … 70»).
Its text is speech nobody judged: the first cue of the answer to the older question waits for its verdict (``first_cue_hold``), and is not heard as the
answer to the new one (fuzz seeds 0 and 16: A2e / A2, the stand's «старый ответ»).
Nor does a final say a later piece by the words that piece shares with the earlier one it says («В каком году было Куликовская битва?» says nothing of
«В каком году было основание Петербурга?» heard after it: seed 8). The same when the ear's text of the new utterance comes after the final (seed 18)."""
import pytest

CS = 'prepare_wide=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,stumble_place=on'


@pytest.mark.parametrize("seed,at", [(0, 80.28), (16, 34.2), (8, 20.18), (18, 41.46)])
def test_the_answer_of_the_question_before_is_not_heard_over_the_new_one(monkeypatch, seed, at):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    out = stand.run(seed)
    assert [v for v in out.violations if v[0] in ('A2', 'A2e') and abs(v[1] - at) < 0.05] == []


def test_a_command_said_before_the_first_cue_does_not_hold_it(monkeypatch):
    """Fuzz seed 532: «Повтори.» said right after the question, before its answer was heard, held the first cue until its own final (7.5 s instead of 5.5 s), and with the
    repeats after it the portion was said 4 times in a row (A5). A command, a doubt is said of the answer: no new question to wait for."""
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    out = stand.run(532)
    assert [v for v in out.violations if v[0] == 'A5'] == [] and min(c[0] for c in out.cues if not c[6]) < 6.0


def test_a_final_of_other_words_leaves_a_question_whose_final_was_lost_unjudged(monkeypatch):
    """Fuzz seed 36: the cloud lost the final of «Нужно не уменьшать, а увеличивать …?» (46.12-49.38); the final of the remark after it («Сейчас, подожди, я подумаю.»,
    51.22-52.29) named none of the pieces nobody had judged and took them all («one of the two misheard the other»), and «Петербург основали в 1703 году.» of the
    question before was cued at 54.42. Its own speech is a piece the ear heard: the question stays unjudged."""
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    out = stand.run(36)
    assert [v for v in out.violations if v[0] in ('A2', 'A2e') and abs(v[1] - 54.42) < 0.05] == []
