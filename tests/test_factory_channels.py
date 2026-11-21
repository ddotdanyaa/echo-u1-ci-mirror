"""Channel layer of the factory: token reservation, structural error classes, cooling.

Fake Kilo output only; no model or network is ever called.
"""
import json
import math

import pytest

from tools import factory_channels as C

CH = dict(id='a', group='p', model='google/x', key_env='KEY', tpm=100000, rpd=50)


def err(status=None, name='APIError', message='boom', body=None):
    data = {'message': message}
    if status is not None:
        data['statusCode'] = status
    if body is not None:
        data['responseBody'] = body if isinstance(body, str) else json.dumps(body)
    return json.dumps({'type': 'error', 'error': {'name': name, 'data': data}}).encode()


def quota_body(code, quota_id=None, retry=None, status='RESOURCE_EXHAUSTED', message='quota'):
    details = []
    if quota_id:
        details.append({'@type': 'type.googleapis.com/google.rpc.QuotaFailure',
                        'violations': [{'quotaId': quota_id}]})
    if retry:
        details.append({'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': retry})
    return {'error': {'code': code, 'status': status, 'message': message, 'details': details}}


def test_reservation_comes_from_prompt_length_not_the_old_formula():
    assert C.estimate_tokens(0) == C.KILO_OVERHEAD_TOKENS
    assert C.estimate_tokens(7000) == math.ceil(7000 / 3.5) + C.KILO_OVERHEAD_TOKENS
    assert C.estimate_tokens(20000) > C.estimate_tokens(7000)
    assert C.estimate_tokens(C.PROMPT_LIMIT_CHARS) < 40000  # old (budget+8192)*5 was 185 960
    assert 7000 <= C.KILO_OVERHEAD_TOKENS <= 8000    # measured by the canary, not the old 13 000 guess


def test_reconcile_returns_the_surplus_to_the_channel():
    state = {}
    at = C.reserve(state, CH, 30000, now=100, requests=5)
    C.reconcile(state, CH, at, 30000, 12000, requests=5, actual_requests=2)
    group = state['p']
    assert sum(n for _, n in group['minute']) == 12000
    assert len(group['request_times']) == 2
    C.choose([CH], state, 80000, {'KEY': 'k'}, now=101)  # 12000 + 80000 fits in 100000


def test_choose_reports_reason_and_wait_when_tpm_window_is_full():
    state = {}
    C.reserve(state, CH, 90000, now=100)
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([CH], state, 20000, {'KEY': 'k'}, now=110)
    assert caught.value.reason == 'tpm_window' and 40 <= caught.value.wait_s <= 60


def test_reservation_larger_than_channel_tpm_is_reported_as_never_fitting():
    small = dict(CH, tpm=16000)
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([small], {}, 29000, {'KEY': 'k'}, now=1)
    assert caught.value.reason == 'reservation_exceeds_tpm'


def test_rpm_is_respected_when_the_channel_sets_it():
    ch = dict(CH, rpm=5)
    state = {}
    C.reserve(state, ch, 100, now=100, requests=5)
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([ch], state, 100, {'KEY': 'k'}, now=110, requests=1)
    assert caught.value.reason == 'rpm'
    assert C.choose([ch], state, 100, {'KEY': 'k'}, now=161, requests=1)['id'] == 'a'


def test_cool_may_be_shorter_than_a_minute_when_the_provider_says_so():
    state = {}
    C.cool(state, CH, now=100, seconds=7)
    assert state['p']['cool_until'] == 107


# ---- classification: structure only -----------------------------------------------------------

def test_bad_request_invalid_key_is_key_invalid():
    body = quota_body(400, status='INVALID_ARGUMENT', message='API key not valid. Please pass a valid API key.')
    body['error']['details'] = [{'@type': 'type.googleapis.com/google.rpc.ErrorInfo', 'reason': 'API_KEY_INVALID'}]
    info = C.classify(err(400, body=body), b'', 1)
    assert info['kind'] == 'key_invalid' and info['status'] == 400


def test_forbidden_and_location_text_are_region():
    assert C.classify(err(403, message='PERMISSION_DENIED'), b'', 1)['kind'] == 'region'
    assert C.classify(err(400, message='User location is not supported for the API use.'), b'', 1)['kind'] == 'region'


