"""1.6: the end-to-end canary. A new version of the factory runs ONE seeded row (a deliberately broken `add`) through the whole
chain on its own throw-away repository, state and paths; only a `green` lets a restart on that version go on.

    python -m tools.factory_canary --sha SHA --out FILE --work DIR --env-file FILE --channels FILE [--minutes 25]

exit code: 0 green, 3 inconclusive (no quota, no cloud: nothing is proven), 4 red.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools import agent_factory as F
from tools import agent_factory_import as IMP

ROW = "B9"
SEED_FILES = {      # the seed lives in this module: the mirror publishes modules, not a data directory
    "echo_sync/canary_mod.py": "def add(a, b):\n    return a - b\n",
    "tests/test_canary.py": "from echo_sync.canary_mod import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    "tests/data/factory_durations.json": '{"tests/test_canary.py": 0.1}\n',
}
WAITS = ("channel_cooldown", "architect_wait", F.REASON_CLOUD_DOWN)
GREEN, INCONCLUSIVE, RED = "green", "inconclusive", "red"
EXIT = {GREEN: 0, INCONCLUSIVE: 3, RED: 4}


def backlog_text() -> str:
    """A real, bounded section 4 (IMP.ACTIVE_START .. IMP.ACTIVE_END) with the one row the triage reads."""
    text = ("## 4. Canary\n"
            "| ID | Формулировка | Evidence | Приоритет | Состояние | Примечание |\n"
            "|---|---|---|---|---|---|\n"
            "| B9 | в echo_sync/canary_mod.py add возвращает разность вместо суммы; тест tests/test_canary.py | x | P1 | новая | — |\n"
            "## 5. End\n")
    assert IMP.ACTIVE_START.match(text.splitlines()[0]) and IMP.ACTIVE_END.match(text.splitlines()[-1])
    return text


def verdict(state: dict, events=(), ls=None) -> tuple[str, str]:
    rows = [r for r in ((state or {}).get("tasks") or {}).values()
            if isinstance(r, dict) and F.row_of(str(r.get("backlog_id") or "")) == ROW]
    if any(r.get("status") == "PROMOTED" for r in rows):
        return GREEN, ""
    failed = [r for r in rows if r.get("status") == "FAILED"]
    if failed:
        return RED, str(failed[-1].get("reason") or "failed")
    waits = sorted({str(e.get("reason")) for e in events if isinstance(e, dict) and e.get("reason") in WAITS})
    if waits:
        return INCONCLUSIVE, "the channel or the cloud was not there: " + ", ".join(waits)
    held = ((ls or {}).get("quarantine") or {}).get(ROW)    # a row cut off before it had any task: the loop's own quarantine
    if not rows and isinstance(held, dict):
        return RED, "quarantine: " + str(held.get("why") or "the row was quarantined")
    return RED, "the row did not finish in time" if rows else "row was never sliced"


def _usable_default(env_file, channels) -> int:
    """How many channels of the channels file got a key: its variable is in the key file or in the environment."""
    names = [c.get("key_env") for c in json.loads(Path(channels).read_text(encoding="utf-8") or "{}").get("channels", [])]
    have = set()
    try:
        for line in Path(env_file).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip().removeprefix("export ").strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                if value.strip().strip("\"'"):
                    have.add(key.strip())
    except OSError:
        pass
    return sum(1 for n in names if n and (n in have or os.environ.get(n)))


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=canary", "-c", "user.email=canary@example.com", *args],
                   check=True, capture_output=True)


def _run_loop(argv, env) -> int:
    return subprocess.run([sys.executable, "-B", "-m", "tools.factory_loop", *argv], env=env,
                          cwd=str(Path(__file__).resolve().parents[1])).returncode


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _events(state_dir) -> list:
    out = []
    try:
        for line in (Path(state_dir) / "telemetry.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def main(argv=None, run_loop=None, usable=None) -> int:
    p = argparse.ArgumentParser(prog="factory_canary")
    p.add_argument("--sha", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--channels", type=Path, required=True)
    p.add_argument("--minutes", type=int, default=25)
    a = p.parse_args(argv)
    run_loop, usable = run_loop or _run_loop, usable or _usable_default

    def write(status, reason):
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps({"sha": a.sha, "status": status, "reason": reason,
                                     "at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}), encoding="utf-8")
        return EXIT[status]

    try:
        return _run_canary(a, write, run_loop, usable)
    except Exception as e:      # noqa: BLE001  whatever breaks, the verdict file is written and the code is 4 (red cancels the restart)
        try:
            return write(RED, "the canary itself failed: " + type(e).__name__ + ": " + str(e)[:200])
        except Exception:       # noqa: BLE001  not even the file can be written: still the red code
            return EXIT[RED]


def _run_canary(a, write, run_loop, usable) -> int:
    if usable(a.env_file, a.channels) <= 0:
        return write(RED, "no keys: the version sees no channel key")
    base = a.work / a.sha
    repo, state, backlog, none_env = base / "repo", base / "state", base / "BACKLOG.md", base / "no_paid_key.txt"
    shutil.rmtree(base, ignore_errors=True)
    for rel, text in SEED_FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
    state.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "canary/" + a.sha)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "canary seed")
    backlog.write_text(backlog_text(), encoding="utf-8")
    none_env.write_text("", encoding="utf-8")          # no paid key: the free path is what is proven
    until = (dt.datetime.now() + dt.timedelta(minutes=a.minutes)).strftime("%Y-%m-%d %H:%M")
    args = ["--repo", str(repo), "--worktree", str(repo), "--branch", "canary/" + a.sha, "--backlog", str(backlog),
            "--state-dir", str(state), "--env-file", str(a.env_file), "--channels", str(a.channels),
            "--until", until, "--exit-when-idle", "--no-cloud-sweep"]
    env = dict(os.environ, FACTORY_PAID_ENV=str(none_env))
    try:
        run_loop(args, env)
    except Exception as e:                              # a loop that cannot even run proves nothing good
        return write(RED, "the loop failed to run: " + type(e).__name__)
    status, why = verdict(_read_json(state / "state.json", {}), _events(state), _read_json(state / "loop_state.json", {}))
    return write(status, why)


if __name__ == "__main__":
    sys.exit(main())
