# Factory status (generated, structured data only)

Generated: 2026-11-21T12:26:04Z
Source commit: sha7a868d1a67ed

## Commits (sha, time)
- sha7a868d1a 2026-11-21T15:24:27+03:00
- shab241ed09 2026-11-21T15:21:32+03:00
- sha6e22230b 2026-11-21T15:21:31+03:00
- shae8dc738b 2026-11-21T15:21:05+03:00
- sha3ba51688 2026-11-21T15:21:04+03:00
- sha5b6793f0 2026-11-21T15:21:04+03:00
- sha37ae5bc6 2026-11-21T15:21:03+03:00
- shad3018729 2026-11-21T15:17:44+03:00
- shad1418318 2026-11-21T15:17:26+03:00
- sha9868c0b1 2026-11-21T15:16:26+03:00
- shab80664cc 2026-11-21T15:15:37+03:00
- shaa6fdd2d9 2026-11-21T15:14:41+03:00
- sha66c86faa 2026-11-21T15:14:23+03:00
- sha653c9abd 2026-11-21T15:13:38+03:00
- shaf5a8ff4b 2026-11-21T15:11:00+03:00
- sha225d27f5 2026-11-21T15:10:06+03:00
- shaf8e8df54 2026-11-21T15:10:02+03:00
- shac3cffd2b 2026-11-21T15:09:49+03:00
- shac53c0bd3 2026-11-21T15:09:04+03:00
- sha8dc5239a 2026-11-21T15:05:25+03:00

## Funnel
| step | count |
|---|---|
| accepted | 4 |
| claimed | 104 |
| coded | 56 |
| found_in_backlog | unknown |
| gate_pass | 30 |
| known_to_loop | 238 |
| promoted | 28 |
| ready | 8 |
| reviewed | 40 |
| triaged | 82 |

Side counters: blocked=2, parked=0, requeued=2
Tasks now: BLOCKED=2, DONE=64, FAILED=34, PROMOTED=4, READY=8
Accepted: 4
Promoted: 28
Free RAM, GB: 2.65
Telemetry rows: 10457 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 597 | 3750535 | 270172 | 31 | 0 | 31 |
| google/gemini-3.5-flash-lite | 879 | 5915310 | 309329 | 21 | 0 | 21 |
| google/gemini-3.6-flash | 82 | 299985 | 14692 | 35 | 1 | 35 |
| google/gemini-3.8-flash | 7 | 21237 | 15 | 4 | 2 | 4 |
| google/gemma-4-26b-a4b-it | 104 | 261085 | 30548 | 51 | 0 | 51 |
| google/gemma-4-31b-it | 121 | 140353 | 4594 | 82 | 0 | 82 |
| openrouter/cohere/north-mini-code:free | 22 | 69376 | 10273 | 5 | 0 | 6 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 95 | 551204 | 147387 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 435 | 0 |
| gate | 1559 | 0 |
| infra | 214 | 0 |
| loop | 2094 | 0 |
| other | 1185 | 0 |
| promote | 39 | 0 |
| review | 606 | 330 |
| run | 4210 | 1577 |
| triage | 115 | 0 |

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
Tests not in the cloud: 41
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_class_cases.py (backlog-id, call-word, long-run, path, phone)
- tests/test_factory_closures.py (backlog-id)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
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
