# brain_eval_n2: карта покрытия (класс -> строки -> что проверяет -> что НЕ доказано)

Файл: `corpus/brain_eval_n2.json`, собран `build_brain_eval_n2.py` из `brain_eval_n2_d1..d3.py` (задача r05-admission, 5 ноября). Запуск: `exp_brain_eval_n2.py`. Варианты правок BRAIN: `corpus/brain_variants_n2.json`, предложения: `corpus/brain_eval_n2_proposals.md`.

**Это набор, а не результат.** Модель не вызывалась ни разу: ни одно число про поведение BRAIN здесь не измерено. Метки написаны по смыслу и по стабильным фактам, а не по ответам продукта.

Всего строк 544: по-русски 536, на другом языке 8; с прежними репликами 434; сомнительных (допустимо любое действие, в зачёт не идут) 24; пар 17.

## Классы и выборки

| Класс | Слово владельца | dev | holdout | молчать | ответить | метка | сомнит. |
|---|---|---|---|---|---|---|---|
| `chat` (CH) | болтовня | 49 | 14 | 63 | 0 | 0 | 0 |
| `remark` (RM) | замечание | 42 | 16 | 58 | 0 | 0 | 2 |
| `question_other` (QO) | вопрос другому человеку | 42 | 15 | 57 | 0 | 0 | 4 |
| `rhetorical` (RH) | риторический вопрос | 34 | 14 | 48 | 0 | 0 | 2 |
| `question_to_speaker` (QS) | вопрос к говорящему | 81 | 25 | 30 | 76 | 0 | 1 |
| `long_preamble` (LP) | вопрос после длинного вступления | 24 | 10 | 10 | 24 | 0 | 1 |
| `request` (RQ) | просьба | 28 | 11 | 25 | 14 | 0 | 2 |
| `dispute` (DS) | спор | 40 | 14 | 26 | 28 | 0 | 3 |
| `command` (CM) | команда | 38 | 11 | 23 | 0 | 26 | 7 |
| `unclear` (UN) | неразборчивое | 26 | 10 | 34 | 2 | 0 | 2 |

## Что именно проверяет каждый класс

