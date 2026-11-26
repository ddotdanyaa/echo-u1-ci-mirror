# Factory status (generated, structured data only)

Generated: 2026-11-26T12:20:16Z
Source commit: shaa05af52c3e34

## Commits (sha, time)
- shaa05af52c 2026-11-26T15:19:15+03:00
- shaf109dba0 2026-11-26T15:11:20+03:00
- sha115139a9 2026-11-26T15:10:27+03:00
- sha883cca5a 2026-11-26T15:09:55+03:00
- sha4230eb86 2026-11-26T15:09:09+03:00
- sha934e7591 2026-11-26T15:08:10+03:00
- sha4c2e05e6 2026-11-26T15:05:03+03:00
- sha2e75a9df 2026-11-26T15:04:27+03:00
- shade3db606 2026-11-26T14:56:25+03:00
- sha76bb9916 2026-11-26T14:48:55+03:00
- sha7d62a709 2026-11-26T14:44:17+03:00
- sha548033e2 2026-11-26T12:01:23+03:00
- sha3b2dca2c 2026-11-26T11:55:29+03:00
- shaf9262f47 2026-11-26T11:42:24+03:00
- sha45d5b65f 2026-11-26T11:37:13+03:00
- sha661879da 2026-11-26T10:27:11+03:00
- sha9abe9f8c 2026-11-26T10:23:22+03:00
- sha5eb6d410 2026-11-26T10:23:02+03:00
- sha59021a30 2026-11-26T10:23:01+03:00
- shaffb0336e 2026-11-26T10:23:00+03:00

## Funnel
| step | count |
|---|---|
| accepted | 79 |
| claimed | 1327 |
| coded | 199 |
| found_in_backlog | unknown |
| gate_pass | 150 |
| known_to_loop | 874 |
| promoted | 146 |
| ready | 29 |
| reviewed | 404 |
| triaged | 680 |

