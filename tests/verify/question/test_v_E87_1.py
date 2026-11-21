"""V2 E87.1: the prepared search is taken «by meaning» (``search_identity.same_meaning``) with no switch: a SECOND function of equality outside the table of E87 (``native_prefetch.py:109``), against «No fuzzy semantic equivalence» and A08 4.4.
The row's check: the same contrast table, the lookup is prepared on the first words and the final's own words must not take it.

Three levels. (1) The table of A2 (both directions) on ``same_meaning`` itself: the pairs of different roles are NOT the same meaning. (2) The order of the call on the real ControlledMedia and NativeMediaSocket (a scripted lookup): a prefetch begun on the
cloud's open turn is adopted by a final of the same question and by no other. (3) No behaviour key and no environment name for it (the lock of the family). Not run on the laptop. A red row of (1) or (2) is a defect card for the family Q.
"""
import asyncio
import inspect

import pytest

from echo_sync import native_prefetch, search_identity
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.search_identity import same_meaning
from echo_sync.settings import DEFAULTS
from question_kit import call      # noqa: F401
from test_a2_same_question import REFUSE


@pytest.mark.parametrize('name, a, b', [row[:3] for row in REFUSE], ids=[row[0] for row in REFUSE])
def test_the_roles_of_the_table_of_e87_are_not_one_meaning_in_either_direction(name, a, b):
    assert not same_meaning(a, b) and not same_meaning(b, a), f'{name}: two questions taken for one by meaning'


def prepared_then_final(tmp_path, ear_text, final_text):
    """The cloud's open turn holds ``ear_text`` still for 0.6 s (a prefetch begins), then its final says ``final_text``. Returns (the questions asked of the search, the stages of the wire)."""
    async def go():
        queries, sent, clock = [], [], [0]

        async def fetch(question):
            queries.append(question)
            return [{'url': 'https://example.org', 'text': 'source'}]

        async def emit(event):
            sent.append(event)
        controller = ControlledMedia(tmp_path / 's.db', session_id='s', source_delivery='delegation')
        wire = NativeMediaSocket(controller, emit, None, fetch, None, prefetch=True, clock=lambda: clock[0], diagnostics=True)
        wire.ready = True
        await wire.provider({'type': 'turn.created', 'turn': {'id': 'u', 'role': 'user', 'transcript': ear_text}})
        clock[0] = 0.6
        await wire.tick()
        await asyncio.sleep(0)
        await wire.provider({'type': 'turn.done', 'turn': {'id': 'u', 'role': 'user', 'transcript': final_text}})
        await asyncio.sleep(0.05)
        stages = [event.get('stage') for event in sent]
        await wire.close()
        return queries, stages
    return asyncio.run(go())


def test_control_the_same_question_with_a_mark_adopts_the_prefetch_and_asks_the_search_once(tmp_path):
    queries, stages = prepared_then_final(tmp_path, 'Что такое инерция', 'Что такое инерция?')
    assert len(queries) == 1 and 'prefetch_adopted' in stages, (queries, stages)


CONTRAST = [
    ('number_of_the_article', 'Что устанавливает статья двести восемнадцатая Гражданского кодекса', 'Что устанавливает статья 219-я Гражданского кодекса'),
    ('negation', 'Что устанавливает статья 218-я Гражданского кодекса', 'Что НЕ устанавливает статья 218-я Гражданского кодекса'),
    ('another_code', 'Что устанавливает статья 218-я Гражданского кодекса', 'Что устанавливает статья 218-я Налогового кодекса'),
    ('article_and_part', 'Что говорит статья 18 часть 2 налогового кодекса', 'Что говорит статья 2 часть 18 налогового кодекса'),
    ('another_road', 'Сколько стоит билет из Москвы в Питер', 'Сколько стоит билет из Питера в Москву'),
    ('another_person', 'Что должен платить он по статье 218 Налогового кодекса', 'Что должна платить она по статье 218 Налогового кодекса'),
    ('another_modal', 'Нужно ли платить налог по статье 218 Налогового кодекса', 'Можно ли платить налог по статье 218 Налогового кодекса'),
    ('before_and_after', 'Что было до статьи 218 Налогового кодекса', 'Что было после статьи 218 Налогового кодекса'),
]


@pytest.mark.parametrize('name, ear, final', CONTRAST, ids=[row[0] for row in CONTRAST])
def test_a_prefetch_prepared_for_one_reading_is_not_taken_by_the_final_of_another(tmp_path, name, ear, final):
    queries, stages = prepared_then_final(tmp_path, ear, final)
    if not queries:
        pytest.skip(f'{name}: no search is prepared for this form on the base: nothing to adopt')
    assert 'prefetch_adopted' not in stages, f'{name}: the search of {ear!r} served {final!r}'


def test_no_behaviour_key_and_no_environment_name_for_the_adoption_by_meaning():
    assert not [key for key in DEFAULTS if 'same_meaning' in key or 'prefetch' in key], [key for key in DEFAULTS if 'prefetch' in key]
    source = inspect.getsource(native_prefetch) + inspect.getsource(search_identity)
    assert 'os.environ' not in source and 'getenv' not in source


def test_one_function_of_equality_for_the_prefetch_is_the_same_meaning():
    """The second equality of the row exists in ONE place: ``native_prefetch`` calls ``same_meaning`` and no other comparison of its own."""
    source = inspect.getsource(native_prefetch.EarlyLookup)
    assert source.count('same_meaning(') == 1, 'a second comparison of questions in the early lookup'
