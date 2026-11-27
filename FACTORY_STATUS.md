# Factory status (generated, structured data only)

Generated: 2026-11-27T06:55:52Z
Source commit: sha3ac0dc6738e6

## Commits (sha, time)
- sha3ac0dc67 2026-11-27T09:50:00+03:00
- shaedf2ff75 2026-11-27T09:41:12+03:00
- shac0174f32 2026-11-27T07:24:20+03:00
- shaeba41691 2026-11-27T07:19:26+03:00
- sha743f9549 2026-11-27T07:03:45+03:00
- sha4ac497e2 2026-11-27T06:15:57+03:00
- sha81d8fa2c 2026-11-27T06:07:48+03:00
- sha6d783546 2026-11-27T06:07:46+03:00
- sha5fcc1875 2026-11-27T06:07:42+03:00
- sha2b188593 2026-11-27T05:27:20+03:00
- shafacc26ba 2026-11-27T04:45:20+03:00
- shac6c3a133 2026-11-27T04:35:02+03:00
- sha8587a788 2026-11-27T04:30:36+03:00
- sha0627cc20 2026-11-27T04:28:12+03:00
- shad45b3040 2026-11-27T04:25:50+03:00
- sha68184b09 2026-11-27T04:23:19+03:00
- sha42175e35 2026-11-27T04:03:18+03:00
- sha2bb2b0a7 2026-11-27T03:56:13+03:00
- sha17c73552 2026-11-27T03:49:23+03:00
- shaa6989765 2026-11-27T03:47:10+03:00

## Funnel
| step | count |
|---|---|
| accepted | 124 |
| claimed | 1564 |
| coded | 216 |
| found_in_backlog | unknown |
| gate_pass | 210 |
| known_to_loop | 1002 |
| promoted | 207 |
| ready | 38 |
| reviewed | 534 |
| triaged | 798 |

Side counters: blocked=20, parked=0, requeued=14
Tasks now: BLOCKED=20, DONE=68, FAILED=1567, PROMOTED=177, READY=38, RUNNING=1
Accepted: 124
Promoted: 207
Free RAM, GB: 2.04
Telemetry rows: 111430 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 46 | 93172 | 12146 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 13 | 5678 | 452 | 9 | 0 | 9 |
| cohere/north-mini-code-1.0 | 7 | 10515 | 346 | 3 | 0 | 3 |
| google/gemini-3-flash-preview | 70 | 62669 | 8576 | 46 | 45 | 46 |
| google/gemini-3.1-flash-lite | 1829 | 9168262 | 644361 | 157 | 12 | 157 |
| google/gemini-3.1-flash-lite-preview | 683 | 1490335 | 197260 | 138 | 25 | 138 |
| google/gemini-3.5-flash | 60 | 30545 | 1824 | 50 | 46 | 50 |
| google/gemini-3.5-flash-lite | 2331 | 11258719 | 663800 | 339 | 13 | 49 |
| google/gemini-3.6-flash | 154 | 416172 | 20302 | 75 | 29 | 75 |
| google/gemini-3.7-flash | 48 | 9121 | 14 | 47 | 35 | 47 |
| google/gemini-3.8-flash | 44 | 21237 | 15 | 41 | 28 | 41 |
| google/gemini-4-hydrogen | 26 | 2852 | 507 | 25 | 18 | 25 |
| google/gemini-robotics-er-2-preview | 39 | 32055 | 1605 | 29 | 27 | 29 |
| google/gemma-4-26b-a4b-it | 8567 | 6763822 | 1073461 | 5896 | 212 | 4462 |
| google/gemma-4-31b-it | 6441 | 3555045 | 356724 | 5055 | 193 | 4603 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 143 | 750953 | 158909 | 3 | 2 | 3 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 546 | 0 |
| gate | 13288 | 0 |
| infra | 7462 | 0 |
| loop | 16362 | 0 |
| other | 36467 | 2176 |
| promote | 231 | 0 |
| review | 6168 | 3307 |
| run | 30216 | 15083 |
| triage | 690 | 0 |

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
Tests in the cloud: 117
Tests not in the cloud: 156
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
