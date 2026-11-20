# Factory status (generated, structured data only)

Generated: 2026-11-20T19:48:09Z
Source commit: sha0e14abf39476

## Commits (sha, time)
- sha0e14abf3 2026-11-20T22:47:28+03:00
- shaacd8f831 2026-11-20T21:55:25+03:00
- shaf7334f7b 2026-11-20T21:54:57+03:00
- shae8e4657a 2026-11-20T21:53:16+03:00
- sha63eccc08 2026-11-20T21:52:05+03:00
- sha9cd92a58 2026-11-20T20:46:38+03:00
- sha08c8196d 2026-11-20T19:34:25+03:00
- shab4978d08 2026-11-20T19:33:08+03:00
- shae502ceb7 2026-11-20T18:11:39+03:00
- sha630c2d61 2026-11-20T17:40:37+03:00
- shad326bd73 2026-11-20T16:31:24+03:00
- sha65516f8e 2026-11-20T16:30:41+03:00
- shab4fbb508 2026-11-20T15:44:25+03:00
- sha4901b1ee 2026-11-20T14:53:26+03:00
- sha9c422638 2026-11-20T14:03:17+03:00
- shabae3b5dc 2026-11-20T12:57:58+03:00
- sha20aca72b 2026-11-20T12:18:35+03:00
- shae082cdd3 2026-11-20T12:12:45+03:00
- sha238a85e2 2026-11-20T10:33:14+03:00
- sha4363ba9b 2026-11-20T09:53:56+03:00

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 78 |
| coded | 32 |
| found_in_backlog | unknown |
| gate_pass | 21 |
| known_to_loop | 345 |
| promoted | 20 |
| ready | 10 |
| reviewed | 29 |
| triaged | 61 |

Side counters: blocked=1, parked=0, requeued=1
Tasks now: BLOCKED=1, DONE=31, FAILED=46, READY=10
Accepted: 0
Promoted: 20
Free RAM, GB: 3.28
Telemetry rows: 7027 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 417 | 2590033 | 187016 | 25 | 0 | 25 |
| google/gemini-3.5-flash-lite | 626 | 4189922 | 211466 | 20 | 0 | 20 |
| google/gemini-3.6-flash | 59 | 261862 | 13302 | 18 | 1 | 18 |
| google/gemma-4-26b-a4b-it | 71 | 158376 | 28783 | 36 | 0 | 36 |
| google/gemma-4-31b-it | 98 | 104464 | 4138 | 64 | 0 | 64 |
| openrouter/cohere/north-mini-code:free | 20 | 69376 | 10273 | 3 | 0 | 4 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 51 | 230417 | 113622 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 334 | 0 |
| gate | 1156 | 0 |
| infra | 116 | 0 |
| loop | 1343 | 0 |
| other | 780 | 0 |
| promote | 28 | 0 |
| review | 382 | 200 |
| run | 2812 | 1142 |
| triage | 76 | 0 |

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
Tests not in the cloud: 86
- tests/test_agent_factory.py (backlog-id, email, env-path, key, long-run, owner-name, path, user-path)
- tests/test_factory_ab.py (backlog-id)
- tests/test_factory_asked_code.py (dependency)
- tests/test_factory_base_cache.py (dependency)
- tests/test_factory_channels.py (long-run)
- tests/test_factory_class_cases.py (backlog-id, call-word, path, phone)
- tests/test_factory_context.py (env-path, key, long-run, owner-name, path, short-name, user-path)
- tests/test_factory_context_fit_whole.py (backlog-id)
- tests/test_factory_critic_gate_told.py (dependency)
- tests/test_factory_critic_prior.py (backlog-id)
- tests/test_factory_critic_rubric.py (dependency)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- <redacted-name> (backlog-id, call-word, long-run)
- tests/test_factory_feedback_window.py (backlog-id)
- tests/test_factory_gate.py (backlog-id, email, path)
- tests/test_factory_gate_hollow.py (backlog-id)
- tests/test_factory_gate_marker.py (backlog-id)
- tests/test_factory_gate_more.py (email)
- tests/test_factory_gate_slots.py (long-run)
- tests/test_factory_gate_unrun.py (dependency)
- tests/test_factory_holds.py (backlog-id, long-run)
- tests/test_factory_holds_candidates.py (backlog-id)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (pid-port)
- tests/test_factory_kilo_rpm.py (dependency)
- tests/test_factory_light.py (backlog-id)
- tests/test_factory_light_floor.py (long-run)
- tests/test_factory_light_function_edit.py (email, path)
- tests/test_factory_light_indent.py (path)
- tests/test_factory_light_reasoning.py (backlog-id, long-run)
- tests/test_factory_light_telemetry.py (backlog-id, long-run)
- tests/test_factory_loop_ab.py (backlog-id)
- tests/test_factory_loop_answers.py (backlog-id, call-word, long-run)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (backlog-id)
- tests/test_factory_loop_budget.py (long-run)
- tests/test_factory_loop_candidates.py (backlog-id, email)
- tests/test_factory_loop_core2.py (env-path, path)
- tests/test_factory_loop_core3.py (env-path, key, long-run)
- tests/test_factory_loop_d8b.py (backlog-id)
- tests/test_factory_loop_d8c.py (backlog-id)
- tests/test_factory_loop_d8d.py (backlog-id, call-word, key, long-run, phone)
- tests/test_factory_loop_d8e.py (long-run)
- tests/test_factory_loop_discover.py (env-path)
- <redacted-name> (backlog-id, path)
- tests/test_factory_loop_git.py (backlog-id)
- tests/test_factory_loop_locate.py (dependency)
- tests/test_factory_loop_parents.py (dependency)
- tests/test_factory_loop_r7.py (backlog-id, ip, key, long-run, phone)
- tests/test_factory_loop_r7b.py (dependency)
- tests/test_factory_loop_report.py (key, long-run)
- tests/test_factory_loop_report7.py (backlog-id)
- tests/test_factory_loop_requeue.py (backlog-id)
- tests/test_factory_loop_run.py (key, long-run)
- tests/test_factory_loop_selffix.py (call-word, phone)
- tests/test_factory_neighbours.py (dependency)
- tests/test_factory_no_effect.py (dependency)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_path.py (dependency)
- tests/test_factory_pool_loop.py (backlog-id)
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
- tests/test_factory_triage_candidates.py (backlog-id, email, path)
- tests/test_factory_triage_example.py (backlog-id)
- tests/test_factory_triage_state.py (backlog-id, call-word)
- tests/test_factory_wiring.py (dependency)

## Cloud test matrix
Not read yet.