- **болтовня** (`chat`): far_after_answer (8), monologue (8), topic_word (5), after_answer (3), announcement (2), greeting (2), phone_greeting (2), weather (2), advert (1), break (1), child (1), coffee (1), commute (1), english_chat (1), english_tv (1), equipment (1), food (1), home_tech (1), memory (1), mic_check (1), museum (1), news (1), night (1), number_talk (1), phone_close (1), proverb (1), repair (1), retry_to_colleague (1), school (1), sport (1), station (1), sunset (1), teasing (1), thanks (1), traffic (1), tv_comment (1), tv_finance (1), tv_weather (1), waiting (1)
- **замечание** (`remark`): about_prompter (8), about_speaker (6), about_material (5), about_room (5), about_answer_of_another (4), about_question (4), ear_style (4), filler_comment (4), agreement (3), doubt_bare (3), doubt_word_remark (3), about_time (2), far_after_answer (2), narration (2), english_remark (1), slide_title (1), tv_comment (1)
- **вопрос другому человеку** (`question_other`): logistics (7), status (6), ear_style (4), family (4), listener (4), remote (4), after_answer (3), doubt_to_other (3), friend (3), topic_to_other (3), far_after_answer (2), knowledge_to_colleague (2), student_to_neighbour (2), definition_to_other (1), doubt_to_colleague (1), doubt_to_friend (1), family_math (1), gossip_reaction (1), knowledge_to_other (1), phone_other (1), when_to_colleague (1), why_to_colleague (1), why_to_friend (1)
- **риторический вопрос** (`rhetorical`): far_bare_doubt (8), exclaim (6), self_answered (6), stage_hook (6), musing (5), ear_style (4), far_doubt (3), sarcasm (3), after_answer (2), quote (2), tag (2), doubt_particle (1)
- **вопрос к говорящему** (`question_to_speaker`): finance (9), history (9), science (9), followup (7), everyday (5), personal_work (5), self_recall (5), topic_task (5), astronomy (3), it (3), personal_bio (3), personal_exam (3), personal_memory (3), personal_plan (3), ear_style (2), english_question (2), interrupter (2), law (2), medicine (2), personal_medicine (2), personal_opinion (2), personal_taste (2), sport (2), travel (2), two_recognitions (2), definition (1), mixed_language (1), museum (1), personal_ear (1), personal_family (1), personal_feeling (1), personal_firm (1), personal_forecast (1), personal_money (1), repair (1), school (1), when_to_prompter (1)
- **вопрос после длинного вступления** (`long_preamble`): preamble_only (4), conditions_spread (3), story_then_question (3), ear_style (2), preamble_other (2), preamble_request (2), two_questions (2), angry_then_question (1), complaint_then_question (1), complaint_then_topic (1), conditions_in_preamble (1), exam_muddle (1), family_then_question (1), filler_heavy (1), ip_question (1), late_to_class (1), negation_in_condition (1), nerves_then_question (1), preamble_rhetorical (1), question_withdrawn (1), stage_nerves (1), thanks_then_question (1), trip_then_question (1)
- **просьба** (`request`): to_other (11), listener_to_speaker (7), to_prompter (7), to_speaker_personal (5), to_audience (3), to_prompter_meta (2), to_speaker_physical (2), english_to_other (1), to_speaker_repeat (1)
- **спор** (`dispute`): right_answer_doubted (11), between_people (9), far_after_answer (7), wrong_answer_doubted (7), wrong_answer_denied (6), about_plan (4), late_true_doubt (4), challenge_to_speaker (2), about_numbers_of_others (1), bare_doubt_after_answer (1), ear_style (1), not_to_prompter (1)
- **команда** (`command`): stop (10), next (6), repeat (6), continue (4), to_other (3), to_room (3), to_child (2), to_colleague (2), english_to_other (1), narration (1), reported (1), to_client (1), to_coworker (1), to_driver (1), to_group (1), to_neighbour (1), to_self (1), to_speaker (1), to_student (1), to_students (1), to_voice_assistant (1)
- **неразборчивое** (`unclear`): cut_question (4), noise (4), hesitation (3), agreement (2), cut_topic (2), garbled_question (2), name_only (2), number_only (2), slang (2), stutter (2), two_recognitions_complete (2), word_salad (2), cut_sentence (1), ear_style (1), humming (1), laugh (1), trailing (1), two_recognitions_noise (1), whisper (1)

## Гипотезы (откуда ждём ошибку) и охраны (что правка не должна сломать)

