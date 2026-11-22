"""factory_loop core, third part (core3 group)."""
import json
import os
import shutil
import subprocess
import tempfile
import sys
import time
from pathlib import Path
import pytest
from tools import agent_factory as F
from tools import factory_loop as L
import os, sys
from test_factory_loop import _stale_index_lock, Env, Clock, git, task_row, env, empty_env, BRANCH, PY  # noqa: <id>
from test_factory_loop import empty_env, env, git  # noqa: <id>


def test_event_every_iteration_and_clean_jsonl(env):
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    loop = env.loop()
    for _ in range(3):
        loop.step()
    raw = (env.state_dir / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    assert raw and all(line.startswith("{") for line in raw)
    rows = [json.loads(x) for x in raw]
    assert all({"ts", "run_id", "span"} <= set(r) for r in rows)
    assert len({r["run_id"] for r in rows}) == 1
    loops = [r for r in rows if r["span"] == "loop"]
    assert len(loops) == 3 and all(r.get("action") and "reason" in r for r in loops)
    assert rows[0]["ts"][:4].isdigit()


def test_stats_json_written(env):
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    env.loop(once=True).run()
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    for key in ("accepted", "rejected", "quarantine", "blocked", "blocked_by_reason", "opus_questions", "tokens_in",
                "tokens_out", "seconds", "last_iteration"):
        assert key in stats


# ---- HOLD / DONE ------------------------------------------------------------------------

def test_hold_only_without_expired_blocks_writes_questions_and_sleeps_long(env):
    """<id>: HOLD stays only while no block's term is over; it sleeps at most hold_sleep (60) and never past the
    earliest term; an expired term is lifted by the loop (UNBLOCK), not held."""
    env.set_row("T1", status="BLOCKED", blocked_reason="scope_violation", blocked_at=env.clock.t,
                block_until=env.clock.t + 10_000)
    loop = env.loop(triage_fn=lambda **kw: {"tasks": [], "holds": [], "stale": [], "skipped": []})
    loop.step()  # TRIAGE (empty)
    out = loop.step()  # HOLD
    assert env.loop_events()[-1]["action"] == "HOLD"
    assert out.sleep == 60                            # 21.11: hold_sleep 300 -> 60
    text = (env.state_dir / "opus_questions.md").read_text(encoding="utf-8")
    assert "T1" in text and "scope_violation" in text
    env.set_row("T1", block_until=env.clock.t + 42)
    assert loop.step().sleep == 42                    # the HOLD ends at the term
    env.set_row("T1", block_until=env.clock.t - 1)
    out = loop.step()
    assert out.action == "UNBLOCK" and env.state()["tasks"]["T1"]["status"] == "READY"


def test_done_sleeps_300(env):
    env.set_row("T1", status="DONE")
    loop = env.loop(triage_fn=lambda **kw: {"tasks": [], "holds": [], "stale": [], "skipped": []})
    loop.step()
    out = loop.step()
    assert env.loop_events()[-1]["action"] == "DONE" and out.sleep == 300     # 21.11: was 900


# ---- CLI --------------------------------------------------------------------------------

def test_cli_defaults_and_flags(tmp_path):
    a = L.parse_args(["--state-dir", str(tmp_path), "--once", "--until", "2026-11-20 08:30"])
    assert a.once is True
    assert a.branch == "factory/night-20261119"
    assert str(a.backlog).endswith("BACKLOG_ECHO.md")
    assert a.until.year == 2026 and a.until.hour == 8
    d = L.parse_args([])
    assert str(d.state_dir).endswith(os.path.join("agent-factory", "echo"))


# ---- risk register additions (a-g) --------------------------------------------------------

def test_a_any_exception_is_infra_and_loop_lives(empty_env):
    e = empty_env

    def triage(**kw):
        raise RuntimeError("boom " + "AI" + "zaSyA1234567890" + "abcdefghijklmnopqrstuvwx")

    loop = e.loop(triage_fn=triage)
    out = loop.step()
    assert out.code is None
    ev = [x for x in e.events() if x["span"] == "infra"][-1]
    assert "RuntimeError" in ev["reason"] and "AI" + "zaSyA1234567890" not in ev["reason"]
    assert e.state()["infra_streak"] == 1


def test_a_refresh_failure_is_infra(env, monkeypatch):
    def bad(*a, **k):
        raise subprocess.CalledProcessError(128, "git archive")
    monkeypatch.setattr(L, "refresh_mirror", bad)
    assert env.loop().step().code is None
    assert env.state()["infra_streak"] == 1


def test_e_sleep_guard_set_and_released(env):
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    env.loop(once=True).run()
    assert env.power[0] == 0x80000001
    assert env.power[-1] == 0x80000000


def test_f_low_ram_waits_without_strike(env):
    loop = env.loop(extra={"free_ram_fn": lambda: 512 * 2 ** 20})   # below the light floor (768 MB)
    out = loop.step()
    assert env.runs() == 0
    assert out.sleep == 60 and out.reason == "low_ram"
    assert env.state()["infra_streak"] == 0
    assert F.strikes_for(env.state(), "B1") == 0


def test_g_timeout_is_a_module_constant():
    assert isinstance(L.RUNNER_TIMEOUT_S, int) and L.RUNNER_TIMEOUT_S >= 600
    assert "task_timeout" not in L.Config.__dataclass_fields__


# ---- models and keys ----------------------------------------------------------------------

def test_default_models_are_the_verified_pair():
    cfg = L.Config(state_dir=Path("x"))
    assert cfg.small_model == cfg.large_model == "google/gemini-3.5-flash-lite"
    assert cfg.review_model == "google/gemini-3.1-flash-lite"


def test_reviewer_must_differ_from_coder(env):
    with pytest.raises(ValueError, match="review model must differ"):
        env.loop(review_model="google/gemini-3.5-flash-lite")
    with pytest.raises(SystemExit):
        L.main(["--state-dir", str(env.state_dir), "--review-model", "google/gemini-3.5-flash-lite",
                "--once"])


def test_env_file_keys_stay_out_of_process_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_FAKE", raising=False)
    ch = tmp_path / "ch.json"
    ch.write_text(json.dumps({"channels": [{"key_env": "GEMINI_FAKE"}]}), encoding="utf-8")
    envf = tmp_path / ("." + "env")
    envf.write_text("OTHER=zzz\nexport GEMINI_FAKE='sekret-value-123'\n", encoding="utf-8")
    assert L.load_keys(envf, ch) == {"GEMINI_FAKE": "sekret-value-123"}
    assert "GEMINI_FAKE" not in os.environ
    envf.write_text("OTHER=zzz\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        L.load_keys(envf, ch)
    assert "GEMINI_FAKE" in str(ei.value)


# ---- critic round 2: triage robustness, until in sleep, keys ------------------------------

def test_invalid_portion_becomes_holds_not_infra(empty_env):
    e = empty_env
    bad = {"id": "T9", "title": "x", "touch_files": [], "tests": [], "backlog_id": "B9"}
    loop = e.loop(triage_fn=lambda **kw: {"tasks": [bad], "holds": [], "stale": [], "skipped": []})
    for _ in range(6):
        assert loop.step().code is None
    assert e.state()["infra_streak"] == 0
    text = (e.state_dir / "opus_questions.md").read_text(encoding="utf-8")
    assert "B9" in text and "invalid" in text.lower()
    assert not (e.state_dir / "BRAKE").exists()


def _forget_empty_mark(e):
    path = e.state_dir / "loop_state.json"
    ls = json.loads(path.read_text(encoding="utf-8"))
    ls["triage_empty"] = None
    path.write_text(json.dumps(ls), encoding="utf-8")
