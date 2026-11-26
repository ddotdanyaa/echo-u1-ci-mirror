"""f1-question (WAVE15): ``gate_text`` silent on a long preface with the question at its end, ``prepare_wide`` refusing the final. Scene n1_02 step 1."""
import logging

import pytest

import helpers_s6_state as S
from echo_sync.classifier import strip_fillers
from echo_sync.fast_text import refusal
from echo_sync.gate_text import TALK, decide
from test_h1_fast_text import rig, user_says      # noqa: F401 - rig is the fixture
from test_h7 import wide_fast

FULL = 'Добрый день, садитесь, чай, кофе будете, нет, ну ладно. Резюме ваше я видела, опыт хороший. Давайте сразу по делу, э-э, испытательный срок для главного бухгалтера, какой максимум'
CUT = ['Добрый день, садитесь, чай, кофе будете, нет, ну ладно.', 'Резюме ваше я видела, опыт хороший. Давайте сразу по делу, э-э, испытательный срок для главного бухгалтера,', 'какой максимум']

# 1. gate_text: the head of a question cut by the cloud is no talk

@pytest.mark.parametrize('said', [CUT[1], 'давайте сразу по делу э испытательный срок для главного бухгалтера', 'Давайте сразу по делу, испытательный срок для главного бухгалтера.',
                                  'испытательный срок для главного бухгалтера', 'Перейдём к делу, отпуск для совместителя.', 'Ну и вот, короче, по делу, отпуск для совместителя', FULL])
def test_the_head_of_a_question_is_no_talk(said):
    assert decide(said).kind != TALK


@pytest.mark.parametrize('said', ['Резюме ваше я видела, опыт хороший.', 'Я вчера до двух ночи сидел над курсовой, глаза слипаются.', 'Мы вчера ходили в кино, фильм был длинный и скучный.'])
def test_a_remark_is_still_talk(said):
    assert decide(said).kind == TALK


def run_scene(rig, pieces, caplog):
    caplog.set_level(logging.INFO)
    for i, text in enumerate(pieces):
        user_says(rig, f'u{i}', text)
        rig.w.feed(S.turn_created(f'a{i}', 'assistant', 'Ну'))
        rig.pump(0.7)
    return [r.question for r in rig.fake.runs], [r.getMessage() for r in caplog.records if 'gate_text kind=talk' in r.getMessage()]


def test_the_cut_scene_gets_its_jobs_the_gate_keeps_nothing_quiet(rig, caplog):
    runs, talk = run_scene(rig, CUT, caplog)
    assert talk == [] and any('главного бухгалтера' in q for q in runs), runs


# 2. prepare_wide: the final's new words are fillers or the ear's word by its stem and sound; numbers, «не», roles exact

HEARD = 'испытательный срок для главного бухгалтера какой максимум'


def soft(heard, final):
    return refusal(heard, final, strip=lambda text: strip_fillers(text, None), soft=True)


@pytest.mark.parametrize('heard, final', [
    ('испытательный срок для главного бухгалтерии какой максимум', 'испытательный срок для главного бухгалтера, какой максимум'),     # the ear's ending: one stem, one sound
    (HEARD, 'испытательный срок для главного бухгалтера, какой, собственно, максимум'),
    (HEARD, 'испытательный срок для главного бухгалтера, какой вообще максимум, получается'),
    (HEARD, 'испытательный срок для главного бухгалтера, короче, какой максимум'),
])
def test_soft_acceptance(heard, final):
    assert soft(heard, final) is None


@pytest.mark.parametrize('heard, final', [
    ('испытательный срок для бухгалтера какой максимум', 'испытательный срок для главного бухгалтера, какой максимум'),      # a role word is no filler
    ('испытательный срок для главного бухгалтера', 'испытательный срок для главного бухгалтера, какой максимум'),
    ('испытательный срок для главного бухгалтера какой максимум', 'испытательный срок не для главного бухгалтера, какой максимум'),
    ('испытательный срок три месяца для главного бухгалтера', 'испытательный срок шесть месяцев для главного бухгалтера'),
    ('какая столица австралии', 'Какая столица Австрии'), ('что такое сальто', 'Что такое сальдо'), ('налог на прибыль', 'налог на прибытие'),
    ('какого вида налог', 'какого типа налог'),
])
def test_soft_still_refuses(heard, final):
    assert soft(heard, final) is not None


def test_the_wide_job_on_the_ear_serves_the_final_of_the_scene():
    fast, _, _ = wide_fast()
    fast.prepare('давайте сразу по делу испытательный срок для главного бухгалтерии какой максимум')
    assert fast.release(qid='u1', turn='t1', epoch=1, question=FULL) == 'adopted'
    fast.close()
