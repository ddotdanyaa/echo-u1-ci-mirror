"""U20-S1: the table of time constants is complete, its relations hold, a broken one is caught, the clock is injected."""
from echo_sync import reserve_text, timer_policy as tp, controlled_host, native_media_socket, controlled_media

OWNER_LIKE = {'repeat_seconds': 2.0, 'max_auto_repeats': 3, 'dictation_cycle': 'on'}


def test_every_time_constant_is_registered():
    assert tp.unregistered() == []
    assert tp.stale() == []
    assert tp.unscanned_modules() == []


def test_every_module_is_really_scanned_and_no_module_waits_in_a_future_list():
    """M5 (harvest11 9a): FUTURE is empty; ``unscanned_modules`` reads EVERY file of echo_sync, so the six modules once listed as «future» are scanned for real: three hold constants of time (registered), three hold none."""
    import pathlib
    assert tp.FUTURE == ()
    for name in ('conversation_ledger', 'input_state', 'call_audio'):
        assert name in tp.SCANNED and tp.scan(name), name
    for name in ('recall', 'utterance_judge', 'lang_hint'):
        assert tp.scan(name) == [] and name not in tp.SCANNED, name
    assert (pathlib.Path(tp.__file__).parent / 'recall.py').is_file() and tp.scan('no_such_module_yet') == []


def test_no_hard_violation_by_default_and_with_owner_settings():
    for settings in (None, {}, OWNER_LIKE):
        assert [v for v in tp.validate(settings) if v.hard] == []


def test_relations_are_r1_to_r13():
    assert sorted((r.rule for r in tp.RELATIONS), key=lambda rule: int(rule[1:])) == ['R%d' % n for n in range(1, 14)]


def test_r1_mutation_is_caught(monkeypatch):
    monkeypatch.setattr(reserve_text, 'REFUSE_AFTER_S', 11.0)       # the h31 defect
    assert [v.rule for v in tp.validate({}) if v.hard] == ['R1']


def test_new_settings_relations(monkeypatch):
    assert [v.rule for v in tp.validate({'asr_grace_seconds': 9.0})] == ['R10']
    assert tp.validate({'asr_grace_seconds': 8.0}) == []
    soft = tp.validate({'half_listen_seconds': 9.0})
    assert [(v.rule, v.hard) for v in soft] == [('R11', False)]


def test_r9_cap_bounds():
    assert [v.rule for v in tp.validate({'max_auto_repeats': 3, 'cycle_max_repeats': 31})] == ['R9']
    assert [v.rule for v in tp.validate({'max_auto_repeats': 10, 'cycle_max_repeats': 5})] == ['R9']
    assert tp.validate({'max_auto_repeats': 3, 'cycle_max_repeats': 30}) == []


def test_r9_checks_repeat_cap_when_it_exists(monkeypatch):
    from echo_sync import repeat_rule
    monkeypatch.setattr(repeat_rule, 'repeat_cap', lambda **kw: (15, 'ignores unplaced'), raising=False)
    assert [v.rule for v in tp.validate({'max_auto_repeats': 3})] == ['R9']
    monkeypatch.setattr(repeat_rule, 'repeat_cap', lambda cycling, recording, unplaced, record_mode, cycle_max_repeats, max_auto_repeats: (max_auto_repeats if unplaced else cycle_max_repeats, 'x'), raising=False)
    assert tp.validate({'max_auto_repeats': 3}) == []
    assert [v for v in tp.validate(OWNER_LIKE) if v.hard] == []
    monkeypatch.undo()
    assert [v.rule for v in tp.validate({'max_auto_repeats': 3, 'cycle_max_repeats': 31})] == ['R9']


def test_unregistered_sees_a_new_constant(tmp_path, monkeypatch):
    text = 'NEW_WAIT_SECONDS = 5\nBYTES_PER_SECOND = 48000\nNAME = "x"\n'
    (tmp_path / 'input_state.py').write_text(text, encoding='utf-8')      # a module of the table gets a constant: unregistered
    (tmp_path / 'recall.py').write_text(text, encoding='utf-8')           # a module nobody listed gets one: unscanned (no future list: every file is read)
    monkeypatch.setattr(tp, '_DIR', tmp_path)
    assert tp.unregistered() == ['input_state.NEW_WAIT_SECONDS']
    assert tp.unscanned_modules() == ['recall']


def test_clock_lock_holds():
    assert tp.clock_violations() == []


def test_clock_lock_sees_a_direct_call(tmp_path, monkeypatch):
    (tmp_path / 'controlled_media.py').write_text('import time\nclass A:\n    def tick(self):\n        return time.monotonic()\n', encoding='utf-8')
    monkeypatch.setattr(tp, '_DIR', tmp_path)
    assert tp.clock_violations() == [('controlled_media', 'tick', 4)]


