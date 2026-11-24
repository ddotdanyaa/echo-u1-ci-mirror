"""Реестр 2.12 «Мусор речи не хоронит следующий вопрос»: по реестру РАБОТАЕТ НА СЕРВЕРЕ. Стенд tools/replay/quantity.py поверх tests/test_h3_tempo.Rig (настоящие ControlledMedia, NativeMediaSocket,
ShadowEar, FastText; подделаны детектор, распознаватель уха, облако, поток модели; виртуальное время). Настройки: ВЕСЬ живой файл сервера (LIVE, 65 ключей, без отклонений) идёт стенду файлом через
ECHO_REPLAY_PROFILE, Rig строит контроллер как controlled_host (controller_settings(resolve(LIVE))). Ключи самого стенда (Q.LIVE, CANDIDATE) равны живым. Оговорки: resolve выключает ear_job,
cloud_form, ear_lookup (в живом файле on) при prepare_wide=off, как на сервере; ack_match и on_mismatch хост контроллеру не отдаёт (CALL_SETTINGS) — функции они не касаются.
Подделка модели отвечает по содержанию заявки: на вопрос из таблицы — его ответом, на речь — «—» (иначе tail_guard=on даёт отказ на речь и ложную подсказку).
Снаружи видно: опубликованные подсказки и когда. Зелёное: вопрос из базы после K кусков речи (только ухо / с финалами облака) получает тот же ответ базы, что без неё, быстро и без ложных подсказок.
Остаток (xfail): вопрос НЕ из базы после речи без финалов облака, если модель отклоняет сборную заявку «Распознано: речь вопрос»: ответа нет. Контроли: без речи; с речью, если модель отвечает."""
import json
import random

import pytest

from tools.replay import quantity as Q
from tools.replay import repeat_scenes as R

LIVE = {
        'preset': 'meaning', 'portion_sense': 'off', 'abbreviations': {}, 'local_ear': 'act',
        'ear_early_ms': 0, 'ear_vocab': 'off', 'fast_text': 'on', 'text_transport': 'http', 'ear_release': 'on',
        'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on', 'material_pick': 'on',
        'warm_start': 'on', 'instant': 'on', 'stumble_place': 'on',
        'fast_private': 'off', 'stop_in_flight': 'on',
        'gate_text': 'off', 'bank_rejoin': 'on',
        'brain_short': 'off', 'pcm_cache_mb': 800, 'pcm_record': 'on', 'pcm_record_calls': 200, 'pcm_record_mb': 8192,
        'pcm_record_call_mb': 1200, 'facts_journal': 'on', 'v5_answer_gate': 'shadow', 'adopt_missing_words': 1, 'spare_helper': 'on',
        'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0, 'open_overlap': 'on', 'inline_repeat': False,
        'max_auto_repeats': 3, 'local_fallback': 'on', 'conversation_ledger': 'memory', 'recall_words': 'on',
        'lang_turn': 'shadow'}
TALK = ['слушай я кажется забыл зонт в машине', 'тихо там кто-то поёт на лестнице', 'а в среду у нас вроде совещание перенесли', 'нет красный проводок вот этот',
        'смотри какая смешная собака у соседей', 'ладно потом доскажу про дачу', 'погоди чайник уже кипит', 'три коробки это много или нет']
BANK = {'Что такое инфляция?': 'Устойчивый рост общего уровня цен.', 'Что такое денежная масса?': 'Все наличные и безналичные деньги в обращении, агрегат М2.',
        'Когда была Куликовская битва?': 'В 1380 году.', 'контрольная функция финансов': 'Контроль за распределением и использованием денег по их цели.'}      # вопрос -> первая порция базы стенда
OWN = 'Ответ модели, не из базы.'      # так модель ответила бы на вопрос из базы: подсказка с этим текстом = путь базы сломан
KM = ('Сколько километров от Земли до Луны', 'Около трёхсот восьмидесяти четырёх тысяч километров.')      # не из базы: отвечает модель
BOOK = ('Кто написал роман Война и мир', 'Лев Толстой написал роман Война и мир.')


@pytest.fixture(autouse=True)
def live(monkeypatch, tmp_path):
    (tmp_path / 'live.json').write_text(json.dumps(LIVE), encoding='utf-8')
    monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(tmp_path / 'live.json'))      # стенд берёт файл профиля как хост: настройки доходят и до контроллера, и до модели


