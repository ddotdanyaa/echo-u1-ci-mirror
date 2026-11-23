"""<id> (rule 5 of 21.11): cost and time per ACCEPTED task, per hour and per cohort. Standard library only, no LLM.

Sources: telemetry.jsonl (+ .1 .2), state.json, loop_state.json (``accepted``), paid_spend.json of the paid critic.
ECHO tasks and factory tasks (backlog id ``fac-*``) are counted apart. Counters are cumulative sets of task ids:
PROMOTED = merged into the factory branch, ACCEPTED = taken by the coordinator (so every accepted task is also promoted).
The free contour counts only accepted tasks that got no paid-critic verdict; paid spend is shown on its own.
"""
import argparse
import datetime as dt
import json
import statistics
from pathlib import Path

SCHEMA = 1
KINDS = ("echo", "fac")
WORK_SPANS = ("run", "gate", "review")


def _t(text):
    try:
        d = dt.datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.astimezone()


def _json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _kind(bid, tid):
    name = str(bid or "")
    if not name:
        name = str(tid or "")
        name = name[3:] if name.startswith("bl_") else name
    return "fac" if name.lower().startswith("fac-") else "echo"


def _rows(state_dir):
    base = Path(state_dir) / "telemetry.jsonl"
    for p in (base.with_name(base.name + ".2"), base.with_name(base.name + ".1"), base):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("span") and _t(row.get("ts")):
                yield row


def _median(values):
    return round(statistics.median(values), 1) if values else None


def _zero():
    return {"queued": 0, "attempted": 0, "promoted": 0, "accepted": 0}


def build_report(state_dir, since=None, now=None, paid_spend=None, money_spend=None) -> dict:
    state_dir = Path(state_dir)
    now_t = _t(now) or dt.datetime.now().astimezone()
    since_t = _t(since)
    tasks = {}      # tid -> facts

    def task(tid):
        return tasks.setdefault(tid, {"first": None, "bid": None, "attempt_hours": set(), "calls": 0, "promoted": None,
                                      "accepted": None, "paid": False})

    paid_usd, paid_n = 0.0, 0
    for row in _rows(state_dir):
        t, tid, span = _t(row["ts"]), row.get("task_id"), row["span"]
        if span == "paid_critic":
            paid_n += 1
            paid_usd += row["usd"] if isinstance(row.get("usd"), (int, float)) and not isinstance(row.get("usd"), bool) else 0
        if not isinstance(tid, str) or not tid:
            continue
        f = task(tid)
        if f["first"] is None or t < f["first"]:
            f["first"] = t
        f["bid"] = f["bid"] or row.get("backlog_id")
        if span == "paid_critic":
            f["paid"] = True
        if span in WORK_SPANS:
            f["attempt_hours"].add(t)
        if span == "run" and row.get("role"):
            f["calls"] += 1
        if span == "promote" and row.get("status") == "promoted" and not f["promoted"]:
            f["promoted"] = t
        if span == "accept" and row.get("status") == "accepted" and not f["accepted"]:
            f["accepted"] = t
    for tid, r in (_json(state_dir / "loop_state.json").get("accepted") or {}).items():
        if isinstance(r, dict) and isinstance(tid, str):
            f = task(tid)
            f["accepted"] = f["accepted"] or _t(r.get("at")) or now_t
    for tid, r in (_json(state_dir / "state.json").get("tasks") or {}).items():
        if isinstance(r, dict):
            f = task(tid)
            f["bid"] = f["bid"] or r.get("backlog_id")
            if r.get("status") == "PROMOTED" and not f["promoted"]:
                f["promoted"] = f["first"] or now_t
    for f in tasks.values():
        if f["accepted"] and not f["promoted"]:        # ACCEPTED implies PROMOTED: one consistent counter
            f["promoted"] = f["accepted"]
    members = {tid: f for tid, f in tasks.items()
               if since_t is None or (f["first"] is not None and f["first"] >= since_t)}

    cohort = {k: _zero() for k in KINDS}
    acc = {k: {"free": 0, "paid": 0, "times": [], "calls": []} for k in KINDS}
    hours: dict = {}

    def bump(hour, kind, key):
        hours.setdefault(hour, {k: _zero() for k in KINDS})[kind][key] += 1

    def hkey(t):
        return t.isoformat(timespec="seconds")[:13]

    for tid, f in members.items():
        k = _kind(f["bid"], tid)
        if f["first"]:
            cohort[k]["queued"] += 1
            bump(hkey(f["first"]), k, "queued")
        if f["attempt_hours"] or f["calls"]:
            cohort[k]["attempted"] += 1
            for h in {hkey(x) for x in f["attempt_hours"]}:
                bump(h, k, "attempted")
        if f["promoted"]:
            cohort[k]["promoted"] += 1
            bump(hkey(f["promoted"]), k, "promoted")
        if f["accepted"]:
            cohort[k]["accepted"] += 1
            bump(hkey(f["accepted"]), k, "accepted")
            acc[k]["paid" if f["paid"] else "free"] += 1
            if f["first"]:
                acc[k]["times"].append((f["accepted"] - f["first"]).total_seconds())
            acc[k]["calls"].append(f["calls"])
    start = since_t or min((f["first"] for f in members.values() if f["first"]), default=now_t)
    window_h = max((now_t - start).total_seconds() / 3600, 1 / 60)
    for k in KINDS:
        cohort[k].update(accepted_free=acc[k]["free"], accepted_paid_verified=acc[k]["paid"],
                         accepted_per_hour_free=round(acc[k]["free"] / window_h, 3),
                         median_time_s=_median(acc[k]["times"]), median_calls=_median(acc[k]["calls"]))
    total = {key: sum(cohort[k][key] for k in KINDS) for key in
             ("queued", "attempted", "promoted", "accepted", "accepted_free", "accepted_paid_verified")}
    total["accepted_per_hour_free"] = round(total["accepted_free"] / window_h, 3)
    times, calls = acc["echo"]["times"] + acc["fac"]["times"], acc["echo"]["calls"] + acc["fac"]["calls"]
    total.update(median_time_s=_median(times), median_calls=_median(calls))
    cohort["all"] = total
    spend = _json(paid_spend) if paid_spend else {}
    try:
        money = money_report(state_dir, now=now_t.isoformat(), spend=money_spend)
    except Exception:
        money = None
    return {"money": money, "schema": SCHEMA, "since": since_t.isoformat(timespec="seconds") if since_t else None,
            "now": now_t.isoformat(timespec="seconds"), "window_hours": round(window_h, 2), "cohort": cohort,
            "hours": [dict(hour=h, **hours[h]) for h in sorted(hours)],
            "paid": {"spend_file": {"date": spend.get("date"), "usd": spend.get("usd")} if spend else None,
                     "telemetry_usd": round(paid_usd, 6), "verdicts": paid_n}}


