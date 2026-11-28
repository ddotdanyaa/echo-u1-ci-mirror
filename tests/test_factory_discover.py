"""<id> (owner: a new key - Google, OpenRouter or another - is added by one line in the secrets; the channel
registry is not edited by hand; the free models of that key are found by themselves). Pure part: which provider a key
name belongs to, which models of a provider listing are known free models, and the channel rows they make with the
known free limits; a merge that adds new rows and never drops or changes an existing one (hand edits stay)."""
from tools import factory_discover as D

GOOGLE = {'models': [
    {'name': 'models/gemini-3.5-flash-lite', 'supportedGenerationMethods': ['generateContent', 'countTokens']},
    {'name': 'models/gemma-4-31b-it', 'supportedGenerationMethods': ['generateContent']},
    {'name': 'models/text-embedding-9', 'supportedGenerationMethods': ['embedContent']},
    {'name': 'models/gemini-9-ultra-paid', 'supportedGenerationMethods': ['generateContent']}]}
OPENROUTER = {'data': [{'id': 'nvidia/nemotron-3-ultra:free'}, {'id': 'openai/gpt-9'}, {'id': 'cohere/north-mini-code:free'}]}


def test_the_provider_of_a_key_name():
    assert D.provider_of('GEMINI_API_KEY') == 'google'
    assert D.provider_of('GOOGLE_API_KEY_3') == 'google'
    assert D.provider_of('OPENROUTER_API_KEY') == 'openrouter'
    assert D.provider_of('HOME') is None


def test_only_known_free_models_of_a_listing_are_taken():
    assert D.google_models(GOOGLE) == ['gemini-3.5-flash-lite', 'gemma-4-31b-it']
    assert D.openrouter_models(OPENROUTER) == ['cohere/north-mini-code:free', 'nvidia/nemotron-3-ultra:free']


def test_rows_carry_the_known_limits_and_a_group_per_key():
    rows = D.rows('google', 'GOOGLE_API_KEY_3', ['gemini-3.5-flash-lite', 'gemma-4-31b-it'])
    lite = next(r for r in rows if r['model'] == 'google/gemini-3.5-flash-lite')
    assert (lite['rpm'], lite['tpm'], lite['rpd']) == (15, 250000, 500)
    assert lite['key_env'] == 'GOOGLE_API_KEY_3' and lite['verified'] is False
    assert lite['group'] != D.rows('google', 'GEMINI_API_KEY', ['gemini-3.5-flash-lite'])[0]['group']
    gemma = next(r for r in rows if r['model'] == 'google/gemma-4-31b-it')
    assert (gemma['rpm'], gemma['tpm'], gemma['rpd']) == (30, 16000, 14400)
    assert len({r['id'] for r in rows}) == 2


def test_the_group_is_what_the_provider_counts_together_and_the_rows_pass_the_registry_check():
    from tools import factory_channels as C
    google = D.rows('google', 'GOOGLE_API_KEY_3', ['gemini-3.5-flash-lite', 'gemma-4-31b-it'])
    assert google[0]['group'] != google[1]['group']                 # Google: a quota per model and key
    assert [r['tier'] for r in google] == ['main', 'small']
    free = D.rows('openrouter', 'OPENROUTER_API_KEY_2', ['nvidia/nemotron-3-ultra:free', 'cohere/north-mini-code:free'])
    assert free[0]['group'] == free[1]['group']                     # OpenRouter: one free pool per key
    assert D.rows('google', 'GEMINI_API_KEY', ['gemini-9-ultra-paid']) == []   # unknown limits: no row, no zero
    C.validate(google + free)


def test_the_merge_adds_new_rows_and_keeps_every_existing_one_as_it_is():
    old = [dict(id='g-3-5-flash-lite', model='google/gemini-3.5-flash-lite', key_env='GEMINI_API_KEY', group='a',
                rpd=400, tpm=250000, verified=True)]
    new = D.rows('google', 'GEMINI_API_KEY', ['gemini-3.5-flash-lite']) + D.rows('google', 'GOOGLE_API_KEY_3',
                                                                               ['gemini-3.5-flash-lite'])
    merged = D.merge(old, new)
    assert merged[0] == old[0]                                  # the hand-made row stays as it is (rpd 400)
    assert len(merged) == 2                                     # same model and key: not added twice
    assert merged[1]['key_env'] == 'GOOGLE_API_KEY_3'


# ---- the I/O part, with the network injected: get(url, headers) -> (status, listing | None),
# probe(row, key) -> HTTP status of one tiny call of that row's model with that key


def fake_get(listings):
    calls = []

    def get(url, headers):
        calls.append((url, headers))
        for prefix, data in listings.items():
            if url.startswith(prefix):
                return 200, data
        return 404, None
    get.calls = calls
    return get


