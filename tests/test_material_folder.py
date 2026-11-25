"""CL1: the owner puts the lesson in ONE folder (ТЕМА.txt + the files) and runs ONE script; the profile then holds exactly that.

The real importer, the real settings writer and the real call-context loader run on temporary folders: the last test of the
chain reads what the next call would be given, so what the owner is told ("loaded: ...") and what the call receives cannot drift
apart. Documents (docx / pdf / pptx) go through the importer's own seams (`extract`, `config`), as in test_materials.py.
"""
import hashlib
import io
import json
from pathlib import Path

import pytest

from echo_sync import materials
from echo_sync.content_policy import MATERIAL_EXCERPT_CHARS, load_call_context
from echo_sync.materials import PLACEHOLDER_CONTEXT, folder_main, import_materials, load_folder, parse_topic, plural, read_topic

SAFE = lambda: {'file_tools': {'hosted_ocr': False}}


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def put(folder, name, content, *, encoding='utf-8'):
    path = Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode(encoding))
    return path


@pytest.fixture
def folder(tmp_path):
    return tmp_path / 'МАТЕРИАЛЫ'


@pytest.fixture
def home(tmp_path):
    return tmp_path / 'profile'


# --- ТЕМА.txt -----------------------------------------------------------------------------------------------------------------

def test_labelled_lines_in_russian_or_english_in_any_case():
    text = 'Предмет: Налоговое право\nАУДИТОРИЯ = студенты второго курса\nstyle: простыми словами\n'
    assert parse_topic(text) == {'subject': 'Налоговое право', 'audience': 'студенты второго курса', 'style': 'простыми словами'}
    assert parse_topic('Тема: Физика\nСлушатели: школьники\nМанера: коротко') == {
        'subject': 'Физика', 'audience': 'школьники', 'style': 'коротко'}
    assert parse_topic('subject: Law') == {'subject': 'Law'}


def test_plain_lines_are_subject_audience_style_in_that_order():
    """Break: «plain lines» is how the owner is told to write it; labels must be optional."""
    assert parse_topic('Налоговое право\nстуденты второго курса\nпростыми словами\n') == {
        'subject': 'Налоговое право', 'audience': 'студенты второго курса', 'style': 'простыми словами'}
    assert parse_topic('Налоговое право') == {'subject': 'Налоговое право'}


def test_a_line_with_a_label_is_never_taken_by_position_and_plain_lines_fill_the_rest():
    assert parse_topic('Аудитория: школьники\nОсновы права\nпростыми словами') == {
        'audience': 'школьники', 'subject': 'Основы права', 'style': 'простыми словами'}


def test_comments_blank_lines_and_extra_plain_lines_are_ignored():
    text = '# подсказка для владельца\n; ещё одна\n// и ещё\n\nФизика\n\nшкольники\nкоротко\nлишняя строка\n'
    assert parse_topic(text) == {'subject': 'Физика', 'audience': 'школьники', 'style': 'коротко'}


def test_a_colon_in_a_plain_subject_is_not_taken_for_a_label():
    assert parse_topic('Право: общая часть') == {'subject': 'Право: общая часть'}
    assert parse_topic('Неизвестный ключ: значение\nвторая') == {
        'subject': 'Неизвестный ключ: значение', 'audience': 'вторая'}


def test_an_empty_value_is_a_value_the_template_of_empty_labels_means_nothing_is_set():
    assert parse_topic('Предмет:\nАудитория:   \nСтиль:\n') == {'subject': '', 'audience': '', 'style': ''}
    assert parse_topic('# только подсказки\n') == {}


def test_when_a_label_repeats_the_last_one_wins():
    assert parse_topic('Предмет: Старое\nПредмет: Новое') == {'subject': 'Новое'}


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16', 'cp1251'])
def test_the_topic_file_is_read_whatever_notepad_saved_it_as(tmp_path, encoding):
    """Break: the owner saves ТЕМА.txt with the Windows default and the subject arrives as mojibake."""
    path = put(tmp_path, 'ТЕМА.txt', 'Предмет: Налоговое право\nСтиль: простыми словами\n', encoding=encoding)
    assert read_topic(path) == {'subject': 'Налоговое право', 'style': 'простыми словами'}


