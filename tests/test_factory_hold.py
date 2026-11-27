"""<id> (backlog, <id>): while tasks exist the loop does not sit in HOLD for more than 5 minutes: it unblocks a task itself
or takes another one. Every block or ban in the journal has a reason and a term; a ban "cannot be fixed" without an
owner rule counts as an error.

Live 20.11: 15 idle windows over 5 min (374 of 946 min), every one closed by a coordinator restart, never by the loop;
no BLOCKED row had a term. Every block now carries a reason and a term (agent_factory._block); the loop lifts an
expired block itself (UNBLOCK), at most AUTO_UNBLOCK_MAX times per task (shared with the new-version requeue ledger),
then escalates; only the owner's rules (private, only_opus) hold a task without a term."""
import json

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from tools import factory_requeue as R
from test_factory_loop import Env, task_row, _plan, EMPTY


def _pair():
    """<id> (code) waits for its test task <id>: the live shape of <id> / <id> / <id>."""
    return [task_row(1, depends_on=["T" "2"]),
            task_row(2, kind="unit_test", touch_files=["tests/test_x2.py"], tests=["tests/test_x2.py"])]


def _blocked(row, now):
    return (row["status"] == "BLOCKED" and row.get("blocked_reason")
            and type(row.get("block_until")) in (int, float) and row["block_until"] > now
            and type(row.get("blocked_at")) in (int, float))


def test_every_block_has_reason_and_deadline():
    tasks = _plan(task_row(1), task_row(2), task_row(3), task_row(4))
    s = F.initial_state(tasks)
    now = 1000.0
    F.park(s, "T1", "spec_not_testable", "not a testable code defect", now=now)
    tok = F.acquire(tasks, s, "T" "2", now=now)
    F.quarantine(s, "T" "2", tok, reason="scope_violation", now=now)
    later = now
    for _ in range(3):                                   # the third expiry of one task blocks it
        F.acquire(tasks, s, "T3", now=later)
        later += 4000
        F.release_expired(s, later)
    L.Loop._block_review(s, "T4", "no_diff", "promote: no diff", now=now)
    for tid, at in (("T1", now), ("T" "2", now), ("T3", later), ("T4", now)):
        assert _blocked(s["tasks"][tid], at), (tid, s["tasks"][tid])
    assert s["tasks"]["T3"]["blocked_reason"] == "lease_expired"
    F.validate_state(tasks, s)
    s["tasks"]["T1"].pop("block_until")
    with pytest.raises(F.InvalidPlan, match="term"):
        F.validate_state(tasks, s)                       # a block without a term is refused
    s["tasks"]["T1"]["block_until"] = now + 300
    s["tasks"]["T1"]["blocked_reason"] = None
    with pytest.raises(F.InvalidPlan, match="reason"):
        F.validate_state(tasks, s)                       # a block without a reason is refused


def test_legacy_block_without_term_gets_one_and_a_past_defer_expires_at_once(tmp_path):
    """<id> (gate_unknown): its «отложить до» passed 824 min ago and it stayed BLOCKED. A legacy row gets the
    passed not_before as its term (expired at once) or a fresh term."""
    tasks = _plan(task_row(1), task_row(2))
    s = F.initial_state(tasks)
    s["tasks"]["T1"].update(status="BLOCKED", blocked_reason="gate_unknown", not_before=5.0)
    s["tasks"]["T" "2"].update(status="BLOCKED", blocked_reason=None)
    path = tmp_path / "state.json"
    F.save_atomic(path, s)
    st = F.load_state(path, tasks)
    assert st["tasks"]["T1"]["block_until"] == 5.0 and "not_before" not in st["tasks"]["T1"]
    assert st["tasks"]["T" "2"]["blocked_reason"] and st["tasks"]["T" "2"]["block_until"] > 5.0
    assert F.next_action(st, 6.0, 0, False, tasks)["action"] == "UNBLOCK"