def test_rate_limit_per_minute_uses_retry_delay():
    info = C.classify(err(429, body=quota_body(429, 'GenerateContentRequestsPerMinutePerProjectPerModel', '34s')), b'', 1)
    assert info['kind'] == 'rate_minute' and info['retry_after_s'] == 34


def test_bare_rate_limit_cools_sixty_seconds():
    info = C.classify(err(429), b'', 1)
    assert info['kind'] == 'rate_minute' and info['retry_after_s'] == 60


def test_rate_limit_per_day_ignores_the_misleading_retry_delay(monkeypatch):
    monkeypatch.setattr(C.time, 'time', lambda: utc(2026, 11, 19, 12, 0))
    body = quota_body(429, 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', '3s')
    info = C.classify(err(429, body=body), b'', 1)
    assert info['kind'] == 'rate_day'
    assert info['retry_after_s'] == 20 * 3600  # PST midnight, the 3 s retryDelay is ignored


def test_server_error_and_apierror_without_code_are_transient():
    assert C.classify(err(503), b'', 1)['kind'] == 'transient'
    assert C.classify(err(None, name='APIError'), b'', 1)['kind'] == 'transient'


def test_rate_limit_text_inside_a_successful_answer_is_not_an_error():
    text = {'type': 'text', 'part': {'text': 'the docs say: 429 RESOURCE_EXHAUSTED rate limit; 403 PERMISSION_DENIED'}}
    tool = {'type': 'tool_use', 'part': {'input': 'status 503 Internal Server Error API_KEY_INVALID'}}
    out = '\n'.join(json.dumps(e) for e in (text, tool)).encode()
    assert C.classify(out, b'', 0)['kind'] == 'ok'
    # even with a nonzero code the stdout payload is never grepped
    assert C.classify(out, b'', 1)['kind'] == 'unknown'


def test_stderr_text_is_the_only_fallback_when_there_is_no_error_event():
    assert C.classify(b'', b'HTTP 429 Too Many Requests', 1)['kind'] == 'rate_minute'
    assert C.classify(b'', b'worker-timeout', 124)['kind'] == 'timeout'
    assert C.classify(b'', b'unsafe launcher', 125)['kind'] == 'launcher'


# ---- applying a failure to the checkpoint state -------------------------------------------------

def test_key_invalid_kills_the_channel_until_the_key_changes():
    state = {}
    C.apply_failure(state, CH, {'kind': 'key_invalid'}, env={'KEY': 'old'}, now=100)
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([CH], state, 100, {'KEY': 'old'}, now=101)
    assert caught.value.reason == 'dead'
    assert C.choose([CH], state, 100, {'KEY': 'new'}, now=101)['id'] == 'a'


def test_region_and_rate_failures_cool_the_group():
    state = {}
    out = C.apply_failure(state, CH, {'kind': 'region'}, env={'KEY': 'k'}, now=100)
    assert out['cool_s'] == 3600 and state['p']['cool_until'] == 3700
    out = C.apply_failure(state, CH, {'kind': 'rate_minute', 'retry_after_s': 34}, env={'KEY': 'k'}, now=100)
    assert out['cool_s'] == 34
    assert state['p']['cool_until'] == 3700  # never shortens a longer cooling


# ---- review round: stderr text, daily reset without tzdata, more classes ---------------------------

@pytest.mark.parametrize("line", ["    at run (index.js:429:15)", "at x (file.js:403:9)", "at y (index.js:512:3)",
                                  "Error: spawn failed at /app/main.js:500:1"])
def test_stack_line_numbers_are_not_http_statuses(line):
    assert C.classify(b'', line.encode(), 1)['kind'] == 'unknown'


@pytest.mark.parametrize("text,kind", [("HTTP 429 Too Many Requests", 'rate_minute'), ("statusCode: 503", 'transient'),
                                       ("request failed, status 403", 'region'), ("error code 402", 'balance')])
def test_status_next_to_http_words_is_still_read(text, kind):
    assert C.classify(b'', text.encode(), 1)['kind'] == kind


def utc(*args):
    import datetime
    return datetime.datetime(*args, tzinfo=datetime.timezone.utc).timestamp()


def test_daily_reset_is_midnight_pacific_without_tzdata():
    assert C.seconds_to_daily_reset(utc(2026, 11, 19, 12, 0)) == 20 * 3600   # PST, local 04:00
    assert C.seconds_to_daily_reset(utc(2026, 7, 1, 12, 0)) == 19 * 3600     # PDT, local 05:00
    assert C.seconds_to_daily_reset(utc(2026, 3, 8, 9, 59)) == 22 * 3600 + 60  # still PST, local 01:59
    assert C.seconds_to_daily_reset(utc(2026, 3, 8, 10, 0)) == 21 * 3600     # PDT starts: local 03:00
    assert C.seconds_to_daily_reset(utc(2026, 11, 1, 8, 59)) == 22 * 3600 + 60  # PDT until 09:00 UTC: local 01:59


OR = dict(id='o', group='or', model='openrouter/x:free', key_env='KEY', tpm=100000, rpd=2)
GO = dict(CH, rpd=2)
# live 19.11 20:03 (the user id cut): OpenRouter's daily refusal of its free models names its own reset time
OR_DAY = ('{"error":{"message":"Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model '
          'requests per day","code":429,"metadata":{"headers":{"X-RateLimit-Limit":"50","X-RateLimit-Remaining":"0",'
          '"X-RateLimit-Reset":"%d"}}}}')


def test_each_provider_has_its_own_quota_day():
    """OpenRouter resets at 00:00 UTC, Gemini at midnight Pacific (live 20.11 03:00: both on the Pacific clock)."""
    at = utc(2026, 11, 20, 0, 1)                                          # 03:01 Moscow
    assert C.seconds_to_daily_reset(at, model='openrouter/x:free') == 24 * 3600 - 60
    assert C.seconds_to_daily_reset(at, model='google/x') == 7 * 3600 + 59 * 60      # PST 16:01 on 19.11
    assert C.quota_day('openrouter/x:free', at) == (utc(2026, 11, 20, 0, 0), utc(2026, 11, 21, 0, 0))
    assert C.quota_day('google/x', at)[0] == utc(2026, 11, 19, 8, 0)


def test_the_day_window_counts_from_the_providers_midnight_not_the_last_twenty_four_hours():
    late = {'or': {'request_times': [utc(2026, 11, 19, 23, 30)] * 2}, 'p': {'request_times': [utc(2026, 11, 19, 23, 30)] * 2}}
    with pytest.raises(C.ChannelUnavailable) as caught:                   # the same OpenRouter day: used up
        C.choose([OR], late, 10, {'KEY': 'k'}, now=utc(2026, 11, 19, 23, 45))
    assert caught.value.reason == 'rpd' and caught.value.wait_s == 15 * 60          # until 00:00 UTC
    assert C.choose([OR], late, 10, {'KEY': 'k'}, now=utc(2026, 11, 20, 0, 30))['id'] == 'o'   # its new day
    with pytest.raises(C.ChannelUnavailable) as caught:                   # still the same Pacific day for Gemini
        C.choose([GO], late, 10, {'KEY': 'k'}, now=utc(2026, 11, 20, 0, 30))
    assert caught.value.reason == 'rpd' and caught.value.wait_s == 7 * 3600 + 30 * 60
    assert C.choose([GO], late, 10, {'KEY': 'k'}, now=utc(2026, 11, 20, 8, 0))['id'] == 'a'      # Pacific midnight


def test_a_daily_rate_limit_cools_until_the_reset_the_provider_names(monkeypatch):
    now = utc(2026, 11, 19, 17, 3)
    monkeypatch.setattr(C.time, 'time', lambda: now)
    info = C.classify(err(429, body=OR_DAY % (utc(2026, 11, 20, 0, 0) * 1000)), b'', 1)
    assert info['kind'] == 'rate_day' and info['retry_after_s'] == 6 * 3600 + 57 * 60
    state = {}
    assert C.apply_failure(state, OR, info, now=now) == {'action': 'cool', 'cool_s': 6 * 3600 + 57 * 60}
    assert state['or']['cool_until'] == utc(2026, 11, 20, 0, 0)
    stale = C.classify(err(429, body=OR_DAY % ((now - 5) * 1000)), b'', 1)  # a reset in the past is not believed
    assert 'reset_at' not in stale and C.apply_failure({}, OR, stale, now=now)['cool_s'] == 6 * 3600 + 57 * 60


def test_a_daily_rate_limit_without_a_named_reset_cools_until_the_channels_own_midnight():
    info = {'kind': 'rate_day', 'retry_after_s': 99999}                   # the classifier knows no provider
    assert C.apply_failure({}, OR, info, now=utc(2026, 11, 19, 22, 0))['cool_s'] == 2 * 3600
    assert C.apply_failure({}, GO, info, now=utc(2026, 11, 19, 22, 0))['cool_s'] == 10 * 3600
    # the first hour of the provider's day: its counter may lag its clock, a quarter of an hour, not the whole day
    assert C.apply_failure({}, OR, info, now=utc(2026, 11, 20, 0, 10))['cool_s'] == C.DAY_GRACE_COOL_S


def test_classes_payment_notfound_timeout():
    assert C.classify(err(402, message='negative balance'), b'', 1)['kind'] == 'balance'
    assert C.classify(err(404, message='model not found'), b'', 1)['kind'] == 'model_missing'
    assert C.classify(err(408), b'', 1)['kind'] == 'transient'


def test_balance_cools_long_and_missing_model_kills_the_channel():
    state = {}
    assert C.apply_failure(state, CH, {'kind': 'balance'}, env={'KEY': 'k'}, now=0)['cool_s'] == 6 * 3600
    state = {}
    C.apply_failure(state, CH, {'kind': 'model_missing'}, env={'KEY': 'k'}, now=0)
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([CH], state, 100, {'KEY': 'k'}, now=1)
    assert caught.value.reason == 'dead'



# ---- round 3 ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,kind", [("HTTP/1.1 404 Not Found", 'model_missing'), ("HTTP/2 429", 'rate_minute'),
                                       ("fetch failed: status code 503", 'transient')])