@pytest.mark.parametrize('count, words', [(0, 'файлов'), (1, 'файл'), (2, 'файла'), (4, 'файла'), (5, 'файлов'), (11, 'файлов'),
                                          (12, 'файлов'), (14, 'файлов'), (21, 'файл'), (22, 'файла'), (25, 'файлов'),
                                          (101, 'файл'), (111, 'файлов'), (112, 'файлов')])
def test_the_units_in_the_report_agree_with_the_numbers(count, words):
    """Break: «1 файлов», «22 файл» - a report for a non-programmer that reads like a machine wrote it."""
    assert plural(count, 'файл', 'файла', 'файлов') == words


def test_the_report_declines_the_units_of_what_it_counts(folder, home):
    put(folder, 'лекция.txt', 'Один.')
    text = run_main(folder, home)[1]
    assert '9 байт, 5 знаков' in text and 'Загружено: 1 файл, ' in text, text


# --- the folder -----------------------------------------------------------------------------------------------------------------

def test_a_folder_with_a_topic_and_files_becomes_the_lesson_of_the_next_call(folder, home):
    """The whole chain: files -> importer -> context.md + settings -> what the next call is given."""
    put(folder, 'ТЕМА.txt', 'Предмет: Налоговое право\nАудитория: студенты\nСтиль: простыми словами\n')
    put(folder, 'б_конспект.txt', 'Налог на прибыль платят юридические лица.')
    put(folder, 'а_лекция.md', '# Лекция\nНДС - косвенный налог.')
    result = load_folder(folder, home)
    assert [item['name'] for item in result['files']] == ['а_лекция.md', 'б_конспект.txt'], 'sorted by name'
    assert [item['bytes'] for item in result['files']] == [len('# Лекция\nНДС - косвенный налог.'.encode()),
                                                           len('Налог на прибыль платят юридические лица.'.encode())]
    assert result['skipped'] == [] and result['cleared'] is None
    stored = json.loads((home / 'materials' / 'echo_settings.json').read_text(encoding='utf-8'))
    assert stored == {'subject': 'Налоговое право', 'audience': 'студенты', 'style': 'простыми словами'}
    call = load_call_context(home)
    assert (call.subject, call.audience, call.style) == ('Налоговое право', 'студенты', 'простыми словами')
    assert 'НДС - косвенный налог.' in call.excerpt and 'Налог на прибыль платят юридические лица.' in call.excerpt
    assert result['context']['sha256'] == call.material_sha256, 'what the owner is told is what the call reads'
    assert result['context']['chars'] == call.material_chars


def test_documents_and_presentations_go_through_the_same_importer(folder, home):
    for name in ('лекция.docx', 'книга.pdf', 'слайды.pptx'):
        put(folder, name, b'binary')
    result = load_folder(folder, home, extract=lambda path: 'Текст из файла ' + path.name, config=SAFE)
    assert [(item['name']) for item in result['files']] == ['книга.pdf', 'лекция.docx', 'слайды.pptx']
    text = load_call_context(home).excerpt
    for name in ('книга.pdf', 'лекция.docx', 'слайды.pptx'):
        assert 'Текст из файла ' + name in text


def test_the_topic_file_is_not_a_material_and_junk_is_neither_loaded_nor_reported(folder, home):
    put(folder, 'ТЕМА.txt', 'Физика')
    put(folder, 'тема.TXT.bak.txt', 'это настоящий файл материала')      # not the topic file: a different name
    for junk in ('~$лекция.docx', '.скрытый.txt', 'desktop.ini', 'Thumbs.db'):
        put(folder, junk, b'junk')
    put(folder, 'схема.png', b'\x89PNG')
    result = load_folder(folder, home)
    assert [item['name'] for item in result['files']] == ['тема.TXT.bak.txt']
    assert result['skipped'] == ['схема.png']
    assert 'Физика' not in load_call_context(home).excerpt


def test_the_topic_file_is_found_whatever_the_case_of_its_name(folder, home):
    put(folder, 'тема.txt', 'Предмет: Химия')
    put(folder, 'лекция.txt', 'Сублимация.')
    load_folder(folder, home)
    assert load_call_context(home).subject == 'Химия'


def test_the_other_keys_of_the_owners_settings_file_survive(folder, home):
    (home / 'materials').mkdir(parents=True)
    (home / 'materials' / 'echo_settings.json').write_text('{"portion_mode": "syllables", "target_syllables": 6}', encoding='utf-8')
    put(folder, 'ТЕМА.txt', 'Химия')
    put(folder, 'лекция.txt', 'Сублимация.')
    load_folder(folder, home)
    stored = json.loads((home / 'materials' / 'echo_settings.json').read_text(encoding='utf-8'))
    assert stored == {'portion_mode': 'syllables', 'target_syllables': 6, 'subject': 'Химия'}


