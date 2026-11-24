"""Функция 2.08 «Команды: «слайд пять», «следующий», «вернись», «повтори», «хватит»». Реестр: РАБОТАЕТ НА СЕРВЕРЕ; `ear_command_early` (стоп по раннему тексту уха) ВЫКЛЮЧЕНО.
Стенд: test_h3_tempo.Rig (настоящие ControlledMedia, NativeMediaSocket, ShadowEar; подделаны детектор речи, события облака, поток текстовой модели) на ЖИВОМ профиле: LIVE (весь файл настроек
сервера, 65 ключей, без отступлений) пишется в ECHO_REPLAY_PROFILE, Rig ставит на контроллер то же, что хост. Знать: resolve гасит ear_job, cloud_form, ear_lookup (prepare_wide=off); три ключа
CALL_SETTINGS (preset) хост профилю не отдаёт (строка 2.08 их не называет). Банк слайдов как у хоста (instant.for_home по materials/context.md).
Для стопа по частичному тексту ухо пересобрано ear_shadow.for_call с настоящим EarWorker и распознавателем с peek. Снаружи: подсказки, кадры телефону, задания модели, решения в логе echo-sync."""
import json, logging, re, time      # noqa: E401

import pytest

import helpers_s6_state as S
from echo_sync import ear_shadow, instant
from test_h3_tempo import Rig

LIVE = {'preset': 'meaning', 'portion_sense': 'off', 'abbreviations': {}, 'local_ear': 'act', 'ear_early_ms': 0, 'ear_vocab': 'off', 'fast_text': 'on', 'text_transport': 'http',
        'ear_release': 'on', 'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on', 'material_pick': 'on', 'warm_start': 'on',
        'instant': 'on', 'stumble_place': 'on', 'fast_private':
        'off', 'stop_in_flight': 'on', 'gate_text': 'off', 'bank_rejoin': 'on', 'brain_short': 'off', 
        'pcm_cache_mb': 800, 'pcm_record': 'on', 'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 'facts_journal': 'on', 'v5_answer_gate': 'shadow', 'adopt_missing_words': 1, 'spare_helper':
        'on', 'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0, 'open_overlap': 'on', 'inline_repeat': False, 'max_auto_repeats': 3, 'local_fallback': 'on',
        'conversation_ledger': 'memory', 'recall_words': 'on', 'lang_turn': 'shadow'}
Q, ANSWER = 'Как устроена приёмка товара', 'Сначала склад стоит у дороги. Потом на воротах считают машины. В конце накладные сверяют с описью.'
P1, P2 = 'Сначала склад стоит у дороги.', 'Потом на воротах считают машины.'
SLIDES = {'Слайд три': 'На третьем слайде таблица тарифов.', 'Седьмой слайд': 'Седьмой слайд показывает схему склада.', 'Слайд двенадцать': 'На двенадцатом слайде итоговые цифры.',
          'Слайд Погрузка и приёмка': 'Слайд про погрузку и приёмку: две очереди.'}
BROKEN = pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.08: работает; в единой ветке сломано: «вернись» только от уха (облако финал не прислало) уходит модели как вопрос, план на паузе')

@pytest.fixture
def make(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    rigs = []

    def build(bank=False, **over):
        (tmp_path / 'profile.json').write_text(json.dumps({**LIVE, **over}), encoding='utf-8')
        monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(tmp_path / 'profile.json'))
        rigs.append(Rig(monkeypatch))
        if bank:      # как хост (controlled_host: controller.instant = instant.for_home(profile_settings, home))
            (tmp_path / 'materials').mkdir()
            (tmp_path / 'materials' / 'context.md').write_text(''.join(f'В: {q}\nО: {a}\n\n' for q, a in SLIDES.items()), encoding='utf-8')
            rigs[-1].c.instant = instant.for_home(rigs[-1].settings, tmp_path)
        return rigs[-1]
    yield build
    for rig in rigs:
        assert rig.w.violations == [], rig.w.violations
        rig.close()

