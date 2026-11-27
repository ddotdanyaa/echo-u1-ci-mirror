"""Bounded local material import using Hermes's existing document parser; no LLM."""
import importlib.util
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
import zipfile

from .settings import SETTINGS_FILE, TEXT_LIMITS, environment, save_content_fields

MAX_CHARS = 180000
DOCUMENTS = {'.pdf', '.docx', '.pptx'}
MAX_SOURCE_BYTES = 50 * 1024 * 1024
# S4: a .docx / .pptx is a zip; its text is read by unpacking parts of it. What it declares to unpack to is checked before anything is unpacked (a bomb of 50 MiB packed can unpack to gigabytes).
MAX_UNPACKED_BYTES = 200 * 1024 * 1024      # all the parts together
MAX_UNPACKED_XML_BYTES = 40 * 1024 * 1024   # the text parts (.xml, .rels): 180 000 characters of material are a few MiB of them
MAX_ZIP_MEMBERS = 10000
MANIFEST_PREFIX = '<!-- ECHO_MATERIALS_V1 '
# What install_echo.py writes into a new profile's context.md: a note to the owner, not a material.
PLACEHOLDER_CONTEXT = '# Учебные материалы\n\nДобавьте сюда проверенный текст конспекта. Этот файл используется при генерации новых ответов.\n'


def material_body(content):
    """The text of a context file without the one-line manifest header the importer puts in front of it (a legacy file has none).

    Call it on what ``read_material_context`` returned: that is where the header has been verified.
    """
    if content.startswith(MANIFEST_PREFIX):
        return content.split('\n', 1)[1] if '\n' in content else ''
    return content


_BLANK_RUN = re.compile(r'\n[ \t]*(?:\n[ \t]*){2,}')


def squeeze_blank_lines(text):
    """``text`` with every run of empty lines reduced to one (and line ends made ``\\n``): what a call is shown and what the report
    counts, so the two cannot differ. A converted DOCX or PDF is full of such runs and they would spend the excerpt on nothing."""
    return _BLANK_RUN.sub('\n\n', text.replace('\r\n', '\n').replace('\r', '\n'))


def _manifest_digest(manifest):
    protected = {key: value for key, value in manifest.items() if key != 'manifest_hash'}
    canonical = json.dumps(protected, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def read_material_context(path):
    """Read legacy context, or verify the embedded v1 content manifest.

    Provenance and text share one atomic file replacement: there is no interval
    with a new context and an old sidecar. Hashes detect accidental corruption;
    they do not authenticate an author or prove factual correctness.
    """
    content = Path(path).read_text(encoding='utf-8-sig')
    if not content.startswith(MANIFEST_PREFIX):
        return content
    try:
        header, body = content.split('\n', 1)
        if not header.endswith(' -->'):
            raise ValueError('Invalid manifest delimiter')
        manifest = json.loads(header[len(MANIFEST_PREFIX):-4])
        if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1 \
                or not isinstance(manifest.get('sources'), list) or not manifest['sources']:
            raise ValueError('Invalid manifest schema')
        if _manifest_digest(manifest) != manifest.get('manifest_hash'):
            raise ValueError('Manifest digest mismatch')
        for source in manifest['sources']:
            if not isinstance(source, dict):
                raise ValueError('Invalid source entry')
            digest = source.get('source_hash')
            extracted = source.get('extracted_text_hash')
            if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) \
                    or not isinstance(extracted, str) or not re.fullmatch('[0-9a-f]{64}', extracted) \
                    or source.get('material_id') != 'sha256:' + digest \
                    or source.get('source_uri') != 'urn:sha256:' + digest \
                    or source.get('format') not in {'txt', 'md', 'pdf', 'docx', 'pptx'} \
                    or not isinstance(source.get('source_name'), str) or not source['source_name'] \
                    or type(source.get('characters')) is not int or source['characters'] < 1:
                raise ValueError('Invalid source metadata')
        if hashlib.sha256(body.encode('utf-8')).hexdigest() != manifest.get('context_hash'):
            raise ValueError('Context digest mismatch')
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Material integrity check failed; re-import the source files.') from exc
    return content