def test_a_key_the_topic_file_does_not_mention_is_cleared_too(folder, home):
    """Break: the folder is the truth - an audience from the last lesson must not survive a ТЕМА.txt that no longer has one."""
    (home / 'materials').mkdir(parents=True)
    (home / 'materials' / 'echo_settings.json').write_text('{"subject": "Старый", "audience": "старые", "style": "тоже", "portion_mode": "words"}',
                                                          encoding='utf-8')
    put(folder, 'ТЕМА.txt', 'Предмет: Химия')
    put(folder, 'лекция.txt', 'Текст.')
    load_folder(folder, home)
    assert json.loads((home / 'materials' / 'echo_settings.json').read_text(encoding='utf-8')) == {'portion_mode': 'words', 'subject': 'Химия'}


def test_an_empty_topic_file_removes_the_old_subject(folder, home):
    """Break: the template of empty labels is run for a new lesson and the old subject keeps steering the model."""
    (home / 'materials').mkdir(parents=True)
    (home / 'materials' / 'echo_settings.json').write_text('{"subject": "Старый", "audience": "старые", "style": "тоже"}', encoding='utf-8')
    put(folder, 'ТЕМА.txt', '# подсказки\nПредмет:\nАудитория:\nСтиль:\n')
    put(folder, 'лекция.txt', 'Текст.')
    load_folder(folder, home)
    assert json.loads((home / 'materials' / 'echo_settings.json').read_text(encoding='utf-8')) == {}


def test_without_a_topic_file_the_subject_is_left_alone(folder, home):
    (home / 'materials').mkdir(parents=True)
    (home / 'materials' / 'echo_settings.json').write_text('{"subject": "Остаётся"}', encoding='utf-8')
    put(folder, 'лекция.txt', 'Новый текст.')
    result = load_folder(folder, home)
    assert result['topic'] is None and result['settings'] is None
    assert load_call_context(home).subject == 'Остаётся' and 'Новый текст.' in load_call_context(home).excerpt


def test_a_folder_without_material_files_removes_the_old_material_after_copying_it_aside(folder, home):
    """Break: the lesson changes, the folder is emptied, and the last lecture keeps feeding the model with no sign of it."""
    old = Path(folder).parent / 'старое.txt'
    old.write_text('Старая лекция про законы Ньютона.', encoding='utf-8')
    import_materials([old], home)
    before = (home / 'materials' / 'context.md').read_bytes()
    put(folder, 'ТЕМА.txt', 'Предмет: Химия')
    result = load_folder(folder, home)
    assert result['files'] == [] and result['context'] is None
    assert (home / 'materials' / 'context.md').read_text(encoding='utf-8') == PLACEHOLDER_CONTEXT
    assert Path(result['cleared']['backup']).read_bytes() == before
    call = load_call_context(home)
    assert call.excerpt == '' and call.note == 'placeholder' and call.subject == 'Химия'


def test_clearing_twice_does_not_pile_up_copies_of_the_placeholder(folder, home):
    put(folder, 'ТЕМА.txt', 'Химия')
    first = load_folder(folder, home)
    second = load_folder(folder, home)
    assert first['cleared']['backup'] is None and second['cleared']['backup'] is None
    assert list((home / 'materials').glob('*.bak')) == []


def test_nothing_at_all_changes_when_one_file_cannot_be_imported(folder, home):
    """Break: a new subject over an old lecture, or half of the new files - a state the owner cannot see and cannot explain."""
    old = Path(folder).parent / 'старое.txt'
    old.write_text('Старая лекция.', encoding='utf-8')
    import_materials([old], home)
    (home / 'materials' / 'echo_settings.json').write_text('{"subject": "Старый"}', encoding='utf-8')
    snapshot = {p.name: p.read_bytes() for p in (home / 'materials').iterdir()}
    put(folder, 'ТЕМА.txt', 'Предмет: Новый')
    put(folder, 'хорошая.txt', 'Хороший файл.')
    put(folder, 'плохая.pdf', b'scan')

    def extract(path):
        raise ValueError('No extractable text in плохая.pdf; nothing changed.')
    with pytest.raises(ValueError, match='плохая.pdf'):
        load_folder(folder, home, extract=extract, config=SAFE)
    assert {p.name: p.read_bytes() for p in (home / 'materials').iterdir()} == snapshot


