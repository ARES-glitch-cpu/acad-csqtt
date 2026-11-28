"""Per-user config.json storage with DPAPI protection for sensitive fields."""
import base64
import ctypes
from ctypes import wintypes
from dataclasses import asdict
import json
import os

from csqtt_client.config import CONFIG_DIR, CONFIG_JSON, PROFILE, LEGACY_PROFILE
from csqtt_client.models.profile import Profile


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


_SECRET_FIELDS = {
    "password",
    "proxy_user",
    "proxy_password",
    "hashes",
    "salt",
    "share_link",
    "client_password",
}
_FORMAT = "csqtt-desktop-config"
_VERSION = 1


def dpapi(value: bytes, decrypt=False):
    """Encrypt/decrypt bytes for the current Windows account."""
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), "CSQTT config.json", None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def _decode_config(raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("config.json должен содержать JSON-объект.")
    # Portable/importable JSON export format.
    if data.get("format") != _FORMAT:
        if isinstance(data.get("profile"), dict):
            data = data["profile"]
        return Profile(**{k: v for k, v in data.items() if k in Profile.__dataclass_fields__})
    if data.get("version") != _VERSION:
        raise ValueError(f"Неподдерживаемая версия config.json: {data.get('version')}")
    values = data.get("profile", {})
    secrets = data.get("protected", {})
    if not isinstance(values, dict) or not isinstance(secrets, dict):
        raise ValueError("Структура config.json повреждена.")
    for key, encoded in secrets.items():
        if key in _SECRET_FIELDS and isinstance(encoded, str):
            values[key] = dpapi(base64.b64decode(encoded, validate=True), decrypt=True).decode("utf-8")
    return Profile(**{k: v for k, v in values.items() if k in Profile.__dataclass_fields__})


def save_profile(profile):
    """Atomically save all settings to a JSON file; protect secrets with Windows DPAPI."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    values = asdict(profile)
    protected = {}
    for key in _SECRET_FIELDS:
        if key in values:
            raw = str(values.pop(key)).encode("utf-8")
            protected[key] = base64.b64encode(dpapi(raw)).decode("ascii")
    payload = {
        "format": _FORMAT,
        "version": _VERSION,
        "platform": "windows-dpapi",
        "profile": values,
        "protected": protected,
    }
    temp = CONFIG_JSON.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, CONFIG_JSON)


def _load_legacy(path):
    if not path.exists():
        return None
    if path.suffix == ".dat":
        data = json.loads(dpapi(path.read_bytes(), decrypt=True))
    else:
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