def _publish_context(home, content, *, copy_old=lambda path: True):
    """Make ``content`` the profile's materials/context.md in one step (a reader sees the old file or the new one, never half).

    The file it replaces is first copied to ``context.md.<id>.bak`` when ``copy_old(path)`` says so.
    Returns ``(path, backup path or None)``.
    """
    dest = Path(home).expanduser().resolve() / 'materials' / 'context.md'
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix='.context-', suffix='.md', dir=dest.parent)
    backup = None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if dest.exists() and copy_old(dest):
            backup = dest.with_name(f'context.md.{uuid.uuid4().hex}.bak')
            shutil.copy2(dest, backup)
        os.replace(pending, dest)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    return dest, backup


def _file_hash(path):
    """sha256 of a file, read in blocks (S4: a source of 50 MiB was read whole into memory three times)."""
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def check_unpack(path):
    """S4: refuse a .docx / .pptx whose zip declares more parts or more unpacked bytes than a lesson's document can have; nothing is unpacked here. A file that is no zip is the extractor's to refuse."""
    try:
        if not zipfile.is_zipfile(path):
            return
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError(f'{Path(path).name}: the document cannot be opened as a package ({type(error).__name__}); nothing changed.') from error
    total = sum(item.file_size for item in members)
    text = sum(item.file_size for item in members if item.filename.lower().endswith(('.xml', '.rels')))
    if len(members) > MAX_ZIP_MEMBERS or total > MAX_UNPACKED_BYTES or text > MAX_UNPACKED_XML_BYTES:
        raise ValueError(f'{Path(path).name} unpacks to {len(members)} parts, {total // (1024 * 1024)} MiB ({text // (1024 * 1024)} MiB of text parts): '
                         'more than a document of a lesson has (it may be a bomb); nothing changed.')


def inside(folder, path):
    """S4: ``path`` is a regular file that lies in ``folder`` itself: not a link (a shortcut to a file of someone else, say the profile's auth.json), and its real place is under the real ``folder``."""
    path = Path(path)
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        return False
    try:
        base, real = os.path.realpath(folder), os.path.realpath(path)
        return os.path.normcase(os.path.commonpath([base, real])) == os.path.normcase(base)
    except ValueError:      # another drive
        return False


def _host_extract(path):
    if path.suffix.lower() in {'.pdf', '.pptx'} and importlib.util.find_spec('anydoc') is None:
        raise ValueError('PDF/PPTX require the existing Hermes optional anydoc parser; use UTF-8 TXT/MD or DOCX instead. No packages were installed.')
    from tools.read_extract import extract_document_text
    return extract_document_text(str(path))


def _safe_config():
    from hermes_cli.config import load_config_readonly
    return load_config_readonly()


