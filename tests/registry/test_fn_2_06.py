"""Реестр 2.06 «Вопросы с числами и номерами». Состояние по реестру: РАБОТАЕТ НА СЕРВЕРЕ — диапазоны number_ranges: ВЫКЛЮЧЕНО.

Живой файл сервера целиком (LIVE, 65 ключей). Отклонения: HOST (настоящий serve, HostRig) = LIVE без fast_text и local_ear (нет поддельной модели и уха, иначе сеть); Rig (настоящий контроллер, ухо act, поддельная модель)
= LIVE + instant_bank_file на свой банк в tmp_path, профиль через ECHO_REPLAY_PROFILE. Живое доходит: шапка call_open (record_mode earned, dictation_cycle on, number_ranges off), банк на Rig открыт лишь живыми fast_text on + local_ear act.
Хост берёт preset/ack_match/on_mismatch из CALL_SETTINGS (meaning/ru_aligned/silent), не из файла; реестр 2.06 их не называет. Реплики выдуманы. Время виртуальное: подача от конца речи, не замер телефона.
"""
import json
from pathlib import Path

import pytest

import helpers_s6_fault as F
from echo_sync import instant
from helpers_spoken_diagnostics import run_host
from test_h1_fast_text import settled
from test_h3_tempo import Rig
from test_h4_ear_first import final, speaks
LIVE = {'preset': 'meaning', 'portion_sense': 'off', 'abbreviations': {}, 'local_ear': 'act', 'ear_early_ms': 0, 'ear_vocab': 'off', 'fast_text': 'on', 'text_transport': 'http',
        'ear_release': 'on', 'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on', 'material_pick': 'on',
        'warm_start': 'on', 'instant': 'on', 'stumble_place': 'on', 
        'fast_private': 'off', 'stop_in_flight': 'on', 'gate_text': 'off', 'bank_rejoin': 'on',
        'brain_short': 'off', 'pcm_cache_mb': 800, 'pcm_record': 'on', 'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 'facts_journal': 'on', 
        'v5_answer_gate': 'shadow', 'adopt_missing_words': 1, 'spare_helper': 'on', 'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0, 'open_overlap': 'on', 'inline_repeat': False,
        'max_auto_repeats': 3, 'local_fallback': 'on', 'conversation_ledger': 'memory', 'recall_words': 'on', 'lang_turn': 'shadow'}
HOST = {**LIVE, 'fast_text': 'off', 'local_ear': 'off'}
BANK = [{'q': q, 'answer': a, 'source': 'выдумано', 'subject': 'выдумано'} for q, a in [
    ('Что сказано в статье 214', 'Статья 214 вводит срок в тридцать дней для ответа на претензию.'), ('Что сказано в статье 241', 'Статья 241 запрещает передавать долю третьим лицам без согласия.'),
    ('Что учитывается на счёте 62', 'Счёт 62 учитывает расчёты с покупателями и заказчиками.'), ('Что учитывается на счёте 26', 'Счёт 26 учитывает общехозяйственные расходы организации.')]]
STATUTE = 'Статья 214 вводит срок в 30 дней для ответа на претензию, и он считается со дня получения.'
ACCOUNT = 'Номер счёта 508 нужно указать в платёжном поручении, иначе платёж вернётся обратно.'
CHAPEL = 'Часовню возвели в XVI веке, и после этого её много раз перестраивали позднее.'
RANGES = [('Собор строили в XVII–XIX веках, и после этого его много раз перестраивали позднее.', 'собор строили в семнадцатом по девятнадцатом веках'), ('Канал рыли в 1861–1869 годах, и работы шли без остановки круглый год.', 'канал рыли в тысяча восемьсот шестьдесят первом по тысяча восемьсот шестьдесят девятом годах')]

def host_call(tmp_path, monkeypatch, caplog, answer, *said):
    """Вопрос, ответ облака, слушатель по очереди повторяет первую порцию. -> (порции телефону после каждой фразы, решения лога, шапка call_open журнала звонка)."""
    caplog.set_level(20, logger='echo-sync')

    async def body(host):
        (Path(host.home) / 'materials').mkdir(parents=True, exist_ok=True)
        (Path(host.home) / 'materials' / 'echo_settings.json').write_text(json.dumps(HOST), encoding='utf-8')
        await host.handshake()
        await host.ask('Когда и что это было?', tid='u1')
        await host.answer(answer, tid='a1')
        await host.advance(1)
        seen = [list(host.spoken())]
        for n, words in enumerate(said, 1):
            host.cloud(F.created(f'r{n}', 'user', words.split()[0]))
            host.cloud(F.done(f'r{n}', 'user', words))
            await host.advance(1)
            seen.append(list(host.spoken()))
        return seen, host.home
    seen, home = run_host(tmp_path, monkeypatch, body, handshake=False)
    decisions = [r.getMessage().split('decision ', 1)[1].split(' revision')[0] for r in caplog.records if ' decision kind=' in r.getMessage()]
    rows = [json.loads(line) for path in (Path(home) / 'logs' / 'echo_calls').glob('*.jsonl') for line in path.read_text(encoding='utf-8').splitlines()]
    return seen, decisions, next(r for r in rows if r.get('ev') == 'call_open')

