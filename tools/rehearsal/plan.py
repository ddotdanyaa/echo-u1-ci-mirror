"""Р001-Р104: each rehearsal is one line of configuration, and the bank of questions the fake mind answers from.

A line is ``title | key=value key=value ...``. Keys (all optional; ``sim.Spec`` has the defaults):
  min      simulated minutes                       ask    the question families, comma separated (``bank``): op09 tax op05 op01 out law def num cmp why ex yesno
  noise    the ear: clean snr10 snr5               intro  share of questions after a long preamble          long   answer of N sentences (one portion each about)
  tempo    words per second of speech (2-3)        st     the stutter of a repeat: first mid last num filler stretch cut restart skip swap more own closed
  user     weights of what the user does after a cue (kind:weight,...)      idle   weights of what is said with no fresh cue
  others   weights of who else speaks: stranger tv laugh door aside argue rhet answer_other again_other stop_other chatter (kind:weight,...)
  orate    others' utterances per minute            gap    seconds of silence between acts (lo,hi)           burst  N questions in S seconds at the start (N/S)
  faults   events at seconds: drop5@40 drop30@40 silent12@20 429@20 search@20 live@0 eardead@20 restart@40 cold@0 call2@30
  pause    S@T: nobody speaks S seconds from T     flags  profile overrides (key:value,...)   approx  what this text stand does not model (said in the board)
"""
from dataclasses import dataclass

