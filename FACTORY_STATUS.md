# Factory status (generated, structured data only)

Generated: 2026-11-20T21:27:43Z
Source commit: sha46cd666c0bcc

## Commits (sha, time)
- sha46cd666c 2026-11-21T00:27:07+03:00
- sha8fecc977 2026-11-21T00:20:03+03:00
- sha85d04614 2026-11-20T23:41:52+03:00
- sha22cce829 2026-11-20T23:31:32+03:00
- sha1a8b7a7a 2026-11-20T23:24:06+03:00
- sha1f928dc3 2026-11-20T23:22:22+03:00
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

## Funnel
| step | count |
|---|---|
| accepted | 0 |
| claimed | 84 |
| coded | 38 |
| found_in_backlog | unknown |
| gate_pass | 26 |
| known_to_loop | 344 |
| promoted | 24 |
| ready | 13 |
| reviewed | 33 |
| triaged | 64 |

Side counters: blocked=0, parked=0, requeued=2
Tasks now: DONE=32, FAILED=49, READY=13
Accepted: 0
Promoted: 24
Free RAM, GB: 2.74
Telemetry rows: 7956 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 495 | 3025522 | 209789 | 25 | 0 | 25 |
| google/gemini-3.5-flash-lite | 687 | 4540411 | 231460 | 20 | 0 | 20 |
| google/gemini-3.6-flash | 59 | 261862 | 13302 | 18 | 1 | 18 |
| google/gemma-4-26b-a4b-it | 89 | 214998 | 29939 | 44 | 0 | 44 |
| google/gemma-4-31b-it | 106 | 104464 | 4138 | 72 | 0 | 72 |
| openrouter/cohere/north-mini-code:free | 20 | 69376 | 10273 | 3 | 0 | 4 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 51 | 230417 | 113622 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 354 | 0 |
| gate | 1331 | 0 |
| infra | 127 | 0 |
| loop | 1507 | 0 |
| other | 868 | 0 |
| promote | 33 | 0 |
| review | 545 | 291 |
| run | 3111 | 1216 |
| triage | 80 | 0 |

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
Modules: 20
Tests in the cloud: 111
Tests not in the cloud: 27
- tests/test_factory_class_cases.py (backlog-id, call-word, path, phone)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- <redacted-name> (backlog-id)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (dependency)
- tests/test_factory_loop_answers.py (backlog-id, call-word, long-run)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (dependency)
- tests/test_factory_loop_d8c.py (dependency)
- tests/test_factory_loop_d8d.py (backlog-id, call-word, key, long-run, phone)
- <redacted-name> (backlog-id)
- tests/test_factory_loop_parents.py (dependency)
- tests/test_factory_loop_r7.py (dependency)
- tests/test_factory_loop_r7b.py (dependency)
- tests/test_factory_loop_selffix.py (call-word, phone)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_path.py (dependency)
- tests/test_factory_port_wiring.py (dependency)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_status.py (dependency)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, phone)
- tests/test_factory_triage_example.py (dependency)

## Cloud test matrix
Not read yet.