CALL_SPANS = ("run", "review")       # a model call is an event of these spans with a role; the paid critic's verdict is a call too
GREEN_STATUSES = ("REVIEW", "PROMOTED", "DONE", "accepted", "promoted")


def money_report(state_dir, now=None, spend=None, until="2026-11-30") -> dict:
    """W-money 4: accepted in the last hour, accepted per 1000 model calls (24 h and cumulative), the share of code cards whose
    FIRST pass with an edit passed the gates (24 h, with n), the paid allowance still free for each day up to ``until``.
    ``spend`` = dollars spent so far (default: the paid critic's own total; None when it cannot be read)."""
    now_t = _t(now) or dt.datetime.now().astimezone()
    hour_ago, day_ago = now_t - dt.timedelta(hours=1), now_t - dt.timedelta(hours=24)
    accepted, calls_all, calls_day, passes = {}, 0, 0, {}
    for row in _rows(state_dir):
        t, tid, span = _t(row["ts"]), row.get("task_id"), row["span"]
        if (span in CALL_SPANS and row.get("role")) or span == "paid_critic":
            calls_all += 1
            calls_day += t >= day_ago
        if not isinstance(tid, str) or not tid:
            continue
        if span == "accept" and row.get("status") == "accepted" and (tid not in accepted or t < accepted[tid]):
            accepted[tid] = t
        if span == "run" and not row.get("role") and row.get("kind") == "code" and row.get("changed") \
                and isinstance(row.get("attempt"), int) and not isinstance(row.get("attempt"), bool):
            if tid not in passes or row["attempt"] < passes[tid][0]:
                passes[tid] = (row["attempt"], t, row.get("status") in GREEN_STATUSES)
    for tid, r in (_json(Path(state_dir) / "loop_state.json").get("accepted") or {}).items():
        if isinstance(r, dict) and isinstance(tid, str) and tid not in accepted:
            accepted[tid] = _t(r.get("at")) or now_t
    day_accepted = sum(1 for t in accepted.values() if t >= day_ago)
    recent = [green for _, t, green in passes.values() if t >= day_ago]
    if spend is None:
        try:
            from tools import factory_paid_critic as P
            spend = P.spent_total()
        except Exception:
            spend = None
    left = []
    try:
        from tools import factory_paid_critic as P
        for d in P.allowance_left_by_day(spent=spend or 0.0, until=until, since=now_t.date().isoformat()):
            left.append(dict(d, left=d["left"] if spend is not None else None))
    except Exception:
        pass
    return {"accepted_hour": sum(1 for t in accepted.values() if t >= hour_ago),
            "accepted_per_1000_calls": {
                "day": round(1000 * day_accepted / calls_day, 2) if calls_day else None, "day_accepted": day_accepted,
                "day_calls": calls_day,
                "total": round(1000 * len(accepted) / calls_all, 2) if calls_all else None,
                "total_accepted": len(accepted), "total_calls": calls_all},
            "edit_first_try_pct": {"pct": round(100 * sum(recent) / len(recent), 1) if recent else None,
                                   "n": len(recent), "green": sum(recent)},
            "allowance_left": left}


