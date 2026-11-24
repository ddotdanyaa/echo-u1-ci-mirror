"""g37/c24-e: the register of the backlog N01-N200 and the rehearsals Р001-Р100: class + proof + six separate stages of each row. python -m tools.backlog_register [--md PATH] [--json PATH] [--run-tests PATH] [--reconcile PATH].
Class = what the cloud snapshot can say, and no more. DONE: code and a test in this snapshot, NOT a working and accepted product (c24-e: the old «141/200» summary read it so). FLAG (done behind a flag that is off, waits for a laptop measurement),
WIRE (module and test exist, the call into controlled_media is the coordinator's: patch in the report), OPEN (closable, not closed yet: the row says why), OWNER (only the owner can: the phone, the ear, a decision, a file or a person),
AGENT (an agent on the laptop can do it itself: Windows, the real model, the network, the disk; `rest` names what stays for the owner), LATER (the backlog itself says «позже»).
Stages (same register, no second one): implemented, verified_shared (the row's tests pass on the shared base: tools.backlog_register --run-tests writes the table), enabled (in the owner's server profile), deployed, on_device, target_met.
Values: yes / part / no / na (not a product code: a report or a tool) / unk (the cloud has no data; this is NOT «no»). A row is `accepted` only when all six are yes. N02 with the 0,5 s target is not closed by the file instant.py: its target_met is unk until the laptop measures it.
Every DONE/FLAG/WIRE row names files; tests/test_g37_backlog.py checks that they exist and that every id of the source file is classified once. Nothing here is a measurement of a call."""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTX = ROOT / 'cloud_context'
SOURCES = (CTX / 'ЗАДАЧИ_НОЧЬ_05-06_11.md',)
DONE, FLAG, WIRE, OWNER, AGENT, LATER, OPEN = 'DONE', 'FLAG', 'WIRE', 'OWNER', 'AGENT', 'LATER', 'OPEN'
R = 'cloud_context/reports/'
T = 'tests/'
E = 'echo_sync/'