def import_materials(files, home, *, extract=None, config=None):
    """Replace context only after every source has converted and passed its budget."""
    if not files:
        raise ValueError('Provide at least one local file.')
    parts, sources = [], []
    for source in files:
        if Path(source).expanduser().is_symlink():
            raise ValueError('Each source must be a regular file, not a link to another place.')
        path = Path(source).expanduser().resolve(strict=True)
        if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('Each source must be a regular file no larger than 50 MiB.')
        source_hash = _file_hash(path)
        suffix = path.suffix.lower()
        if suffix in {'.txt', '.md'}:
            if path.stat().st_size > MAX_CHARS * 4 + 4:
                raise ValueError('Material exceeds the 180000 character limit; nothing changed.')
            data = path.read_bytes()
            body = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        elif suffix in DOCUMENTS:
            try:
                settings = (config or _safe_config)()
                safe = isinstance(settings, dict) and isinstance(settings.get('file_tools'), dict) and settings['file_tools'].get('hosted_ocr') is False
            except Exception as exc:
                raise ValueError('Cannot verify file_tools.hosted_ocr: false; refusing document extraction.') from exc
            if not safe:
                raise ValueError('Set file_tools.hosted_ocr: false in this Hermes profile before document extraction.')
            check_unpack(path)
            body = (extract or _host_extract)(path)
        else:
            raise ValueError('Supported files: TXT, MD, DOCX; PDF/PPTX with existing optional parser.')
        if not isinstance(body, str) or not body.strip():
            raise ValueError(f'No extractable text in {path.name}; nothing changed.')
        body = body.replace('\r\n', '\n').replace('\r', '\n')
        if '[NEEDS OCR' in body or '[EXTRACTION COVERAGE WARNING' in body:
            raise ValueError(f'OCR/text coverage is incomplete in {path.name}; nothing changed.')
        if _file_hash(path) != source_hash:
            raise ValueError('Source changed during extraction; nothing changed. Retry with a stable file.')
        sources.append({'material_id': 'sha256:' + source_hash, 'source_name': path.name,
                        'source_uri': 'urn:sha256:' + source_hash, 'source_hash': source_hash,
                        'extracted_text_hash': hashlib.sha256(body.strip().encode('utf-8')).hexdigest(),
                        'format': suffix[1:], 'characters': len(body.strip())})
        parts.append(f'# Source: {path.name}\n\n{body.strip()}\n')
        if sum(map(len, parts)) + 2 * (len(parts) - 1) > MAX_CHARS:
            raise ValueError('Combined context exceeds 180000 characters; nothing changed. Split materials explicitly.')
    content = '\n\n'.join(parts)
    manifest = {'schema_version': 1, 'updated_at': datetime.now(timezone.utc).isoformat(),
                'context_hash': hashlib.sha256(content.encode('utf-8')).hexdigest(), 'sources': sources}
    manifest['manifest_hash'] = _manifest_digest(manifest)
    content = MANIFEST_PREFIX + json.dumps(manifest, ensure_ascii=False, separators=(',', ':')) + ' -->\n' + content
    if len(content) > MAX_CHARS:
        raise ValueError('Combined context and provenance exceed 180000 characters; nothing changed.')
    dest, backup = _publish_context(home, content)
    return {'files': len(files), 'characters': len(content), 'path': dest, 'backup': backup, 'manifest': manifest}


def add_arguments(parser):
    parser.add_argument('files', nargs='+', help='Local TXT/MD/DOCX or PDF/PPTX sources')


def run_cli(args):
    from hermes_constants import get_hermes_home
    result = import_materials(args.files, get_hermes_home())
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, ensure_ascii=False))


# --- the owner's folder (CL1): U1\МАТЕРИАЛЫ\ТЕМА.txt + the files, loaded by U1\ЗАГРУЗИТЬ_МАТЕРИАЛЫ.cmd -------------------------------

TOPIC_FILE = 'ТЕМА.txt'
FOLDER_SUFFIXES = ('.txt', '.md', '.docx', '.pdf', '.pptx')          # what import_materials can read
_JUNK_NAMES = frozenset({'desktop.ini', 'thumbs.db'})
# The labels a line of ТЕМА.txt may start with (compared in lower case, ё = е).
_LABELS = {'subject': ('предмет', 'тема', 'дисциплина', 'subject', 'topic'),
           'audience': ('аудитория', 'слушатели', 'кто слушает', 'роли', 'audience'),
           'style': ('стиль', 'манера', 'style')}
_LABEL_OF = {label: key for key, labels in _LABELS.items() for label in labels}
_LABELLED = re.compile(r'^([^:=：]{1,30}?)\s*[:=：]\s*(.*)$')
_FIELD_NAMES = {'subject': 'Предмет', 'audience': 'Аудитория', 'style': 'Стиль'}


class PartialLoad(Exception):
    """The materials were replaced but the topic could not be written: the owner is told exactly that, not "nothing changed"."""