def render(report) -> str:
    out = ["cohort since %s, now %s (%s h)" % (report["since"] or "the beginning", report["now"], report["window_hours"]),
           "%-6s %6s %9s %8s %8s %6s %6s %10s %9s %7s" % ("kind", "queued", "attempted", "promoted", "accepted", "free", "paid",
                                                          "free/hour", "median_s", "calls")]
    for k in ("echo", "fac", "all"):
        c = report["cohort"][k]
        out.append("%-6s %6d %9d %8d %8d %6d %6d %10s %9s %7s" % (
            k, c["queued"], c["attempted"], c["promoted"], c["accepted"], c["accepted_free"], c["accepted_paid_verified"],
            c["accepted_per_hour_free"], c["median_time_s"], c["median_calls"]))
    out.append("per hour (queued/attempted/promoted/accepted), echo | fac:")
    for h in report["hours"]:
        f = lambda c: "%d/%d/%d/%d" % (c["queued"], c["attempted"], c["promoted"], c["accepted"])
        out.append("  %s  %s | %s" % (h["hour"], f(h["echo"]), f(h["fac"])))
    p = report["paid"]
    out.append("paid critic: %s verdicts, telemetry usd %s, spend file %s" % (p["verdicts"], p["telemetry_usd"], p["spend_file"]))
    m = report.get("money")
    if m:
        k, e = m["accepted_per_1000_calls"], m["edit_first_try_pct"]
        out.append("money: accepted_hour %s, accepted per 1000 calls day %s total %s, edit first try %s%% (n=%s)" % (
            m["accepted_hour"], k["day"], k["total"], e["pct"], e["n"]))
        out.append("allowance left: " + ", ".join("%s %s" % (d["day"][5:], d["left"]) for d in m["allowance_left"]))
    return "\n".join(out)


def span_fields(report) -> dict:
    """The flat payload of the hourly telemetry span (no per-hour table)."""
    return {"cohort": report["cohort"], "paid": report["paid"], "window_hours": report["window_hours"],
            "since": report["since"], **({"money": report["money"]} if report.get("money") else {})}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="factory_metrics", description="accepted per hour, time and calls per accepted")
    p.add_argument("--state-dir", type=Path, default=Path("C:/agent-factory/echo"))
    p.add_argument("--since", help="cohort start (ISO time): tasks first queued after it")
    p.add_argument("--now")
    p.add_argument("--paid-spend", type=Path, help="paid_spend.json (default: the paid critic's state dir)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    spend = a.paid_spend
    if spend is None:
        try:
            from tools import factory_paid_critic as P
            spend = P._spend_file()
        except Exception:
            spend = None
    r = build_report(a.state_dir, since=a.since, now=a.now, paid_spend=spend)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
