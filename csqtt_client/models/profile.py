"""Connection settings and validation, independent of the desktop UI."""
from dataclasses import dataclass
import ipaddress
import re


@dataclass
class Profile:
    server: str = ""
    password: str = ""
    hashes: str = ""
    proxy: str = "10.0.0.1:3128"
    proxy_user: str = ""
    proxy_password: str = ""
    socks_port: str = "1080"
    http_port: str = "8080"
    workers: str = "6"
    turn: str = ""
    obfs: str = "unified"
    srtp: str = "auto"
    generation: str = "0"
    salt: str = ""
    mode: str = "proxy"
    internet_mode: str = "direct"
    # Keep new fields at the end to preserve the historical positional signature.
    share_link: str = ""
    client_password: str = ""
    dns_override: str = ""
    config_file: str = ""
    auto_load_config: str = "0"
    turn_transport: str = "auto"
    domain_routing_enabled: str = "0"
    domain_is_whitelist: str = "0"
    exclude_ru_zones: str = "0"
    template_domains: str = "0"
    direct_domains: str = ""
    ip_routing_enabled: str = "0"
    ip_is_whitelist: str = "0"
    direct_ips: str = ""
    panel_url: str = ""
    fingerprint: str = "chrome"
    captcha_mode: str = "auto"
    client_ids: str = "8202606,6287487"
    custom_turn_ips: str = ""
    turn_subnet: str = ""
    turn_ip_limit: str = "ALL"

    def validate(self):
        host, port = split_address(self.server)
        if not host or not 1 <= port <= 65535:
            raise ValueError("Сервер csqtt: укажите IP или домен и порт, например 203.0.113.10:443.")
        if not self.password:
            raise ValueError("Введите пароль пользователя сервера csqtt.")
        hashes = normalize_hashes(self.hashes)
        if not 1 <= len(hashes) <= 6:
            raise ValueError("Нужно от 1 до 6 хешей VK или ссылок /call/join/.")
        if self.internet_mode not in ("direct", "proxy"):
            raise ValueError("Выберите прямое подключение или HTTP-прокси.")
        if self.internet_mode == "proxy":
            phost, pport = split_address(self.proxy)
            proxy_address = ipaddress.ip_address(phost)
            if self.mode == "tun" and not isinstance(proxy_address, ipaddress.IPv4Address):
                raise ValueError("Для режима TUN укажите IPv4-адрес корпоративного HTTP-прокси.")
            if not 1 <= pport <= 65535:
                raise ValueError("Проверьте порт корпоративного прокси.")
            if self.proxy_user and not self.proxy_password:
                raise ValueError("Введите пароль корпоративного прокси.")
            if ":" in self.proxy_user or any(c in self.proxy_user + self.proxy_password for c in "\r\n"):
                raise ValueError("Логин/пароль прокси содержат недопустимые символы.")
        if self.turn and (":" in self.turn or "/" in self.turn or any(c.isspace() for c in self.turn)):
            raise ValueError("TURN: только IPv4 или имя хоста без схемы и порта. Порт фиксирован: 443.")
        ports = [int(self.socks_port), int(self.http_port)]
        if any(not 1024 <= p <= 65535 for p in ports) or ports[0] == ports[1]:
            raise ValueError("Локальные порты: разные числа от 1024 до 65535.")
        if not 1 <= int(self.workers) <= 100:
            raise ValueError("Число потоков: от 1 до 100.")
        if not 0 <= int(self.generation) < 2**64:
            raise ValueError("Поколение: целое неотрицательное число.")
        if self.dns_override.strip():
            try:
                ipaddress.ip_address(self.dns_override.strip())
            except ValueError:
                raise ValueError("Пользовательский DNS должен быть IP-адресом, например 1.1.1.1 или 9.9.9.9.")
        if self.auto_load_config not in ("0", "1"):
            raise ValueError("Флаг автозагрузки конфигурации некорректен.")
        if self.panel_url.strip():
            from urllib.parse import urlsplit
            parsed = urlsplit(self.panel_url.strip())
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError("Ссылка веб-панели должна иметь вид https://домен/путь без логина и пароля.")
        if self.mode not in ("proxy", "tun"):
            raise ValueError("Режим подключения должен быть proxy или tun.")
        if self.obfs not in ("unified", "audio", "video") or self.srtp not in ("auto", "wrap", "dtls"):
            raise ValueError("Неверный режим протокола.")
        if self.turn_transport not in ("auto", "udp", "tcp"):
            raise ValueError("Транспорт TURN должен быть Авто, UDP или TCP.")
        if self.fingerprint not in ("chrome", "firefox", "edge", "opera", "safari"):
            raise ValueError("Неизвестный TLS-отпечаток браузера.")
        if self.captcha_mode not in ("auto", "wv", "rjs"):
            raise ValueError("Метод обработки капчи должен быть Авто, WebView или Rust JS.")
        if not self.client_ids.strip() or any(not item.strip().isdigit() for item in self.client_ids.split(",")):
            raise ValueError("Client IDs должны содержать числовые идентификаторы через запятую.")
        from csqtt_client.models.turn_subnets import subnet_titles, TURN_IP_LIMITS
        if self.turn_subnet and self.turn_subnet not in subnet_titles():
            raise ValueError("Выберите TURN-подсеть из списка или оставьте автоматический выбор VK.")
        if self.turn_ip_limit not in TURN_IP_LIMITS:
            raise ValueError("Количество TURN-IP должно быть: Все, 1, 2, 4 или 9.")
        if self.custom_turn_ips.strip():
            for endpoint in re.split(r"[,;\s]+", self.custom_turn_ips.strip()):
                endpoint = endpoint.strip()
                if not endpoint:
                    continue
                if endpoint.startswith("[") and "]:" in endpoint:
                    host, port = endpoint[1:].split("]:", 1)
                    ipaddress.IPv6Address(host)
                    if not 1 <= int(port) <= 65535:
                        raise ValueError(f"Некорректный TURN-порт: {port}")
                elif endpoint.count(":") == 1:
                    host, port = endpoint.rsplit(":", 1)
                    try:
                        ipaddress.ip_address(host)
                    except ValueError:
                        if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
                            raise ValueError(f"Некорректный TURN-адрес: {endpoint}") from None
                    if not 1 <= int(port) <= 65535:
                        raise ValueError(f"Некорректный TURN-порт: {port}")
                else:
                    try:
                        ipaddress.ip_address(endpoint)
                    except ValueError:
                        if not re.fullmatch(r"[A-Za-z0-9.-]+", endpoint):
                            raise ValueError(f"Некорректный TURN-адрес: {endpoint}") from None
        if self.internet_mode == "proxy" and self.turn_transport == "udp":
            raise ValueError("При корпоративном HTTP-прокси UDP недоступен. Выберите Авто или TCP.")
        for key in ("domain_routing_enabled", "domain_is_whitelist", "exclude_ru_zones",
                    "template_domains", "ip_routing_enabled", "ip_is_whitelist"):
            if getattr(self, key) not in ("0", "1"):
                raise ValueError("Параметры маршрутизации имеют неверный формат.")
        domains = [item for item in re.split(r"[\s,;]+", self.direct_domains.strip()) if item]
        if self.domain_routing_enabled == "1" and not domains and self.exclude_ru_zones != "1" and self.template_domains != "1":
            raise ValueError("Включена маршрутизация доменов, но список доменов пуст.")
        for domain in domains:
            candidate = domain.strip().lower()
            if candidate.startswith(("http://", "https://")):
                candidate = candidate.split("://", 1)[1]
            candidate = candidate.split("/", 1)[0].split(":", 1)[0].strip(".")
            if not candidate or len(candidate) > 253 or not re.fullmatch(r"[a-z0-9.-]+", candidate):
                raise ValueError(f"Некорректный домен в списке маршрутизации: {domain}")
            if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                   for label in candidate.split(".")):
                raise ValueError(f"Некорректный домен в списке маршрутизации: {domain}")
        ip_tokens = [item for item in re.split(r"[\s,;]+", self.direct_ips.strip()) if item]
        if self.ip_routing_enabled == "1" and not ip_tokens:
            raise ValueError("Включена маршрутизация IP, но список адресов пуст.")
        for token in ip_tokens:
            try:
                if "/" in token:
                    ipaddress.IPv4Network(token, strict=False)
                elif "-" in token:
                    first, last = token.split("-", 1)
                    if int(ipaddress.IPv4Address(first)) > int(ipaddress.IPv4Address(last)):
                        raise ValueError
                else:
                    ipaddress.IPv4Address(token)
            except ValueError:
                raise ValueError(f"Некорректное IPv4-правило: {token}. Используйте IP, CIDR или диапазон.") from None
        return hashes


def split_address(value):
    host, port = value.strip().rsplit(":", 1)
    if any(c.isspace() for c in host) or any(c in host for c in "/@?#"):
        raise ValueError("Адрес должен иметь вид IP:порт или домен:порт.")
    return host.strip("[]"), int(port)


def normalize_hashes(value):
    result = []
    for token in re.split(r"[\s,;]+", value.strip()):
        token = token.strip("<>\"'")
        if "/call/join/" in token:
            token = token.split("/call/join/", 1)[1]
        elif token.startswith(("http://", "https://")):
            raise ValueError("Ссылка VK должна содержать /call/join/.")
        token = re.split(r"[?#/]", token, maxsplit=1)[0]
        if token and token not in result:
            result.append(token)
    return result
