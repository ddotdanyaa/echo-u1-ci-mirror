"""c23-final, round 0 of the rounds on the recommended profile: with ``fast_private`` (and ``ear_job``) the ear joins the correction «Нет, не 40, а 50.»
(0.95 s after «… 40 рублей и я потратил 80 рублей, сколько денег осталось?») to the question before it (``utterance_continued``), and the job prepared on
that question («Не хватает 40 рублей.») is admitted as the answer of the grown utterance: a cue that contradicts the correction (A7, fuzz seed 1029).
``fast_private`` is deleted (f84a05a9): the job of a personal question is prepared before the final always, the seed below is the case. c24-b: the cause is the release at the final of u5 while the cloud had opened u6 (the correction) already: the
personal question keeps its prepared job only when nothing was said after it (``_split_after``), else it goes the lookup way like without the flag."""
CS = 'prepare_wide=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'


def a7(monkeypatch, flags):
    monkeypatch.setenv('ECHO_REPLAY_FLAGS', CS + flags)
    from tools.replay import stand
    return [v for v in stand.run(1029).violations if v[0] == 'A7']


# c24-a1: green: the same correction at 31.20 is answered «Не хватает 30 рублей.» (the old first cue waits for speech said after its question, ``_said_after``); c24-b: and fast_private keeps the prepared job only when no turn was opened after the question
def test_a_correction_joined_to_a_personal_question_never_gets_the_old_answer(monkeypatch):
    assert a7(monkeypatch, ',ear_job=on') == []
