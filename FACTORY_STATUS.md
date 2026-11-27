# Factory status (generated, structured data only)

Generated: 2026-11-27T16:50:02Z
Source commit: shaf4768919fb16

## Commits (sha, time)
- shaf4768919 2026-11-27T19:40:05+03:00
- shac326ae6c 2026-11-27T19:35:09+03:00
- sha266ee521 2026-11-27T19:32:56+03:00
- shabc090d9c 2026-11-27T18:04:16+03:00
- sha58f59b39 2026-11-27T17:58:27+03:00
- sha709a3d9f 2026-11-27T17:53:27+03:00
- sha4c8d2a48 2026-11-27T17:17:16+03:00
- sha829c2373 2026-11-27T17:14:48+03:00
- shac01269d1 2026-11-27T17:13:22+03:00
- sha9b4f578a 2026-11-27T17:03:04+03:00
- shafaa59f99 2026-11-27T16:59:21+03:00
- sha79baf411 2026-11-27T16:54:50+03:00
- sha22721931 2026-11-27T16:38:03+03:00
- sha922f9c0e 2026-11-27T16:26:00+03:00
- sha25d0eb73 2026-11-27T16:22:41+03:00
- shae995f971 2026-11-27T16:18:12+03:00
- sha43e6e0a7 2026-11-27T15:57:13+03:00
- sha3b82f739 2026-11-27T15:56:18+03:00
- sha8191e540 2026-11-27T15:51:28+03:00
- sha7675a9a2 2026-11-27T15:47:58+03:00

## Funnel
| step | count |
|---|---|
| accepted | 143 |
| claimed | 1730 |
| coded | 229 |
| found_in_backlog | unknown |
| gate_pass | 238 |
| known_to_loop | 1064 |
| promoted | 235 |
| ready | 11 |
| reviewed | 582 |
| triaged | 838 |

Side counters: blocked=0, parked=0, requeued=15
Tasks now: DONE=68, FAILED=1729, PROMOTED=202, READY=11, RUNNING=2
Accepted: 143
Promoted: 235
Free RAM, GB: 4.22
Telemetry rows: 128721 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 56 | 125549 | 14605 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 19 | 9624 | 659 | 13 | 0 | 13 |
| cohere/north-mini-code-1.0 | 16 | 18302 | 3543 | 8 | 0 | 8 |
| google/gemini-3-flash-preview | 122 | 105389 | 12113 | 86 | 45 | 46 |
| google/gemini-3.1-flash-lite | 2389 | 9331418 | 660588 | 659 | 12 | 160 |
| google/gemini-3.1-flash-lite-preview | 1256 | 1673871 | 218270 | 647 | 25 | 142 |
| google/gemini-3.5-flash | 88 | 43899 | 4709 | 74 | 46 | 51 |
| google/gemini-3.5-flash-lite | 3241 | 11564695 | 696562 | 1139 | 13 | 49 |
| google/gemini-3.6-flash | 183 | 429461 | 21657 | 100 | 29 | 77 |
| google/gemini-3.7-flash | 75 | 9121 | 14 | 74 | 35 | 52 |
| google/gemini-3.8-flash | 69 | 21237 | 15 | 66 | 28 | 43 |
| google/gemini-4-hydrogen | 77 | 27174 | 2032 | 68 | 18 | 28 |
| google/gemini-robotics-er-2-preview | 86 | 58488 | 4068 | 69 | 27 | 29 |
| google/gemma-4-26b-a4b-it | 12874 | 7492056 | 1183496 | 9900 | 212 | 4481 |
| google/gemma-4-31b-it | 9675 | 3906884 | 386403 | 8162 | 193 | 4610 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 143 | 750953 | 158909 | 3 | 2 | 3 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 552 | 0 |
| gate | 14105 | 0 |
| infra | 7765 | 0 |
| loop | 17866 | 0 |
| other | 49591 | 11276 |
| promote | 260 | 0 |
| review | 6392 | 3433 |
| run | 31457 | 15725 |
| triage | 733 | 0 |

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
Tests in the cloud: 118
Tests not in the cloud: 159
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
- tests/test_factory_bucket.py (email, long-run)
- tests/test_factory_bucket_review.py (long-run)
- tests/test_factory_calls.py (path)
- tests/test_factory_canary.py (env-path, long-run)
- tests/test_factory_cannot_scope.py (env-path)
- tests/test_factory_channels.py (long-run)
- tests/test_factory_choke.py (dependency)
- tests/test_factory_class_cases.py (backlog-id, call-word, long-run, path, phone)
- tests/test_factory_closures.py (backlog-id)
- tests/test_factory_cloud_path.py (email)
- tests/test_factory_cloud_product.py (long-run)
- tests/test_factory_cloud_sizing.py (dependency)
- tests/test_factory_context_pinned.py (path)
- tests/test_factory_contract_intake.py (email)
- tests/test_factory_cool.py (backlog-id, long-run)
- tests/test_factory_critic_gate_told.py (dependency)
- tests/test_factory_critic_kinds.py (dependency)
- tests/test_factory_critic_prior.py (owner-words)
- tests/test_factory_critic_rubric.py (dependency)
- tests/test_factory_ctx.py (dependency)
- tests/test_factory_culprit.py (dependency)
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
- tests/test_factory_fac68b.py (long-run)
- tests/test_factory_fanout.py (long-run, path)
- tests/test_factory_feed.py (backlog-id, call-word)
- tests/test_factory_flow.py (long-run)
- tests/test_factory_gate_neighbour_base.py (dependency)
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
- tests/test_factory_part1.py (backlog-id, path)
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
- tests/test_factory_slicer_pool.py (backlog-id, env-path, long-run)
- tests/test_factory_slim_worker.py (long-run)
- tests/test_factory_solver.py (path)
- tests/test_factory_source_guard.py (dependency)
- tests/test_factory_spread.py (backlog-id, long-run)
- tests/test_factory_status.py (dependency)
- tests/test_factory_supply.py (dependency)
- tests/test_factory_supply_rows.py (backlog-id)
- tests/test_factory_survive.py (path, pid-port, user-path)
- tests/test_factory_sweep_refresh.py (dependency)
- tests/test_factory_sync.py (backlog-id, email)
- tests/test_factory_t2.py (dependency)
- tests/test_factory_t5.py (backlog-id)
- tests/test_factory_tcode.py (dependency)
- tests/test_factory_test_audit.py (dependency)
- tests/test_factory_test_order.py (dependency)
- tests/test_factory_texts.py (dependency)
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
