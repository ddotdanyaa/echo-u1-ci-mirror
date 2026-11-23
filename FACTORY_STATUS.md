# Factory status (generated, structured data only)

Generated: 2026-11-23T11:08:56Z
Source commit: sha731f182467d7

## Commits (sha, time)
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
- sha90a3b5ae 2026-11-23T12:17:06+03:00
- shae1653bb7 2026-11-23T12:16:09+03:00
- sha8418174e 2026-11-23T12:15:22+03:00
- sha037d1b27 2026-11-23T12:13:22+03:00

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 351 |
| coded | 180 |
| found_in_backlog | unknown |
| gate_pass | 58 |
| known_to_loop | 322 |
| promoted | 54 |
| ready | 9 |
| reviewed | 149 |
| triaged | 188 |

Side counters: blocked=1, parked=0, requeued=6
Tasks now: BLOCKED=1, DONE=68, FAILED=429, PROMOTED=30, READY=9, REVIEW=1, RUNNING=6
Accepted: 5
Promoted: 54
Free RAM, GB: 4.98
Telemetry rows: 32169 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 36 | 38166 | 9670 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 12 | 5678 | 452 | 8 | 0 | 8 |
| cohere/north-mini-code-1.0 | 6 | 4159 | 237 | 3 | 0 | 3 |
| google/gemini-3-flash-preview | 27 | 33838 | 6152 | 12 | 11 | 12 |
| google/gemini-3.1-flash-lite | 1552 | 8580370 | 589826 | 69 | 4 | 69 |
| google/gemini-3.1-flash-lite-preview | 229 | 465906 | 73336 | 25 | 8 | 25 |
| google/gemini-3.5-flash | 30 | 30545 | 1824 | 20 | 18 | 20 |
| google/gemini-3.5-flash-lite | 1847 | 10717917 | 598337 | 35 | 4 | 35 |
| google/gemini-3.6-flash | 133 | 414079 | 20196 | 55 | 10 | 55 |
| google/gemini-3.7-flash | 18 | 9121 | 14 | 17 | 6 | 17 |
| google/gemini-3.8-flash | 21 | 21237 | 15 | 18 | 7 | 18 |
| google/gemma-4-26b-a4b-it | 259 | 422061 | 35721 | 161 | 0 | 161 |
| google/gemma-4-31b-it | 248 | 218139 | 8191 | 187 | 0 | 187 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 115 | 663252 | 151232 | 2 | 2 | 2 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 5057 | 0 |
| infra | 826 | 0 |
| loop | 5612 | 0 |
| other | 6886 | 0 |
| promote | 69 | 0 |
| review | 2046 | 1110 |
| run | 10777 | 3488 |
| triage | 360 | 0 |

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
Tests not in the cloud: 69
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
