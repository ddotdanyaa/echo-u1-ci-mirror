# Factory status (generated, structured data only)

Generated: 2026-11-23T04:25:15Z
Source commit: sha7d3f6f76ac23

## Commits (sha, time)
- sha7d3f6f76 2026-11-23T07:24:39+03:00
- sha925856fd 2026-11-23T07:16:11+03:00
- sha971ac612 2026-11-23T07:16:08+03:00
- sha7b1467bb 2026-11-23T07:12:08+03:00
- shaf1486e73 2026-11-23T07:03:59+03:00
- shae3a8dbed 2026-11-23T07:00:46+03:00
- shad6375f2f 2026-11-23T06:58:37+03:00
- sha4f5929ad 2026-11-23T06:52:26+03:00
- sha480d59d2 2026-11-23T06:51:10+03:00
- sha6a34d370 2026-11-23T06:50:35+03:00
- sha6d9c08ed 2026-11-23T06:50:08+03:00
- shae55545a1 2026-11-23T06:49:24+03:00
- shad8d12f12 2026-11-23T06:48:34+03:00
- sha4687154d 2026-11-23T05:29:17+03:00
- sha04bed750 2026-11-23T05:23:14+03:00
- sha9758fcdf 2026-11-23T05:05:56+03:00
- sha8aa12227 2026-11-23T05:04:10+03:00
- shae33e7efb 2026-11-23T04:58:54+03:00
- shaa7b6eef4 2026-11-23T04:56:10+03:00
- sha7d90be74 2026-11-23T04:47:00+03:00

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 226 |
| coded | 145 |
| found_in_backlog | unknown |
| gate_pass | 32 |
| known_to_loop | 300 |
| promoted | 30 |
| ready | 132 |
| reviewed | 85 |
| triaged | 179 |

Side counters: blocked=6, parked=0, requeued=2
Tasks now: BLOCKED=6, DONE=68, FAILED=195, PROMOTED=6, READY=132
Accepted: 5
Promoted: 30
Free RAM, GB: 5.23
Telemetry rows: 26688 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 10 | 9143 | 3871 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 11 | 5678 | 452 | 7 | 0 | 7 |
| cohere/north-mini-code-1.0 | 4 | 4159 | 237 | 1 | 0 | 1 |
| google/gemini-3-flash-preview | 2 | 0 | 0 | 2 | 2 | 2 |
| google/gemini-3.1-flash-lite | 1412 | 8273072 | 543827 | 57 | 2 | 57 |
| google/gemini-3.1-flash-lite-preview | 91 | 143589 | 21867 | 11 | 5 | 11 |
| google/gemini-3.5-flash | 4 | 8402 | 347 | 3 | 2 | 3 |
| google/gemini-3.5-flash-lite | 1592 | 10132570 | 479128 | 30 | 2 | 30 |
| google/gemini-3.6-flash | 101 | 383453 | 17290 | 41 | 3 | 41 |
| google/gemini-3.7-flash | 4 | 9121 | 14 | 3 | 2 | 3 |
| google/gemini-3.8-flash | 9 | 21237 | 15 | 6 | 4 | 6 |
| google/gemma-4-26b-a4b-it | 205 | 400475 | 33673 | 116 | 0 | 116 |
| google/gemma-4-31b-it | 190 | 195762 | 6167 | 140 | 0 | 140 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 115 | 663252 | 151232 | 2 | 2 | 2 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 3983 | 0 |
| infra | 787 | 0 |
| loop | 4862 | 0 |
| other | 5130 | 0 |
| promote | 41 | 0 |
| review | 1643 | 879 |
| run | 9381 | 2936 |
| triage | 325 | 0 |

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
Tests in the cloud: 118
Tests not in the cloud: 55
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
- tests/test_factory_selfgate.py (dependency)
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
