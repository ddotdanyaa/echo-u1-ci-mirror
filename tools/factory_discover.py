"""<id>, a new key is one line in the secrets; the registry rows of its free models are made by code: the provider of a key name, the known free models of a provider listing, rows with the known free limits, and a merge that never drops or changes an existing row."""
import hashlib
import re

LIMITS = (
    (r'gemini-3\.5-flash-lite', 15, 250000, 500, 'main'),
    (r'gemini-3\.1-flash-lite', 15, 250000, 500, 'main'),
    (r'gemini-3\.6-flash', 5, 250000, 20, 'escalation'),
    (r'gemini-3\.8-flash', 5, 250000, 20, 'escalation'),
    # Gemma 4 from 26B up only: a 1B-12B model in the small tier would review code (review tries small first)
    (r'gemma-4-(?:2[6-9]|[3-9]\d)b(?:-a\d+b)?-it', 30, 16000, 14400, 'small'),
    (r'[\w.-]+/[\w.-]+:free', 20, 100000, 50, 'escalation'),
)


def _limits(model_id):
    for pattern, rpm, tpm, rpd, tier in LIMITS:
        if re.fullmatch(pattern, model_id):
            return (rpm, tpm, rpd, tier)
    return None


def provider_of(key_name) -> str | None:
    if re.fullmatch(r'(GEMINI|GOOGLE)\w*API_KEY\w*', key_name):
        return 'google'
    if re.fullmatch(r'OPENROUTER\w*KEY\w*', key_name):
        return 'openrouter'
    for prefix in ('GROQ', 'CEREBRAS', 'COHERE'):
        if re.fullmatch(prefix + r'\w*API_KEY\w*', key_name):
            return prefix.lower()
    if re.fullmatch(r'HF_TOKEN\w*|HUGGINGFACE\w*(?:API_KEY|TOKEN)\w*', key_name):
        return 'huggingface'
    return None


def google_models(listing) -> list:
    result = []
    for m in listing.get('models', []):
        if 'generateContent' in m.get('supportedGenerationMethods', []):
            name = m.get('name', '')
            model_id = name.split('/')[-1]
            if _limits(model_id) is not None:
                result.append(model_id)
    return sorted(result)


def openrouter_models(listing) -> list:
    result = []
    for r in listing.get('data', []):
        model_id = r.get('id', '')
        if model_id.endswith(':free') and _limits(model_id) is not None:
            result.append(model_id)
    return sorted(result)


SHARED_FREE_POOL = frozenset(('openrouter',))   # one free quota per key for all its :free models


def rows(provider, key_env, model_ids) -> list:
    """Registry rows of the known free models of one key. The quota group is what the provider counts together:
    Google counts per model and key, OpenRouter one free pool per key. A model without known free limits makes no
    row (an unknown limit is not zero and not a guess). New rows are unverified until a canary call answers."""
    tag = hashlib.sha1(key_env.encode('utf-8')).hexdigest()[:6]
    res = []
    for model_id in model_ids:
        lim = _limits(model_id)
        if lim is None:
            continue
        rpm, tpm, rpd, tier = lim
        short = re.sub(r'[^a-z0-9]+', '-', model_id.lower()).strip('-')
        group = ('%s-%s-free' % (provider, tag) if provider in SHARED_FREE_POOL
                 else '%s-%s-%s' % (provider, tag, short))
        res.append({'id': '%s-%s' % (tag, short), 'model': '%s/%s' % (provider, model_id), 'key_env': key_env,
                    'group': group, 'tier': tier, 'rpm': rpm, 'tpm': tpm, 'rpd': rpd, 'verified': False})
    return res


def merge(old_rows, new_rows) -> list:
    merged = list(old_rows)
    existing_keys = {(r.get('model'), r.get('key_env')) for r in old_rows}
    for nr in new_rows:
        key = (nr.get('model'), nr.get('key_env'))
        if key not in existing_keys:
            merged.append(nr)
            existing_keys.add(key)
    return merged


# ---- the I/O part (<id>): the network is injected, so the same code serves the loop and the tests.
# The coordinator wrote it after 4 factory rounds (20.11 01:02-01:12): every model probed rows that already existed
# and reported model names instead of row ids, though the failing assertion showed exactly that.
GOOGLE_LIST = 'https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000'
OPENROUTER_LIST = 'https://openrouter.ai/api/v1/models'


