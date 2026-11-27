# Factory status (generated, structured data only)

Generated: 2026-11-27T21:45:44Z
Source commit: shadbd3657862ff

## Commits (sha, time)
- shadbd36578 2026-11-28T00:45:01+03:00
- shaec9ebb76 2026-11-28T00:23:06+03:00
- shab6dd10b5 2026-11-28T00:21:42+03:00
- sha5299d91b 2026-11-28T00:04:34+03:00
- sha22c1cf65 2026-11-27T23:45:48+03:00
- sha4b1a7126 2026-11-27T23:41:04+03:00
- shaada9ad60 2026-11-27T23:29:52+03:00
- shadaa5d5e1 2026-11-27T23:26:38+03:00
- sha2df2839b 2026-11-27T23:18:14+03:00
- sha19b8775d 2026-11-27T23:16:14+03:00
- sha37e687d4 2026-11-27T23:13:38+03:00
- sha1d866176 2026-11-27T23:13:24+03:00
- sha1253a89a 2026-11-27T23:04:44+03:00
- sha937df3fb 2026-11-27T23:04:09+03:00
- shabbbb709f 2026-11-27T23:00:15+03:00
- shaf967f954 2026-11-27T22:59:10+03:00
- shaef620c5b 2026-11-27T22:51:37+03:00
- shaa359820d 2026-11-27T22:37:36+03:00
- sha986eda18 2026-11-27T22:35:51+03:00
- sha1adc1177 2026-11-27T22:34:01+03:00

## Funnel
| step | count |
|---|---|
| accepted | 151 |
| claimed | 1787 |
| coded | 231 |
| found_in_backlog | unknown |
| gate_pass | 255 |
| known_to_loop | 1071 |
| promoted | 250 |
| ready | 19 |
| reviewed | 601 |
| triaged | 838 |

Side counters: blocked=0, parked=0, requeued=17
Tasks now: DONE=68, FAILED=1767, PROMOTED=217, READY=19, RUNNING=1
Accepted: 151
Promoted: 250
Free RAM, GB: 4.87
Telemetry rows: 136709 recognised, 0 unrecognised

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
| google/gemma-4-26b-a4b-it | 15127 | 7959810 | 1250757 | 11992 | 212 | 4485 |
| google/gemma-4-31b-it | 12354 | 4184704 | 408758 | 10744 | 193 | 4618 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 143 | 750953 | 158909 | 3 | 2 | 3 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 552 | 0 |
| gate | 14468 | 0 |
| infra | 8009 | 0 |
| loop | 18529 | 0 |
| other | 55697 | 15938 |
| promote | 277 | 0 |
| review | 6493 | 3485 |
| run | 31921 | 15943 |
| triage | 763 | 0 |

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
Tests not in the cloud: 164
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_503.py (backlog-id, long-run)
- tests/test_factory_architect.py (backlog-id, email, env-path, path)
- tests/test_factory_architect_sub_rung.py (long-run)
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
- tests/test_factory_green_proof.py (backlog-id)
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
- tests/test_factory_j4_cards.py (dependency)
- tests/test_factory_keep.py (dependency)
- tests/test_factory_keep_cards.py (backlog-id)
- tests/test_factory_kilo_rpm.py (dependency)
- tests/test_factory_ladder_top.py (dependency)
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
- tests/test_factory_phantom.py (backlog-id)
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
