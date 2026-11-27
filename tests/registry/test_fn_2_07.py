"""Реестр 2.07 «Составной вопрос, забытый подпункт». Состояние по реестру: ВЫКЛЮЧЕНО (question_parts=off).
LIVE - весь файл настроек сервера (65 ключей) литералом. Отклонения: HostRig - fast_text=off (без поддельной модели он ходит в сеть; текстовый путь проверяет Call), Call - topic_recap/v6_memory=off
(умолч.; Call включает их сам), question_parts=on только в [on] (там, где спрашиваем, что даст включение). Хост из CALL_SETTINGS не переопределяет preset/ack_match/on_mismatch: к этой функции они не относятся.
Снаружи: HostRig (настоящий controlled_host.serve, два звонка над одной домашней папкой, настройки файлом до рукопожатия, журнал звонка) - кадры session.context.append канала commentary, ушедшие помощнику
при открытии новой связи: единственный выход карты частей (engine.conversation_map -> progress_notes). Call (настоящий контроллер, поддельная модель отвечает по содержанию вопроса) - текстовый путь.
Не покрыто: поведение живой модели после заметки, звук. Недописано в движке: open_parts кладётся в карту, но заметка его не читает (мёртвое поле), поэтому ключ ничего не включает."""
import json
import pytest
import helpers_night_memory as N
import helpers_s6_fault as F
import helpers_s6_state as S
LIVE = {
    'preset': 'meaning', 'portion_sense': 'off', 'abbreviations': {}, 'ack_match': 'stem', 'on_mismatch': 'replay_if_attempt', 'local_ear': 'act', 'ear_early_ms': 0, 'ear_vocab': 'off', 'fast_text': 'on',
    'text_transport': 'http', 'prompt_tempo': 'ear', 'ear_release': 'on', 'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on', 
    'material_pick': 'on', 'warm_start': 'on', 'quick_math': 'on', 'instant': 'on', 'repeat_rule': 'on', 'dictation': 'off', 'dictation_cycle': 'on', 'stumble_place': 'on', 'resume_word': 'on', 'instant_rank': 'on',
    'instant_rank2': 'on', 'two_witnesses': 'on', 'fast_private': 'off', 'stop_in_flight': 'on', 'gate_text': 'off', 
    'bank_rejoin': 'on', 'brain_short': 'off', 'ear_command_early': 'off', 'pcm_cache_mb': 800, 'pcm_record': 'on', 'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 'facts_journal': 'on',
    'v5_answer_gate': 'shadow', 'adopt_missing_words': 1, 'spare_helper': 'on', 'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0, 'open_overlap': 'on', 
    'inline_repeat': False, 'max_auto_repeats': 3, 'record_mode': 'earned', 'local_onset': 'on', 'local_fallback': 'on', 'conversation_ledger': 'memory', 'recall_words': 'on', 'input_state': 'on',
    'lang_turn': 'shadow'}
# (вопрос, ответ модели из трёх порций, открытая часть, закрытая часть): первая порция закрывает первую часть, вторая часть остаётся без ответа
CASES = {
    'amount_time': ('Сколько стоит абонемент в бассейн и когда он заканчивается', 'Абонемент стоит двести рублей. Он заканчивается в июне. Скидка действует всем.', 'когда он заканчивается', 'Сколько стоит'),
    'place_who': ('Где находится склад и кто им заведует', 'Склад находится на окраине города. Заведует им Пётр Сидоров. Телефон указан внизу.', 'кто им заведует', 'Где находится'),
    'why_how': ('Почему закрыт мост и как проехать в объезд', 'Мост закрыт из-за ремонта опор. Проехать можно по северной дороге. Это займёт десять минут.', 'как проехать в объезд', 'Почему закрыт'),
    'about_list': ('Расскажи про ремонт крыши, про окна и про забор', 'Крышу чинят в мае. Окна меняют осенью. Забор красят летом.', 'про окна', 'про ремонт крыши'),
}
xf = lambda why: pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.07: открытая часть составного вопроса никуда не выводится, включение ключа не помогает' + why)      # noqa: E731