HAND_ROW = dict(id='g-3-5-flash-lite', model='google/gemini-3.5-flash-lite', key_env='GEMINI_API_KEY',
                group='google-ai-studio-3.5-flash-lite', tier='main', rpm=15, tpm=250000, rpd=400, verified=True)


def test_the_key_names_of_an_env_file_are_read_without_values():
    text = 'GEMINI_API_KEY=abc\n# OPENROUTER_API_KEY=old\nexport GOOGLE_API_KEY_3="def"\nHOME=/x\n\nbroken line\n'
    assert D.key_names(text) == ['GEMINI_API_KEY', 'GOOGLE_API_KEY_3']


def test_a_third_key_adds_its_verified_rows_and_the_capacity_grows():
    from tools import factory_channels as C
    registry = {'channels': [dict(HAND_ROW)]}
    report = D.discover(registry, {'GEMINI_API_KEY': 'k1', 'GOOGLE_API_KEY_3': 'k3'},
                        get=fake_get({D.GOOGLE_LIST: GOOGLE}), probe=lambda row, key: 200)
    pairs = {(c['model'], c['key_env']) for c in registry['channels']}
    assert ('google/gemini-3.5-flash-lite', 'GOOGLE_API_KEY_3') in pairs
    assert ('google/gemma-4-31b-it', 'GOOGLE_API_KEY_3') in pairs
    assert ('google/gemma-4-31b-it', 'GEMINI_API_KEY') in pairs           # a model the first key had not listed yet
    assert registry['channels'][0] == HAND_ROW                             # the hand-made row stays as it is
    assert all(c['verified'] is True for c in registry['channels'])
    assert sum(c['rpd'] for c in registry['channels']) > HAND_ROW['rpd']  # the capacity grew
    assert len(report['added']) == 3 and report['failed'] == {} and report['errors'] == {}
    C.validate(registry['channels'])


def test_a_row_whose_probe_fails_is_not_written_and_a_listing_error_is_reported():
    registry = {'channels': []}
    report = D.discover(registry, {'GOOGLE_API_KEY_3': 'k3', 'OPENROUTER_API_KEY': 'k4'},
                        get=fake_get({D.GOOGLE_LIST: GOOGLE}),
                        probe=lambda row, key: 403 if 'gemma' in row['model'] else 200)
    assert [c['model'] for c in registry['channels']] == ['google/gemini-3.5-flash-lite']
    assert list(report['failed'].values()) == [403]
    assert report['errors'] == {'OPENROUTER_API_KEY': 404}


def test_names_without_a_provider_are_never_listed_and_the_key_stays_out_of_the_url():
    get = fake_get({D.GOOGLE_LIST: GOOGLE})
    D.discover({'channels': []}, {'HOME': 'x', 'GEMINI_API_KEY': 'secret-k1'}, get=get, probe=lambda r, k: 200)
    assert len(get.calls) == 1
    url, headers = get.calls[0]
    assert 'secret-k1' not in url and 'secret-k1' in ' '.join(headers.values())


def test_a_shared_pool_keeps_its_group_and_a_new_key_gets_only_the_trusted_models():
    """OpenRouter: one pool of free calls per key. Another model of the same key adds no capacity and is not taken; a
    new key (a new pool) gets the models the registry already trusts for the provider, never an untried one."""
    old = dict(id='or-north', model='openrouter/cohere/north-mini-code:free', key_env='OPENROUTER_API_KEY',
               group='openrouter-free', tier='escalation', rpm=20, tpm=100000, rpd=50, verified=True)
    listing = {'data': [{'id': 'vendor%d/model-%d:free' % (i, i)} for i in range(8)]
               + [{'id': 'cohere/north-mini-code:free'}]}
    registry, probed = {'channels': [dict(old)]}, []
    report = D.discover(registry, {'OPENROUTER_API_KEY': 'k', 'OPENROUTER_API_KEY_2': 'k2'},
                        get=fake_get({D.OPENROUTER_LIST: listing}),
                        probe=lambda row, key: probed.append(row['id']) or 200)
    assert len(probed) == 1 and len(report['added']) == 1
    new = registry['channels'][1]
    assert new['model'] == old['model'] and new['key_env'] == 'OPENROUTER_API_KEY_2'
    assert new['group'] != old['group']                                   # a new key is a new pool


def test_small_gemma_models_never_become_channels():
    assert D.google_models({'models': [{'name': 'models/gemma-4-%s-it' % size,
                                        'supportedGenerationMethods': ['generateContent']}
                                       for size in ('1b', '4b', '12b', '26b-a4b', '31b')]}) == [
        'gemma-4-26b-a4b-it', 'gemma-4-31b-it']