def test_http_version_prefix_and_phrases_are_read(text, kind):
    assert C.classify(b'', text.encode(), 1)['kind'] == kind


@pytest.mark.parametrize("text", ["at barcode 429 scan", "mycode 503 failed", "at f (x.js:12) code 429:15",
                                  "statusfoo 404", "ENOENT status 4290"])
def test_status_words_need_a_boundary_and_no_position_suffix(text):
    assert C.classify(b'', text.encode(), 1)['kind'] == 'unknown'


def test_reservation_counts_the_files_the_model_will_read():
    assert C.estimate_tokens(1000, 7000) == C.estimate_tokens(1000) + 2000
    assert C.estimate_tokens(1000, 0) == C.estimate_tokens(1000)


def test_next_wait_is_the_soonest_channel_that_can_serve():
    a = dict(CH, id='a', group='ga')
    b = dict(CH, id='b', group='gb', model='google/y')
    state = {}
    C.cool(state, a, now=100, seconds=300)
    assert C.next_wait([a, b], state, 1000, {'KEY': 'k'}, now=110) == 0
    C.cool(state, b, now=100, seconds=40)
    assert 25 <= C.next_wait([a, b], state, 1000, {'KEY': 'k'}, now=110) <= 31
    assert C.next_wait([], state, 1000, {'KEY': 'k'}, now=110) is None