def parse_topic(text):
    """The subject, audience and style written in ТЕМА.txt: ``{key: value}`` for the keys the text mentions (an empty value
    means "not set").

    ``Предмет: ...`` / ``Аудитория: ...`` / ``Стиль: ...`` (Russian or English label, any case) are taken by their label. Other
    lines fill the keys no label gave, in the order subject, audience, style. Empty lines are skipped; ``#``, ``;`` and ``//``
    start a comment; lines left over are ignored; of a repeated label the last wins.
    """
    given, plain = {}, []
    for raw in str(text).splitlines():
        line = raw.strip().lstrip(chr(0xFEFF))
        if not line or line.startswith(('#', ';', '//')):
            continue
        match = _LABELLED.match(line)
        key = _LABEL_OF.get(match[1].strip().casefold().replace('ё', 'е')) if match else None
        if key:
            given[key] = match[2].strip()
        else:
            plain.append(line)
    spare = iter(plain)
    for key in _FIELD_NAMES:
        if key not in given:
            value = next(spare, None)
            if value is None:
                break
            given[key] = value
    return {key: given[key] for key in _FIELD_NAMES if key in given}


def read_topic(path):
    """``parse_topic`` of a ТЕМА.txt as the owner saved it: UTF-16 (Notepad "Unicode"), UTF-8 with or without a mark, or the
    Windows Cyrillic code page."""
    data = Path(path).read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = data.decode('utf-16')
    else:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('cp1251', errors='replace')
    return parse_topic(text)


def clear_materials(home):
    """Replace the imported material by the installer's placeholder, i.e. "no material". The old file is first copied to
    ``context.md.<id>.bak`` unless it already was the placeholder (or missing). Returns ``{'path', 'backup'}``."""
    def worth_a_copy(path):
        try:
            return ' '.join(path.read_text(encoding='utf-8-sig').split()) != ' '.join(PLACEHOLDER_CONTEXT.split())
        except (OSError, UnicodeError):
            return True
    dest, backup = _publish_context(home, PLACEHOLDER_CONTEXT, copy_old=worth_a_copy)
    return {'path': dest, 'backup': backup}


def _named_extract(extract):
    """The document extractor, made to fail the way the importer reports failures: a ValueError that says WHICH file. Hermes'
    own extractor raises its own exception types whose messages do not name the file (and a stack trace is no message for the owner)."""
    call = extract or _host_extract

    def run(path):
        try:
            return call(path)
        except Exception as error:
            message = str(error) or type(error).__name__
            raise ValueError(message if path.name in message else f'{path.name}: {message}') from error
    return run


def load_folder(folder, home, *, extract=None, config=None):
    """Make the profile ``home`` hold exactly what is in ``folder``: ТЕМА.txt (if there is one) becomes the subject, audience
    and style of ``materials/echo_settings.json`` (other keys untouched; an empty line removes its key), every .txt / .md /
    .docx / .pdf / .pptx file goes through ``import_materials`` into ``materials/context.md`` (sorted by name), and a folder with no
    such file clears the material (the old one is kept as a .bak). The materials come first and are all-or-nothing: when a file
    cannot be imported, nothing at all has changed. Returns a dict of what was done, for ``format_report``."""
    folder, home = Path(folder), Path(home).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f'Папка не найдена: {folder}')
    found = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
    entries = [p for p in found if inside(folder, p)]
    links = [p.name for p in found if p not in entries and not p.name.startswith('.')]      # S4: a link is not followed out of the folder; the owner is told
    topic_path = next((p for p in entries if p.name.casefold() == TOPIC_FILE.casefold()), None)
    files, skipped = [], []
    for path in entries:
        if path == topic_path or path.name.startswith(('.', '~$')) or path.name.casefold() in _JUNK_NAMES:
            continue
        (files if path.suffix.lower() in FOLDER_SUFFIXES else skipped).append(path)
    topic = read_topic(topic_path) if topic_path else None
    context = cleared = saved = None
    report = []
    if files:
        imported = import_materials(files, home, extract=_named_extract(extract), config=config)
        body = squeeze_blank_lines(material_body(read_material_context(imported['path']))).strip()
        context = {'path': imported['path'], 'sha256': imported['manifest']['context_hash'], 'chars': len(body),
                   'backup': imported['backup']}
        report = [{'name': path.name, 'bytes': path.stat().st_size, 'chars': source['characters'], 'sha256': source['source_hash']}
                  for path, source in zip(files, imported['manifest']['sources'])]
    else:
        cleared = clear_materials(home)
    if topic is not None:
        try:
            saved = save_content_fields(home / 'materials' / SETTINGS_FILE, {key: topic.get(key, '') for key in TEXT_LIMITS})
        except OSError as error:
            raise PartialLoad(f'Материалы загружены, но тему записать не удалось ({error}). Запустите загрузку ещё раз.') from error
    return {'folder': folder, 'home': home, 'topic_file': topic_path, 'topic': topic, 'files': report, 'skipped': [p.name for p in skipped],
            'context': context, 'cleared': cleared, 'settings': saved, 'links': links}