@pytest.fixture
def rig():
    made = []

    def make():
        made.append(Q.rig_of())
        assert made[-1].settings['fast_text'] == 'on', 'живой файл дошёл стенду'
        return made[-1]
    yield make
    for each in made:
        each.close()
        each._mp.undo()      # откат подмен самого стенда, как в tools/replay/quantity.py


def model(c, seen, answers, decline_compound):
    """Подделка модели: на новую заявку с вопросом из ``answers`` — его ответ, на остальное (речь) — «—». ``decline_compound``: сборную «Распознано: речь вопрос / речь» отклоняет. -> число заявок."""
    for n in range(seen, len(c.fake.runs)):
        asked = c.fake.runs[n].question
        reply = next((a for ask, a in answers.items() if ask.lower() in asked.lower()), '—')
        c.job_says(n, '—' if decline_compound and asked.startswith('Распознано') else reply)
        c.job_ends(n)
    return len(c.fake.runs)


def ask_after(c, k, ask, answers, *, finals=False, decline_compound=False, wait=10.0):
    """K кусков чужой речи (ухо; с финалами облака, если finals; пауза 0,3-1 с), затем вопрос ухом. -> (ложные подсказки на речь, [(текст, секунд после конца вопроса)])."""
    rng, seen = random.Random(k + 5), 0
    for _ in range(k):
        (R.utter if finals else Q.ear_only)(c, rng.choice(TALK))
        for _ in range(rng.choice((3, 5, 10))):
            c.pump(0.1)
            seen = model(c, seen, answers, decline_compound)
    false_cues, mark = len(c.cues()), len(c.cues())
    ended = Q.ear_only(c, ask)
    for _ in range(int(wait * 10)):
        c.pump(0.1)
        seen = model(c, seen, answers, decline_compound)
    return false_cues, [(x.text, round(x.t - ended, 2)) for x in c.cues()[mark:]]


@pytest.mark.parametrize('ask, k', [('Что такое инфляция?', 0), ('Что такое инфляция?', 5), ('Что такое денежная масса?', 10), ('Когда была Куликовская битва?', 10),
                                    ('контрольная функция финансов', 10)])
def test_bank_question_after_unrecognised_talk_gets_the_same_cue(rig, k, ask):
    """Облако не записало ни слова: K кусков речи слышит одно ухо, потом вопрос из базы — тот же ответ базы (не модели), быстро, ни одной подсказки на речь."""
    false_cues, cues = ask_after(rig(), k, ask, {ask: OWN})
    assert false_cues == 0 and cues and cues[0][0] == BANK[ask] and cues[0][1] < 1.0, cues


def test_bank_question_after_a_long_talk(rig):
    false_cues, cues = ask_after(rig(), 40, 'Что такое денежная масса?', {'Что такое денежная масса?': OWN})
    assert false_cues == 0 and cues[0][0] == BANK['Что такое денежная масса?'] and cues[0][1] < 1.0, cues


def test_bank_question_after_talk_with_cloud_finals(rig):
    false_cues, cues = ask_after(rig(), 6, 'Что такое инфляция?', {'Что такое инфляция?': OWN}, finals=True)
    assert false_cues == 0 and cues[0][0] == BANK['Что такое инфляция?'] and cues[0][1] < 1.0, cues


@pytest.mark.parametrize('k, decline', [(0, False), (0, True), (3, False)])
def test_a_question_the_model_answers_gets_its_cue(rig, k, decline):
    """Контроль для xfail: без речи (в том числе при той же подделке, что отклоняет сборные заявки) и с речью, если модель отвечает и на сборную заявку, — ответ модели опубликован."""
    _, cues = ask_after(rig(), k, KM[0], dict([KM]), decline_compound=decline)
    assert cues and cues[0][0] == KM[1], cues


@pytest.mark.parametrize('ask', [KM, BOOK])
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.12: работает; в единой ветке сломано для вопроса не из базы: после 3 кусков речи без финалов облака '
                   'ответ модели на чистую заявку (0,35 с) не публикуется, через 4 с его заменяет ответ на сборную «Распознано: речь вопрос»; если модель её отклоняет — подсказки нет')
def test_a_question_the_model_answers_gets_its_cue_after_talk_if_the_compound_is_declined(rig, ask):
    _, cues = ask_after(rig(), 3, ask[0], dict([ask]), decline_compound=True)
    assert cues and cues[0][0] == ask[1], cues
