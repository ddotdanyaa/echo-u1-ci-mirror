# Factory status (generated, structured data only)

Generated: 2026-11-23T13:13:28Z
Source commit: sha1448123d5be2

## Commits (sha, time)
- sha1448123d 2026-11-23T16:07:26+03:00
- sha228ad7ee 2026-11-23T16:02:57+03:00
- sha0fb3fc57 2026-11-23T15:56:31+03:00
- sha382b8742 2026-11-23T15:52:40+03:00
- shacfeb650a 2026-11-23T15:48:42+03:00
- sha164ae35a 2026-11-23T15:44:21+03:00
- sha5c67e438 2026-11-23T15:42:39+03:00
- sha00b3e0c2 2026-11-23T15:36:47+03:00
- shadfd1091a 2026-11-23T15:33:13+03:00
- shafb8b8ab7 2026-11-23T14:47:43+03:00
- sha7e0c99f6 2026-11-23T14:43:20+03:00
- sha71e89811 2026-11-23T14:39:33+03:00
- shad47ba2b4 2026-11-23T14:36:17+03:00
- sha5a63e6a4 2026-11-23T14:34:42+03:00
- sha60e74ac2 2026-11-23T14:34:16+03:00
- sha53eee43c 2026-11-23T14:32:54+03:00
- sha24500403 2026-11-23T14:31:02+03:00
- sha213f7527 2026-11-23T14:27:49+03:00
- shaa1ddac8b 2026-11-23T14:13:20+03:00
- sha731f1824 2026-11-23T14:08:28+03:00

## Funnel
| step | count |
|---|---|
| accepted | 16 |
| claimed | 393 |
| coded | 183 |
| found_in_backlog | unknown |
| gate_pass | 67 |
| known_to_loop | 460 |
| promoted | 63 |
| ready | 99 |
| reviewed | 164 |
| triaged | 295 |

Side counters: blocked=0, parked=0, requeued=7
Tasks now: DONE=68, FAILED=469, PROMOTED=39, READY=99, RUNNING=3
Accepted: 16
Promoted: 63
Free RAM, GB: 4.58
Telemetry rows: 34115 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 36 | 38166 | 9670 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 12 | 5678 | 452 | 8 | 0 | 8 |
| cohere/north-mini-code-1.0 | 6 | 4159 | 237 | 3 | 0 | 3 |
| google/gemini-3-flash-preview | 31 | 37167 | 6757 | 14 | 13 | 14 |
| google/gemini-3.1-flash-lite | 1606 | 8686947 | 609727 | 73 | 4 | 73 |
| google/gemini-3.1-flash-lite-preview | 290 | 580835 | 93042 | 30 | 8 | 30 |
| google/gemini-3.5-flash | 34 | 30545 | 1824 | 24 | 22 | 24 |
| google/gemini-3.5-flash-lite | 1920 | 10852491 | 630615 | 43 | 10 | 43 |
| google/gemini-3.6-flash | 134 | 414079 | 20196 | 56 | 11 | 56 |
| google/gemini-3.7-flash | 22 | 9121 | 14 | 21 | 10 | 21 |
| google/gemini-3.8-flash | 24 | 21237 | 15 | 21 | 9 | 21 |
| google/gemma-4-26b-a4b-it | 281 | 438783 | 37373 | 179 | 0 | 179 |
| google/gemma-4-31b-it | 273 | 243011 | 8846 | 206 | 0 | 206 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 115 | 663252 | 151232 | 2 | 2 | 2 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 5370 | 0 |
| infra | 882 | 0 |
| loop | 5799 | 0 |
| other | 7736 | 0 |
| promote | 79 | 0 |
| review | 2136 | 1163 |
| run | 11201 | 3686 |
| triage | 376 | 0 |

## Channels (model ids)
- 1db4ab-gemini-3-8-flash
- co-command-a
- co-command-a-plus
- co-north-mini-code
- cohere/command-a-03-2025
- cohere/command-a-plus-05-2026
- cohere/north-mini-code-1.0
- g-3-1-flash-lite
- g-3-5-flash-lite
- g-3-6-flash
- g-gemini-3-1-flash-lite-preview
- g-gemini-3-5-flash
- g-gemini-3-7-flash
- g-gemini-3-8-flash
- g-gemini-3-flash-preview
- g-gemma-4-26b
- g-gemma-4-31b
- google/gemini-3-flash-preview
- google/gemini-3.1-flash-lite
- google/gemini-3.1-flash-lite-preview
- google/gemini-3.5-flash
- google/gemini-3.5-flash-lite
- google/gemini-3.6-flash
- google/gemini-3.7-flash
- google/gemini-3.8-flash
- google/gemma-4-26b-a4b-it
- google/gemma-4-31b-it
- k2-g-3-1-flash-lite
- k2-g-3-5-flash-lite
- k2-g-3-6-flash
- k2-g-gemma-4-26b
- k2-g-gemma-4-31b
- k2-gemini-3-1-flash-lite-preview
- k2-gemini-3-5-flash
- k2-gemini-3-7-flash
- k2-gemini-3-flash-preview
- openrouter/nvidia/nemotron-3-ultra-550b-a55b:free
- or-nemotron-3-ultra

