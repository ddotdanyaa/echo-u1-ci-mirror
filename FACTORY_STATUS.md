# Factory status (generated, structured data only)

Generated: 2026-11-21T11:00:10Z
Source commit: sha394863d3db22

## Commits (sha, time)
- sha394863d3 2026-11-21T13:59:27+03:00
- shad603c05a 2026-11-21T13:12:43+03:00
- sha81c72fa7 2026-11-21T13:04:34+03:00
- shaae6391e1 2026-11-21T12:24:27+03:00
- sha95469ae9 2026-11-21T11:34:35+03:00
- sha442be6e2 2026-11-21T11:03:23+03:00
- shab588f7e6 2026-11-21T10:43:56+03:00
- sha39c023a7 2026-11-21T10:28:16+03:00
- shaf33c430c 2026-11-21T10:23:50+03:00
- sha1a4510c0 2026-11-21T10:21:03+03:00
- sha22773320 2026-11-21T10:07:56+03:00
- sha7473e5ed 2026-11-21T09:54:40+03:00
- sha6915caa4 2026-11-21T09:22:25+03:00
- sha4d99ed6a 2026-11-21T09:13:10+03:00
- sha4dbc2a7d 2026-11-21T05:55:38+03:00
- sha840450d1 2026-11-21T02:34:31+03:00
- sha5d0cd220 2026-11-21T02:30:23+03:00
- shabd4a32eb 2026-11-21T00:41:03+03:00
- sha775a5669 2026-11-21T00:29:42+03:00
- sha46cd666c 2026-11-21T00:27:07+03:00

## Funnel
| step | count |
|---|---|
| accepted | 4 |
| claimed | 104 |
| coded | 56 |
| found_in_backlog | unknown |
| gate_pass | 30 |
| known_to_loop | 238 |
| promoted | 28 |
| ready | 6 |
| reviewed | 40 |
| triaged | 82 |

Side counters: blocked=2, parked=0, requeued=2
Tasks now: BLOCKED=2, DONE=64, FAILED=32, PROMOTED=4, READY=6, RUNNING=4
Accepted: 4
Promoted: 28
Free RAM, GB: 2.59
Telemetry rows: 9752 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| google/gemini-3.1-flash-lite | 588 | 3701236 | 265841 | 29 | 0 | 29 |
| google/gemini-3.5-flash-lite | 830 | 5591520 | 294806 | 21 | 0 | 21 |
| google/gemini-3.6-flash | 77 | 294499 | 14683 | 31 | 1 | 31 |
| google/gemini-3.8-flash | 7 | 21237 | 15 | 4 | 2 | 4 |
| google/gemma-4-26b-a4b-it | 102 | 253075 | 30404 | 51 | 0 | 51 |
| google/gemma-4-31b-it | 119 | 140353 | 4594 | 80 | 0 | 80 |
| openrouter/cohere/north-mini-code:free | 22 | 69376 | 10273 | 5 | 0 | 6 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 95 | 551204 | 147387 | 1 | 1 | 1 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 431 | 0 |
| gate | 1516 | 0 |
| infra | 144 | 0 |
| loop | 1972 | 0 |
| other | 1049 | 0 |
| promote | 39 | 0 |
| review | 600 | 326 |
| run | 3889 | 1514 |
| triage | 112 | 0 |

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
Tests not in the cloud: 34
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_class_cases.py (backlog-id, call-word, path, phone)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_decompose.py (backlog-id, call-word, email)
- <redacted-name> (backlog-id)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (dependency)
- tests/test_factory_light_squeezed.py (path)
- tests/test_factory_loop_answers.py (backlog-id, call-word)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (dependency)
- tests/test_factory_loop_channel_brake.py (long-run)
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
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone, tunnel-host)
- tests/test_factory_triage_example.py (dependency)

## Cloud test matrix
Not read yet.
