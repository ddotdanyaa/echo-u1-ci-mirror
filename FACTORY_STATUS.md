# Factory status (generated, structured data only)

Generated: 2026-11-20T00:14:57Z
Source commit: sha91e696cc75d4

## Commits (sha, time)
- sha91e696cc 2026-11-20T03:09:39+03:00
- sha886e6076 2026-11-20T02:57:14+03:00
- shaad200c31 2026-11-20T02:53:56+03:00
- sha25517e21 2026-11-20T02:48:33+03:00
- sha348433d7 2026-11-20T02:45:48+03:00
- shab3203f5d 2026-11-20T02:45:48+03:00
- sha99d17782 2026-11-20T02:35:16+03:00
- shabd98edf9 2026-11-20T02:32:45+03:00
- shaec9dc6b0 2026-11-20T02:25:49+03:00
- sha6a4485a7 2026-11-20T02:18:15+03:00
- shaf62b74c7 2026-11-20T02:12:08+03:00
- sha1ab9fc21 2026-11-20T02:11:21+03:00
- sha736ef691 2026-11-20T02:06:55+03:00
- sha46d3db8e 2026-11-20T01:56:18+03:00
- shae3bbd773 2026-11-20T01:50:41+03:00
- sha27252329 2026-11-20T01:43:05+03:00
- sha44af5bea 2026-11-20T01:32:55+03:00
- sha1a51710a 2026-11-20T01:31:21+03:00
- sha0b955456 2026-11-20T01:28:32+03:00
- shae183782a 2026-11-20T01:27:46+03:00

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 44 |
| coded | 22 |
| found_in_backlog | unknown |
| gate_pass | 13 |
| known_to_loop | 352 |
| promoted | 13 |
| ready | 17 |
| reviewed | 15 |
| triaged | 33 |

Side counters: blocked=12, parked=0, requeued=0
Tasks now: BLOCKED=12, DONE=8, FAILED=4, PROMOTED=7, READY=17, RUNNING=1
Accepted: 0
Promoted: 13
Free RAM, GB: 3.46
Telemetry rows: 2767 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 122 | 528808 | 41392 | 8 | 0 | 8 |
| google/gemini-3.5-flash-lite | 258 | 1612879 | 61667 | 12 | 0 | 12 |
| google/gemini-3.6-flash | 24 | 69915 | 3702 | 6 | 1 | 6 |
| google/gemma-4-26b-a4b-it | 38 | 100733 | 28677 | 14 | 0 | 14 |
| google/gemma-4-31b-it | 55 | 43101 | 2056 | 36 | 0 | 36 |
| openrouter/cohere/north-mini-code:free | 1 | 1603 | 8192 | 0 | 0 | 0 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 22 | 76445 | 94977 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 140 | 0 |
| gate | 561 | 0 |
| infra | 78 | 0 |
| loop | 559 | 0 |
| other | 131 | 0 |
| promote | 17 | 0 |
| review | 157 | 84 |
| run | 1099 | 436 |
| triage | 25 | 0 |

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
Tests in the cloud: 40
Tests not in the cloud: 57
- tests/test_agent_factory.py (backlog-id, email, env-path, key, long-run, owner-name, path, user-path)
- tests/test_factory_ab.py (backlog-id)
- tests/test_factory_channels.py (long-run)
- tests/test_factory_context.py (env-path, key, long-run, owner-name, path, short-name, user-path)
- tests/test_factory_context_fit_whole.py (backlog-id)
- tests/test_factory_critic_prior.py (dependency)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- tests/test_factory_gate.py (email, path)
- tests/test_factory_gate_marker.py (backlog-id)
- tests/test_factory_gate_more.py (email)
- tests/test_factory_gate_slots.py (long-run)
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
- tests/test_factory_spec.py (backlog-id)
- tests/test_factory_status.py (backlog-id)
- tests/test_factory_tournament.py (dependency)
- tests/test_factory_tournament_gate.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, phone)
- tests/test_factory_triage_example.py (backlog-id)
- tests/test_factory_triage_state.py (backlog-id, call-word)

## Cloud test matrix
Not read yet.