@pytest.mark.parametrize('answer,right,wrong', [
    (STATUTE, 'статья двести четырнадцать вводит срок в тридцать дней', 'статья двести сорок один вводит срок в тридцать дней'),
    (ACCOUNT, 'номер счёта пятьсот восемь нужно указать в платёжном поручении', 'номер счёта пятьсот шесть нужно указать в платёжном поручении'),
    (CHAPEL, 'часовню возвели в шестнадцатом веке', 'часовню возвели в пятнадцатом веке')], ids=['статья', 'счёт', 'век'])
def test_number_in_digits_is_repeated_in_words_and_a_wrong_number_is_not(tmp_path, monkeypatch, caplog, answer, right, wrong):
    """Число цифрами в порции: чужое число не двигает ответ, верное словами засчитано (ack), подана следующая порция; «счёт» = контроль к xfail «пять ноль восемь», «век» = к диапазонам."""
    seen, decisions, head = host_call(tmp_path, monkeypatch, caplog, answer, wrong, right)
    assert len(seen[0]) == 1 and seen[1] == seen[0] and len(seen[2]) == 2 and seen[2][0] == seen[0][0], seen
    assert decisions[-1].startswith('kind=ack'), decisions

@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.06: работает; в единой ветке сломано: цифры по одной («пять ноль восемь», «два один четыре») не собираются в число (в реестре «четыре два два»)')
@pytest.mark.parametrize('answer,said', [(ACCOUNT, 'номер счёта пять ноль восемь нужно указать в платёжном поручении'), (STATUTE, 'статья два один четыре вводит срок в тридцать дней')], ids=['счёт', 'статья'])
def test_digits_said_one_by_one_are_the_number(tmp_path, monkeypatch, caplog, answer, said):
    """Номер, продиктованный по цифрам, засчитан как число (контроль: тот же номер словами засчитан в тесте выше)."""
    seen, decisions, _ = host_call(tmp_path, monkeypatch, caplog, answer, said)
    assert len(seen[1]) == 2, (seen, decisions)
@pytest.mark.parametrize('answer,said', RANGES, ids=['век', 'года'])
def test_a_range_said_as_two_ends_advances_the_answer(tmp_path, monkeypatch, caplog, answer, said):
    """Диапазон (правило владельца, без ключа): диапазон, сказанный двумя концами, засчитан, подана следующая порция (контроль: одиночный век в тесте чисел выше)."""
    seen, decisions, _ = host_call(tmp_path, monkeypatch, caplog, answer, said)
    assert len(seen[1]) == 2, (seen, decisions)

