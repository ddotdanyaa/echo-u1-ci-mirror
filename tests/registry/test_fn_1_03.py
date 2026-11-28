"""Реестр 1.03 «Ухо на длинной речи и под нагрузкой»: ТОЛЬКО В ВЕТКЕ. В единой ветке код L3 слит (ear_shadow.py; ключи ear_window / ear_overflow УДАЛЕНЫ: carry и live единственный путь; в сборке сервера 671d2fe и в живом файле ключей нет.
Стенд: helpers_night_memory.Call (настоящие ControlledMedia, NativeMediaSocket, fast_text, журнал звонка; controller_settings(resolve(LIVE)); подделана лишь текстовая модель по содержанию) и настоящее ухо ear_shadow.for_call(resolve(LIVE)) с EarWorker,
как его строит controlled_host; подделаны детектор речи и распознаватель (слово целое, если все его пакеты в одном потоке, иначе «ск~»). Звук: input_audio_buffer.append по 100 мс, время виртуальное. Снаружи: запросы к модели и ответы, ear_final журнала, подсказки телефону, лог echo-sync.
LIVE: весь живой файл сервера (65 ключей); отклонения: v6_memory и topic_recap = off (стенд Call включает их по умолчанию, на сервере они off). CALL_SETTINGS хоста (preset/ack_match/on_mismatch) ключи 1.03 не затрагивают. Не покрыто: акустическая модель, CPU ноутбука, путь «файл настроек -> хост -> ухо».
"""
import base64, collections, logging, re, threading, time  # noqa: E401
import pytest
import helpers_night_memory as N
from echo_sync import ear_shadow
from echo_sync.settings import resolve
from test_ear_shadow import ScriptedDetector

LIVE = {'preset': 'meaning', 'abbreviations': {}, 'local_ear': 'act', 'ear_early_ms': 0, 'fast_text': 'on', 'text_transport': 'http', 
        'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on', 'instant': 'on', 
        
        'brain_short': 'off', 'pcm_cache_mb': 800, 'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 
        'v5_answer_gate': 'shadow', 'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0, 'max_auto_repeats': 3, 
        'topic_recap': 'off'}
PER = 4                                             # пакетов на слово; граница окна 15 с = 150 пакетов = середина слова 37
PRE = 'вчера мы с женой разбирали антресоль нашли там старые коробки с книгами и посудой потом решили отдать часть вещей соседям и заодно перебрали ящики в гараже а ещё нашли пару лыж и санки которые давно искали весной'.split()
ASK = 'сколько стоит перевозка контейнера до порта Находка'.split()
FILL = 'если учесть что мы возим коробки с книгами и посудой вместе с лыжами и санками из гаража антресоли а ещё ящики соседей которые просили помочь с отправкой весной и ещё мешки с зерном и бочки с краской'.split()
LONG, TAIL = PRE[:37] + ASK, ' '.join(ASK[2:])       # 44 слова = 17,6 с: «сколько» (слово 37) лежит на границе окна (15 с); TAIL — хвост вопроса, по нему модель узнаёт вопрос
LQ, SHORT = ASK[:2] + FILL + ASK[2:], ASK[:2] + FILL[:15] + ASK[2:]      # вопрос с вопросительного слова длиннее окна (44 слова = 17,6 с, граница в «бочки с краской») и он же короче окна
FACT = 'Перевозка контейнера до порта Находка стоит 1830 долларов.'
script = lambda packets: ['onset'] + ['speech'] * (packets - 2) + ['end']      # noqa: E731

def mind(request):      # Текстовая модель по содержанию: о перевозке отвечает, только если вопрос дошёл целым; о гарантии лифта отвечает числом из номера; иначе просит уточнить.
    asked = N.asked(request)
    lift = re.search(r'лифт номер (\d+)', asked)
    return FACT if TAIL in asked else f'Гарантия на лифт номер {lift[1]} — {10 + int(lift[1]) % 7} месяцев. Сервис раз в квартал.' if lift else 'Уточните вопрос.'