# (ids, class, evidence files, what)
ROWS = [
    ('N01', DONE, ['cloud_context/analysis/12_LATENCY_CHAIN.md'], 'цепочка по классам вопроса разложена в мс; g38 уточняет ожидания первой подсказки'),
    ('N02 N06', DONE, [E + 'instant.py', E + 'pcm_cache.py', T + 'test_w5_instant.py', T + 'test_w13_pcm_cache.py'], 'банк мгновенного ответа и записанный заранее звук первой порции'),
    ('N03', FLAG, [E + 'law_base.py', E + 'material_pick.py', T + 'test_w4_law.py', T + 'test_material_pick_gold.py'], 'законы и материал локально; секунда с поиском мерится только на ноутбуке'),
    ('N04 N168 N19 N94 N95 N96', OWNER, [], 'нужны настоящая модель и ноутбук (замер 02:28, сравнение с GPT-Live, оценка BRAIN на 544 строках)'),
    ('N05', DONE, [E + 'instant.py', T + 'test_w5_instant_wiring.py'], 'совпадение с банком на промежуточном тексте уха'),
    ('N07', FLAG, [E + 'ear_shadow.py', T + 'test_ear_early.py'], 'ранний текст уха на тишине 135 мс за флагом; нужен замер'),
    ('N08', DONE, [E + 'two_witnesses.py', T + 'test_w10_two_witnesses.py'], 'согласие двух свидетелей, E86'),
    ('N09 N26', FLAG, [T + 'test_h7.py'], 'задание на устойчивом тексте и вопрос после вступления за флагом H7'),
    ('N10', DONE, [T + 'test_t1_transport.py', R + 'w10-integ.md'], 'постоянное соединение и прогрев, −508 мс замерено в t1'),
    ('N11', DONE, [E + 'ws_transport.py', T + 'test_t2_ws.py'], 'WebSocket: транспорт и тесты; опыт T2 на сети ноутбука отдельно'),
    ('N12 N122', DONE, [E + 'reserve_text.py', T + 'test_roads_policy.py', T + 'test_roads_refusal.py'], 'второй запрос против хвоста и лимит по квоте (хвост и его двойник ушли в Roads: one-answers)'),
    ('N13', DONE, [E + 'question_lead.py', T + 'test_w5_lead.py', T + 'test_w5_lead_wiring.py'], 'начало ответа из слов вопроса'),
    ('N14 N15', DONE, [E + 'ear_prefetch.py', E + 'stable_text.py', T + 'test_native_prefetch.py', T + 'test_w8_donors.py'], 'поиск и банк через ухо без финала; подготовлено устойчивым текстом'),
    ('N16', DONE, [E + 'helper_pool.py', T + 'test_w6_spare_helper.py'], 'запасной процесс звука'),
    ('N17 N18 N106', DONE, [R + 'w8-net.md', T + 'test_w8_net.py'], 'разбор открытия, open_overlap, очередь микрофона; сеть телефона мерится на месте'),
    ('N20', FLAG, [E + 'quick_math.py', T + 'test_q1_quick.py'], 'арифметика кодом за флагом'),
    ('N21', DONE, [E + 'generator.py'], 'c22: долгий кэш устойчивых ответов в `PrivateCodexGenerator` удалён при слиянии answer (plugin-answer-cache): повторное использование ответа живёт только в cm-local-base (prepared_answers)'),
    ('N22 N23 N24 N25 N27 N28 N32', DONE, [R + 'w8-admission.md', T + 'test_r05_admission.py', T + 'test_w1f_foreign_reply.py'], 'когда подсказывать и когда молчать: шлюз допуска'),
    ('N29 N30 N31', DONE, [T + 'test_w3_scenes.py', T + 'test_w3_replays.py'], 'чужое «повторите», «повторить» от группы, поток вопросов: сцены стенда'),
    ('N33 N34', DONE, [E + 'near_voice.py', T + 'test_w5_near.py', T + 'test_f4_noise.py'], 'шум перемены и чужая речь без пауз'),
    ('N35 N36 N48 N49 N141', DONE, [T + 'test_w8_silence.py', R + 'w8-silence.md'], 'тишина минутами, болтовня, «дальше», стоп, возврат к плану'),
    ('N37 N38 N139 N140', DONE, [T + 'test_w8_repeat_guard.py', T + 'test_repeat_cases.py', R + 'w8-repeat.md'], 'повтор владельца и собственное эхо'),
    ('N39', DONE, [E + 'ru_numbers.py', T + 'test_ru_numbers.py', T + 'test_resume_word.py'], 'число словами и цифрами в повторе'),
    ('N40 N41 N42 N137', DONE, [E + 'ru_alignment.py', T + 'test_resume_word.py', T + 'test_w5_stumble_real.py'], 'запинка с того же слова, заполнители, оборванное слово'),
    ('N43', DONE, [T + 'test_repeat_cases.py'], 'хвост, пропуск, перестановка (F1–F11)'),
    ('N44 N45 N143 N156', DONE, [E + 'flow_ahead.py', E + 'pace.py', T + 'test_w5_flow.py', T + 'test_w5_pace.py'], 'порция сразу после слова, длина под человека, пауза между порциями'),
    ('N46', DONE, [E + 'portioner.py', T + 'test_f1_meaning_portions.py'], 'смысловые порции'),
    ('N47 N155', OWNER, [E + 'pcm_trim.py', T + 'test_e76_end_intonation.py'], 'конец ответа интонацией: код и тесты есть, слышимость проверяет ноутбук'),
    ('N50 N154 N167', OWNER, [], 'тумблер микрофона, наушник и смена сети телефона: только телефон'),
    ('N51 N117 N118', DONE, [E + 'brain_short.py', T + 'test_r21_first_portion.py', T + 'test_w9_brain.py'], 'первый ответ короткий, суть первой'),
    ('N52', DONE, [E + 'speech_text.py', E + 'ru_numbers.py', T + 'test_speech_text.py'], 'числа вслух верно, проверка обратным разбором'),
    ('N53 N174', DONE, [E + 'privacy_gate.py', T + 'test_w10_safe.py', R + 'w9-safe.md'], 'личное не уходит в поиск'),
    ('N54', DONE, [E + 'material_pick.py', T + 'test_material_pick_gold.py'], 'найден нужный кусок материала'),
    ('N55 N160 N158 N159', DONE, [E + 'arch_liveness.py', T + 'test_w9_arch.py', T + 'test_w9_liveness.py'], 'честное «не нашёл», работа без облака, кодекса, поиска'),
    ('N56', OWNER, [E + 'brain_short.py'], 'текст BRAIN внедрён; оценка на настоящей модели'),
    ('N57', DONE, [E + 'question_part.py', T + 'test_question_part.py'], 'вопрос вместе с условиями'),
    ('N58 N67', OWNER, [E + 'law_base.py', E + 'kb_nk.py', T + 'test_w4_law.py'], 'движок законов готов; полный свод собирается на ноутбуке из скачанных кодексов'),
    ('N59', DONE, [E + 'kb_accounts.py', T + 'test_w9_fast_no.py'], 'план счетов'),
    ('N60 N197', FLAG, [E + 'materials.py', T + 'test_w5_material.py'], 'материал всех предметов сразу: модуль, флаг material_pick'),
    ('N61 N62 N63 N65 N66 N68 N70 N71 N199', OWNER, [], 'файлы и загрузки на диске владельца или ноутбука, кодексы из сети'),
    ('N64', DONE, ['cloud_context/material/ВСЕ_ПРЕДМЕТЫ.md'], 'какие темы уже прошли: в пакете материала'),
    ('N69 N198', DONE, ['tools/ear_vocab.py', T + 'test_g24_ear_vocab.py'], 'словарь уха из материалов автоматически'),
    ('N72 N74 N75 N76 N77 N78 N79 N180', DONE, [R + 'w8-donors.md', T + 'test_w8_donors.py'], 'доноры и идеи: отчёт с цифрами и отказами'),
    ('N73', DONE, [E + 'stable_text.py', T + 'test_w8_donors.py'], 'LocalAgreement'),
    ('N80 N81', DONE, ['tools/backlog_register.py', 'tests/test_g37_backlog.py'], 'каждая строка N01–N200 сверена с файлами; T01–T15 разобраны в w3-integ'),
    ('N82 N83 N84 N85', OPEN, [R + 'c24-e-reconcile.md', T + 'test_g37_backlog.py'], 'c24-e: сверка по файлам cloud_context сделана (R01–R24 по пяти столбцам, 54/53 блокера, очередь E/W; `python -m tools.backlog_register --reconcile`); остаток: узлы графа и код ветки на ноутбуке'),
    ('N86 N87 N88 N89 N90 N91 N92 N97', DONE, [R + 'w10-integ.md', R + 'w13-final.md'], 'сборки w3/w6/w10/w13; повторные прогоны на новых головах — g37 (раздел «стенд»)'),
    ('N93', DONE, [T + 'test_w3_scenes.py'], 'сцены n1/n2 текстом'),
    ('N98 N99 N100 N101 N102 N176 N178', DONE, ['tools/profile_backup.py', T + 'test_g24_profile_backup.py'], 'резервная копия и откат одной командой; выкладку на сервер делает ноутбук'),
    ('N103 N104 N105 N111 N112', DONE, [R + 'w9-loop.md', T + 'test_w9_loop.py'], 'отсечка, H3 без финала, такт событием, SQLite, второй Silero'),
    ('N107 N108 N109', DONE, [E + 'warm.py', T + 'test_w9_warm.py', T + 'test_boot_order.py'], 'прогрев банков, уха, голоса'),
    ('N115', FLAG, [E + 'gate_text.py', 'echo_sync/controlled_media.py', T + 'test_gate_text.py', T + 'test_gate_text_wiring.py'], 'c22: шлюз текста подключён (`ControlledMedia._gate_talk`, флаг `gate_text`, выключен); «30% запросов» не мерили, нужен замер ноутбука'),
    ('N110 N116 N120', WIRE, [E + 'gate_text.py', T + 'test_gate_text.py'], 'синтез заранее у ворот, лид с числами со вторым свидетелем, материал по вопросу: в `controlled_media.py` подключения нет (c22 искал `GATE_TALK`/gate_decide — это только шлюз N115)'),
    ('N113 N114', DONE, [T + 'test_hold_sweep.py', T + 'test_open_tail_pairs.py', R + 'w9-hold.md'], 'окно удержания на 2000 сидов, незавершённая реплика'),
    ('N119', OWNER, [], 'влияние длины инструкции мерится настоящей моделью'),
    ('N121', DONE, [T + 'test_t1_transport.py'], 'пинг держит соединение'),
    ('N123 N124 N125', LATER, [], 'отказ: search_race.py не был подключён ни к чему и удалён вместе с тестом (хозяин search-race, перепись); гонку поиска и задания держит Roads'),
    ('N126 N192', DONE, ['tools/call_report.py', T + 'test_w9_call_report.py'], 'отчёт шагов из журнала после звонка'),
    ('N127 N128 N129 N144', DONE, [E + 'own_voice.py', E + 'near_voice.py', T + 'test_w9_ear_voice.py', T + 'test_w2_own_voice.py'], 'близкая речь, буфер реплики, динамик как чужая речь, предел времени'),
    ('N130 N138 N142 N146 N147 N148', DONE, [T + 'test_w9_rehearsal.py', 'tools/rehearsal/plan.py'], 'репетиции стенда Р043, Р052, Р053, Р065, Р059, Р068'),
    ('N131 N132', DONE, [T + 'test_r05_admission.py', T + 'test_audit_g10.py'], 'вопрос не распознан, повторил; уже ответили сами'),
    ('N133', FLAG, [E + 'followup.py', E + 'engine.py', T + 'test_w9_map.py', T + 'test_c22_wiring.py'], 'c22: части составного вопроса без предлога в `conversation_map` (`open_parts`), флаг `question_parts` (off); голосом «Осталось: …» не подключено — форму решает владелец'),
    ('N134', DONE, [E + 'lang_hint.py', T + 'test_w9_fast_no.py'], 'вопрос на английском: «not/no/never» защищены как «не»'),
    ('N135', FLAG, [E + 'personal_volatile.py', 'echo_sync/controlled_media.py', T + 'test_w9_fast_no.py', T + 'test_c22_wiring.py'], 'c22: честный ответ на личный изменчивый вопрос как локальный ответ (`_reference` → `_personal_reply`), флаг `personal_volatile` (off); «0,3 с» — оценка, звонком не мерили; вариант plain/hedged (D-1) за владельцем'),
    ('N136', FLAG, [E + 'abbrev_state.py', 'echo_sync/controlled_media.py', T + 'test_w9_map.py', T + 'test_c22_wiring.py'], 'c22: сокращение расшифровывается один раз за звонок (`ControlledMedia._abbreviations`), всегда включено, ключа нет; по просьбе «расшифруй» снова; на слух не проверено'),
    ('N145', OWNER, [], 'запасные кнопки: проверка в протоколе на телефоне'),
    ('N149 N150', DONE, [T + 'test_w9_long.py'], 'час и три часа: ничего не растёт'),
    ('N151 N152 N153', OWNER, [E + 'speech_text.py'], 'голос и произношение: текст до синтеза готов, сравнение голосов — ноутбук'),
    ('N157 N161 N162 N163 N164 N165 N166 N169', DONE, [R + 'w9-arch.md', T + 'test_w9_arch.py', T + 'test_chaos.py'], 'карта путей и таблица отказов; сторож сервера описан в отчёте'),
    ('N170', DONE, [T + 'test_w6_spare_helper.py', T + 'test_w9_rehearsal.py'], 'столкновения флагов: все флаги кандидата вместе в стенде'),
    ('N171 N172 N173 N175 N179', OWNER, [R + 'w9-safe.md'], 'проверка живого адреса, решения D-4 и D-14, слияние: разбор готов, решает владелец'),
    ('N177 N186', DONE, [E + 'build_info.py', T + 'test_w13_fingerprint.py'], 'отпечаток кода и номер сборки'),
    ('N181 N182 N183 N184', DONE, [T + 'test_w9_gate.py', 'tools/gate/inventory.py'], 'опись xfail/skip, обёртка, замок слота, целостность реестра'),
    ('N185', DONE, ['tools/mutate_check.py', T + 'test_w3_skeptic.py'], 'мутации ключевых условий'),
    ('N187', OWNER, [], 'новый контрольный корпус нужен от владельца'),
    ('N188 N189', DONE, [T + 'test_a1_replay.py', R + 'a4-stand.md'], 'проверяющий стенда и паспорт прогона'),
    ('N190', DONE, [T + 'test_w9_rehearsal.py', 'tools/rehearsal/score.py'], 'табло репетиций'),
    ('N191 N196', DONE, ['tools/bank_refresh.py', T + 'test_w9_bank_refresh.py'], 'обновление банка одной командой (режим игры удалён: в движке его никто не вызывал)'),
    ('N193 N194 N195', OWNER, [], 'лист настройки телефона, плагин 0.127.1 (D-2), записка решений — владелец'),
    ('N200', LATER, [], 'кнопки и дизартрия для детей с ДЦП: в самом списке «позже», E26'),
]
# rehearsals: every Р is one line of the stand's plan; what the text stand cannot model it says by ``approx=``
REHEARSAL_OWNER = ('Р033 Р091 Р092 Р093 Р094 Р095 Р096 Р097 Р098 Р099 Р100 Р154').split()


