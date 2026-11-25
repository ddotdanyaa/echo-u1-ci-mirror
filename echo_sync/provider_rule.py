"""The ONE rule of which model road ECHO may take: the existing official Codex OAuth, never a paid API.

Read by the installer (``install_echo.select_model``: the profile it writes), by the plugin hook (``plugin.execute``: the road of a turn) and by the generator (the endpoint of the
credentials it resolves). No imports of the package: the installer loads this file by its path, before the package is installed anywhere.
"""
from urllib.parse import urlsplit

PROVIDER = 'openai-codex'
API_MODE = 'codex_responses'
BYPASS_RUNTIME = 'codex_app_server'      # the Codex app-server walks around the controller: never


def official_codex(url):
    """The official subscription endpoint, https://chatgpt.com/backend-api/codex, and no other address."""
    try:
        p = urlsplit(str(url or ''))
        return p.scheme == 'https' and p.hostname == 'chatgpt.com' and p.port in (None, 443) and p.path.rstrip('/') == '/backend-api/codex' and not p.username and not p.password
    except ValueError:
        return False


def road_allowed(provider, api_mode):
    """A turn at run time: the provider and the API mode of the one road."""
    return provider == PROVIDER and api_mode == API_MODE


def refusal(value):
    """The model chosen in Hermes at install time: None when it may be used, else the sentence that says why not."""
    if not isinstance(value, dict) or value.get('provider') != PROVIDER:
        return 'В текущем Hermes должен быть выбран OpenAI Codex через существующий OAuth. Платный API не используется.'
    if value.get('openai_runtime') == BYPASS_RUNTIME:
        return 'Codex app-server обходит контроллер. Для Echo нужен обычный маршрут openai-codex.'
    if not str(value.get('default') or '').strip():
        return 'В Hermes не выбрана модель.'
    return None
