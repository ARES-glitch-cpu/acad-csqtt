"""Import administrator connection profiles from a UTF-8 TXT file."""
from __future__ import annotations

import re

from csqtt_client.models.profile import normalize_hashes


def parse_admin_txt(content: str) -> dict[str, str]:
    """Parse key=value records. Repeated call/hash entries are supported."""
    values: dict[str, list[str]] = {}
    aliases = {
        "server": "server", "server_address": "server", "server_addr": "server",
        "peer": "server", "host": "server_host", "server_host": "server_host",
        "server_ip": "server_host", "server_port": "server_port",
        "server_password": "password", "csqtt_password": "password", "password": "password",
        "proxy": "proxy", "proxy_address": "proxy", "proxy_addr": "proxy",
        "proxy_host": "proxy_host", "proxy_port": "proxy_port",
        "proxy_user": "proxy_user", "proxy_login": "proxy_user",
        "username": "proxy_user", "login": "proxy_user",
        "proxy_password": "proxy_password",
        "internet_mode": "internet_mode", "access_mode": "internet_mode",
        "call": "call", "call_url": "call", "call_link": "call",
        "vk_call": "call", "hash": "call", "vk_hash": "call",
        "hashes": "hashes", "vk_hashes": "hashes", "calls": "hashes",
    }

    for line_number, original in enumerate((content or "").splitlines(), 1):
        line = original.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        if "=" not in line:
            raise ValueError(f"Строка {line_number}: ожидается запись key=value.")
        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip().lower().replace("-", "_").replace(" ", "_")
        canonical = aliases.get(key)
        if canonical is None:
            raise ValueError(f"Строка {line_number}: неизвестный параметр «{raw_key.strip()}».")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values.setdefault(canonical, []).append(value)

    def single(key: str) -> str:
        items = values.get(key, [])
        if not items:
            return ""
        if len(items) > 1:
            raise ValueError(f"Параметр {key} указан несколько раз.")
        return items[0]

    result: dict[str, str] = {}
    server = single("server")
    server_host = single("server_host")
    server_port = single("server_port")
    if server and (server_host or server_port):
        raise ValueError("Укажите сервер либо одной строкой server=host:port, либо через server_host и server_port.")
    if not server and (server_host or server_port):
        if not server_host or not server_port:
            raise ValueError("Для сервера нужны оба параметра server_host и server_port.")
        host = server_host.strip("[]")
        server = f"[{host}]:{server_port}" if ":" in host else f"{host}:{server_port}"
    if server:
        result["server"] = server
    password = single("password")
    if password:
        result["password"] = password

    proxy = single("proxy")
    proxy_host = single("proxy_host")
    proxy_port = single("proxy_port")
    if proxy and (proxy_host or proxy_port):
        raise ValueError("Укажите прокси либо proxy=host:port, либо через proxy_host и proxy_port.")
    if not proxy and (proxy_host or proxy_port):
        if not proxy_host or not proxy_port:
            raise ValueError("Для прокси нужны оба параметра proxy_host и proxy_port.")
        proxy = f"{proxy_host}:{proxy_port}"
    if proxy:
        result["proxy"] = proxy
        result["internet_mode"] = "proxy"

    proxy_user = single("proxy_user")
    proxy_password = single("proxy_password")
    if proxy_user:
        result["proxy_user"] = proxy_user
    if proxy_password:
        result["proxy_password"] = proxy_password

    if "internet_mode" in values:
        result["internet_mode"] = single("internet_mode").lower()
    elif not proxy:
        result["internet_mode"] = "direct"

    hashes: list[str] = []
    for record in values.get("call", []) + values.get("hashes", []):
        # normalize_hashes understands URL forms and simple separators.
        for item in normalize_hashes(record):
            if item not in hashes:
                hashes.append(item)
    if hashes:
        if len(hashes) > 6:
            raise ValueError("В TXT-файле больше шести ссылок/хешей звонков VK.")
        result["hashes"] = "\n".join(hashes)
    return result
