# Factory status (generated, structured data only)

Generated: 2026-11-19T15:01:23Z
Source commit: sha7dc45061af38

## Commits (sha, time)
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
- shaf9782ee0 2026-11-19T12:00:03+03:00
- shad75e32c4 2026-11-19T11:54:57+03:00
- sha366a4e53 2026-11-19T11:54:56+03:00
- sha60af8590 2026-11-19T11:45:16+03:00
- sha07f237c7 2026-11-19T11:36:07+03:00

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 7 |
| coded | 4 |
| found_in_backlog | unknown |
| gate_pass | 0 |
| known_to_loop | 114 |
| promoted | 0 |
| ready | 2 |
| reviewed | 2 |
| triaged | 7 |

Side counters: blocked=3, parked=0, requeued=0
Tasks now: BLOCKED=3, FAILED=4, READY=2
Accepted: 0
Promoted: 0
Free RAM, GB: 2.59
Telemetry rows: 167 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.5-flash-lite | 16 | 357077 | 5279 | 0 | 0 | 0 |
| google/gemini-3.6-flash | 4 | 6680 | 325 | 3 | 0 | 3 |
| google/gemma-4-31b-it | 5 | 3304 | 287 | 2 | 0 | 2 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 5 | 0 |
| gate | 26 | 0 |
| infra | 14 | 0 |
| loop | 44 | 0 |
| review | 8 | 5 |
| run | 68 | 20 |
| triage | 2 | 0 |

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
Tests in the cloud: 18
Tests not in the cloud: 26
- tests/test_agent_factory.py (backlog-id, email, env-path, key, long-run, owner-name, path, user-path)
- tests/test_factory_channels.py (long-run)
- tests/test_factory_context.py (env-path, key, long-run, owner-name, path, short-name, user-path)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- tests/test_factory_gate.py (email, path)
- tests/test_factory_gate_marker.py (backlog-id)
- tests/test_factory_gate_more.py (email)
- tests/test_factory_gate_slots.py (long-run)
- tests/test_factory_loop.py (email)
- tests/test_factory_loop_answers.py (backlog-id, call-word, long-run)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, email, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (backlog-id, email)
- tests/test_factory_loop_core2.py (email, env-path, path)
- tests/test_factory_loop_core3.py (env-path, key, long-run)
- tests/test_factory_loop_d8d.py (backlog-id, call-word, key, long-run, phone)
- tests/test_factory_loop_d8e.py (long-run)
- tests/test_factory_loop_r7.py (backlog-id, ip, key, long-run, phone)
- tests/test_factory_loop_report.py (email, key, long-run)
- tests/test_factory_loop_report5.py (email)
- tests/test_factory_loop_run.py (key, long-run)
- tests/test_factory_profile.py (backlog-id, email)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_runtime.py (backlog-id, email, env-path, key, long-run, path, user-path)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, phone)

## Cloud test matrix
Not read yet.