def test_a_missing_folder_is_a_clear_error(tmp_path, home):
    with pytest.raises(ValueError, match='Папка'):
        load_folder(tmp_path / 'нет такой', home)


# --- what the script prints ---------------------------------------------------------------------------------------------------

def run_main(folder, home, **options):
    out = io.StringIO()
    code = folder_main([str(folder), '--home', str(home)], out=out, **options)
    return code, out.getvalue()


def test_the_script_says_in_plain_russian_what_was_loaded_and_when_it_takes_effect(folder, home):
    put(folder, 'ТЕМА.txt', 'Предмет: Налоговое право\nАудитория: студенты\n')
    put(folder, 'лекция.txt', 'Налог на добавленную стоимость.')
    put(folder, 'схема.png', b'\x89PNG')
    code, text = run_main(folder, home)
    call = load_call_context(home)
    assert code == 0
    source_hash = hashlib.sha256('Налог на добавленную стоимость.'.encode()).hexdigest()[:12]
    for expected in ('Налоговое право', 'студенты', 'лекция.txt', f'{len("Налог на добавленную стоимость.".encode())} байт',
                     f'sha256 {source_hash}', f'версия {call.material_sha256[:12]}', 'схема.png', 'со следующего звонка',
                     'перезапуск не нужен'):
        assert expected in text, expected
    assert 'Стиль: не задано' in text, 'a field the owner left out is said to be not set'


def test_a_long_material_is_announced_as_only_partly_shown_with_the_numbers(folder, home):
    put(folder, 'лекция.txt', ('Предложение про налоги. ' * 40 + '\n\n') * 60)
    code, text = run_main(folder, home)
    call = load_call_context(home)
    assert code == 0 and call.truncated and len(call.excerpt) <= MATERIAL_EXCERPT_CHARS
    assert f'{len(call.excerpt)} из {call.material_chars}' in text


def test_removed_material_is_announced_with_the_place_of_the_copy(folder, home):
    old = Path(folder).parent / 'старое.txt'
    old.write_text('Старая лекция.', encoding='utf-8')
    import_materials([old], home)
    put(folder, 'ТЕМА.txt', 'Химия')
    code, text = run_main(folder, home)
    assert code == 0 and 'убраны' in text and '.bak' in text


def test_a_failure_is_one_clear_message_with_a_nonzero_code_and_nothing_changed(folder, home):
    put(folder, 'ТЕМА.txt', 'Химия')
    put(folder, 'плохая.pdf', b'scan')

    def extract(path):
        raise ValueError('No extractable text in плохая.pdf; nothing changed.')
    code, text = run_main(folder, home, extract=extract, config=SAFE)
    assert code == 1
    assert 'ОШИБКА' in text and 'плохая.pdf' in text and 'ничего не изменено' in text.lower()
    assert not (home / 'materials').exists()


def test_when_only_the_topic_cannot_be_written_the_owner_is_not_told_that_nothing_changed(folder, home, monkeypatch):
    """Break: «Ничего не изменено» printed after the new lecture was already loaded - the owner then trusts a state that is not real."""
    def refuse(path, fields):
        raise PermissionError('settings file is locked')
    monkeypatch.setattr(materials, 'save_content_fields', refuse)
    put(folder, 'ТЕМА.txt', 'Химия')
    put(folder, 'лекция.txt', 'Сублимация.')
    code, text = run_main(folder, home)
    assert code == 1 and 'ОШИБКА' in text and 'Материалы загружены' in text and 'locked' in text
    assert 'Ничего не изменено' not in text
    assert 'Сублимация.' in load_call_context(home).excerpt


class ExtractionError(Exception):
    """Like tools.read_extract.ExtractionError of Hermes: not a ValueError, and its message does not name the file."""


