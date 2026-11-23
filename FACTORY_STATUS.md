# Factory status (generated, structured data only)

Generated: 2026-11-23T00:34:43Z
Source commit: sha6266768a498c

## Commits (sha, time)
- sha6266768a 2026-11-23T03:34:08+03:00
- sha67b1ec9a 2026-11-23T03:27:39+03:00
- sha134d2e9a 2026-11-23T03:03:54+03:00
- shae6a67756 2026-11-23T02:55:49+03:00
- sha600a83c7 2026-11-23T02:55:47+03:00
- sha931c111b 2026-11-23T02:53:44+03:00
- sha545ab80e 2026-11-23T02:44:45+03:00
- sha9bf49ad6 2026-11-23T02:38:16+03:00
- sha3ee6f7e4 2026-11-23T02:37:49+03:00
- shaa971293a 2026-11-23T02:35:20+03:00
- shacdb2452e 2026-11-23T02:34:32+03:00
- sha8214b773 2026-11-23T02:26:58+03:00
- shae7f921e2 2026-11-23T01:11:02+03:00
- shab324ce21 2026-11-23T01:03:31+03:00
- sha82c607f7 2026-11-23T00:40:47+03:00
- sha9487a412 2026-11-23T00:39:35+03:00
- sha613d682b 2026-11-23T00:39:08+03:00
- shaee515384 2026-11-23T00:25:00+03:00
- shac0908892 2026-11-23T00:23:05+03:00
- sha58bb1e6f 2026-11-23T00:17:01+03:00

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
Tasks now: DONE=68, FAILED=95, PROMOTED=5, READY=9
Accepted: 5
Promoted: 29
Free RAM, GB: 5.18
Telemetry rows: 22008 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3-flash-preview | 2 | 0 | 0 | 2 | 2 | 2 |
| google/gemini-3.1-flash-lite | 1312 | 8145271 | 518629 | 48 | 0 | 48 |
| google/gemini-3.1-flash-lite-preview | 3 | 20209 | 1402 | 0 | 0 | 0 |
| google/gemini-3.5-flash | 1 | 8402 | 347 | 0 | 0 | 0 |
| google/gemini-3.5-flash-lite | 1520 | 10045003 | 454510 | 28 | 0 | 28 |
| google/gemini-3.6-flash | 99 | 383453 | 17290 | 39 | 1 | 39 |
| google/gemini-3.7-flash | 1 | 9121 | 14 | 0 | 0 | 0 |
| google/gemini-3.8-flash | 7 | 21237 | 15 | 4 | 2 | 4 |
| google/gemma-4-26b-a4b-it | 169 | 375266 | 32564 | 97 | 0 | 97 |
| google/gemma-4-31b-it | 178 | 194429 | 5591 | 129 | 0 | 129 |
| openrouter/cohere/north-mini-code:free | 23 | 69376 | 10273 | 6 | 0 | 7 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 113 | 661842 | 151107 | 1 | 1 | 1 |
| other | 42 | 1084816 | 56437 | 0 | 0 | 0 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 3269 | 0 |
| infra | 768 | 0 |
| loop | 4345 | 0 |
| other | 2817 | 0 |
| promote | 40 | 0 |
| review | 1544 | 843 |
| run | 8394 | 2627 |
| triage | 295 | 0 |

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
Tests in the cloud: 123
Tests not in the cloud: 49
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_cannot_scope.py (env-path)
- tests/test_factory_class_cases.py (backlog-id, call-word, long-run, path, phone)
- tests/test_factory_closures.py (backlog-id)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_cloud_sizing.py (dependency)
- tests/test_factory_context_pinned.py (path)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (dependency)
- tests/test_factory_light_squeezed.py (path)
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
- tests/test_factory_loop_selffix.py (call-word, phone)
- tests/test_factory_metrics.py (owner-words)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_paid_coder.py (backlog-id, env-path, key, owner-words)
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
- tests/test_factory_release.py (backlog-id)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_slicer.py (backlog-id, call-word, email, key, long-run)
- tests/test_factory_slim_worker.py (long-run)
- tests/test_factory_status.py (dependency)
- tests/test_factory_survive.py (path, pid-port, user-path)
- tests/test_factory_sync.py (backlog-id, email)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_tree.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone, tunnel-host)
- tests/test_factory_triage_example.py (dependency)

## Cloud test matrix
Not read yet.
