"""E60 (package EA): the ear's vocabulary comes from the material AND the base. The answer's own terms (C6) were there; the BASE - the owner's materials, ``materials/context.md`` -
is the second source: its plain words (never a number, never «не»/«ни») are the bias of every utterance the real ear starts, after the waiting portion and the answer's terms, before the
command words, inside the one length cap. Stand: the real ControlledMedia + NativeMediaSocket (helpers_night_memory.Call) with the real ear (``ear_shadow.for_call``); only the recognizer is a toy
that keeps the bias it was started with. No key: ``base`` is a rule of the ear (the settings do not know it)."""
import base64
import logging

import pytest

import helpers_night_memory as N
from echo_sync import ear_shadow, ear_sherpa, settings as cfg
from echo_sync.settings import resolve
from test_ear_shadow import ScriptedDetector
from test_s5_ear_part import LIVE, Toy, mind, settle, tagged

BASE = ('Сублимация это переход вещества из твёрдого состояния в газообразное. Сублимация идёт без плавления. Антресоль и контейнер. Статья 422 не допускает это.\n') * 3


def phrases(bias):
    return [p for p in str(bias or '').split('/') if p]


def heard(tmp_path, caplog, base):
    caplog.set_level(logging.INFO)
    toy = Toy()
    call = N.Call(tmp_path, mind, **LIVE)
    worker = ear_shadow.EarWorker(lambda: toy)
    assert worker.wait_ready(5)
    call.worker = worker
    if base is not None and base.thread is not None:
        base.thread.join(5)
    call.w.wire.ear = ear_shadow.for_call(resolve(LIVE), call.c, detector_factory=lambda: ScriptedDetector(['onset', 'speech', 'speech', 'end']), worker=worker, report=call.trace.note,
                                         clock=call.w.clock.now, base=base)
    call.finals = lambda: [r for r in call.journal() if r['ev'] == 'ear_final']
    for i in range(4):
        call.w.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(tagged(i)).decode('ascii')})
        call.w.advance(0.1)
    settle(call, 1)
    started = list(toy.started)
    call.close()
    return started


def test_the_real_ear_starts_an_utterance_with_the_terms_of_the_base(tmp_path, caplog):
    got = phrases(heard(tmp_path, caplog, ear_shadow.BaseTerms(text=BASE).prime())[0])
    assert any(p.startswith('сублимаци') for p in got) and 'антресоль' in got, 'the base is in the bias of the first utterance'
    assert all(not any(ch.isdigit() for ch in p) and p not in ('не', 'ни') for p in got), 'never a number or a negation'
    assert got[-len(ear_sherpa.COMMAND_HOTWORDS):] == list(ear_sherpa.COMMAND_HOTWORDS), 'the command words stay last'


def test_without_a_base_the_bias_is_what_it_was(tmp_path, caplog):
    got = phrases(heard(tmp_path, caplog, ear_shadow.BaseTerms(text='').prime())[0])
    assert got == list(ear_sherpa.COMMAND_HOTWORDS)


def test_the_answers_terms_come_before_the_bases_and_the_cap_holds():
    base = ear_sherpa.base_terms(BASE)
    both = phrases(ear_sherpa.hotwords_for('Переход вещества', material=['Плавление металла требует нагрева.'], base=base))
    assert both[0] == 'переход вещества'
    assert both.index(next(p for p in both if p.startswith('плавлен'))) < both.index(next(p for p in both if p.startswith('сублимаци')))
    big = ['слово%s' % ''.join(chr(1072 + (i // 33 ** k) % 32) for k in range(3)) * 2 for i in range(200)]
    assert len('/'.join(phrases(ear_sherpa.hotwords_for(None, base=big)))) <= ear_sherpa.MATERIAL_CHARS + 60


def test_the_base_has_no_key():
    assert 'ear_base' not in resolve({'ear_base': 'on'}) and not any('base' in key and key.startswith('ear') for key in cfg.DEFAULTS)