def plural(count, one, few, many):
    """The Russian form of a unit after a number: 1 файл, 2 файла, 5 файлов, 11 файлов, 21 файл."""
    tail = abs(int(count)) % 100
    if 11 <= tail <= 14:
        return many
    return one if tail % 10 == 1 else few if 2 <= tail % 10 <= 4 else many


def _units(count, one, few, many):
    return f'{count} {plural(count, one, few, many)}'


def format_report(result):
    """What the owner is told after a load: the topic, every file with its size and hash, and what the next call will receive."""
    from .content_policy import load_call_context
    lines = [f'Папка: {result["folder"]}', f'Профиль: {result["home"]}', '']
    if result['topic'] is None:
        lines.append(f'{TOPIC_FILE} не найден: предмет, аудитория и стиль не менялись.')
    else:
        lines.append(f'{TOPIC_FILE}:')
        lines += [f'  {label}: {result["topic"].get(key) or "не задано"}' for key, label in _FIELD_NAMES.items()]
    lines.append('')
    if result['files']:
        lines.append('Материалы:')
        for number, item in enumerate(result['files'], 1):
            lines.append(f'  {number}. {item["name"]} - {_units(item["bytes"], "байт", "байта", "байт")}, '
                         f'{_units(item["chars"], "знак", "знака", "знаков")}, sha256 {item["sha256"][:12]}')
        context = result['context']
        lines.append(f'Загружено: {_units(len(result["files"]), "файл", "файла", "файлов")}, '
                     f'{_units(context["chars"], "знак", "знака", "знаков")}, версия {context["sha256"][:12]}.')
        call = load_call_context(result['home'])
        if call.excerpt:
            lines.append(f'В звонок попадёт: {len(call.excerpt)} из {call.material_chars} знаков'
                         + (' (начало; остальное не вмещается).' if call.truncated else ' (целиком).'))
    else:
        backup = result['cleared']['backup']
        lines.append('Файлов материалов в папке нет: прежние материалы убраны'
                     + (f' (копия: {backup}).' if backup else ' (прежних материалов не было).'))
    if result['skipped']:
        lines.append('Не загружены (такой формат не читается): ' + ', '.join(result['skipped']))
    if result.get('links'):
        lines.append('Не загружены (это ссылки на файлы вне папки, по ним не ходим; положите сами файлы): ' + ', '.join(result['links']))
    lines += ['', 'Действует со следующего звонка, перезапуск не нужен.']
    return '\n'.join(lines)


