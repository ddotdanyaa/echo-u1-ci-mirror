# Factory status (generated, structured data only)

Generated: 2026-11-23T20:54:34Z
Source commit: shafd4839b91f75

## Commits (sha, time)
- shafd4839b9 2026-11-23T23:53:33+03:00
- sha860d6a0c 2026-11-23T23:45:47+03:00
- sha5e794160 2026-11-23T23:31:26+03:00
- shab70fb9a5 2026-11-23T23:07:54+03:00
- sha49e13840 2026-11-23T23:02:45+03:00
- sha3dc5e68e 2026-11-23T22:56:29+03:00
- sha8e71a33f 2026-11-23T22:54:53+03:00
- sha1767183f 2026-11-23T22:53:57+03:00
- sha4004511b 2026-11-23T22:41:08+03:00
- sha580dbad6 2026-11-23T22:34:14+03:00
- sha4dbd7c25 2026-11-23T22:30:20+03:00
- sha6e6124b7 2026-11-23T22:26:39+03:00
- sha91719ddf 2026-11-23T22:25:38+03:00
- shab9dfe539 2026-11-23T22:21:00+03:00
- shaa659e486 2026-11-23T22:18:50+03:00
- sha7f4dfe04 2026-11-23T22:18:48+03:00
- sha046e73ce 2026-11-23T22:17:09+03:00
- shab794e8f9 2026-11-23T22:15:51+03:00
- sha1a966d01 2026-11-23T22:13:59+03:00
- sha362fa108 2026-11-23T22:11:45+03:00

## Funnel
| step | count |
|---|---|
| accepted | 17 |
| claimed | 507 |
| coded | 184 |
| found_in_backlog | unknown |
| gate_pass | 68 |
| known_to_loop | 497 |
| promoted | 64 |
| ready | 137 |
| reviewed | 173 |
| triaged | 336 |

Side counters: blocked=0, parked=0, requeued=7
Tasks now: DONE=68, FAILED=485, PROMOTED=40, READY=137
Accepted: 17
Promoted: 64
Free RAM, GB: 2.55
Telemetry rows: 40541 recognised, 0 unrecognised

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
| google/gemma-4-26b-a4b-it | 704 | 604769 | 68684 | 535 | 0 | 535 |
| google/gemma-4-31b-it | 581 | 292763 | 18688 | 488 | 0 | 488 |
| openrouter/nvidia/nemotron-3-ultra-550b-a55b:free | 115 | 663252 | 151232 | 2 | 2 | 2 |
| other | 65 | 1154192 | 66710 | 6 | 0 | 7 |

## Spans
| span | rows | calls |
|---|---|---|
| answer | 536 | 0 |
| gate | 6002 | 0 |
| infra | 1040 | 0 |
| loop | 6657 | 0 |
| other | 10793 | 0 |
| promote | 80 | 0 |
| review | 2334 | 1287 |
| run | 12721 | 4392 |
| triage | 378 | 0 |

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
Modules: 30
Tests in the cloud: 101
Tests not in the cloud: 110
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
- tests/test_factory_w_free.py (dependency)
- tests/test_factory_wiring.py (dependency)
- tests/test_factory_worker_exception_return.py (backlog-id)

## Cloud test matrix
Not read yet.
