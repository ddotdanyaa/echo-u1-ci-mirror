"""V E32 (BACKLOG: «Квоты и полезность канала: число запросов, отмен, побед, ошибок»): what a call spends of the first road (``Roads.spend``, U107) counts requests and answers, but not the CANCELLED requests nor the
FAILED ones, so «доля пользы» (wins of all asked) cannot be told from the call trace. Real ``Roads`` walking real road functions; no mock of the counting."""
import threading

from echo_sync import reserve_text
from echo_sync.reserve_text import Roads


def _fresh():
    for table in (reserve_text._REST, reserve_text._BUDGET):
        table.clear()
    reserve_text._PRIMARY['until'] = 0.0


def _walk(roads, cancelled=None):
    return ''.join(piece for piece in roads({'input': 'Что такое инерция?'}, cancelled or threading.Event()) if isinstance(piece, str))


def test_spend_counts_a_failed_request_of_the_first_road_as_an_error():
    _fresh()

    def road(request, cancelled):
        raise RuntimeError('http_500')
        yield ''      # pragma: no cover

    roads = Roads(road, None)
    try:
        _walk(roads)
    except Exception:      # noqa: BLE001 - what the walk does with a dead only road is not asked here
        pass
    spend = roads.spend()['codex']
    assert spend['requests'] == 1 and spend.get('errors') == 1, spend


def test_spend_counts_a_cancelled_request_of_the_first_road_as_cancelled_not_as_a_win():
    _fresh()
    stop = threading.Event()

    def road(request, cancelled):
        yield 'Начало '
        stop.set()
        cancelled.set()
        yield 'продолжения.'

    roads = Roads(road, None)
    _walk(roads, stop)
    spend = roads.spend()['codex']
    assert spend['requests'] == 1 and spend.get('cancelled') == 1 and spend['answered'] == 0, spend


def test_spend_names_a_win_apart_from_asked_so_the_share_of_use_can_be_told():
    _fresh()

    def road(request, cancelled):
        yield 'Ответ.'
        yield {'usage': {'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12}}

    roads = Roads(road, None)
    _walk(roads)
    spend = roads.spend()['codex']
    assert {'requests', 'answered', 'cancelled', 'errors'} <= set(spend), sorted(spend)
    assert (spend['requests'], spend['answered'], spend['cancelled'], spend['errors']) == (1, 1, 0, 0), spend
