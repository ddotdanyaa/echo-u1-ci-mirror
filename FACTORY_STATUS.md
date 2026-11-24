# Factory status (generated, structured data only)

Generated: 2026-11-24T10:42:06Z
Source commit: sha3fb5bd7867cc

## Commits (sha, time)
- sha3fb5bd78 2026-11-24T13:40:12+03:00
- shaba80191e 2026-11-24T13:12:08+03:00
- sha0d45d329 2026-11-24T13:10:31+03:00
- sha7f96bcfa 2026-11-24T13:03:15+03:00
- shaf3375ccf 2026-11-24T12:12:37+03:00
- sha1e231616 2026-11-24T12:00:18+03:00
- sha65d9fbbe 2026-11-24T11:52:42+03:00
- sha2d790425 2026-11-24T11:39:12+03:00
- shaf3558912 2026-11-24T11:02:35+03:00
- sha521dc4cb 2026-11-24T10:48:49+03:00
- sha22ec8759 2026-11-24T10:44:15+03:00
- sha6fa08fee 2026-11-24T10:40:42+03:00
- sha88f4062c 2026-11-24T10:39:30+03:00
- shaed96f635 2026-11-24T10:22:27+03:00
- shad3e11270 2026-11-24T10:20:47+03:00
- shaa579e0bc 2026-11-24T10:18:13+03:00
- sha1435c225 2026-11-24T10:13:49+03:00
- shaa3f487e5 2026-11-24T10:13:37+03:00
- shafb3cf053 2026-11-24T10:09:27+03:00
- shadf8595e0 2026-11-24T10:07:23+03:00

## Funnel
| step | count |
|---|---|
| accepted | 28 |
| claimed | 699 |
| coded | 188 |
| found_in_backlog | unknown |
| gate_pass | 82 |
| known_to_loop | 551 |
| promoted | 77 |
| ready | 51 |
| reviewed | 199 |
| triaged | 375 |

Side counters: blocked=6, parked=0, requeued=9
Tasks now: BLOCKED=6, DONE=68, FAILED=715, PROMOTED=53, READY=51, RUNNING=18
Accepted: 28
Promoted: 77
Free RAM, GB: 2.57
Telemetry rows: 56229 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 45 | 84775 | 11984 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 12 | 5678 | 452 | 8 | 0 | 8 |
| cohere/north-mini-code-1.0 | 7 | 10515 | 346 | 3 | 0 | 3 |
| google/gemini-3-flash-preview | 39 | 42084 | 7471 | 20 | 19 | 20 |
| google/gemini-3.1-flash-lite | 1642 | 8724535 | 612702 | 99 | 8 | 99 |
| google/gemini-3.1-flash-lite-preview | 378 | 711082 | 132036 | 63 | 16 | 63 |
| google/gemini-3.5-flash | 35 | 30545 | 1824 | 25 | 23 | 25 |
| google/gemini-3.5-flash-lite | 1965 | 10992287 | 643428 | 48 | 13 | 48 |
| google/gemini-3.6-flash | 135 | 414079 | 20196 | 57 | 12 | 57 |
| google/gemini-3.7-flash | 26 | 9121 | 14 | 25 | 14 | 25 |
| google/gemini-3.8-flash | 28 | 21237 | 15 | 25 | 13 | 25 |
| google/gemini-4-hydrogen | 3 | 0 | 0 | 3 | 0 | 3 |
| google/gemini-robotics-er-2-preview | 2 | 5373 | 134 | 0 | 0 | 0 |
| google/gemma-4-26b-a4b-it | 2708 | 2154080 | 397101 | 1847 | 9 | 1847 |
| google/gemma-4-31b-it | 2126 | 969554 | 99725 | 1758 | 7 | 1758 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 130 | 715529 | 156330 | 2 | 2 | 2 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 7777 | 0 |
| infra | 1456 | 0 |
| loop | 8272 | 0 |
| other | 16528 | 0 |
| promote | 95 | 0 |
| review | 3193 | 1519 |
| run | 17943 | 7827 |
| triage | 429 | 0 |

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
- g-gemini-4-hydrogen
- g-gemini-robotics-er-2-preview
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
- google/gemini-4-hydrogen
- google/gemini-robotics-er-2-preview
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
- k2-gemini-4-hydrogen
- k2-gemini-robotics-er-2-preview
- openrouter/nvidia/nemotron-3-ultra-550b-a55b:free
- or-nemotron-3-ultra

