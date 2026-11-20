# Factory status (generated, structured data only)

Generated: 2026-11-20T23:35:01Z
Source commit: sha840450d18721

## Commits (sha, time)
- sha840450d1 2026-11-21T02:34:31+03:00
- sha5d0cd220 2026-11-21T02:30:23+03:00
- shabd4a32eb 2026-11-21T00:41:03+03:00
- sha775a5669 2026-11-21T00:29:42+03:00
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

## Funnel
| step | count |
|---|---|
| accepted | 2 |
| claimed | 88 |
| coded | 40 |
| found_in_backlog | unknown |
| gate_pass | 27 |
| known_to_loop | 346 |
| promoted | 25 |
| ready | 0 |
| reviewed | 34 |
| triaged | 66 |

Side counters: blocked=0, parked=0, requeued=2
Tasks now: DONE=56, FAILED=37, PROMOTED=2, RUNNING=1
Accepted: 2
Promoted: 25
Free RAM, GB: 2.46
Telemetry rows: 8196 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 514 | 3171755 | 225235 | 25 | 0 | 25 |
| google/gemini-3.5-flash-lite | 705 | 4681703 | 242379 | 20 | 0 | 20 |
| google/gemini-3.6-flash | 59 | 261862 | 13302 | 18 | 1 | 18 |
| google/gemma-4-26b-a4b-it | 91 | 221629 | 30084 | 44 | 0 | 44 |
| google/gemma-4-31b-it | 108 | 112726 | 4188 | 73 | 0 | 73 |
| openrouter/cohere/north-mini-code:free | 20 | 69376 | 10273 | 3 | 0 | 4 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 51 | 230417 | 113622 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 394 | 0 |
| gate | 1355 | 0 |
| infra | 128 | 0 |
| loop | 1560 | 0 |
| other | 886 | 0 |
| promote | 36 | 0 |
| review | 558 | 298 |
| run | 3195 | 1250 |
| triage | 84 | 0 |

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
Tests in the cloud: 112
Tests not in the cloud: 29
- tests/test_factory_class_cases.py (backlog-id, call-word, path, phone)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- <redacted-name> (backlog-id)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (dependency)
- tests/test_factory_light_squeezed.py (path)
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
