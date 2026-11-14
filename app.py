"""Small native Windows launcher for CSQTT + local SOCKS5/HTTP proxies."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
import http.client
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
PROFILE = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "CSQTT-Kolenka" / "profile.dat"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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

    def validate(self):
        host, port = split_address(self.server)
        if not host or not 1 <= port <= 65535:
            raise ValueError("Сервер csqtt: укажите IP или домен и порт, например 203.0.113.10:443.")
        phost, pport = split_address(self.proxy)
        ipaddress.ip_address(phost)
        if not 1 <= pport <= 65535:
            raise ValueError("Проверьте порт корпоративного прокси.")
        if not self.password:
            raise ValueError("Введите пароль пользователя сервера csqtt.")
        hashes = normalize_hashes(self.hashes)
        if not 1 <= len(hashes) <= 6:
            raise ValueError("Нужно от 1 до 6 хешей VK или ссылок /call/join/.")
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
        if self.obfs not in ("unified", "audio", "video") or self.srtp not in ("auto", "wrap", "dtls"):
            raise ValueError("Неверный режим протокола.")
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


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(value: bytes, decrypt=False):
    """Encrypt for the current Windows account; never write plaintext profiles."""
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
        ok = crypt.CryptProtectData(ctypes.byref(source), "CSQTT profile", None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def save_profile(profile):
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    temp = PROFILE.with_suffix(".tmp")
    temp.write_bytes(dpapi(json.dumps(asdict(profile), ensure_ascii=False).encode("utf-8")))
    temp.replace(PROFILE)


def load_profile():
    if not PROFILE.exists():
        return Profile()
    data = json.loads(dpapi(PROFILE.read_bytes(), decrypt=True))
    return Profile(**{k: v for k, v in data.items() if k in Profile.__dataclass_fields__})


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


def core_command(profile, packet_port):
    hashes = profile.validate()
    args = [str(ROOT / "bin" / "csqtt-core.exe"), "--peer", profile.server.strip(),
            "--listen", f"127.0.0.1:{packet_port}", "--vk", ",".join(hashes),
            "--workers", profile.workers, "--exact-workers", "--turn-transport", "tcp", "--port", "443",
            "--obfs", profile.obfs, "--srtp-mode", profile.srtp, "--gen", profile.generation, "--salt", profile.salt]
    if profile.turn.strip():
        args += ["--turn", profile.turn.strip()]
    env = os.environ.copy()
    # Ignore inherited bypasses and proxy credentials. The core uses this explicit proxy.
    for key in list(env):
        if key.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            del env[key]
    env.update(CSQTT_PASSWORD=profile.password, CSQTT_HTTP_PROXY=profile.proxy.strip(),
               CSQTT_PROXY_USER=profile.proxy_user, CSQTT_PROXY_PASSWORD=profile.proxy_password,
               CSQTT_EVENTS="1")
    return args, env


class App:
    def __init__(self, root):
        self.root = root
        root.title("CSQTT — коленка / TCP")
        root.geometry("790x860")
        root.minsize(700, 760)
        self.events = queue.Queue()
        self.core = self.helper = None
        self.session = 0
        self.ready = False
        self.config = None
        self.running_profile = None
        self.secrets = []
        self.closing = False
        try:
            profile = load_profile()
        except Exception:
            profile = Profile()
        self.vars = {k: tk.StringVar(value=str(v)) for k, v in asdict(profile).items()}
        self.remember = tk.BooleanVar(value=PROFILE.exists())
        self.status = tk.StringVar(value="Отключено")
        self.stats = tk.StringVar(value="SOCKS5 127.0.0.1:1080 · HTTP 127.0.0.1:8080")
        outer = ttk.Frame(root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="CSQTT / TCP через корпоративный прокси", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Без TUN и прав администратора. Все внешние соединения — через HTTP CONNECT.").pack(anchor="w", pady=(5, 12))
        server = ttk.LabelFrame(outer, text="Сервер csqtt", padding=10)
        server.pack(fill="x")
        self.field(server, "Сервер IP:порт", "server", 0)
        self.field(server, "Пароль csqtt", "password", 1, secret=True)
        ttk.Label(server, text="Хеши VK / ссылки звонков\nпо одному на строку (до 6)").grid(row=2, column=0, sticky="nw", pady=5)
        self.hashes = tk.Text(server, height=3, width=44, font=("Consolas", 10), wrap="word")
        self.hashes.grid(row=2, column=1, sticky="ew", pady=5)
        self.hashes.insert("1.0", profile.hashes)
        proxy = ttk.LabelFrame(outer, text="Корпоративный HTTP-прокси · авторизация Basic", padding=10)
        proxy.pack(fill="x", pady=10)
        self.field(proxy, "Адрес IP:порт", "proxy", 0)
        self.field(proxy, "Логин", "proxy_user", 1)
        self.field(proxy, "Пароль прокси", "proxy_password", 2, secret=True)
        self.check_proxy_button = ttk.Button(proxy, text="Проверить CONNECT :443", command=self.check_proxy)
        self.check_proxy_button.grid(row=3, column=1, sticky="w", pady=4)
        advanced = ttk.LabelFrame(outer, text="Параметры (обычно можно оставить как есть)", padding=10)
        advanced.pack(fill="x")
        self.field(advanced, "TURN-хост (необязательно)", "turn", 0)
        self.field(advanced, "Потоки / workers", "workers", 1)
        row = ttk.Frame(advanced)
        row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        for label, name, values in [("Обфускация", "obfs", ("unified", "audio", "video")), ("SRTP", "srtp", ("auto", "wrap", "dtls"))]:
            ttk.Label(row, text=label).pack(side="left", padx=(0, 7))
            ttk.Combobox(row, textvariable=self.vars[name], values=values, state="readonly", width=12).pack(side="left", padx=(0, 20))
        ports = ttk.Frame(advanced)
        ports.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        for label, name in [("SOCKS5 порт", "socks_port"), ("HTTP порт", "http_port"), ("Поколение", "generation")]:
            ttk.Label(ports, text=label).pack(side="left", padx=(0, 5))
            ttk.Entry(ports, textvariable=self.vars[name], width=7).pack(side="left", padx=(0, 15))
        self.field(advanced, "Salt (если выдан сервером)", "salt", 4, secret=True)
        ttk.Checkbutton(outer, text="Запомнить профиль (шифрование Windows DPAPI для текущего пользователя)", variable=self.remember).pack(anchor="w", pady=8)
        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="Подключить", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="Отключить", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        self.test_button = ttk.Button(actions, text="Проверить интернет / IP", command=self.check_internet, state="disabled")
        self.test_button.pack(side="left")
        ttk.Label(outer, textvariable=self.status, font=("Segoe UI", 11, "bold"), wraplength=740).pack(anchor="w", pady=(12, 3))
        ttk.Label(outer, textvariable=self.stats).pack(anchor="w", pady=(0, 8))
        self.log = tk.Text(outer, height=7, state="disabled", font=("Consolas", 9), wrap="word")
        self.log.pack(fill="both", expand=True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def field(self, frame, label, key, row, secret=False):
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=label, width=29).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.vars[key], show="•" if secret else "").grid(row=row, column=1, sticky="ew", pady=4)

    def profile(self):
        return Profile(**{**{k: v.get() for k, v in self.vars.items()}, "hashes": self.hashes.get("1.0", "end").strip()})

    def append(self, message):
        # Core messages can contain partial hashes; mask these as well as passwords.
        for value in self.secrets:
            if value:
                message = message.replace(value, "[скрыто]")
        message = re.sub(r"(?i)(access_token|client_secret|password|secret)=([^\s&]+)", r"\1=[скрыто]", message)
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S ") + message.rstrip() + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 450:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def background(self, function):
        threading.Thread(target=function, daemon=True).start()

    def check_proxy(self):
        profile = self.profile()
        self.check_proxy_button.configure(state="disabled")
        def work():
            try:
                target = f"{profile.turn.strip() or 'dns.google'}:443"
                proxy_connect(profile, target)
                self.events.put(("message", f"CONNECT {target}: успешно. Это проверка прокси, доступность csqtt проверяется при подключении."))
            except Exception as error:
                self.events.put(("message", str(error)))
            finally:
                self.events.put(("proxy_checked", None))
        self.background(work)

    def start(self):
        try:
            profile = self.profile()
            hashes = profile.validate()
            if not (ROOT / "bin" / "csqtt-core.exe").exists() or not (ROOT / "bin" / "packet-proxy.exe").exists():
                raise ValueError("Не найдены bin/csqtt-core.exe и bin/packet-proxy.exe. Распакуйте portable целиком.")
            # Check listener conflicts before establishing a tunnel.
            for port in (profile.socks_port, profile.http_port):
                with socket.socket() as check:
                    check.bind(("127.0.0.1", int(port)))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as check:
                check.bind(("127.0.0.1", 0))
                self.packet_port = check.getsockname()[1]
            args, env = core_command(profile, self.packet_port)
            if self.remember.get():
                save_profile(profile)
            elif PROFILE.exists():
                PROFILE.unlink()
            self.session += 1
            self.ready = False
            self.config = None
            self.running_profile = profile
            self.secrets = sorted([profile.password, profile.proxy_password, profile.salt, *hashes, *(h[:8] for h in hashes)], key=len, reverse=True)
            self.core = subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            self.read_process(self.core, "core", self.session)
            self.status.set("Подключение: получаю TURN-сессию и конфигурацию сервера…")
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.append("Запущено ядро: TCP через HTTP CONNECT, TURN :443, без прямого выхода.")
        except Exception as error:
            messagebox.showerror("Не удалось начать подключение", str(error))

    def read_process(self, process, kind, session):
        def read():
            for line in process.stdout:
                self.events.put(("process", (session, kind, line.rstrip())))
            self.events.put(("exit", (session, kind, process.wait())))
        self.background(read)

    def start_helper(self):
        if self.helper or not self.ready or not self.config:
            return
        profile = self.running_profile
        ip, dns = self.config
        args = [str(ROOT / "bin" / "packet-proxy.exe"), "--core", f"127.0.0.1:{self.packet_port}",
                "--ip", ip, "--dns", dns, "--socks", f"127.0.0.1:{profile.socks_port}", "--http", f"127.0.0.1:{profile.http_port}"]
        try:
            self.helper = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            self.read_process(self.helper, "helper", self.session)
        except Exception as error:
            self.append(f"Не запущен локальный прокси: {error}")
            self.stop()

    def process_line(self, kind, line):
        if kind == "helper" and line.startswith("PROXY_READY"):
            self.status.set("Туннель готов, локальные прокси запущены. Проверяю интернет…")
            self.test_button.configure(state="normal")
            self.check_internet()
        if line.startswith("__CSQTT_EVENT__|"):
            try:
                _, name, data = line.split("|", 2)
                payload = json.loads(data)
                if name == "CONFIG":
                    fields = payload["config"].split(":")
                    if fields[0] != "TUNCONF" or len(fields) < 3:
                        raise ValueError("Сервер не выдал конфигурацию TUNCONF.")
                    ipaddress.IPv4Address(fields[1])
                    config = (fields[1], fields[2])
                    if self.config and self.config != config:
                        self.append("Сервер изменил IP/DNS: переподключите клиент.")
                        self.stop()
                        return
                    self.config = config
                elif name == "READY":
                    self.ready = True
                elif name == "STATS":
                    self.stats.set(f"Активных потоков: {payload.get('active', 0)} · ↑ {payload.get('bytes_up', 0)/1048576:.2f} МБ · ↓ {payload.get('bytes_down', 0)/1048576:.2f} МБ")
                elif name in ("ACTIVE_ZERO", "SERVER_RESTART", "NETWORK_SUSPECT"):
                    self.status.set("Связь с сервером потеряна; ядро пытается восстановить туннель…")
                elif name == "ERROR":
                    self.append(str(payload.get("message", payload)))
                self.start_helper()
            except (ValueError, KeyError) as error:
                self.append(f"Ошибка события ядра: {error}")
            return
        self.append(line)

    def check_internet(self):
        if not self.helper or not self.running_profile:
            return
        profile, session = self.running_profile, self.session
        self.test_button.configure(state="disabled")
        def work():
            conn = None
            try:
                # Explicit CONNECT to the LOCAL proxy, unaffected by proxy environment variables.
                conn = http.client.HTTPSConnection("127.0.0.1", int(profile.http_port), timeout=25, context=ssl.create_default_context())
                conn.set_tunnel("api.ipify.org", 443)
                conn.request("GET", "/", headers={"Host": "api.ipify.org", "Connection": "close"})
                response = conn.getresponse()
                if response.status != 200:
                    raise ValueError(f"Проверка IP вернула HTTP {response.status}")
                address = str(ipaddress.ip_address(response.read(128).decode().strip()))
                result = f"Интернет через csqtt работает. Внешний IP: {address}"
            except Exception:
                result = "Локальные прокси запущены, но интернет не подтверждён. Проверьте журнал и параметры сервера."
            finally:
                if conn:
                    conn.close()
                self.events.put(("internet", (session, result)))
        self.background(work)

    def stop(self):
        self.session += 1
        processes = [p for p in (self.helper, self.core) if p]
        self.helper = self.core = None
        for process in processes:
            if process.stdin:
                try:
                    process.stdin.write("STOP\n")
                    process.stdin.flush()
                except (OSError, ValueError):
                    pass
        def cleanup():
            for process in processes:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if process.stdin:
                    process.stdin.close()
                if process.stdout:
                    process.stdout.close()
            self.events.put(("cleaned", None))
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.test_button.configure(state="disabled")
        self.status.set("Отключение…")
        # Keep cleanup alive if the window closes while STOP is pending.
        threading.Thread(target=cleanup, daemon=False).start()

    def close(self):
        self.closing = True
        self.stop()

    def poll(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "process":
                session, source, line = value
                if session == self.session:
                    self.process_line(source, line)
            elif kind == "exit":
                session, source, code = value
                if session == self.session:
                    self.append(f"{source}: процесс завершился (код {code}).")
                    self.stop()
            elif kind == "message":
                self.append(value)
            elif kind == "proxy_checked":
                self.check_proxy_button.configure(state="normal")
            elif kind == "internet":
                session, result = value
                if session == self.session:
                    self.status.set(result)
                    self.append(result)
                    self.test_button.configure(state="normal")
            elif kind == "cleaned":
                if self.closing:
                    self.root.destroy()
                    return
                self.status.set("Отключено")
                self.start_button.configure(state="normal")
        self.root.after(100, self.poll)


def main():
    root = tk.Tk()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    ttk.Style().theme_use("vista" if sys.platform == "win32" else "clam")
    App(root)
    if "--smoke" in sys.argv:
        root.after(700, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
