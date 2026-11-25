# ECHO — что вошло в ночь и что сейчас активно, 25 ноября

Рабочий SHA 93617c4ff942. Проверка первой родительской линии от вечерней точки 24.11 19:08. Колонка «пакет» использует смысл итогового изменения. Некоторые рабочие ветки переиспользовали одно имя.

| МСК | Слияние | Проверенное изменение |
|---|---|---|
| 24.11 21:35 | 74b89c9f | W-hypo3 — удержание ответов, приоритет ревью, изменения поиска и отделения очередей |
| 25.11 00:01 | c7d02df5 | W-rig — стенд для прохождения карточки через цепочку проверок |
| 00:04 | ddebb135 | W-true2 — учёт фактических вызовов и аргументов |
| 01:15 | bdc73abf | W-pack — пакет и проверки фикстур/вердиктов |
| 02:24 | 97ff5ce6 | W-pack — учёт блокировок и тесты пакета |
| 02:45 | d6156e48 | W-pack — финальная сборка после пакета или отката |
| 06:58 | 1284c89e | fac-39 — поведение при лимите GitHub |
| 08:48 | e3b9ec19 | W-exact — адресность контракта для красных строк |
| 08:56 | 82dbd550 | W-split — роли Flash-Lite для нарезки и Gemma для правок |
| 09:22 | 8180139d | W-path/W-free — выбор пути, маршруты и проверки |
| 09:25 | 066d315c | W-await — главный шаг возобновляется при длительном ожидании воркера |
| 09:58 | 93617c4f | W-need2 — decision=need нормализуется в запрос исходника |

Локально прошли 45 адресных тестов в test_factory_need2.py, test_factory_need_outline.py и test_factory_loop_core3.py.

Публичное зеркало 02dbc299ebccca52a4a8e1189e525b25fa2cab95 ссылается на тот же исходный SHA. Матрица: 28 успешных задач, aggregate gate пропущен. Она проверяет опубликованное подмножество. Живая приёмка по продукту измеряется журналом фабрики. [Коммит зеркала](https://github.com/ddotdanyaa/echo-u1-ci-mirror/commit/02dbc299ebccca52a4a8e1189e525b25fa2cab95) · [Прогон](https://github.com/ddotdanyaa/echo-u1-ci-mirror/actions/runs/45564708443)

## Ветки и лишние слои

Верхушки fix/W-hypo3, fix/W-pack, fix/W-rig и fix/W-true2 являются предками живого SHA. Эти четыре рабочие копии всё ещё зарегистрированы в Git. Их наличие само по себе не запускает повторную работу: цикл отчитывается по SHA основной ветки. Затраты создают одновременно запущенные сборки, повторное владение одними файлами, фоновые проверки старой базы и переплетение поведения в уже влитом коде. Чтобы установить дубли, сверять parent SHA, изменённые модули, тест и запущенный процесс. Метки WT/W/TIC/WC нельзя использовать как критерий удаления. Для WT/TIC/WC однозначного соответствия живым веткам и активным задачам в найденных реестрах не установлено. Удаление веток, откат кода или изменение прав контроллера не выполнялись.

Два отдельных направления следует различать по доказательству. Рабочие пакеты тестов помогли закрыть большой объём уже зелёного долга: 248 уникальных строк. Главный дефект нарезчика устранили утром после разбора живого ответа. Доказательств, что все ночные изменения были необходимы для этой конкретной правки или что они ускорили приёмку, нет.

## Прямые исходники

- [Нарезчик и парсер ответа](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/factory_architect.py)
- [Адресные тесты нового протокола](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tests/test_factory_need2.py)
- [Цикл и ожидание воркеров](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/factory_loop.py)
- [Очередь гипотез](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/factory_hypo.py)
- [Исполнитель и ревью](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/agent_factory_runner.py)
- [Маршрутизация Flash-Lite/Gemma и квоты](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/factory_channels.py)
- [Учёт фактических вызовов](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/factory_calls.py)
- [Подбор файлов и символов](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/repomap.py)
- [Проверки кандидата](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/factory_gate.py)
- [Сборка, релиз и закрытие долга](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/factory_release.py)
- [Метрики и знаменатели](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/tools/factory_metrics.py)
- [Облачный workflow](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/02dbc299ebccca52a4a8e1189e525b25fa2cab95/.github/workflows/factory-matrix.yml)

- [Парсер непосредственно перед W-need2, 066d315c](https://raw.githubusercontent.com/ddotdanyaa/echo-u1-ci-mirror/2ccfc536131a64072c4700f7d5170789fb63fca0/tools/factory_architect.py)