def test_a_missing_model_is_dead_for_six_hours_then_probed_again():
    state = {}
    C.apply_failure(state, CH, {'kind': 'model_missing'}, env={'KEY': 'k'}, now=1000)
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([CH], state, 100, {'KEY': 'k'}, now=1000 + 3600)
    assert caught.value.reason == 'dead'
    assert C.choose([CH], state, 100, {'KEY': 'k'}, now=1000 + 6 * 3600 + 1)['id'] == 'a'   # the retry probe
    state = {}
    C.apply_failure(state, CH, {'kind': 'key_invalid'}, env={'KEY': 'k'}, now=1000)   # a bad key has no TTL
    with pytest.raises(C.ChannelUnavailable):
        C.choose([CH], state, 100, {'KEY': 'k'}, now=1000 + 30 * 3600)



def test_a_multi_step_call_needs_three_free_requests_for_both_rpd_and_rpm():
    ch = dict(CH, rpd=10, rpm=5)
    state = {}
    C.reserve(state, ch, 10, now=100, requests=8)             # used = rpd - 2
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([ch], state, 10, {'KEY': 'k'}, now=200, requests=3)
    assert caught.value.reason == 'rpd'
    state = {}
    C.reserve(state, ch, 10, now=100, requests=3)             # 3 of rpm=5 in the last minute: 2 free
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([ch], state, 10, {'KEY': 'k'}, now=110, requests=3)
    assert caught.value.reason == 'rpm'
    assert C.choose([dict(CH, rpd=3)], {}, 10, {'KEY': 'k'}, now=1, requests=3)['id'] == 'a'   # all 3 free: allowed




