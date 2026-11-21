# Factory status (generated, structured data only)

Generated: 2026-11-21T18:19:11Z
Source commit: sha86718ac78ebc

## Commits (sha, time)
- sha86718ac7 2026-11-21T21:17:50+03:00
- shad538a50e 2026-11-21T20:48:21+03:00
- shaa65f87a0 2026-11-21T20:38:22+03:00
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

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 111 |
| coded | 60 |
| found_in_backlog | unknown |
| gate_pass | 31 |
| known_to_loop | 244 |
| promoted | 29 |
| ready | 40 |
| reviewed | 48 |
| triaged | 89 |

Side counters: blocked=4, parked=0, requeued=2
Tasks now: BLOCKED=4, DONE=68, FAILED=3, PROMOTED=5, READY=40, RUNNING=6
Accepted: 5
Promoted: 29
Free RAM, GB: 2.09
Telemetry rows: 13094 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 715 | 4440998 | 295959 | 41 | 0 | 41 |
| google/gemini-3.5-flash-lite | 1014 | 6740830 | 331195 | 23 | 0 | 23 |
| google/gemini-3.6-flash | 99 | 383453 | 17290 | 39 | 1 | 39 |
| google/gemini-3.8-flash | 7 | 21237 | 15 | 4 | 2 | 4 |
| google/gemma-4-26b-a4b-it | 131 | 302370 | 31112 | 71 | 0 | 71 |
| google/gemma-4-31b-it | 145 | 160385 | 4843 | 102 | 0 | 102 |
| openrouter/cohere/north-mini-code:free | 22 | 69376 | 10273 | 5 | 0 | 6 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 95 | 551204 | 147387 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 485 | 0 |
| gate | 1917 | 0 |
| infra | 356 | 0 |
| loop | 2526 | 0 |
| other | 1681 | 0 |
| promote | 40 | 0 |
| review | 830 | 456 |
| run | 5100 | 1772 |
| triage | 159 | 0 |

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
Tests not in the cloud: 45
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
- tests/test_factory_jam_lift.py (backlog-id)
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
