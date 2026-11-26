"""one-input U19: the language of the utterance is a probe (M7) whose verdict the answer owner (M3, the brain's language line) and the speech owner (M6, the voice) use. No mode key: defaults only."""
import pytest

import helpers_night_memory as M
from echo_sync.sapi_worker import lang_ssml

BASE = {'fast_text': 'on', 'conversation_ledger': 'off', 'topic_recap': 'off', 'v6_memory': 'off'}      # the defaults for everything about the language
EN_Q = 'What is the capital of Canada, please?'
EN_A = 'The capital of Canada is Ottawa. It stands on the Ottawa river.'
RU_Q = 'Какая столица у Канады, подскажите?'


@pytest.fixture
def make(tmp_path):
    calls = []

    def build(mind=lambda request: 'Первая часть ответа. Вторая часть ответа.', **over):
        call = M.Call(tmp_path / f'c{len(calls)}', mind=mind, **{**BASE, **over})
        calls.append(call)
        return call
    yield build
    for call in calls:
        call.close()


def test_an_english_question_gets_an_english_answer_request(make):
    call = make()
    call.say(EN_Q)
    assert len(call.requests) == 1 and 'Answer in English' in call.requests[0][2]['instructions']


def test_a_russian_question_after_an_english_one_is_back_to_the_policy_without_the_english_line(make):
    call = make()
    call.say(EN_Q)
    call.say(RU_Q)
    instructions = call.requests[-1][2]['instructions']
    assert instructions.startswith(M.POLICY) and 'Answer in English' not in instructions      # M9: the memory card follows the policy, it is no setting


def test_an_english_answer_is_spoken_by_the_english_voice(make):
    call = make(mind=lambda request: EN_A)
    call.say(EN_Q)
    call.pump(2.0)
    spoken = [t for t in call.w.synth_calls if 'Ottawa' in t]
    assert spoken and all(lang_ssml(t) is not None and '<voice ' in lang_ssml(t) for t in spoken)


def test_the_host_picks_the_voice_by_the_cue_without_a_key():
    from echo_sync import controlled_host
    from echo_sync.settings import DEFAULTS
    assert 'answer_lang' not in DEFAULTS and 'tts_lang' not in DEFAULTS
    assert 'tts_lang' not in open(controlled_host.__file__, encoding='utf-8').read()
