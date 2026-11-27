"""V3 E14: the identity of the search document and the article: a row about ANOTHER code or ANOTHER article is no source of the question (the same article number of another code never sounds as the fact asked about).
The scene n1_02 step 11 / n1_03 step 16 is «Статья 21 Трудового кодекса» answered with another code's row. The unit rows are in test_a3_search; this is the lookup route on the wire.

Real ControlledMedia and wire (rig of test_h1_fast_text: the lookup route is open, ``S.SOURCE_ROWS`` is what the search returns). Row 1: the code differs -> the job gets no source (the rule of ``_relevant`` / ``search_identity``) and the
answer is not ``source_backed``. Row 2: the article differs. Control: the right code and article -> the job gets the row, ``source_backed``. Not run on the laptop."""
import pytest

import helpers_s6_state as S
from echo_sync import fast_text as FT
from echo_sync.native_media_socket import native_result_text
from test_h1_fast_text import rig      # noqa: F401 - rig is the fixture

QUESTION = 'Проверь, что говорится в статье 19 Трудового кодекса.'
ANSWER = 'Статья 19 Трудового кодекса определяет, что работодатель обязан соблюдать закон. Это основа трудовых отношений.'
RIGHT_ROW = {'url': 'https://example.org/tk19', 'text': 'Статья 19 Трудового кодекса. Работодатель обязан соблюдать законы и иные нормативные акты о труде.'}
OTHER_CODE = {'url': 'https://example.org/nk19', 'text': 'Статья 19 Налогового кодекса. Налогоплательщиками признаются организации и физические лица, на которых возложена обязанность уплачивать налоги.'}
OTHER_ARTICLE = {'url': 'https://example.org/tk21', 'text': 'Статья 21 Трудового кодекса. Работник имеет право на заключение, изменение и расторжение трудового договора.'}


def run_question(rig, rows, monkeypatch):
    monkeypatch.setattr(S, 'SOURCE_ROWS', rows)
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', QUESTION))
    rig.pump()
    run = rig.fake.run(0)
    sent = run.request['input'][0]['content'][0]['text']
    rig.say(0, ANSWER)
    status = (rig.w.controller.engine.state(rig.w.session_id) or {}).get('retrieval_status')
    return sent, status


def test_control_the_right_code_and_article_is_the_source(rig, monkeypatch):
    sent, status = run_question(rig, [RIGHT_ROW], monkeypatch)
    assert sent == native_result_text(rig.w.controller.question_text, [RIGHT_ROW]) and status == 'source_backed'


@pytest.mark.parametrize('row', [OTHER_CODE, OTHER_ARTICLE], ids=['other_code', 'other_article'])
def test_a_row_about_another_code_or_article_is_no_source_and_the_answer_is_not_source_backed(rig, monkeypatch, row):
    sent, status = run_question(rig, [row], monkeypatch)
    assert sent != native_result_text(rig.w.controller.question_text, [row]), 'the wrong document went to the model as the source'
    assert status != 'source_backed', status


def test_the_right_row_beside_the_wrong_one_is_the_source(rig, monkeypatch):
    sent, status = run_question(rig, [OTHER_CODE, RIGHT_ROW], monkeypatch)
    assert 'Налогового' not in sent and status == 'source_backed', (sent, status)
