"""<id> wiring: a candidates hold (a row that named no file) goes to the free head model; a pick becomes the triage's
``scopes`` (the normal unit_test + code pair), a not-code answer is booked with a reason and a term that survives
backlog edits until the row's own text changes; an owner-words row never reaches the model."""
import json
import os

from tests.test_factory_loop import Env
from tools import factory_holds as H

HDR = "| ID | Формулировка | Origin | Приоритет: причина | Состояние | Зависит |\n|---|---|---|---|---|---|\n"
CAND = H.candidate_question("P1", [("echo_sync/x.py", 4.0, ["id"]), ("tools/x1.py", 1.0, ["doc"])])
PICK = '{"touch_files": ["echo_sync/x.py"], "note": "Speed up slow in x"}'


def _backlog(env, text="Медленный путь надо ускорить без задержек", extra=""):
    env.backlog.write_text("## 4. Q\n### 4.2 P1\n" + HDR + "| B9 | %s | x | P1 | новая | — |\n%s## 5. H\n" % (text, extra),
                           encoding="utf-8")
    st = env.backlog.stat()
    os.utime(env.backlog, (st.st_atime, st.st_mtime + 10 + len(extra) + len(text)))


def setup(tmp_path, monkeypatch, answer=PICK, unclean=False):
    env = Env(tmp_path, monkeypatch, tasks=[])
    _backlog(env)
    seen = []

    def triage(**kw):
        seen.append(kw)
        return {"tasks": [], "holds": [], "stale": [], "skipped": []}
    loop = env.loop(triage_fn=triage)            # no mirror: the outlines are optional
    ls = loop.ls()
    ls["holds"] = {"B9": CAND}
    loop.save_ls(ls)
    calls = []

    def ask(text, **kw):
        calls.append(text)
        return "ok", "google/x", answer, 5
    monkeypatch.setattr(loop, "_light_ask", ask)
    monkeypatch.setattr(loop, "_backlog_text", lambda bid: ("", False, True) if unclean else ("speed it up", False, False))
    return env, loop, calls, seen