def test_the_wait_of_a_dead_channel_is_the_time_left_but_at_most_an_hour():
    fp = C._fingerprint({'KEY': 'k'}, CH)
    soon = {'dead': {'a': {'key': fp, 'since': 0, 'until': 1000 + 120}}}
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([CH], soon, 100, {'KEY': 'k'}, now=1000)
    assert 100 <= caught.value.wait_s <= 121
    late = {'dead': {'a': {'key': fp, 'since': 0, 'until': 1000 + 5 * 3600}}}
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([CH], late, 100, {'KEY': 'k'}, now=1000)
    assert caught.value.wait_s == 3600



def test_a_channel_with_tiny_own_limits_still_works_while_it_is_free():
    ch = dict(CH, rpm=2, rpd=2)
    state = {}
    assert C.choose([ch], state, 10, {'KEY': 'k'}, now=100, requests=3)['id'] == 'a'    # need = min(3, rpd, rpm) = 2
    C.reserve(state, ch, 10, now=100, requests=2)
    with pytest.raises(C.ChannelUnavailable) as caught:                                    # no IndexError on an empty window
        C.choose([ch], state, 10, {'KEY': 'k'}, now=110, requests=3)
    assert caught.value.reason in ('rpm', 'rpd')
    assert C.choose([dict(CH, rpm=1, rpd=1)], {}, 10, {'KEY': 'k'}, now=1, requests=3)['id'] == 'a'


def test_dead_records_without_a_reason_are_a_bad_key_and_garbage_expires_at_once():
    fp = C._fingerprint({'KEY': 'k'}, CH)
    legacy = {'dead': {'a': {'key': fp, 'since': 1000}}}                  # no reason, no until: treated as key_invalid
    with pytest.raises(C.ChannelUnavailable):
        C.choose([CH], legacy, 100, {'KEY': 'k'}, now=1000 + 90 * 3600)
    junk_until = {'dead': {'a': {'key': fp, 'reason': 'model_missing', 'since': 1000, 'until': 'soon'}}}
    assert C.choose([CH], junk_until, 100, {'KEY': 'k'}, now=1001)['id'] == 'a'
    junk_since = {'dead': {'a': {'key': fp, 'reason': 'model_missing', 'since': 'long ago'}}}
    assert C.choose([CH], junk_since, 100, {'KEY': 'k'}, now=1001)['id'] == 'a'
    ttl = {'dead': {'a': {'key': fp, 'reason': 'model_missing', 'since': 1000}}}      # reason known, no until: since + 6 h
    with pytest.raises(C.ChannelUnavailable):
        C.choose([CH], ttl, 100, {'KEY': 'k'}, now=1000 + 3600)
    assert C.choose([CH], ttl, 100, {'KEY': 'k'}, now=1000 + 6 * 3600 + 1)['id'] == 'a'


def test_a_dead_mark_with_until_none_never_expires():
    key = C._fingerprint({'KEY': 'k'}, CH)
    state = {'dead': {'a': {'key': key, 'reason': 'key_invalid', 'until': None}}}
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([CH], state, 10, {'KEY': 'k'}, now=10 ** 9)
    assert caught.value.reason == 'dead'
    assert C._dead_until({'reason': 'model_missing', 'since': 100, 'until': None}) == 100 + C.MODEL_MISSING_TTL_S


def test_usable_channels_are_the_live_ones_with_a_key():
    other = dict(CH, id='b', group='q', key_env='OTHER')
    key = C._fingerprint({'OTHER': 'z'}, other)
    state = {'dead': {'b': {'key': key, 'reason': 'balance', 'until': 500}}}
    env = {'KEY': 'k', 'OTHER': 'z'}
    assert [c['id'] for c in C.usable([CH, other], state, env, now=100)] == ['a']
    assert [c['id'] for c in C.usable([CH, other], state, env, now=600)] == ['a', 'b']
    assert C.usable([CH, other], {}, {'KEY': 'k'}, now=1) == [CH]


