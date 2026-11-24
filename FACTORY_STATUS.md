# Factory status (generated, structured data only)

Generated: 2026-11-24T04:55:08Z
Source commit: shaae8712334633

## Commits (sha, time)
- shaae871233 2026-11-24T07:54:23+03:00
- sha6a92ba54 2026-11-24T05:48:53+03:00
- sha8e17c41e 2026-11-24T05:43:57+03:00
- sha59aac0f3 2026-11-24T05:37:09+03:00
- sha3e683cb2 2026-11-24T05:32:36+03:00
- shac3311953 2026-11-24T05:25:58+03:00
- shafd6fc201 2026-11-24T04:28:32+03:00
- sha51589267 2026-11-24T04:24:26+03:00
- shaf0542e52 2026-11-24T04:21:51+03:00
- sha45164926 2026-11-24T04:18:21+03:00
- sha5190295b 2026-11-24T04:13:19+03:00
- sha461b8777 2026-11-24T04:08:51+03:00
- shabd95639b 2026-11-24T04:03:29+03:00
- sha216cad7a 2026-11-24T03:57:01+03:00
- shafa3392b2 2026-11-24T03:54:45+03:00
- sha14e9f938 2026-11-24T03:36:21+03:00
- sha776918ad 2026-11-24T03:31:17+03:00
- sha18b8a530 2026-11-24T03:27:18+03:00
- shaf95bd27d 2026-11-24T03:25:46+03:00
- shaa7503929 2026-11-24T03:16:58+03:00

## Funnel
| step | count |
|---|---|
| accepted | 21 |
| claimed | 614 |
| coded | 185 |
| found_in_backlog | unknown |
| gate_pass | 74 |
| known_to_loop | 542 |
| promoted | 70 |
| ready | 87 |
| reviewed | 189 |
| triaged | 365 |

Side counters: blocked=2, parked=0, requeued=7
Tasks now: BLOCKED=2, DONE=68, FAILED=612, PROMOTED=46, READY=87, RUNNING=2
Accepted: 21
Promoted: 70
Free RAM, GB: 4.39
Telemetry rows: 50437 recognised, 0 unrecognised

## Spend per model
| model | calls | tokens_in | tokens_out | usage_unknown | http_429 | errors |
|---|---|---|---|---|---|---|
| cohere/command-a-03-2025 | 36 | 38166 | 9670 | 0 | 0 | 0 |
| cohere/command-a-plus-05-2026 | 12 | 5678 | 452 | 8 | 0 | 8 |
| cohere/north-mini-code-1.0 | 6 | 4159 | 237 | 3 | 0 | 3 |
| google/gemini-3-flash-preview | 39 | 42084 | 7471 | 20 | 19 | 20 |
| google/gemini-3.1-flash-lite | 1620 | 8692402 | 610140 | 84 | 8 | 84 |
| google/gemini-3.1-flash-lite-preview | 354 | 663559 | 128296 | 55 | 16 | 55 |
| google/gemini-3.5-flash | 35 | 30545 | 1824 | 25 | 23 | 25 |
| google/gemini-3.5-flash-lite | 1923 | 10852491 | 630615 | 46 | 13 | 46 |
| google/gemini-3.6-flash | 135 | 414079 | 20196 | 57 | 12 | 57 |
| google/gemini-3.7-flash | 26 | 9121 | 14 | 25 | 14 | 25 |
| google/gemini-3.8-flash | 28 | 21237 | 15 | 25 | 13 | 25 |
| google/gemma-4-26b-a4b-it | 1979 | 1760050 | 326472 | 1303 | 2 | 1303 |
| google/gemma-4-31b-it | 1470 | 770578 | 80418 | 1190 | 2 | 1190 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 130 | 715529 | 156330 | 2 | 2 | 2 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 7275 | 0 |
| infra | 1246 | 0 |
| loop | 7708 | 0 |
| other | 14332 | 0 |
| promote | 86 | 0 |
| review | 2868 | 1412 |
| run | 15968 | 6446 |
| triage | 418 | 0 |

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
Modules: 33
Tests in the cloud: 104
Tests not in the cloud: 123
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
- tests/test_factory_money.py (backlog-id, long-run, owner-words)
- tests/test_factory_need_outline.py (dependency)
- tests/test_factory_neighbours.py (dependency)
- tests/test_factory_no_effect.py (dependency)
- tests/test_factory_other_model.py (dependency)
- tests/test_factory_owner_list.py (backlog-id, call-word, long-run)
- tests/test_factory_paid_critic.py (long-run)
- tests/test_factory_paid_critic_span.py (key)
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