def call_twice(tmp_path, monkeypatch, case, **over):
    """Звонок 1 (хост настоящий, настройки файлом): вопрос, ответ из трёх порций, человек повторил первую. Звонок 2 над той же домашней папкой.
    -> (текст заметки помощнику при открытии связи, шапка журнала звонка 1, озвучено в звонке 1)."""
    question, answer = CASES[case][:2]

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            (host.home / 'materials').mkdir(parents=True)
            (host.home / 'materials' / 'echo_settings.json').write_text(json.dumps({**LIVE, 'fast_text': 'off', **over}), encoding='utf-8')
            await host.handshake()
            await host.ask(question, tid='u1')
            await host.answer(answer, tid='a1')
            await host.ask(S.relaxed(host.spoken()[0]), tid='u2')
            await host.advance(1.0)
            spoken = host.spoken()
            [path] = [p for p in (host.home / 'logs' / 'echo_calls').glob('*.jsonl') if not p.name.endswith('.v5tap.jsonl')]
            head = json.loads(path.read_text(encoding='utf-8').splitlines()[0])
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
            frames = [json.loads(p) for k, p in host.bridge.sent if k == 'E']
        assert all(f['type'] == 'session.context.append' and f['channel'] == 'commentary' for f in frames)
        return ''.join(f['content'][0]['text'] for f in frames), head, spoken
    return F.run(main)


@pytest.mark.parametrize('case', CASES)
def test_control_reconnect_note_carries_the_question_what_was_said_and_what_was_not(tmp_path, monkeypatch, case):
    """Контроль (тот же сценарий без проверяемого условия): связь восстановлена, заметка помощнику есть: вопрос, сказанное и несказанное. Живой файл дошёл до хоста (шапка журнала)."""
    question, answer = CASES[case][:2]
    note, head, spoken = call_twice(tmp_path, monkeypatch, case)
    first, second = answer.split('. ')[:2]
    assert (head['record_mode'], head['max_auto_repeats'], head['dictation_cycle']) == ('earned', 3, 'on') and len(spoken) == 2
    assert note.startswith('Служебная заметка суфлёра, не вопрос: связь восстановлена') and f'вопрос «{question}» — сказано «{first}.' in note and f'не сказано «{second}.' in note


@pytest.mark.parametrize('flag, case', [pytest.param('off', 'amount_time', marks=xf(' (живое question_parts=off)')), pytest.param('off', 'about_list', marks=xf(' (ветка «про …, про …» включена всегда)')),
                                         pytest.param('on', 'amount_time', marks=xf('')), pytest.param('on', 'place_who', marks=xf('')), pytest.param('on', 'why_how', marks=xf(''))])
def test_target_reconnect_note_names_the_open_part(tmp_path, monkeypatch, case, flag):
    question, answer, open_part, closed_part = CASES[case]
    note, *_ = call_twice(tmp_path, monkeypatch, case, question_parts=flag)
    rest = note.replace(question, '').lower()      # вопрос процитирован целиком: открытая часть должна быть названа сверх цитаты
    assert open_part.lower() in rest, note
    assert closed_part.lower() not in rest, 'закрытая часть не должна числиться открытой'


@pytest.mark.parametrize('flag', ['off', 'on'])
@pytest.mark.parametrize('case', CASES)
def test_text_route_answers_the_whole_compound_question_in_portions(tmp_path, case, flag):
    """Текстовый путь (fast_text=on, поддельная модель отвечает, только если вопрос пришёл ЦЕЛИКОМ): первая порция про первую часть, после повтора - вторая про вторую; с question_parts on и off одинаково
    (ключ порции не меняет). Живой файл дошёл до контроллера: проверено командой (controller_settings(resolve(...)) в Call), в самом тесте виден через fast_text=on - без него модели не будет вовсе."""
    question, answer = CASES[case][:2]
    first, second = (s + '.' for s in answer.split('. ')[:2])
    call = N.Call(tmp_path, mind=lambda request: answer if N.asked(request).endswith(question) else 'Вопрос пришёл не целиком.', **{**LIVE, 'topic_recap': 'off', 'question_parts': flag})
    try:
        call.say(question)
        call.pump(1.0)
        call.say(S.relaxed(call.cues()[0]))
        call.pump(1.0)
        assert call.cues() == [first, second]
    finally:
        call.close()
