"""Provider routing and discovery without network calls or account credentials."""
import json

import pytest

from tools import agent_factory as F
from tools import agent_factory_runner as R
from tools import factory_channels as C
from tools import factory_discover as D


PROVIDERS = [
    ('groq', 'GROQ_API_KEY', 'llama-code', 'https://api.groq.com/openai/v1'),
    ('cerebras', 'CEREBRAS_API_KEY', 'llama-code', 'https://api.cerebras.ai/v1'),
    ('cohere', 'COHERE_API_KEY', 'command-code', 'https://api.cohere.ai/compatibility/v1'),
    ('huggingface', 'HF_TOKEN', 'org/code-model', 'https://router.huggingface.co/v1'),
]


@pytest.mark.parametrize('provider,key_env,model,base', PROVIDERS)
def test_free_provider_routes_edits_to_its_endpoint(tmp_path, monkeypatch, provider, key_env, model, base):
    monkeypatch.setenv(key_env, 'synthetic')
    task = F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    (tmp_path / 'calc.py').write_text('x = 1\n')
    calls = []

    def post(url, key, body, timeout):
        calls.append((url, key, body['model']))
        return 200, json.dumps({'choices': [{'message': {'content':
            'calc.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n'},
            'finish_reason': 'stop'}]}).encode()

    rc, _, note = R.light_attempt(task, tmp_path, provider + '/' + model,
                                   key_env=key_env, prompt_override='p', post=post)
    assert rc == 0, note
    assert calls == [(base + '/chat/completions', 'synthetic', model)]
    assert (tmp_path / 'calc.py').read_text() == 'x = 2\n'


def _channel(provider, model='code-model'):
    return dict(id=provider, model=provider + '/' + model, group=provider, key_env='TEST_KEY',
                rpm=5, tpm=1000, rpd=10, verified=True)


def test_free_provider_pool_skips_unknown_registry_row(tmp_path, caplog):
    path = tmp_path / 'channels.json'
    path.write_text(json.dumps({'channels': [_channel('unknown'), _channel('groq')]}))
    configured = json.loads(path.read_text())['channels']
    C.validate(configured)
    assert [c['id'] for c in configured] == ['groq']
    assert 'unknown' in caplog.text and 'provider' in caplog.text
    assert C.choose(configured, {}, 100, {'TEST_KEY': 'synthetic'})['id'] == 'groq'


@pytest.mark.parametrize('provider,key_env,model,base', PROVIDERS)
def test_free_provider_listing_request_and_models(provider, key_env, model, base):
    assert D.provider_of(key_env) == provider
    assert D.provider_of(key_env + '_2') == provider
    url, headers = D.listing_request(provider, 'synthetic')
    expected = 'https://api.cohere.ai/v1/models' if provider == 'cohere' else base + '/models'
    assert url == expected and 'synthetic' not in url
    assert list(headers) == ['Authorization']
    assert headers['Authorization'].endswith(' synthetic')
    listing = ({'models': [{'name': model, 'endpoints': ['chat']},
                           {'name': 'embed-model', 'endpoints': ['embed']},
                           {'name': 'old-model', 'endpoints': ['chat'], 'is_deprecated': True}]}
               if provider == 'cohere' else
               {'data': [{'id': model}, {'id': 'inactive', 'active': False}, {'id': ''}]})
    assert D.models_of(provider, listing) == [model]
    configured = [_channel(provider, model)]
    C.validate(configured)
    assert C.choose(configured, {}, 100, {'TEST_KEY': 'synthetic'})['model'] == provider + '/' + model
    # Listing a model is not evidence of a free quota: do not invent channel limits.
    assert D.rows(provider, key_env, [model]) == []


def test_free_provider_unknown_listing_is_refused():
    with pytest.raises(ValueError, match='provider'):
        D.listing_request('unknown', 'synthetic')
