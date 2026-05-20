import os
from pathlib import Path


SETTINGS_FILENAME = ".pgn_to_html_settings.json"
APP_DIRNAME = "PGN_To_HTML_2"


def get_user_config_dir():
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, APP_DIRNAME)

    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return os.path.join(config_home, APP_DIRNAME)

    return os.path.join(str(Path.home()), ".config", APP_DIRNAME)


def get_settings_path():
    return os.path.join(get_user_config_dir(), SETTINGS_FILENAME)


def get_legacy_settings_path(project_dir):
    return os.path.join(os.path.abspath(project_dir), SETTINGS_FILENAME)


def get_settings_load_candidates(project_dir):
    settings_path = get_settings_path()
    candidates = [settings_path]
    legacy_path = get_legacy_settings_path(project_dir)
    if os.path.abspath(legacy_path) != os.path.abspath(settings_path):
        candidates.append(legacy_path)
    return candidates


def ensure_settings_dir(settings_path):
    os.makedirs(os.path.dirname(os.path.abspath(settings_path)), exist_ok=True)