PROFILE = {'stop_in_flight': 'on', 'stumble_place': 'on', 'local_fallback': 'on', 'voice_gain': 2.0, 'dictation': 'off'}
PROFILE_NOTE = 'профиль сервера со слов владельца 07.11 (repeat_rule, stop_in_flight, stumble_place, local_fallback вкл; voice_gain 2; dictation выкл, но работает голосом «диктуй медленно»); какой коммит выложен, облако не знает'
# stage overrides: id -> {stage: (value, basis)}
PROFILE_ROWS = {'stumble_place': 'N40 N41 N42 N137', 'stop_in_flight': 'N49', 'local_fallback': 'N158 N159 N160'}
STAGES = ('implemented', 'verified_shared', 'enabled', 'deployed', 'on_device', 'target_met')
YES, PART, NO, NA, UNK = 'yes', 'part', 'no', 'na', 'unk'
VALUES = (YES, PART, NO, NA, UNK)
OVR = {}
for _flag, _ids in PROFILE_ROWS.items():
    for _id in _ids.split():
        OVR.setdefault(_id, {})['enabled'] = (PART if _flag == 'local_fallback' else YES, 'профиль: %s=on (%s)' % (_flag, PROFILE_NOTE[:42]))
OVR['N154'] = {'enabled': (PART, 'voice_gain 2 в профиле; слышимость на наушнике не проверена')}
for _id in ('N45', 'N156'):
    OVR.setdefault(_id, {})['enabled'] = (PART, 'dictation выкл, включается голосом; остальной темп без флага')