## Published files
Modules: 34
Tests in the cloud: 108
Tests not in the cloud: 132
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_503.py (backlog-id, long-run)
- tests/test_factory_architect.py (backlog-id, email, env-path, path)
- tests/test_factory_asked_code.py (dependency)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_base_cache.py (dependency)
- tests/test_factory_base_near.py (email, short-name)
- tests/test_factory_base_unsettled.py (dependency)
- tests/test_factory_bisect_loop.py (backlog-id)
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
- tests/test_factory_dry_architect.py (long-run)
- tests/test_factory_dry_channels.py (long-run)
- tests/test_factory_dry_count.py (long-run)
- tests/test_factory_dry_loop.py (backlog-id)
- tests/test_factory_dry_review.py (long-run)
- tests/test_factory_echo.py (backlog-id, long-run)
- tests/test_factory_ensemble_retry.py (long-run)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_fanout.py (long-run)
- tests/test_factory_feed.py (backlog-id, call-word)
- tests/test_factory_feed2_fix1.py (long-run)
- tests/test_factory_flow.py (long-run)
- tests/test_factory_gate_unrun.py (dependency)
- tests/test_factory_gemma.py (dependency)
- tests/test_factory_gemma2.py (long-run)
- tests/test_factory_gemma3.py (long-run)
- tests/test_factory_gemma4.py (dependency)
- tests/test_factory_gemma5.py (dependency)
- tests/test_factory_gslice.py (dependency)
- tests/test_factory_guard.py (backlog-id)
- tests/test_factory_guard_ids.py (backlog-id)
- tests/test_factory_hard.py (long-run)
- tests/test_factory_hypo.py (dependency)
- tests/test_factory_hypo2.py (dependency)
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
- tests/test_factory_lost_rows.py (dependency)
- tests/test_factory_marker_self.py (long-run)
- tests/test_factory_mem.py (long-run)
- tests/test_factory_metrics.py (owner-words)
- tests/test_factory_money.py (backlog-id, long-run, owner-words)
- tests/test_factory_need_outline.py (dependency)
- tests/test_factory_neighbours.py (dependency)
- tests/test_factory_no_effect.py (dependency)
- tests/test_factory_optimistic.py (backlog-id)
- tests/test_factory_optimistic_fix3.py (dependency)
- tests/test_factory_other_model.py (dependency)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_paid_critic.py (long-run)
- tests/test_factory_paid_critic_span.py (key)
- tests/test_factory_part2.py (dependency)
- tests/test_factory_path.py (backlog-id)
- tests/test_factory_pool_runner.py (dependency)
- tests/test_factory_port_wiring.py (dependency)
- tests/test_factory_prio.py (dependency)
- tests/test_factory_prio2.py (dependency)
- tests/test_factory_prio3.py (dependency)
- <redacted-name> (backlog-id, long-run)
- tests/test_factory_quota_wire.py (dependency)
- tests/test_factory_redrow.py (key, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_registry.py (backlog-id, owner-words)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_release.py (backlog-id)
- tests/test_factory_release_run.py (dependency)
- tests/test_factory_review_wait.py (backlog-id, long-run)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_router_wiring.py (dependency)
- tests/test_factory_runtime.py (backlog-id, long-run)
- tests/test_factory_seams.py (dependency)
- tests/test_factory_see.py (long-run)
- tests/test_factory_self_loop.py (backlog-id)
- tests/test_factory_selfgate.py (dependency)
- tests/test_factory_selfgate_scan.py (dependency)
- tests/test_factory_slicer.py (backlog-id, call-word, email, key, long-run)
- tests/test_factory_slicer_pool.py (env-path, long-run)
- tests/test_factory_slim_worker.py (long-run)
- tests/test_factory_source_guard.py (dependency)
- tests/test_factory_status.py (dependency)
- tests/test_factory_supply.py (dependency)
- tests/test_factory_supply_rows.py (backlog-id)
- tests/test_factory_survive.py (path, pid-port, user-path)
- tests/test_factory_sweep_refresh.py (dependency)
- tests/test_factory_sync.py (backlog-id, email)
- tests/test_factory_tcode.py (dependency)
- tests/test_factory_test_audit.py (dependency)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_think.py (long-run)
- tests/test_factory_tournament.py (dependency)
- tests/test_factory_tournament_gate.py (dependency)
- tests/test_factory_tree.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone)
- tests/test_factory_triage_example.py (dependency)
- tests/test_factory_vgs.py (dependency)
- tests/test_factory_vgs3.py (backlog-id, path)
- tests/test_factory_w_free.py (dependency)
- tests/test_factory_wiring.py (dependency)
- tests/test_factory_worker_exception_return.py (backlog-id)

## Cloud test matrix
Not read yet.