def test_whatever_the_document_extractor_raises_the_owner_is_told_which_file_and_nothing_changes(folder, home):
    """Break (found by running the .cmd on a junk PDF): Hermes' own exception type escaped as a 25-line English traceback."""
    (home / 'materials').mkdir(parents=True)
    (home / 'materials' / 'echo_settings.json').write_text('{"subject": "Старый"}', encoding='utf-8')
    before = (home / 'materials' / 'echo_settings.json').read_bytes()
    put(folder, 'ТЕМА.txt', 'Предмет: Новый')
    put(folder, 'плохой.pdf', b'\x01\x02')

    def extract(path):
        raise ExtractionError('MalformedError: malformed document: not a PDF')
    with pytest.raises(ValueError) as caught:
        load_folder(folder, home, extract=extract, config=SAFE)
    assert 'плохой.pdf' in str(caught.value) and 'not a PDF' in str(caught.value)
    code, text = run_main(folder, home, extract=extract, config=SAFE)
    assert code == 1 and 'ОШИБКА' in text and 'плохой.pdf' in text and 'not a PDF' in text and 'Ничего не изменено' in text
    assert 'Traceback' not in text
    assert (home / 'materials' / 'echo_settings.json').read_bytes() == before and not (home / 'materials' / 'context.md').exists()


def test_an_unexpected_error_is_reported_with_its_type_and_without_claiming_that_nothing_changed(folder, home, monkeypatch):
    put(folder, 'лекция.txt', 'Текст.')

    def boom(*args, **kwargs):
        raise RuntimeError('boom')
    monkeypatch.setattr(materials, 'load_folder', boom)
    code, text = run_main(folder, home)
    assert code == 1 and 'RuntimeError' in text and 'boom' in text and 'Traceback' not in text
    assert 'Ничего не изменено' not in text


IMPORTER_REFUSALS = {
    'Combined context exceeds 180000 characters; nothing changed. Split materials explicitly.': '180000',
    'Material exceeds the 180000 character limit; nothing changed.': '180000',
    'Set file_tools.hosted_ocr: false in this Hermes profile before document extraction.': 'hosted_ocr',
    'Cannot verify file_tools.hosted_ocr: false; refusing document extraction.': 'hosted_ocr',
    'PDF/PPTX require the existing Hermes optional anydoc parser; use UTF-8 TXT/MD or DOCX instead. No packages were installed.': 'парсер',
    'OCR/text coverage is incomplete in скан.pdf; nothing changed.': 'скан',
    'No extractable text in пустой.pdf; nothing changed.': 'скан',
    'Source changed during extraction; nothing changed. Retry with a stable file.': 'менялся',
}


@pytest.mark.parametrize('refusal', list(IMPORTER_REFUSALS))
def test_the_importers_english_refusals_come_with_a_russian_explanation(folder, home, refusal):
    """Break: the owner (not a programmer) is left with «Combined context exceeds 180000 characters» and no idea what to do."""
    put(folder, 'файл.pdf', b'x')

    def extract(path):
        raise ValueError(refusal)
    code, text = run_main(folder, home, extract=extract, config=SAFE)
    assert code == 1 and 'ОШИБКА' in text and 'Что делать' in text
    assert IMPORTER_REFUSALS[refusal] in text.split('Что делать', 1)[1], text


def test_an_error_without_a_known_cause_gets_no_invented_advice(folder, home):
    put(folder, 'файл.pdf', b'x')

    def extract(path):
        raise ValueError('something nobody has seen')
    code, text = run_main(folder, home, extract=extract, config=SAFE)
    assert code == 1 and 'something nobody has seen' in text and 'Что делать' not in text


def test_an_error_message_does_not_end_in_two_full_stops(folder, home):
    put(folder, 'плохая.pdf', b'scan')

    def extract(path):
        raise ValueError('No extractable text in плохая.pdf; nothing changed.')
    assert '..' not in run_main(folder, home, extract=extract, config=SAFE)[1]


def test_a_missing_folder_gives_the_same_kind_of_message(tmp_path, home):
    code, text = run_main(tmp_path / 'нет такой', home)
    assert code == 1 and 'ОШИБКА' in text and 'Папка' in text


def test_the_main_hermes_is_never_written_to(tmp_path, folder, monkeypatch):
    """Break: LOCKED rule - the main Hermes (%LOCALAPPDATA%\\hermes) is not touched, by a script run in the wrong environment."""
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    main_home = tmp_path / 'local' / 'hermes'
    put(folder, 'ТЕМА.txt', 'Химия')
    put(folder, 'лекция.txt', 'Текст.')
    for target in (main_home, main_home / 'profiles' / 'echo-sync'):
        code, text = run_main(folder, target)
        assert code == 2 and 'основной Hermes' in text
        assert not target.exists()
    echo_home = tmp_path / 'local' / 'hermes-echo' / 'home' / 'profiles' / 'echo-sync'
    assert run_main(folder, echo_home)[0] == 0


