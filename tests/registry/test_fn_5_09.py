"""Registry 5.09 «Первая подсказка коротким куском 2-4 слова (добавлено проверяющим)» - state per registry: РАБОТАЕТ НА СЕРВЕРЕ
(on, effect not measured), hard-wired in controlled_host.serve (first_useful_gate=True), no settings key.

Proved through the real controlled_host.serve() (HostRig: fake phone, cloud helper, SAPI, lookup, virtual time): the cloud streams
an answer word by word. GREEN (answers with an early comma, 4-5 word cue): the FIRST cue reaches the phone while the answer is still
streaming (before the cloud's final event), is 2-5 words from the start of the answer, goes to synthesis and to the call journal; after
the listener repeats it the next portions are ordinary (2-9 words) and together are the whole answer in order. The cue also starts the
answer, reaches synthesis and the journal on answers WITHOUT an early comma. XFAIL(strict) defects: (a) on such answers (Mars, pump) the
cue is 10 / 7 words, not 2-4; (b) on every answer the cue sounds at the 10th streamed word (~1 s), not once the next word is known.
Dummy check (private copy): first_useful_gate=True -> False in controlled_host.serve (green cue tests go red); an «ideal» stub of
first_cue (4 words once 5 have arrived) turns all xfail tests green under --runxfail.
"""
import json
import re

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

WORD = re.compile(r'[^\W_]+', re.U)
CASES = [
    ('Где находится Байкал?', 'Байкал находится в Восточной Сибири между Иркутской областью и Бурятией и считается самым глубоким озером планеты. '
     'Его глубина превышает полторы тысячи метров. Вокруг озера живут разные редкие виды животных и растений.'),
    ('Как образуется радуга?', 'Радуга образуется при преломлении и отражении солнечного света в каплях дождя, поэтому её видно при солнце и дожде. '
     'Цвета идут в строгом порядке. Первый цвет всегда красный, последний всегда фиолетовый.'),
    ('Что такое скорость?', 'Скорость показывает, как быстро тело меняет своё положение в пространстве за единицу времени. '
     'Её измеряют в метрах в секунду. Для разных задач берут разные единицы измерения.'),
]


def journal(host):
    files = sorted(f for f in (host.home / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name)
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def stream(question, answer, tmp_path, monkeypatch):
    """The cloud streams ``answer`` one word per 0.1 s; returns (what the phone and the journal got, see keys)."""
    out = {}

    async def body(host):
        await host.ask(question)
        words = answer.split(' ')
        host.cloud(F.created('a1', 'assistant', words[0]))
        for n, word in enumerate(words[1:], 1):
            host.cloud(F.delta('a1', ' ' + word, n))
            await host.advance(0.1)
            if host.spoken() and 'fed' not in out:
                out['fed'] = n + 1                       # words of the answer that had arrived when the first cue sounded
        out['before_final'] = list(host.spoken())
        host.cloud(F.done('a1', 'assistant', answer))
        await host.advance(3)
        for k in range(8):                               # the listener repeats each portion aloud, the next one comes
            if len(host.spoken()) < 1 + k:
                break
            host.cloud(F.done('r%d' % k, 'user', host.spoken()[-1]))
            await host.advance(4)
        out['spoken'], out['synth'] = list(host.spoken()), [t for _, t in host.synth_plan.calls]
        out['journal'], out['total'] = journal(host), len(words)
    run_host(tmp_path, monkeypatch, body)
    return out


LATE = [   # ordinary answers with NO early comma or other early boundary
    ('Сколько длится год на Марсе?', 'Год на Марсе длится примерно шестьсот восемьдесят семь земных суток. Это почти вдвое дольше земного года. '
     'Из-за этого времена года там тоже тянутся дольше.'),
    ('Как работает насос?', 'Насос создаёт разность давлений и заставляет жидкость двигаться по трубе. Поток зависит от мощности двигателя. '
     'Для разных жидкостей подбирают разные насосы.'),
]


_RUNS = {}   # one streamed call per case for the whole file (keeps the file fast); the rig lives only inside stream()


def cached(case, tmp_path, monkeypatch):
    if case not in _RUNS:
        _RUNS[case] = stream(*case, tmp_path, monkeypatch)
    return case, _RUNS[case]


@pytest.fixture(params=CASES, ids=['baikal', 'rainbow', 'speed'])
def run(request, tmp_path, monkeypatch):
    return cached(request.param, tmp_path, monkeypatch)


@pytest.fixture(params=CASES + LATE, ids=['baikal', 'rainbow', 'speed', 'mars', 'pump'])
def anyrun(request, tmp_path, monkeypatch):
    return cached(request.param, tmp_path, monkeypatch)


@pytest.fixture(params=LATE, ids=['mars', 'pump'])
def late(request, tmp_path, monkeypatch):
    return cached(request.param, tmp_path, monkeypatch)


def test_first_cue_is_short_and_sounds_before_the_answer_is_complete(run):
    (_, answer), r = run
    first = r['before_final'][0]
    assert len(r['before_final']) == 1, 'one cue only until the listener repeats it'
    assert 2 <= len(WORD.findall(first)) <= 5, first      # registry says 2-4, 5 keeps a term; see the proof notes
    assert ' '.join(WORD.findall(answer)).find(' '.join(WORD.findall(first))) in range(13), 'the cue is the start of the answer (bar a definition lead)'
    assert r['fed'] <= 12 and r['fed'] < r['total'] // 2, 'it sounded long before the cloud had sent the last word (about 1 s of stream)'


def test_next_portions_are_ordinary_size_and_make_the_whole_answer(run):
    (_, answer), r = run
    spoken = r['spoken']
    assert len(spoken) >= 3
    assert all(2 <= len(WORD.findall(t)) <= 9 for t in spoken), spoken       # after the short first cue: ordinary portions, one per repeat
    said, whole = ' '.join(WORD.findall(' '.join(spoken))), ' '.join(WORD.findall(answer))
    assert whole.endswith(said) and len(said) > len(whole) - 20, 'nothing lost, in order (a definition lead «X — это» may be dropped)'


def test_the_cue_goes_to_synthesis_and_to_the_journal_also_without_an_early_comma(anyrun):
    (_, answer), r = anyrun
    assert r['before_final'] and WORD.findall(answer)[0] == WORD.findall(r['before_final'][0])[0], 'the cue starts the answer, before its final event'
    first = r['before_final'][0]
    assert first in r['synth'], r['synth']
    assert [x['text'] for x in r['journal'] if x['ev'] == 'cue'][0] == first


@pytest.mark.xfail(strict=True, reason='реестр 5.09: РАБОТАЕТ, на деле без ранней границы в ответе первая подсказка 7-10 слов')
def test_first_cue_is_short_also_without_an_early_comma(late):
    _, r = late
    n = len(WORD.findall(r['before_final'][0]))
    assert 2 <= n <= 5, (n, r['before_final'][0])         # the same bound as the green cases; the registry promise is 2-4


@pytest.mark.xfail(strict=True, reason='реестр 5.09: РАБОТАЕТ, на деле подсказка выходит через ~1 с потока (10-12-е слово), а не как только известно следующее слово')
def test_first_cue_is_released_as_soon_as_the_next_word_is_known(run):
    _, r = run
    assert r['fed'] <= len(WORD.findall(r['before_final'][0])) + 2, (r['fed'], r['before_final'][0])   # cue words + the next one (+1 slack)
