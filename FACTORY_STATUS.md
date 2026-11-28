# Factory status (generated, structured data only)

Generated: 2026-11-28T11:34:55Z
Source commit: shaae4875899d7f

## Commits (sha, time)
- shaae487589 2026-11-28T14:33:12+03:00
- sha53d9867f 2026-11-28T14:29:33+03:00
- sha09ce3338 2026-11-28T13:22:57+03:00
- sha44cdfa87 2026-11-28T13:10:50+03:00
- shae54b96f2 2026-11-28T12:55:49+03:00
- sha1cae6075 2026-11-28T12:51:56+03:00
- shada5d4e0b 2026-11-28T11:25:16+03:00
- shac7c98e1b 2026-11-28T11:17:50+03:00
- shaf3b9aa3e 2026-11-28T11:17:02+03:00
- shaf5a9e1a0 2026-11-28T10:23:51+03:00
- shab9a7648a 2026-11-28T10:13:18+03:00
- shaa309904d 2026-11-28T10:02:17+03:00
- shaa4cdee6f 2026-11-28T09:55:12+03:00
- sha749e0970 2026-11-28T09:54:59+03:00
- sha74458dfe 2026-11-28T09:51:19+03:00
- sha90420fa5 2026-11-28T09:51:09+03:00
- shaa78e7d1a 2026-11-28T09:18:48+03:00
- sha3936ada8 2026-11-28T09:04:57+03:00
- sha552c4b4b 2026-11-28T08:55:43+03:00
- shaf13f272e 2026-11-28T08:49:45+03:00

## Funnel
| step | count |
|---|---|
| accepted | 208 |
| claimed | 2115 |
| coded | 231 |
| found_in_backlog | unknown |
| gate_pass | 328 |
| known_to_loop | 1123 |
| promoted | 322 |
| ready | 6 |
| reviewed | 744 |
| triaged | 872 |

Side counters: blocked=3, parked=0, requeued=21
Tasks now: BLOCKED=3, DONE=68, FAILED=2027, PROMOTED=288, READY=6, RUNNING=14
Accepted: 208
Promoted: 322
Free RAM, GB: 2.58
Telemetry rows: 163043 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 56 | 125549 | 14605 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 20 | 9624 | 659 | 14 | 0 | 14 |
| cohere/north-mini-code-1.0 | 17 | 18302 | 3543 | 9 | 0 | 9 |
| google/gemini-3-flash-preview | 151 | 129344 | 12774 | 111 | 45 | 46 |
| google/gemini-3.1-flash-lite | 2928 | 9780978 | 683438 | 1097 | 12 | 164 |
| google/gemini-3.1-flash-lite-preview | 1729 | 2279388 | 247684 | 986 | 25 | 150 |
| google/gemini-3.5-flash | 114 | 60502 | 5115 | 96 | 46 | 51 |
| google/gemini-3.5-flash-lite | 3911 | 12197938 | 712133 | 1677 | 13 | 49 |
| google/gemini-3.6-flash | 212 | 451033 | 22019 | 126 | 29 | 77 |
| google/gemini-3.7-flash | 93 | 9121 | 14 | 92 | 35 | 52 |
| google/gemini-3.8-flash | 88 | 21237 | 15 | 85 | 28 | 44 |
| google/gemini-4-hydrogen | 120 | 34543 | 2187 | 109 | 18 | 28 |
| google/gemini-robotics-er-2-preview | 131 | 76020 | 4474 | 111 | 27 | 29 |
| google/gemma-4-26b-a4b-it | 21001 | 9727147 | 1469198 | 17219 | 212 | 4502 |
| google/gemma-4-31b-it | 17818 | 5238076 | 483305 | 15867 | 193 | 4633 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 173 | 846691 | 170279 | 3 | 2 | 3 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 554 | 0 |
| gate | 16143 | 0 |
| infra | 8614 | 0 |
| loop | 20731 | 0 |
| other | 74528 | 27751 |
| promote | 353 | 0 |
| review | 7344 | 4024 |
| run | 33924 | 16852 |
| triage | 852 | 0 |

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
Tests in the cloud: 126
Tests not in the cloud: 174
- tests/test_agent_factory.py (backlog-id, call-word, env-path, long-run, pid-port)
- tests/test_factory_503.py (backlog-id, long-run)
- tests/test_factory_architect.py (backlog-id, email, env-path, path)
- tests/test_factory_architect_sub_rung.py (long-run)
- tests/test_factory_ask_lock.py (backlog-id)
- tests/test_factory_asked_code.py (dependency)
- tests/test_factory_asked_memory.py (backlog-id)
- tests/test_factory_author_talk.py (long-run)
- tests/test_factory_author_try.py (long-run)
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
- tests/test_factory_free_code_proof.py (long-run)
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
- tests/test_factory_import_private_secrets_only.py (backlog-id, call-word, env-path, phone)
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
- tests/test_factory_lost_fingerprint.py (dependency)
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
- tests/test_factory_red_precheck.py (long-run)
- tests/test_factory_redrow.py (key, long-run)
- tests/test_factory_regex_lock.py (call-word, key)
- tests/test_factory_registry.py (backlog-id, owner-words)
- tests/test_factory_reject_apply.py (dependency)
- tests/test_factory_reject_note.py (dependency)
- tests/test_factory_rel_closed.py (backlog-id)
- tests/test_factory_rel_lost.py (dependency)
- tests/test_factory_release.py (backlog-id)
- tests/test_factory_release_run.py (dependency)
- tests/test_factory_repair2.py (path)
- tests/test_factory_review_claim.py (dependency)
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
- tests/test_factory_test_id.py (backlog-id)
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
