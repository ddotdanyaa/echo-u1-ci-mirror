# Factory status (generated, structured data only)

Generated: 2026-11-23T02:24:02Z
Source commit: sha04bed750979c

## Commits (sha, time)
- sha04bed750 2026-11-23T05:23:14+03:00
- sha9758fcdf 2026-11-23T05:05:56+03:00
- sha8aa12227 2026-11-23T05:04:10+03:00
- shae33e7efb 2026-11-23T04:58:54+03:00
- shaa7b6eef4 2026-11-23T04:56:10+03:00
- sha7d90be74 2026-11-23T04:47:00+03:00
- sha8803633a 2026-11-23T04:46:19+03:00
- sha807b8079 2026-11-23T04:45:39+03:00
- sha02346419 2026-11-23T04:45:33+03:00
- sha80e9d2d7 2026-11-23T04:45:23+03:00
- sha8f131f88 2026-11-23T04:41:43+03:00
- sha145eb03d 2026-11-23T04:35:37+03:00
- shac42dbe95 2026-11-23T04:34:10+03:00
- sha07b31cd3 2026-11-23T04:28:58+03:00
- sha5d669a38 2026-11-23T04:22:20+03:00
- sha47e918a6 2026-11-23T04:22:06+03:00
- shad09138da 2026-11-23T04:15:39+03:00
- sha66943b50 2026-11-23T04:12:40+03:00
- sha900a340a 2026-11-23T04:06:25+03:00
- sha4042e202 2026-11-23T04:04:02+03:00

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 166 |
| coded | 89 |
| found_in_backlog | unknown |
| gate_pass | 32 |
| known_to_loop | 300 |
| promoted | 30 |
| ready | 5 |
| reviewed | 66 |
| triaged | 110 |

Side counters: blocked=6, parked=0, requeued=2
Tasks now: BLOCKED=6, DONE=68, FAILED=120, PROMOTED=6, READY=5, RUNNING=3
Accepted: 5
Promoted: 30
Free RAM, GB: 4.92
Telemetry rows: 24098 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-plus-05-2026 | 2 | 1765 | 309 | 1 | 0 | 1 |
| google/gemini-3-flash-preview | 2 | 0 | 0 | 2 | 2 | 2 |
| google/gemini-3.1-flash-lite | 1334 | 8171418 | 524893 | 48 | 0 | 48 |
| google/gemini-3.1-flash-lite-preview | 14 | 34877 | 4814 | 0 | 0 | 0 |
| google/gemini-3.5-flash | 2 | 8402 | 347 | 1 | 0 | 1 |
| google/gemini-3.5-flash-lite | 1590 | 10131179 | 478647 | 29 | 1 | 29 |
| google/gemini-3.6-flash | 100 | 383453 | 17290 | 40 | 2 | 40 |
| google/gemini-3.7-flash | 2 | 9121 | 14 | 1 | 0 | 1 |
| google/gemini-3.8-flash | 7 | 21237 | 15 | 4 | 2 | 4 |
| google/gemma-4-26b-a4b-it | 181 | 377615 | 32639 | 107 | 0 | 107 |
| google/gemma-4-31b-it | 184 | 194429 | 5591 | 135 | 0 | 135 |
| openrouter/cohere/north-mini-code:free | 23 | 69376 | 10273 | 6 | 0 | 7 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 114 | 663252 | 151232 | 1 | 1 | 1 |
| other | 42 | 1084816 | 56437 | 0 | 0 | 0 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 3487 | 0 |
| infra | 783 | 0 |
| loop | 4550 | 0 |
| other | 4142 | 0 |
| promote | 41 | 0 |
| review | 1549 | 846 |
| run | 8688 | 2751 |
| triage | 322 | 0 |

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
Modules: 29
Tests in the cloud: 116
Tests not in the cloud: 54
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_architect.py (backlog-id, env-path, path)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_canary.py (env-path, long-run)
- tests/test_factory_cannot_scope.py (env-path)
- tests/test_factory_channels.py (dependency)
- tests/test_factory_class_cases.py (backlog-id, call-word, long-run, path, phone)
- tests/test_factory_closures.py (backlog-id)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_cloud_sizing.py (dependency)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_decompose.py (call-word, email)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_fanout.py (long-run)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (dependency)
- tests/test_factory_light_squeezed.py (path)
- tests/test_factory_links.py (backlog-id, call-word, key, long-run)
- tests/test_factory_loop_answers.py (backlog-id, call-word)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (dependency)
- tests/test_factory_loop_channel_brake.py (long-run)
- tests/test_factory_loop_core2.py (dependency)
- tests/test_factory_loop_core3.py (long-run)
- tests/test_factory_loop_d8c.py (dependency)
- tests/test_factory_loop_d8d.py (backlog-id, call-word, key, long-run, phone)
- tests/test_factory_loop_r7.py (dependency)
- tests/test_factory_loop_r7b.py (dependency)
- tests/test_factory_metrics.py (owner-words)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_paid_critic_span.py (key)
- tests/test_factory_path.py (backlog-id)
- tests/test_factory_port_wiring.py (dependency)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_registry.py (backlog-id, owner-words)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_release.py (backlog-id)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_self_loop.py (backlog-id)
- tests/test_factory_slicer.py (backlog-id, call-word, email, key, long-run)
- tests/test_factory_slicer_pool.py (env-path, long-run)
- tests/test_factory_slim_worker.py (long-run)
- tests/test_factory_status.py (dependency)
- tests/test_factory_supply.py (dependency)
- tests/test_factory_survive.py (path, pid-port, user-path)
- tests/test_factory_sync.py (backlog-id, email)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_tree.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone)
- tests/test_factory_triage_example.py (dependency)

## Cloud test matrix
Not read yet.