def test_promoted_literals_keep_their_values():
    assert tp.QUIET_INTERVAL_S == 3 and tp.COALESCE_SECONDS == 3.2
    assert (tp.LOCAL_READ_TIMEOUT_S, controlled_host.WAKE_TICK_S, controlled_host.RECEIVE_TIMEOUT_S) == (2, .1, 65)
    for key in ('timer_policy.QUIET_INTERVAL_S', 'timer_policy.COALESCE_SECONDS', 'timer_policy.LOCAL_READ_TIMEOUT_S', 'timer_policy.WAKE_TICK_S', 'timer_policy.RECEIVE_TIMEOUT_S'):
        assert key in tp.TIMERS


def test_u20_s3_epoch_is_bumped_only_inside_new_epoch():
    """U20-S3: one owner of the reply token; every other site calls _new_epoch(reason)."""
    import ast, inspect
    from echo_sync import controlled_media
    tree = ast.parse(inspect.getsource(controlled_media))
    owners = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute) and node.target.attr == 'epoch':
                    owners.setdefault(fn.name, []).append(node.lineno)
    assert list(owners) == ['_new_epoch'] and len(owners['_new_epoch']) == 1


def test_u20_s3_new_epoch_bumps_by_one_and_returns_it():
    from echo_sync.controlled_media import ControlledMedia
    probe = type('P', (), {'epoch': 4})()
    assert ControlledMedia._new_epoch(probe, 'test') == 5 and probe.epoch == 5


def test_u20_s5a_play_then_refuse_is_o1():
    led = tp.OrderLedger()
    led.play(3)
    assert led.refusal_allowed(3) == (False, 'O1')
    assert led.refuse(3) == 'O1' and led.violations == [('O1', 3)]


def test_u20_s5a_double_refusal_is_o2():
    led = tp.OrderLedger()
    assert led.refuse(2) is None
    assert led.refuse(2) == 'O2'
    led = tp.OrderLedger()
    led.refuse(2, provisional=True)
    assert led.refusal_allowed(2) == (False, 'O2')


def test_u20_s5a_provisional_then_play_is_allowed():
    led = tp.OrderLedger()
    assert led.refuse(5, provisional=True) is None
    assert led.play(5) is None and led.violations == []


def test_u20_s5a_newer_play_then_older_refuse_is_o3():
    led = tp.OrderLedger()
    led.play(8)
    assert led.refuse(7) == 'O3' and led.violations == [('O3', 7)]
    assert led.refuse(8 + 1) is None


def test_u20_s5a_closed_epoch_is_o4_and_ledger_is_pure():
    led = tp.OrderLedger()
    led.close(4)
    assert led.closed(4) and not led.closed(5)
    assert led.refuse(4) == 'O4' and led.play(4) == 'O4'
    assert tp.OrderLedger().refusal_allowed(1) == (True, None)


# --- U20-S4: token-stamped deferred slots (timer_guard: a rule of the owner) ---

def _controller(tmp_path, **settings):
    from echo_sync.controlled_media import ControlledMedia
    return ControlledMedia(tmp_path / 's.db', session_id='s', settings={'words_per_portion': 3, **settings})


def test_u20_s4_stamped_remembers_the_epoch_it_was_armed_in():
    class Owner:
        slot = tp.Stamped('epoch')
        epoch = 3
    o = Owner()
    assert o.slot is None and tp.stale_slots(o) == []
    o.slot = 9.5
    assert o.slot == 9.5 and tp.stale_slots(o) == []
    o.epoch += 1
    assert tp.stale_slots(o) == ['slot']
    o.slot = None
    assert tp.stale_slots(o) == []


def test_u20_s4_the_eight_slots_are_stamped_on_the_controller():
    from echo_sync.controlled_media import ControlledMedia
    names = sorted(n for n, v in vars(ControlledMedia).items() if isinstance(v, tp.Stamped))
    assert names == sorted(tp.STAMPED_SLOTS) and len(names) == 8


def test_u20_s4_on_clears_the_stale_slot(tmp_path, caplog):
    import logging
    c = _controller(tmp_path)
    c.repeat_at = 12.0
    c.go_on = (1, 2)
    c.resume_repeat = True
    with caplog.at_level(logging.INFO):
        c._new_epoch('t')
    assert c.repeat_at is None and c.go_on is None and c.resume_repeat is False
    assert len([r for r in caplog.records if 'timer_stale' in r.getMessage()]) == 1


def test_u20_s4_a_slot_armed_after_the_bump_is_untouched(tmp_path):
    c = _controller(tmp_path)
    c._new_epoch('t')
    c.repeat_at = 7.0
    c._new_epoch('t2')
    assert c.repeat_at is None
    c.repeat_at = 8.0
    assert tp.stale_slots(c) == [] and c.repeat_at == 8.0