def _commit(env, rel, text):
    import subprocess
    p = env.repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    git = ["git", "-C", str(env.repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(git + ["commit", "-q", "-m", "code"], check=True, capture_output=True)


def _answers(env):
    box = env.state_dir / "answers"
    return list(box.glob("*.json")) if box.exists() else []


def test_a_pick_needs_no_test_and_comes_back_as_a_scope(tmp_path, monkeypatch):
    env, loop, calls, seen = setup(tmp_path, monkeypatch)
    loop._head_holds()
    assert len(calls) == 1 and '"not_code"' in calls[0]
    ls = loop.ls()
    assert ls["head_holds"]["B9"]["status"] == "scoped" and not _answers(env)
    assert "B9" not in ls["holds"]
    assert ls["head_scope"]["B9"]["touch_files"] == ["echo_sync/x.py"]
    assert ls["head_scope"]["B9"]["note"] == "Speed up slow in x"
    _commit(env, "echo_sync/x.py", "# B9: the slow path\ndef slow():\n    return 1\n")   # <id>: a strong row keeps its pick
    loop.step()
    assert seen and seen[-1]["scopes"]["B9"]["touch_files"] == ["echo_sync/x.py"]
    assert "B9" not in seen[-1]["known_backlog_ids"]


def test_the_scope_is_dropped_once_the_row_has_tasks(tmp_path, monkeypatch):
    env, loop, calls, seen = setup(tmp_path, monkeypatch)
    loop._head_holds()
    task = {"id": "bl_B9", "title": "B9", "touch_files": ["tools/x1.py"], "tests": ["tests/test_x1.py"],
            "privacy_safe": True, "estimated_tokens": 100, "backlog_id": "B9"}
    loop.triage_fn = lambda **kw: {"tasks": [task], "holds": [], "stale": [], "skipped": []}
    loop.step()
    assert "B9" not in (loop.ls().get("head_scope") or {})


def test_not_code_is_booked_with_reason_and_term_and_survives_edits(tmp_path, monkeypatch):
    env, loop, calls, seen = setup(tmp_path, monkeypatch, answer='{"not_code": "proxy operations"}')
    loop._head_holds()
    ls = loop.ls()
    rec = ls["not_code"]["B9"]
    assert "proxy operations" in rec["reason"] and rec["reason"].startswith("не код")
    assert float(rec["until"]) > env.clock.t + 6 * 86400 and rec["hash"]
    assert "B9" not in ls["holds"] and ls["head_holds"]["B9"]["status"] == "not_code"
    loop.step()
    assert "B9" in seen[-1]["known_backlog_ids"]
    rows = json.loads((env.state_dir / "reconcile.json").read_text(encoding="utf-8"))["rows"]
    assert rows["B9"]["state"] == "not_code" and rows["B9"]["until"]
    _backlog(env, extra=f"| B{10} | другая строка про код и тесты | x | P2 | новая | — |\n")   # an edit elsewhere
    loop.step()
    assert "B9" in seen[-1]["known_backlog_ids"]
    _backlog(env, text="Новый текст строки про медленный путь", extra=f"| B{10} | другое | x | P2 | новая | — |\n")
    loop.step()
    assert "B9" not in seen[-1]["known_backlog_ids"]        # the row's own text changed: a fresh look


def test_not_code_term_runs_out(tmp_path, monkeypatch):
    env, loop, calls, seen = setup(tmp_path, monkeypatch, answer='{"not_code": "proxy operations"}')
    loop._head_holds()
    env.clock.t += loop.cfg.not_code_term_s + 1
    loop.step()
    assert "B9" not in seen[-1]["known_backlog_ids"]


def test_owner_words_candidates_hold_never_reaches_the_model(tmp_path, monkeypatch):
    env, loop, calls, seen = setup(tmp_path, monkeypatch, unclean=True)
    loop._head_holds()
    assert not calls and loop.ls()["holds"]["B9"] == CAND
    assert loop.ls()["head_holds"]["B9"]["status"] == "private"


def test_an_unbookable_not_code_answer_is_not_asked_again_at_once(tmp_path, monkeypatch):
    # critic <id>: the model already answered; a "later" status would re-ask it on every idle step
    env, loop, calls, seen = setup(tmp_path, monkeypatch, answer='{"not_code": "proxy operations"}')
    monkeypatch.setattr(loop, "_row_hashes", lambda field="row": {})
    loop._head_holds()
    ls = loop.ls()
    assert not H.select(ls["holds"], ls["head_holds"], loop.clock())      # not picked again before the 24 h repeat
    assert len(calls) == 1 and ls["head_holds"]["B9"]["status"] == "unbooked"
    assert "B9" in loop.ls()["holds"] and "B9" not in (loop.ls().get("not_code") or {})


def test_a_weak_candidates_hold_is_dropped_by_the_next_triage(tmp_path, monkeypatch):
    # <id> live 20.11: holds raised by the older words-only rule (<id>, <id>, <id> among them) must not survive
    import subprocess
    env = Env(tmp_path, monkeypatch, tasks=[])
    (env.repo / "echo_sync").mkdir(exist_ok=True)
    (env.repo / "echo_sync" / "slowpath.py").write_text("# B8: the slow path guard\ndef slow():\n    return 1\n",
                                                        encoding="utf-8")
    git = ["git", "-C", str(env.repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(git + ["commit", "-q", "-m", "slow path"], check=True, capture_output=True)
    _backlog(env, text="Медленный путь ускорить без задержек",
             extra="| B8 | Медленный путь ускорить без задержек | x | P1 | новая | — |\n")
    seen = []

    def triage(**kw):
        seen.append(kw)
        return {"tasks": [], "holds": [], "stale": [], "skipped": []}
    loop = env.loop(triage_fn=triage)
    ls = loop.ls()
    ls["holds"] = {"B9": H.candidate_question("P1", [("echo_sync/slowpath.py", 2.0, ["doc"])]),
                   "B8": H.candidate_question("P1", [("echo_sync/slowpath.py", 6.0, ["id", "doc"])]),
                   "B7": "уточнить область: тест(ы) tests/test_a.py импортируют 3 модулей"}
    ls["head_scope"] = {"B9": {"touch_files": ["echo_sync/slowpath.py"], "note": "", "at": "x"}}   # a pick on it too
    loop.save_ls(ls)
    loop.step()
    ls = loop.ls()
    assert "B9" not in ls["holds"] and "B9" not in ls.get("hold_hash", {})   # words only: dropped
    assert "B9" not in (ls.get("head_scope") or {}) and "scopes" not in seen[-1]  # its pick never becomes a task
    assert "B8" in ls["holds"] and "B7" in ls["holds"]                       # ID in the code; not a candidates hold
    rec = ls["seen"]["B9"]
    assert "кандидаты слабые" in rec["reason"] and float(rec["until"]) > env.clock.t
    assert seen and "B9" in seen[-1]["known_backlog_ids"]                     # booked: not re-triaged before its term
    assert any(e.get("status") == "hold_dropped" and "B9" in str(e.get("reason")) for e in env.events())