def test_hold_with_expired_block_unblocks():
    tasks = _plan(*_pair())
    s = F.initial_state(tasks)
    F.park(s, "T" "2", "spec_not_testable", "not a testable code defect", now=0.0)
    act = F.next_action(s, 299.0, 0, False, tasks)
    assert act["action"] == "HOLD" and 0 < act["wait_s"] <= 300       # the term is named, the wait is bounded
    act = F.next_action(s, 300.0, 0, False, tasks)
    assert act == {"action": "UNBLOCK", "task_id": "T" "2", "reason": "spec_not_testable", "block_until": 300.0}
    F.unblock(s, "T" "2", "auto")
    assert F.next_action(s, 300.0, 0, False, tasks)["task_id"] == "T" "2"     # the dead dependency is lifted with it


def test_expired_block_is_lifted_also_during_a_channel_cooldown():
    """W-sha: <id> is BLOCKED by worker_exception (term 300 s, 50 min passed) while a runnable card waits for a cooling
    channel: the lift is not held back by WAIT channel_cooldown; with no expired block the WAIT stays."""
    tasks = _plan(task_row(1), task_row(2))
    s = F.initial_state(tasks)
    F.park(s, "T1", "spec_not_testable", "a fault of the code", now=0.0)
    s["tasks"]["T1"].update(blocked_reason="worker_exception", block_until=300.0)
    now = 300.0 + 3000.0
    act = F.next_action(s, now, 120.0, False, tasks)
    assert act == {"action": "UNBLOCK", "task_id": "T1", "reason": "worker_exception", "block_until": 300.0}
    F.unblock(s, "T1", None)
    assert F.next_action(s, now, 120.0, False, tasks)["reason"] == "channel_cooldown"      # <id> and <id> are runnable now
    s["tasks"]["T1"].update(status="BLOCKED", blocked_reason="worker_exception", block_until=now + 100)
    assert F.next_action(s, now, 120.0, False, tasks)["reason"] == "channel_cooldown"      # the term is not over: waits
    assert F.next_action(s, now, 0.0, False, tasks)["action"] == "RUN"


def test_loop_never_holds_over_five_min_while_blocked_tasks(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch, tasks=_pair())
    e.set_row("T" "2", status="BLOCKED", blocked_reason="spec_not_testable", blocked_at=e.clock.t,
              block_until=e.clock.t + 300)
    loop = e.loop(triage_fn=lambda **kw: EMPTY)
    held, out = 0.0, None
    for _ in range(8):
        out = loop.step()
        if out.action == "UNBLOCK":
            break
        if out.action == "HOLD":
            assert out.sleep <= 300
            held += out.sleep
            e.clock.t += out.sleep
    assert out.action == "UNBLOCK" and held <= 300
    ev = [x for x in e.loop_events() if x["action"] == "UNBLOCK"][-1]
    assert "T" "2" in ev["reason"] and "spec_not_testable" in ev["reason"] and "1/%d" % F.AUTO_UNBLOCK_MAX in ev["reason"]
    assert "срок" in ev["reason"]
    row = e.state()["tasks"]["T" "2"]
    assert row["status"] == "READY" and "block_until" not in row
    # no Opus note: an Opus note would hide the task's last failure from its next coder (fresh_feedback)
    assert not any(x.get("source") == "opus" for x in row.get("feedback") or [])
    ledger = json.loads((e.state_dir / "requeue_ledger.json").read_text(encoding="utf-8"))
    assert len(ledger["T" "2"]) == 1 and ledger["T" "2"][0].startswith("hold:")