## Published files
Modules: 29
Tests in the cloud: 100
Tests not in the cloud: 95
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_503.py (backlog-id, long-run)
- tests/test_factory_architect.py (backlog-id, env-path, path)
- tests/test_factory_asked_code.py (dependency)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_base_cache.py (dependency)
- tests/test_factory_base_near.py (email, short-name)
- tests/test_factory_base_unsettled.py (dependency)
- tests/test_factory_canary.py (env-path, long-run)
- tests/test_factory_cannot_scope.py (env-path)
- tests/test_factory_channels.py (dependency)
- tests/test_factory_class_cases.py (backlog-id, call-word, long-run, path, phone)
- tests/test_factory_closures.py (backlog-id)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_cloud_sizing.py (dependency)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_cool.py (backlog-id, long-run)
- tests/test_factory_critic_gate_told.py (dependency)
- tests/test_factory_critic_kinds.py (dependency)
- tests/test_factory_critic_prior.py (dependency)
- tests/test_factory_critic_rubric.py (dependency)
- tests/test_factory_ctx.py (dependency)
- tests/test_factory_debt.py (long-run)
- tests/test_factory_decompose.py (call-word, email)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_fanout.py (long-run)
- tests/test_factory_feed.py (backlog-id, call-word)
- tests/test_factory_gate_unrun.py (dependency)
- tests/test_factory_hard.py (long-run)
- tests/test_factory_intake.py (call-word, pid-port)
- tests/test_factory_intake_merge.py (dependency)
- tests/test_factory_keep.py (dependency)
- tests/test_factory_keep_cards.py (backlog-id)
- tests/test_factory_kilo_rpm.py (dependency)
- tests/test_factory_light_squeezed.py (path)
- tests/test_factory_links.py (backlog-id, call-word, key, long-run)
- tests/test_factory_loop_answers.py (backlog-id, call-word)
- tests/test_factory_loop_answers2.py (backlog-id, call-word, env-path, path, phone, user-path)
- tests/test_factory_loop_answers3.py (dependency)
- tests/test_factory_loop_channel_brake.py (long-run)
- tests/test_factory_loop_core2.py (dependency)
- tests/test_factory_loop_core3.py (long-run)
- tests/test_factory_loop_d8c.py (dependency)
- tests/test_factory_loop_d8d.py (backlog-id, call-word, key, long-run, phone)
- tests/test_factory_loop_r7.py (dependency)
- tests/test_factory_loop_r7b.py (dependency)
- tests/test_factory_loop_watch.py (long-run)
- tests/test_factory_marker_self.py (long-run)
- tests/test_factory_metrics.py (owner-words)
- tests/test_factory_need_outline.py (dependency)
- tests/test_factory_neighbours.py (dependency)
- tests/test_factory_no_effect.py (dependency)
- tests/test_factory_other_model.py (dependency)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_paid_critic.py (dependency)
- tests/test_factory_paid_critic_span.py (key)
- tests/test_factory_path.py (backlog-id)
- tests/test_factory_pool_runner.py (dependency)
- tests/test_factory_port_wiring.py (dependency)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_quota_wire.py (dependency)
- tests/test_factory_redrow.py (key, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_registry.py (backlog-id, owner-words)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_release.py (backlog-id)
- tests/test_factory_release_run.py (dependency)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_router_wiring.py (dependency)
- tests/test_factory_runtime.py (backlog-id, long-run)
- tests/test_factory_seams.py (dependency)
- tests/test_factory_self_loop.py (backlog-id)
- tests/test_factory_selfgate.py (dependency)
- tests/test_factory_selfgate_scan.py (dependency)
- tests/test_factory_slicer.py (backlog-id, call-word, email, key, long-run)
- tests/test_factory_slicer_pool.py (env-path, long-run)
- tests/test_factory_slim_worker.py (long-run)
- tests/test_factory_source_guard.py (dependency)
- tests/test_factory_status.py (dependency)
- tests/test_factory_supply.py (dependency)
- tests/test_factory_survive.py (path, pid-port, user-path)
- tests/test_factory_sync.py (backlog-id, email)
- tests/test_factory_tcode.py (dependency)
- tests/test_factory_test_audit.py (dependency)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_tournament.py (dependency)
- tests/test_factory_tournament_gate.py (dependency)
- tests/test_factory_tree.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone)
- tests/test_factory_triage_example.py (dependency)
- tests/test_factory_wiring.py (dependency)
- tests/test_factory_worker_exception_return.py (backlog-id)

## Cloud test matrix
Not read yet.