def test_booking_two_requests_is_visible_in_the_quota_state():
    ch = dict(CH, rpm=2, rpd=2)
    state = {}
    C.reserve(state, ch, 10, now=100, requests=2)
    assert len(state['p']['request_times']) == 2


# ---- a channel whose last calls all failed (live 20.11: g-gemma-4-31b failed 9 calls in a row over 5 h and kept
# getting traffic; its overload series was forgotten after 30 min and a "transient" without a code cooled nothing) ----

def test_three_failed_calls_in_a_row_cool_the_channel_with_reason_and_term():
    state = {}
    assert C.note_outcome(state, CH, False, now=100)['action'] == 'none'
    assert C.note_outcome(state, CH, False, now=110)['action'] == 'none'
    out = C.note_outcome(state, CH, False, now=120)
    assert out == {'action': 'cool', 'cool_s': C.STREAK_COOL_S, 'reason': 'fail_streak'}
    assert C.STREAK_FAILS == 3 and C.STREAK_COOL_S == 600
    assert state['p']['cool_until'] == 120 + C.STREAK_COOL_S
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([CH], state, 10, {'KEY': 'k'}, now=121)
    assert caught.value.reason == 'cool'


def test_every_further_failure_of_the_series_doubles_the_term_up_to_the_ceiling():
    state = {}
    terms = [C.note_outcome(state, CH, False, now=100 * k)['cool_s'] for k in range(1, 11)]
    assert terms[:3] == [0, 0, 600]
    assert terms[3:6] == [1200, 2400, 3600]                 # the probe after a cooling failed again: twice as long
    assert max(terms) == C.STREAK_COOL_MAX_S == 3600        # never longer than the ceiling (21.11: was 14400, 4800)


def test_a_successful_call_resets_the_series():
    state = {}
    C.note_outcome(state, CH, False, now=100)
    C.note_outcome(state, CH, False, now=110)
    C.note_outcome(state, CH, True, now=120)
    assert C.note_outcome(state, CH, False, now=130)['action'] == 'none'
    assert C.note_outcome(state, CH, False, now=140)['action'] == 'none'
    assert C.note_outcome(state, CH, False, now=150)['cool_s'] == 600     # a new series starts at the base term
    C.note_outcome(state, CH, True, now=900)
    assert C.note_outcome(state, CH, False, now=910)['action'] == 'none'


def test_in_a_group_of_several_models_the_model_is_cooled_not_the_group():
    other = dict(CH, id='b', model='google/other')
    state = {}
    for t in (100, 110, 120):
        out = C.note_outcome(state, CH, False, now=t, channels=[CH, other])
    assert out == {'action': 'cool_model', 'cool_s': 600, 'reason': 'fail_streak'}
    assert state['model_cool']['google/x'] == 720
    assert not state['p'].get('cool_until')
    assert C.choose([CH, other], state, 10, {'KEY': 'k'}, now=130)['id'] == 'b'


def test_the_series_is_kept_per_channel():
    other = dict(CH, id='b', group='q')
    state = {}
    C.note_outcome(state, CH, False, now=100)
    C.note_outcome(state, CH, False, now=110)
    assert C.note_outcome(state, other, False, now=120)['action'] == 'none'
    assert C.note_outcome(state, CH, False, now=130)['action'] == 'cool'


def test_a_series_never_parks_the_factory_for_hours_when_no_other_model_is_free():
    other = dict(CH, id='b', group='q', model='google/other')
    state = {'q': {'cool_until': 10 ** 9}}                  # the only other model is cooled for a long time
    terms = [C.note_outcome(state, CH, False, now=100 * k, channels=[CH, other])['cool_s'] for k in range(1, 7)]
    assert terms == [0, 0, 600, 600, 600, 600]              # the base term only: the probe comes back in 10 min
    state = {}                                              # the other model is free: the series doubles
    terms = [C.note_outcome(state, CH, False, now=100 * k, channels=[CH, other])['cool_s'] for k in range(1, 6)]
    assert terms == [0, 0, 600, 1200, 2400]
