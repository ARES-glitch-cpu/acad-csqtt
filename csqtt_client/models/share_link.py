"""Parse CSQTT share links issued by server panels.

Supports encrypted CSQTT 2.5.0 links, their plaintext-base64 fallback,
the explicit connect?v=2 form, and the legacy password@host:port form.
Secrets are never included in exception text.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import unquote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from csqtt_client.models.profile import normalize_hashes

_SCHEME = "csqtt://"
_CIPHER_SEED = b"csqtt-chiper-key"
_NONCE_SIZE = 12
_CONNECT_PREFIX = b"connect?"
_KNOWN_KEYS = {"v", "host", "peer", "password", "hashes", "token"}


@dataclass(frozen=True)
class ShareLink:
    server: str
    password: str
    hashes: tuple[str, ...]


def parse_csqtt_link(value: str) -> ShareLink:
    """Decode a CSQTT link without exposing its contents in errors."""
    text = (value or "").strip()
    lowered = text.lower()
    if not lowered.startswith(_SCHEME):
        raise ValueError("Ссылка должна начинаться с csqtt://.")
    if lowered.count(_SCHEME) != 1:
        raise ValueError("Вставлена не одна ссылка CSQTT. Вставьте ссылку целиком один раз.")
    rest = text[len(_SCHEME):].strip()
    if not rest or "#" in rest:
        raise ValueError("Ссылка CSQTT пустая или повреждена.")

    if rest.lower().startswith("connect?"):
        return _parse_connect(rest[len(_CONNECT_PREFIX):])
    if _looks_like_base64(rest):
        return _parse_sealed(rest)
    return _parse_legacy(rest)


def _looks_like_base64(value: str) -> bool:
    return bool(value) and all(
        char.isspace() or char.isalnum() or char in "-_+/=" for char in value
    ) and not any(char in value for char in "?@:")


def _parse_sealed(value: str) -> ShareLink:
    compact = "".join(value.split()).replace("+", "-").replace("/", "_").rstrip("=")
    try:
        raw = base64.b64decode(
            compact + "=" * (-len(compact) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error):
        raise ValueError("Зашифрованная ссылка CSQTT повреждена или обрезана.") from None

    plain = None
    if len(raw) >= _NONCE_SIZE + 16:
        key = hashlib.sha256(_CIPHER_SEED).digest()
        try:
            plain = AESGCM(key).decrypt(raw[:_NONCE_SIZE], raw[_NONCE_SIZE:], None)
        except (InvalidTag, ValueError):
            plain = None

    # The 2.5.0 panel also emits this form if encryption was unavailable.
    if plain is None and raw.startswith(_CONNECT_PREFIX):
        plain = raw
    if plain is None or not plain.lower().startswith(_CONNECT_PREFIX):
        raise ValueError("Не удалось проверить ссылку CSQTT. Скопируйте её заново из панели сервера.")
    try:
        query = plain[len(_CONNECT_PREFIX):].decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Ссылка CSQTT содержит некорректные данные.") from None
    return _parse_connect(query)


def _decode_value(key: str, value: str) -> str:
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        raise ValueError(f"В ссылке повреждён параметр {key}. Скопируйте её заново.")
    try:
        return unquote(value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ValueError(f"В ссылке повреждён параметр {key}.") from None


def _parse_connect(query: str) -> ShareLink:
    query = query.replace("&amp;", "&")
    if not query:
        raise ValueError("В ссылке CSQTT отсутствуют параметры.")
    raw: dict[str, str] = {}
    for item in re.split(r"[&;]", query):
        if not item:
            continue
        key, separator, raw_value = item.partition("=")
        if not separator:
            continue
        key = _decode_value("имя параметра", key).lower()
        if key not in _KNOWN_KEYS:
            continue
        if key in raw:
            raise ValueError(f"Параметр {key} в ссылке повторяется.")
        raw[key] = raw_value

    decoded = {key: _decode_value(key, raw[key]) for key in ("v", "host", "peer", "password", "token") if key in raw}
    if decoded.get("v") != "2":
        raise ValueError("Поддерживается только версия ссылки CSQTT v=2.")
    host = decoded.get("host", "").strip()
    port_text = decoded.get("peer", "").strip()
    if not host or not port_text:
        raise ValueError("В ссылке CSQTT не указан адрес или порт сервера.")
    if "token" in raw and decoded.get("token"):
        raise ValueError("Ссылка содержит VK-токен сервера. Этот режим пока не поддерживается; запросите ссылку с хешами звонков.")
    password = decoded.get("password", "")
    if "password" in raw and not password:
        raise ValueError("В ссылке CSQTT указан пустой пароль.")
    if any(char.isspace() for char in password) or "|" in password:
        raise ValueError("Пароль в ссылке CSQTT содержит недопустимые символы.")
    if "token" in raw and not decoded.get("token"):
        raise ValueError("В ссылке CSQTT указан пустой VK-токен.")

    server = _format_server(host, port_text)
    hashes: list[str] = []
    if "hashes" in raw:
        if raw["hashes"] == "":
            raise ValueError("В ссылке CSQTT указан пустой список звонков.")
        for item in raw["hashes"].split("+"):
            decoded_hash = _decode_value("hashes", item)
            if any(char.isspace() for char in decoded_hash):
                raise ValueError("Хеш звонка в ссылке CSQTT содержит пробел.")
            for candidate in normalize_hashes(decoded_hash):
                if len(candidate) < 16:
                    raise ValueError("Хеш звонка в ссылке CSQTT слишком короткий.")
                if candidate not in hashes:
                    hashes.append(candidate)
        if not hashes:
            raise ValueError("В ссылке CSQTT не удалось найти хеши звонков.")
        if len(hashes) > 6:
            raise ValueError("В ссылке больше шести звонков VK; поддерживается максимум шесть.")
    return ShareLink(server=server, password=password, hashes=tuple(hashes))


def _parse_legacy(rest: str) -> ShareLink:
    rest = rest.removesuffix("/")
    if "@" not in rest or any(char in rest for char in "/?#"):
        raise ValueError("Неизвестный формат ссылки. Используйте ссылку csqtt:// из панели сервера.")
    encoded_password, endpoint = rest.rsplit("@", 1)
    password = _decode_value("password", encoded_password)
    if not password or any(char.isspace() for char in password) or "|" in password:
        raise ValueError("В старой ссылке CSQTT отсутствует корректный пароль.")
    if endpoint.startswith("["):
        closing = endpoint.find("]")
        if closing < 0 or endpoint[closing + 1:closing + 2] != ":":
            raise ValueError("В ссылке CSQTT неверно указан адрес IPv6.")
        host, port = endpoint[1:closing], endpoint[closing + 2:]
    else:
        host, separator, port = endpoint.rpartition(":")
        if not separator:
            raise ValueError("В ссылке CSQTT не указан порт сервера.")
    return ShareLink(server=_format_server(host, port), password=password, hashes=())


def _format_server(host: str, port_text: str) -> str:
    host = host.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        port = int(port_text, 10)
    except ValueError:
        raise ValueError("В ссылке CSQTT неверный порт сервера.") from None
    if not host or not 1 <= port <= 65535:
        raise ValueError("В ссылке CSQTT неверный адрес или порт сервера.")
    if any(char.isspace() or char in "/\\@?#" for char in host):
        raise ValueError("В ссылке CSQTT неверный адрес сервера.")
    try:
        address = ipaddress.ip_address(host)
        if address.version == 6:
            return f"[{address.compressed}]:{port}"
        return f"{address.compressed}:{port}"
    except ValueError:
        if ":" in host or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            raise ValueError("В ссылке CSQTT неверный адрес сервера.") from None
        if host.startswith(".") or host.endswith(".") or ".." in host:
            raise ValueError("В ссылке CSQTT неверный адрес сервера.")
        return f"{host}:{port}"
