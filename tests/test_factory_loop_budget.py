"""<id>/<id>: the day's model-call budget is the capacity of the channel registry, not a hand number. Live 20.11 02:35:
259 of a hand-set 400 calls were spent by 02:30; the loop would have stood from about 04:00 to midnight while every
channel still had quota."""
import json

from tests.test_factory_loop_ab import make, runner_args
from tools import agent_factory_runner as W
from tools import factory_loop as L

ROW = {"id": "g1", "model": "google/gemini-x", "group": "g", "key_env": "FAKE_KEY_ENV", "tpm": 100000, "rpm": 100}


def _channels(env, rows):
    (env.tmp / "channels.json").write_text(json.dumps({"channels": rows}), encoding="utf-8")


def test_the_budget_is_the_rpd_of_the_verified_channels_with_a_key(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    _channels(env, [dict(ROW, rpd=1000, verified=True), dict(ROW, id="g2", group="g2", rpd=500, verified=True),
                    dict(ROW, id="g3", group="g3", rpd=7000, verified=False),
                    dict(ROW, id="g4", group="g4", rpd=9000, verified=True, key_env="NO_SUCH_KEY_ENV")])
    env.loop(extra={"extra_env": {"FAKE_KEY_ENV": "k"}}).step()
    assert runner_args(env)["--max-model-calls"] == "1500"


def test_an_explicit_budget_wins_and_a_broken_registry_gives_the_old_default(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    _channels(env, [dict(ROW, rpd=1000, verified=True)])
    assert env.loop(extra={"extra_env": {"FAKE_KEY_ENV": "k"}}, max_model_calls=77)._call_budget() == 77
    (env.tmp / "channels.json").write_text("not json", encoding="utf-8")
    assert env.loop()._call_budget() == 400


def test_the_runner_takes_the_capacity_of_all_keys():
    assert W.MAX_MODEL_CALLS >= 60000 and L.Config.max_model_calls == 0