PLAN = {
    # А. Друг спрашивает
    'Р001': 'Один вопрос по ОП.09 | ask=op09',
    'Р002': 'По налогам | ask=tax',
    'Р003': 'По ОП.05 | ask=op05',
    'Р004': 'По ОП.01 | ask=op01',
    'Р005': 'Вне предметов | ask=out',
    'Р006': 'Статья закона по номеру | ask=law',
    'Р007': 'Определение | ask=def',
    'Р008': 'Число, дата | ask=num,year',
    'Р009': 'Сравнение двух понятий | ask=cmp',
    'Р010': 'Почему | ask=why',
    'Р011': 'Пример | ask=ex',
    'Р012': 'Да или нет с условием | ask=yesno,verb',
    'Р013': 'Вопрос после длинного вступления | ask=op09,tax,num intro=1',
    'Р014': 'Вопрос с поправкой числа | ask=money,mult user=fix:30,repeat:40 idle=question:30,fix:30,silence:10',
    'Р015': 'Вопрос с «не» | ask=verb',
    'Р016': 'Уточнение к прошлому ответу | ask=op09,tax user=follow:25,repeat:45',
    'Р017': 'Возражение | ask=op09,tax,num user=object:25,repeat:45',
    'Р018': 'Сомнение «точно?» | ask=num,money user=doubt:25,repeat:45',
    'Р019': 'Вопрос на английском | ask=en',
    'Р020': 'Составной вопрос | ask=compound',
    # Б. Запинка и повтор
    'Р021': 'Запинка на первом слове | st=first user=stutter:60,repeat:15',
    'Р022': 'В середине | st=mid user=stutter:60,repeat:15',
    'Р023': 'На последнем | st=last user=stutter:60,repeat:15',
    'Р024': 'На числе | ask=money,mult,num,year st=num user=stutter:60,repeat:15',
    'Р025': 'С заполнителем | st=filler user=stutter:60,repeat:15',
    'Р026': 'Растянутое слово | st=stretch user=stutter:60,repeat:15',
    'Р027': 'Оборванное слово | st=cut user=stutter:60,repeat:15',
    'Р028': 'Возврат к началу | st=restart user=stutter:60,repeat:15',
    'Р029': 'Пропуск слова | st=skip user=stutter:60,repeat:15',
    'Р030': 'Перестановка | st=swap user=stutter:60,repeat:15',
    'Р031': 'Сказал больше порции | st=more user=stutter:60,repeat:15 long=4',
    'Р032': 'Сказал своими словами | st=own user=stutter:60,repeat:15',
    'Р033': 'Запинка в закрытый микрофон | st=closed user=stutter:60,repeat:15 approx=mic',
    'Р034': 'Быстрый темп | tempo=3.5',
    'Р035': 'Медленный темп | tempo=1.5 user=stutter:30,repeat:40 st=stretch',
    # В. Шум и чужая речь
    'Р036': 'Перемена, гул 10 дБ | noise=snr10 others=chatter:3,laugh:1 orate=2',
    'Р037': 'Гул 5 дБ | noise=snr5 others=chatter:3,laugh:1 orate=2',
    'Р038': 'Телевизор | others=tv:1 orate=3 approx=voice',
    'Р039': 'Говорят рядом 20 с | others=aside:1 orate=1',
    'Р040': 'Говорят поверх подсказки | others=chatter:1 orate=3 over=1',
    'Р041': 'Смех | others=laugh:1 orate=2',
    'Р042': 'Хлопок двери | others=door:1 orate=2',
    'Р043': 'Прошёл мимо и спросил другое | others=passer:1 orate=0.7',
    'Р044': '«Повторите» от другого | others=again_other:1 orate=1',
    'Р045': '«Стоп» от другого | others=stop_other:1 orate=1',
    'Р046': 'Реплика другому человеку | others=aside:1 orate=1.5',
    'Р047': 'Болтовня 5 минут | min=6 others=chatter:4,aside:1 orate=8 chat=5@30',
    'Р048': 'Спор двоих | others=argue:1 orate=4',
    'Р049': 'Риторический вопрос | others=rhet:1 orate=1',
    'Р050': 'Чужой ответ на вопрос | others=answer_other:1 orate=1',
    # Г. Поток вопросов
    'Р051': 'Три вопроса за 20 с | burst=3/20',
    'Р052': 'Новый посреди порции | user=newq:25,repeat:50 barge=0.5',
    'Р053': 'Новый посреди запинки | st=restart user=stutter:40,newq:25,repeat:20',
    'Р054': 'Вопрос отменён «неважно» | idle=question:40,cancel:25,silence:10',
    'Р055': 'Вопрос не распознан, вы повторили | lostq=0.4',
    'Р056': 'Вы ответили сами | user=self:25,repeat:45',
    'Р057': 'Два человека сразу | others=passer:1,chatter:1 orate=2 over=1',
    'Р058': 'Возврат к старому вопросу | idle=question:40,back:20,silence:10',
    'Р059': 'Десять вопросов подряд | burst=10/60 min=3',
    'Р060': 'Двадцать вопросов без касания | burst=20/180 min=4 user==silence:1 idle==silence:1',
    # Д. Длинная дистанция
    'Р061': '10 минут | min=10',
    'Р062': '30 минут | min=30',
    'Р063': '60 минут | min=60',
    'Р064': '180 минут | min=180',
    'Р065': 'Ответ на 40 порций | long=40 min=6 user=repeat:80,partial:5,stutter:5 idle=question:5,silence:5',
    'Р066': 'Дословная статья целиком | ask=law long=12 min=4 user=repeat:70,stutter:10',
    'Р067': 'Материал на 27 000 знаков | long=25 min=6 approx=material',
    'Р068': 'Смена четырёх предметов | ask=op09,tax,op05,op01 rotate=1 min=4',
    'Р069': 'Сжатие истории | min=30 approx=history',
    'Р070': 'Тишина 2 минуты и вопрос | min=4 pause=120@20',
    # Е. Сбои
    'Р071': 'Первый звонок после ночи | faults=cold@0',
    'Р072': 'Второй звонок подряд | faults=call2@40',
    'Р073': 'Разрыв на 5 с | faults=drop5@40',
    'Р074': 'Разрыв на 30 с | faults=drop30@40 min=3',
    'Р075': 'Модель молчит 12 с | faults=silent12@15',
    'Р076': 'Codex 429 | faults=429@15',
    'Р077': 'Поиск упал | ask=out,law faults=search@10 approx=search',
    'Р078': 'GPT-Live не открылся | faults=live@0',
    'Р079': 'Умер процесс звука | faults=eardead@30',
    'Р080': 'Перезапуск сервера посреди | faults=restart@50',
    # Ж. Материал и законы
    'Р081': 'Вопрос из файла | ask=op09,op05 approx=material',
    'Р082': 'Вне файла | ask=out approx=material',
    'Р083': 'Статья НК дословно | ask=law long=8',
    'Р084': 'Часть и пункт | ask=lawpart',
    'Р085': '«Дальше» по статье | ask=law long=8 user=resume:40,repeat:30',
    'Р086': 'Статья утратила силу | ask=lawgone',
    'Р087': 'Чужой закон с тем же номером | ask=law,lawother',
    'Р088': 'Счёт плана счетов | ask=acct',
    'Р089': 'Устаревшая норма | ask=lawgone,law',
    'Р090': 'Личное в вопросе | ask=personal',
    # З. Голос и слышимость
    'Р091': 'Числа вслух | ask=num,money,mult,year approx=voice',
    'Р092': 'Термины | ask=def approx=voice',
    'Р093': 'Сокращения | ask=en,acct approx=voice',
    'Р094': 'Длинное слово | ask=def,op05 approx=voice',
    'Р095': 'Конец ответа | long=3 user=repeat:85 approx=voice',
    # И. Утренний тест
    'Р096': 'Открытие звонка за секунду-две | first=1 approx=call_open',
    'Р097': 'Вопрос из ОП.09 | ask=op09',
    'Р098': 'Запинка с другом | st=mid,filler,restart user=stutter:50,repeat:25',
    'Р099': 'Перемена в шуме | noise=snr10 others=chatter:3,laugh:1,door:1 orate=3',
    'Р100': 'Игра 5 минут целиком | min=5 ask=op09,tax,op05,op01,num,money,law st=mid,filler,first user=stutter:20 others=chatter:1,laugh:1 orate=1',
    # З. Тяжёлые сцены (f6-stress)
    'Р101': 'Шум и перебивание | noise=snr5 others=chatter:3,laugh:1 orate=3 over=1 user=newq:25,repeat:45 barge=0.5',
    'Р102': 'Поток вопросов во время запинки | st=mid,restart,filler user=stutter:40,newq:30,repeat:15 burst=3/15 barge=0.4',
    'Р103': 'Разрыв связи посреди порции | long=6 faults=drop5@25,drop5@70 user=repeat:70,stutter:10 min=3',
    'Р104': 'Новый вопрос поверх поправки числа | ask=money,mult user=fix:30,newq:30,repeat:25 idle=question:30,fix:30,silence:10 barge=0.5',
}