OVR['N02'] = {'enabled': (UNK, 'instant=on в кандидате стенда; в профиле владельца не назван'), 'target_met': (UNK, 'цель 0,5 с до уха не мерили на ноутбуке; наличие instant.py её не закрывает')}
OVR['N06'] = {'enabled': (UNK, 'pcm_cache: в профиле владельца не назван')}
OVR['N10'] = {'target_met': (PART, '−508 мс замерено в t1 (отчёт); общую цель это не закрывает')}
OVR['N115'] = {'target_met': (UNK, '«30% запросов» не мерили')}
OVR['N135'] = {'target_met': (UNK, '«0,3 с» — оценка')}
OVR['N07'] = {'target_met': (UNK, 'нужен замер ноутбука')}
# the 37 OWNER ids split: the owner alone (the phone, the ear, a decision, a person) vs the agent on the laptop (Windows, model, network, disk); `rest` is what stays for the other side
SPLIT = {
    'N04': (AGENT, 'замер 02:28 на настоящей модели', 'владелец: слышит, принимает цель'),
    'N19': (AGENT, 'сравнение с GPT-Live: модель и сеть ноутбука', ''),
    'N94': (AGENT, 'сцены со звуком и настоящей моделью: Windows SAPI + модель', ''),
    'N95': (AGENT, 'пара с c14 чередованием на модели', ''),
    'N96': (AGENT, 'оценка BRAIN на 544 строках: модель', ''),
    'N168': (AGENT, 'замер GPT-Live как первой подсказки: модель и сеть', ''),
    'N119': (AGENT, 'длина инструкции мерится настоящей моделью', ''),
    'N56': (AGENT, 'оценка BRAIN на настоящей модели', ''),
    'N47': (AGENT, 'конец ответа: хвост волны и RMS мерит агент на Windows SAPI', 'владелец: слышимость интонации на ухо'),
    'N155': (AGENT, 'конец ответа: хвост волны и RMS мерит агент на Windows SAPI', 'владелец: слышимость интонации на ухо'),
    'N58': (AGENT, 'свод законов собирается из скачанных кодексов: сеть и диск ноутбука', ''),
    'N67': (AGENT, 'база законов собирается на ноутбуке', ''),
    'N66': (AGENT, 'докачать кодексы: сеть ноутбука', ''),
    'N199': (AGENT, 'обновление кодексов: сеть ноутбука', ''),
    'N61': (AGENT, 'ОП.09 загружен: проверка текстом на стенде и поиск по материалу', 'владелец: звонком'),
    'N62': (AGENT, 'поиск «Учебник 3» блок 3 по диску ноутбука', ''),
    'N63': (AGENT, 'поиск сообщений и первых пар по диску ноутбука', ''),
    'N65': (AGENT, 'банки ответов по 4 предметам: сборка на ноутбуке (tools/build_instant_bank.py)', 'владелец: принимает тексты'),
    'N68': (AGENT, 'поиск файла презентации по диску ноутбука', ''),
    'N70': (AGENT, 'текст трёх сканов: распознавание на ноутбуке', ''),
    'N151': (AGENT, 'темп, паузы, числа: рендер Windows SAPI и разбор волны', 'владелец: выбор на слух'),
    'N152': (AGENT, 'словарь произношения терминов: рендер и сверка на Windows', 'владелец: слушает спорные'),
    'N153': (AGENT, 'сравнение Irina и Piper: рендер и метрики на ноутбуке', 'владелец: выбор на слух'),
    'N171': (AGENT, 'проверка открытых адресов и входа живого сервера: сеть', 'владелец: решает, что закрыть'),
    'N172': (AGENT, 'поиск секретов в логах и облаке: скан файлов и сети', ''),
    'N179': (AGENT, 'проверка кода облака перед слиянием: чтение и прогон, при слиянии', ''),
    'N195': (AGENT, 'записка решений D-1…D-18: агент пишет', 'владелец: решает'),
    'N50': (OWNER, 'тумблер микрофона на телефоне', 'агент: лист проверки и разбор журнала после'),
    'N154': (OWNER, 'слышимость на наушнике владельца', 'агент: сверка voice_gain по журналу'),
    'N167': (OWNER, 'телефон сменил сеть: рукой на телефоне', 'агент: обрыв сокета в стенде (tools/replay/chaos)'),
    'N71': (OWNER, 'протокол игры с другом: человек и телефон', 'агент: готовит сценарий'),
    'N145': (OWNER, 'запасные кнопки: нажатия на телефоне', 'агент: лист'),
    'N173': (OWNER, 'решение D-4 о репликах в журнале', 'агент: вариант и патч'),
    'N175': (OWNER, 'решение D-14 о текстах в истории облака', 'агент: вариант'),
    'N187': (OWNER, 'новый контрольный корпус даёт владелец', ''),
    'N193': (OWNER, 'настройка телефона по листу: руки владельца', 'агент: пишет лист'),
    'N194': (OWNER, 'плагин 0.127.1 после приёмки, решение D-2', ''),
}
AGENT_LOCAL = (E, 'tools/', T)


def expand(ids):
    return [x for x in ids.split()]


def load_source_ids():
    found = []
    for path in SOURCES:
        text = path.read_text(encoding='utf-8')
        found += re.findall(r'(?m)^\| (N\d{2,3}) \|', text)           # tables
        found += re.findall(r'(?m)^(N\d{3}) ', text)                  # lines of part 2
    return sorted(set(found), key=lambda x: int(x[1:]))


def load_tests(path=None):
    """file -> bool from the table that --run-tests wrote (cloud_context/reports/c24-e-register-tests.json); {} when there is none."""
    path = Path(path) if path else CTX / 'reports' / 'c24-e-register-tests.json'
    if not path.exists():
        return {}
    return {k: v['passed'] for k, v in json.loads(path.read_text(encoding='utf-8')).get('files', {}).items()}


