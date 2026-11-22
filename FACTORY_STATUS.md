# Factory status (generated, structured data only)

Generated: 2026-11-22T22:30:14Z
Source commit: sha94c4ff48c198

## Commits (sha, time)
- sha94c4ff48 2026-11-23T00:33:33+03:00
- shaad39c64d 2026-11-23T00:14:18+03:00
- shac5da0f06 2026-11-23T00:13:36+03:00
- sha318cdbfc 2026-11-22T23:40:53+03:00
- sha094ebf2a 2026-11-22T23:31:07+03:00
- shaea5cbe26 2026-11-22T23:29:05+03:00
- shaab8f59ae 2026-11-22T23:22:58+03:00
- sha844596f5 2026-11-22T22:28:46+03:00
- sha2afa53ca 2026-11-22T22:15:21+03:00
- shadba3e872 2026-11-22T22:13:55+03:00
- sha15951366 2026-11-22T22:13:50+03:00
- sha7267beb4 2026-11-22T22:12:43+03:00
- shab515ae15 2026-11-22T22:12:03+03:00
- shacc51013f 2026-11-22T22:11:52+03:00
- shab5f9b741 2026-11-22T03:51:11+03:00
- sha67a8781b 2026-11-22T03:28:08+03:00
- sha98c2b3fb 2026-11-22T03:25:24+03:00
- sha743801c8 2026-11-22T02:51:24+03:00
- sha7b5dd292 2026-11-22T02:29:47+03:00
- sha57ca874c 2026-11-22T02:29:21+03:00

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 141 |
| coded | 82 |
| found_in_backlog | unknown |
| gate_pass | 31 |
| known_to_loop | 172 |
| promoted | 29 |
| ready | 9 |
| reviewed | 65 |
| triaged | 110 |

Side counters: blocked=0, parked=0, requeued=2
Tasks now: DONE=68, FAILED=94, PROMOTED=5, READY=9, RUNNING=1
Accepted: 5
Promoted: 29
Free RAM, GB: 5.43
Telemetry rows: 21738 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 1305 | 8084741 | 514650 | 48 | 0 | 48 |
| google/gemini-3.5-flash-lite | 1510 | 9966348 | 453398 | 27 | 0 | 27 |
| google/gemini-3.6-flash | 99 | 383453 | 17290 | 39 | 1 | 39 |
| google/gemini-3.8-flash | 7 | 21237 | 15 | 4 | 2 | 4 |
| google/gemma-4-26b-a4b-it | 169 | 375266 | 32564 | 97 | 0 | 97 |
| google/gemma-4-31b-it | 178 | 194429 | 5591 | 129 | 0 | 129 |
| openrouter/cohere/north-mini-code:free | 23 | 69376 | 10273 | 6 | 0 | 7 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 112 | 653753 | 151099 | 1 | 1 | 1 |
| other | 42 | 1084816 | 56437 | 0 | 0 | 0 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 534 | 0 |
| gate | 3258 | 0 |
| infra | 755 | 0 |
| loop | 4236 | 0 |
| other | 2761 | 0 |
| promote | 40 | 0 |
| review | 1544 | 843 |
| run | 8335 | 2602 |
| triage | 275 | 0 |

## Channels (model ids)
- 1db4ab-gemini-3-8-flash
- co-command-a
- co-command-a-plus
- co-north-mini-code
- cohere/command-a-03-2025
- cohere/command-a-plus-05-2026
- cohere/north-mini-code-1.0
- g-3-1-flash-lite
- g-3-5-flash-lite
- g-3-6-flash
- g-gemini-3-1-flash-lite-preview
- g-gemini-3-5-flash
- g-gemini-3-7-flash
- g-gemini-3-8-flash
- g-gemini-3-flash-preview
- g-gemma-4-26b
- g-gemma-4-31b
- google/gemini-3-flash-preview
- google/gemini-3.1-flash-lite
- google/gemini-3.1-flash-lite-preview
- google/gemini-3.5-flash
- google/gemini-3.5-flash-lite
- google/gemini-3.6-flash
- google/gemini-3.7-flash
- google/gemini-3.8-flash
- google/gemma-4-26b-a4b-it
- google/gemma-4-31b-it
- k2-g-3-1-flash-lite
- k2-g-3-5-flash-lite
- k2-g-3-6-flash
- k2-g-gemma-4-26b
- k2-g-gemma-4-31b
- k2-gemini-3-1-flash-lite-preview
- k2-gemini-3-5-flash
- k2-gemini-3-7-flash
- k2-gemini-3-flash-preview
- openrouter/cohere/north-mini-code:free
- openrouter/nvidia/nemotron-3-ultra-550b-a55b:free
- or-nemotron-3-ultra
- or-north-mini-code

## Published files
Modules: 25
Tests in the cloud: 114
Tests not in the cloud: 53
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_cannot_scope.py (env-path)
- tests/test_factory_channels.py (dependency)
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
- tests/test_factory_fanout.py (long-run)
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
- tests/test_factory_refeed.py (backlog-id)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_registry.py (backlog-id, owner-words)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_route_d.py (backlog-id, long-run)
- tests/test_factory_spec.py (dependency)
- tests/test_factory_status.py (dependency)
- tests/test_factory_survive.py (path, pid-port, user-path)
- tests/test_factory_sync.py (backlog-id, email)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_tree.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone, tunnel-host)
- tests/test_factory_triage_example.py (dependency)

## Cloud test matrix
Not read yet.
