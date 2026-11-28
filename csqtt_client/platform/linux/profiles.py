"""Per-user config.json storage with restrictive Linux file permissions."""
from dataclasses import asdict
import json
import os
from pathlib import Path

from csqtt_client.config import CONFIG_DIR, CONFIG_JSON, PROFILE, LEGACY_PROFILE
from csqtt_client.models.profile import Profile

_FORMAT = "csqtt-desktop-config"
_VERSION = 1


def _write_json(path: Path, payload):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass
    temp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _decode_config(raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("config.json должен содержать JSON-объект.")
    if data.get("format") == _FORMAT:
        if data.get("version") != _VERSION:
            raise ValueError(f"Неподдерживаемая версия config.json: {data.get('version')}")
        values = data.get("profile")
        if not isinstance(values, dict):
            raise ValueError("В config.json отсутствует профиль.")
    else:
        values = data.get("profile") if isinstance(data.get("profile"), dict) else data
    return Profile(**{k: v for k, v in values.items() if k in Profile.__dataclass_fields__})


def save_profile(profile):
    """Atomically persist the editable profile to owner-only config.json."""
    values = asdict(profile)
    payload = {
        "format": _FORMAT,
        "version": _VERSION,
        "platform": "linux-user-file",
        "profile": values,
        "_security": "Секреты хранятся в этом файле открытым текстом; доступ ограничен правами 600.",
    }
    _write_json(CONFIG_JSON, payload)


def _load_legacy(path):
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Profile(**{k: v for k, v in data.items() if k in Profile.__dataclass_fields__})


def load_profile():
    if CONFIG_JSON.exists():
        return _decode_config(CONFIG_JSON.read_text(encoding="utf-8"))
    for source in (PROFILE, LEGACY_PROFILE):
        profile = _load_legacy(source)
        if profile is not None:
            save_profile(profile)
            return profile
    return Profile()


def profile_exists():
    return CONFIG_JSON.exists() or PROFILE.exists() or LEGACY_PROFILE.exists()


def delete_profile():
    for path in (CONFIG_JSON, PROFILE, LEGACY_PROFILE):
        path.unlink(missing_ok=True)
