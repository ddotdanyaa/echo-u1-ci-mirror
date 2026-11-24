"""w4-law: a plausible FAKE of consultant.ru page markup (the real pages are not here) and a generator of a big base. The parser is law_base.parse_page; fit it to real pages on the laptop."""
import html

TK = ('Трудовой кодекс Российской Федерации от 30.12.2001 N 197-ФЗ (ред. от 08.08.2024)', 'https://www.consultant.ru/document/cons_doc_LAW_34683/')
KONST = ('Конституция Российской Федерации (принята всенародным голосованием 12.12.1993) (с изменениями, одобренными в ходе общероссийского голосования 01.07.2020)',
         'https://www.consultant.ru/document/cons_doc_LAW_28399/')
GK = ('Гражданский кодекс Российской Федерации (часть первая) от 30.11.1994 N 51-ФЗ (ред. от 08.08.2024)', 'https://www.consultant.ru/document/cons_doc_LAW_5142/')
NK = ('Налоговый кодекс Российской Федерации (часть первая) от 31.07.1998 N 146-ФЗ (ред. от 29.10.2024)', 'https://www.consultant.ru/document/cons_doc_LAW_19671/')
UK = ('Уголовный кодекс Российской Федерации от 13.06.1996 N 63-ФЗ (ред. от 30.12.2020)', 'https://www.consultant.ru/document/cons_doc_LAW_10699/')


def page(title, articles):
    """articles: [(heading, [paragraph, ...])]; a paragraph that starts with «(» is an annotation; «@» + text is a navigation line."""
    out = ['<html><body><div class="document-page__title">%s</div><div class="document-page__toc"><a href="#x">Содержание</a></div>' % html.escape(title)]
    for n, (heading, paragraphs) in enumerate(articles):
        out.append('<h3 class="article"><a name="article-%d"></a>%s</h3>' % (n, html.escape(heading)))
        out.append('<div class="document-page__content">')
        for p in paragraphs:
            out.append('<p class="%s">%s</p>' % ('note' if p.startswith('(') or p.startswith('Консультант') else 'text', html.escape(p)))
        out.append('</div><div class="footer"><a href="#top">Наверх</a></div>')
    out.append('</body></html>')
    return '\n'.join(out)


TK_ARTICLES = [
    ('Статья 70. Испытание при приеме на работу', [
        '1. При заключении трудового договора в нем по соглашению сторон может быть предусмотрено условие об испытании работника в целях проверки его соответствия поручаемой работе.',
        '(в ред. Федерального закона от 30.06.2006 N 90-ФЗ)',
        '2. В срок испытания не засчитываются период временной нетрудоспособности работника и другие периоды, когда он фактически отсутствовал на работе.']),
    ('Статья 71. Результат испытания', [
        '1. При неудовлетворительном результате испытания работодатель имеет право до истечения срока испытания расторгнуть трудовой договор с работником.',
        'КонсультантПлюс: примечание.']),
    ('Статья 81. Расторжение трудового договора по инициативе работодателя', [
        '1. Трудовой договор может быть расторгнут работодателем в случаях:',
        '1) ликвидации организации либо прекращения деятельности индивидуальным предпринимателем;',
        '2) сокращения численности или штата работников организации, индивидуального предпринимателя;',
        '3) несоответствия работника занимаемой должности или выполняемой работе вследствие недостаточной квалификации, подтвержденной результатами аттестации;',
        'а) первый подпункт для проверки;',
        '(п. 3 в ред. Федерального закона от 30.06.2006 N 90-ФЗ)',
        '2. Увольнение по основаниям, предусмотренным пунктами 2 и 3 части первой настоящей статьи, допускается, если невозможно перевести работника на другую работу, т.е. не более 5% штата.']),
    ('Статья 82. Утратила силу', ['Утратила силу с 6 октября 2006 года. - Федеральный закон от 30.06.2006 N 90-ФЗ.']),
    ('Статья 19. Права потребителя', ['Текст статьи 19 Трудового кодекса для проверки чужого номера.']),
]
KONST_ARTICLES = [
    ('Статья 19', [
        '1. Все равны перед законом и судом.',
        '2. Государство гарантирует равенство прав и свобод человека и гражданина независимо от пола, расы, национальности, языка, происхождения, имущественного и должностного положения.']),
    ('Статья 20', ['1. Каждый имеет право на жизнь.']),
]
GK_ARTICLES = [('Статья 19. Имя гражданина', ['1. Гражданин приобретает и осуществляет права и обязанности под своим именем.'])]
NK_ARTICLES = [('Статья 19. Налогоплательщики и плательщики сборов', ['1. Налогоплательщиками и плательщиками сборов признаются организации и физические лица.'])]


def build(path, today_edition=True):
    from echo_sync import law_base as lb
    docs = [(TK, TK_ARTICLES, 'tk'), (KONST, KONST_ARTICLES, 'konst'), (GK, GK_ARTICLES, 'gk'), (NK, NK_ARTICLES, 'nk')]
    parsed = [lb.parse_page(page(t[0], arts), code, t[1]) for t, arts, code in docs]
    lb.build(path, parsed)
    return parsed


_SYL = ['ба', 'ко', 'му', 'ле', 'ри', 'то', 'ша', 'не', 'вы', 'до', 'жи', 'пра']
WORDS = [a + b + c + d for a in _SYL for b in _SYL for c in _SYL for d in _SYL[:3]][::3]       # ~580 words, distinct five-letter stems: a word is selective, as in real law text


def synthetic(n_articles, seed=7):
    """A big base of the right shape: n_articles in 5 documents, 3 parts each with two points; words from a fixed vocabulary."""
    import random
    from echo_sync import law_base as lb
    rnd = random.Random(seed)
    vocab = WORDS
    codes = ['tk', 'gk', 'nk', 'uk', 'sk']
    docs = []
    for ci, code in enumerate(codes):
        arts = []
        for a in range(1, n_articles // len(codes) + 1):
            paras = []
            for part in range(1, 4):
                paras.append('%d. %s.' % (part, ' '.join(rnd.choice(vocab) for _ in range(18))))
                paras += ['%d) %s;' % (pt, ' '.join(rnd.choice(vocab) for _ in range(9))) for pt in (1, 2)]
            arts.append(('Статья %d. %s' % (a, ' '.join(rnd.choice(vocab) for _ in range(4)).capitalize()), paras))
        docs.append(lb.parse_page(page('Кодекс %d (ред. от 01.01.2025)' % ci, arts), code, 'https://example.invalid/%s' % code))
    return docs
