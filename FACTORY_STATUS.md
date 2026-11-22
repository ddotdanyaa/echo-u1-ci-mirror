# Factory status (generated, structured data only)

Generated: 2026-11-22T00:31:32Z
Source commit: sha67a8781b6ac3

## Commits (sha, time)
- sha67a8781b 2026-11-22T03:28:08+03:00
- sha98c2b3fb 2026-11-22T03:25:24+03:00
- sha743801c8 2026-11-22T02:51:24+03:00
- sha7b5dd292 2026-11-22T02:29:47+03:00
- sha57ca874c 2026-11-22T02:29:21+03:00
- shab497322f 2026-11-22T02:26:18+03:00
- shadab39040 2026-11-22T02:22:58+03:00
- shafc334477 2026-11-22T01:53:03+03:00
- sha5a45b2ba 2026-11-22T01:13:14+03:00
- sha3965ff52 2026-11-22T00:39:51+03:00
- shadc5292c4 2026-11-22T00:35:48+03:00
- sha56d3d8db 2026-11-22T00:33:25+03:00
- sha6aab7c34 2026-11-22T00:31:26+03:00
- shae70a80aa 2026-11-22T00:28:25+03:00
- sha3ee534fd 2026-11-22T00:21:39+03:00
- sha54ec7cfb 2026-11-22T00:21:39+03:00
- sha9cbc465b 2026-11-22T00:19:58+03:00
- sha85b4a8b4 2026-11-22T00:17:29+03:00
- sha33389d99 2026-11-22T00:15:45+03:00
- sha12a52f74 2026-11-22T00:13:38+03:00

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 139 |
| coded | 81 |
| found_in_backlog | unknown |
| gate_pass | 31 |
| known_to_loop | 172 |
| promoted | 29 |
| ready | 16 |
| reviewed | 65 |
| triaged | 110 |

Side counters: blocked=3, parked=0, requeued=2
Tasks now: BLOCKED=3, DONE=68, FAILED=82, PROMOTED=5, READY=16, RUNNING=1
Accepted: 5
Promoted: 29
Free RAM, GB: 3.4
Telemetry rows: 20733 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 1295 | 8042830 | 512395 | 48 | 0 | 48 |
| google/gemini-3.5-flash-lite | 1508 | 9952485 | 452504 | 27 | 0 | 27 |
| google/gemini-3.6-flash | 99 | 383453 | 17290 | 39 | 1 | 39 |
| google/gemini-3.8-flash | 7 | 21237 | 15 | 4 | 2 | 4 |
| google/gemma-4-26b-a4b-it | 168 | 375266 | 32564 | 96 | 0 | 96 |
| google/gemma-4-31b-it | 177 | 194429 | 5591 | 128 | 0 | 128 |
| openrouter/cohere/north-mini-code:free | 23 | 69376 | 10273 | 6 | 0 | 7 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 106 | 624466 | 149284 | 1 | 1 | 1 |
| other | 26 | 256728 | 24797 | 0 | 0 | 0 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 529 | 0 |
| gate | 3205 | 0 |
| infra | 670 | 0 |
| loop | 3634 | 0 |
| other | 2702 | 0 |
| promote | 40 | 0 |
| review | 1530 | 833 |
| run | 8233 | 2576 |
| triage | 190 | 0 |

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
Modules: 26
Tests in the cloud: 115
Tests not in the cloud: 52
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
- tests/test_factory_paid_coder.py (backlog-id, env-path, key, owner-words)
- tests/test_factory_paid_critic.py (env-path, key, url)
- tests/test_factory_paid_critic_span.py (key)
- tests/test_factory_paid_wholeview.py (dependency)
- tests/test_factory_path.py (dependency)
- tests/test_factory_port_wiring.py (dependency)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_refeed.py (backlog-id)
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
