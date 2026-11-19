# Factory status (generated, structured data only)

Generated: 2026-11-19T22:43:21Z
Source commit: sha2725232986a5

## Commits (sha, time)
- sha27252329 2026-11-20T01:43:05+03:00
- sha44af5bea 2026-11-20T01:32:55+03:00
- sha1a51710a 2026-11-20T01:31:21+03:00
- sha0b955456 2026-11-20T01:28:32+03:00
- shae183782a 2026-11-20T01:27:46+03:00
- shaac4c7914 2026-11-20T01:23:01+03:00
- sha48701950 2026-11-20T01:17:32+03:00
- shad19c9662 2026-11-20T01:13:23+03:00
- shaff52273b 2026-11-20T01:09:43+03:00
- shaffc50297 2026-11-20T01:05:03+03:00
- shaf040d37a 2026-11-20T01:03:51+03:00
- shad9e63993 2026-11-20T01:01:59+03:00
- shab8ed74b6 2026-11-20T01:00:20+03:00
- shac7405f39 2026-11-20T00:54:37+03:00
- shad4961407 2026-11-20T00:52:10+03:00
- sha69f6e031 2026-11-20T00:45:23+03:00
- sha2a6df453 2026-11-20T00:42:13+03:00
- sha9afbc479 2026-11-20T00:41:16+03:00
- sha96067707 2026-11-20T00:40:42+03:00
- sha013b5d25 2026-11-20T00:37:55+03:00

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 39 |
| coded | 22 |
| found_in_backlog | unknown |
| gate_pass | 11 |
| known_to_loop | 366 |
| promoted | 11 |
| ready | 18 |
| reviewed | 14 |
| triaged | 29 |

Side counters: blocked=7, parked=0, requeued=0
Tasks now: BLOCKED=7, DONE=8, FAILED=4, PROMOTED=7, READY=18, RUNNING=1
Accepted: 0
Promoted: 11
Free RAM, GB: 3.84
Telemetry rows: 2209 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 68 | 249058 | 20630 | 8 | 0 | 8 |
| google/gemini-3.5-flash-lite | 195 | 1026359 | 42426 | 12 | 0 | 12 |
| google/gemini-3.6-flash | 24 | 69915 | 3702 | 6 | 1 | 6 |
| google/gemma-4-26b-a4b-it | 26 | 56039 | 26301 | 10 | 0 | 10 |
| google/gemma-4-31b-it | 49 | 41512 | 2040 | 31 | 0 | 31 |
| openrouter/cohere/north-mini-code:free | 1 | 1603 | 8192 | 0 | 0 | 0 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 22 | 76445 | 94977 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 113 | 0 |
| gate | 449 | 0 |
| infra | 66 | 0 |
| loop | 473 | 0 |
| other | 87 | 0 |
| promote | 14 | 0 |
| review | 133 | 70 |
| run | 851 | 315 |
| triage | 23 | 0 |

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
Tests not in the cloud: 55
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
- tests/test_factory_light_indent.py (path)
- tests/test_factory_light_reasoning.py (backlog-id, long-run)
- tests/test_factory_light_telemetry.py (backlog-id, long-run)
- tests/test_factory_loop_ab.py (backlog-id)
- tests/test_factory_loop_answers.py (backlog-id, call-word, long-run)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (backlog-id)
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
