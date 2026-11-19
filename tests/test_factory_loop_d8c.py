"""factory_loop round D8: one record per model call, summary, PROMOTED vs ACCEPTED (d8c group)."""
import json

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, task_row, two_tasks, env, empty_env  # noqa: <id>
from test_factory_loop_answers import put, answers  # noqa: <id>
from test_factory_loop_git3 import REAL_CALL


def _rows(e, span):
    return [x for x in e.events() if x["span"] == span]


# ---- telemetry: one record per call, no duplicated tokens, unknown stays unknown ----------------------------------

CALL = {"role": "code", "model": "google/m1", "channel": "c1", "returncode": 0, "error_class": None,
        "input_tokens": 100, "output_tokens": 20, "reasoning_tokens": 7, "cache_read_tokens": 30,
        "cache_write_tokens": 4, "actual_tokens": 120, "reserved_tokens": 150, "http_status": 200, "steps": 3,
        "tool_events": 2}


def test_a_call_is_one_record_with_every_usage_field_and_no_token_copy_elsewhere(env):
    env.runner_says({"status": "REVIEW", "task": "T1", "calls": [CALL]})
    env.loop().step()
    with_tokens = [x for x in env.events() if "tokens_in" in x]
    assert len(with_tokens) == 1                         # the aggregate row carries no copy of the tokens
    call = with_tokens[0]
    assert (call["tokens_in"], call["tokens_out"], call["tokens_reasoning"], call["tokens_cache_read"],
            call["tokens_cache_write"], call["actual_tokens"], call["reserved_tokens"],
            call["http_status"], call["steps"]) == (100, 20, 7, 30, 4, 120, 150, 200, 3)
    agg = [x for x in _rows(env, "run") if "calls" in x][-1]
    assert agg["calls"] == 1 and "tokens_in" not in agg and "tokens_out" not in agg


def test_unknown_usage_is_absent_not_zero_and_adds_nothing_to_the_totals(env):
    bare = {"role": "code", "model": "google/m1", "returncode": 0}
    env.runner_says({"status": "REVIEW", "task": "T1", "calls": [bare]})
    env.loop().step()
    row = [x for x in env.events() if x.get("role") == "code"][-1]
    assert "tokens_in" not in row and "tokens_out" not in row and "actual_tokens" not in row
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["tokens_in"] == 0 and stats["tokens_out"] == 0
    s = L.summary(env.state_dir)
    assert s["model"]["google/m1"]["calls"] == 1 and s["model"]["google/m1"]["calls_usage_unknown"] == 1


# ---- summary: the one reader of the format ----------------------------------------------------------------------------

def _write_tel(e, rows):
    path = e.state_dir / "telemetry.jsonl"
    path.write_text("\n".join(json.dumps(dict({"ts": "t", "run_id": "r"}, **r)) for r in rows) + "\nnot json\n",
                    encoding="utf-8")


def test_summary_funnel_and_spend_per_model(env):
    env.set_row("T1", status="READY")
    _write_tel(env, [
        {"span": "run", "task_id": "T1", "status": "REVIEW", "calls": 2},
        {"span": "run", "task_id": "T1", "role": "code", "model": "google/m1", "tokens_in": 100, "tokens_out": 20},
        {"span": "run", "task_id": "T1", "role": "code", "model": "google/m1", "http_status": 429,
         "error_class": "rate_limit"},
        {"span": "review", "task_id": "T1", "role": "review", "model": "google/m2", "tokens_in": 10, "tokens_out": 2},
        {"span": "promote", "task_id": "T1", "status": "promoted"},
        {"span": "promote", "task_id": "T9", "status": "requeued"},
        {"span": "promote", "task_id": "T8", "status": "parked"},
        {"span": "accept", "task_id": "T1", "status": "accepted"},
        {"span": "run", "task_id": "T2", "status": "WAITING_CHANNEL"},
    ])
    s = L.summary(env.state_dir, free_ram_fn=lambda: 3 * 2 ** 30)
    f = s["funnel"]
    assert (f["claimed"], f["coded"], f["gate_pass"], f["reviewed"], f["promoted"], f["accepted"]) == (1, 1, 1, 1, 1, 1)
    assert f["triaged"] == 1 and f["ready"] == 1 and f["found_in_backlog"] == "unknown"
    assert s["side"] == {"blocked": 0, "requeued": 1, "parked": 1}
    m1, m2 = s["model"]["google/m1"], s["model"]["google/m2"]
    assert (m1["calls"], m1["tokens_in"], m1["tokens_out"], m1["http_429"], m1["errors"]) == (
        2, 100, 20, 1, {"rate_limit": 1})
    assert m1["calls_usage_unknown"] == 1 and (m2["calls"], m2["tokens_in"]) == (1, 10)
    assert s["rows_recognized"] == 9 and s["unrecognized_rows"] == 1 and s["free_ram_gb"] == 3.0
    assert s["accepted"] == 1 and s["promoted"] == 1


