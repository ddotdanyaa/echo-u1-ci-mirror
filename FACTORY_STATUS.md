# Factory status (generated, structured data only)

Generated: 2026-11-23T06:38:00Z
Source commit: sha507a036428ec

## Commits (sha, time)
- sha507a0364 2026-11-23T09:37:28+03:00
- sha6401990e 2026-11-23T09:30:16+03:00
- sha36042ce8 2026-11-23T09:27:09+03:00
- shaa8c29042 2026-11-23T09:25:54+03:00
- shae426c095 2026-11-23T09:24:19+03:00
- sha1910185e 2026-11-23T09:19:06+03:00
- shaaa738699 2026-11-23T08:38:46+03:00
- shadd471230 2026-11-23T08:33:21+03:00
- sha721f8a14 2026-11-23T08:27:09+03:00
- sha7ce28037 2026-11-23T08:25:19+03:00
- sha6a061cb9 2026-11-23T08:22:44+03:00
- shabe63052b 2026-11-23T08:03:52+03:00
- sha2fa75c38 2026-11-23T08:03:44+03:00
- sha0c5c001a 2026-11-23T07:58:24+03:00
- shacda47361 2026-11-23T07:57:41+03:00
- sha4559b8fa 2026-11-23T07:55:09+03:00
- shafe5abaa1 2026-11-23T07:53:57+03:00
- shac53a78e3 2026-11-23T07:43:09+03:00
- sha5c8da291 2026-11-23T07:37:26+03:00
- sha34b691ac 2026-11-23T07:33:35+03:00

## Funnel
| step | count |
|---|---|
| accepted | 5 |
| claimed | 236 |
| coded | 150 |
| found_in_backlog | unknown |
| gate_pass | 32 |
| known_to_loop | 300 |
| promoted | 30 |
| ready | 125 |
| reviewed | 89 |
| triaged | 179 |

Side counters: blocked=9, parked=0, requeued=2
Tasks now: BLOCKED=9, DONE=68, FAILED=203, PROMOTED=6, READY=125
Accepted: 5
Promoted: 30
Free RAM, GB: 4.27
Telemetry rows: 27675 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 10 | 9143 | 3871 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 11 | 5678 | 452 | 7 | 0 | 7 |
| cohere/north-mini-code-1.0 | 4 | 4159 | 237 | 1 | 0 | 1 |
| google/gemini-3-flash-preview | 4 | 0 | 0 | 4 | 4 | 4 |
| google/gemini-3.1-flash-lite | 1415 | 8274765 | 544000 | 59 | 4 | 59 |
| google/gemini-3.1-flash-lite-preview | 95 | 143589 | 21867 | 15 | 8 | 15 |
| google/gemini-3.5-flash | 8 | 12034 | 610 | 5 | 4 | 5 |
| google/gemini-3.5-flash-lite | 1596 | 10134925 | 479753 | 32 | 4 | 32 |
| google/gemini-3.6-flash | 104 | 384903 | 17369 | 43 | 5 | 43 |
| google/gemini-3.7-flash | 6 | 9121 | 14 | 5 | 4 | 5 |
| google/gemini-3.8-flash | 12 | 21237 | 15 | 9 | 5 | 9 |
| google/gemma-4-26b-a4b-it | 210 | 404904 | 34507 | 119 | 0 | 119 |
| google/gemma-4-31b-it | 196 | 198624 | 7209 | 144 | 0 | 144 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 115 | 663252 | 151232 | 2 | 2 | 2 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 4155 | 0 |
| infra | 794 | 0 |
| loop | 5083 | 0 |
| other | 5489 | 0 |
| promote | 41 | 0 |
| review | 1675 | 887 |
| run | 9577 | 2964 |
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
Tests in the cloud: 120
Tests not in the cloud: 58
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_architect.py (backlog-id, env-path, path)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
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
- tests/test_factory_worker_exception_return.py (backlog-id)

## Cloud test matrix
Not read yet.
