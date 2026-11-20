# Factory status (generated, structured data only)

Generated: 2026-11-20T07:33:30Z
Source commit: sha238a85e2ad10

## Commits (sha, time)
- sha238a85e2 2026-11-20T10:33:14+03:00
- sha4363ba9b 2026-11-20T09:53:56+03:00
- sha95474a12 2026-11-20T09:46:00+03:00
- shaf5ee1739 2026-11-20T09:42:06+03:00
- sha74fdfeb9 2026-11-20T09:31:58+03:00
- sha378c3fc3 2026-11-20T09:14:57+03:00
- shadbb9a36d 2026-11-20T08:27:18+03:00
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

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 57 |
| coded | 22 |
| found_in_backlog | unknown |
| gate_pass | 13 |
| known_to_loop | 358 |
| promoted | 13 |
| ready | 3 |
| reviewed | 15 |
| triaged | 46 |

Side counters: blocked=6, parked=0, requeued=0
Tasks now: BLOCKED=6, DONE=28, FAILED=25, READY=3
Accepted: 0
Promoted: 13
Free RAM, GB: 4.24
Telemetry rows: 4079 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 248 | 1478935 | 105913 | 10 | 0 | 10 |
| google/gemini-3.5-flash-lite | 405 | 2750820 | 117492 | 13 | 0 | 13 |
| google/gemini-3.6-flash | 24 | 69915 | 3702 | 6 | 1 | 6 |
| google/gemma-4-26b-a4b-it | 48 | 111834 | 28683 | 21 | 0 | 21 |
| google/gemma-4-31b-it | 73 | 67690 | 3572 | 49 | 0 | 49 |
| openrouter/cohere/north-mini-code:free | 20 | 69376 | 10273 | 3 | 0 | 4 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 51 | 230417 | 113622 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 229 | 0 |
| gate | 761 | 0 |
| infra | 92 | 0 |
| loop | 798 | 0 |
| other | 223 | 0 |
| promote | 17 | 0 |
| review | 165 | 88 |
| run | 1761 | 781 |
| triage | 33 | 0 |

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
Tests in the cloud: 47
Tests not in the cloud: 69
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
- tests/test_factory_pool_runner.py (backlog-id)
- tests/test_factory_pool_state.py (backlog-id)
- tests/test_factory_port.py (backlog-id, key)
- tests/test_factory_port_triage.py (backlog-id, email)
- tests/test_factory_port_wiring.py (backlog-id, path)
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