def test_summary_keeps_the_keys_the_mirror_reads(env):
    _write_tel(env, [{"span": "run", "task_id": "T1", "status": "REVIEW"}])
    s = L.summary(env.state_dir)
    for key in ("schema", "span", "model", "status", "accepted", "promoted", "rows_recognized",
                "unrecognized_rows", "skipped_files", "funnel", "free_ram_gb"):
        assert key in s
    for t in list(s["span"].values()):
        assert {"rows", "calls", "tokens_in", "tokens_out", "errors", "status"} <= set(t)


def test_summary_has_no_task_text_no_ids_no_paths_no_secrets(env):
    env.set_row("T1", status="BLOCKED", blocked_reason="gate_failed")
    _write_tel(env, [{"span": "run", "task_id": "T1", "backlog_id": "B1", "status": "REVIEW",
                      "reason": "secret remark about tools/x1.py", "model": "google/m1", "role": "code"}])
    text = json.dumps(L.summary(env.state_dir), ensure_ascii=False)
    for bad in ("T1", "B1", "task 1", "tools/x1.py", "secret remark", "gate_failed"):
        assert bad not in text
    assert json.loads(text)["tasks_now"] == {"BLOCKED": 1}


def test_summary_cli_prints_the_same_dict(env, capsys):
    _write_tel(env, [{"span": "run", "task_id": "T1", "status": "REVIEW"}])
    assert L.main(["summary", "--state-dir", str(env.state_dir)]) == 0
    printed = json.loads(capsys.readouterr().out)
    direct = L.summary(env.state_dir)
    printed.pop("free_ram_gb"), direct.pop("free_ram_gb")
    assert printed == direct


def test_summary_of_an_empty_state_dir_is_zeros_not_a_crash(tmp_path):
    s = L.summary(tmp_path)
    assert s["rows_recognized"] == 0 and s["funnel"]["triaged"] == 0 and s["model"] == {}


# ---- PROMOTED is not ACCEPTED -------------------------------------------------------------------------------------------

def _promoted(env):
    env.set_row("T1", status="PROMOTED")


def test_accept_marks_a_promoted_task_and_stats_tell_them_apart(env):
    _promoted(env)
    put(env, backlog_id="B1", task_id="T1", accept=True, note="taken")
    env.loop().apply_answers()
    ls = json.loads((env.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert "T1" in ls["accepted"] and env.state()["tasks"]["T1"]["status"] == "PROMOTED"
    assert _rows(env, "accept") and _rows(env, "accept")[-1]["status"] == "accepted"
    env.loop().step()
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["promoted"] == 1 and stats["accepted"] == 1


def test_stats_count_a_merged_task_as_promoted_not_accepted(env):
    _promoted(env)
    env.loop().step()
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["promoted"] == 1 and stats["accepted"] == 0


def test_accept_of_a_task_that_is_not_promoted_or_already_accepted_is_refused(env):
    put(env, backlog_id="B1", task_id="T1", accept=True)
    env.loop().apply_answers()
    assert list((answers(env) / "rejected").glob("*.reason.txt"))
    _promoted(env)
    put(env, backlog_id="B1", task_id="T1", accept=True)
    put(env, backlog_id="B1", task_id="T1", accept=True)
    env.loop().apply_answers()
    assert len(list((answers(env) / "rejected").glob("*.reason.txt"))) == 2     # the unknown state and the second accept


def test_cli_accept_flag_needs_a_task_and_nothing_else(env):
    with pytest.raises(SystemExit):
        L.main(["answer", "--state-dir", str(env.state_dir), "--backlog-id", "B1", "--accept"])
    with pytest.raises(SystemExit):
        L.main(["answer", "--state-dir", str(env.state_dir), "--task-id", "T1", "--accept", "--touch", "tools/x1.py"])
    assert L.main(["answer", "--state-dir", str(env.state_dir), "--task-id", "T1", "--accept", "--note", "ok"]) == 0
    (name,) = list((env.state_dir / "answers").glob("*.json"))
    assert json.loads(name.read_text(encoding="utf-8"))["accept"] is True
