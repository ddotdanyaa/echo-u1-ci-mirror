# Factory status (generated, structured data only)

Generated: 2026-11-23T11:38:28Z
Source commit: shad47ba2b4d58c

## Commits (sha, time)
- shad47ba2b4 2026-11-23T14:36:17+03:00
- sha53eee43c 2026-11-23T14:32:54+03:00
- sha24500403 2026-11-23T14:31:02+03:00
- shaa1ddac8b 2026-11-23T14:13:20+03:00
- sha731f1824 2026-11-23T14:08:28+03:00
- sha269a867b 2026-11-23T14:06:52+03:00
- shae9b07756 2026-11-23T14:00:18+03:00
- shafac1b1d3 2026-11-23T13:29:49+03:00
- sha3c212cce 2026-11-23T13:25:03+03:00
- sha754753fc 2026-11-23T13:14:23+03:00
- shac23bc46b 2026-11-23T13:08:28+03:00
- shabdbd0514 2026-11-23T13:06:35+03:00
- shaaf9998d7 2026-11-23T12:44:06+03:00
- shaaf49a142 2026-11-23T12:43:17+03:00
- sha17c2e3c6 2026-11-23T12:39:29+03:00
- sha45624b24 2026-11-23T12:36:59+03:00
- sha0be41792 2026-11-23T12:32:35+03:00
- sha5f952479 2026-11-23T12:26:27+03:00
- shac54f0e35 2026-11-23T12:20:20+03:00
- sha79544961 2026-11-23T12:17:19+03:00

## Funnel
| step | count |
|---|---|
| accepted | 10 |
| claimed | 363 |
| coded | 183 |
| found_in_backlog | unknown |
| gate_pass | 64 |
| known_to_loop | 344 |
| promoted | 60 |
| ready | 6 |
| reviewed | 156 |
| triaged | 188 |

Side counters: blocked=1, parked=0, requeued=7
Tasks now: BLOCKED=1, DONE=68, FAILED=445, PROMOTED=36, READY=6, RUNNING=6
Accepted: 10
Promoted: 60
Free RAM, GB: 5.68
Telemetry rows: 32778 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 36 | 38166 | 9670 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 12 | 5678 | 452 | 8 | 0 | 8 |
| cohere/north-mini-code-1.0 | 6 | 4159 | 237 | 3 | 0 | 3 |
| google/gemini-3-flash-preview | 28 | 35638 | 6501 | 12 | 11 | 12 |
| google/gemini-3.1-flash-lite | 1575 | 8621928 | 597083 | 70 | 4 | 70 |
| google/gemini-3.1-flash-lite-preview | 249 | 516929 | 80695 | 25 | 8 | 25 |
| google/gemini-3.5-flash | 32 | 30545 | 1824 | 22 | 20 | 22 |
| google/gemini-3.5-flash-lite | 1878 | 10774779 | 616172 | 36 | 4 | 36 |
| google/gemini-3.6-flash | 133 | 414079 | 20196 | 55 | 10 | 55 |
| google/gemini-3.7-flash | 19 | 9121 | 14 | 18 | 7 | 18 |
| google/gemini-3.8-flash | 22 | 21237 | 15 | 19 | 8 | 19 |
| google/gemma-4-26b-a4b-it | 264 | 423342 | 36171 | 165 | 0 | 165 |
| google/gemma-4-31b-it | 258 | 230146 | 8705 | 193 | 0 | 193 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 115 | 663252 | 151232 | 2 | 2 | 2 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 5186 | 0 |
| infra | 830 | 0 |
| loop | 5668 | 0 |
| other | 7090 | 0 |
| promote | 76 | 0 |
| review | 2087 | 1132 |
| run | 10937 | 3560 |
| triage | 368 | 0 |

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
- openrouter/nvidia/nemotron-3-ultra-550b-a55b:free
- or-nemotron-3-ultra

## Published files
Modules: 29
Tests in the cloud: 122
Tests not in the cloud: 70
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_architect.py (backlog-id, env-path, path)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_base_near.py (email, short-name)
- tests/test_factory_base_unsettled.py (dependency)
- tests/test_factory_canary.py (env-path, long-run)
- tests/test_factory_cannot_scope.py (env-path)
- tests/test_factory_channels.py (dependency)
- tests/test_factory_class_cases.py (backlog-id, call-word, long-run, path, phone)
- tests/test_factory_closures.py (backlog-id)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_cloud_sizing.py (dependency)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_cool.py (long-run)
- tests/test_factory_ctx.py (dependency)
- tests/test_factory_debt.py (long-run)
- tests/test_factory_decompose.py (call-word, email)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_fanout.py (long-run)
- tests/test_factory_feed.py (backlog-id, call-word)
- tests/test_factory_hard.py (long-run)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (dependency)
- tests/test_factory_keep.py (dependency)
- tests/test_factory_keep_cards.py (backlog-id)
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
- tests/test_factory_loop_watch.py (long-run)
- tests/test_factory_metrics.py (owner-words)
- tests/test_factory_need_outline.py (dependency)
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
- tests/test_factory_release_run.py (dependency)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_self_loop.py (backlog-id)
- tests/test_factory_selfgate.py (dependency)
- tests/test_factory_selfgate_scan.py (dependency)
- tests/test_factory_slicer.py (backlog-id, call-word, email, key, long-run)
- tests/test_factory_slicer_pool.py (env-path, long-run)
- tests/test_factory_slim_worker.py (long-run)
- tests/test_factory_status.py (dependency)
- tests/test_factory_supply.py (dependency)
- tests/test_factory_survive.py (path, pid-port, user-path)
- tests/test_factory_sync.py (backlog-id, email)
- tests/test_factory_tcode.py (dependency)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_tree.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone)
- tests/test_factory_triage_example.py (dependency)
- tests/test_factory_worker_exception_return.py (backlog-id)

## Cloud test matrix
Not read yet.
