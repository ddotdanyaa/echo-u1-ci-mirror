# Factory status (generated, structured data only)

Generated: 2026-11-21T21:23:27Z
Source commit: sha3ee534fdacdd

## Commits (sha, time)
- sha3ee534fd 2026-11-22T00:21:39+03:00
- sha54ec7cfb 2026-11-22T00:21:39+03:00
- sha9cbc465b 2026-11-22T00:19:58+03:00
- sha85b4a8b4 2026-11-22T00:17:29+03:00
- sha33389d99 2026-11-22T00:15:45+03:00
- sha12a52f74 2026-11-22T00:13:38+03:00
- sha940c08b5 2026-11-22T00:11:42+03:00
- sha40b92bf5 2026-11-21T23:56:22+03:00
- sha92f9852a 2026-11-21T23:50:23+03:00
- sha9e19658b 2026-11-21T23:19:49+03:00
- shaed33a6f0 2026-11-21T23:17:14+03:00
- sha1715ff1b 2026-11-21T23:17:09+03:00
- shac3ec61c9 2026-11-21T23:17:06+03:00
- sha1afaedda 2026-11-21T23:17:00+03:00
- shafb6ec4c0 2026-11-21T23:10:57+03:00
- shab8d6b511 2026-11-21T23:10:51+03:00
- shab799e8b7 2026-11-21T23:07:11+03:00
- sha88fd8dd0 2026-11-21T23:06:02+03:00
- sha251545fc 2026-11-21T23:03:25+03:00
- shac05bcb56 2026-11-21T23:01:24+03:00

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 128 |
| coded | 71 |
| found_in_backlog | unknown |
| gate_pass | 31 |
| known_to_loop | 259 |
| promoted | 29 |
| ready | 27 |
| reviewed | 60 |
| triaged | 106 |

Side counters: blocked=3, parked=0, requeued=2
Tasks now: BLOCKED=3, DONE=68, FAILED=54, PROMOTED=5, READY=27, RUNNING=3
Accepted: 5
Promoted: 29
Free RAM, GB: 3.19
Telemetry rows: 17709 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 1005 | 6310610 | 405507 | 44 | 0 | 44 |
| google/gemini-3.5-flash-lite | 1289 | 8616318 | 402202 | 23 | 0 | 23 |
| google/gemini-3.6-flash | 99 | 383453 | 17290 | 39 | 1 | 39 |
| google/gemini-3.8-flash | 7 | 21237 | 15 | 4 | 2 | 4 |
| google/gemma-4-26b-a4b-it | 147 | 327722 | 31667 | 83 | 0 | 83 |
| google/gemma-4-31b-it | 160 | 174129 | 5167 | 114 | 0 | 114 |
| openrouter/cohere/north-mini-code:free | 22 | 69376 | 10273 | 5 | 0 | 6 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 95 | 551204 | 147387 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 494 | 0 |
| gate | 2663 | 0 |
| infra | 658 | 0 |
| loop | 3225 | 0 |
| other | 2337 | 0 |
| promote | 40 | 0 |
| review | 1189 | 649 |
| run | 6936 | 2175 |
| triage | 167 | 0 |

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
Modules: 25
Tests in the cloud: 115
Tests not in the cloud: 49
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
- <redacted-name> (backlog-id, call-word, email, key, long-run)
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
- tests/test_factory_route_d.py (backlog-id, long-run)
- tests/test_factory_status.py (dependency)
- tests/test_factory_survive.py (path, pid-port, user-path)
- tests/test_factory_sync.py (backlog-id, email)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_tree.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone, tunnel-host)
- tests/test_factory_triage_example.py (dependency)

## Cloud test matrix
Not read yet.
