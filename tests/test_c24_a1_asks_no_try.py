"""c24-a1 (F1 of c23, fuzz seed 107: A2/A2e): «Если у меня было 70 рублей и я потратил 90 рублей, сколько денег осталось?» said over the portion «Осталось 10 рублей.»
shares «рублей», «осталось» with it: the ear's tempo took it for a try and said the portion again (``ear_tempo`` replay) - the old answer over the new question, whose
final the cloud lost. g17 made a question no try by the ear's kind; the ear writes no «?» (its kind was ``silent``): a question by its form without the mark, with words
of its own beyond the portion, is no try either."""
CS = 'prepare_wide=on,ear_release=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,stumble_place=on,local_fallback=on'


def test_a_question_sharing_words_with_the_portion_is_no_try(monkeypatch):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    assert [v for v in stand.run(107).violations if v[0] in ('A2', 'A2e') and abs(v[1] - 53.22) < 0.05] == []