@dataclass(frozen=True)
class Fact:
    """A question of the bank: ``text`` as asked, ``reply`` the right answer; ``fits``/``contradicts`` like ``tools.replay.stand.Q`` (the scoreboard and the invariants
    use both). The key of an answer: its numbers and its longer words that the question does not have."""
    family: str
    params: tuple
    text: str
    reply: str

    def answer(self):
        return self.reply

    def _keys(self):
        from tools.replay.stand import lemmas, values
        asked = lemmas(self.text)
        return values(self.reply), {w for w in lemmas(self.reply) - asked if len(w) >= 5}

    def allowed(self):
        from tools.replay.stand import values
        return values(self.reply) | values(self.text)

    def fits(self, plan):
        from tools.replay.stand import lemmas, values
        from echo_sync.textutil import normalize
        said, ideal = normalize(plan), normalize(self.reply)
        if said and (ideal.startswith(said) or said.startswith(ideal) or (len(said) > 25 and said in ideal)):
            return True
        if self.contradicts(plan):
            return False
        asked = values(self.text)
        if self.family in LAWS and asked and asked <= values(plan) and lemmas(plan) & {'статья', 'пункт', 'часть', 'счёт', 'счет'}:
            return True                                     # the local base's own reference to the same article or account (the engine answers those itself)
        numbers, words = self._keys()
        if numbers and numbers & values(plan) and (not words or words & lemmas(plan)):
            return True
        return len(words & lemmas(plan)) >= min(2, len(words)) if words else False

    def contradicts(self, plan):
        from tools.replay.stand import lemmas, values
        codes = CODES & lemmas(plan)
        if codes and (CODES & lemmas(self.text)) and not codes & lemmas(self.text):
            return True                                     # another code with the same number (Р087)
        return bool(values(plan) - self.allowed()) if self.allowed() else False


LAWS = ('law', 'lawpart', 'lawgone', 'lawother', 'acct')
CODES = {'налоговый', 'трудовой', 'гражданский'}


