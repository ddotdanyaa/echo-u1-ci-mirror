# Factory status (generated, structured data only)

Generated: 2026-11-21T15:01:47Z
Source commit: shabeb76b5112a5

## Commits (sha, time)
- shabeb76b51 2026-11-21T17:58:54+03:00
- shab23d4d2a 2026-11-21T15:53:59+03:00
- sha3afe6e29 2026-11-21T15:49:08+03:00
- sha4ce1d324 2026-11-21T15:43:46+03:00
- sha3aa2e980 2026-11-21T15:42:35+03:00
- shaa6a06179 2026-11-21T15:39:50+03:00
- sha48e62bb7 2026-11-21T15:39:10+03:00
- sha6e6721b7 2026-11-21T15:34:26+03:00
- sha05ec65e6 2026-11-21T15:34:25+03:00
- sha560f1dcc 2026-11-21T15:30:15+03:00
- sha0226ae1e 2026-11-21T15:30:12+03:00
- sha8b1accf1 2026-11-21T15:29:04+03:00
- shaa80df2ac 2026-11-21T15:27:53+03:00
- sha7a868d1a 2026-11-21T15:24:27+03:00
- shafc542b90 2026-11-21T15:22:01+03:00
- shab241ed09 2026-11-21T15:21:32+03:00
- sha6e22230b 2026-11-21T15:21:31+03:00
- shae8dc738b 2026-11-21T15:21:05+03:00
- sha3ba51688 2026-11-21T15:21:04+03:00
- sha5b6793f0 2026-11-21T15:21:04+03:00

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 110 |
| coded | 60 |
| found_in_backlog | unknown |
| gate_pass | 31 |
| known_to_loop | 244 |
| promoted | 29 |
| ready | 8 |
| reviewed | 47 |
| triaged | 88 |

Side counters: blocked=2, parked=0, requeued=2
Tasks now: BLOCKED=2, DONE=64, FAILED=44, PROMOTED=5, READY=8, RUNNING=1
Accepted: 5
Promoted: 29
Free RAM, GB: 1.69
Telemetry rows: 11998 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 659 | 4094528 | 282514 | 38 | 0 | 38 |
| google/gemini-3.5-flash-lite | 964 | 6407820 | 322240 | 22 | 0 | 22 |
| google/gemini-3.6-flash | 99 | 383453 | 17290 | 39 | 1 | 39 |
| google/gemini-3.8-flash | 7 | 21237 | 15 | 4 | 2 | 4 |
| google/gemma-4-26b-a4b-it | 116 | 278391 | 30818 | 60 | 0 | 60 |
| google/gemma-4-31b-it | 132 | 144472 | 4666 | 92 | 0 | 92 |
| openrouter/cohere/north-mini-code:free | 22 | 69376 | 10273 | 5 | 0 | 6 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 95 | 551204 | 147387 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 437 | 0 |
| gate | 1751 | 0 |
| infra | 293 | 0 |
| loop | 2338 | 0 |
| other | 1520 | 0 |
| promote | 40 | 0 |
| review | 725 | 392 |
| run | 4757 | 1702 |
| triage | 137 | 0 |

## Channels (model ids)
- 1db4ab-gemini-3-8-flash
- g-3-1-flash-lite
- g-3-5-flash-lite
- g-3-6-flash
- g-gemma-4-26b
- g-gemma-4-31b
- google/gemini-3.1-flash-lite
- google/gemini-3.5-flash-lite
- google/gemini-3.6-flash
- google/gemini-3.8-flash
- google/gemma-4-26b-a4b-it
- google/gemma-4-31b-it
- k2-g-3-1-flash-lite
- k2-g-3-5-flash-lite
- k2-g-3-6-flash
- k2-g-gemma-4-26b
- k2-g-gemma-4-31b
- openrouter/cohere/north-mini-code:free
- openrouter/nvidia/nemotron-3-ultra-550b-a55b:free
- or-nemotron-3-ultra
- or-north-mini-code

## Published files
Modules: 24
Tests in the cloud: 114
Tests not in the cloud: 44
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_cannot_scope.py (env-path)
- tests/test_factory_class_cases.py (backlog-id, call-word, long-run, path, phone)
- tests/test_factory_closures.py (backlog-id)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- <redacted-name> (backlog-id)
- <redacted-name> (backlog-id)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (dependency)
- tests/test_factory_light_squeezed.py (path)
- tests/test_factory_loop_answers.py (backlog-id, call-word)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (dependency)
- tests/test_factory_loop_channel_brake.py (long-run)
- tests/test_factory_loop_d8c.py (dependency)
- tests/test_factory_loop_d8d.py (backlog-id, call-word, key, long-run, phone)
- <redacted-name> (backlog-id)
- tests/test_factory_loop_parents.py (dependency)
- tests/test_factory_loop_r7.py (dependency)
- tests/test_factory_loop_r7b.py (dependency)
- tests/test_factory_loop_selffix.py (call-word, phone)
- tests/test_factory_metrics.py (owner-words)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_paid_critic.py (env-path, key, url)
- tests/test_factory_paid_critic_span.py (key)
- tests/test_factory_path.py (dependency)
- tests/test_factory_port_wiring.py (dependency)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_registry.py (backlog-id, owner-words)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_status.py (dependency)
- tests/test_factory_survive.py (path, pid-port, user-path)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone, tunnel-host)
- tests/test_factory_triage_example.py (dependency)

## Cloud test matrix
Not read yet.
