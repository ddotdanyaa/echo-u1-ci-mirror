"""<id> wiring (owner: a new key is one line in the secrets; the registry of channels is not edited by
hand; the free models of that key are found by themselves). Once a day at START the loop lists the models of every key
of its env file, probes each new row once and writes only the verified rows to channels.json; the new key reaches the
runner at once; a second START the same day asks nothing; a fault never stops the loop. The network is faked."""
import json

from tests.test_factory_loop import Env, L, task_row

GOOGLE = {'models': [{'name': 'models/gemini-3.5-flash-lite', 'supportedGenerationMethods': ['generateContent']},
                     {'name': 'models/gemma-4-31b-it', 'supportedGenerationMethods': ['generateContent']}]}


def setup(tmp_path, monkeypatch, env_text):
    env = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    env_file = tmp_path / ('keys.' + 'env')
    env_file.write_text(env_text, encoding='utf-8')
    channels = tmp_path / 'channels.json'
    channels.write_text(json.dumps({'note': 'kept', 'channels': [dict(
        id='g-lite', model='google/gemini-3.5-flash-lite', key_env='GEMINI_API_KEY', group='g-lite', tier='main',
        rpm=15, tpm=250000, rpd=400, verified=True)]}), encoding='utf-8')
    gets = []
    monkeypatch.setattr(L, '_http_get', lambda url, headers: gets.append(url) or (200, GOOGLE))
    monkeypatch.setattr(L, '_probe', lambda row, key: 200)
    monkeypatch.delenv('GOOGLE_API_KEY_3', raising=False)
    loop = env.loop(extra={'extra_env': {'GEMINI_API_KEY': 'k1'}})
    loop.cfg.env_file, loop.cfg.channels = env_file, channels
    return env, loop, channels, gets


def test_a_new_key_in_the_secrets_adds_its_verified_rows_and_reaches_the_runner(tmp_path, monkeypatch):
    env, loop, channels, gets = setup(tmp_path, monkeypatch, 'GEMINI_API_KEY=k1\nGOOGLE_API_KEY_3=k3\nHOME=x\n')
    loop._discover_keys()
    data = json.loads(channels.read_text(encoding='utf-8'))
    pairs = {(c['model'], c['key_env']) for c in data['channels']}
    assert ('google/gemini-3.5-flash-lite', 'GOOGLE_API_KEY_3') in pairs and len(pairs) == 4
    assert data['note'] == 'kept' and data['channels'][0]['rpd'] == 400        # hand-made content stays
    assert loop.extra_env.get('GOOGLE_API_KEY_3') == 'k3'                      # the runner gets the new key now
    event = [e for e in env.events() if e.get('span') == 'discover'][-1]
    assert event['reason'].startswith('added 3') and 'k3' not in json.dumps(event)


def test_a_second_start_the_same_day_asks_nothing(tmp_path, monkeypatch):
    env, loop, channels, gets = setup(tmp_path, monkeypatch, 'GEMINI_API_KEY=k1\n')
    loop._discover_keys()
    loop._discover_keys()
    assert len(gets) == 1


def test_a_fault_never_stops_the_loop(tmp_path, monkeypatch):
    env, loop, channels, gets = setup(tmp_path, monkeypatch, 'GEMINI_API_KEY=k1\n')

    def boom(url, headers):
        raise OSError('network')
    monkeypatch.setattr(L, '_http_get', boom)
    loop._discover_keys()
    assert any(e.get('span') == 'infra' and 'discover' in e.get('reason', '') for e in env.events())
