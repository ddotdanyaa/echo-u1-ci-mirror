"""c24-a1 (fuzz seed 730, A8; the owner's call of 4 Nov 20:34): a remark whose job failed goes back to the cloud (``fast_text_candidate_handed_back``), and the cloud's
reply «Ну наконец-то.» to it was admitted as an answer and cued. An interjection is no sentence of substance, like «Хорошо.» or «Мг.»."""
import pytest

from echo_sync.controlled_media import ControlledMedia as C

CS = 'prepare_wide=on,ear_release=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,stumble_place=on,local_fallback=on'


@pytest.mark.parametrize('reply', ['Ну наконец-то.', 'Наконец-то!', 'Ну наконец-то. Ну что обсудим сегодня?'])
def test_an_interjection_of_the_cloud_is_no_answer(reply):
    assert C._of_substance(reply, 'Ты быстро подсказываешь, молодец.', True)[1] == []


def test_a_sentence_with_the_word_is_still_one():
    assert C._of_substance('Война наконец закончилась в 1945 году.', 'Когда закончилась война?', True)[1]


def test_the_seed_says_no_chatter_of_the_cloud(monkeypatch):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    assert [v for v in stand.run(730).violations if v[0] == 'A8'] == []
