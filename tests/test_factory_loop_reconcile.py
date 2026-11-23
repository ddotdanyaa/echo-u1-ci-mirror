"""Reconcile: while idle the loop takes its next work by itself.

Observed in a live run (20.11 17:09): triage 'added=0 holds=0 skipped=236 stale=102', loop_state.seen kept 338 rows
as the bare word 'skipped'/'stale' (no reason, no term) and revisited them only on a backlog edit; 38 FAILED tasks were
retried only at the loop START on a new code version; no file mapped a backlog row to its queue state. These tests pin
the next work the loop takes by itself when nothing is runnable."""
import json

from tests.test_factory_loop import Env, task_row
from tools import factory_requeue

NO_SCOPE = "нет упомянутых файлов или модулей области"


def _ls(env):
    return json.loads((env.state_dir / "loop_state.json").read_text(encoding="utf-8"))


def test_a_skipped_or_stale_row_keeps_its_reason_and_a_term(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, tasks=[])

    def triage(**kw):
        return {"tasks": [], "holds": [], "stale": ["B2"],
                "skipped": [{"backlog_id": "B5", "reason": NO_SCOPE}]}
    env.loop(triage_fn=triage).step()
    seen = _ls(env)["seen"]
    for bid, word in (("B5", NO_SCOPE), ("B2", "")):
        rec = seen[bid]
        assert isinstance(rec, dict), "seen[%s] is %r: no reason, no term" % (bid, rec)
        assert word in rec["reason"] and rec["reason"]
        assert float(rec["until"]) > env.clock.t


def test_a_seen_row_past_its_term_is_triaged_again_without_a_backlog_edit(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, tasks=[])
    known = []

    def triage(backlog_path, head_root, known_backlog_ids, limit):
        known.append(set(known_backlog_ids))
        return {"tasks": [], "holds": [], "stale": [], "skipped": [{"backlog_id": "B5", "reason": NO_SCOPE}]}
    loop = env.loop(triage_fn=triage)
    loop.step()
    assert known and "B5" not in known[0]
    env.clock.t += 7 * 3600                      # far past any term; the backlog file is untouched
    for _ in range(3):
        loop.step()
    assert len(known) >= 2, "an expired seen term never woke the triage"
    assert "B5" not in known[-1], "a seen row past its term is still passed as known"


def test_failed_tasks_are_taken_back_by_the_slicer_while_idle_not_only_at_start(tmp_path, monkeypatch):
    """<id> replaced the idle requeue of FAILED tasks (factory_requeue.run at a term) by the slicer: while nothing is
    runnable a failed row goes to the architect ladder, one rung up each time (tests/test_factory_reslice.py)."""
    env = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    env.set_row("T1", status="FAILED", reason="escalated:off_path")
    seen = []

    def slicer(row, cause, rung, evidence, **kw):
        seen.append((row, cause))
        return {"tasks": [], "holds": [], "stale": [], "skipped": []}
    loop = env.loop(triage_fn=lambda **kw: {"tasks": [], "holds": [], "stale": [], "skipped": []},
                    extra={"slice_fn": slicer})
    for _ in range(4):
        loop.step()
        env.clock.t += 3600
    assert seen and seen[0] == ("B1", "first"), "the idle loop never gave a FAILED row back to the slicer"


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


def test_the_loop_writes_a_reconciliation_of_every_backlog_row(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    env.set_row("T1", status="FAILED", reason="quarantine")

    def triage(**kw):
        return {"tasks": [], "holds": [{"backlog_id": "B7", "question": "дать область?"}], "stale": ["B6"],
                "skipped": [{"backlog_id": "B1", "reason": "уже известна"}, {"backlog_id": "B5", "reason": NO_SCOPE}],
                "skipped_unknown": [{"backlog_id": "B8", "state": "непонятно"}]}
    loop = env.loop(triage_fn=triage)
    for _ in range(2):
        loop.step()
    path = env.state_dir / "reconcile.json"
    assert path.is_file(), "the loop writes no backlog reconciliation"
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    assert rows["B1"]["state"] == "FAILED" and rows["B1"]["reason"] == "quarantine"   # the queue wins over 'known'
    assert rows["B5"]["state"] == "seen" and NO_SCOPE in rows["B5"]["reason"] and rows["B5"]["until"]
    assert rows["B6"]["state"] == "stale"
    assert rows["B7"]["state"] == "hold" and rows["B7"]["reason"]
    body = json.loads(path.read_text(encoding="utf-8"))
    assert "unknown_state" not in body["counts"]                         # W-feed 3: open, words reported
    assert body["unknown_words"] == {"непонятно": 1}
    assert all(r.get("reason") for r in rows.values()), "every row has a reason"


def test_a_live_seen_row_reported_as_known_keeps_its_term(tmp_path, monkeypatch):
    """A live seen row is passed as known, so the triage answers 'уже известна': the term must survive that, or the
    row is triaged in full on every second triage whatever its term."""
    env = Env(tmp_path, monkeypatch, tasks=[])

    def triage(backlog_path, head_root, known_backlog_ids, limit):
        if "B5" in known_backlog_ids:
            return {"tasks": [], "holds": [], "stale": [], "skipped": [{"backlog_id": "B5", "reason": "уже известна"}]}
        return {"tasks": [], "holds": [], "stale": [], "skipped": [{"backlog_id": "B5", "reason": NO_SCOPE}]}
    loop = env.loop(triage_fn=triage)
    loop.step()
    until = _ls(env)["seen"]["B5"]["until"]
    env.clock.t += 1800                          # inside the term (seen_retry_s 3600, 21.11), past the empty-triage mark (600)
    loop._triage(*reversed(loop.load()), _ls(env), env.clock.t)
    assert _ls(env)["seen"].get("B5", {}).get("until") == until


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.