def decisions(caplog, mark=0):
    return [f'{m.group(1)}:{m.group(2)}' for r in caplog.records if (m := re.search(r'decision kind=(\w+) reason=(\w+)', r.getMessage()))][mark:]

def tell(rig, tid, text):      # реплика человека, как её присылает облако: начало хода и итог
    rig.w.feed(S.turn_created(tid, 'user', text.split()[0]))
    rig.w.feed(S.turn_done(tid, 'user', text))
    rig.pump(1.0)

def asked(make, caplog, **over):
    rig = make(**over)
    rig.asks('u0', Q, 0, ANSWER)
    rig.pump(0.5)
    assert rig.said() == [P1]
    return rig, len(decisions(caplog))

def hear(rig, text):
    """Ухо Rig пересобрано так же, но с настоящим EarWorker и распознавателем с peek (частичный текст идёт путём звонка). Возвращает класс со счётчиком peek."""
    class Mic:
        peeks, start, accept, finish = 0, staticmethod(lambda hotwords=None: []), staticmethod(lambda stream, pcm: stream.append(pcm)), staticmethod(lambda stream: text)

        def peek(self, stream):
            Mic.peeks += 1
            return text if len(stream) >= 2 else ''
    worker = ear_shadow.EarWorker(Mic)
    assert worker.wait_ready(5)
    rig.ear = rig.w.wire.ear = ear_shadow.for_call(rig.settings, rig.c, detector_factory=lambda: rig.detector, worker=worker, clock=rig.w.clock.now)
    return Mic

def test_the_live_file_reaches_the_controller(make, caplog):
    rig, mark = asked(make, caplog)
    assert {k for k, v in LIVE.items() if rig.settings.get(k) != v} == {'ear_job', 'cloud_form', 'ear_lookup'}
    tell(rig, 'c1', 'ну вот это')
    assert decisions(caplog, mark) == ['silent:unrelated_speech', 'silent:mismatch_policy_silent', 'silent:repeat_gate'], 'input_state=on (repeat_gate); on_mismatch=silent от хоста'

@pytest.mark.parametrize('said,cues,kinds,silent', [
    (['Следующий'], [P1, P2], ['next'], False), (['Дальше пожалуйста'], [P1, P2], ['next'], False), (['Повтори'], [P1, P1], ['repeat'], False), (['Хватит'], [P1], ['stop'], True), (['Подождите, пожалуйста'], [P1], ['stop'], True),
    (['Хватит', 'Вернись'], [P1, P1], ['stop', 'resume'], False), (['Стоп', 'Вернись назад пожалуйста'], [P1, P1], ['stop', 'resume'], False)])
def test_a_command_is_a_rule_not_a_question(make, caplog, said, cues, kinds, silent):
    rig, mark = asked(make, caplog)
    for n, text in enumerate(said):
        tell(rig, f'c{n}', text)
    if silent:
        rig.pump(10)      # после «хватит» подсказка не повторяется по таймеру
    assert rig.said() == cues
    assert [d.split(':')[0] for d in decisions(caplog, mark) if d.split(':')[0] in ('next', 'repeat', 'stop', 'resume')] == kinds
    assert len(rig.fake.runs) == 1, 'команда модели не уходит: ответ дал только первый вопрос'

def test_a_fragment_does_not_reset_the_plan_but_a_real_question_does(make, caplog):
    """U59 «обрывок не сбрасывает план»: после обрывков «следующий» всё ещё даёт вторую порцию; контроль: настоящий вопрос план снимает и уходит модели."""
    rig, mark = asked(make, caplog)
    for n, text in enumerate(['и ещё', 'ну вот это', 'а если']):
        tell(rig, f'f{n}', text)
    assert rig.said() == [P1] and len(rig.fake.runs) == 1 and not any(d.startswith('retire') for d in decisions(caplog, mark))
    tell(rig, 'n', 'Следующий')
    assert rig.said() == [P1, P2]
    tell(rig, 'q', 'Какой срок хранения товара на складе')
    assert 'retire:new_question' in decisions(caplog, mark) and 'срок хранения товара' in rig.fake.run(1).question

