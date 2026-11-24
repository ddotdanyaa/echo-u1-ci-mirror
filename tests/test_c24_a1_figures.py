"""c24-a1 (fuzz seed 42, A2e): the ear writes a number in figures («нет не 70 а 60»): that is speech with content as much as «нет не семьдесят а шестьдесят». It was no
content (``_has_content``: a figure is no known word), so the correction of the question held nothing, and «Осталось 40 рублей.» of the question it corrects was said
0.5 s after the ear had it."""
import pytest

CS = 'prepare_wide=on,ear_release=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,stumble_place=on,local_fallback=on'


@pytest.mark.parametrize('text', ['нет не 70 а 60', 'нет не семьдесят а шестьдесят'])
def test_figures_are_content(text):
    from echo_sync.controlled_media import ControlledMedia
    assert ControlledMedia._has_content(type('Probe', (), {'settings': {}})(), text)


def test_the_correction_in_figures_holds_the_old_first_cue(monkeypatch):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    assert [v for v in stand.run(42).violations if v[0] in ('A2', 'A2e') and abs(v[1] - 25.48) < 0.05] == []
