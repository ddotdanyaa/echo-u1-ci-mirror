#!/usr/bin/env python3
"""Install one isolated Echo profile using an already installed Hermes CLI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

PROFILE = 'echo-sync'


def select_model(value):
    if not isinstance(value, dict) or value.get('provider') != 'openai-codex':
        raise ValueError('В текущем Hermes должен быть выбран OpenAI Codex через существующий OAuth. Платный API не используется.')
    if value.get('openai_runtime') == 'codex_app_server':
        raise ValueError('Codex app-server обходит контроллер. Для Echo нужен обычный маршрут openai-codex.')
    if not str(value.get('default') or '').strip():
        raise ValueError('В Hermes не выбрана модель.')
    return {'provider': 'openai-codex', 'default': value['default'],
            'openai_runtime': 'auto', 'streaming': False}


def profile_config(model):
    return {
        'model': select_model(model), 'fallback_model': [],
        'plugins': {'enabled': ['echo-sync']},
        'platform_toolsets': {'cli': []}, 'mcp_servers': {},
        'file_tools': {'hosted_ocr': False},
        'compression': {'enabled': False},
        'memory': {'memory_enabled': False, 'user_profile_enabled': False, 'nudge_interval': 0},
        'auxiliary': {'background_review': {'enabled': False}, 'title_generation': {'enabled': False}},
        'tts': {'provider': 'echo_sapi'},      # the plugin's own provider (echo_sync/sapi_provider.py): the profile's resident SAPI worker, no command script
    }


def write_new_profile(profile, config, bundle):
    profile, bundle = Path(profile), Path(bundle)
    if profile.exists():
        raise FileExistsError('Профиль уже существует; его файлы не изменены: ' + str(profile))
    profile.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.echo-stage-', dir=profile.parent) as tmp:
        stage = Path(tmp) / profile.name
        stage.mkdir()
        (stage / 'config.yaml').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        (stage / '.no-bundled-skills').write_text('', encoding='utf-8')
        (stage / 'SOUL.md').write_text('Голосовой тренировочный суфлёр. Управление последовательностью выполняет программный контроллер.\n', encoding='utf-8')
        shutil.copytree(bundle / 'echo_sync', stage / 'plugins' / 'echo-sync', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        materials = stage / 'materials'
        materials.mkdir()
        qa = [{'question': 'Что такое финансовая система Российской Федерации?',
               'answer': 'Финансовая система Российской Федерации представляет собой совокупность взаимосвязанных сфер финансовых отношений.'},
              {'question': 'Что такое фотосинтез?',
               'answer': 'Фотосинтез позволяет растениям превращать световую энергию в химическую энергию органических веществ.'}]
        (materials / 'qa.json').write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding='utf-8')
        (materials / 'context.md').write_text('# Учебные материалы\n\nДобавьте сюда проверенный текст конспекта. Этот файл используется при генерации новых ответов.\n', encoding='utf-8')
        stage.rename(profile)


def cli(*args):
    executable = shutil.which('hermes')
    if not executable:
        raise RuntimeError('Hermes не найден. Запустите установку в том терминале, где уже работает команда hermes.')
    result = subprocess.run([executable, *map(str, args)], text=True, encoding='utf-8',
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    if result.returncode:
        raise RuntimeError('Команда Hermes не выполнена: ' + ' '.join(map(str, args)) + '\n' + result.stderr[-2000:] + '\n' + result.stdout[-2000:])
    return result.stdout


def parse_profile_path(output):
    clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', output)
    match = re.search(r'^Path:\s*(.+?)\s*$', clean, re.MULTILINE)
    if not match:
        raise ValueError('Не удалось получить путь профиля из установленного Hermes; установка остановлена.')
    path = Path(match.group(1)).expanduser()
    if not path.is_absolute():
        raise ValueError('Hermes вернул не абсолютный путь профиля; установка остановлена.')
    return path.resolve()


def preserve_failed_profile(profile):
    destination = profile.with_name('.echo-sync-failed-' + uuid.uuid4().hex[:12])
    profile.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-root', type=Path, help='Папка существующего исходного кода Hermes; определяется автоматически, если доступна')
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    model = select_model(json.loads(cli('config', 'get', 'model', '--json')))
    # Ask the installed host: native Windows uses LOCALAPPDATA, WSL/custom
    # deployments have other roots. A guessed ~/.hermes can be invisible.
    root = parse_profile_path(cli('profile', 'show', 'default'))
    profile = root / 'profiles' / PROFILE
    if profile.exists():
        raise FileExistsError('Профиль уже существует; ничего не изменено: ' + str(profile))
    # Check actual offline synthesis BEFORE creating a profile or changing Hermes.
    sys.path.insert(0, str(bundle))      # the bundle's own package: the same resident worker the profile will use
    from echo_sync.sapi_worker import SapiWorkerManager
    worker = SapiWorkerManager('install-check')
    try:
        with tempfile.TemporaryDirectory(prefix='echo-check-') as tmp:
            probe = Path(tmp) / 'probe.wav'
            voice = worker.synthesize('Проверка русского голоса.', str(probe))
            print('Русская офлайн-озвучка проверена: ' + str(voice))
    finally:
        worker.close()
    config = profile_config(model)
    write_new_profile(profile, config, bundle)
    # The narrow, version-guarded host patch is part of this package. Never
    # update/reinstall Hermes implicitly and never publish a dashboard port.
    from host_patch import apply_patch, rollback_patch
    hermes_root = args.hermes_root
    result = None
    try:
        if hermes_root is None:
            info = json.loads(cli('-p', PROFILE, 'echo-host-info'))
            hermes_root = Path(info['hermes_root'])
            config = profile_config(model)
            (profile / 'config.yaml').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        # Admission first: a bad plugin must not change the shared source.
        print(cli('-p', PROFILE, 'plugins', 'doctor', str(profile / 'plugins' / 'echo-sync'), '--ci'))
        result = apply_patch(hermes_root, profile)
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        if result is not None and result['status'] == 'applied':
            rollback_patch(hermes_root, profile)
        elif result is not None:
            (profile / 'echo-sync' / 'allow_silence').unlink(missing_ok=True)
        saved = preserve_failed_profile(profile)
        print('Новый незавершённый профиль сохранён для диагностики: ' + str(saved), file=sys.stderr)
        raise
    print('Установка подготовлена. Перезапустите существующий Hermes dashboard; выберите профиль echo-sync в Conduit. Проверка iPhone ещё требуется.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('НЕ ГОТОВО: ' + str(exc), file=sys.stderr)
        sys.exit(1)
