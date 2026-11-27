"""Registry 6.06: «Расшифровка сокращений один раз за звонок» (abbrev_once: a table abbreviation is spelled out once per call, again if the listener asks what it is).

Registry state: ВКЛЮЧЕНО навсегда (the key abbrev_once is deleted; with an empty table `abbreviations` nothing happens). Proved here through the real ControlledMedia + NativeMediaSocket
(tests/helpers_s6_state.World, fakes only at the boundary): the table {НДС: ...} is DATA given by the test, the cloud answers three questions of one call that all mention «НДС».
Promise: answer 1 is heard (and synthesised) with the term spelled out; answer 2 keeps the short «НДС»; answer 3, to «Что такое НДС?», spells it out again.
There is no switch: the rule is the controller's.
Other keys: repeat_seconds=2.0, max_auto_repeats=3 as in the live profile. Dummy check (private copy): the stock expander in place of ControlledMedia._abbreviations -> it fails on answer 2."""
import pytest

import helpers_s6_state as S
from echo_sync.controlled_host import controller_settings
from echo_sync.settings import resolve

TABLE = {'НДС': 'налог на добавленную стоимость'}      # the data of the function
LONG = TABLE['НДС']
CALL = [('Какая ставка НДС в учебной задаче?', 'В учебной задаче НДС составляет двадцать процентов.'),
        ('А сколько НДС со ста рублей?', 'В этом случае НДС равен двадцати рублям.'),
        ('Что такое НДС?', 'В учебной задаче НДС означает налог с добавленной стоимости.')]


def heard_per_answer(**extra):
    """Run the call; return, per question, (text of the cues the phone got, texts that went to synthesis). The profile swap is undone and the stand closed."""
    profile = resolve({'repeat_seconds': 2.0, 'max_auto_repeats': 3, 'abbreviations': TABLE, **extra})
    original = S.host_kwargs
    host = {'settings': controller_settings(profile), 'repeat_seconds': profile['repeat_seconds'], 'max_auto_repeats': profile['max_auto_repeats']}
    S.host_kwargs = lambda: {**original(), **host}
    w = S.World()
    try:
        out = []
        for i, (question, answer) in enumerate(CALL):
            cues, synth = len(w.cues), len(w.synth_calls)
            w.feed(S.turn_created(f'u{i}', 'user', question[:8]))
            w.feed(S.turn_done(f'u{i}', 'user', question))
            w.feed(S.turn_done(f'a{i}', 'assistant', answer))
            w.advance(1)
            out.append((' '.join(c.text for c in w.cues[cues:] if not c.diagnostic), ' '.join(w.synth_calls[synth:])))
            w.advance(20)
        assert not w.errors and not w.violations, (w.errors, w.violations)
        return out
    finally:
        w.close()
        S.host_kwargs = original


def test_abbreviation_is_spelled_out_once_per_call_and_again_when_asked():
    (first, first_synth), (second, second_synth), (third, third_synth) = heard_per_answer()
    assert LONG in first and LONG in first_synth, 'the first answer spells the term out, and it is what the voice says'
    assert 'НДС' in second and LONG not in second and LONG not in second_synth, f'the second answer keeps the short form: {second!r}'
    assert LONG in third and LONG in third_synth, f'asked «Что такое НДС?», the term is spelled out again: {third!r}'
