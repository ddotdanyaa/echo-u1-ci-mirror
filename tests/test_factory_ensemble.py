"""W-vgs: the ensemble core: votes and order, the early exit, invalid answers sifted out, a refused channel is no answer."""
import threading
import time

from tools import factory_ensemble as ENS


def _verify(answer):
    if answer.startswith("bad"):
        return False, "invalid " + answer, ""
    return True, "", answer.split(":")[0]


def test_votes_and_order():
    answers = {0: "b:1", 1: "a:1", 2: "b:2", 3: "c:1"}
    gate = {"n": 0}

    def ask(n, temperature, channel):
        return answers[n]

    ens = ENS.Ensemble(4, ask, _verify, total_s=5)
    # no early exit here: the keys are b, a, b, c but the same key from two calls ends the run, so the b group leads
    result = ens.run()
    assert result[0].key == "b" and result[0].votes >= 2
    assert ens.stats["votes_top"] == result[0].votes


def test_order_votes_then_arrival():
    clock = {"t": 0.0}

    def ask(n, temperature, channel):
        return ["x:0", "y:0", "z:0"][n]

    ens = ENS.Ensemble(3, ask, _verify, total_s=5, first_good_s=0.3)
    result = ens.run()
    assert {c.key for c in result} == {"x", "y", "z"}
    assert [c.order for c in result] == sorted(c.order for c in result)     # equal votes: the earlier arrival first
    assert ens.stats["unique"] == 3 and ens.stats["valid"] == 3


def test_early_exit_on_two_equal_keys():
    slow_started = threading.Event()

    def ask(n, temperature, channel):
        if n == 2:
            slow_started.set()
            time.sleep(3)
            return "other:1"
        return "same:%d" % n

    ens = ENS.Ensemble(3, ask, _verify, total_s=10)
    began = time.monotonic()
    result = ens.run()
    assert time.monotonic() - began < 2
    assert ens.early and result[0].key == "same" and result[0].votes == 2


def test_invalid_answers_are_sifted():
    def ask(n, temperature, channel):
        return "bad%d" % n

    ens = ENS.Ensemble(3, ask, _verify, total_s=5)
    assert ens.run() == []
    assert ens.stats["answered"] == 3 and ens.stats["valid"] == 0 and len(ens.rejected) == 3


def test_refused_channel_is_filled_by_another():
    seen = []

    def ask(n, temperature, channel):
        seen.append(channel)
        if channel == "down":
            raise ENS.ChannelRefused("503")
        return "ok:%d" % n

    ens = ENS.Ensemble(2, ask, _verify, channels=["down", "up"], total_s=5)
    result = ens.run()
    assert result and result[0].key == "ok"
    assert ens.stats["refused"] >= 1 and ens.stats["answered"] == 2


def test_temperatures_differ():
    got = {}

    def ask(n, temperature, channel):
        got[n] = temperature
        return "t:%d" % n

    ENS.Ensemble(4, ask, _verify, total_s=5).run()
    assert len(set(got.values())) >= 3


def test_total_term_ends_the_run():
    def ask(n, temperature, channel):
        time.sleep(2)
        return "late:%d" % n

    began = time.monotonic()
    ens = ENS.Ensemble(2, ask, _verify, total_s=0.3)
    assert ens.run() == [] and time.monotonic() - began < 1.5


def test_fingerprint_ignores_formatting_of_python():
    a = ENS.fingerprint("x = 1  # c\n", "m.py")
    b = ENS.fingerprint("x   =   1\n", "m.py")
    assert a == b and a != ENS.fingerprint("x = 2\n", "m.py")
    assert ENS.fingerprint("a  \nb\n", "t.txt") == ENS.fingerprint("a\nb  \n\n", "t.txt")
