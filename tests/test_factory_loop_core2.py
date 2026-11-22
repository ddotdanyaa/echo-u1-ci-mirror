"""factory_loop core, second half (core2 group)."""
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
from test_factory_loop import BRANCH, Env, PY, empty_env, env, git, task_row  # noqa: <id>
from test_factory_loop_core3 import _forget_empty_mark  # noqa: <id>


def test_stale_and_skipped_are_remembered_while_backlog_is_unchanged(empty_env):
    e = empty_env
    seen = []

    def triage(backlog_path, head_root, known_backlog_ids, limit):
        seen.append(set(known_backlog_ids))
        return {"tasks": [], "holds": [{"backlog_id": "H1", "question": "q?"}],
                "stale": ["S1", {"backlog_id": "S2"}],
                "skipped": [{"backlog_id": "K1", "reason": "x"}]}

    loop = e.loop(triage_fn=triage)
    loop.step()
    ls = json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert {"S1", "S2", "K1"} <= set(ls["seen"])
    _forget_empty_mark(e)
    loop.step()
    assert {"S1", "S2", "K1", "H1"} <= seen[-1]   # holds are known too: no repeated question


def test_seen_is_reset_when_backlog_mtime_changes_holds_stay(empty_env):
    e = empty_env
    seen = []

    def triage(backlog_path, head_root, known_backlog_ids, limit):
        seen.append(set(known_backlog_ids))
        return {"tasks": [], "holds": [{"backlog_id": "H1", "question": "q?"}],
                "stale": ["S1"], "skipped": []}

    loop = e.loop(triage_fn=triage)
    loop.step()
    os.utime(e.backlog, (time.time() + 50, time.time() + 50))
    _forget_empty_mark(e)
    loop.step()
    assert "S1" not in seen[-1] and "H1" in seen[-1]
    ls = json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert "H1" in ls["holds"] and "S1" in ls["seen"]  # re-recorded by the new pass


def test_until_is_checked_inside_sleep(empty_env):
    import datetime as dt
    e = empty_env
    until = dt.datetime.fromtimestamp(e.clock.t + 100)
    rc = e.loop(until=until, triage_fn=lambda **kw: {"tasks": [], "holds": [], "stale": [],
                                                      "skipped": []}).run()
    assert rc == 0
    assert sum(e.clock.sleeps) < 400  # DONE sleeps 900 s, the deadline cuts it


