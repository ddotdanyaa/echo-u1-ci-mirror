# Factory status (generated, structured data only)

Generated: 2026-11-22T23:24:34Z
Source commit: shab3c7f2d80d7d

## Commits (sha, time)
- shab3c7f2d8 2026-11-23T02:23:57+03:00
- sha04761862 2026-11-23T01:14:37+03:00
- sha97958749 2026-11-23T01:13:23+03:00
- sha6c0c5ecc 2026-11-23T01:11:25+03:00
- shab324ce21 2026-11-23T01:03:31+03:00
- shaa087e15d 2026-11-23T00:57:44+03:00
- sha9bf0ebe0 2026-11-23T00:57:17+03:00
- sha9a3ab9bc 2026-11-23T00:54:44+03:00
- sha1deeb16d 2026-11-23T00:52:18+03:00
- shae407d0fd 2026-11-23T00:37:20+03:00
- sha24628bc7 2026-11-23T00:35:50+03:00
- shafce44179 2026-11-23T00:35:28+03:00
- shae58997cb 2026-11-23T00:23:36+03:00
- sha4fc041b2 2026-11-23T00:08:08+03:00
- sha1c7726dd 2026-11-23T00:03:07+03:00
- sha6cd8239c 2026-11-22T23:50:27+03:00
- sha5294a04b 2026-11-22T23:50:08+03:00
- sha9e525a31 2026-11-22T23:46:35+03:00
- sha98df1b39 2026-11-22T23:31:01+03:00
- sha03f15a8e 2026-11-22T23:30:45+03:00

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

Side counters: blocked=1, parked=0, requeued=2
Tasks now: BLOCKED=1, DONE=68, FAILED=94, PROMOTED=5, READY=9
Accepted: 5
Promoted: 29
Free RAM, GB: 3.87
Telemetry rows: 21871 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3-flash-preview | 2 | 0 | 0 | 2 | 2 | 2 |
| google/gemini-3.1-flash-lite | 1310 | 8127750 | 517319 | 48 | 0 | 48 |
| google/gemini-3.1-flash-lite-preview | 3 | 20209 | 1402 | 0 | 0 | 0 |
| google/gemini-3.5-flash | 1 | 8402 | 347 | 0 | 0 | 0 |
| google/gemini-3.5-flash-lite | 1518 | 10027125 | 454164 | 28 | 0 | 28 |
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
| answer | 535 | 0 |
| gate | 3267 | 0 |
| infra | 761 | 0 |
| loop | 4277 | 0 |
| other | 2780 | 0 |
| promote | 40 | 0 |
| review | 1544 | 843 |
| run | 8384 | 2623 |
| triage | 283 | 0 |

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
Tests in the cloud: 122
Tests not in the cloud: 47
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_architect.py (env-path, path)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_cannot_scope.py (env-path)
- tests/test_factory_class_cases.py (backlog-id, call-word, long-run, path, phone)
- tests/test_factory_closures.py (backlog-id)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_decompose.py (call-word, email)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (dependency)
- tests/test_factory_light_squeezed.py (path)
- tests/test_factory_loop_answers.py (backlog-id, call-word)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (dependency)
- tests/test_factory_loop_channel_brake.py (long-run)
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
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_registry.py (backlog-id, owner-words)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_slicer.py (backlog-id, call-word, email, key, long-run)
- tests/test_factory_slicer_pool.py (env-path, long-run)
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
