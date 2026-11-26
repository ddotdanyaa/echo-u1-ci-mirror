"""The index of the bank is built once per bank and material: every call opened after the first gets it at once, with its own utterance state."""
import json

from echo_sync import instant


def _bank(tmp_path, q='Какая ставка НДС в России'):
    path = tmp_path / 'bank.json'
    path.write_text(json.dumps([{'id': 'a', 'q': q, 'alt': [], 'answer': 'Двадцать процентов.', 'core': 'Двадцать процентов', 'source': 'т', 'subject': 'с', 'trust': 'Д'}], ensure_ascii=False), encoding='utf-8')
    return {'instant': 'on', 'instant_bank_file': str(path)}


def test_two_calls_share_the_build_and_not_the_state(tmp_path, monkeypatch):
    settings, built, real = _bank(tmp_path), [], instant.Instant.__init__

    def counted(self, *a, **k):
        built.append(1)
        real(self, *a, **k)
    monkeypatch.setattr(instant.Instant, '__init__', counted)
    first, second = instant.from_settings(settings), instant.from_settings(settings)
    assert len(built) == 1 and first is not second and first.postings is second.postings
    assert first.feed('какая ставка ндс в россии', 0.0, final=True) is not None
    assert first.hit is not None and second.hit is None


def test_another_bank_file_or_material_is_built_again(tmp_path):
    settings = _bank(tmp_path)
    old = instant.from_settings(settings)
    assert instant.from_settings(settings, material='Новый текст.').postings is not old.postings
    assert instant.from_settings(_bank(tmp_path, 'Что такое баланс')).entries[0]['q'] == 'Что такое баланс'


def test_warm_start_builds_the_index_a_call_takes(tmp_path, monkeypatch):
    from echo_sync import warm
    settings, built, real = _bank(tmp_path), [], instant.Instant.__init__

    def counted(self, *a, **k):
        built.append(1)
        real(self, *a, **k)
    monkeypatch.setattr(instant.Instant, '__init__', counted)
    step = next(s for s in warm.default_steps(tmp_path, settings=settings) if s.name == 'instant')
    step.fn()
    assert len(built) == 1
    assert instant.for_home(settings, tmp_path) is not None and len(built) == 1


def test_the_ranker_is_the_rule_of_every_call(tmp_path):
    settings = _bank(tmp_path)
    assert instant.from_settings(settings).ranker is not None