| Метка | Строк | Суть |
|---|---|---|
| `H-FRAME` | 23 | Вступление BRAIN («человек на экзамене, на собеседовании или перед презентацией») учит отвечать на всё, что похоже на знание: диктор, реклама, рассказ с цифрами получают ответ. |
| `H-ADDR` | 90 | В BRAIN нет адресата: имя в начале, «ты», поручение, вопрос про дела коллеги читаются как вопрос к подсказке. |
| `H-RHET` | 41 | Риторический вопрос, возглас в форме вопроса, вопрос докладчика залу читаются как настоящий вопрос. |
| `H-ANSWERSELF` | 7 | Говорящий сам отвечает на свой вопрос в той же реплике; подсказка отвечает второй раз. |
| `H-TOPIC` | 28 | Правило «тема билета без вопроса есть вопрос» срабатывает на рассказ, на объявление темы слайда, на тему в сплетне. |
| `H-PERSONAL` | 36 | Вопрос о личном (жизнь, планы, чувства, фирма, самочувствие говорящего) получает выдуманный ответ: «на любой вопрос отвечай самым надёжным». |
| `H-DOUBT` | 97 | Рамка «Вопрос / Твой ответ / Сейчас прозвучало» живёт весь звонок (fast_in_play берёт последний обмен всегда). Правило BRAIN «сомнение — отвечай всегда, «—» запрещён» и правило контроллера (of_the_answer, _doubt_held) тянут постороннее «правда?», «точно», «не может быть», «неправильно» в повтор старого ответа. |
| `H-CMD` | 39 | Слова команды («дальше», «подожди», «повтори», «продолжай», «стой») к другому человеку или внутри рассказа читаются как метка. |
| `H-UNCLEAR` | 37 | Обрывок, шум, ошибка записи, слово без глагола получают выдуманный вопрос и ответ. |
| `H-LONG` | 39 | Длинное вступление или минута рассказа искажает вердикт: условие теряется, или рассказ с темой принимается за задание. |
| `H-CTX` | 19 | Реплику без прежних строк нельзя решить: продолжение («а почему?», «а Италии?») и пары с одинаковыми словами. |
| `H-NUM` | 67 | Число, имя или одно слово без глагола: число считается вопросом, или вопрос с числом теряет число. |
| `H-MULTI` | 4 | В реплике два вопроса: другому человеку и подсказке; или вопрос о факте, который назван «коллегам». |
| `H-EN` | 8 | Не русский язык или смесь: BRAIN не сказано, что делать. |
| `H-SELF` | 9 | Вопрос себе: воспоминание («забыл, в каком году…») надо отвечать, мысль вслух («интересно, что будет…») нет. |
| `G-ANSWER` | 72 | Охрана: настоящий вопрос к говорящему должен получать верный ответ; правка, которая глушит «лишнее», не должна глушить его. |
| `G-ADDR` | 22 | Охрана: вопрос или просьба с «скажите», «подскажи», «ты можешь», «покажите» к говорящему или подсказке не должны глохнуть от правила адресата. |
| `G-TOPIC` | 10 | Охрана: тема без вопроса, названная экзаменатором («Закон Ома.», «Билет пять, инфляция.», «Семь на восемь.»), должна оставаться заданием. |
| `G-DOUBT` | 33 | Охрана: настоящее сомнение в ответе подсказки («ты уверена?», «нет, это неверно») должно получать ответ: верный подтверждён, неверный исправлен. |
| `G-CMD` | 26 | Охрана: настоящая команда подсказке («повтори», «дальше», «продолжай», «стоп») должна давать метку. |
| `G-STOP` | 17 | Охрана P0: «стоп» должен оставаться лёгким; лишняя пауза дёшева, пропущенный стоп нет. |
| `G-SELF` | 8 | Охрана: вопрос себе вслух («забыл, как называется…») — работа суфлёра, его нельзя заглушить правилом «нет адресата». |
| `G-LATE` | 4 | Охрана: настоящее сомнение с предметом, сказанное через две-три реплики после ответа («про год крещения ты ошиблась»), должно получать ответ: это цена срока жизни ответа «в игре» (V11). |
| `G-CTX` | 9 | Охрана: продолжение («а Италии?», «а почему?», «а звука?») должно отвечаться с опорой на ответ в игре. |
| `G-PREAMBLE` | 25 | Охрана: вопрос после длинного вступления должен получить ответ на вопрос, с числами и условиями вступления. |

## Прежние реплики (контекст)

- строк без прежних реплик (начало разговора): 110; с 1-2 репликами: 320; с 3 и более: 114.
- прежние реплики написаны вручную у 192 строк; у 242 строк без собственного контекста стоят одна-три нейтральные реплики сцены из заготовленного списка (`ctx_auto`, `fill_context` в сборщике: без вопросов, чисел, слов команды и сомнения), чтобы режим `prior` и рамка были проверены не только на строках с придуманным контекстом.
- строк, где в прошлом есть ответ подсказки (в боевом звонке такая реплика получает рамку «Вопрос / Твой ответ / Сейчас прозвучало»): 123; сколько реплик прошло после этого ответа: 0: 80, 1: 8, 2: 11, 3: 23, 4: 1.

## Пары: одни слова, разные метки