Side counters: blocked=20, parked=0, requeued=11
Tasks now: BLOCKED=20, DONE=68, FAILED=1362, PROMOTED=116, READY=29, RUNNING=2
Accepted: 79
Promoted: 146
Free RAM, GB: 1.69
Telemetry rows: 92978 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 46 | 93172 | 12146 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 13 | 5678 | 452 | 9 | 0 | 9 |
| cohere/north-mini-code-1.0 | 7 | 10515 | 346 | 3 | 0 | 3 |
| google/gemini-3-flash-preview | 68 | 62669 | 8576 | 44 | 43 | 44 |
| google/gemini-3.1-flash-lite | 1712 | 8834878 | 621315 | 139 | 10 | 139 |
| google/gemini-3.1-flash-lite-preview | 511 | 1012808 | 156586 | 116 | 18 | 116 |
| google/gemini-3.5-flash | 55 | 30545 | 1824 | 45 | 42 | 45 |
| google/gemini-3.5-flash-lite | 2009 | 11157331 | 654681 | 49 | 13 | 49 |
| google/gemini-3.6-flash | 152 | 416172 | 20302 | 73 | 27 | 73 |
| google/gemini-3.7-flash | 42 | 9121 | 14 | 41 | 29 | 41 |
| google/gemini-3.8-flash | 42 | 21237 | 15 | 39 | 26 | 39 |
| google/gemini-4-hydrogen | 26 | 2852 | 507 | 25 | 18 | 25 |
| google/gemini-robotics-er-2-preview | 37 | 32055 | 1605 | 27 | 25 | 27 |
| google/gemma-4-26b-a4b-it | 6408 | 5767428 | 982678 | 4075 | 74 | 4075 |
| google/gemma-4-31b-it | 5482 | 3165464 | 328879 | 4224 | 58 | 4224 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 140 | 744121 | 158302 | 3 | 2 | 3 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 546 | 0 |
| gate | 11485 | 0 |
| infra | 5945 | 0 |
| loop | 13742 | 0 |
| other | 27840 | 0 |
| promote | 167 | 0 |
| review | 4819 | 2423 |
| run | 27831 | 14392 |
| triage | 603 | 0 |

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
Modules: 38
Tests in the cloud: 115
Tests not in the cloud: 148
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_503.py (backlog-id, long-run)
- tests/test_factory_architect.py (backlog-id, email, env-path, path)
- tests/test_factory_ask_lock.py (backlog-id)
- tests/test_factory_asked_code.py (dependency)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_autofeed.py (backlog-id)
- tests/test_factory_base_cache.py (dependency)
- tests/test_factory_base_near.py (email, short-name)
- tests/test_factory_base_unsettled.py (dependency)
- tests/test_factory_bisect_loop.py (backlog-id)
- tests/test_factory_calls.py (path)
- tests/test_factory_canary.py (env-path, long-run)
- tests/test_factory_cannot_scope.py (env-path)
- tests/test_factory_channels.py (dependency)
- tests/test_factory_class_cases.py (backlog-id, call-word, long-run, path, phone)
- tests/test_factory_closures.py (backlog-id)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_cloud_sizing.py (dependency)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_contract_intake.py (dependency)
- tests/test_factory_cool.py (backlog-id, long-run)
- tests/test_factory_critic_gate_told.py (dependency)
- tests/test_factory_critic_kinds.py (dependency)
- tests/test_factory_critic_prior.py (owner-words)
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
- tests/test_factory_flow.py (long-run)
- tests/test_factory_gate_red_reuse.py (email)
- tests/test_factory_gate_unrun.py (dependency)
- tests/test_factory_gemma.py (dependency)
- tests/test_factory_gemma2.py (long-run)
- tests/test_factory_gemma3.py (long-run)
- tests/test_factory_gemma4.py (dependency)
- tests/test_factory_gemma5.py (dependency)
- tests/test_factory_gh_limit.py (dependency)
- tests/test_factory_gslice.py (dependency)
- tests/test_factory_guard.py (backlog-id)
- tests/test_factory_guard_ids.py (backlog-id)
- tests/test_factory_hard.py (long-run)
- tests/test_factory_head.py (long-run)
- tests/test_factory_hypo.py (dependency)
- tests/test_factory_hypo2.py (dependency)
- tests/test_factory_hypo3.py (dependency)
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
- tests/test_factory_loop_revert.py (email)
- tests/test_factory_loop_watch.py (long-run)
- tests/test_factory_lost_rows.py (dependency)
- tests/test_factory_marker_self.py (long-run)
- tests/test_factory_mem.py (long-run)
- tests/test_factory_metrics.py (owner-words)
- tests/test_factory_money.py (backlog-id, long-run, owner-words)
- tests/test_factory_need_outline.py (dependency)
- tests/test_factory_neighbours.py (dependency)
- tests/test_factory_no_effect.py (dependency)
- tests/test_factory_noxml.py (long-run)
- tests/test_factory_optimistic.py (backlog-id)
- tests/test_factory_optimistic_fix3.py (dependency)
- tests/test_factory_other_model.py (dependency)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_package.py (email)
- tests/test_factory_paid_critic.py (long-run, owner-words)
- tests/test_factory_paid_critic_span.py (key)
- tests/test_factory_part2.py (email)
- tests/test_factory_part2b.py (dependency)
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
- tests/test_factory_repair2.py (path)
- tests/test_factory_review_grounding.py (backlog-id)
- tests/test_factory_review_wait.py (backlog-id, long-run)
- tests/test_factory_round7.py (backlog-id, call-word, owner-name, path, phone, user-path)
- tests/test_factory_router_table.py (long-run)
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
- tests/test_factory_solver.py (path)
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
- tests/test_factory_tick_cost.py (backlog-id)
- tests/test_factory_tournament.py (owner-words)
- tests/test_factory_tournament_gate.py (dependency)
- tests/test_factory_tree.py (dependency)
- tests/test_factory_triage.py (backlog-id, call-word, email, env-path, key, phone)
- tests/test_factory_triage_example.py (dependency)
- tests/test_factory_vgs.py (dependency)
- tests/test_factory_vgs3.py (backlog-id, path)
- tests/test_factory_w_free.py (dependency)
- tests/test_factory_w_path.py (email, long-run)
- tests/test_factory_wiring.py (dependency)
- tests/test_factory_worker_exception_return.py (backlog-id)

## Cloud test matrix
Not read yet.
