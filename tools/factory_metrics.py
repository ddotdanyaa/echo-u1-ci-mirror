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
            with p.open(encoding="utf-8", errors="replace") as fh:       # fac-58: line by line, not the whole journal
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and row.get("span") and _t(row.get("ts")):
                        yield row
        except OSError:
            continue


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
def is_slice_call(row) -> bool:
    """The slicer's request to a model: a ``slice`` event with an engine whose status is not ``barred`` (a barred event is a
    tick of a waiting row, no call was made)."""
    return row.get("span") == "slice" and bool(row.get("engine")) and row.get("status") != "barred"


RED_FIRST_TRY = ("gate", "part_failed", "off_path", "no_changes", "neighbors_regression")
NOT_A_PASS = ("rate_minute", "rate_day", "transient", "channel_wait", "cloud_", "network", "timeout", "region")


def first_try_verdict(row):
    """False (red) / True (green) for a code run row that is the card's pass with an edit; None for a deferral or a row that
    says nothing about the edit (the next row of the card is looked at)."""
    reason = str(row.get("reason") or "")
    if row.get("status") == "WAITING_CHANNEL" or reason.startswith(NOT_A_PASS):
        return None
    if reason.startswith(RED_FIRST_TRY) or any(x in reason for x in RED_FIRST_TRY[1:]):
        return False
    if row.get("status") in GREEN_STATUSES:
        return True
    return None


GREEN_STATUSES = ("REVIEW", "PROMOTED", "DONE", "accepted", "promoted")


def vgs_report(state_dir, now=None) -> dict:
    """W-vgs 5: the ensemble of the small tier over the last 24 h, from the ``vgs`` of the run rows: ``cards`` (passes with
    an ensemble), ``valid_pct`` (valid answers among the answered), ``green_pct`` (passes with a green union), ``p_hat``
    (green unions among the unions that reached the gates)."""
    now_t = _t(now) or dt.datetime.now().astimezone()
    day_ago = now_t - dt.timedelta(hours=24)
    cards = green = gates = answered = valid = 0
    for row in _rows(state_dir):
        vgs = row.get("vgs")
        if row["span"] != "run" or not isinstance(vgs, dict) or _t(row["ts"]) < day_ago:
            continue
        number = lambda name: vgs.get(name) if type(vgs.get(name)) is int else 0
        cards += 1
        answered += number("answered")
        valid += number("valid")
        gates += number("gates")
        green += type(vgs.get("green_at")) is int
    pct = lambda a, b: round(100.0 * a / b, 1) if b else None
    return {"cards": cards, "valid_pct": pct(valid, answered), "green_pct": pct(green, cards), "p_hat": pct(green, gates)}


def money_report(state_dir, now=None, spend=None, until="2026-11-30") -> dict:
    """W-money 4: accepted in the last hour, accepted per 1000 model calls (24 h and cumulative), the share of code cards whose
    FIRST pass with an edit passed the gates (24 h, with n), the paid allowance still free for each day up to ``until``.
    ``spend`` = dollars spent so far (default: the paid critic's own total; None when it cannot be read)."""
    now_t = _t(now) or dt.datetime.now().astimezone()
    hour_ago, day_ago = now_t - dt.timedelta(hours=1), now_t - dt.timedelta(hours=24)
    accepted, calls_all, calls_day, passes = {}, 0, 0, {}
    wire_all = wire_day = 0       # fac-farm 2 (11.2): network requests = calls + the ensemble's asked branches + review retries
    for row in _rows(state_dir):
        t, tid, span = _t(row["ts"]), row.get("task_id"), row["span"]
        counted = bool((span in CALL_SPANS and row.get("role")) or span == "paid_critic" or is_slice_call(row))
        if counted:
            calls_all += 1
            calls_day += t >= day_ago
        vgs = row.get("vgs") if isinstance(row.get("vgs"), dict) else {}
        asked = vgs.get("asked") if type(vgs.get("asked")) is int and vgs["asked"] > 0 else 0
        extra = (asked - 1 if counted and asked else asked) + sum(   # a counted call whose ensemble asked n branches = n requests, not n+1
            1 for x in (row.get("events") or []) if str(x).startswith("review_503_retry"))
        wire_all += extra
        wire_day += extra if t >= day_ago else 0
        if not isinstance(tid, str) or not tid:
            continue
        if span == "accept" and row.get("status") == "accepted" and (tid not in accepted or t < accepted[tid]):
            accepted[tid] = t
        if span == "run" and not row.get("role") and row.get("kind") == "code":
            verdict = first_try_verdict(row)
            if verdict is not None and (tid not in passes or t < passes[tid][0]):
                passes[tid] = (t, verdict, row.get("edit_by") == "code")
    for tid, r in (_json(Path(state_dir) / "loop_state.json").get("accepted") or {}).items():
        if isinstance(r, dict) and isinstance(tid, str) and tid not in accepted:
            accepted[tid] = _t(r.get("at")) or now_t
    day_accepted = sum(1 for t in accepted.values() if t >= day_ago)
    recent = {"model": [], "code": []}
    for t, green, by_code in passes.values():
        if t >= day_ago:
            recent["code" if by_code else "model"].append(green)

    def share(rows):
        return {"pct": round(100 * sum(rows) / len(rows), 1) if rows else None, "n": len(rows), "green": sum(rows)}

    explicit = spend is not None
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
            if spend is None:
                value = None
            elif explicit:         # a given total (tests): the same PK formula over the row with that total
                value = round(P._left(d["day"], dict(P._spend_row(), total_usd=float(spend))), 2)
            else:                  # the real number: PK.left
                value = round(P.left(d["day"]), 2)
            left.append(dict(d, left=value))
    except Exception:
        pass
    return {"accepted_hour": sum(1 for t in accepted.values() if t >= hour_ago),
            "accepted_per_1000_calls": {
                "day": round(1000 * day_accepted / calls_day, 2) if calls_day else None, "day_accepted": day_accepted,
                "day_calls": calls_day,
                "total": round(1000 * len(accepted) / calls_all, 2) if calls_all else None,
                "total_accepted": len(accepted), "total_calls": calls_all},
            "accepted_per_1000_wire": {
                "day": round(1000 * day_accepted / (calls_day + wire_day), 2) if calls_day + wire_day else None,
                "day_wire": calls_day + wire_day,
                "total": round(1000 * len(accepted) / (calls_all + wire_all), 2) if calls_all + wire_all else None,
                "total_wire": calls_all + wire_all},
            "edit_first_try_pct": share(recent["model"]),       # the model's edit (kept under the old name)
            "first_try_model": share(recent["model"]), "first_try_code": share(recent["code"]),
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
        k, e, w = m["accepted_per_1000_calls"], m["edit_first_try_pct"], m["accepted_per_1000_wire"]
        out.append("money: accepted_hour %s, accepted per 1000 calls day %s total %s, per 1000 network requests day %s "
                   "total %s, edit first try %s%% (n=%s), by code %s%% (n=%s)" % (
            m["accepted_hour"], k["day"], k["total"], w["day"], w["total"], e["pct"], e["n"],
            m["first_try_code"]["pct"], m["first_try_code"]["n"]))
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
