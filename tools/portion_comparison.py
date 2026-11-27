"""Regenerates ``../portion_comparison.md`` by running the real portioner on six sample answers.

Nothing in the report is written by hand except the sample answers: the portions, the syllable counts
and the summary figures all come from ``echo_sync.portioner`` and ``echo_sync.textutil``.

Run (cwd = addon_dev):  python tools/portion_comparison.py [output.md]
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from echo_sync.portioner import _function_marks, _tokenize, _unit_marks, expand_abbreviations, portions, syllables  # noqa: E402
from echo_sync.settings import resolve  # noqa: E402
from echo_sync.textutil import WORDS, normalize  # noqa: E402

ABBREVIATIONS = {'ВВП': 'валовой внутренний продукт', 'ЦБ': 'Центральный банк'}
SAMPLES = [
    ('Определение финансовой системы',
     'Финансовая система Российской Федерации представляет собой совокупность взаимосвязанных сфер финансовых '
     'отношений, в которых образуются, распределяются и используются денежные фонды государства, предприятий и населения.', {}),
    ('Фотосинтез',
     'Фотосинтез — это процесс, в котором растения, водоросли и некоторые бактерии превращают световую энергию '
     'в химическую энергию органических веществ. Он протекает в хлоропластах при участии хлорофилла.', {}),
    ('Статья 228 УК РФ',
     'Статья 228 УК РФ предусматривает ответственность за незаконные приобретение, хранение, перевозку, изготовление '
     'и переработку наркотических средств без цели сбыта в значительном размере.', {}),
    ('Проценты и год',
     'В 2026 году доходы компании выросли на 15 %, а расходы сократились на 6,5 %. Чистая прибыль составила '
     '2,3 млн рублей, и это на 15 % больше, чем годом ранее.', {}),
    ('Длинный термин',
     'Электроэнцефалография — метод регистрации электрической активности головного мозга с помощью электродов, '
     'которые закрепляют на поверхности головы. Метод применяют при диагностике эпилепсии и нарушений сна.', {}),
    ('Сокращения раскрываются при первом упоминании',
     'ВВП показывает стоимость всех товаров и услуг, произведённых в стране за год. Рост ВВП говорит о расширении '
     'экономики, а ЦБ следит за ценами, чтобы инфляция не обесценивала доходы.', {'abbreviations': ABBREVIATIONS}),
]
MODES = [
    ('words = 3', {'portion_mode': 'words', 'words_per_portion': 3}),
    ('syllables', {'portion_mode': 'syllables'}),
]


def split_units(text, pieces):
    """How many inseparable units (number+unit, статья+номер, УК РФ, initials, ...) a cut tears apart."""
    tokens = _tokenize(text)
    glue = _unit_marks(tokens)
    torn, boundary = 0, 0
    for piece in pieces[:-1]:
        boundary += len(WORDS.findall(piece))
        if 0 < boundary < len(tokens) and glue[boundary - 1]:
            torn += 1
    return torn


def dangling(pieces, text):
    """Portions that end on a preposition, conjunction or particle (except at a sentence end)."""
    tokens = _tokenize(text)
    func = _function_marks(tokens)
    count, boundary = 0, 0
    for piece in pieces[:-1]:
        boundary += len(WORDS.findall(piece))
        if boundary and func[boundary - 1]:
            count += 1
    return count


def table(pieces):
    lines = ['| № | Порция | Слов | Слогов |', '|--:|---|--:|--:|']
    for number, piece in enumerate(pieces, 1):
        lines.append(f'| {number} | {piece.replace("|", chr(92) + "|")} | {len(normalize(piece).split())} | {syllables(piece)} |')
    return lines


def main(target=None):
    target = Path(target) if target else ROOT.parent / 'portion_comparison.md'
    out = [
        '# Порции: `words = 3` и `syllables`',
        '',
        f'Файл создан автоматически {datetime.date.today().isoformat()} запуском `addon_dev/tools/portion_comparison.py` '
        '(настоящий `echo_sync.portioner`); руками написаны только шесть образцов ответа.',
        '',
        'Настройки режима `syllables` — значения по умолчанию: ' + ', '.join(
            f'`{key}` = {value}' for key, value in resolve({'portion_mode': 'syllables'}).items()
            if key in ('target_syllables', 'max_syllables', 'max_words', 'min_words', 'long_word_syllables')) + '.',
        'Режим `words = 3` — нынешний по умолчанию: ровно три слова, но порция не кончается предлогом, союзом или частицей '
        'и число («6,5») не рвётся. Режим `syllables` дополнительно не разрывает число с единицей, «статья + номер», «УК РФ», '
        'инициалы и раскрытое сокращение и режет по знакам препинания.',
        'Слоги: число гласных `аеёиоуыэюя`; ЗАГЛАВНЫЕ сокращения читаются по буквам (ВВП = 3), число оценивается по цифрам, '
        '«%» произносится словом. «Слов» — слова в смысле подтверждения повтора (число «6,5» — два слова, тире не слово).',
        '',
    ]
    summary = ['| № | Образец | Режим | Порций | Слогов мин / средн. / макс. | Слов макс. | На служебном слове | Разорвано блоков |',
               '|--:|---|---|--:|---|--:|--:|--:|']
    body = []
    for number, (title, text, extra) in enumerate(SAMPLES, 1):
        body += [f'## {number}. {title}', '', f'> {text}', '']
        if extra.get('abbreviations'):
            body += ['Словарь сокращений: ' + ', '.join(f'«{k}» → «{v}»' for k, v in extra['abbreviations'].items())
                     + '. Первое упоминание произносится полностью, повторное остаётся сокращением.', '']
        for label, settings in MODES:
            settings = {**settings, **extra}
            pieces = portions(text, settings)
            counts = [syllables(piece) for piece in pieces]
            words = [len(normalize(piece).split()) for piece in pieces]
            # Blocks and function words are judged on the text actually spoken (abbreviations expanded).
            expanded = expand_abbreviations(text, resolve(settings)['abbreviations'])
            torn, bad = split_units(expanded, pieces), dangling(pieces, expanded)
            summary.append(f'| {number} | {title} | {label} | {len(pieces)} | {min(counts)} / {sum(counts) / len(counts):.1f} / {max(counts)} '
                           f'| {max(words)} | {bad} | {torn} |')
            body += [f'### {label}', '', *table(pieces), '', f'Всего слогов: {sum(counts)}.', '']
    out += ['## Итоги', '', *summary, '',
            '«На служебном слове» — порции, кончающиеся предлогом, союзом или частицей (не считая конца предложения). '
            '«Разорвано блоков» — сколько раз разрез попал внутрь числа с единицей, «статья + номер», пары сокращений '
            '(«УК РФ»), инициалов или «и т. д.».', '']
    out += body
    target.write_text('\n'.join(out) + '\n', encoding='utf-8')
    print(f'written {target}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