# The importer's refusals are English sentences for a programmer. For the ones an owner can meet, what to do about it.
_ADVICE = (
    ('180000', 'Материалов слишком много: предел - 180000 знаков на всё вместе. Оставьте в папке только нужное или разделите по занятиям.'),
    ('hosted_ocr', 'В профиле ECHO должно быть file_tools.hosted_ocr: false (облачное распознавание выключено). Для .txt и .md это не нужно, '
                   'для .docx, .pdf и .pptx нужно: сообщите помощнику, он проверит настройку.'),
    ('anydoc', 'Для PDF и PPTX в ECHO нужен парсер anydoc, а его нет. Возьмите .txt, .md или .docx.'),
    ('OCR/text coverage', 'В файле нет читаемого текста (похоже на скан). Нужен PDF с текстом или текстовый файл.'),
    ('No extractable text', 'В файле нет читаемого текста (похоже на скан). Нужен PDF с текстом или текстовый файл.'),
    ('may be a bomb', 'В документе слишком много частей или он распаковывается в слишком большой объём. Сохраните его заново или возьмите .txt / .md.'),
    ('Source changed during extraction', 'Файл менялся, пока его читали. Закройте его в других программах и запустите загрузку ещё раз.'),
)


def explain(message):
    """What to do about an importer refusal, in Russian; ``''`` for a message nobody has a known remedy for."""
    return next((advice for marker, advice in _ADVICE if marker in message), '')


def _is_main_hermes(home):
    """True for the main Hermes (%LOCALAPPDATA%\\hermes and everything under it): the ECHO copy lives in hermes-echo."""
    local = environment('LOCALAPPDATA')
    if not local:
        return False
    main = os.path.normcase(os.path.realpath(os.path.join(local, 'hermes')))
    here = os.path.normcase(os.path.realpath(str(home)))
    return here == main or here.startswith(main + os.sep)


def folder_main(argv=None, *, extract=None, config=None, out=None):
    """Entry of ЗАГРУЗИТЬ_МАТЕРИАЛЫ.cmd: ``<folder> [--home <profile home>]`` (the profile is HERMES_HOME of the environment when
    --home is not given). Prints what was loaded in plain Russian; the exit code is 0 for success, 1 when nothing could be loaded
    (and nothing changed), 2 when the profile is missing or is the main Hermes."""
    import argparse
    parser = argparse.ArgumentParser(prog='ЗАГРУЗИТЬ_МАТЕРИАЛЫ', description='Загрузить тему (ТЕМА.txt) и материалы из папки в профиль ECHO.')
    parser.add_argument('folder', help='папка с ТЕМА.txt и файлами материалов')
    parser.add_argument('--home', help='папка профиля ECHO (по умолчанию HERMES_HOME)')
    args = parser.parse_args(argv)
    out = out if out is not None else sys.stdout
    if hasattr(out, 'reconfigure'):
        try:
            out.reconfigure(encoding='utf-8', errors='replace')
        except (OSError, ValueError):
            pass

    def say(text):
        print(text, file=out)
    home = args.home or environment('HERMES_HOME')
    if not home:
        say('ОШИБКА: не указан профиль ECHO (HERMES_HOME). Ничего не изменено.')
        return 2
    if _is_main_hermes(home):
        say('ОШИБКА: это основной Hermes, его нельзя менять. Нужен профиль ECHO (hermes-echo\\home\\profiles\\echo-sync). Ничего не изменено.')
        return 2
    try:
        result = load_folder(args.folder, home, extract=extract, config=config)
    except PartialLoad as error:
        say(f'ОШИБКА: {error}')
        return 1
    except (ValueError, OSError) as error:
        say(f'ОШИБКА: {str(error).rstrip(". ")}. Ничего не изменено.')
        if explain(str(error)):
            say('Что делать: ' + explain(str(error)))
        return 1
    except Exception as error:
        # A bug, not a problem with the owner's files: no promise that nothing changed, and no stack trace for the owner.
        say(f'ОШИБКА (непредвиденная): {type(error).__name__}: {error}. Проверьте, что загружено, и сообщите об этом.')
        return 1
    say(format_report(result))
    return 0