def stages(rid, cls, files, tests):
    """The six stages of one row. Defaults come from the class and the files; OVR carries the facts that are known better."""
    engine = any(f.startswith(E) for f in files)
    test_files = [f for f in files if f.startswith(T)]
    st = {k: [UNK, ''] for k in STAGES}
    st['implemented'] = [{DONE: YES, FLAG: YES, WIRE: PART, OPEN: PART, LATER: NO}.get(cls, YES if files else UNK), '']
    if cls in (OWNER, AGENT) and not files:
        st['implemented'] = [NO, 'нет файлов']
    if cls == WIRE:
        st['implemented'][1] = 'модуль есть, вызова из controlled_media нет'
    if test_files and tests:
        res = [tests.get(f) for f in test_files]
        st['verified_shared'] = [YES if all(r is True for r in res) else NO if any(r is False for r in res) else UNK, 'pytest на c24-base: %d из %d файлов' % (sum(1 for r in res if r), len(res))]
    elif test_files:
        st['verified_shared'] = [UNK, 'таблицы прогона нет']
    else:
        st['verified_shared'] = [NO if cls in (DONE, FLAG, WIRE) else UNK, 'теста нет: отчёт или инструмент' if files else '']
    if cls == FLAG:
        st['enabled'] = [NO, 'флаг выключен']
    elif cls == WIRE:
        st['enabled'] = [NO, 'не подключено']
    elif cls in (DONE, FLAG) and not engine:
        for k in ('enabled', 'deployed', 'on_device', 'target_met'):
            st[k] = [NA, 'инструмент или отчёт']
    for k, v in OVR.get(rid, {}).items():
        st[k] = list(v)
    return {k: {'v': v[0], 'basis': v[1]} for k, v in st.items()}


def accepted(row):
    return all(row['stages'][k]['v'] == YES for k in STAGES)


def register(tests=None):
    tests = load_tests() if tests is None else tests
    rows, seen = [], {}
    for ids, cls, files, what in ROWS:
        for one in expand(ids):
            if one in seen:
                raise ValueError('twice: ' + one)
            seen[one] = 1
            c, w, rest = cls, what, ''
            if one in SPLIT:
                c, w, rest = SPLIT[one]
            row = {'id': one, 'class': c, 'files': files, 'what': w, 'rest': rest}
            row['stages'] = stages(one, c, files, tests)
            row['accepted'] = accepted(row)
            rows.append(row)
    for one in SPLIT:
        assert one in seen, one
    rows.sort(key=lambda r: int(r['id'][1:]))
    return rows


def rehearsal_rows():
    from tools.rehearsal import plan
    names = sorted(plan.PLAN) if isinstance(plan.PLAN, dict) else [p[0] for p in plan.PLAN]
    return names


def run_tests(out, jobs=3, timeout=1500, only=None):
    """pytest per test file named by the register, on the checked-out base: the stage verified_shared. Cloud only: no network, no model."""
    import subprocess, concurrent.futures as cf, time
    files = sorted({f for r in register({}) for f in r['files'] if f.startswith(T)})
    old = json.loads(Path(out).read_text(encoding='utf-8')).get('files', {}) if only and Path(out).exists() else {}
    files = [f for f in files if not only or f in only]
    sys.stdout.write('%d test files\n' % len(files))

    def one(f):
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider', f], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
            tail = (p.stdout.strip().splitlines() or [''])[-1]
            return f, {'passed': None if p.returncode == 5 else p.returncode == 0, 'rc': p.returncode, 'tail': tail, 'sec': round(time.time() - t0, 1)}
        except subprocess.TimeoutExpired:
            return f, {'passed': False, 'rc': -1, 'tail': 'timeout %ds' % timeout, 'sec': timeout}
    with cf.ThreadPoolExecutor(jobs) as ex:
        res = {**old, **dict(ex.map(one, files))}
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    Path(out).write_text(json.dumps({'head': head, 'note': 'cloud run, not a laptop; a file passes when pytest -x exits 0', 'files': res}, ensure_ascii=False, indent=1), encoding='utf-8')
    bad = [k for k, v in res.items() if v['passed'] is False]
    sys.stdout.write('passed %d of %d; failed: %s; nothing ran (skipped): %s\n' % (sum(1 for v in res.values() if v['passed']), len(res), bad, [k for k, v in res.items() if v['passed'] is None]))
    return res