def test_the_script_takes_the_profile_from_hermes_home_when_no_home_is_given(tmp_path, folder, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    profile = tmp_path / 'local' / 'hermes-echo' / 'home' / 'profiles' / 'echo-sync'
    monkeypatch.setenv('HERMES_HOME', str(profile))
    put(folder, 'лекция.txt', 'Текст.')
    out = io.StringIO()
    assert folder_main([str(folder)], out=out) == 0
    assert (profile / 'materials' / 'context.md').exists()


def test_with_no_profile_given_anywhere_the_script_refuses_to_guess(tmp_path, folder, monkeypatch):
    """Break: guessing Hermes' default home would be the MAIN Hermes."""
    monkeypatch.delenv('HERMES_HOME', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    put(folder, 'лекция.txt', 'Текст.')
    out = io.StringIO()
    assert folder_main([str(folder)], out=out) == 2
    assert 'профиль' in out.getvalue()
    assert not (tmp_path / 'local').exists()


# --- S4: a link is not followed out of the folder; a document is not unpacked past what a lesson's document holds ----------------

def link(path, target):
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('this machine cannot make a symbolic link')


def test_a_link_in_the_folder_to_a_file_of_someone_else_is_not_read_into_the_call(tmp_path, folder, home):
    """A shortcut to the profile's own secret file (here a stand-in) must not reach context.md, the subject or the prompt of the next call."""
    secret = tmp_path / 'profile_auth.txt'
    secret.write_text('КАНАРЕЙКА-ЧУЖОГО-ФАЙЛА-5521', encoding='utf-8')
    put(folder, 'лекция.txt', 'Свой текст лекции.')
    link(folder / 'ключи.txt', secret)
    link(folder / 'ТЕМА.txt', secret)
    result = load_folder(folder, home)
    assert result['links'] == ['ТЕМА.txt', 'ключи.txt'] and [item['name'] for item in result['files']] == ['лекция.txt']
    call = load_call_context(home)
    assert 'КАНАРЕЙКА' not in call.excerpt and 'КАНАРЕЙКА' not in call.subject and 'Свой текст лекции.' in call.excerpt
    assert 'КАНАРЕЙКА' not in (home / 'materials' / 'context.md').read_text(encoding='utf-8')
    assert 'ключи.txt' in materials.format_report(result)      # the owner is told which files were not taken


def test_a_source_that_is_a_link_is_refused_by_the_importer_itself(tmp_path, home):
    real = tmp_path / 'real.txt'
    real.write_text('Текст.', encoding='utf-8')
    link(tmp_path / 'shortcut.txt', real)
    with pytest.raises(ValueError, match='not a link'):
        import_materials([tmp_path / 'shortcut.txt'], home)


def packed(path, parts):
    import zipfile
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as package:
        for name, data in parts:
            package.writestr(name, data)
    return path


def test_a_document_that_unpacks_to_too_much_is_refused_before_anything_is_unpacked(tmp_path, home):
    bomb = packed(tmp_path / 'bomb.docx', [('word/document.xml', b'0' * (materials.MAX_UNPACKED_XML_BYTES + 1))])
    assert bomb.stat().st_size < 1_000_000      # a few KiB of the packed file are 40 MiB of text
    asked = []
    with pytest.raises(ValueError, match='may be a bomb'):
        import_materials([bomb], home, extract=lambda path: asked.append(path) or 'Текст', config=SAFE)
    assert asked == [] and not (home / 'materials' / 'context.md').exists()      # the extractor never ran; nothing changed
    many = packed(tmp_path / 'many.pptx', [(f'ppt/media/{n}.bin', b'') for n in range(materials.MAX_ZIP_MEMBERS + 1)])
    with pytest.raises(ValueError, match='may be a bomb'):
        import_materials([many], home, extract=lambda path: asked.append(path) or 'Текст', config=SAFE)
    assert asked == []


def test_an_ordinary_document_is_still_read(tmp_path, home):
    fine = packed(tmp_path / 'ok.docx', [('word/document.xml', '<w:t>Русский документ</w:t>'.encode('utf-8') * 1000)])
    result = import_materials([fine], home, extract=lambda path: 'Русский документ', config=SAFE)
    assert 'Русский документ' in result['path'].read_text(encoding='utf-8')
