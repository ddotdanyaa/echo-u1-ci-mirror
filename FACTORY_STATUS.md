# Factory status (generated, structured data only)

Generated: 2026-11-20T05:22:37Z
Source commit: sha389125d84b8f

## Commits (sha, time)
- sha389125d8 2026-11-20T08:22:19+03:00
- shaab44c66a 2026-11-20T08:21:26+03:00
- sha9d8c2b32 2026-11-20T07:59:21+03:00
- sha418bd704 2026-11-20T07:44:57+03:00
- sha6a1742d8 2026-11-20T07:02:07+03:00
- sha51a8356d 2026-11-20T06:50:04+03:00
- sha5c7a1faf 2026-11-20T06:42:02+03:00
- sha8aed118c 2026-11-20T06:39:33+03:00
- shad3953565 2026-11-20T05:37:16+03:00
- shab326123f 2026-11-20T05:33:52+03:00
- sha2f5a2915 2026-11-20T05:33:51+03:00
- sha4c97eb9a 2026-11-20T05:12:59+03:00
- shab0455c8d 2026-11-20T04:56:19+03:00
- shaea2c77ef 2026-11-20T03:59:21+03:00
- sha8bd01526 2026-11-20T03:57:03+03:00
- shae855205d 2026-11-20T03:50:20+03:00
- sha435cebbb 2026-11-20T03:49:08+03:00
- shad68d3a33 2026-11-20T03:41:01+03:00
- sha0a612339 2026-11-20T03:38:35+03:00
- shad27142b9 2026-11-20T03:23:44+03:00

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 51 |
| coded | 22 |
| found_in_backlog | unknown |
| gate_pass | 13 |
| known_to_loop | 352 |
| promoted | 13 |
| ready | 6 |
| reviewed | 15 |
| triaged | 40 |

Side counters: blocked=11, parked=0, requeued=0
Tasks now: BLOCKED=11, DONE=26, FAILED=12, READY=6, RUNNING=1
Accepted: 0
Promoted: 13
Free RAM, GB: 2.93
Telemetry rows: 3511 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 175 | 883392 | 60009 | 9 | 0 | 9 |
| google/gemini-3.5-flash-lite | 327 | 2035949 | 78729 | 13 | 0 | 13 |
| google/gemini-3.6-flash | 24 | 69915 | 3702 | 6 | 1 | 6 |
| google/gemma-4-26b-a4b-it | 43 | 107516 | 28677 | 17 | 0 | 17 |
| google/gemma-4-31b-it | 67 | 60152 | 3140 | 44 | 0 | 44 |
| openrouter/cohere/north-mini-code:free | 20 | 69376 | 10273 | 3 | 0 | 4 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 51 | 230417 | 113622 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 201 | 0 |
| gate | 691 | 0 |
| infra | 90 | 0 |
| loop | 694 | 0 |
| other | 181 | 0 |
| promote | 17 | 0 |
| review | 165 | 88 |
| run | 1442 | 619 |
| triage | 30 | 0 |

## Channels (model ids)
- g-3-1-flash-lite
- g-3-5-flash-lite
- g-3-6-flash
- g-gemma-4-26b
- g-gemma-4-31b
- google/gemini-3.1-flash-lite
- google/gemini-3.5-flash-lite
- google/gemini-3.6-flash
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
Modules: 19
Tests in the cloud: 46
Tests not in the cloud: 64
- tests/test_agent_factory.py (backlog-id, email, env-path, key, long-run, owner-name, path, user-path)
- tests/test_factory_ab.py (backlog-id)
- tests/test_factory_asked_code.py (dependency)
- tests/test_factory_base_cache.py (dependency)
- tests/test_factory_channels.py (long-run)
- tests/test_factory_context.py (env-path, key, long-run, owner-name, path, short-name, user-path)
- tests/test_factory_context_fit_whole.py (backlog-id)
- tests/test_factory_critic_gate_told.py (dependency)
- tests/test_factory_critic_prior.py (backlog-id)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- tests/test_factory_feedback_window.py (backlog-id)
- tests/test_factory_gate.py (email, path)
- tests/test_factory_gate_marker.py (backlog-id)
- tests/test_factory_gate_more.py (email)
- tests/test_factory_gate_slots.py (long-run)
- tests/test_factory_gate_unrun.py (dependency)
- tests/test_factory_holds.py (backlog-id, long-run)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (pid-port)
- tests/test_factory_light_function_edit.py (email, path)
- tests/test_factory_light_indent.py (path)
- tests/test_factory_light_reasoning.py (backlog-id, long-run)
- tests/test_factory_light_telemetry.py (backlog-id, long-run)
- tests/test_factory_loop_ab.py (backlog-id)
- tests/test_factory_loop_answers.py (backlog-id, call-word, long-run)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (backlog-id)
- tests/test_factory_loop_budget.py (long-run)
- tests/test_factory_loop_core2.py (env-path, path)
- tests/test_factory_loop_core3.py (env-path, key, long-run)
- tests/test_factory_loop_d8b.py (backlog-id)
- tests/test_factory_loop_d8c.py (backlog-id)
- tests/test_factory_loop_d8d.py (backlog-id, call-word, key, long-run, phone)
- tests/test_factory_loop_d8e.py (long-run)
- tests/test_factory_loop_discover.py (env-path)
- tests/test_factory_loop_git.py (backlog-id)
- tests/test_factory_loop_parents.py (dependency)
- tests/test_factory_loop_r7.py (backlog-id, ip, key, long-run, phone)
- tests/test_factory_loop_r7b.py (dependency)
- tests/test_factory_loop_report.py (key, long-run)
- tests/test_factory_loop_report7.py (backlog-id)
- tests/test_factory_loop_requeue.py (backlog-id)
- tests/test_factory_loop_run.py (key, long-run)
- tests/test_factory_neighbours.py (dependency)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_profile.py (backlog-id, email)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_quota_wire.py (dependency)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_requeue.py (backlog-id)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_runtime.py (backlog-id, email, env-path, key, long-run, path, user-path)
- tests/test_factory_selffix.py (long-run)
- tests/test_factory_source_guard.py (key)
- tests/test_factory_spec.py (backlog-id)
- tests/test_factory_status.py (backlog-id)
- tests/test_factory_test_audit.py (backlog-id)
- tests/test_factory_tournament.py (dependency)
- tests/test_factory_tournament_gate.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, phone)
- tests/test_factory_triage_example.py (backlog-id)
- tests/test_factory_triage_state.py (backlog-id, call-word)

## Cloud test matrix
Not read yet.
