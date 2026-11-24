"""c25-a G6 (rehearsal Р017 seed 101, the c24 profile): the owner said «В високосном году 366 дней.» right, the cloud confirmed it, the ear heard «триста
пятьдесят шесть» and its number veto took the step back (``local_ear_number_veto boundary=taken_back``). In all 15 take-backs of the c24-e seeds the owner had said
the portion's number (``cloud_context/reports/c25-a/veto_truth.py``): the veto is kept (the real call w3_02: a cloud biased to the answer), but the help after it
is the owner's rule: from the number, not the whole portion again."""
import sys

import pytest

sys.path.insert(0, 'cloud_context/reports/c25-a')
PROF = ('prepare_wide:on,ear_release:on,gate_text:on,instant:on,spare_helper:on,open_overlap:on,warm_start:on,stop_in_flight:on,'
        'stumble_place:on,local_fallback:on,voice_gain:2.0,ear_job:on,cloud_form:on,ear_lookup:on')


def play(name, seed):
    from tools.rehearsal import sim
    spec = sim.Spec(name)
    spec.minutes = min(spec.minutes, 6)
    return sim.play(spec, seed, flags=dict(kv.split(':', 1) for kv in PROF.split(',')))


def test_after_the_number_veto_the_help_starts_at_the_number():
    out = play('Р017', 101)
    veto = [t for t, line in out.ctl if 'boundary=taken_back' in line]
    assert veto, 'the veto no longer happens here: find another seed'
    after = [c for c in out.cues if veto[0] < c[0] < veto[0] + 5]
    assert after and after[0][1] == '366 дней.', after


@pytest.mark.parametrize('name,seed,at', [('Р084', 102, 70.66)])
def test_a_repeat_asked_after_a_newer_question_is_no_old_answer(name, seed, at):
    """G1 repeat_command: the ear heard a new question over the plan, after its cue («Что сказано в пункте 2 статьи 146 НК?»); «Ещё раз, пожалуйста.» before its
    final asks for that answer, not the older plan's (it sounded at 70.66: old_answer). OPEN, not this rule: Р073 seed 102 @97.26, the older plan opened (admitted_answer)
    while the newer question was being said, its first cue held until «ещё раз»."""
    from tools.rehearsal import score
    out = play(name, seed)
    _, eps = score.board(out)
    assert [e for e in eps if e['kind'] == 'old_answer' and abs(e['t'] - at) < 1.0] == []


def test_the_plan_does_not_go_on_after_a_newer_question_heard_over_it():
    """G1 plan_goes_on_after_no_answer (Р086 seed 101): «Действует ли статья 117 НК?» heard by the ear over the ENVD plan, no final; «ты меня хорошо слышишь» took the
    plan over and was declined; the ENVD plan went on at 112.9 as the answer of the newer question (old_answer)."""
    from tools.rehearsal import score
    _, eps = score.board(play('Р086', 101))
    assert [e for e in eps if e['kind'] == 'old_answer' and abs(e['t'] - 112.9) < 1.0] == []


def test_an_admitted_answer_does_not_sound_first_after_a_newer_question():
    """G1 admitted_answer (Р027 seed 105): «Сколько часов в неделе?» (9.2-10.55, the ear heard it as a question at 10.8) after «Сколько дней в високосном году?»;
    the job's answer of the first («В високосном году 366 дней.») was published at 12.0 and said again at 17.38 and 38.56 (old_answer)."""
    from tools.rehearsal import score
    m, eps = score.board(play('Р027', 105))
    assert [e for e in eps if e['kind'] == 'old_answer'] == []
    assert m['missed'] == 0


def test_an_answer_held_back_for_a_newer_question_gives_no_older_plan_back():
    """Р059 seed 101 (the first version of ca2792f): the answer held back went as a decline, and the plan before it went on at 29.48 (old_answer)."""
    from tools.rehearsal import score
    _, eps = score.board(play('Р059', 101))
    assert [e for e in eps if e['kind'] == 'old_answer'] == []
