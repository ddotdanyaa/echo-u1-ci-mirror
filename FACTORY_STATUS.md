# Factory status (generated, structured data only)

Generated: 2026-11-19T15:31:11Z
Source commit: shad507b723387f

## Commits (sha, time)
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
- sha8a637b2c 2026-11-19T16:56:56+03:00
- shad1b3557d 2026-11-19T15:05:56+03:00
- sha1e41f026 2026-11-19T14:55:25+03:00
- sha9f47f5fe 2026-11-19T14:36:43+03:00
- sha8da7a784 2026-11-19T14:23:20+03:00
- sha08be01f0 2026-11-19T12:39:46+03:00
- shaa88a6343 2026-11-19T12:08:39+03:00

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 10 |
| coded | 6 |
| found_in_backlog | unknown |
| gate_pass | 0 |
| known_to_loop | 156 |
| promoted | 0 |
| ready | 3 |
| reviewed | 3 |
| triaged | 10 |

Side counters: blocked=4, parked=0, requeued=0
Tasks now: BLOCKED=4, FAILED=6, READY=3, RUNNING=1
Accepted: 0
Promoted: 0
Free RAM, GB: 3.3
Telemetry rows: 331 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.5-flash-lite | 32 | 371127 | 7273 | 3 | 0 | 3 |
| google/gemini-3.6-flash | 4 | 6680 | 325 | 3 | 0 | 3 |
| google/gemma-4-26b-a4b-it | 1 | 0 | 0 | 1 | 0 | 1 |
| google/gemma-4-31b-it | 17 | 8316 | 589 | 11 | 0 | 11 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 11 | 0 |
| gate | 64 | 0 |
| infra | 27 | 0 |
| loop | 75 | 0 |
| other | 3 | 0 |
| review | 29 | 18 |
| run | 119 | 36 |
| triage | 3 | 0 |

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
Tests in the cloud: 17
Tests not in the cloud: 27
- tests/test_agent_factory.py (backlog-id, email, env-path, key, long-run, owner-name, path, user-path)
- tests/test_factory_channels.py (long-run)
- tests/test_factory_context.py (env-path, key, long-run, owner-name, path, short-name, user-path)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- tests/test_factory_gate.py (email, path)
- tests/test_factory_gate_marker.py (backlog-id)
- tests/test_factory_gate_more.py (email)
- tests/test_factory_gate_slots.py (long-run)
- tests/test_factory_loop_answers.py (backlog-id, call-word, long-run)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (backlog-id)
- tests/test_factory_loop_core2.py (env-path, path)
- tests/test_factory_loop_core3.py (env-path, key, long-run)
- tests/test_factory_loop_d8c.py (dependency)
- tests/test_factory_loop_d8d.py (backlog-id, call-word, key, long-run, phone)
- tests/test_factory_loop_d8e.py (long-run)
- tests/test_factory_loop_parents.py (dependency)
- tests/test_factory_loop_r7.py (backlog-id, ip, key, long-run, phone)
- tests/test_factory_loop_r7b.py (dependency)
- tests/test_factory_loop_report.py (key, long-run)
- tests/test_factory_loop_run.py (key, long-run)
- tests/test_factory_profile.py (backlog-id, email)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_runtime.py (backlog-id, email, env-path, key, long-run, path, user-path)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, phone)

## Cloud test matrix
Not read yet.
