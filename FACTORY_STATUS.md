# Factory status (generated, structured data only)

Generated: 2026-11-19T17:25:38Z
Source commit: sha48d06dd2ff32

## Commits (sha, time)
- sha48d06dd2 2026-11-19T20:19:37+03:00
- sha82b8046a 2026-11-19T20:08:12+03:00
- sha371ec767 2026-11-19T20:00:39+03:00
- shab9452364 2026-11-19T19:37:20+03:00
- sha8154f978 2026-11-19T19:35:20+03:00
- shaafd002ad 2026-11-19T18:56:02+03:00
- sha864eaf9a 2026-11-19T18:38:54+03:00
- shad507b723 2026-11-19T18:29:20+03:00
- sha0bb551de 2026-11-19T18:20:11+03:00
- sha33a1ab55 2026-11-19T18:17:00+03:00
- sha690fb967 2026-11-19T18:11:35+03:00
- sha5abb1b0c 2026-11-19T18:06:50+03:00
- sha7dc45061 2026-11-19T18:01:12+03:00
- sha60e38828 2026-11-19T17:58:34+03:00
- shab743f20f 2026-11-19T17:57:28+03:00
- sha6c8b15dc 2026-11-19T17:54:24+03:00
- sha29685b39 2026-11-19T17:49:54+03:00
- sha8201c28c 2026-11-19T17:47:08+03:00
- shab2ef7713 2026-11-19T17:46:21+03:00
- sha4b3f128c 2026-11-19T17:39:24+03:00

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 29 |
| coded | 20 |
| found_in_backlog | unknown |
| gate_pass | 3 |
| known_to_loop | 300 |
| promoted | 3 |
| ready | 3 |
| reviewed | 9 |
| triaged | 26 |

Side counters: blocked=9, parked=0, requeued=0
Tasks now: BLOCKED=9, FAILED=25, PROMOTED=3, READY=3
Accepted: 0
Promoted: 3
Free RAM, GB: 2.79
Telemetry rows: 730 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 14 | 39536 | 5979 | 5 | 0 | 5 |
| google/gemini-3.5-flash-lite | 51 | 419453 | 8472 | 9 | 0 | 9 |
| google/gemini-3.6-flash | 4 | 6680 | 325 | 3 | 0 | 3 |
| google/gemma-4-26b-a4b-it | 6 | 3720 | 0 | 4 | 0 | 4 |
| google/gemma-4-31b-it | 27 | 19821 | 1214 | 16 | 0 | 16 |
| openrouter/cohere/north-mini-code:free | 1 | 1603 | 8192 | 0 | 0 | 0 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 22 | 76445 | 94977 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 15 | 0 |
| gate | 144 | 0 |
| infra | 35 | 0 |
| loop | 176 | 0 |
| other | 6 | 0 |
| promote | 3 | 0 |
| review | 64 | 36 |
| run | 278 | 89 |
| triage | 9 | 0 |

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
- openrouter/cohere/north-mini-code:free
- openrouter/nvidia/nemotron-3-ultra-550b-a55b:free
- or-nemotron-3-ultra
- or-north-mini-code

## Published files
Modules: 10
Tests in the cloud: 15
Tests not in the cloud: 31
- tests/test_agent_factory.py (backlog-id, email, env-path, key, long-run, owner-name, path, user-path)
- tests/test_factory_channels.py (long-run)
- tests/test_factory_context.py (env-path, key, long-run, owner-name, path, short-name, user-path)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- tests/test_factory_gate.py (email, path)
- tests/test_factory_gate_marker.py (backlog-id)
- tests/test_factory_gate_more.py (email)
- tests/test_factory_gate_slots.py (long-run)
- tests/test_factory_light_reasoning.py (backlog-id, long-run)
- tests/test_factory_loop_answers.py (backlog-id, call-word, long-run)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (backlog-id)
- tests/test_factory_loop_core2.py (env-path, path)
- tests/test_factory_loop_core3.py (env-path, key, long-run)
- tests/test_factory_loop_d8b.py (backlog-id)
- tests/test_factory_loop_d8c.py (backlog-id)
- tests/test_factory_loop_d8d.py (backlog-id, call-word, key, long-run, phone)
- tests/test_factory_loop_d8e.py (long-run)
- tests/test_factory_loop_git.py (backlog-id)
- tests/test_factory_loop_parents.py (dependency)
- tests/test_factory_loop_r7.py (backlog-id, ip, key, long-run, phone)
- tests/test_factory_loop_r7b.py (dependency)
- tests/test_factory_loop_report.py (key, long-run)
- tests/test_factory_loop_report7.py (backlog-id)
- tests/test_factory_loop_run.py (key, long-run)
- tests/test_factory_profile.py (backlog-id, email)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_runtime.py (backlog-id, email, env-path, key, long-run, path, user-path)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, phone)

## Cloud test matrix
Not read yet.