L = 'Если у меня было {a} рублей'
BANK = {
    'op09': [('Что такое информационная безопасность по ОП.09?', 'Информационная безопасность это защищённость информации от случайных и преднамеренных воздействий.'),
             ('Какие бывают виды угроз информации?', 'Угрозы бывают случайные и преднамеренные, внешние и внутренние.'),
             ('Что такое конфиденциальность?', 'Конфиденциальность это доступ к информации только у тех, кому она разрешена.'),
             ('Сколько уровней у модели OSI?', 'У модели OSI семь уровней, от физического до прикладного.'),
             ('Что такое брандмауэр?', 'Брандмауэр фильтрует сетевой трафик по заданным правилам.')],
    'tax': [('Какая ставка НДФЛ для резидента?', 'Ставка НДФЛ для резидента 13 процентов, с дохода выше 2400000 рублей 15 процентов.'),
            ('Какая основная ставка НДС?', 'Основная ставка НДС 20 процентов, льготные 10 и 0 процентов.'),
            ('Когда платят налог на имущество физических лиц?', 'Налог на имущество физических лиц платят до 1 декабря следующего года.'),
            ('Кто платит налог на прибыль?', 'Налог на прибыль платят российские организации и иностранные с постоянным представительством.'),
            ('Что такое налоговый вычет?', 'Налоговый вычет уменьшает облагаемую базу или возвращает уплаченный налог.')],
    'op05': [('Что такое бухгалтерский баланс?', 'Бухгалтерский баланс показывает активы, обязательства и капитал на отчётную дату.'),
             ('Что такое амортизация?', 'Амортизация переносит стоимость основного средства на расходы по частям за срок полезного использования.'),
             ('Что относится к оборотным активам?', 'К оборотным активам относятся запасы, дебиторская задолженность и денежные средства.'),
             ('Что такое дебет?', 'Дебет это левая сторона счёта, куда записывают увеличение активов.')],
    'op01': [('Что изучает экономика организации?', 'Экономика организации изучает ресурсы, затраты и результаты деятельности предприятия.'),
             ('Что такое себестоимость?', 'Себестоимость это затраты организации на производство и продажу продукции.'),
             ('Что такое рентабельность?', 'Рентабельность это отношение прибыли к затратам или выручке в процентах.'),
             ('Чем выручка отличается от прибыли?', 'Выручка это все поступления от продаж, а прибыль это выручка минус затраты.')],
    'out': [('Какая самая длинная река в России?', 'Самая длинная река России Обь вместе с Иртышом, около 5410 километров.'),
            ('Сколько планет в Солнечной системе?', 'В Солнечной системе восемь планет.'),
            ('Какая скорость света в вакууме?', 'Скорость света в вакууме около 300000 километров в секунду.'),
            ('Кто написал Войну и мир?', 'Войну и мир написал Лев Толстой.')],
    'law': [('Что говорит статья 143 Налогового кодекса?', 'Статья 143 Налогового кодекса называет плательщиков НДС: организации, предпринимателей и тех, кто ввозит товары.'),
            ('О чём статья 207 Налогового кодекса?', 'Статья 207 Налогового кодекса определяет налогоплательщиков НДФЛ: резидентов и нерезидентов с доходом в России.'),
            ('Что в статье 346.12 НК?', 'Статья 346.12 НК называет плательщиков упрощённой системы и кто её применять не вправе.'),
            ('Что говорит статья 81 Трудового кодекса?', 'Статья 81 Трудового кодекса перечисляет основания увольнения по инициативе работодателя.')],
    'lawpart': [('Что сказано в пункте 2 статьи 146 НК?', 'Пункт 2 статьи 146 НК перечисляет операции, которые не признаются объектом НДС.'),
                ('Что в части 1 статьи 21 Трудового кодекса?', 'Часть 1 статьи 21 Трудового кодекса перечисляет основные права работника.')],
    'lawgone': [('Действует ли статья 117 Налогового кодекса?', 'Нет, статья 117 Налогового кодекса утратила силу с 2019 года.'),
                ('Действует ли ЕНВД?', 'Нет, ЕНВД отменён с 2021 года, теперь применяют упрощёнку или патент.')],
    'lawother': [('Что говорит статья 143 Гражданского кодекса?', 'Статья 143 Гражданского кодекса называет виды ценных бумаг: облигации, векселя, акции.')],
    'acct': [('Что такое счёт 51?', 'Счёт 51 это расчётные счета организации в банке.'), ('Что учитывают на счёте 01?', 'На счёте 01 учитывают основные средства организации.'),
             ('Что такое счёт 68?', 'Счёт 68 это расчёты по налогам и сборам с бюджетом.')],
    'def': [('Что такое дивиденды?', 'Дивиденды это часть прибыли, которую распределяют между акционерами.'),
            ('Что такое инфляция?', 'Инфляция это устойчивый рост общего уровня цен и падение покупательной способности денег.'),
            ('Что такое дебиторская задолженность?', 'Дебиторская задолженность это долги других лиц перед организацией.')],
    'num': [('Сколько дней в високосном году?', 'В високосном году 366 дней.'), ('Сколько часов в неделе?', 'В неделе 168 часов.'),
            ('Сколько процентов НДС в России?', 'Основная ставка НДС 20 процентов.')],
    'cmp': [('Чем НДС отличается от налога на прибыль?', 'НДС косвенный налог с добавленной стоимости, а налог на прибыль прямой налог с прибыли организации.'),
            ('Чем актив отличается от пассива?', 'Актив показывает имущество организации, а пассив источники его образования.')],
    'why': [('Почему растут цены при инфляции?', 'Цены растут, потому что денег в обращении становится больше, чем товаров.'),
            ('Почему нужна амортизация?', 'Амортизация нужна, чтобы стоимость основного средства распределить на расходы за срок службы.')],
    'ex': [('Приведи пример косвенного налога.', 'Пример косвенного налога: НДС или акциз, их включают в цену товара.'),
           ('Приведи пример нематериального актива.', 'Пример нематериального актива: патент, товарный знак или программа.')],
    'yesno': [('Если доход меньше миллиона, нужно ли платить налог на имущество?', 'Да, налог на имущество платят независимо от дохода, если имущество есть.'),
              ('Можно ли получить вычет, если работаешь неофициально?', 'Нет, вычет по НДФЛ дают только с уплаченного налога, без официального дохода его нет.')],
    'en': [('What does VAT stand for?', 'VAT это value added tax, налог на добавленную стоимость, по-русски НДС.'),
           ('What is ROI?', 'ROI это return on investment, окупаемость инвестиций, отношение прибыли к вложениям.')],
    'personal': [('Мне 19 лет и я студент, нужно ли мне платить НДФЛ со стипендии?', 'Нет, государственная стипендия НДФЛ не облагается, возраст значения не имеет.'),
                 ('Я работаю в ИП у мамы за 30000 рублей, какой налог с меня?', 'С 30000 рублей зарплаты удерживают НДФЛ 13 процентов, это 3900 рублей.')],
}
INTROS = ('Слушай, у нас тут вчера был такой разговор с преподавателем, долго спорили, и вот я никак не могу понять одну вещь, ну, короче, вопрос такой.',
          'Значит, смотри, ситуация такая: мы разбирали тему на паре, потом ещё дома читал, и всё равно осталось непонятно, скажи мне вот что.')
SENTENCES = ('Первое: налог начисляют по итогам периода.', 'Второе: базу считают нарастающим итогом с начала года.', 'Третье: ставку берут из главы кодекса.',
             'Четвёртое: вычеты уменьшают базу.', 'Пятое: декларацию подают до тридцатого апреля.', 'Шестое: уплату переносят на ближайший рабочий день.',
             'Седьмое: пени начисляют за каждый день просрочки.', 'Восьмое: штраф зависит от умысла.')


def parse(line):
    title, _, body = line.partition('|')
    spec = {}
    for token in body.split():
        key, _, value = token.partition('=')
        spec[key] = value
    return title.strip(), spec


def names(text):
    """``Р001-Р020,Р051`` (Cyrillic or Latin P) -> the rehearsal names in the plan's order."""
    text = (text or 'all').replace('P', 'Р').replace('p', 'Р')
    if text == 'all':
        return list(PLAN)
    out = []
    for part in text.split(','):
        lo, _, hi = part.partition('-')
        lo, hi = int(lo.lstrip('Р')), int((hi or lo).lstrip('Р'))
        out += [f'Р{n:03d}' for n in range(lo, hi + 1) if f'Р{n:03d}' in PLAN]
    return out