class Rec:      # поток читает слово целым, если получил все его пакеты, иначе «ск~» (первые буквы и тильда); gate держит распознаватель (перегруз)
    def __init__(self, words, gate): self.words, self.gate, self.streams, self.busy = words, gate, [], threading.Event()  # noqa: E704
    def start(self, hotwords=None): return self.streams.append([]) or self.streams[-1]  # noqa: E704
    def accept(self, stream, pcm): self.busy.set(), self.gate.wait(10), stream.extend(pcm[at] for at in range(0, len(pcm), 4800))  # noqa: E704
    def peek(self, stream): return ' '.join(self.words[j] if n == PER else self.words[j][:2] + '~' for j, n in sorted(collections.Counter(tag // PER for tag in stream).items()))  # noqa: E704
    finish = peek

@pytest.fixture
def make(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    def build(words, script, stall=False, **keys):
        call = N.Call(tmp_path, mind, **{**LIVE, **keys})
        call.gate, call.i, call.log, call.finals = threading.Event(), 0, caplog, lambda: [r for r in call.journal() if r['ev'] == 'ear_final']
        call.rec = Rec(words, call.gate)
        call.gate.set() if not stall else None
        worker, detector = ear_shadow.EarWorker(lambda: call.rec), ScriptedDetector(script)
        assert worker.wait_ready(5)
        call.w.wire.ear = ear_shadow.for_call(resolve({**LIVE, **keys}), call.c, detector_factory=lambda: detector, worker=worker, report=call.trace.note, clock=call.w.clock.now)
        calls.append(call)
        return call
    yield build
    for call in calls:
        call.gate.set()
        call.close()

def speak(call, count, wait=True):      # Пакеты по 100 мс; телефон шлёт не быстрее хода времени, поэтому распознавателю даётся принять каждый (иначе стенд сам перегрузит ухо). wait=False: пакеты летят, распознаватель стоит.
    seen = lambda: sum(map(len, call.rec.streams))      # noqa: E731
    base = seen()
    for sent in range(1, count + 1):
        call.w.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(bytes([call.i % 251, 0]) * 2400).decode('ascii')})
        call.w.advance(0.1), setattr(call, 'i', call.i + 1)
        deadline = time.monotonic() + 0.3
        while wait and seen() < base + sent and time.monotonic() < deadline:
            time.sleep(0.0005)
        wait = wait and seen() >= base + sent         # ухо отбросило звук (перегруз): дальше не ждём

def finals(call, want, limit=2):      # Тишина, пока ухо не отдало want записей ear_final (не дольше limit с настоящего времени).
    deadline = time.monotonic() + limit
    while len(call.finals()) < want and time.monotonic() < deadline:
        call.pump(0.1, 0.1), time.sleep(0.002)
    call.pump(1.0)
    return call.finals()

def heard_by_model(call, words):      # Речь words без паузы: что спросили у модели и что она ответила.
    speak(call, len(words) * PER)
    finals(call, 2 if len(words) * PER > 150 else 1)
    return [N.asked(r) for r in call.all_requests()], [r['first'] for r in call.journal() if r['ev'] == 'fast_job']

def overload(call):      # Распознаватель встал: 4 с звука при очереди в 3 с; потом его отпускают, и человек говорит дальше (речь «сейчас»).
    speak(call, 1, wait=False)
    assert call.rec.busy.wait(5)
    speak(call, 40, wait=False), call.gate.set()
    while not sum(map(len, call.rec.streams)):
        time.sleep(0.002)
    call.w.advance(0.5)
    speak(call, 30)
    return finals(call, 2, 0.25)

def waiting_portion(call, stall):      # Вопрос о гарантии лифта: подсказка отдана; человек молчит, потом 6 с говорит (ухо перегружено, если stall) и снова молчит 20 с. Возвращает подсказки телефону.
    call.say('Какой срок гарантии на лифт номер 12?')
    for _ in range(30):
        call.pump(0.3) if not call.w.cues else None
    call.pump(2.0)
    speak(call, 60, wait=not stall)
    call.gate.set()
    speak(call, 200, wait=False), call.pump(1.0)
    return call.cues()


@pytest.mark.parametrize('words', [pytest.param(LONG, id='word_on_the_bound'), pytest.param(LQ, id='long_question_word_in_filler'), pytest.param(SHORT, id='control_short_question')])
def test_long_speech_reaches_the_model_whole(make, words):
    asked, answers = heard_by_model(make(words, script(len(words) * PER)), words)
    assert any(TAIL in q for q in asked) and not any('~' in q for q in asked) and FACT in answers, 'вопрос после границы окна дошёл целым и получил ответ'

def test_the_window_bound_tears_no_word_and_the_journal_says_the_speech_goes_on(make):
    """Речь 17,6 с идёт через границу окна в 15 с одним потоком: слово «сколько» целое, в журнале у первого окна more, у второго part=2, ни одного «~»."""
    call = make(LONG, script(len(LONG) * PER))
    heard_by_model(call, LONG)
    first, second = call.finals()[:2]
    assert first.get('more') is True and second.get('part') == 2 and not any('~' in (r.get('text') or '') for r in call.finals())
    assert ' '.join(ASK) in first['text'] + ' ' + second['text'], 'граница окна не режет слово'

def test_overloaded_ear_says_what_it_lost_and_hears_speech_of_now(make):
    records = overload(make(PRE, script(71), stall=True))
    assert sum(r.get('lost_ms') or 0 for r in records) > 0 and any(r.get('cut') == 'overflow' for r in records)
    assert any(PRE[15] in (r.get('text') or '') for r in records), 'речь после разгрузки услышана'

def test_control_an_ear_that_keeps_up_loses_nothing(make):
    """Контроль перегруза: без остановки распознавателя те же слова на месте и потери нет (ни lost_ms, ни cut)."""
    whole = make(PRE, script(71))
    speak(whole, 71)
    first = finals(whole, 1)[0]
    assert PRE[15] in first['text'] and not first.get('lost_ms') and not first.get('cut')

def test_overload_leaves_the_portion_repeat_going(make):
    """Живые значения (drop, input_state on, the ear tempo): перегруз уха не мешает автоповтору подсказки (подсказка и 3 повтора); настройки дошли до контроллера."""
    call = make(PRE, script(60), stall=True)
    cues, said = waiting_portion(call, True), call.log.messages
    assert len(cues) == 5 and all('15 месяцев' in c for c in cues) and any('ear state=overflow' in m for m in said)
    assert any('input_state state=' in m for m in said) and any('reason=ear_tempo' in m for m in said)

def test_overflow_with_input_state_on_keeps_the_portion_repeat(make):
    call = make(PRE, script(60), stall=True)
    cues = waiting_portion(call, True)
    assert any(r.get('cut') == 'overflow' for r in call.finals()) and len(cues) == 5, 'перегруз назван в журнале, автоповтор не остановлен'


import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
