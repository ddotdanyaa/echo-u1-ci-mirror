"""<id>: the loop emits the metrics span once an hour (no LLM)."""
from test_factory_loop import Env, task_row, env  # noqa: <id>


def _spans(env):
    return [x for x in env.events() if x["span"] == "metrics"]


def test_metrics_span_once_per_hour(env):
    lp = env.loop()
    lp.step()
    assert len(_spans(env)) == 1
    row = _spans(env)[0]
    assert row["status"] == "ok" and set(("echo", "fac", "all")) <= set(row["cohort"])
    lp.step()
    assert len(_spans(env)) == 1                      # the same hour
    env.clock.sleep(3601)
    lp.step()
    assert len(_spans(env)) == 2