def test_the_expiry_after_the_last_automatic_unblock_escalates_not_loops(tmp_path, monkeypatch):
    assert F.AUTO_UNBLOCK_MAX == 6                       # 21.11 (was 3)
    e = Env(tmp_path, monkeypatch, tasks=_pair())
    loop = e.loop(triage_fn=lambda **kw: EMPTY)
    actions = []
    for _ in range(F.AUTO_UNBLOCK_MAX + 1):
        e.set_row("T" "2", status="BLOCKED", blocked_reason="spec_not_testable", blocked_at=e.clock.t - 400,
                  block_until=e.clock.t - 1)
        for _ in range(4):
            out = loop.step()
            if out.action in ("UNBLOCK", "ESCALATE"):
                actions.append(out.action)
                break
        e.clock.t += 1
    assert actions == ["UNBLOCK"] * F.AUTO_UNBLOCK_MAX + ["ESCALATE"]
    row = e.state()["tasks"]["T" "2"]
    assert row["status"] == "FAILED" and row["reason"] == "escalated:spec_not_testable"
    assert any(x["span"] == "infra" and x.get("status") == "escalated" and x.get("task_id") == "T" "2"
               for x in e.events())
    text = (e.state_dir / "opus_questions.md").read_text(encoding="utf-8")
    assert "T" "2" in text and "escalated:spec_not_testable" in text
    out = loop.step()
    assert out.action != "UNBLOCK"                       # an escalated task is not lifted again


def test_owner_rule_is_the_only_permanent_ban():
    tasks = _plan(task_row(1, privacy_safe=False), task_row(2, only_opus=True), task_row(3))
    s = F.initial_state(tasks)
    F._block(s["tasks"]["T3"], "private", 0.0)
    assert s["tasks"]["T3"]["block_until"] is None
    F.validate_state(tasks, s)                           # the owner's rule needs no term
    act = F.next_action(s, 10 ** 9, 0, False, tasks)
    assert act["action"] == "HOLD" and act["reason"] == "owner_rule:only_opus,private"
    # the lock: the requeue ban list holds only the owner's rules
    for word in ("scope_violation", "already_green", "spec_not_testable", "runner_no_result", "gate_unknown"):
        assert not R.SKIP.search(word), word
    for word in F.OWNER_RULES:
        assert R.SKIP.search(word)
    assert F.OWNER_RULES == frozenset(("private", "only_opus"))


def test_an_already_green_block_goes_to_the_head_question_at_once_not_to_reruns(tmp_path, monkeypatch):
    """Live 21.11 21:41-22:20: 7 already-green tasks were lifted 12 times, each lift a pool slot rerunning the same
    green test on the same base. already_green is a fact of the base: the first expiry escalates; another reason lifts."""
    e = Env(tmp_path, monkeypatch, tasks=_pair())
    loop = e.loop(triage_fn=lambda **kw: EMPTY)

    def first(reason):
        e.set_row("T" "2", status="BLOCKED", blocked_reason=reason, blocked_at=e.clock.t - 400, block_until=e.clock.t - 1)
        for _ in range(4):
            out = loop.step()
            if out.action in ("UNBLOCK", "ESCALATE"):
                return out.action
        return None
    assert first("already_green") != "UNBLOCK"             # fac-74: the proof book takes the card before the term: never lifted, never rerun
    row = e.state()["tasks"]["T" "2"]
    assert row["status"] == "FAILED" and row["reason"] in ("reslice:stale", "superseded:already_green")
    assert "T" "2" in loop.ls()["green_proof"].get("B2", {}).get("tids", [])
    e.set_row("T" "2", status="BLOCKED", blocked_reason="scope_violation", blocked_at=e.clock.t - 400,
              block_until=e.clock.t - 1, reason=None)
    assert first("scope_violation") == "UNBLOCK"           # the neighbour: a model-made block is still lifted


def test_an_already_green_block_of_a_rel_row_still_escalates_at_once(tmp_path, monkeypatch):
    """fac-74: the old path _auto_unblock -> F.escalate stays for rows the proof book skips (rel- rows; red / unknown guard)."""
    e = Env(tmp_path, monkeypatch, tasks=_pair())
    loop = e.loop(triage_fn=lambda **kw: EMPTY)
    e.set_row("T" "2", status="BLOCKED", blocked_reason="already_green", blocked_at=e.clock.t - 400,
              block_until=e.clock.t - 1, backlog_id="rel-B2")
    acts = [loop.step().action for _ in range(4)]
    assert "ESCALATE" in acts and "UNBLOCK" not in acts
    assert e.state()["tasks"]["T" "2"]["status"] == "FAILED"
    assert "T" "2" in (e.state_dir / "opus_questions.md").read_text(encoding="utf-8")