@pytest.mark.parametrize('said,hold', [('Подождите, а сколько машин проходит за смену', False), ('Стоп, а какой срок хранения товара', False), ('Подождите', True)])
def test_e42_a_hold_word_at_the_start_of_a_question_stops_nothing_and_the_question_goes_to_the_model(make, caplog, said, hold):      # контроль: само «подождите» стопает
    rig, mark = asked(make, caplog)
    tell(rig, 'q', said)
    assert ('stop:stop_pauses_the_answer' in decisions(caplog, mark)) == hold and len(rig.fake.runs) == (1 if hold else 2)
    assert hold or said.split(', а ')[1] in rig.fake.run(1).question, 'вопрос после слова-команды ушёл модели целиком'

@pytest.mark.parametrize('said,key', [('Слайд три', 'Слайд три'), ('Третий слайд', 'Слайд три'), ('слайд 7', 'Седьмой слайд'), ('Двенадцатый слайд', 'Слайд двенадцать'),
                                      ('слайд погрузка и приёмка', 'Слайд Погрузка и приёмка'), ('Слайд девять', None)])
def test_a_slide_command_gives_the_bank_text_verbatim_within_two_seconds_with_no_model(make, said, key):      # последний случай - контроль: слайда нет в материале, выдуманного текста нет
    rig = make(bank=True)
    rig.w.feed(S.turn_created('c0', 'user', said.split()[0]))
    rig.w.feed(S.turn_done('c0', 'user', said))
    t = rig.w.clock.t
    while not rig.said() and rig.w.clock.t - t < 2.0:      # U59: команда слайда за 2 с
        rig.pump(0.1)
    assert rig.said() == ([SLIDES[key]] if key else []) and (len(rig.fake.runs) == 0 or key is None), 'именно текст этого слайда, без запроса модели (нет в банке: ушло модели, своего текста нет)'

@pytest.mark.parametrize('heard', ['хватит'])
def test_target_a_stop_in_the_ears_text_so_far_cuts_the_cue_while_the_listener_still_speaks(make, caplog, heard):      # ключа нет: стоп по раннему тексту уха - правило слушающего уха
    rig, mark = asked(make, caplog)
    rig.w.wire.synthesize = rig.w._synthesize      # подсказка звучит кадрами по виртуальному времени
    frames, mic = len(rig.w.frames), hear(rig, heard)
    rig.onset()
    for _ in range(300):      # человек говорит, конца речи нет; ждём, пока распознаватель отдаст два peek
        if mic.peeks >= 2:
            break
        rig.packet('speech')
        rig.pump(0.1)
        time.sleep(0.01)
    time.sleep(0.05)
    rig.pump(0.3)
    assert rig.ear.current is not None, 'человек ещё говорит'
    assert any(f[2].get('type') == 'output_audio_buffer.clear' for f in rig.w.frames[frames:]), 'телефону не ушла команда оборвать звук'
    assert 'stop:local_ear_stop' in decisions(caplog, mark), 'стоп не принят до конца фразы'

@pytest.mark.parametrize('seq,kind,cue', [(['дальше'], 'next', [P1, P2]), (['хватит', 'повтори'], 'repeat', [P1, P1]), pytest.param(['хватит', 'вернись'], 'resume', [P1, P1], marks=BROKEN)])
def test_commands_heard_by_the_ear_alone_are_rules_too(make, caplog, seq, kind, cue):
    """Контроль к xfail: «дальше» и «повтори» после «хватит» от одного уха разобраны правилом."""
    rig, mark = asked(make, caplog)
    for text in seq:
        rig.says(text, speech=0.8)      # слышит только ухо, облако финала не прислало
        rig.pump(4.0)
    assert rig.said() == cue and kind in [d.split(':')[0] for d in decisions(caplog, mark)], 'команда разобрана правилом'
    assert len(rig.fake.runs) == 1, 'команда модели не уходит'
