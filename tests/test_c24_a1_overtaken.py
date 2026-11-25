"""c24-a1 (fuzz seed 117, A2): the ear stood in for the final of «Если у меня было 40 рублей и я потратил 70 рублей, …» (``no_final_the_ear_stands_in``), its job
answered «Не хватает 30 рублей.», and G23 ``_overtaken`` dropped that answer as an older one: the turn the ear made has no start of speech (``start_ms`` -1), so every
turn of the cloud was «newer». «Гагарин полетел в 1961 году.» of the question before was cued instead. A turn with no known start is no older turn."""
CS = 'prepare_wide=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,stumble_place=on'


def test_the_answer_of_a_question_the_ear_stood_in_for_is_not_overtaken(monkeypatch):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    assert [v for v in stand.run(117).violations if v[0] in ('A2', 'A2e') and abs(v[1] - 58.34) < 0.05] == []
