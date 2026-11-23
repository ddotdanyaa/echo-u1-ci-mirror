# Factory status (generated, structured data only)

Generated: 2026-11-23T09:45:46Z
Source commit: shaaf9998d7f853

## Commits (sha, time)
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
- shae7c27d0e 2026-11-23T12:10:15+03:00
- sha897eca58 2026-11-23T12:04:35+03:00
- shab1ae5faa 2026-11-23T12:04:34+03:00
- sha3018e0ee 2026-11-23T11:57:51+03:00
- sha4ffd58e7 2026-11-23T11:55:56+03:00
- sha4acd280f 2026-11-23T11:54:36+03:00
- shacb4e1676 2026-11-23T11:53:48+03:00
- sha5da3004b 2026-11-23T11:45:56+03:00

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 308 |
| coded | 178 |
| found_in_backlog | unknown |
| gate_pass | 49 |
| known_to_loop | 252 |
| promoted | 46 |
| ready | 8 |
| reviewed | 133 |
| triaged | 182 |

Side counters: blocked=1, parked=0, requeued=6
Tasks now: BLOCKED=1, DONE=68, FAILED=400, PROMOTED=22, READY=8, RUNNING=4
Accepted: 5
Promoted: 46
Free RAM, GB: 5.33
Telemetry rows: 30705 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 36 | 38166 | 9670 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 12 | 5678 | 452 | 8 | 0 | 8 |
| cohere/north-mini-code-1.0 | 6 | 4159 | 237 | 3 | 0 | 3 |
| google/gemini-3-flash-preview | 26 | 33838 | 6152 | 11 | 10 | 11 |
| google/gemini-3.1-flash-lite | 1492 | 8440538 | 563569 | 65 | 4 | 65 |
| google/gemini-3.1-flash-lite-preview | 205 | 419330 | 63338 | 21 | 8 | 21 |
| google/gemini-3.5-flash | 23 | 23222 | 1391 | 15 | 13 | 15 |
| google/gemini-3.5-flash-lite | 1772 | 10553538 | 558359 | 33 | 4 | 33 |
| google/gemini-3.6-flash | 133 | 414079 | 20196 | 55 | 10 | 55 |
| google/gemini-3.7-flash | 16 | 9121 | 14 | 15 | 5 | 15 |
| google/gemini-3.8-flash | 18 | 21237 | 15 | 15 | 6 | 15 |
| google/gemma-4-26b-a4b-it | 241 | 419925 | 35023 | 144 | 0 | 144 |
| google/gemma-4-31b-it | 231 | 217340 | 8041 | 171 | 0 | 171 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 115 | 663252 | 151232 | 2 | 2 | 2 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 4779 | 0 |
| infra | 818 | 0 |
| loop | 5461 | 0 |
| other | 6319 | 0 |
| promote | 61 | 0 |
| review | 1960 | 1063 |
| run | 10427 | 3328 |
| triage | 344 | 0 |

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
Tests not in the cloud: 66
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