def test_channel_without_key_is_skipped_but_none_is_refused(tmp_path, monkeypatch):
    for name in ("GEMINI_A", "GEMINI_B"):
        monkeypatch.delenv(name, raising=False)
    ch = tmp_path / "ch.json"
    ch.write_text(json.dumps({"channels": [{"key_env": "GEMINI_A"}, {"key_env": "GEMINI_B"}]}),
                  encoding="utf-8")
    envf = tmp_path / ("." + "env")
    envf.write_text("GEMINI_A=aaaaaaaa1\n", encoding="utf-8")
    missing = []
    assert L.load_keys(envf, ch, missing) == {"GEMINI_A": "aaaaaaaa1"}
    assert missing == ["GEMINI_B"]
    envf.write_text("X=1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        L.load_keys(envf, ch, [])


def test_append_skipped_is_visible_in_triage_event(empty_env):
    e = empty_env
    (e.state_dir / "plan.json").write_text(json.dumps({"tasks": [task_row(1)]}), encoding="utf-8")
    e.set_row("T1", status="DONE")
    dup = task_row(1)  # same id: append_tasks skips it silently
    dup["backlog_id"] = "B-DUP"
    new = task_row(2)
    loop = e.loop(triage_fn=lambda **kw: {"tasks": [dup, new], "holds": [], "stale": [],
                                          "skipped": []})
    loop.step()
    ev = [x for x in e.events() if x["span"] == "triage"][-1]
    assert ev["append_skipped"] == [{"id": "T1", "backlog_id": "B-DUP", "reason": "duplicate id"}]


# ---- triage telemetry: localisation events and deferred rows --------------------------------

def test_triage_events_and_deferred_are_visible_and_not_remembered(empty_env):
    e = empty_env
    calls = []

    def triage(backlog_path, head_root, known_backlog_ids, limit):
        calls.append(set(known_backlog_ids))
        return {"tasks": [], "holds": [], "stale": [], "skipped": [],
                "events": ["profile_unknown", "e2 owner@example.com"] + ["x%d" % i for i in range(20)],
                "deferred": [{"backlog_id": "D1"}, "D2"]}

    loop = e.loop(triage_fn=triage)
    loop.step()
    ev = [x for x in e.events() if x["span"] == "triage"][-1]
    assert ev["deferred"] == 2 and len(ev["events"]) == 10 and ev["events"][0] == "profile_unknown"
    assert "owner@example.com" not in json.dumps(ev)
    ls = json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert "D1" not in ls["seen"] and "D2" not in ls["seen"]
    loop.step()                                    # no pause: triage again, not DONE
    assert len(calls) == 2 and "D1" not in calls[1]
    assert e.loop_events()[-1]["action"] == "TRIAGE"


# ---- integration critic: idle triage, profile attempts ---------------------------------------

def test_idle_triage_sleeps_and_does_not_reset_the_series(empty_env):
    e = empty_env
    st = e.state()
    st["infra_streak"] = 3
    F.save_atomic(e.state_dir / "state.json", st)
    loop = e.loop(triage_fn=lambda **kw: {"tasks": [], "holds": [], "stale": [], "skipped": [],
                                          "deferred": [{"backlog_id": "D1"}]})
    out = loop.step()
    assert out.action == "TRIAGE" and out.sleep == 120
    assert e.state()["infra_streak"] == 3


def test_triage_with_added_tasks_does_not_reset_the_series(empty_env):
    e = empty_env
    st = e.state()
    st["infra_streak"] = 3
    F.save_atomic(e.state_dir / "state.json", st)
    e.loop(triage_fn=lambda **kw: {"tasks": [task_row(7)], "holds": [], "stale": [],
                                   "skipped": []}).step()
    assert e.state()["infra_streak"] == 3        # only proof that the pipeline works resets it


def test_profile_attempts_are_passed_merged_and_cleaned(empty_env):
    e = empty_env
    e.backlog.write_text(ROWS_MD, encoding="utf-8")
    seen = []

    def triage(backlog_path, head_root, known_backlog_ids, limit, profile_attempts=None):
        seen.append(dict(profile_attempts or {}))
        return {"tasks": [], "holds": [], "stale": [], "skipped": [], "deferred": ["D1"],
                "profile_attempts": {"E1": 1 + len(seen)}}

    loop = e.loop(triage_fn=triage)
    loop.step()
    loop.step()
    assert seen == [{}, {"E1": 2}]
    e.backlog.write_text(ROWS_MD.replace("первая строка", "изменённая первая"), encoding="utf-8")
    os.utime(e.backlog, (time.time() + 99, time.time() + 99))   # the row itself changed: reset
    loop.step()
    assert seen[-1] == {}


def test_triage_function_without_profile_param_still_works(empty_env):
    e = empty_env
    n = []

    def old(backlog_path, head_root, known_backlog_ids, limit):
        n.append(1)
        return {"tasks": [], "holds": [], "stale": [], "skipped": [],
                "profile_attempts": {"E1": 1}}
    e.loop(triage_fn=old).step()
    assert n == [1]


# ---- survivability: profile attempts per row, durable closes, wake-up, rotation -------------

ROWS_MD = ("## 4. Очередь\n### 4.1 P0\n| ID | Приоритет | Состояние | Формулировка |\n"
           "|---|---|---|---|\n| E1 | P1 | новая | первая строка про tools/a.py |\n"
           "| E2 | P1 | новая | вторая строка про tools/b.py |\n## 5. Конец\n")


def test_profile_attempts_survive_an_edit_of_another_row(empty_env):
    e = empty_env
    e.backlog.write_text(ROWS_MD, encoding="utf-8")
    seen = []

    def triage(backlog_path, head_root, known_backlog_ids, limit, profile_attempts=None):
        seen.append(dict(profile_attempts or {}))
        return {"tasks": [], "holds": [], "stale": [], "skipped": [], "deferred": ["E1"],
                "profile_attempts": {"E1": len(seen)}}

    loop = e.loop(triage_fn=triage)
    loop.step()
    e.backlog.write_text(ROWS_MD.replace("вторая строка", "правка второй строки"), encoding="utf-8")
    os.utime(e.backlog, (time.time() + 50, time.time() + 50))
    loop.step()
    assert seen[1] == {"E1": 1}                       # <id> changed, <id>'s counter stays
    e.backlog.write_text(ROWS_MD.replace("первая строка", "изменённая первая"), encoding="utf-8")
    os.utime(e.backlog, (time.time() + 99, time.time() + 99))
    loop.step()
    assert seen[2] == {}                              # <id>'s own row changed: counter dropped


def test_profile_attempts_of_vanished_rows_are_dropped(empty_env):
    e = empty_env
    e.backlog.write_text(ROWS_MD, encoding="utf-8")
    seen = []

    def triage(backlog_path, head_root, known_backlog_ids, limit, profile_attempts=None):
        seen.append(dict(profile_attempts or {}))
        return {"tasks": [], "holds": [], "stale": [], "skipped": [], "deferred": ["E1"],
                "profile_attempts": {"E1": 2, "E2": 1}}

    loop = e.loop(triage_fn=triage)
    loop.step()
    e.backlog.write_text(ROWS_MD.replace("| E2 |", "| E9 |"), encoding="utf-8")
    os.utime(e.backlog, (time.time() + 50, time.time() + 50))
    loop.step()
    assert seen[1] == {"E1": 2}


def test_closed_ids_survive_backlog_edits_and_are_known(empty_env):
    e = empty_env
    e.set_loop_state(closed={"E5": "closed"}, holds={}, bases={})
    got = []

    def triage(backlog_path, head_root, known_backlog_ids, limit):
        got.append(set(known_backlog_ids))
        return {"tasks": [], "holds": [], "stale": [], "skipped": []}

    loop = e.loop(triage_fn=triage)
    loop.step()
    os.utime(e.backlog, (time.time() + 70, time.time() + 70))
    loop._forget = True
    ls = json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    ls["triage_empty"] = None
    (e.state_dir / "loop_state.json").write_text(json.dumps(ls), encoding="utf-8")
    loop.step()
    assert "E5" in got[0] and "E5" in got[1]


def test_new_answer_wakes_a_sleeping_loop_but_a_deferred_one_does_not(env):
    box = env.state_dir / "answers"
    box.mkdir()
    loop = env.loop()
    loop._sleep(300)
    assert env.clock.sleeps                           # nothing to do: it really slept
    env.clock.sleeps.clear()
    (box / "1-x.json").write_text("{}", encoding="utf-8")
    loop._sleep(300)
    assert not env.clock.sleeps                       # an unprocessed answer wakes it at once
    loop._known_names = {"1-x.json"}                  # seen by apply_answers: no busy loop
    loop._sleep(120)
    assert env.clock.sleeps


def test_telemetry_rotation_keeps_two_generations_and_reports_failure_once(env, monkeypatch):
    monkeypatch.setattr(L, "TELEMETRY_MAX_BYTES", 200)
    loop = env.loop()
    for i in range(40):
        loop.event("loop", action="X", reason="r" * 30 + str(i))
    names = sorted(p.name for p in env.state_dir.glob("telemetry.jsonl*"))
    assert names == ["telemetry.jsonl", "telemetry.jsonl.1", "telemetry.jsonl.2"]
    real = os.replace

    def broken(src, dst, *a, **k):
        if "telemetry" in str(src):
            raise PermissionError("locked")
        return real(src, dst, *a, **k)
    monkeypatch.setattr(os, "replace", broken)
    for i in range(10):
        loop.event("loop", action="Y", reason="z" * 60)
    raw = (env.state_dir / "telemetry.jsonl").read_text(encoding="utf-8")
    assert raw.count("rotate_failed") == 1


def test_default_state_dir_is_outside_the_user_profile():
    """Kilo puts its cwd into the model's system prompt: the path must not carry the user name."""
    for default in (L.parse_args([]).state_dir, L.DEFAULT_STATE_DIR):
        assert default.name == "echo" and default.parent.name == "agent-factory"
        if os.name == "nt":
            assert Path.home().name not in default.parts
            assert default.parts[0].rstrip("\\/").upper().endswith(":")
            assert "Users" not in default.parts


# ---- round 2 of the integration critic ----------------------------------------------------------

def test_answer_that_cannot_be_moved_does_not_keep_the_loop_awake(env, monkeypatch):
    box = env.state_dir / "answers"
    box.mkdir()
    (box / "1-x.json").write_text(json.dumps({"backlog_id": "B1", "note": "hello"}), encoding="utf-8")
    real = os.replace

    def flaky(src, dst, *a, **k):
        if "answers" in str(src):
            raise PermissionError("antivirus holds the file")
        return real(src, dst, *a, **k)
    monkeypatch.setattr(os, "replace", flaky)
    loop = env.loop()
    loop.apply_answers()
    assert (box / "1-x.json").exists()            # the move failed: the file is still there
    loop._sleep(300)
    assert env.clock.sleeps                       # ...and the loop sleeps normally
    monkeypatch.setattr(os, "replace", real)
    env.clock.sleeps.clear()
    loop.apply_answers()                          # next iteration retries the move (no double apply)
    assert not list(box.glob("*.json")) and (box / "done" / "1-x.json").exists()
    assert F.last_feedback(env.state(), "T1").count("hello") == 1


def test_scrub_covers_environment_keys_and_json_escaping(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    (tmp_path / "channels.json").write_text(json.dumps({"channels": [{"key_env": "GEMINI_X"}]}),
                                            encoding="utf-8")
    monkeypatch.setenv("GEMINI_X", "env-only-secret-0001")
    loop = e.loop(extra={"extra_env": {"OTHER": 'quote"and\\slash-secret-0002'}})
    loop.event("run", reason="provider said env-only-secret-0001 and " +
               'quote"and\\slash-secret-0002')
    raw = (e.state_dir / "telemetry.jsonl").read_text(encoding="utf-8")
    assert "env-only-secret-0001" not in raw and "slash-secret-0002" not in raw
    assert loop._scrub("x env-only-secret-0001 y") == "x [REDACTED] y"


def test_brake_file_holds_and_reason_files_are_scrubbed(env):
    key = "plainsecretvalue-0099"
    loop = env.loop(extra={"extra_env": {"K": key}})
    loop._brake(5, L.Outcome(reason="boom " + key))
    assert key not in (env.state_dir / "BRAKE").read_text(encoding="utf-8")
    bad = {"id": "T9", "title": "x " + key, "touch_files": [], "tests": [], "backlog_id": "B9"}
    env2 = env
    loop.triage_fn = lambda **kw: {"tasks": [bad], "holds": [], "stale": [], "skipped": []}
    (env.state_dir / "plan.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
    loop.step()
    assert key not in (env.state_dir / "loop_state.json").read_text(encoding="utf-8")
    box = env.state_dir / "answers"
    box.mkdir()
    (box / "1.json").write_text(json.dumps({"backlog_id": "B1", "task_id": "NOPE-" + key}),
                                encoding="utf-8")
    loop.apply_answers()
    reasons = list((box / "rejected").glob("*.reason.txt"))
    assert reasons and key not in reasons[0].read_text(encoding="utf-8")


def test_questions_file_is_not_rewritten_when_nothing_changed(env):
    key = "plainsecretvalue-0100"
    env.set_row("T1", status="BLOCKED", blocked_reason="gate")
    st = env.state()
    F.add_feedback(st, "T1", "gate", "the provider said " + key)
    F.save_atomic(env.state_dir / "state.json", st)
    loop = env.loop(extra={"extra_env": {"K": key}})
    tasks, state = loop.load()
    loop._write_questions(tasks, state, loop.ls())
    path = env.state_dir / "opus_questions.md"
    old = time.time() - 500
    os.utime(path, (old, old))
    loop._write_questions(tasks, state, loop.ls())
    assert abs(path.stat().st_mtime - old) < 2        # compared after the scrub: not rewritten


def test_closed_row_is_forgotten_when_its_text_changes(empty_env):
    e = empty_env
    e.backlog.write_text(ROWS_MD, encoding="utf-8")
    loop = e.loop(triage_fn=lambda **kw: {"tasks": [], "holds": [], "stale": [], "skipped": []})
    put_answer = e.state_dir / "answers"
    put_answer.mkdir()
    (put_answer / "1.json").write_text(json.dumps({"backlog_id": "E1", "close": True,
                                                   "note": "done"}), encoding="utf-8")
    loop.apply_answers()
    ls = json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert "E1" in ls["closed"] and ls["closed"]["E1"] != "closed"     # carries the row hash
    e.backlog.write_text(ROWS_MD.replace("вторая строка", "правка второй"), encoding="utf-8")
    os.utime(e.backlog, (time.time() + 50, time.time() + 50))
    loop.step()
    ls = json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert "E1" in ls["closed"]                                         # another row changed
    e.backlog.write_text(ROWS_MD.replace("первая строка", "новая формулировка"), encoding="utf-8")
    os.utime(e.backlog, (time.time() + 99, time.time() + 99))
    ls["triage_empty"] = None
    (e.state_dir / "loop_state.json").write_text(json.dumps(ls), encoding="utf-8")
    loop.step()
    ls = json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert "E1" not in ls["closed"]                                     # reopened by the owner


def test_drop_pending_is_strict_about_the_staging_area(env):
    loop = env.loop()
    stage = env.state_dir / "stage"
    stage.mkdir()
    (stage / "keep.txt").write_text("x", encoding="utf-8")
    for bad in ({"workdir": str(stage)}, {"workdir": ""}, {"workdir": str(env.state_dir)},
                {"workdir": "../.."}, "not-a-dict", None, 7):
        row = {"pending_review": bad}
        loop._drop_pending(row)
        assert "pending_review" not in row
        assert (stage / "keep.txt").exists() and env.state_dir.exists()
    inner = stage / "pending-T1"
    inner.mkdir()
    loop._drop_pending({"pending_review": {"workdir": str(inner)}})
    assert not inner.exists()


def test_two_loops_on_one_worktree_refuse_each_other(env, tmp_path):
    other = tmp_path / "state2"
    other.mkdir()
    first = env.loop()
    assert first.acquire()
    try:
        cfg = L.Config(state_dir=other, repo=env.repo, branch=BRANCH, worktree=env.repo,
                       backlog=env.backlog, channels=tmp_path / "c.json", once=True)
        second = L.Loop(cfg, runner_cmd=[PY, str(env.script)], clock=env.clock.now,
                        sleep=env.clock.sleep, power_fn=lambda f: None, free_ram_fn=lambda: 2 ** 40)
        assert second.run() == 4
        assert any("worktree" in x.get("reason", "") for x in
                   (json.loads(l) for l in (other / "telemetry.jsonl").read_text(
                       encoding="utf-8").splitlines()))
    finally:
        first.release()
    assert env.loop(once=True).run() == 0            # the lock is released with the first loop


def test_start_moves_temp_files_into_the_state_dir(env, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setenv("TEMP", "/elsewhere")
    monkeypatch.setenv("TMP", "/elsewhere")
    seen = []
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    loop = env.loop(once=True)
    real_step = loop.step
    loop.step = lambda: (seen.append((tempfile.gettempdir(), os.environ["TEMP"], os.environ["TMP"])),
                         real_step())[1]
    loop.run()
    tmp = (env.state_dir / "tmp").resolve()
    assert tmp.is_dir()
    assert all(Path(x).resolve() == tmp for x in seen[0])      # during the run
    assert os.environ["TEMP"] == "/elsewhere"                # restored afterwards


# ---- round 3 of the integration critic -------------------------------------------------------------

def test_sleep_is_not_skipped_when_the_step_fails_before_apply_answers(env, monkeypatch):
    box = env.state_dir / "answers"
    box.mkdir()
    (box / "1-x.json").write_text("{}", encoding="utf-8")        # lying there since before the start
    monkeypatch.setattr(L, "refresh_mirror", lambda *a, **k: (_ for _ in ()).throw(
        subprocess.CalledProcessError(128, "git")))
    env.clock.on_sleep = lambda s: (env.state_dir / "STOP").write_text("x", encoding="utf-8")
    assert env.loop().run() == 0
    assert env.clock.sleeps and env.clock.sleeps[0] > 0           # the 60 s tolerance is real


def test_a_file_that_appears_between_two_looks_wakes_the_loop_once(env):
    box = env.state_dir / "answers"
    box.mkdir()
    loop = env.loop()
    loop._known_names = set()
    (box / "late.json").write_text("{}", encoding="utf-8")
    assert loop._answer_waiting() is True
    assert loop._answer_waiting() is False                       # one wake per name


def test_tmp_directory_is_cleaned_of_old_files_at_start(env):
    tmp = env.state_dir / "tmp"
    tmp.mkdir()
    old, young = tmp / "old.txt", tmp / "young.txt"
    old.write_text("x", encoding="utf-8")
    young.write_text("y", encoding="utf-8")
    ancient = time.time() - 3 * 86400
    os.utime(old, (ancient, ancient))
    olddir = tmp / "olddir"
    olddir.mkdir()
    (olddir / "f").write_text("z", encoding="utf-8")
    os.utime(olddir, (ancient, ancient))
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    env.loop(once=True).run()
    assert not old.exists() and not olddir.exists() and young.exists()


def test_key_names_are_not_cached_when_channels_json_is_unreadable(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    ch = tmp_path / "channels.json"
    ch.write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("GEMINI_X", "env-only-secret-0007")
    loop = e.loop()
    assert loop._scrub("a env-only-secret-0007 b") == "a env-only-secret-0007 b"   # cannot know yet
    assert any("channels.json" in x.get("reason", "") for x in e.events())
    ch.write_text(json.dumps({"channels": [{"key_env": "GEMINI_X"}]}), encoding="utf-8")
    assert loop._scrub("a env-only-secret-0007 b") == "a [REDACTED] b"            # not cached as []


def test_old_state_dir_warning_also_covers_plan_and_state(env, tmp_path, monkeypatch):
    old = tmp_path / "local" / "agent-factory" / "echo"
    old.mkdir(parents=True)
    (old / "plan.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(L, "LOCALAPPDATA", tmp_path / "local")
    loop = env.loop()
    assert loop.acquire()
    loop.release()
    assert any(x.get("status") == "warning" and "plan.json" in x.get("reason", "")
               for x in env.events())
