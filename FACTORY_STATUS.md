# Factory status (generated, structured data only)

Generated: 2026-11-21T06:23:06Z
Source commit: sha6915caa4ceb9

## Commits (sha, time)
- sha6915caa4 2026-11-21T09:22:25+03:00
- sha4d99ed6a 2026-11-21T09:13:10+03:00
- sha4dbc2a7d 2026-11-21T05:55:38+03:00
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

## Funnel
| step | count |
|---|---|
| accepted | 4 |
| claimed | 89 |
| coded | 41 |
| found_in_backlog | unknown |
| gate_pass | 30 |
| known_to_loop | 347 |
| promoted | 28 |
| ready | 0 |
| reviewed | 38 |
| triaged | 67 |

Side counters: blocked=0, parked=0, requeued=2
Tasks now: DONE=61, FAILED=32, PROMOTED=4
Accepted: 4
Promoted: 28
Free RAM, GB: 3.69
Telemetry rows: 8596 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 538 | 3373953 | 238112 | 26 | 0 | 26 |
| google/gemini-3.5-flash-lite | 730 | 4902266 | 258146 | 20 | 0 | 20 |
| google/gemini-3.6-flash | 59 | 261862 | 13302 | 18 | 1 | 18 |
| google/gemini-3.8-flash | 1 | 0 | 0 | 1 | 1 | 1 |
| google/gemma-4-26b-a4b-it | 97 | 253075 | 30404 | 46 | 0 | 46 |
| google/gemma-4-31b-it | 114 | 136803 | 4411 | 76 | 0 | 76 |
| openrouter/cohere/north-mini-code:free | 21 | 69376 | 10273 | 4 | 0 | 5 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 75 | 421790 | 132479 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 412 | 0 |
| gate | 1403 | 0 |
| infra | 131 | 0 |
| loop | 1661 | 0 |
| other | 915 | 0 |
| promote | 39 | 0 |
| review | 587 | 317 |
| run | 3352 | 1318 |
| triage | 96 | 0 |

## Channels (model ids)
- 1db4ab-gemini-3-8-flash
- g-3-1-flash-lite
- g-3-5-flash-lite
- g-3-6-flash
- g-gemma-4-26b
- g-gemma-4-31b
- google/gemini-3.1-flash-lite
- google/gemini-3.5-flash-lite
- google/gemini-3.6-flash
- google/gemini-3.8-flash
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
Tests not in the cloud: 31
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_class_cases.py (backlog-id, call-word, path, phone)
- tests/test_factory_cloud_product.py (long-run)
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