@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Настоящий контроллер на стенде h3 с живым профилем (ECHO_REPLAY_PROFILE); банк читает настоящий instant.from_settings, его ставит хост в build_instant."""
    (tmp_path / 'bank.json').write_text(json.dumps(BANK, ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'live.json').write_text(json.dumps({**LIVE, 'instant_bank_file': str(tmp_path / 'bank.json')}), encoding='utf-8')
    monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(tmp_path / 'live.json'))
    stand = Rig(monkeypatch)
    stand.c.instant = instant.from_settings(stand.settings)
    yield stand
    assert stand.w.violations == []
    stand.close()

def utter(rig, ear, cloud, n=0):
    """Ухо слышит «ear», облако записывает «cloud»; модель, если её спросили, отвечает по содержанию вопроса. -> конец речи."""
    ended = speaks(rig, ear, turn=f'u{n}', announced=0.4, speech=2.0)
    final(rig, f'u{n}', cloud, after=1.0)
    for run in rig.fake.runs[n:]:
        if not run.cancelled.is_set():
            run.say('Модель отвечает на вопрос «%s».' % run.question.rsplit('Сейчас прозвучало: ', 1)[-1])
            run.finish()
            settled(rig.fast)
    rig.pump(2.0)
    return ended

@pytest.mark.parametrize('ear,cloud,want', [
    ('что сказано в статье двести четырнадцать', 'Что сказано в статье 214?', 'Статья 214 вводит срок'), ('двести четырнадцать статья что сказано', 'Двести четырнадцать статья, что сказано?', 'Статья 214 вводит срок'),
    ('что учитывается на счёте шестьдесят два', 'Что учитывается на счёте 62?', 'Счёт 62 учитывает'),
    ('счёт двадцать шесть', 'Счёт 26.', 'Счёт 26 —')], ids=['прямой', 'обратный', 'счёт62', 'счёт26_план'])
def test_a_bank_question_with_a_number_is_answered_by_that_number_fast(rig, ear, cloud, want):
    """Вопрос с номером (прямой и обратный порядок слов; «счёт 26 —» отвечает встроенный план счетов продукта, остальное мой банк): подан ответ по этому номеру, не по соседнему, модель не спрошена, подача не позже 0,4 с от конца речи; облако слышит то же (контроль к расхождению)."""
    ended = utter(rig, ear, cloud)
    assert len(rig.said()) == 1 and rig.said()[0].startswith(want) and rig.fake.runs == [], (rig.said(), len(rig.fake.runs))
    assert rig.cues()[0].t - ended <= 0.4, rig.cues()[0].t - ended

@pytest.mark.parametrize('ear,cloud', [('что сказано в статье двести двадцать', 'Что сказано в статье 220?'), ('что учитывается на счёте сто двадцать пять', 'Что учитывается на счёте 125?')], ids=['статья220', 'счёт125'])
def test_a_number_the_bank_does_not_hold_goes_to_the_model_not_to_a_neighbour(rig, ear, cloud):
    """Номера нет в банке: соседний номер не отвечен, вопрос ушёл модели с этим номером, подан её ответ (контроль: номера из банка отвечены в тесте выше)."""
    utter(rig, ear, cloud)
    said = ' '.join(rig.said())
    assert rig.fake.runs and 'Модель отвечает' in said and not any(s in said for s in ('Статья 214', 'Статья 241', 'Счёт 62', 'Счёт 26')), rig.said()

@pytest.mark.parametrize('ear,cloud,last', [
    ('что сказано в статье двести четырнадцать', 'Что сказано в статье 241?', 'Статья 241 запрещает'), ('что учитывается на счёте шестьдесят два', 'Что учитывается на счёте 26?', 'Счёт 26')], ids=['статья', 'счёт'])
def test_ear_and_cloud_hear_two_numbers_the_cloud_is_trusted_then_asked_again(rig, ear, cloud, last):
    """Расхождение в номере: в первый раз верят облаку (последняя подача по его номеру), во второй раз переспрос «Не расслышал число»."""
    utter(rig, ear, cloud, 0)
    assert rig.said()[-1].startswith(last) and not any('Не расслышал' in s for s in rig.said()), rig.said()
    utter(rig, ear, cloud, 1)
    assert any(s.startswith('Не расслышал число') for s in rig.said()), rig.said()

def test_agreeing_witnesses_give_one_bare_calculation(rig):
    """Контроль к xfail ниже: ухо и облако слышат «12 умножить на 5» — расчёт «Шестьдесят.» без оговорки."""
    utter(rig, 'сколько будет двенадцать умножить на пять', 'Сколько будет 12 умножить на 5?')
    assert rig.said() == ['Шестьдесят.'], rig.said()

@pytest.mark.parametrize('ear,cloud,bad', [('сколько будет двенадцать умножить на пять', 'Сколько будет 13 умножить на 5?', 'Шестьдесят пять'),      # U43c (one-answers 832d077): the figure names its operands, «Тринадцать на пять — шестьдесят пять.»
    pytest.param('что сказано в статье двести четырнадцать', 'Что сказано в статье 241?', 'Статья 214', marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.06: ответ банка по числу уха звучит до исправления облаком'))], ids=['расчёт', 'статья'])
def test_a_disagreeing_number_is_never_said_as_if_sure(rig, ear, cloud, bad):
    """Ухо и облако слышат два числа: ни расчёт без оговорки («Шестьдесят пять.», нужно «Если 13: …»), ни ответ по числу одного уха не звучат (контроль: тот же сценарий с одним числом в тестах выше)."""
    utter(rig, ear, cloud)
    assert rig.said() and not any(s.startswith(bad) for s in rig.said()), rig.said()
