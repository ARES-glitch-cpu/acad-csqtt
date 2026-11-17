"""Corporate HTTP CONNECT proxy probe."""
import base64
import ipaddress
import socket

from csqtt_client.models.profile import split_address


def proxy_connect(profile, target):
    host, port = split_address(profile.proxy)
    ipaddress.ip_address(host)
    auth = ""
    if profile.proxy_user:
        token = base64.b64encode(f"{profile.proxy_user}:{profile.proxy_password}".encode()).decode()
        auth = f"Proxy-Authorization: Basic {token}\r\n"
    with socket.create_connection((host, port), timeout=12) as conn:
        conn.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n{auth}\r\n".encode())
        header = bytearray()
        while not header.endswith(b"\r\n\r\n"):
            value = conn.recv(1)
            if not value or len(header) >= 16384:
                raise ValueError("Прокси закрыл соединение или прислал неверный ответ.")
            header.extend(value)
        status = header.split(b"\r\n", 1)[0].split()
        if len(status) < 2 or status[1] != b"200":
            code = status[1].decode("ascii", "replace") if len(status) > 1 else "?"
            raise ValueError({"407": "Прокси: ошибка авторизации 407. Нужен HTTP Basic; NTLM/Kerberos пока не поддерживаются.",
                              "403": "Прокси запретил CONNECT 403: проверьте разрешённый TURN-хост и порт 443."}.get(code, f"Прокси вернул HTTP {code}."))