PROVIDER_LISTS = {
    'openrouter': OPENROUTER_LIST,
    'groq': 'https://api.groq.com/openai/v1/models',
    'cerebras': 'https://api.cerebras.ai/v1/models',
    'cohere': 'https://api.cohere.ai/v1/models',
    'huggingface': 'https://router.huggingface.co/v1/models',
}


def key_names(env_text) -> list:
    """Names of the env file whose provider is known, in file order; the values are never read out."""
    names = []
    for line in (env_text or '').splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[7:].strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name = line.split('=', 1)[0].strip()
        if provider_of(name) is not None and name not in names:
            names.append(name)
    return names


def listing_request(provider, key) -> tuple:
    """(url, headers) of the provider's model listing: the key travels in a header, never in the URL."""
    if provider == 'google':
        return GOOGLE_LIST, {'x-goog-api-key': key}
    if provider == 'openrouter':
        return OPENROUTER_LIST, {'Authorization': 'Bearer ' + key}
    if provider not in PROVIDER_LISTS:
        raise ValueError('unsupported provider')
    return PROVIDER_LISTS[provider], listing_request('openrouter', key)[1]   # the same header as OpenRouter's


def models_of(provider, listing) -> list:
    if provider == 'google':
        return google_models(listing)
    if provider == 'openrouter':
        return openrouter_models(listing)
    if provider == 'cohere':
        return sorted({m['name'] for m in listing.get('models', [])
                       if isinstance(m.get('name'), str) and m['name']
                       and 'chat' in m.get('endpoints', []) and not m.get('is_deprecated', False)})
    if provider in ('groq', 'cerebras', 'huggingface'):
        # These catalogs do not establish free quotas; rows() still requires known limits.
        return sorted({m['id'] for m in listing.get('data', [])
                       if isinstance(m.get('id'), str) and m['id'] and m.get('active', True)})
    return []


MAX_NEW_PER_KEY = 3     # probes per key and run: OpenRouter lists dozens of :free models in one pool of 50 calls a day


def discover(registry, keys, *, get, probe, max_new=MAX_NEW_PER_KEY) -> dict:
    """New rows of every key: listed by the provider, known free limits, one probe call each; only a row whose probe
    answered 200 is written (verified). Rows already in the registry (same model and key) are never probed, changed
    or removed. A key whose provider has one free pool keeps the group its registry rows already have (two groups of
    one pool would count its 50 calls twice). get(url, headers) -> (status, listing or None); probe(row, key) -> HTTP
    status. At most max_new probes per key and run: the rest waits for the next run."""
    report = {'added': [], 'failed': {}, 'errors': {}}
    have = {(r.get('model'), r.get('key_env')) for r in registry['channels']}
    pools = {}
    for r in registry['channels']:
        provider = str(r.get('model', '')).split('/')[0]
        if provider in SHARED_FREE_POOL and r.get('group'):
            pools.setdefault((provider, r.get('key_env')), r['group'])
    for name in sorted(keys):
        provider = provider_of(name)
        if provider is None:
            continue
        url, headers = listing_request(provider, keys[name])
        status, listing = get(url, headers)
        if status != 200 or listing is None:
            report['errors'][name] = status
            continue
        found = models_of(provider, listing)
        if provider in SHARED_FREE_POOL:
            # one pool per key: another model adds no capacity, a new key adds a pool; it gets the models the registry
            # already trusts for this provider, never an untried one (a weak :free model would land in escalation)
            trusted = {str(r.get('model', '')).split('/', 1)[1] for r in registry['channels']
                       if str(r.get('model', '')).split('/')[0] == provider}
            found = [m for m in found if m in trusted]
        probes = 0
        for row in rows(provider, name, found):
            if (row['model'], row['key_env']) in have:
                continue
            if probes >= max_new:
                break
            probes += 1
            row['group'] = pools.get((provider, name), row['group'])
            code = probe(row, keys[name])
            if code == 200:
                row['verified'] = True
                registry['channels'].append(row)
                have.add((row['model'], row['key_env']))
                report['added'].append(row['id'])
            else:
                report['failed'][row['id']] = code
    return report