def render(rows):
    count = {}
    for r in rows:
        count[r['class']] = count.get(r['class'], 0) + 1
    sc = {k: {} for k in STAGES}
    for r in rows:
        for k in STAGES:
            v = r['stages'][k]['v']
            sc[k][v] = sc[k].get(v, 0) + 1
    out = ['# Реестр N01–N200 (g37, c24-e)', '', 'Всего: %d. ' % len(rows) + ', '.join('%s %d' % kv for kv in sorted(count.items())), '',
           '**DONE = код и тест в снимке, не работающий и принятый продукт.** Принято целиком (все шесть признаков «да»): %d из %d.' % (sum(1 for r in rows if r['accepted']), len(rows)), '',
           '| признак | да | частично | нет | не продукт | нет данных |', '|---|---|---|---|---|---|']
    for k in STAGES:
        out.append('| %s | %s |' % (k, ' | '.join(str(sc[k].get(v, 0)) for v in (YES, PART, NO, NA, UNK))))
    out += ['', 'Профиль: ' + PROFILE_NOTE + '.', '', '| № | класс | что | реализ. | общая | вкл. | выложено | устройство | цель | доказательство | остаётся другой стороне |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        out.append('| %s | %s | %s | %s | %s | %s |' % (r['id'], r['class'], r['what'], ' | '.join(r['stages'][k]['v'] for k in STAGES), ', '.join('`%s`' % f for f in r['files']) or '—', r['rest'] or ''))
    return '\n'.join(out) + '\n'


BACK = CTX / 'BACKLOG_ECHO.md'
WORD = {'да': YES, 'частично': PART, 'нет': NO, 'н/п': NA}
RU = {YES: 'да', PART: 'частично', NO: 'нет', NA: 'н/п', UNK: '?', 'text': 'текст'}


def _cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _refs(text, known):
    """E/W ids in a cell, ranges E34–E38 expanded over the ids that exist."""
    out = []
    for m in re.finditer(r'\b([EW])(\d+)(?:\.(\d+))?(?:–[EW]?(\d+))?', text):
        k, a, sub, b = m.groups()
        one = '%s%s%s' % (k, a, '.' + sub if sub else '')
        if b and not sub:
            out += [x for x in known if re.fullmatch(k + r'(\d+)', x) and int(a) <= int(x[1:]) <= int(b)]
        else:
            out.append(one)
    return out


def _trace(ids):
    """id -> (files of code/tests/tools that name it, reports that name it): a mention, not a proof."""
    code = [p for d in ('echo_sync', 'tests', 'tools') for p in (ROOT / d).rglob('*.py') if p.name not in ('backlog_register.py', 'test_g37_backlog.py')]
    rep = [p for p in (CTX / 'reports').glob('*.md') if not p.name.startswith('c24-e')] + [p for p in (CTX / 'wave2').glob('*.md')]      # not its own output: the table must not change when it is written
    texts = {p: p.read_text(encoding='utf-8', errors='replace') for p in code + rep}
    out = {}
    for i in ids:
        rx = re.compile(r'(?<![\w.])' + re.escape(i) + r'(?![\w]|\.\d)')
        out[i] = (sum(1 for p in code if rx.search(texts[p])), sum(1 for p in rep if rx.search(texts[p])))
    return out


def reconcile():
    """N82-N85 by the files of cloud_context: R01-R24 by five columns, the blocker list against the rows, the queue by sections. A fact of the paper register, not of the code on the branches."""
    lines = BACK.read_text(encoding='utf-8').split('\n')
    sect, rows, rrows = '', {}, []
    for ln in lines:
        if ln.startswith('#'):
            sect = ln.lstrip('# ').split(' ')[0]
            continue
        m = re.match(r'\| ([EW]\d+(?:\.\d+)?|R\d\d) \|', ln)
        if not m:
            continue
        c = _cells(ln)
        if c[0].startswith('R'):
            rrows.append(c)
        else:
            rows.setdefault(c[0], []).append((sect, c))
    known = sorted(rows, key=lambda x: (x[0], [int(y) for y in x[1:].split('.')]))
    # R01-R24
    rr = []
    for c in rrows:
        st = [WORD.get(re.split(r'[\s:,;.]', x)[0].lower(), 'text') for x in c[3:8]]
        refs = _refs(c[3], known)
        rr.append({'r': c[0], 'meaning': c[1], 'refs': refs, 'dangling': sorted(set(r for r in refs if r not in rows)), 'stages': dict(zip(('implemented', 'verified', 'integrated', 'deployed', 'device'), st)), 'next': c[8] if len(c) > 8 else ''})
    # blockers
    text = '\n'.join(lines)
    listed = re.search(r'\*\*Блокеры ближайшего разговора \((\d+)\):\*\* ([^\n]*?)\. Сценарий', text)
    claim_list, blockers = int(listed.group(1)), _refs(listed.group(2), known)
    hist = [(t, [x for x in _refs(ids, known)], int(n)) for t, ids, n in re.findall(r'\*\*Добавлено (\d\d\.\d\d \d\d:\d\d)\.\*\* Новые ID: ([^\n]*?)\(\d+\)\. [^\n]*?\(блокеров (\d+)', text)]      # the paper register's own history: the count of blockers after each addition
    claim_note = [(t, n, sorted(set(ids) & set(_refs(listed.group(2), known)))) for t, ids, n in hist]
    cls_rows = [i for i in known if any(re.match(r'блокер', c[4]) for s, c in rows[i] if len(c) == 9)]
    tr = _trace(blockers)
    bl = []
    for b in blockers:
        sect_c = next(((s, c) for s, c in rows.get(b, []) if len(c) == 9), None) or next(iter(rows.get(b, [])), None)
        state = sect_c[1][4] if sect_c and len(sect_c[1]) >= 5 else ''
        low = state.lower()
        bl.append({'id': b, 'row': bool(sect_c), 'state': state[:140], 'code_files': tr[b][0], 'report_files': tr[b][1], 'unproven': bool(re.search(r'не доказан|не проверен|не мерен|не измерен|нет:|нет,|сервером не|на телефоне не', low)), 'on_branch': bool(re.search(r'на ветке|integ|сделан|влит|в master|да\b', low))})
    # queue and closed
    queue = {}
    for i, lst in rows.items():
        for s, c in lst:
            queue.setdefault(s, set()).add(i)
    return {'r': rr, 'blockers': bl, 'claim_list': claim_list, 'claim_note': claim_note, 'blocker_class_rows': cls_rows, 'known': len(known), 'by_section': {k: len(v) for k, v in sorted(queue.items())}, 'rows_E': len([k for k in known if k[0] == 'E']), 'rows_W': len([k for k in known if k[0] == 'W'])}


def render_reconcile(rc):
    out = ['# Сверка N82–N85 по файлам cloud_context (c24-e)', '',
           'Источник: `cloud_context/BACKLOG_ECHO.md` (бумажный реестр, состояние на 22:53 05.11) и сами файлы репозитория (`echo_sync/`, `tests/`, `tools/`, `cloud_context/reports/`). Это сверка бумаги с файлами снимка: что в реестре названо и есть ли след в коде. Строки кода на ветках ноутбука и узлы графа здесь не видны.', '',
           '## N82. R01–R24', '', '| R | реализовано | проверено | интегрировано | выложено | на устройстве | висячие ссылки |', '|---|---|---|---|---|---|---|']
    for r in rc['r']:
        s = r['stages']
        out.append('| %s | %s | %s | %s | %s | %s | %s |' % (r['r'], RU[s['implemented']], RU[s['verified']], RU[s['integrated']], RU[s['deployed']], RU[s['device']], ', '.join(r['dangling']) or '—'))
    cnt = {}
    for r in rc['r']:
        for k, v in r['stages'].items():
            cnt.setdefault(k, {})
            cnt[k][v] = cnt[k].get(v, 0) + 1
    out += ['', 'Счёт по столбцам (да/частично/нет/н-п/текст): ' + '; '.join('%s: %s' % (k, ', '.join('%s %d' % (RU[a], b) for a, b in sorted(v.items()))) for k, v in cnt.items()) + '.', '',
            '«текст» — в клетке не слово «да/нет/частично», а перечень коммитов или условий: читается глазами, в счёт не идёт.', '']
    bl = rc['blockers']
    out += ['## N83. Блокеры ближайшего разговора', '',
            'Число блокеров в самом реестре росло по записям «Добавлено»: %s. В задании «53 блокера» — состояние 21:45; список раздела 3.4 («%d») содержит %d id, то есть расхождения нет: 54-й добавлен записью 22:30. Блокеры из последней записи: %s. Сверяю по списку 3.4.' % (', '.join('%s → %d' % (t, n) for t, n, _ in rc['claim_note']), rc['claim_list'], len(bl), ', '.join(rc['claim_note'][-1][2]) or '—'), '',
            'Строк с классом «блокер» в столбце «Состояние» очереди: %d (из них не в списке 3.4: %s; в списке без такой строки: %s).' % (len(rc['blocker_class_rows']), ', '.join(sorted(set(rc['blocker_class_rows']) - {b['id'] for b in bl})) or '—', ', '.join(sorted({b['id'] for b in bl} - set(rc['blocker_class_rows']))) or '—'), '',
            'Всего блокеров %d; со строкой в очереди %d; названы в коде/тестах снимка %d; только в отчётах %d; нигде %d; в состоянии сказано «не доказан/не проверен/нет» %d; сказано «на ветке/влит/сделан» %d.' % (len(bl), sum(b['row'] for b in bl), sum(1 for b in bl if b['code_files']), sum(1 for b in bl if not b['code_files'] and b['report_files']), sum(1 for b in bl if not b['code_files'] and not b['report_files']), sum(b['unproven'] for b in bl), sum(b['on_branch'] for b in bl)), '',
            '| id | файлов кода/тестов | отчётов | «не доказан» | «на ветке» | состояние в реестре |', '|---|---|---|---|---|---|']
    for b in bl:
        out.append('| %s | %d | %d | %s | %s | %s |' % (b['id'], b['code_files'], b['report_files'], 'да' if b['unproven'] else '—', 'да' if b['on_branch'] else '—', b['state'].replace('|', '/')))
    out += ['', 'Упоминание id в файле — след, не доказательство: его читает человек или ноутбук с графом. Ни один блокер здесь не объявляется закрытым.', '',
            '## N84–N85. Остальные E и W, очередь', '', 'Строк E: %d, W: %d (уникальных id в таблицах реестра %d). Строк по разделам:' % (rc['rows_E'], rc['rows_W'], rc['known']), '']
    out += ['- %s: %d' % kv for kv in rc['by_section'].items()]
    return '\n'.join(out) + '\n'


# ---- I11 (U180, U182, U131, U69, W21, W02): requirement -> ID -> commit -> test -> SHA, and the owner's words -> ID ----
CHAIN_CLOSED = ('сделано', 'выполнено', 'закрыто', 'заменено', 'дубль', 'отклонено', 'отложено')
ROW_ID = re.compile(r'^\|\s*([A-ZА-Я]{1,2}\d+(?:[.-]\d+)*)\s*\|')
OWNER_HEAD = re.compile(r'^## ⟦владелец⟧ (\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):\d\d')
QUOTE_TIME = re.compile(r'\[(\d{1,2})\.(\d{2})\s+(\d{1,2}):(\d{2})')
OWNER_WORDS_CANDIDATES = (ROOT / 'OWNER_WORDS.md', ROOT.parent / 'U1' / '05_WORK' / 'OWNER_WORDS.md', Path('C:/УСТРОЙСТВО 1/U1/05_WORK/OWNER_WORDS.md'))


def chain_backlog(path):
    """{id: {'line', 'closed', 'priority', 'quotes': {'dd.mm hh:mm'}}} from the rows `| ID | ...` of BACKLOG_ECHO.md. First row of an ID is its main row; later rows (stubs of other tables) only add quotes.
    closed = a cell after the second one starts with a closing word (the count_open.py rule): a heuristic, not a verdict."""
    rows = {}
    for n, line in enumerate(Path(path).read_text(encoding='utf-8', errors='replace').splitlines(), 1):
        m = ROW_ID.match(line)
        if not m:
            continue
        cells = _cells(line)
        quotes = {'%02d.%s %02d:%s' % (int(d), mo, int(h), mi) for d, mo, h, mi in QUOTE_TIME.findall(line)}
        row = rows.get(m.group(1))
        if row is None:
            closed = any(c.lower().lstrip('*_ ').startswith(CHAIN_CLOSED) for c in cells[2:])
            prio = next((c for c in cells[2:6] if re.fullmatch(r'P[0-3]', c)), '')
            rows[m.group(1)] = {'line': n, 'closed': closed, 'priority': prio, 'quotes': quotes}
        else:
            row['quotes'] |= quotes
    return rows


def chain_owner_words(path):
    """[{'at': 'dd.mm hh:mm', 'len': chars, 'ids': set}] for every message of the owner's words file (a header `## ⟦владелец⟧ date time`)."""
    from tools import id_query
    msgs, cur, body = [], None, []

    def flush():
        if cur is not None:
            text = '\n'.join(body)
            cur['len'], cur['ids'] = len(text.strip()), set(id_query.ids_in(text))
            msgs.append(cur)
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        h = OWNER_HEAD.match(line)
        if h:
            flush()
            cur, body = {'at': '%s.%s %s:%s' % (h.group(3), h.group(2), h.group(4), h.group(5))}, []
        elif cur is not None:
            body.append(line)
    flush()
    return msgs


def chain(root=None, backlog=None, owner_words=None, only=None):
    """The chain per ID. Stages: row (the requirement has a row), words (an owner's message names it, or the row quotes a message minute that exists), commit (a commit of the log closes it by the subject prefix `<ID>: `),
    test (a file of tests/ mentions it: a mention, not a pass; a pass is only a cloud run), sha. `broken` = the first stage that is missing. words = None when the words file is not found: unknown, not «no»."""
    from tools import id_query
    root = Path(root or ROOT)
    rows = chain_backlog(backlog or root / 'BACKLOG_ECHO.md')
    ow_path = Path(owner_words) if owner_words else next((p for p in OWNER_WORDS_CANDIDATES if p.exists()), None)
    msgs = chain_owner_words(ow_path) if ow_path and Path(ow_path).exists() else None
    ids = sorted(rows) if only is None else list(only)
    idx = id_query.index(root, set(ids))
    log = id_query.commits(root)
    by_commit, by_mention = {}, {}
    for c in log:
        for i in c['closes']:
            by_commit.setdefault(i, []).append(c['sha'][:10])
        for i in c['mentions']:
            by_mention.setdefault(i, []).append(c['sha'][:10])
    words_of, loose = {}, 0
    if msgs is not None:
        for m in msgs:
            linked = {i for i in m['ids'] if i in rows} | {i for i, r in rows.items() if m['at'] in r['quotes']}
            for i in linked:
                words_of.setdefault(i, []).append(m['at'])
            if not linked and m['len'] >= 40:
                loose += 1
    res = []
    for i in ids:
        r = rows.get(i)
        tests = sorted(idx.get(i, {}).get('tests', []))
        cm = by_commit.get(i, [])
        words = None if msgs is None else sorted(set(words_of.get(i, [])))
        st = {'row': r is not None, 'words': None if words is None else bool(words), 'commit': bool(cm), 'test': bool(tests)}
        broken = next((k for k in ('row', 'words', 'commit', 'test') if st[k] is False), None)
        res.append({'id': i, 'row_line': r['line'] if r else None, 'closed': bool(r and r['closed']), 'priority': r['priority'] if r else '', 'stages': st, 'broken': broken,
                    'words': words or [], 'commits': cm, 'mentions': [s for s in by_mention.get(i, []) if s not in cm], 'tests': tests,
                    'closed_without_proof': bool(r and r['closed'] and not (cm and tests))})
    return {'head': next(iter(log), {}).get('sha', ''), 'ids': res, 'owner_words': None if msgs is None else {'messages': len(msgs), 'long_without_id': loose}, 'owner_words_path': str(ow_path) if ow_path else None}


def render_chain(ch, show=None):
    ids = ch['ids']
    rows = [r for r in ids if r['row_line'] is not None]
    lines = ['# Цепочка требование → ID → коммит → тест → SHA (U180, I11)', '',
             'Голова: %s. Звено «тест» = файл `tests/` называет ID (упоминание, не проход: проход даёт только облачный прогон). Закрытость строки — по эвристике `count_open.py` [предположительно].' % (ch['head'][:10] or 'нет git'), '']
    brk = {}
    for r in rows:
        brk[r['broken'] or 'цепочка цела'] = brk.get(r['broken'] or 'цепочка цела', 0) + 1
    lines.append('ID со строкой в бэклоге: %d; закрыто по строке: %d; закрыто без коммита и теста: %d.' % (len(rows), sum(r['closed'] for r in rows), sum(r['closed_without_proof'] for r in rows)))
    lines.append('Где обрывается цепочка (первое отсутствующее звено): ' + ', '.join('%s %d' % kv for kv in sorted(brk.items())) + '.')
    ow = ch['owner_words']
    lines.append('Слова владельца: %s.' % ('файл не найден: связь слов с ID неизвестна (не «нет»)' if ow is None else '%d сообщений, из них длиннее 40 знаков и без единого ID %d (ID нет ни в тексте, ни по времени цитаты бэклога)' % (ow['messages'], ow['long_without_id'])))
    lines += ['', '| ID | пр. | закрыт | слова | коммит | тест | обрыв | SHA |', '|---|---|---|---|---|---|---|---|']
    pick = [r for r in ids if (show is None or r['id'] in show)] if show else [r for r in rows if r['closed_without_proof']]
    yn = {True: 'да', False: 'нет', None: 'н/д'}
    for r in pick:
        st = r['stages']
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (r['id'], r['priority'] or '-', yn[r['closed']], yn[st['words']] + (' %d' % len(r['words']) if r['words'] else ''), yn[st['commit']],
                                                                  yn[st['test']] + (' %d' % len(r['tests']) if r['tests'] else ''), r['broken'] or '-', ','.join(r['commits'][:3]) or '-'))
    lines.append('')
    lines.append('Показаны: %s.' % ('заданные ID' if show else 'закрытые строки без коммита или теста; полный список — `--chain-json`'))
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--md')
    ap.add_argument('--json')
    ap.add_argument('--run-tests', metavar='PATH')
    ap.add_argument('--reconcile', metavar='PATH')
    ap.add_argument('--only', help='with --run-tests: only these test files, k,k; the rest of the table is kept')
    ap.add_argument('--chain', nargs='?', const='-', metavar='PATH', help='I11/U180: requirement -> ID -> commit -> test -> SHA and the owner words -> ID; the table to PATH (- = stdout)')
    ap.add_argument('--chain-json', metavar='PATH', help='the whole chain, every ID, as json')
    ap.add_argument('--ids', help='with --chain: only these IDs, k,k')
    ap.add_argument('--backlog', help='with --chain: path of BACKLOG_ECHO.md (default: the one of the checkout)')
    ap.add_argument('--owner-words', help='with --chain: path of OWNER_WORDS.md (default: the first one found)')
    a = ap.parse_args(argv)
    if a.chain or a.chain_json:
        only = [x for x in re.split(r'[,\s]+', a.ids) if x] if a.ids else None
        ch = chain(backlog=a.backlog, owner_words=a.owner_words, only=only)
        if a.chain_json:
            Path(a.chain_json).write_text(json.dumps(ch, ensure_ascii=False, indent=1), encoding='utf-8', newline=chr(10))
        if a.chain:
            text = render_chain(ch, show=set(only) if only else None)
            (sys.stdout.reconfigure(encoding='utf-8'), sys.stdout.write(text)) if a.chain == '-' else Path(a.chain).write_text(text, encoding='utf-8', newline=chr(10))
        return
    if a.run_tests:
        run_tests(a.run_tests, only=a.only.split(',') if a.only else None)
    if a.reconcile:
        Path(a.reconcile).write_text(render_reconcile(reconcile()), encoding='utf-8')
    rows = register()
    if a.md:
        Path(a.md).write_text(render(rows), encoding='utf-8')
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    if not (a.md or a.json or a.run_tests or a.reconcile):
        sys.stdout.write(render(rows))


if __name__ == '__main__':
    main()
