# Factory status (generated, structured data only)

Generated: 2026-11-19T19:52:40Z
Source commit: sha5398fca240a0

## Commits (sha, time)
- sha5398fca2 2026-11-19T22:50:33+03:00
- sha564f0e35 2026-11-19T22:45:44+03:00
- shaab24723b 2026-11-19T22:40:36+03:00
- sha2b455a15 2026-11-19T22:39:18+03:00
- sha7186642c 2026-11-19T22:39:17+03:00
- sha9be6e4dc 2026-11-19T22:33:17+03:00
- sha07c39b98 2026-11-19T22:33:16+03:00
- sha76937325 2026-11-19T22:20:26+03:00
- shae4d8ead7 2026-11-19T22:15:57+03:00
- shaf48b16cd 2026-11-19T21:41:24+03:00
- sha062c18aa 2026-11-19T21:36:14+03:00
- sha76052b01 2026-11-19T21:30:25+03:00
- sha55b403ce 2026-11-19T21:20:20+03:00
- sha2527f76d 2026-11-19T20:58:26+03:00
- shacbf45709 2026-11-19T20:46:38+03:00
- sha65ed1899 2026-11-19T20:33:51+03:00
- sha7de68f72 2026-11-19T20:33:45+03:00
- sha48d06dd2 2026-11-19T20:19:37+03:00
- sha82b8046a 2026-11-19T20:08:12+03:00
- sha371ec767 2026-11-19T20:00:39+03:00

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 33 |
| coded | 21 |
| found_in_backlog | unknown |
| gate_pass | 4 |
| known_to_loop | 366 |
| promoted | 4 |
| ready | 12 |
| reviewed | 10 |
| triaged | 29 |

Side counters: blocked=6, parked=0, requeued=0
Tasks now: BLOCKED=6, DONE=8, FAILED=18, READY=12, RUNNING=1
Accepted: 0
Promoted: 4
Free RAM, GB: 2.52
Telemetry rows: 1075 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 23 | 73848 | 7876 | 8 | 0 | 8 |
| google/gemini-3.5-flash-lite | 69 | 503913 | 12262 | 12 | 0 | 12 |
| google/gemini-3.6-flash | 4 | 6680 | 325 | 3 | 0 | 3 |
| google/gemma-4-26b-a4b-it | 11 | 9202 | 1286 | 7 | 0 | 7 |
| google/gemma-4-31b-it | 32 | 27983 | 1794 | 19 | 0 | 19 |
| openrouter/cohere/north-mini-code:free | 1 | 1603 | 8192 | 0 | 0 | 0 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 22 | 76445 | 94977 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 49 | 0 |
| gate | 198 | 0 |
| infra | 46 | 0 |
| loop | 285 | 0 |
| other | 16 | 0 |
| promote | 6 | 0 |
| review | 84 | 45 |
| run | 373 | 117 |
| triage | 18 | 0 |

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
Tests in the cloud: 26
Tests not in the cloud: 36
- tests/test_agent_factory.py (backlog-id, email, env-path, key, long-run, owner-name, path, user-path)
- tests/test_factory_channels.py (long-run)
- tests/test_factory_context.py (env-path, key, long-run, owner-name, path, short-name, user-path)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- tests/test_factory_gate.py (email, path)
- tests/test_factory_gate_marker.py (backlog-id)
- tests/test_factory_gate_more.py (email)
- tests/test_factory_gate_slots.py (long-run)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_light_indent.py (path)
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
- tests/test_factory_neighbours.py (dependency)
- tests/test_factory_profile.py (backlog-id, email)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_runtime.py (backlog-id, email, env-path, key, long-run, path, user-path)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, phone)

## Cloud test matrix
Not read yet.
