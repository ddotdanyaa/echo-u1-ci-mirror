"""E48 / U168: the measurement reads the release's BRAIN: same request, same profile, one fingerprint."""
import json

import pytest

from echo_sync import controlled_host, fast_text, warm
from tools import brain_eval as BE


@pytest.fixture
def home(tmp_path):
    folder = tmp_path / 'materials'
    folder.mkdir()
    (folder / 'echo_settings.json').write_text(json.dumps({'subject': 'Налоги', 'style': 'коротко'}, ensure_ascii=False), encoding='utf-8')
    (folder / 'context.md').write_text('Амортизация это перенос стоимости основных средств на затраты.\n\nНалог отличается от сбора.', encoding='utf-8')
    warm.material_cache.key = None
    return tmp_path


def test_the_request_is_the_one_the_release_builds(home):
    brain = BE.Brain(home)
    question = 'Что такое амортизация'
    from echo_sync import material_pick
    context = warm.material_cache.load(home)
    picker = material_pick.for_job(material_pick.load_whole(home))
    release = fast_text.build_request(question, instructions=picker.instructions(question, (), context, fast_text.BRAIN_POLICY), history=())
    assert brain.request_for(question) == release
    assert fast_text.BRAIN_POLICY in release['instructions'] and 'Предмет занятия: Налоги' in release['instructions']


def test_the_measurement_holds_no_prompt_of_its_own():
    text = open(BE.__file__, encoding='utf-8').read()
    assert 'from echo_sync.fast_text import BRAIN' not in text and 'F.SYSTEM' not in text


def test_fingerprint_follows_policy_profile_and_questions(home, monkeypatch):
    base = BE.Brain(home).fingerprint()
    assert BE.Brain(home).fingerprint() == base
    (home / 'materials' / 'echo_settings.json').write_text(json.dumps({'subject': 'Другое'}, ensure_ascii=False), encoding='utf-8')
    warm.material_cache.key = None
    assert BE.Brain(home).fingerprint()['profile_sha256'] != base['profile_sha256']
    monkeypatch.setattr(fast_text, 'BRAIN_POLICY', fast_text.BRAIN_POLICY + ' лишнее')
    assert BE.Brain(home).fingerprint()['brain_policy_sha256'] != base['brain_policy_sha256']
    monkeypatch.setattr(BE, 'ASK', BE.ASK + ('Новый вопрос',))
    assert BE.question_set_sha() != base['questions']


def test_run_scores_groups_and_retries(home):
    brain = BE.Brain(home)
    seen = []

    def send(request, model):
        seen.append(request)
        text = request['input'][-1]['content'][0]['text']
        if 'Сейчас прозвучало' in text:
            return {'status': 200, 'text': '988', 'ttft_ms': 900}
        if text in BE.DECLINE:
            return {'status': 200, 'text': '—', 'ttft_ms': 800}
        return {'status': 200, 'text': 'Крещение Руси 988 год', 'ttft_ms': 1000}
    result = BE.run(brain, send, gold=[{'text': 'В каком году крещение Руси', 'gold_answer': '988 год'}], model='m', sleep=lambda s: None)
    summary = result['summary']
    assert summary['decline_declined'] == [len(BE.DECLINE)] * 2 and summary['gold'] == {'right': 1, 'n': 1, 'declined': 0, 'meta': 0}
    assert summary['preface']['n'] == 1 and summary['errors'] == 0 and summary['ttft_ms']['max'] == 1000
    assert all(r['instructions'].startswith(fast_text.BRAIN_POLICY) for r in seen)      # every probe carries the release policy
    calls = []
    BE.run(brain, lambda r, m: calls.append(1) or {'status': 500}, gold_only=True, gold=[{'text': 'q', 'gold_answer': 'a'}], sleep=lambda s: None)
    assert len(calls) == 4      # gold + preface, two tries each


def test_not_worse_needs_the_same_question_set(home):
    brain = BE.Brain(home)
    ok = lambda r, m: {'status': 200, 'text': '988'}      # noqa: E731
    gold = [{'text': 'q', 'gold_answer': '988'}]
    base = BE.run(brain, ok, gold=gold, sleep=lambda s: None)
    assert BE.not_worse(base, base)
    other = json.loads(json.dumps(base))
    other['fingerprint']['questions'] = 'x'
    assert not BE.not_worse(other, base)


def test_the_host_names_the_same_policy_the_tool_measures(home):
    assert 'BRAIN_POLICY' in open(controlled_host.__file__, encoding='utf-8').read()
    assert BE.Brain(home).policy is fast_text.BRAIN_POLICY