| Пара | Вид | Слова | Метка 1 (контекст) | Метка 2 (контекст) |
|---|---|---|---|---|
| `pair_01` | context_decides | «Налог на прибыль.» | answer: Следующий билет. | silent: Так, теперь переходим к след |
| `pair_02` | context_decides | «А почему?» | answer: Что такое амортизация? / →Амортизация — это перенос ст | silent: Я завтра не приду. |
| `pair_03` | context_decides | «Ты уверена?» | answer: В каком году крестили Русь? / →В 988 году. | silent: Я сам всё оформлю, не пережи |
| `pair_04` | context_decides | «Повтори.» | mark: Столица Франции? / →Париж. | silent: Я не расслышал, что он сказа |
| `pair_05` | context_decides | «Стой.» | mark: Что такое амортизация? / →Амортизация — это перенос ст | silent: Смотри, он побежал к дороге. |
| `pair_06` | context_decides | «Дальше.» | mark: Что такое НДС? / →НДС — налог на добавленную с | silent: Мы закончили со вторым пункт |
| `pair_07` | context_decides | «Неужели?» | answer: В каком году основан Санкт-П / →В 1703 году. | silent: Говорят, экзамен перенесли н |
| `pair_08` | context_decides | «А что такое амортизация?» | answer: Мы сегодня говорили про осно | silent: Лена, объясни Пете про основ |
| `pair_09` | context_decides | «Давай ещё раз.» | mark: Сколько бит в байте? / →8 бит. | silent: У нас не получилось с первог |
| `pair_10` | context_decides | «Это неверно.» | answer: В каком году отменили крепос / →В 1881 году. | silent: Предлагаю перенести запуск н |
| `pair_11` | indistinguishable | «точно» | silent: Сколько ног у паука? / →8 ног. | silent: Сколько ног у паука? / →8 ног. |
| `pair_12` | indistinguishable | «ну может быть» | silent: Сколько ног у паука? / →8 ног. | silent: Сколько ног у паука? / →8 ног. |
| `pair_13` | indistinguishable | «а в каком году это было» | silent: Мы тогда ещё в старом офисе  | silent: Мы тогда ещё в старом офисе  |
| `pair_14` | context_decides | «Ты уверен?» | answer: Сколько игроков в футбольной / →Двенадцать. | silent: Я бы на матч не ходил в таку |
| `pair_15` | context_decides | «Давайте дальше.» | mark: Что такое API? / →API — это интерфейс, по кото | silent: С этим слайдом закончили. |
| `pair_16` | context_decides | «А почему?» | answer: Какая планета самая горячая? / →Венера. | silent: Вася не пришёл на лекцию. |
| `pair_17` | indistinguishable | «вот именно» | silent: Какая звезда ближе всего к З / →Солнце. | silent: Какая звезда ближе всего к З / →Солнце. |

## Как запустить (живой прогон делает ноутбук; здесь модель не вызывалась)

```
. "C:\УСТРОЙСТВО 1\U1\05_WORK\scripts\echo-env.ps1"
& $EchoPython -B exp_brain_eval_n2.py --dry-run                      # запросы построены и проверены, модель не вызвана
& $EchoPython -B exp_brain_eval_n2.py --local                        # локальный слой настоящими функциями продукта, без модели
& $EchoPython -B exp_brain_eval_n2.py --live --confirm-no-phone-call # база: BRAIN как есть, solo, 1 повтор, около 530 коротких вызовов
& $EchoPython -B exp_brain_eval_n2.py --live --confirm-no-phone-call --variants all --reps 1 --max-requests 8000   # все правки по одной
```

Порядок: 1) `--dry-run`; 2) база; 3) смотреть таблицу по классам и список ложных ответов только по dev; 4) варианты по одной правке; 5) сумма удачных; 6) holdout смотреть как число, не как список.

## Что НЕ доказано этим набором

- Голос. Все строки текстовые; ASR-ошибки, громкость, наложение речи, настоящий выбор «кто говорит» остаются на сценах n1/n2 с живым или синтезированным звуком.
- Адресат по звуку. Здесь адресат известен из метки; у системы его нет, и метка «адресат» в запрос не идёт.
- Частота ложных вмешательств в час: набор даёт долю на строку, а не часы разговора (T05: знаменатель в часах нужен отдельно).
- Материал владельца. Строки о личной жизни и фирме ожидают молчание потому, что материала в запросе нет; при материале часть ответов станет верной.
- Независимость holdout: он написан другим сюжетом и темами, но тем же автором; настоящая независимость — живой разговор.
