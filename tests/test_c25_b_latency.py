"""c25-b: the way from the end of speech to the first cue on the stand (``tools.replay.speed``, phone times: cloud 3.3 s, job 1.9 s, search 2.0 s), profile c24 (cloud_context/reports/c24-profile.json).
Times of the stand, not of a laptop nor a phone."""
import logging

import pytest

PROFILE = dict(stop_in_flight='on', stumble_place='on', voice_gain=2.0, voice_presence=0.0, ear_job='on', cloud_form='on', ear_lookup='on', turn_mark='off',
               portion_sense='off', )


def scene(seed, family, **keywords):
    logging.disable(logging.WARNING)
    from tools.replay import first_clock as F, speed as S
    return S.scene(seed, family=family, profile={**F.candidate(), **PROFILE}, **{**S.PHONE, **keywords})


@pytest.mark.parametrize('seed', range(4))
def test_a_word_problem_opens_its_job_on_the_ear_s_text(seed):
    """«Если у меня было 60 рублей и я потратил 90 рублей, сколько денег осталось?»: the ear hears no comma nor «?» (``not_a_question``) and «у меня» kept it from the ear's job: its job began at the
    cloud's final (3.3 s), the cue at 5.5 s. A sum with its condition is nobody's private affair."""
    row = scene(seed, 'money')
    assert row['right'] and not row['violations'], row
    assert row['job'] < 1.0 and row['cue'] < row['final'], row


def test_the_word_problem_is_a_narrow_form():
    from echo_sync.controlled_media import word_problem
    assert word_problem('если у меня было шестьдесят рублей и я потратил девяносто рублей сколько денег осталось')
    assert word_problem('Если у меня было 40 рублей и я потратил 30 рублей, сколько денег осталось?')
    for no in ('сколько у меня денег на карте', 'если у меня было шестьдесят рублей', 'у меня было шестьдесят рублей сколько осталось на моём счёте в банке', 'если я заболею сколько дней больничного'):
        assert not word_problem(no), no


PREFACE = 'Слушай, я тут вчера вечером читал одну книжку по истории, там много всего интересного про средневековье, и вот у меня такой вопрос, '


def prefaced(seed, family, bare):
    """A question said after a long preface in one breath. The stand's model knows the bare question too (the job asks the question's part)."""
    from tools.replay import stand as A
    learn = A.Mind.learn

    def both(self, text, meaning):
        learn(self, text, meaning)
        if meaning and meaning[0] == 'q' and meaning[1].text.startswith(PREFACE) and 'вопрос' in text:
            learn(self, text.rsplit('вопрос', 1)[1].strip(' ,'), meaning)      # the question's own words, in each form the stand teaches (the ear's too)
    A.Mind.learn = both
    try:
        params = {'year': (1,), 'money': (60, 30)}[family]
        return scene(seed, None, question=A.Q(family, params, PREFACE + bare))
    finally:
        A.Mind.learn = learn


@pytest.mark.parametrize('seed', range(3))
@pytest.mark.parametrize('family,bare', [('year', 'в каком году была Куликовская битва?'), ('money', 'если у меня было 60 рублей и я потратил 30 рублей, сколько денег осталось?')])
def test_a_question_after_a_long_preface_opens_its_job_on_the_ear_s_text(seed, family, bare):
    """Case 1: the ear's text of the whole breath is ``not_a_question`` (the question word is past the window) and its «у меня» keeps it from the job: the job began at the cloud's final (3.3 s), the cue at 5.4-6.0 s."""
    row = prefaced(seed, family, bare)
    assert row['right'] and not row['violations'], row
    assert row['job'] is not None and row['job'] < 1.0 and row['cue'] < row['final'], row

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
