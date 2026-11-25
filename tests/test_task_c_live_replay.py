"""WAVE 2 / Task C-seg: the real answers of the live corpus run 20261102-000520 (and the 05:51 inertia probe) replayed through
the host-like ControlledMedia, word by word the way the provider streams them.

The texts and the cues the live build produced are copied from ``03_TESTS/corpus_v1/runs/20261102-000520/*.json`` (field
``final_cursor_state``: the answer as far as it had streamed when the probe ended, and the chunks the server stored).
What is checked is what the owner asked for: the first cue is a speakable unit that arrives no later than the cues of that night,
a stall is never a cue, and nothing is lost or cut. Its SIZE is F1's (wave F, the owner's call of 3 Nov: «по одному слову»): a
meaning unit of up to 8 words - a sentence or a clause - where WAVE 2 / L2 had asked for 2-5 words.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                                       # noqa: E402
from echo_sync.first_useful import asks_for_number, compact_opening, first_cue  # noqa: E402
from echo_sync.portioner import MEANING_FIRST_MAX_WORDS, MEANING_NUMBER_FIRST_MAX_WORDS, first_window   # noqa: E402
from echo_sync.settings import CALL_SETTINGS, resolve                           # noqa: E402
from echo_sync.textutil import WORDS, definition_body, strip_process_prefix, syllables   # noqa: E402

# (id, question, answer as streamed, the live first cue, characters of the answer that had arrived when the live build cued)
LIVE = [
    ('cause_blue_sky', 'Почему небо днем голубое?',
     'солнечный свет, проходя через воздух, рассеивается на молекулах и короткие сине-фиолетовые волны рассеиваются сильнее, '
     'чем длинные. В итоге', 'солнечный свет,', 37),
    ('date_world_war_one', 'В каком году началась Первая мировая война?', 'В 1914 году.', 'В 1914 году.', 12),
    ('def_density', 'Что такое плотность вещества',
     'Плотность — это масса вещества в единице объёма. Обычно её записывают как ρ равно масса, делённая на объём. '
     'Например, если один кубический сантиметр материала весит два грамма,', 'Плотность — это масса вещества', 48),
    ('enum_states_of_matter', 'Назовите три агрегатных состояния вещества', 'Твёрдое, жидкое и газообразное.',
     'Твёрдое, жидкое', 31),
    ('long_electrocardiogram', 'Как называется запись электрической активности сердца', 'Электрокардиограмма, ЭКГ.',
     'Электрокардиограмма,', 25),
    ('neg_sound_vacuum', 'Верно ли, что звук распространяется в вакууме',
     'Нет, звук распространяется только в среде — воздухе, воде, твёрдых телах. В вакууме частиц нет, передавать колебания '
     'нечему, так что звук не идёт. Зато свет и другие электромагнитные волны через вакуум',
     'Нет, звук распространяется только в среде —', 58),
    ('num_boiling_point',
     'Сколько градусов Цельсия составляет температура кипения воды при нормальном атмосферном давлении',
     'При нормальном атмосферном давлении вода кипит при ста градусах Цельсия.',
     'При нормальном атмосферном давлении вода кипит при ста', 72),
    ('term_condensation', 'Как называется переход вещества из газообразного состояния в жидкое?', 'Это конденсация.',
     'Это конденсация.', 16),
    # the 05:51 probe: only the cue is recorded («свойство тела сопротивляться изменению своего движения.», 6 words, 4.3 s);
    # the rest of this answer is written in the style of the model
    ('def_inertia_0551', 'Что такое инерция?',
     'Свойство тела сопротивляться изменению своего движения. Чем больше масса тела, тем сильнее проявляется его инерция.',
     'свойство тела сопротивляться изменению своего движения.', 55),
]
# F1: the first meaning portion (WAVE 2 / L2 had: «солнечный свет,», «Плотность — это масса», «Твёрдое, жидкое», «Нет, звук
# распространяется», «При нормальном», «Свойство тела»)
EXPECTED = {
    'cause_blue_sky': 'солнечный свет, проходя через воздух,', 'date_world_war_one': 'В 1914 году.',
    'def_density': 'Плотность — это масса вещества в единице объёма.', 'enum_states_of_matter': 'Твёрдое, жидкое и газообразное.',
    # c22-merge (WAVE23 c22 item 3): never a first cue on a dash; the next clause fits the cap, so it goes along
    'long_electrocardiogram': 'Электрокардиограмма, ЭКГ.', 'neg_sound_vacuum': 'Нет, звук распространяется только в среде — воздухе, воде,',
    # C7-A: a question for a number gets its number in the first cue, with its unit (that night: «… при ста», torn from «градусах»)
    'num_boiling_point': 'При нормальном атмосферном давлении вода кипит при ста градусах Цельсия.',
    'term_condensation': 'Это конденсация.',
    'def_inertia_0551': 'Свойство тела сопротивляться изменению своего движения.',
}


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def words(text):
    return len(WORDS.findall(text))


def replay(tmp_path, question, answer):
    run = H.Stream(tmp_path, question, answer, 'words')
    index, cue = run.cues[0]
    return run, cue, len(''.join(run.pieces[:index + 1]))


@pytest.mark.parametrize('case', LIVE, ids=[c[0] for c in LIVE])
def test_the_first_cue_of_a_real_answer_is_short_and_comes_sooner(tmp_path, case):
    name, question, answer, live_cue, live_arrived = case
    run, cue, arrived = replay(tmp_path, question, answer)
    assert cue == EXPECTED[name]
    # F1 sizes: up to 8 words (C7-A: 12 for a question for a number), fewer than 3 only for a whole sentence; at most the call profile's syllables
    assert words(cue) <= first_window(CALL_SETTINGS, number=asks_for_number(question))[0] and (words(cue) >= 3 or cue.endswith(('.', '!', '?')))
    assert syllables(cue) <= resolve(CALL_SETTINGS)['max_syllables']
    assert arrived <= live_arrived                           # never later than the build that was measured
    assert run.chunks[0] == cue
    assert not [w for w in H.cut_words(answer, run.chunks)]  # no word is ever cut
    assert re.sub(r'\s+', '', answer).startswith(re.sub(r'\s+', '', ''.join(run.chunks)))   # in order, nothing invented


def test_the_long_cues_of_that_night_are_gone_and_the_median_arrives_earlier(tmp_path):
    cues = []
    for i, (_, question, answer, _, _) in enumerate(LIVE):
        folder = tmp_path / str(i)
        folder.mkdir()
        cues.append(replay(folder, question, answer)[1:])
    live = [c[3] for c in LIVE]
    # F1 (was: at most 3 words, shorter than the cues of that night): a meaning unit, never longer than the longest cue of that night
    # C7-A: a question for a number runs on to its number and unit, inside the wider window of such a question
    plain = [c for (c, _), case in zip(cues, LIVE) if not asks_for_number(case[1])]
    assert max(words(c) for c in plain) <= min(MEANING_FIRST_MAX_WORDS, max(words(c) for c in live))
    assert all(words(c) <= MEANING_NUMBER_FIRST_MAX_WORDS for c, _ in cues)
    arrived = sorted(a for _, a in cues)
    live_arrived = sorted(c[4] for c in LIVE)
    assert arrived[len(arrived) // 2] <= live_arrived[len(live_arrived) // 2]
    assert sum(arrived) < sum(live_arrived)


def test_the_stalling_cue_of_the_lookup_answer_is_gone(tmp_path):
    """lookup_law_article: «Понял, сейчас быстро проверю и скажу. Статья 421 ГК РФ устанавливает принцип свободы договора…»
    was cued «Понял, сейчас быстро». A verified question is not answered from model knowledge, so the host-like harness gives
    no cue; this replays the text pipeline of ControlledMedia._source by hand."""
    question = 'Что устанавливает статья 421 Гражданского кодекса Российской Федерации'
    answer = 'Понял, сейчас быстро проверю и скажу. Статья 421 ГК РФ устанавливает принцип свободы договора: граждане'
    spoken = compact_opening(definition_body(strip_process_prefix(answer), question), question)
    assert spoken == 'принцип свободы договора: граждане'
    arrived = ''
    cue = None
    for piece in re.findall(r'\s*\S+', spoken):
        arrived += piece
        cue = cue or first_cue(arrived, question, H.CONTROLLED_SETTINGS, final=False, last=False)
    # W1F-A (brief task-w1fix-briefs.md (a), G7 sc10): «close the cue at clause/sentence punctuation that has ALREADY arrived» - the
    # term ends at the colon that came with «договора:», on the same delta that released «принцип свободы» before.
    assert cue == 'принцип свободы договора:'
    for end in range(len('Понял'), len('Понял, сейчас быстро проверю и скажу') + 1):
        text = strip_process_prefix(answer[:end])
        assert not text or not first_cue(text, question, H.CONTROLLED_SETTINGS, final=False, last=False)
